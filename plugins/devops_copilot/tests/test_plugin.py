"""devops_copilot plugin 单元测试 — RBAC showcase。"""
import json
import os
import unittest

# Phase 5:K8S_DRY_RUN 默认 True(测试隔离)
os.environ["K8S_DRY_RUN"] = "true"
# Phase 5:make_access_token 需要 AUTH_JWT_SECRET
os.environ["AUTH_JWT_SECRET"] = "dev-secret"

from devops_copilot import tools as t
from CorpAI.platform.plugin_manager import PluginRegistry
from devops_copilot.plugin import register, AGENT_MANIFEST, K8S_TOOL


def _make_token(scopes: list[str]) -> str:
    """生成测试用 JWT(需要 AUTH_JWT_SECRET 在 env)。"""
    secret = os.environ.get("AUTH_JWT_SECRET", "dev-secret")
    from CorpAI.platform.auth.tokens import make_access_token
    return make_access_token("alice", "t1", "devops", scopes, secret)


class TestIncident(unittest.TestCase):
    def test_query_all(self):
        data = json.loads(t.query_incident())
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]), 3)

    def test_query_filter_id(self):
        data = json.loads(t.query_incident(incident_id="INC-001"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"][0]["priority"], "P0")

    def test_query_filter_status(self):
        data = json.loads(t.query_incident(status="resolved"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]), 1)


class TestOncall(unittest.TestCase):
    def test_query_platform(self):
        data = json.loads(t.query_oncall("platform"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["primary"], "张工")

    def test_query_unknown_team(self):
        data = json.loads(t.query_oncall("nonexistent"))
        self.assertEqual(data["status"], "no_data")


class TestK8sRBAC(unittest.TestCase):
    """Phase 5 RBAC showcase:restart_pod 需 devops:write scope。"""

    def test_restart_no_token_denied(self):
        with self.assertRaises(PermissionError) as ctx:
            t.restart_pod("p1", "default", authorization=None)
        self.assertIn("Bearer token", str(ctx.exception))

    def test_restart_invalid_token_denied(self):
        with self.assertRaises(PermissionError) as ctx:
            t.restart_pod("p1", "default", authorization="Bearer invalid.token.here")
        self.assertIn("无效", str(ctx.exception))

    def test_restart_employee_scope_denied(self):
        token = _make_token(["chat:write"])  # employee 角色,无 devops:write
        with self.assertRaises(PermissionError) as ctx:
            t.restart_pod("p1", "default", authorization=f"Bearer {token}")
        self.assertIn("devops:write", str(ctx.exception))

    def test_restart_devops_read_only_denied(self):
        token = _make_token(["devops:read"])  # 只有 read
        with self.assertRaises(PermissionError) as ctx:
            t.restart_pod("p1", "default", authorization=f"Bearer {token}")
        self.assertIn("devops:write", str(ctx.exception))

    def test_restart_devops_write_ok_dry_run(self):
        token = _make_token(["devops:read", "devops:write"])
        data = json.loads(t.restart_pod("p1", "default", authorization=f"Bearer {token}"))
        self.assertEqual(data["status"], "dry_run")
        self.assertEqual(data["pod"], "p1")

    def test_restart_devops_write_with_star_ok(self):
        token = _make_token(["*"])  # super_admin 通配
        data = json.loads(t.restart_pod("p1", "default", authorization=f"Bearer {token}"))
        self.assertEqual(data["status"], "dry_run")


class TestPrompts(unittest.TestCase):
    def test_summarize_incident(self):
        from devops_copilot.prompts import summarize_incident, DEVOPS_LLM_PROMPT
        p = summarize_incident()
        self.assertIn("query", p.input_variables)
        self.assertTrue(len(DEVOPS_LLM_PROMPT) > 0)

    def test_summarize_k8s_action(self):
        from devops_copilot.prompts import summarize_k8s_action
        p = summarize_k8s_action()
        self.assertIn("query", p.input_variables)


class TestRegister(unittest.TestCase):
    def test_register_3_manifests_with_rbac(self):
        r = PluginRegistry()
        register(r)
        self.assertEqual(len(r.list_all()), 3)
        # RBAC showcase:k8s mcp 单独 devops:write,其他 devops:read
        self.assertEqual(r.get("devops_copilot_k8s_mcp").permissions, ["devops:write"])
        self.assertIn("devops:read", r.get("devops_copilot_incident_mcp").permissions)
        self.assertIn("devops:write", r.get("devops_copilot").permissions)


if __name__ == "__main__":
    unittest.main()
