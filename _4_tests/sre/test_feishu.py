"""飞书集成测试 — 不依赖真凭证,只验证本地逻辑。

覆盖:
- is_configured:凭证齐/缺
- build_incident_card:card 结构正确(必填 fields + 按钮 + risk emoji)
- send_approval_card:未配置时返 not_configured(不调 HTTP)
- verify_signature:HMAC 校验对/错
- handle_*_callback:走 ApprovalService(mock DB)
"""
import base64
import hashlib
import hmac
import os
import unittest
from unittest.mock import patch

# 故意设空凭证确保 not_configured 路径
os.environ.pop("FEISHU_APP_ID", None)
os.environ.pop("FEISHU_APP_SECRET", None)
os.environ.pop("FEISHU_VERIFY_TOKEN", None)
os.environ.pop("FEISHU_ENCRYPT_KEY", None)
os.environ.setdefault("AUTH_JWT_SECRET", "dev-secret")

from sre_copilot.feishu import (
    build_incident_card,
    handle_approve_callback,
    handle_reject_callback,
    is_configured,
    send_approval_card,
    verify_signature,
)


class TestConfigured(unittest.TestCase):
    def setUp(self):
        for k in ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_VERIFY_TOKEN"):
            os.environ.pop(k, None)

    def test_not_configured_when_env_empty(self):
        self.assertFalse(is_configured())

    def test_configured_when_all_env_set(self):
        os.environ["FEISHU_APP_ID"] = "cli_xxx"
        os.environ["FEISHU_APP_SECRET"] = "sec_xxx"
        os.environ["FEISHU_VERIFY_TOKEN"] = "verify_xxx"
        self.assertTrue(is_configured())


class TestBuildCard(unittest.TestCase):
    def test_card_structure(self):
        card = build_incident_card(
            incident_id="INC-2026-001",
            service="payment",
            severity="critical",
            plan_summary="重启 payment-api deployment",
            risk_level="high",
            plan_id=1,
            approval_token="t",
        )
        self.assertEqual(card["msg_type"], "interactive")
        c = card["card"]
        # header 含 severity emoji
        self.assertIn("🔴", c["header"]["title"]["content"])
        self.assertEqual(c["header"]["template"], "red")  # critical
        # body 4 fields + hr + plan + hr + actions + note
        self.assertGreater(len(c["elements"]), 4)
        # 找按钮
        actions = next(e for e in c["elements"] if e["tag"] == "action")
        self.assertEqual(len(actions["actions"]), 2)
        # approve 按钮 value 含 plan_id + token + op
        approve_btn = actions["actions"][0]
        self.assertEqual(approve_btn["value"]["plan_id"], 1)
        self.assertEqual(approve_btn["value"]["token"], "t")
        self.assertEqual(approve_btn["value"]["op"], "approve")
        # reject 同理
        reject_btn = actions["actions"][1]
        self.assertEqual(reject_btn["value"]["op"], "reject")
        # 不再含 url 字段(走事件订阅不走 url 跳转)
        self.assertNotIn("url", approve_btn)
        self.assertNotIn("url", reject_btn)

    def test_warning_severity(self):
        card = build_incident_card(
            incident_id="X", service="s", severity="warning",
            plan_summary="p", risk_level="medium",
            plan_id=1, approval_token="t",
        )
        self.assertIn("🟡", card["card"]["header"]["title"]["content"])
        self.assertEqual(card["card"]["header"]["template"], "orange")


class TestSendCard(unittest.TestCase):
    def test_not_configured_returns_status(self):
        # 没设 env
        os.environ.pop("FEISHU_APP_ID", None)
        result = send_approval_card(
            receive_id="chat_abc", receive_id_type="chat_id",
            incident_id="X", service="s", severity="critical",
            plan_summary="p", risk_level="low",
            plan_id=1, approval_token="t",
        )
        self.assertEqual(result["status"], "not_configured")
        self.assertIn("FEISHU_APP_ID", result["required_env"])


class TestVerifySignature(unittest.TestCase):
    def setUp(self):
        os.environ["FEISHU_ENCRYPT_KEY"] = "test-key"

    def tearDown(self):
        os.environ.pop("FEISHU_ENCRYPT_KEY", None)

    def test_correct_signature(self):
        ts, nonce, body = "1700000000", "abc123", '{"plan_id":1}'
        content = f"{ts}{nonce}{body}".encode()
        sig = base64.b64encode(
            hmac.new(b"test-key", content, hashlib.sha256).digest(),
        ).decode()
        self.assertTrue(verify_signature(ts, nonce, body, sig))

    def test_wrong_signature(self):
        self.assertFalse(verify_signature("ts", "n", "body", "bogus"))


class TestCallbacks(unittest.TestCase):
    """approve/reject callback 走 ApprovalService(mock 掉 DB)。"""

    def test_approve_delegates_to_service(self):
        fake_result = {"plan_id": 1, "status": "approved"}
        with patch("sre_copilot.feishu.ApprovalService") as MockSvc:
            MockSvc.return_value.approve.return_value = fake_result
            result = handle_approve_callback(
                plan_id=1, token="t", actor="bob",
                scopes=["sre:approve"],
            )
        self.assertEqual(result["status"], "approved")
        MockSvc.return_value.approve.assert_called_once()

    def test_approve_returns_rejected_on_token_mismatch(self):
        from _0_CorpAI._2_platform.sre.approval import TokenMismatch
        with patch("sre_copilot.feishu.ApprovalService") as MockSvc:
            MockSvc.return_value.approve.side_effect = TokenMismatch("nope")
            result = handle_approve_callback(
                plan_id=1, token="bad", actor="bob",
                scopes=["sre:approve"],
            )
        self.assertEqual(result["status"], "rejected")
        self.assertIn("nope", result["reason"])

    def test_reject_delegates(self):
        with patch("sre_copilot.feishu.ApprovalService") as MockSvc:
            MockSvc.return_value.reject.return_value = {"plan_id": 1, "status": "rejected"}
            result = handle_reject_callback(
                plan_id=1, token="t", actor="bob",
                scopes=["sre:approve"], reason="风险太大",
            )
        self.assertEqual(result["status"], "rejected")
        MockSvc.return_value.reject.assert_called_once()


if __name__ == "__main__":
    unittest.main()
