"""Approval Service 测试 — 用 Mock 避开真 DB,只验证业务逻辑。

覆盖:
- generate_token:UUIDv4 格式 + 不重复
- store_pending_plan:写 DB + 返回 (id, token)
- approve:happy path + 5 类错误(PlanNotFound/TokenMismatch/AlreadyDecided/InsufficientScope)
- reject:同 approve,但 status='rejected'
- 二次校验:无 sre:approve scope 直接拒
- 防复用:approve 后 token 已清,再 approve 二次应 TokenMismatch
"""
import unittest
from unittest.mock import MagicMock, patch

from CorpAI.platform.sre.approval import (
    REQUIRED_SCOPE,
    AlreadyDecided,
    ApprovalService,
    InsufficientScope,
    PlanNotFound,
    TokenMismatch,
)


def _make_cursor(fetchone_value=None, lastrowid=42):
    """构造 mock cursor + connection。"""
    cursor = MagicMock()
    cursor.fetchone.return_value = fetchone_value
    cursor.lastrowid = lastrowid
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def _fake_pool(conn):
    """构造 mock DatabasePool.get().get_conn()。"""
    pool = MagicMock()
    pool.get_conn.return_value = conn
    return pool


class TestGenerateToken(unittest.TestCase):
    def test_uuid_format(self):
        svc = ApprovalService()
        token = svc.generate_token()
        # UUIDv4 hex = 32 chars,无连字符
        self.assertEqual(len(token), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in token))

    def test_unique(self):
        svc = ApprovalService()
        tokens = {svc.generate_token() for _ in range(100)}
        self.assertEqual(len(tokens), 100)


class TestStorePendingPlan(unittest.TestCase):
    def test_returns_plan_id_and_token(self):
        conn, _ = _make_cursor(lastrowid=99)
        pool = _fake_pool(conn)

        with patch("CorpAI.platform.db.DatabasePool.get", return_value=pool):
            svc = ApprovalService()
            plan_id, token = svc.store_pending_plan(
                incident_id="INC-2026-001",
                plan_json='{"actions":[{"tool":"restart_deployment"}]}',
                risk_level="high",
            )

        self.assertEqual(plan_id, 99)
        self.assertEqual(len(token), 32)


class TestApprove(unittest.TestCase):
    def setUp(self):
        self.svc = ApprovalService()
        self.plan_row = {
            "id": 1,
            "status": "pending",
            "approval_token": "tok_aaa",
            "incident_id": "INC-2026-001",
            "plan_json": "{}",
            "risk_level": "high",
        }

    def _patch_pool(self, row, lastrowid=1):
        conn, _ = _make_cursor(fetchone_value=row, lastrowid=lastrowid)
        pool = _fake_pool(conn)
        return patch("CorpAI.platform.db.DatabasePool.get", return_value=pool)

    def test_happy_path(self):
        with self._patch_pool(self.plan_row):
            result = self.svc.approve(
                plan_id=1, token="tok_aaa",
                actor="bob_hr", scopes=[REQUIRED_SCOPE],
            )
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["approved_by"], "bob_hr")

    def test_plan_not_found(self):
        with self._patch_pool(None), self.assertRaises(PlanNotFound):
            self.svc.approve(
                plan_id=999, token="x",
                actor="bob", scopes=[REQUIRED_SCOPE],
            )

    def test_token_mismatch(self):
        with self._patch_pool(self.plan_row), self.assertRaises(TokenMismatch):
            self.svc.approve(
                plan_id=1, token="wrong_token",
                actor="bob", scopes=[REQUIRED_SCOPE],
            )

    def test_empty_token(self):
        """已被用过的 plan(token 已清空)再 approve 应 TokenMismatch。"""
        self.plan_row["approval_token"] = ""
        with self._patch_pool(self.plan_row), self.assertRaises(TokenMismatch):
            self.svc.approve(
                plan_id=1, token="tok_aaa",
                actor="bob", scopes=[REQUIRED_SCOPE],
            )

    def test_already_decided(self):
        """已 approved 的 plan 再 approve 应 AlreadyDecided。"""
        self.plan_row["status"] = "approved"
        with self._patch_pool(self.plan_row), self.assertRaises(AlreadyDecided):
            self.svc.approve(
                plan_id=1, token="tok_aaa",
                actor="bob", scopes=[REQUIRED_SCOPE],
            )

    def test_insufficient_scope(self):
        """无 sre:approve scope → 二次校验拒,不动 DB。"""
        with self.assertRaises(InsufficientScope):
            self.svc.approve(
                plan_id=1, token="tok_aaa",
                actor="bob", scopes=["hr:write"],  # 不是 sre:approve
            )


class TestReject(unittest.TestCase):
    def setUp(self):
        self.svc = ApprovalService()
        self.plan_row = {
            "id": 1,
            "status": "pending",
            "approval_token": "tok_aaa",
            "incident_id": "INC-2026-002",
            "plan_json": "{}",
        }

    def test_happy_path(self):
        conn, cursor = _make_cursor(fetchone_value=self.plan_row)
        pool = _fake_pool(conn)

        with patch("CorpAI.platform.db.DatabasePool.get", return_value=pool):
            result = self.svc.reject(
                plan_id=1, token="tok_aaa",
                actor="bob_hr", scopes=[REQUIRED_SCOPE],
                reason="风险太高",
            )
        self.assertEqual(result["status"], "rejected")
        # 找 UPDATE statement,确认 reason 写入 error_message
        update_call = None
        for call in cursor.execute.call_args_list:
            sql = call.args[0]
            if "UPDATE sre_action_plans SET status='rejected'" in sql:
                update_call = call
                break
        self.assertIsNotNone(update_call, "没找到 UPDATE statement")
        # SQL 参数顺序: (actor, error_message, plan_id)
        self.assertEqual(update_call.args[1][1], "rejected:风险太高")

    def test_reject_requires_scope(self):
        with self.assertRaises(InsufficientScope):
            self.svc.reject(
                plan_id=1, token="tok_aaa",
                actor="bob", scopes=[],
                reason="x",
            )

    def test_reject_token_mismatch(self):
        conn, _ = _make_cursor(fetchone_value=self.plan_row)
        pool = _fake_pool(conn)
        with (
            patch("CorpAI.platform.db.DatabasePool.get", return_value=pool),
            self.assertRaises(TokenMismatch),
        ):
            self.svc.reject(
                plan_id=1, token="wrong",
                actor="bob", scopes=[REQUIRED_SCOPE],
                reason="x",
            )


class TestIdempotency(unittest.TestCase):
    """approve 一次性:成功后 token 清空,二次 approve 应失败。"""

    def test_token_cleared_after_approve(self):
        svc = ApprovalService()
        plan_row = {
            "id": 1,
            "status": "pending",
            "approval_token": "tok_aaa",
            "incident_id": "INC-X",
            "plan_json": "{}",
            "risk_level": "low",
        }
        conn, cursor = _make_cursor(fetchone_value=plan_row)
        pool = _fake_pool(conn)

        with patch("CorpAI.platform.db.DatabasePool.get", return_value=pool):
            # 第 1 次 approve:成功
            svc.approve(
                plan_id=1, token="tok_aaa",
                actor="bob", scopes=[REQUIRED_SCOPE],
            )
            # UPDATE 应包含 approval_token=''
            update_call = None
            for call in cursor.execute.call_args_list:
                sql = call.args[0]
                if "UPDATE sre_action_plans SET status='approved'" in sql:
                    update_call = call
                    break
            self.assertIsNotNone(update_call)
            # SQL 参数顺序: (actor, plan_id) — token 清空是 SQL 字面量 ''
            self.assertIn("approval_token=''", update_call.args[0])


if __name__ == "__main__":
    unittest.main()
