"""hr_assistant plugin 单元测试 — v3.0 生产化精简。

删掉 7 类 KB 测试(query_benefits / query_policy / query_process / 等),
新增 action 路由测试,保留 register 测试(11 manifest)。
"""
import json
import os
import unittest

os.environ.setdefault("AUTH_JWT_SECRET", "dev-secret")

from CorpAI.platform.plugin_manager import PluginRegistry
from hr_assistant import register


def _make_token(user_id: str, scopes: list[str]) -> str:
    """生成测试用 JWT。"""
    from CorpAI.platform.auth.tokens import make_access_token
    secret = os.environ.get("AUTH_JWT_SECRET", "dev-secret")
    return make_access_token(user_id, "t1", "default", scopes, secret)


class TestPrompts(unittest.TestCase):
    def test_summarize_action(self):
        from hr_assistant.prompts import summarize_action
        p = summarize_action()
        self.assertIn("query", p.input_variables)

    def test_llm_prompt_focused_on_actions(self):
        """v3.0:Llm prompt 不再提 7 类 KB,只讲 9 操作 + 3 bridge。"""
        from hr_assistant.prompts import HR_ASSISTANT_LLM_PROMPT
        self.assertIn("submit_leave", HR_ASSISTANT_LLM_PROMPT)
        self.assertIn("approve_request", HR_ASSISTANT_LLM_PROMPT)
        self.assertIn("cross_query_faq", HR_ASSISTANT_LLM_PROMPT)
        # 不再提 KB 类玩具
        self.assertNotIn("B001", HR_ASSISTANT_LLM_PROMPT)
        self.assertNotIn("P001", HR_ASSISTANT_LLM_PROMPT)


class TestRegister(unittest.TestCase):
    def test_register_11_manifests_no_kb(self):
        """v3.0:11 manifest = 1 agent + 8 ops + 2 bridge(无 7 KB manifest)。"""
        r = PluginRegistry()
        register(r)
        manifests = r.list_all()
        names = {m.name for m in manifests}
        # 期望:agent + 8 ops + 2 bridge = 11
        self.assertEqual(len(manifests), 11)
        # 7 个 KB manifest 已删
        for kb in ("hr_assistant_benefits_mcp", "hr_assistant_policy_mcp",
                   "hr_assistant_process_mcp", "hr_assistant_onboarding_mcp",
                   "hr_assistant_compensation_mcp", "hr_assistant_development_mcp",
                   "hr_assistant_welfare_mcp"):
            self.assertNotIn(kb, names, f"{kb} 应被删除")
        # 9 ops + 2 bridge 还在
        self.assertIn("hr_assistant_leave_mcp", names)
        self.assertIn("hr_assistant_reim_mcp", names)
        self.assertIn("hr_assistant_cert_mcp", names)
        self.assertIn("hr_assistant_asset_mcp", names)
        self.assertIn("hr_assistant_train_mcp", names)
        self.assertIn("hr_assistant_reg_mcp", names)
        self.assertIn("hr_assistant_approve_mcp", names)
        self.assertIn("hr_assistant_my_mcp", names)
        self.assertIn("hr_assistant_bridge_faq_mcp", names)
        self.assertIn("hr_assistant_bridge_sre_mcp", names)

    def test_register_agent_has_action_scope(self):
        r = PluginRegistry()
        register(r)
        self.assertEqual(r.get("hr_assistant").permissions, ["hr:read", "hr:write"])
        # ops 工具需 hr:write
        self.assertEqual(r.get("hr_assistant_leave_mcp").permissions, ["hr:write"])
        # query_my 是 chat:write
        self.assertEqual(r.get("hr_assistant_my_mcp").permissions, ["chat:write"])

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