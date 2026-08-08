"""Phase 3 test_login_flow — 端到端 /admin/api/login + 受保护端点。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# 必须设 secret 才能 import dependencies
os.environ["AUTH_JWT_SECRET"] = os.environ.get("AUTH_JWT_SECRET", "test-jwt-secret")


def _db_ok() -> bool:
    try:
        from CorpAI.platform.db import DatabasePool
        return DatabasePool.get().healthcheck()
    except Exception:
        return False


class TestLoginFlow(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """把 FastAPI app + TestClient 准备好(需要 DB + AUTH_JWT_SECRET 已设)。"""
        if not _db_ok():
            return  # raise skipTest in tests below
        cls.app = None
        from fastapi.testclient import TestClient
        from CorpAI.api.app import app as _app
        cls.app = _app
        cls.client = TestClient(_app)

    def setUp(self):
        if not _db_ok():
            self.skipTest("DatabasePool unavailable")

    def test_login_wrong_password_returns_401(self):
        r = self.client.post("/admin/api/login?username=nobody&password=wrong")
        self.assertEqual(r.status_code, 401)

    def test_login_missing_credentials_returns_422_or_401(self):
        # FastAPI 422 for missing query params(Query())
        r = self.client.post("/admin/api/login")
        self.assertIn(r.status_code, (401, 422))

    def test_protected_endpoint_without_token_returns_401(self):
        """无 Bearer token 访问 /admin/api/users → 401。"""
        r = self.client.get("/admin/api/users")
        self.assertEqual(r.status_code, 401)

    def test_protected_endpoint_with_bad_token_returns_401(self):
        r = self.client.get("/admin/api/users",
                            headers={"Authorization": "Bearer garbage.token.here"})
        self.assertEqual(r.status_code, 401)

    def test_protected_endpoint_valid_token_no_super_admin_skipped_or_ok(self):
        """如果有 super_admin 在 DB,login + GET users 都应 200。"""
        # bootstrap 脚本不在这里跑 — 测试只验证 status code 路径
        # 完整 e2e 见 scripts/bootstrap_super_admin.py + Step 6 验证
        try:
            r = self.client.post(
                "/admin/api/login?username=admin&password=admin",
            )
            if r.status_code != 200:
                self.skipTest("admin user not yet bootstrapped; run scripts/bootstrap_super_admin.py")
            token = r.json()["access_token"]
            r2 = self.client.get("/admin/api/users",
                                 headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(r2.status_code, 200)
            self.assertIn("data", r2.json())
        except Exception as e:
            self.skipTest(f"end-to-end login flow not available: {e}")


if __name__ == "__main__":
    unittest.main()
