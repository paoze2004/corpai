"""Action Tools 测试 — dry_run + 真接(用 mock)+ scope 校验。

覆盖:
- 4 个 tool 的 scope 校验(无 sre:execute → PermissionDeniedError)
- DRY_RUN=true(默认) → 返 planned,不调 SDK
- DRY_RUN=false + 缺 env → ConfigError
- DRY_RUN=false + Jira 404/200 → 正确分支
- replicas 范围校验
- 纯文本 → ADF 包装
- tool_dispatcher 异步路径 + 未知 tool 报错
"""
import asyncio
import base64
import os
import unittest
from unittest.mock import MagicMock, patch

# DRY_RUN=true 始终
os.environ.setdefault("SRE_DRY_RUN", "true")
os.environ.setdefault("AUTH_JWT_SECRET", "dev-secret")

from sre_copilot.action_tools import (
    DRY_RUN,
    REQUIRED_SCOPE,
    ConfigError,
    create_incident_comment,
    restart_deployment,
    scale_deployment,
    tool_dispatcher,
    update_incident_status,
)


def _run(coro):
    return asyncio.run(coro)


# ─────────────────── scope 校验 ───────────────────

class TestScopeCheck(unittest.TestCase):
    """所有 action tool 必须 scope 二次校验。"""

    def test_restart_no_scope(self):
        with self.assertRaises(Exception) as ctx:
            restart_deployment("api", "default", scopes=["chat:write"])
        self.assertIn(REQUIRED_SCOPE, str(ctx.exception))

    def test_scale_no_scope(self):
        with self.assertRaises(Exception) as ctx:
            scale_deployment("api", 3, "default", scopes=["sre:read"])
        self.assertIn(REQUIRED_SCOPE, str(ctx.exception))

    def test_jira_status_no_scope(self):
        with self.assertRaises(Exception) as ctx:
            update_incident_status("INC-1", "已完成", scopes=[])
        self.assertIn(REQUIRED_SCOPE, str(ctx.exception))

    def test_jira_comment_no_scope(self):
        with self.assertRaises(Exception) as ctx:
            create_incident_comment("INC-1", "text", scopes=None)
        self.assertIn(REQUIRED_SCOPE, str(ctx.exception))


# ─────────────────── dry_run 路径 ───────────────────

class TestDryRun(unittest.TestCase):
    """DRY_RUN=true(默认)— 不调 SDK,返 planned。"""

    def test_restart_dry_run(self):
        self.assertTrue(DRY_RUN)
        result = restart_deployment(
            "api", "default",
            scopes=[REQUIRED_SCOPE], actor="ai_agent",
        )
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["deployment"], "api")
        self.assertEqual(result["namespace"], "default")

    def test_scale_dry_run(self):
        result = scale_deployment(
            "api", 5, "default", scopes=[REQUIRED_SCOPE],
        )
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["replicas"], 5)

    def test_jira_status_dry_run(self):
        # 没 env 也能 dry_run(SDK 不调)
        os.environ.pop("JIRA_URL", None)
        result = update_incident_status(
            "INC-1", "已完成", scopes=[REQUIRED_SCOPE],
        )
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["target_status"], "已完成")

    def test_jira_comment_dry_run(self):
        os.environ.pop("JIRA_URL", None)
        result = create_incident_comment(
            "INC-1", "AI 修复中",
            scopes=[REQUIRED_SCOPE],
        )
        self.assertEqual(result["status"], "dry_run")


# ─────────────────── replicas 范围 ───────────────────

class TestScaleValidation(unittest.TestCase):
    """scale_deployment 的 replicas 范围 [0, 50]。"""

    def test_replicas_negative(self):
        with self.assertRaises(ConfigError):
            scale_deployment("api", -1, scopes=[REQUIRED_SCOPE])

    def test_replicas_too_large(self):
        with self.assertRaises(ConfigError):
            scale_deployment("api", 100, scopes=[REQUIRED_SCOPE])

    def test_replicas_zero_ok(self):
        # 0 replicas = scale to zero,合法
        result = scale_deployment("api", 0, scopes=[REQUIRED_SCOPE])
        self.assertEqual(result["status"], "dry_run")


# ─────────────────── Jira 真接(mock) ───────────────────

class TestJiraStatusRealCall(unittest.TestCase):
    """DRY_RUN=false 时调 Jira SDK;用 mock 替代真实 HTTP。"""

    def setUp(self):
        os.environ["SRE_DRY_RUN"] = "false"
        os.environ["JIRA_URL"] = "https://corp.atlassian.net"
        os.environ["JIRA_EMAIL"] = "test@example.com"
        os.environ["JIRA_TOKEN"] = "fake-token"

    def tearDown(self):
        os.environ["SRE_DRY_RUN"] = "true"
        for k in ("JIRA_URL", "JIRA_EMAIL", "JIRA_TOKEN"):
            os.environ.pop(k, None)

    @patch("sre_copilot.action_tools.requests.get")
    @patch("sre_copilot.action_tools.requests.post")
    def test_transition_by_name(self, mock_post, mock_get):
        # GET /transitions 返 [{id, name}]
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.json.return_value = {
            "transitions": [
                {"id": "11", "name": "进行中"},
                {"id": "21", "name": "已完成",
                 "to": {"name": "已完成"}},
            ],
        }
        mock_get.return_value = mock_get_resp

        # POST /transitions 返 204
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 204
        mock_post.return_value = mock_post_resp

        result = update_incident_status(
            "INC-1", "已完成", scopes=[REQUIRED_SCOPE],
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["transition_id"], "21")
        # 验证 Basic auth
        auth = mock_post.call_args.kwargs["headers"]["Authorization"]
        expected = "Basic " + base64.b64encode(
            b"test@example.com:fake-token",
        ).decode()
        self.assertEqual(auth, expected)

    @patch("sre_copilot.action_tools.requests.get")
    def test_no_matching_transition(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "transitions": [{"id": "11", "name": "进行中"}],
        }
        mock_get.return_value = mock_resp

        with self.assertRaises(ConfigError):
            update_incident_status(
                "INC-1", "不存在的状态",
                scopes=[REQUIRED_SCOPE],
            )

    @patch("sre_copilot.action_tools.requests.get")
    def test_transitions_404(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "issue not found"
        mock_get.return_value = mock_resp

        from sre_copilot.action_tools import JiraError
        with self.assertRaises(JiraError):
            update_incident_status(
                "INC-999", "已完成",
                scopes=[REQUIRED_SCOPE],
            )


class TestJiraCommentRealCall(unittest.TestCase):
    def setUp(self):
        os.environ["SRE_DRY_RUN"] = "false"
        os.environ["JIRA_URL"] = "https://corp.atlassian.net"
        os.environ["JIRA_EMAIL"] = "test@example.com"
        os.environ["JIRA_TOKEN"] = "fake-token"

    def tearDown(self):
        os.environ["SRE_DRY_RUN"] = "true"
        for k in ("JIRA_URL", "JIRA_EMAIL", "JIRA_TOKEN"):
            os.environ.pop(k, None)

    @patch("sre_copilot.action_tools.requests.post")
    def test_plain_text_wrapped_to_adf(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": "10001"}
        mock_post.return_value = mock_resp

        result = create_incident_comment(
            "INC-1", "AI 已完成",
            scopes=[REQUIRED_SCOPE],
        )
        self.assertEqual(result["status"], "success")
        # 验证 body 是 ADF
        sent_body = mock_post.call_args.kwargs["json"]["body"]
        self.assertEqual(sent_body["type"], "doc")
        text = sent_body["content"][0]["content"][0]["text"]
        self.assertEqual(text, "AI 已完成")

    @patch("sre_copilot.action_tools.requests.post")
    def test_adf_passthrough(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": "10002"}
        mock_post.return_value = mock_resp

        adf = {
            "version": 1, "type": "doc",
            "content": [{"type": "paragraph",
                         "content": [{"type": "text", "text": "x"}]}],
        }
        create_incident_comment(
            "INC-1", adf, scopes=[REQUIRED_SCOPE],
        )
        self.assertEqual(
            mock_post.call_args.kwargs["json"]["body"], adf,
        )


# ─────────────────── tool_dispatcher ───────────────────

class TestDispatcher(unittest.TestCase):
    """Executor.tool_dispatcher 用这个分发到 4 个 tool。"""

    def test_dispatch_restart(self):
        async def go():
            return await tool_dispatcher({
                "tool": "restart_deployment",
                "args": {"deployment": "api", "namespace": "default"},
                "scopes": [REQUIRED_SCOPE],
            })
        result = _run(go())
        self.assertEqual(result["status"], "dry_run")

    def test_dispatch_unknown_tool(self):
        async def go():
            return await tool_dispatcher({
                "tool": "delete_database",
                "args": {},
                "scopes": [REQUIRED_SCOPE],
            })
        with self.assertRaises(ConfigError):
            _run(go())

    def test_dispatch_injects_default_scope(self):
        # 不传 scope → 默认注入 [sre:execute]
        async def go():
            return await tool_dispatcher({
                "tool": "restart_deployment",
                "args": {"deployment": "x"},
                # scopes 故意不给
            })
        # 应通过 scope 校验(因为默认注入)
        result = _run(go())
        self.assertEqual(result["status"], "dry_run")


# ─────────────────── K8s 真接(mock) ───────────────────

class TestK8sRestartRealCall(unittest.TestCase):
    """restart_deployment DRY_RUN=false → 调 K8s SDK。"""

    def setUp(self):
        os.environ["SRE_DRY_RUN"] = "false"

    def tearDown(self):
        os.environ["SRE_DRY_RUN"] = "true"

    def test_no_kubeconfig(self):
        with patch("os.path.exists", return_value=False):
            from sre_copilot.action_tools import ConfigError
            with self.assertRaises(ConfigError):
                restart_deployment(
                    "api", "default", scopes=[REQUIRED_SCOPE],
                )


if __name__ == "__main__":
    unittest.main()
