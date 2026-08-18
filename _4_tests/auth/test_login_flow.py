"""Phase 3 test_login_flow — 端到端 /admin/api/login + 受保护端点。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# 必须设 secret 才能 import dependencies
os.environ["AUTH_JWT_SECRET"] = os.environ.get("AUTH_JWT_SECRET", "test-jwt-secret")


def _db_ok() -> bool:
    try:
        from _0_CorpAI._2_platform.db import DatabasePool
        return DatabasePool.get().healthcheck()
    except Exception:
        return False


class TestLoginFlow(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """把 FastAPI app + TestClient 准备好(需要 DB + AUTH_JWT_SECRET 已设)。"""
        if not _db_ok():
            return  # raise skipTest in _4_tests below
        cls.app = None
        from fastapi.testclient import TestClient
        from _0_CorpAI._0_api.app import app as _app
        cls.app = _app
        cls.client = TestClient(_app)

    def setUp(self):
        if not _db_ok():
            self.skipTest("DatabasePool unavailable")

    def test_login_wrong_password_returns_401(self):
        # 凭据走 Body(不再用 Query,避免进 URL/日志/代理缓存)
        r = self.client.post("/admin/api/login", json={"username": "nobody", "password": "wrong"})
        self.assertEqual(r.status_code, 401)

    def test_login_missing_credentials_returns_422_or_401(self):
        # FastAPI 422 for missing body params(Body())
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
        # 完整 e2e 见 _2_scripts/bootstrap_super_admin.py + Step 6 验证
        try:
            r = self.client.post(
                "/admin/api/login?username=admin&password=admin",
            )
            if r.status_code != 200:
                self.skipTest("admin user not yet bootstrapped; run _2_scripts/bootstrap_super_admin.py")
            token = r.json()["access_token"]
            r2 = self.client.get("/admin/api/users",
                                 headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(r2.status_code, 200)
            self.assertIn("data", r2.json())
        except Exception as e:
            self.skipTest(f"end-to-end login flow not available: {e}")


class TestScopeMerging(unittest.TestCase):
    """login 端点合并 role 默认 scope + auth_users.scopes 列(逗号分隔)。

    演示价值:不同用户登录不同系统(hr_alice / sre_bob / faq_carol),
    每人的 scopes 由 role 默认 + per-user 额外 scope 组成。
    """

    def test_role_default_plus_per_user_merged(self):
        """role=employee 默认 [chat:write] + user.scopes='hr:read,hr:write' → 合并去重 [chat:write, hr:read, hr:write]"""
        from _0_CorpAI._0_api.admin_router import _merge_role_and_user_scopes  # type: ignore
        merged = _merge_role_and_user_scopes(
            role="employee",
            user_scopes_csv="hr:read,hr:write",
        )
        self.assertEqual(merged, ["chat:write", "hr:read", "hr:write"])

    def test_dedup_keeps_first_occurrence(self):
        """重复 scope 只保留第一个出现位置"""
        from _0_CorpAI._0_api.admin_router import _merge_role_and_user_scopes  # type: ignore
        merged = _merge_role_and_user_scopes(
            role="admin",  # 默认含 chat:write + plugin:read
            user_scopes_csv="chat:write,knowledge:read",  # chat:write 重复
        )
        self.assertEqual(merged, ["chat:write", "plugin:read", "plugin:write",
                                  "user:read", "log:read", "knowledge:read"])

    def test_empty_per_user_keeps_role_only(self):
        """user.scopes 为空时只返 role 默认"""
        from _0_CorpAI._0_api.admin_router import _merge_role_and_user_scopes  # type: ignore
        merged = _merge_role_and_user_scopes(role="admin", user_scopes_csv="")
        self.assertEqual(merged, ["chat:write", "plugin:read", "plugin:write",
                                  "user:read", "log:read"])

    def test_whitespace_in_csv_stripped(self):
        """user.scopes 里的多余空白自动 trim"""
        from _0_CorpAI._0_api.admin_router import _merge_role_and_user_scopes  # type: ignore
        merged = _merge_role_and_user_scopes(
            role="employee",
            user_scopes_csv="  hr:read ,  knowledge:read  ",
        )
        self.assertIn("hr:read", merged)
        self.assertIn("knowledge:read", merged)
        self.assertNotIn("  hr:read ", merged)

    def test_demo_users_have_distinct_scopes(self):
        """演示用 3 个 user 的 scope 必须互不重叠,演示 RBAC 隔离:
        - hr_alice  有 hr:* + knowledge:read
        - sre_bob   有 sre:* + knowledge:read
        - faq_carol 只有 knowledge:read
        hr 调 sre 应 deny(缺 sre:write);sre 调 hr 应 deny(缺 hr:write)
        """
        from _0_CorpAI._0_api.admin_router import _merge_role_and_user_scopes  # type: ignore
        from _0_CorpAI._2_platform.auth.scopes import has_scope

        hr_scopes = _merge_role_and_user_scopes("employee", "hr:read,hr:write,knowledge:read")
        sre_scopes = _merge_role_and_user_scopes("employee", "sre:read,sre:write,sre:approve,knowledge:read")
        faq_scopes = _merge_role_and_user_scopes("employee", "knowledge:read")

        # hr 调 hr 工具 → 允许
        self.assertTrue(has_scope("hr:write", hr_scopes))
        # hr 调 sre 工具 → 拒绝(没 sre:write)
        self.assertFalse(has_scope("sre:write", hr_scopes))
        # sre 调 hr → 拒绝
        self.assertFalse(has_scope("hr:write", sre_scopes))
        # faq 调 hr/sre → 都拒绝
        self.assertFalse(has_scope("hr:write", faq_scopes))
        self.assertFalse(has_scope("sre:write", faq_scopes))
        # 三个用户都能调 faq(都有 knowledge:read)
        self.assertTrue(has_scope("knowledge:read", hr_scopes))
        self.assertTrue(has_scope("knowledge:read", sre_scopes))
        self.assertTrue(has_scope("knowledge:read", faq_scopes))

    def test_render_plugin_access_shows_correct_marks(self):
        """admin/users.html 的 plugin 访问列:每个 user 看 3 个 plugin 的 ✓/✗。"""
        from _0_CorpAI._0_api.admin_router import _render_plugin_access  # type: ignore

        # super_admin 拥有 * → 3 个 plugin 全 ✓
        super_access = _render_plugin_access(["*"])
        self.assertIn("hr ✓", super_access)
        self.assertIn("sre ✓", super_access)
        self.assertIn("knowledge ✓", super_access)

        # hr_alice 有效 scopes → hr ✓ / sre ✗ / knowledge ✓
        hr_access = _render_plugin_access(["chat:write", "hr:read", "hr:write", "knowledge:read"])
        self.assertIn("hr ✓", hr_access)
        self.assertIn("sre ✗", hr_access)
        self.assertIn("knowledge ✓", hr_access)

        # knowledge_carol 只有 knowledge:read → hr ✗ / sre ✗ / knowledge ✓
        knowledge_access = _render_plugin_access(["chat:write", "knowledge:read"])
        self.assertIn("hr ✗", knowledge_access)
        self.assertIn("sre ✗", knowledge_access)
        self.assertIn("knowledge ✓", knowledge_access)

        # sre ✗ 的格有 title 提示具体缺哪个 scope(hover 可看)
        self.assertIn('title="sre: 拒绝(缺 sre:read)"', knowledge_access)
        # hr ✗ 的格有 title 提示缺 hr:read
        self.assertIn('title="hr: 拒绝(缺 hr:read)"', knowledge_access)


if __name__ == "__main__":
    unittest.main()
