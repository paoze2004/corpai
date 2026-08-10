"""飞书事件订阅统一入口 /feishu/event 测试 — 验证 HTTP 行为。

覆盖:
- URL 验证 challenge
- 卡片 approve 触发 ApprovalService
- 卡片 reject 触发 ApprovalService
- 缺少 plan_id/token 返错误
- 其它事件 ack 不处理

为什么这个测试重要:飞书后台配 URL 时第一次发 GET 验证,
配完订阅后发 POST card.action.trigger,两者都在这里验证。
"""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("AUTH_JWT_SECRET", "dev-secret")
os.environ.setdefault("API_KEY", "test-api-key")

# mock 掉 chat_service 构造(LLM 客户端需要真凭证,本测试不依赖聊天功能)
with patch("CorpAI.api.app.build_default_service") as _mock_svc, \
     patch("CorpAI.api.app.discover_all", return_value=None):
    from fastapi.testclient import TestClient

    from CorpAI.api.app import app


class TestFeishuEventEndpoint(unittest.TestCase):
    """POST /feishu/event 路由测试。"""

    def setUp(self):
        # 导入会触发 chat_service = build_default_service() — 需 mock 掉
        # 因为我们不测聊天,只测 webhook 路由
        self.client = TestClient(app)

    def test_url_verification_challenge(self):
        """飞书 GET/POST URL 验证 → 原样返回 challenge 字段。"""
        challenge = "test-challenge-abc123"
        resp = self.client.post(
            "/feishu/event",
            json={"challenge": challenge},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"challenge": challenge})

    def test_card_action_trigger_approve(self):
        """card.action.trigger 事件 → 调 ApprovalService.approve。"""
        body = {
            "type": "card_action_trigger",
            "action": {
                "value": {"plan_id": 1, "token": "tok_abc", "op": "approve"},
            },
            "operator": {"open_id": "ou_alice"},
        }
        with patch("CorpAI.api.app.handle_approve_callback") as mock_approve:
            mock_approve.return_value = {
                "status": "approved", "plan_id": 1, "result": {"ok": True},
            }
            resp = self.client.post(
                "/feishu/event",
                json=body,
            )
        self.assertEqual(resp.status_code, 200)
        mock_approve.assert_called_once_with(
            plan_id=1, token="tok_abc",
            actor="ou_alice", scopes=["sre:approve"],
        )

    def test_card_action_trigger_reject(self):
        """card.action.trigger + op=reject → 调 handle_reject_callback。"""
        body = {
            "type": "card_action_trigger",
            "action": {
                "value": {"plan_id": 2, "token": "tok_xyz", "op": "reject"},
            },
            "operator": {"user_id": "u_bob"},
        }
        with patch("CorpAI.api.app.handle_reject_callback") as mock_reject:
            mock_reject.return_value = {
                "status": "rejected", "plan_id": 2, "result": {"ok": True},
            }
            resp = self.client.post(
                "/feishu/event",
                json=body,
            )
        self.assertEqual(resp.status_code, 200)
        mock_reject.assert_called_once()
        _args, kwargs = mock_reject.call_args
        self.assertEqual(kwargs["plan_id"], 2)
        self.assertEqual(kwargs["token"], "tok_xyz")
        self.assertEqual(kwargs["actor"], "u_bob")

    def test_card_action_trigger_missing_value(self):
        """value 缺 plan_id/token → 返 code=-1,不动 ApprovalService。"""
        body = {
            "type": "card_action_trigger",
            "action": {"value": {"op": "approve"}},  # 没 plan_id/token
            "operator": {"open_id": "ou_x"},
        }
        with patch("CorpAI.api.app.handle_approve_callback") as mock_approve:
            resp = self.client.post("/feishu/event", json=body)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["code"], -1)
        mock_approve.assert_not_called()

    def test_unknown_event_acked(self):
        """未知事件类型 → 返 code=0(飞书要求 ack,不报错)。"""
        body = {"type": "im.message.receive_v1", "message": "hello"}
        resp = self.client.post("/feishu/event", json=body)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"code": 0, "msg": "ignored"})

    def test_signature_header_routes_through_verifier(self):
        """带 X-Lark-Signature → 走 verify_signature 校验。

        不设 FEISHU_ENCRYPT_KEY 时 verify_signature 总是返 True,
        所以这里只验证调用没崩,真生产环境需要 mock verify_signature
        验证失败路径(见 test_signature_invalid)。
        """
        os.environ["FEISHU_ENCRYPT_KEY"] = "test-key"
        try:
            body = {"challenge": "abc"}
            resp = self.client.post(
                "/feishu/event",
                json=body,
                headers={
                    "X-Lark-Signature": "fake-sig",
                    "X-Lark-Request-Timestamp": "1700000000",
                    "X-Lark-Request-Nonce": "nonce1",
                },
            )
            self.assertEqual(resp.status_code, 200)
        finally:
            os.environ.pop("FEISHU_ENCRYPT_KEY", None)

    def test_signature_invalid_when_key_set(self):
        """设了 ENCRYPT_KEY + 错签名 → 返 code=-1,不动后续逻辑。"""
        os.environ["FEISHU_ENCRYPT_KEY"] = "test-key"
        try:
            with patch(
                "CorpAI.api.app.verify_signature", return_value=False,
            ):
                body = {"type": "card_action_trigger",
                         "action": {"value": {"plan_id": 1, "token": "t", "op": "approve"}}}
                resp = self.client.post(
                    "/feishu/event",
                    json=body,
                    headers={
                        "X-Lark-Signature": "wrong-sig",
                        "X-Lark-Request-Timestamp": "1700000000",
                        "X-Lark-Request-Nonce": "n",
                    },
                )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"code": -1, "msg": "signature_invalid"})
        finally:
            os.environ.pop("FEISHU_ENCRYPT_KEY", None)


if __name__ == "__main__":
    unittest.main()
