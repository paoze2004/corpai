"""hr_assistant plugin 单元测试 — v2.0。"""
import json
import unittest

from hr_assistant import tools as t
from CorpAI.platform.plugin_manager import PluginRegistry
from hr_assistant import register


class TestBenefits(unittest.TestCase):
    def test_query_all(self):
        data = json.loads(t.query_benefits())
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]), 18)

    def test_query_by_category(self):
        data = json.loads(t.query_benefits(category="社保"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]), 1)
        self.assertEqual(data["data"][0]["id"], "B001")

    def test_query_by_id(self):
        data = json.loads(t.query_benefits(benefit_id="B005"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"][0]["name"], "MacBook Pro 标配")


class TestPolicy(unittest.TestCase):
    def test_query_all(self):
        data = json.loads(t.query_policy())
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]), 30)

    def test_query_filter(self):
        data = json.loads(t.query_policy(topic="年假"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"][0]["id"], "P001")

    def test_query_no_match(self):
        data = json.loads(t.query_policy(topic="不存在的policy_keyword_xyz"))
        self.assertEqual(data["status"], "no_data")


class TestProcess(unittest.TestCase):
    def test_query_all(self):
        data = json.loads(t.query_process())
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]), 12)

    def test_query_filter(self):
        data = json.loads(t.query_process(topic="离职"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"][0]["id"], "PR001")


class TestOnboarding(unittest.TestCase):
    def test_query_all(self):
        data = json.loads(t.query_onboarding())
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]), 6)

    def test_query_filter(self):
        data = json.loads(t.query_onboarding(topic="面试"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"][0]["id"], "ON001")


class TestCompensation(unittest.TestCase):
    def test_query_all(self):
        data = json.loads(t.query_compensation())
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]), 6)

    def test_query_filter(self):
        data = json.loads(t.query_compensation(topic="年终奖"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"][0]["id"], "C002")


class TestDevelopment(unittest.TestCase):
    def test_query_all(self):
        data = json.loads(t.query_development())
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]), 6)

    def test_query_filter(self):
        data = json.loads(t.query_development(topic="导师"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"][0]["id"], "D004")


class TestWelfare(unittest.TestCase):
    def test_query_all(self):
        data = json.loads(t.query_welfare())
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]), 4)


class TestPrompts(unittest.TestCase):
    def test_summarize_benefits(self):
        from hr_assistant.prompts import summarize_benefits
        p = summarize_benefits()
        self.assertIn("query", p.input_variables)

    def test_summarize_policy(self):
        from hr_assistant.prompts import summarize_policy
        p = summarize_policy()
        self.assertIn("query", p.input_variables)

    def test_llm_prompt_exists(self):
        from hr_assistant.prompts import HR_ASSISTANT_LLM_PROMPT
        self.assertTrue(len(HR_ASSISTANT_LLM_PROMPT) > 0)


class TestRegister(unittest.TestCase):
    def test_register_18_manifests(self):
        r = PluginRegistry()
        register(r)
        self.assertEqual(len(r.list_all()), 18)  # 1 agent + 7 KB + 8 ops + 2 bridge
        self.assertEqual(r.get("hr_assistant").permissions, ["hr:read", "hr:write"])
        self.assertEqual(r.get("hr_assistant_policy_mcp").mcp_tool_name, "query_policy")
        self.assertEqual(r.get("hr_assistant_leave_mcp").mcp_tool_name, "submit_leave")
        self.assertEqual(r.get("hr_assistant_bridge_devops_mcp").permissions, ["hr:write"])

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
