"""sre_copilot plugin 单元测试 — v3.0 + Phase 1 真 SDK。

覆盖:
- 4 真工具 not_configured(无 env)
- 4 真工具 HTTP 调用(用 mock 替代真实请求)
- query_incident JQL 构造
- query_oncall team 多样性
- query_alert 客户端过滤
- get_pod_logs RBAC + DRY_RUN + KUBECONFIG 缺失
- prompts 含 4 真工具 + 显式 status 状态
- register 7 manifest
"""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ["K8S_DRY_RUN"] = "true"
os.environ["AUTH_JWT_SECRET"] = "dev-secret"

from sre_copilot import tools as t
from sre_copilot.plugin import register

from _0_CorpAI._2_platform.plugin_manager import PluginRegistry


def _make_token(scopes: list[str]) -> str:
    secret = os.environ.get("AUTH_JWT_SECRET", "dev-secret")
    from _0_CorpAI._2_platform.auth.tokens import make_access_token
    return make_access_token("alice", "t1", "devops", scopes, secret)


# ────────────────── not_configured ──────────────────

class TestNotConfigured(unittest.TestCase):
    def test_query_incident_no_env(self):
        os.environ.pop("JIRA_URL", None)
        os.environ.pop("JIRA_EMAIL", None)
        os.environ.pop("JIRA_TOKEN", None)
        data = json.loads(t.query_incident(limit=5))
        self.assertEqual(data["status"], "not_configured")
        self.assertIn("JIRA_URL", data["required_env"])
        self.assertIn("JIRA_EMAIL", data["required_env"])

    def test_query_oncall_no_env(self):
        os.environ.pop("PAGERDUTY_API_KEY", None)
        data = json.loads(t.query_oncall("platform"))
        self.assertEqual(data["status"], "not_configured")

    def test_query_alert_no_env(self):
        os.environ.pop("PROMETHEUS_URL", None)
        data = json.loads(t.query_alert())
        self.assertEqual(data["status"], "not_configured")


# ────────────────── query_incident(Jira)Phase 1 真 SDK ──────────────────

class TestQueryIncident(unittest.TestCase):
    """Phase 1.1:query_incident 接 Jira REST API v3。"""

    def setUp(self):
        os.environ["JIRA_URL"] = "https://corp.atlassian.net"
        os.environ["JIRA_EMAIL"] = "test@example.com"
        os.environ["JIRA_TOKEN"] = "fake-token"
        os.environ["JIRA_PROJECT"] = "INC"

    def tearDown(self):
        for k in ("JIRA_URL", "JIRA_EMAIL", "JIRA_TOKEN", "JIRA_PROJECT"):
            os.environ.pop(k, None)

    @patch("sre_copilot.tools.requests.request")
    def test_jql_with_filters(self, mock_req):
        """构造 JQL:incident_id + status + priority。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {
            "total": 1,
            "issues": [{
                "key": "INC-123",
                "fields": {
                    "summary": "支付服务挂",
                    "priority": {"name": "P0"},
                    "status": {"name": "Open"},
                    "assignee": {"displayName": "张三"},
                    "updated": "2026-08-08T10:00:00Z",
                    "created": "2026-08-08T09:00:00Z",
                },
            }],
        }
        mock_req.return_value = mock_resp

        data = json.loads(t.query_incident(
            incident_id="INC-123", status="Open", priority="P0", limit=5,
        ))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"][0]["id"], "INC-123")
        self.assertEqual(data["data"][0]["priority"], "P0")
        # 验证 JQL(JQL 现在 POST body 里,不是 params)
        call_kwargs = mock_req.call_args.kwargs
        jql = call_kwargs["json"]["jql"]
        self.assertIn('project = "INC"', jql)
        self.assertIn('key = "INC-123"', jql)
        self.assertIn('status = "Open"', jql)
        self.assertIn('priority = "P0"', jql)
        # 验证 POST + 新端点
        self.assertEqual(call_kwargs["method"] if "method" in call_kwargs else mock_req.call_args.args[0], "POST")
        # 验证 Basic auth = base64("test@example.com:fake-token")
        import base64
        expected = "Basic " + base64.b64encode(b"test@example.com:fake-token").decode()
        auth = call_kwargs["headers"]["Authorization"]
        self.assertEqual(auth, expected)

    @patch("sre_copilot.tools.requests.request")
    def test_jira_http_error(self, mock_req):
        """HTTP 500 → http5xx status + Counter。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"errorMessages": ["Internal Server Error"]}
        mock_req.return_value = mock_resp

        data = json.loads(t.query_incident(limit=5))
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["kind"], "http500")

    @patch("sre_copilot.tools.requests.request")
    def test_jira_timeout(self, mock_req):
        import requests as r
        mock_req.side_effect = r.Timeout("read timeout")
        data = json.loads(t.query_incident(limit=5))
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["kind"], "timeout")

    @patch("sre_copilot.tools.requests.request")
    def test_jira_empty(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"total": 0, "issues": []}
        mock_req.return_value = mock_resp

        data = json.loads(t.query_incident(limit=5))
        self.assertEqual(data["status"], "no_data")
        self.assertEqual(data["data"], [])


# ────────────────── query_oncall(PagerDuty)Phase 1.2 ──────────────────

class TestQueryOncall(unittest.TestCase):
    def setUp(self):
        os.environ["PAGERDUTY_API_KEY"] = "pd-fake-key"
        os.environ["PAGERDUTY_SCHEDULE_ID_PLATFORM"] = "PABCDEF"

    def tearDown(self):
        os.environ.pop("PAGERDUTY_API_KEY", None)
        os.environ.pop("PAGERDUTY_SCHEDULE_ID_PLATFORM", None)

    @patch("sre_copilot.tools.requests.request")
    def test_pagerduty_success(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {
            "oncalls": [
                {
                    "escalation_level": 1,
                    "user": {"name": "李四", "email": "lisi@corp.com"},
                    "schedule": {"html_url": "https://pd.com/sched/PABC"},
                    "escalation_policy": {"summary": "platform L1"},
                    "start": "2026-08-08T00:00:00Z",
                    "end": "2026-08-15T00:00:00Z",
                },
                {
                    "escalation_level": 2,
                    "user": {"name": "王五", "email": "wangwu@corp.com"},
                    "schedule": {"html_url": "https://pd.com/sched/PABC"},
                    "escalation_policy": {"summary": "platform L2"},
                },
            ],
        }
        mock_req.return_value = mock_resp

        data = json.loads(t.query_oncall("platform"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["primary"]["name"], "李四")
        self.assertEqual(data["data"]["secondary"]["name"], "王五")
        # 验证 Token + schedule_ids
        call = mock_req.call_args
        self.assertIn("Token token=", call.kwargs["headers"]["Authorization"])
        self.assertEqual(call.kwargs["params"]["schedule_ids[]"], "PABCDEF")

    @patch("sre_copilot.tools.requests.request")
    def test_pagerduty_no_data(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"oncalls": []}
        mock_req.return_value = mock_resp

        data = json.loads(t.query_oncall("platform"))
        self.assertEqual(data["status"], "no_data")

    def test_pagerduty_no_schedule(self):
        os.environ.pop("PAGERDUTY_SCHEDULE_ID_PLATFORM", None)
        data = json.loads(t.query_oncall("platform"))
        self.assertEqual(data["status"], "not_configured")


# ────────────────── query_alert(Prometheus)Phase 1.3 ──────────────────

class TestQueryAlert(unittest.TestCase):
    def setUp(self):
        os.environ["PROMETHEUS_URL"] = "http://alertmanager:9093"

    def tearDown(self):
        os.environ.pop("PROMETHEUS_URL", None)

    @patch("sre_copilot.tools.requests.request")
    def test_prometheus_success(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = [
            {
                "labels": {"alertname": "HighCPU", "severity": "critical",
                           "service": "payment"},
                "status": {"state": "active", "activeSince": "2026-08-08T09:00:00Z"},
                "annotations": {"summary": "CPU > 90%", "value": "92%"},
            },
        ]
        mock_req.return_value = mock_resp

        data = json.loads(t.query_alert())
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"][0]["name"], "HighCPU")
        self.assertEqual(data["data"][0]["severity"], "critical")

    @patch("sre_copilot.tools.requests.request")
    def test_prometheus_client_filter(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = [
            {"labels": {"alertname": "A1", "severity": "warning",
                        "service": "payment"}, "status": {"state": "active"},
             "annotations": {"summary": ""}},
            {"labels": {"alertname": "A2", "severity": "critical",
                        "service": "auth"}, "status": {"state": "active"},
             "annotations": {"summary": ""}},
        ]
        mock_req.return_value = mock_resp

        data = json.loads(t.query_alert(severity="critical"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]), 1)
        self.assertEqual(data["data"][0]["name"], "A2")

    @patch("sre_copilot.tools.requests.request")
    def test_prometheus_http_404(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.headers = {"content-type": "application/json"}
        mock_req.return_value = mock_resp

        data = json.loads(t.query_alert())
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["kind"], "http404")


# ────────────────── get_pod_logs(K8s)Phase 1.4 ──────────────────

class TestGetPodLogs(unittest.TestCase):
    """Phase 1.4:get_pod_logs 接 kubernetes-python。"""

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
        self.assertIn("sre:read", str(ctx.exception))

    def test_devops_read_dry_run(self):
        token = _make_token(["sre:read"])
        data = json.loads(t.get_pod_logs(
            "payment-api-abc123", "default",
            tail_lines=10, authorization=f"Bearer {token}",
        ))
        self.assertEqual(data["status"], "dry_run")
        self.assertEqual(data["pod"], "payment-api-abc123")
        self.assertGreater(len(data["logs"]), 0)

    def test_tail_lines_invalid(self):
        token = _make_token(["sre:read"])
        data = json.loads(t.get_pod_logs(
            "p1", "default", tail_lines=0,
            authorization=f"Bearer {token}",
        ))
        self.assertEqual(data["status"], "invalid")

    def test_tail_lines_too_large(self):
        token = _make_token(["sre:read"])
        data = json.loads(t.get_pod_logs(
            "p1", "default", tail_lines=99999,
            authorization=f"Bearer {token}",
        ))
        self.assertEqual(data["status"], "invalid")

    @patch("sre_copilot.tools.DRY_RUN", False)
    def test_k8s_dry_run_false_no_kubeconfig(self):
        """DRY_RUN=false 但无 KUBECONFIG → no_kubeconfig。"""
        token = _make_token(["sre:read"])
        with patch("os.path.exists", return_value=False):
            data = json.loads(t.get_pod_logs(
                "p1", "default", tail_lines=10,
                authorization=f"Bearer {token}",
            ))
        self.assertEqual(data["status"], "error")
        self.assertIn(data["kind"], ("no_kubeconfig", "config_load_failed", "missing_dependency"))


# ────────────────── _sdk_call 通用层 ──────────────────

class TestSdkCall(unittest.TestCase):
    """测试通用 _sdk_call 函数 + Counter 上报。"""

    @patch("sre_copilot.tools.requests.request")
    def test_timeout(self, mock_req):
        import requests as r
        mock_req.side_effect = r.Timeout()
        code, body = t._sdk_call("jira", "GET", "http://x")
        self.assertEqual(code, -1)
        self.assertEqual(body, "timeout")

    @patch("sre_copilot.tools.requests.request")
    def test_connection_error(self, mock_req):
        import requests as r
        mock_req.side_effect = r.ConnectionError("refused")
        code, body = t._sdk_call("pagerduty", "GET", "http://x")
        self.assertEqual(code, -1)
        self.assertIn("unreachable", body)

    @patch("sre_copilot.tools.requests.request")
    def test_http_401(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"error": "auth"}
        mock_req.return_value = mock_resp

        code, body = t._sdk_call("jira", "GET", "http://x")
        self.assertEqual(code, 401)
        self.assertEqual(body, {"error": "auth"})

    @patch("sre_copilot.tools.requests.request")
    def test_json_decode_failure(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.side_effect = ValueError("bad json")
        mock_req.return_value = mock_resp

        code, body = t._sdk_call("prometheus", "GET", "http://x")
        self.assertEqual(code, 200)
        self.assertIn("json_decode", body)


# ────────────────── prompts ──────────────────

class TestPrompts(unittest.TestCase):
    def test_summarize_incident_statuses(self):
        from sre_copilot.prompts import SRE_LLM_PROMPT, summarize_incident
        p = summarize_incident()
        self.assertIn("query", p.input_variables)
        for kw in ("query_incident", "query_oncall", "query_alert", "get_pod_logs"):
            self.assertIn(kw, SRE_LLM_PROMPT)
        for removed in ("list_recent_incidents", "list_open_p0",
                        "search_logs", "trigger_pipeline", "restart_pod"):
            self.assertNotIn(removed, SRE_LLM_PROMPT)
        result = p.invoke({"query": "test", "raw_response": "{}"}).to_string()
        for marker in ("not_configured", "not_implemented"):
            self.assertIn(marker, result,
                          f"summarize_incident prompt 缺 {marker} 处理说明")


# ────────────────── register ──────────────────

class TestRegister(unittest.TestCase):
    def test_register_7_manifests_only_real_tools(self):
        r = PluginRegistry()
        register(r)
        manifests = r.list_all()
        names = {m.name for m in manifests}
        self.assertEqual(len(manifests), 7)
        self.assertIn("sre_copilot_incident_mcp", names)
        self.assertIn("sre_copilot_oncall_mcp", names)
        self.assertIn("sre_copilot_alert_mcp", names)
        self.assertIn("sre_copilot_k8s_mcp", names)
        self.assertIn("sre_copilot_bridge_hr_mcp", names)
        self.assertIn("sre_copilot_bridge_knowledge_mcp", names)
        for removed in ("sre_copilot_incident_create_mcp",
                        "sre_copilot_pipeline_mcp",
                        "sre_copilot_log_mcp"):
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
