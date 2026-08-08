"""faq plugin 单元测试。"""
import json
import unittest

from faq import retriever as r
from CorpAI.platform.plugin_manager import PluginRegistry
from faq.plugin import register, AGENT_MANIFEST, QUERY_TOOL


class TestRetriever(unittest.TestCase):
    def setUp(self):
        r._DOC_STORE.clear()
        # 用 default collection(None 走 _DEFAULT_COLLECTION="faq_docs"),test_query_default 也 match
        r.add_document("员工每年 10 天年假,工作满 5 年增至 15 天。")
        r.add_document("缺勤须提前 1 天在 OA 提交申请。")
        r.add_document("差旅费 30 天内提交报销,需发票+出差审批单。")

    def test_query_empty(self):
        r._DOC_STORE.clear()
        data = json.loads(r.query_faq("anything"))
        self.assertEqual(data["status"], "no_data")

    def test_query_keyword_match(self):
        data = json.loads(r.query_faq("年假"))
        self.assertEqual(data["status"], "success")
        self.assertTrue(any("年假" in d["text"] for d in data["data"]))

    def test_query_no_match(self):
        data = json.loads(r.query_faq("完全不相关的关键词 xyz123"))
        self.assertEqual(data["status"], "no_data")

    def test_query_limit(self):
        # 加 5 条 docs,limit=2 只返 2
        for i in range(5):
            r.add_document(f"年假政策第{i}条")
        data = json.loads(r.query_faq("年假", limit=2))
        self.assertLessEqual(len(data["data"]), 2)


class TestPrompts(unittest.TestCase):
    def test_summarize_faq(self):
        from faq.prompts import summarize_faq, FAQ_LLM_PROMPT
        p = summarize_faq()
        self.assertIn("query", p.input_variables)
        self.assertTrue(len(FAQ_LLM_PROMPT) > 0)


class TestRegister(unittest.TestCase):
    def test_register_2_manifests(self):
        r._DOC_STORE.clear()
        r.add_document("test", collection="t1")
        reg = PluginRegistry()
        register(reg)
        self.assertEqual(len(reg.list_all()), 2)
        self.assertEqual(reg.get("faq").endpoint, "http://localhost:5030")
        self.assertEqual(reg.get("faq_query_mcp").mcp_tool_name, "query_faq")


if __name__ == "__main__":
    unittest.main()
