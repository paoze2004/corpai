"""Phase 3 test_scopes — 4 角色 × 5 scope 权限矩阵。"""
import unittest

from _0_CorpAI._2_platform.auth.scopes import (
    ROLE_SCOPES, has_scope, scopes_for_role,
)


class TestScopeMatrix(unittest.TestCase):
    """4 角色 × 5 scope 权限矩阵。"""

    CASES = [
        # (role, scope, expected)
        ("employee",     "chat:write",     True),
        ("employee",     "plugin:write",   False),
        ("employee",     "plugin:read",    False),
        ("employee",     "user:read",      False),
        ("employee",     "log:read",       False),
        # agent_author
        ("agent_author", "chat:write",     True),
        ("agent_author", "plugin:write",   True),
        ("agent_author", "plugin:read",    False),  # 没 plugin:read scope
        ("agent_author", "user:read",      False),
        ("agent_author", "log:read",       False),
        # admin
        ("admin",        "chat:write",     True),
        ("admin",        "plugin:write",   True),
        ("admin",        "plugin:read",    True),
        ("admin",        "user:read",      True),
        ("admin",        "log:read",       True),
        # super_admin — `*` 通配
        ("super_admin",  "chat:write",     True),
        ("super_admin",  "plugin:write",   True),
        ("super_admin",  "user:read",      True),
        ("super_admin",  "log:read",       True),
        ("super_admin",  "anything:anywhere", True),  # 通配
    ]

    def test_scope_matrix(self):
        for role, scope, expected in self.CASES:
            with self.subTest(role=role, scope=scope):
                user_scopes = ROLE_SCOPES[role]
                self.assertEqual(
                    has_scope(scope, user_scopes), expected,
                    f"role={role} scope={scope}",
                )

    def test_scopes_for_role_returns_correct_list(self):
        self.assertEqual(scopes_for_role("employee"), ["chat:write"])
        self.assertIn("plugin:write", scopes_for_role("agent_author"))
        self.assertIn("log:read", scopes_for_role("admin"))
        self.assertEqual(scopes_for_role("super_admin"), ["*"])
        # 未知 role fallback
        self.assertEqual(scopes_for_role("unknown_role"), ["chat:write"])


if __name__ == "__main__":
    unittest.main()
