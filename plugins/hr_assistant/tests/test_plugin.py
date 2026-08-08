"""hr_assistant plugin 单元测试。"""
import json
import unittest

from hr_assistant import tools as t
from CorpAI.platform.plugin_manager import PluginRegistry
from hr_assistant.plugin import register, AGENT_MANIFEST, INSURANCE_TOOL, POLICY_TOOL


class TestInsurance(unittest.TestCase):
    def test_query_all(self):
        data = json.loads(t.query_insurance())
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]), 3)

    def test_query_filter(self):
        data = json.loads(t.query_insurance(insurance_type="医疗"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]), 1)
        self.assertEqual(data["data"][0]["id"], "I002")


class TestPolicy(unittest.TestCase):
    def test_query_all(self):
        data = json.loads(t.query_policy())
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]), 5)

    def test_query_filter(self):
        data = json.loads(t.query_policy(topic="年假"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"][0]["id"], "P001")

    def test_query_no_match(self):
        data = json.loads(t.query_policy(topic="不存在的policy_keyword_xyz"))
        self.assertEqual(data["status"], "no_data")


class TestPrompts(unittest.TestCase):
    def test_summarize_insurance(self):
        from hr_assistant.prompts import summarize_insurance, HR_ASSISTANT_LLM_PROMPT
        p = summarize_insurance()
        self.assertIn("query", p.input_variables)

    def test_summarize_policy(self):
        from hr_assistant.prompts import summarize_policy
        p = summarize_policy()
        self.assertIn("query", p.input_variables)

    def test_llm_prompt_exists(self):
        from hr_assistant.prompts import HR_ASSISTANT_LLM_PROMPT
        self.assertTrue(len(HR_ASSISTANT_LLM_PROMPT) > 0)


class TestRegister(unittest.TestCase):
    def test_register_3_manifests(self):
        r = PluginRegistry()
        register(r)
        self.assertEqual(len(r.list_all()), 3)
        self.assertEqual(r.get("hr_assistant").permissions, ["hr:read", "hr:write"])
        self.assertEqual(r.get("hr_assistant_policy_mcp").mcp_tool_name, "query_policy")


if __name__ == "__main__":
    unittest.main()
