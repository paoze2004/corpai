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
        data = json.loads(t.query_incident(limit=100))
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]), 25)  # v3.0:扩到 25 条

    def test_query_filter_id(self):
        data = json.loads(t.query_incident(incident_id="INC-001"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"][0]["priority"], "P0")

    def test_query_filter_status(self):
        data = json.loads(t.query_incident(status="resolved"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]), 4)  # INC-003/006/015/021

    def test_query_filter_priority(self):
        data = json.loads(t.query_incident(priority="P0"))
        self.assertEqual(data["status"], "success")
        self.assertGreaterEqual(len(data["data"]), 3)  # INC-001/005/011

    def test_get_stats(self):
        data = json.loads(t.get_incident_stats())
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["total"], 25)
        self.assertIn("P0", data["data"]["by_priority"])

    def test_list_p0_open(self):
        data = json.loads(t.list_open_p0_incidents())
        self.assertEqual(data["status"], "success")
        for inc in data["data"]:
            self.assertEqual(inc["priority"], "P0")
            self.assertNotEqual(inc["status"], "resolved")

    def test_search_keyword(self):
        data = json.loads(t.search_incidents_by_keyword("API"))
        self.assertEqual(data["status"], "success")
        self.assertGreater(len(data["data"]), 0)


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
    def test_register_10_manifests_with_rbac(self):
        r = PluginRegistry()
        register(r)
        self.assertEqual(len(r.list_all()), 10)  # v3.0:1 agent + 9 tools (含 2 bridge)
        # RBAC:k8s mcp 单独 devops:write
        self.assertEqual(r.get("devops_copilot_k8s_mcp").permissions, ["devops:write"])
        self.assertIn("devops:read", r.get("devops_copilot_incident_mcp").permissions)
        self.assertIn("devops:write", r.get("devops_copilot").permissions)
        # bridge mcp
        self.assertIn("devops:read", r.get("devops_copilot_bridge_hr_mcp").permissions)
        self.assertIn("devops:read", r.get("devops_copilot_bridge_faq_mcp").permissions)

    def test_register_all_mcp_have_permissions(self):
        r = PluginRegistry()
        register(r)
        for m in r.list_all():
            self.assertGreater(len(m.permissions), 0, f"{m.name} 无 permissions")

    def test_action_tools_mcp_tool_name_unique(self):
        r = PluginRegistry()
        register(r)
        names = [m.mcp_tool_name for m in r.list_all() if m.mcp_tool_name]
        self.assertEqual(len(names), len(set(names)), f"mcp_tool_name 重复:{names}")


if __name__ == "__main__":
    unittest.main()
