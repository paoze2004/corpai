"""Phase 3 test_audit — write_audit_log 通过真 DB 写 + DB 不可用 raise。"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from fastapi import HTTPException

from CorpAI.platform.auth.audit import write_audit_log


def _db_ok() -> bool:
    """本地 MySQL 是否可用(conftest 也有这个 fixture,但这里 inline 检查)。"""
    try:
        from CorpAI.platform.db import DatabasePool
        return DatabasePool.get().healthcheck()
    except Exception:
        return False


class TestAuditLog(unittest.TestCase):

    def test_write_audit_log_inserts_row(self):
        """真 DB:write_audit_log 成功后 INSERT 应可见(用 unique action 标签避免多次跑残留干扰)。"""
        if not _db_ok():
            self.skipTest("DatabasePool unavailable")

        from CorpAI.platform.db import DatabasePool
        import time as _time
        action = f"test_action_{int(_time.time())}"

        conn = DatabasePool.get().get_conn()
        try:
            write_audit_log(
                user_id="test_audit_user",
                tenant_id="default",
                action=action,
                target="test_target",
                ip="127.0.0.1",
                user_agent="unittest",
                result="allow",
                reason=None,
            )

            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM auth_audit_log WHERE user_id=%s AND action=%s",
                        ("test_audit_user", action))
            count = cur.fetchone()[0]
            cur.close()
            self.assertGreaterEqual(count, 1, "write_audit_log 应当至少新增 1 行")
        finally:
            conn.close()

    def test_write_audit_log_db_down_raises_500(self):
        """DB 不可达 → raise HTTPException 500(fail-closed)。"""
        def fake_get_conn():
            raise ConnectionError("DB unreachable")
        with patch("CorpAI.platform.db.DatabasePool.get") as mock_get:
            mock_get.return_value.get_conn.side_effect = fake_get_conn
            with self.assertRaises(HTTPException) as ctx:
                write_audit_log(
                    user_id="x", tenant_id="y", action="z",
                    target="", ip="", user_agent="",
                    result="allow",
                )
            self.assertEqual(ctx.exception.status_code, 500)


if __name__ == "__main__":
    unittest.main()
