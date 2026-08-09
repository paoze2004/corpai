"""hr_assistant e2e 集成测试 — 联动 hr 真 DB + audit_log。

需求:DB 已起(MySQL + 7 张表);否则 skip。
测试流程:
  1. alice 提交请假 → submit_leave 写 hr_leave_requests
  2. 校验 hr_audit_log 记录 submit_leave
  3. bob(HR) 审批 → approve_request 状态机 pending → approved
  4. 校验 hr_audit_log 记录 approve_leave
  5. alice 撤销另一条 → cancel_leave,已审批的不能再 cancel
  6. alice 查自己的 → query_my_requests 返 2 条
"""
from __future__ import annotations

import json
import os
import time
import unittest

import pytest

# 环境变量先于 conftest 跑
os.environ.setdefault("MYSQL_HOST", "localhost")
os.environ.setdefault("MYSQL_USER", "admin")
os.environ.setdefault("MYSQL_PASSWORD", "admin123456")
os.environ.setdefault("MYSQL_DB", "CorpAI")
os.environ.setdefault("AUTH_JWT_SECRET", "dev-secret")


def _check_db_available() -> bool:
    """DB 不在 → skip。"""
    try:
        from CorpAI.platform.db import DatabasePool
        DatabasePool.get().get_conn().close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _check_db_available(), reason="MySQL 不可用,跳过 e2e"
)


def _make_token(user_id: str, scopes: list[str]) -> str:
    from CorpAI.platform.auth.tokens import make_access_token
    return make_access_token(user_id, "t1", "default", scopes,
                              os.environ["AUTH_JWT_SECRET"])


def _clean_hr_tables() -> None:
    """清空测试数据(保留表结构)。"""
    from CorpAI.platform.db import DatabasePool
    conn = DatabasePool.get().get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM hr_audit_log")
        for t in ("hr_regularization", "hr_training_registrations",
                  "hr_asset_requests", "hr_certificates",
                  "hr_reimbursements", "hr_leave_requests"):
            cur.execute(f"DELETE FROM {t}")
        conn.commit()
        cur.close()
    finally:
        conn.close()


class TestHrE2E(unittest.TestCase):
    """alice 提交 → HR 审批 → audit_log 全链路。"""

    @classmethod
    def setUpClass(cls):
        if not _check_db_available():
            raise unittest.SkipTest("MySQL 不可用")
        _clean_hr_tables()

    def setUp(self):
        _clean_hr_tables()
        self.alice = f"Bearer {_make_token('alice', ['chat:write', 'hr:write'])}"
        self.bob_hr = f"Bearer {_make_token('bob_hr', ['hr:write'])}"
        self.alice_chat_only = f"Bearer {_make_token('alice', ['chat:write'])}"

    # ─── 1. submit_leave ───

    def test_01_submit_leave_writes_db_and_audit(self):
        from hr_assistant import actions
        resp = json.loads(actions.submit_leave(
            authorization=self.alice, leave_type="annual",
            start_date="2026-08-15", end_date="2026-08-16",
            days=2.0, reason="家庭事务",
        ))
        self.assertEqual(resp["status"], "success")
        rid = resp["data"]["request_id"]
        self.assertTrue(rid.startswith("L"))

        # DB 里有这条
        from CorpAI.platform.db import DatabasePool
        conn = DatabasePool.get().get_conn()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT * FROM hr_leave_requests WHERE request_id=%s", (rid,))
            row = cur.fetchone()
            cur.close()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["user_id"], "alice")
        self.assertEqual(row["leave_type"], "annual")

        # audit_log 里有
        conn = DatabasePool.get().get_conn()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT * FROM hr_audit_log WHERE entity_id=%s", (rid,))
            audits = cur.fetchall()
            cur.close()
        finally:
            conn.close()
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]["action"], "submit_leave")
        self.assertEqual(audits[0]["user_id"], "alice")
        self.assertIsNotNone(audits[0]["trace_id"])

    # ─── 2. approve_request ───

    def test_02_approve_leave_status_machine(self):
        from hr_assistant import actions
        # alice 提交
        leave = json.loads(actions.submit_leave(
            authorization=self.alice, leave_type="sick",
            start_date="2026-08-15", end_date="2026-08-15",
            days=1.0, reason="感冒",
        ))
        rid = leave["data"]["request_id"]

        # bob_hr 审批
        approval = json.loads(actions.approve_request(
            authorization=self.bob_hr, request_id=rid,
            target_type="leave", action="approve", approval_note="同意",
        ))
        self.assertEqual(approval["status"], "success")
        self.assertEqual(approval["data"]["status"], "approved")

        # 状态机:已 approved 不能再次 approve
        dup = json.loads(actions.approve_request(
            authorization=self.bob_hr, request_id=rid,
            target_type="leave", action="approve",
        ))
        self.assertEqual(dup["status"], "not_found")

        # audit_log 有 submit_leave + approve_leave 2 条
        from CorpAI.platform.db import DatabasePool
        conn = DatabasePool.get().get_conn()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT action, user_id FROM hr_audit_log WHERE entity_id=%s ORDER BY id",
                        (rid,))
            rows = cur.fetchall()
            cur.close()
        finally:
            conn.close()
        actions_set = [r["action"] for r in rows]
        self.assertIn("submit_leave", actions_set)
        self.assertIn("approve_leave", actions_set)
        # approve_leave 操作人应是 bob_hr(审批人)
        approve_rows = [r for r in rows if r["action"] == "approve_leave"]
        self.assertEqual(approve_rows[0]["user_id"], "bob_hr")

    # ─── 3. cancel_leave + 状态机 ───

    def test_03_cancel_only_pending_allowed(self):
        from hr_assistant import actions
        # alice 提交请假 A
        leave_a = json.loads(actions.submit_leave(
            authorization=self.alice, leave_type="personal",
            start_date="2026-08-15", end_date="2026-08-15",
            days=1.0, reason="私事",
        ))
        rid_a = leave_a["data"]["request_id"]
        # alice 提交请假 B,被 HR 批准
        leave_b = json.loads(actions.submit_leave(
            authorization=self.alice, leave_type="annual",
            start_date="2026-08-20", end_date="2026-08-22",
            days=3.0, reason="旅行",
        ))
        rid_b = leave_b["data"]["request_id"]
        actions.approve_request(authorization=self.bob_hr, request_id=rid_b,
                                 target_type="leave", action="approve")

        # A 可撤销
        cancel_a = json.loads(actions.cancel_leave(
            authorization=self.alice, request_id=rid_a,
        ))
        self.assertEqual(cancel_a["status"], "success")

        # B 已 approved,不能撤销
        cancel_b = json.loads(actions.cancel_leave(
            authorization=self.alice, request_id=rid_b,
        ))
        self.assertEqual(cancel_b["status"], "not_found")

    # ─── 4. RBAC — 员工不能审批 ───

    def test_04_employee_cannot_approve(self):
        from hr_assistant import actions
        leave = json.loads(actions.submit_leave(
            authorization=self.alice, leave_type="annual",
            start_date="2026-08-15", end_date="2026-08-15",
            days=1.0, reason="测试",
        ))
        rid = leave["data"]["request_id"]
        # alice 用 chat-only token 尝试审批
        deny = json.loads(actions.approve_request(
            authorization=self.alice_chat_only, request_id=rid,
            target_type="leave", action="approve",
        ))
        self.assertEqual(deny["status"], "forbidden")
        self.assertIn("hr:write", deny["message"])

    # ─── 5. query_my_requests ───

    def test_05_query_my_requests_by_user(self):
        from hr_assistant import actions
        actions.submit_leave(
            authorization=self.alice, leave_type="annual",
            start_date="2026-08-15", end_date="2026-08-16",
            days=2.0, reason="家事1",
        )
        actions.submit_leave(
            authorization=self.alice, leave_type="annual",
            start_date="2026-08-20", end_date="2026-08-22",
            days=3.0, reason="家事2",
        )
        # bob_hr 也提交一条,但 query_my_requests 用 alice token,只返 alice
        actions.submit_leave(
            authorization=self.bob_hr, leave_type="annual",
            start_date="2026-08-25", end_date="2026-08-25",
            days=1.0, reason="bob_hr 的",
        )

        resp = json.loads(actions.query_my_requests(
            authorization=self.alice, limit=10,
        ))
        self.assertEqual(resp["status"], "success")
        self.assertEqual(resp["data"]["total"], 2)
        for item in resp["data"]["items"]:
            self.assertEqual(item["user_id"], "alice")

    # ─── 6. cross_query_faq 兜底降级 ───

    def test_06_bridge_faq_fallback_when_unreachable(self):
        """faq 服务不可达时,cross_query_faq 返 success 但 hits 空(不阻塞主流程)。"""
        from hr_assistant import actions
        resp = json.loads(actions.cross_query_faq(
            authorization=self.alice,
            query="测试兜底",
        ))
        # 即使 faq 不可达,也不报错;status=success, hint 提示
        self.assertIn(resp["status"], ("success", "fallback"))


if __name__ == "__main__":
    unittest.main()