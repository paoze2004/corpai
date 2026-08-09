"""devops_copilot plugin 单元测试 — v3.0 生产化精简。

删掉所有 in-memory dict 玩具测试(query_all/get_stats/list_p0 等),
只保留 4 真工具的 not_configured 行为测试 + RBAC 校验 + register 7 manifest。
"""
import json
import os
import unittest

os.environ["K8S_DRY_RUN"] = "true"
os.environ["AUTH_JWT_SECRET"] = "dev-secret"

from devops_copilot import tools as t
from CorpAI.platform.plugin_manager import PluginRegistry
from devops_copilot.plugin import register, AGENT_MANIFEST


def _make_token(scopes: list[str]) -> str:
    secret = os.environ.get("AUTH_JWT_SECRET", "dev-secret")
    from CorpAI.platform.auth.tokens import make_access_token
    return make_access_token("alice", "t1", "devops", scopes, secret)


class TestQueryIncident(unittest.TestCase):
    """query_incident 接 Jira,无 env 配置时显式 not_configured。"""

    def test_returns_not_configured_without_env(self):
        os.environ.pop("JIRA_URL", None)
        os.environ.pop("JIRA_TOKEN", None)
        data = json.loads(t.query_incident(limit=5))
        self.assertEqual(data["status"], "not_configured")
        self.assertIn("JIRA_URL", data["required_env"])
        self.assertIn("JIRA_TOKEN", data["required_env"])

    def test_returns_not_implemented_with_env(self):
        os.environ["JIRA_URL"] = "https://corp.atlassian.net"
        os.environ["JIRA_TOKEN"] = "fake-token-for-test"
        try:
            data = json.loads(t.query_incident(limit=5))
            self.assertIn(data["status"], ("not_implemented", "success"))
            # 期望:not_implemented(Phase 0 stub),Phase 1 接 SDK 后变 success
        finally:
            del os.environ["JIRA_URL"]
            del os.environ["JIRA_TOKEN"]


class TestQueryOncall(unittest.TestCase):
    def test_returns_not_configured_without_env(self):
        os.environ.pop("PAGERDUTY_API_KEY", None)
        data = json.loads(t.query_oncall("platform"))
        self.assertEqual(data["status"], "not_configured")
        self.assertIn("PAGERDUTY_API_KEY", data["required_env"])


class TestQueryAlert(unittest.TestCase):
    def test_returns_not_configured_without_env(self):
        os.environ.pop("PROMETHEUS_URL", None)
        data = json.loads(t.query_alert())
        self.assertEqual(data["status"], "not_configured")
        self.assertIn("PROMETHEUS_URL", data["required_env"])


class TestGetPodLogsRBAC(unittest.TestCase):
    """get_pod_logs RBAC:需 devops:read;DRY_RUN 返 stub 日志。"""

    def test_no_token_denied(self):
        with self.assertRaises(PermissionError):
            t.get_pod_logs("p1", "default", authorization=None)

    def test_invalid_token_denied(self):
        with self.assertRaises(PermissionError):
            t.get_pod_logs("p1", "default", authorization="Bearer invalid")

    def test_employee_scope_denied(self):
        token = _make_token(["chat:write"])
        with self.assertRaises(PermissionError) as ctx:
            t.get_pod_logs("p1", "default", authorization=f"Bearer {token}")
        self.assertIn("devops:read", str(ctx.exception))

    def test_devops_read_dry_run(self):
        token = _make_token(["devops:read"])
        data = json.loads(t.get_pod_logs("payment-api-abc123", "default",
                                          tail_lines=10, authorization=f"Bearer {token}"))
        self.assertEqual(data["status"], "dry_run")
        self.assertEqual(data["pod"], "payment-api-abc123")
        self.assertGreater(len(data["logs"]), 0)

    def test_tail_lines_invalid(self):
        token = _make_token(["devops:read"])
        data = json.loads(t.get_pod_logs("p1", "default", tail_lines=0,
                                          authorization=f"Bearer {token}"))
        self.assertEqual(data["status"], "invalid")


class TestPrompts(unittest.TestCase):
    def test_summarize_incident_not_configured_handling(self):
        """v3.0 prompt 必须显式 not_configured + not_implemented 状态。"""
        from devops_copilot.prompts import summarize_incident, DEVOPS_LLM_PROMPT
        p = summarize_incident()
        self.assertIn("query", p.input_variables)
        # v3.0:4 真工具都要提
        for kw in ("query_incident", "query_oncall", "query_alert", "get_pod_logs"):
            self.assertIn(kw, DEVOPS_LLM_PROMPT)
        # v3.0:删掉的玩具不再提
        for removed in ("list_recent_incidents", "list_open_p0",
                        "search_logs", "trigger_pipeline", "restart_pod"):
            self.assertNotIn(removed, DEVOPS_LLM_PROMPT)
        # 字符串 .template 已弃用,用 input_variables + invoke 验证 prompt 含关键短语
        # 直接调 invoke 拿最终 prompt 字符串
        result = p.invoke({"query": "test", "raw_response": "{}"}).to_string()
        # v3.0 必须显式提 not_configured / not_implemented
        for marker in ("not_configured", "not_implemented"):
            self.assertIn(marker, result,
                          f"summarize_incident prompt 缺 {marker} 处理说明")


class TestRegister(unittest.TestCase):
    def test_register_7_manifests_only_real_tools(self):
        """v3.0:7 manifest = 1 agent + 4 真工具 + 2 bridge。"""
        r = PluginRegistry()
        register(r)
        manifests = r.list_all()
        names = {m.name for m in manifests}
        self.assertEqual(len(manifests), 7)
        # 4 真工具
        self.assertIn("devops_copilot_incident_mcp", names)
        self.assertIn("devops_copilot_oncall_mcp", names)
        self.assertIn("devops_copilot_alert_mcp", names)
        self.assertIn("devops_copilot_k8s_mcp", names)
        # 2 bridge
        self.assertIn("devops_copilot_bridge_hr_mcp", names)
        self.assertIn("devops_copilot_bridge_faq_mcp", names)
        # 删掉的玩具
        for removed in ("devops_copilot_incident_create_mcp",
                        "devops_copilot_pipeline_mcp",
                        "devops_copilot_log_mcp"):
            self.assertNotIn(removed, names, f"{removed} 应被删除")

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