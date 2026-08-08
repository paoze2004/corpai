"""Phase 3 test_fail_closed — DB 不可达 / secret 缺失时 fail-closed。

Audit log 写失败 / get_jwt_secret 缺失 / require_role 缺 user → 全 raise 401/403/500。
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from fastapi import HTTPException

from CorpAI.platform.auth.audit import write_audit_log
from CorpAI.platform.auth.dependencies import get_jwt_secret, get_current_user, require_role
from CorpAI.platform.auth.tokens import jwt_decode


class TestFailClosed(unittest.TestCase):

    def test_get_jwt_secret_missing_env_raises(self):
        """AUTH_JWT_SECRET 未设 → raise RuntimeError。"""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AUTH_JWT_SECRET", None)
            with self.assertRaises(RuntimeError) as ctx:
                get_jwt_secret()
            self.assertIn("AUTH_JWT_SECRET", str(ctx.exception))

    def test_get_current_user_no_auth_header_raises_401(self):
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization=None)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_get_current_user_wrong_prefix_raises_401(self):
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization="Basic abc.def.ghi")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_get_current_user_garbage_token_raises_401(self):
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(authorization="Bearer this.is.notatoken")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_audit_log_db_down_raises_500(self):
        """fail-closed 关键 case — DB 不可达,任何 audit 写都 raise HTTP 500。"""
        with patch("CorpAI.platform.db.DatabasePool.get") as mock_get:
            mock_get.return_value.get_conn.side_effect = ConnectionError("DB down")
            with self.assertRaises(HTTPException) as ctx:
                write_audit_log("u", "t", "a", "t", "ip", "ua", "allow")
            self.assertEqual(ctx.exception.status_code, 500)

    def test_jwt_decode_rejects_garbage_silently(self):
        """jwt_decode 永不抛 — 任何错误返 None(fail-closed 友好路径)。"""
        for bad in [None, "", "abc.def.ghi", "x.y.z.w", "...."]:
            self.assertIsNone(jwt_decode(bad, "secret"))


if __name__ == "__main__":
    unittest.main()
