"""faq plugin 单元测试。

覆盖:
- TestRetriever:query_faq_inmemory_fallback 关键词路径(不依赖 Milvus / embedding)
- TestPrompts:summarize_faq + FAQ_LLM_PROMPT 形状
- TestRegister:2 manifest 注册
- TestEmbedding:embed / embed_batch(用 mock fixture,不真打 API)
- TestMilvusStore:集成测试,需 set FAQ_MILVUS_HOST=localhost + Milvus 在跑
"""
import json
import os
import unittest

import pytest

from _0_CorpAI._2_platform.plugin_manager import PluginRegistry
from knowledge import retriever as r
from knowledge.plugin import AGENT_MANIFEST, QUERY_TOOL, register


# ──────────────────────────────────────────────────────────────────
# Fallback / in-memory 路径(不依赖 Milvus)
# ──────────────────────────────────────────────────────────────────


class TestRetriever(unittest.TestCase):
    """query_faq_inmemory_fallback 的关键词打分路径测试。"""

    def setUp(self):
        r._DOC_STORE.clear()

    def _seed(self):
        r.add_document("员工每年 10 天年假,工作满 5 年增至 15 天。")
        r.add_document("缺勤须提前 1 天在 OA 提交申请。")
        r.add_document("差旅费 30 天内提交报销,需发票+出差审批单。")

    def test_fallback_empty(self):
        data = json.loads(r.query_faq_inmemory_fallback("anything"))
        self.assertEqual(data["status"], "no_data")

    def test_fallback_keyword_match(self):
        self._seed()
        data = json.loads(r.query_faq_inmemory_fallback("年假"))
        self.assertEqual(data["status"], "success")
        self.assertTrue(any("年假" in d["text"] for d in data["data"]))

    def test_fallback_no_match(self):
        self._seed()
        data = json.loads(r.query_faq_inmemory_fallback("完全不相关的关键词 xyz123"))
        self.assertEqual(data["status"], "no_data")

    def test_fallback_limit(self):
        self._seed()
        for i in range(5):
            r.add_document(f"年假政策第{i}条")
        data = json.loads(r.query_faq_inmemory_fallback("年假", limit=2))
        self.assertLessEqual(len(data["data"]), 2)


class TestPrompts(unittest.TestCase):
    def test_summarize_faq(self):
        from knowledge.prompts import FAQ_LLM_PROMPT, summarize_faq

        p = summarize_faq()
        self.assertIn("query", p.input_variables)
        self.assertTrue(len(FAQ_LLM_PROMPT) > 0)


class TestRegister(unittest.TestCase):
    def test_register_2_manifests(self):
        reg = PluginRegistry()
        register(reg)
        self.assertEqual(len(reg.list_all()), 2)
        self.assertEqual(reg.get("knowledge").endpoint, "http://localhost:5030")
        self.assertEqual(reg.get("knowledge_query_mcp").mcp_tool_name, "query_knowledge")

    def test_manifest_has_required_intent_and_perms(self):
        self.assertIn("knowledge", AGENT_MANIFEST.required_intents)
        self.assertIn("knowledge:read", AGENT_MANIFEST.permissions)
        self.assertIn("knowledge:read", QUERY_TOOL.permissions)


# ──────────────────────────────────────────────────────────────────
# Embedding(用 mock fixture,不真打 API)
# ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_embedding_response(monkeypatch):
    """挡掉真实 MiniMax /v1/embeddings 调用,返回 deterministic 1536 维向量。"""
    from knowledge import embedding

    def fake_post(texts, input_type):
        # MiniMax 协议:返 {"vectors": [...]}。fixture 直接返 vectors 列表。
        return [
            [1.0 if (hash(t) % 1536) == i else 0.0 for i in range(1536)]
            for t in texts
        ]

    monkeypatch.setattr(embedding, "_post_embed", fake_post)
    embedding.clear_cache()
    yield
    embedding.clear_cache()


class TestEmbedding:
    """Pytest 风格 — 用 fixture。"""

    def test_embed_returns_1536_dim(self, mock_embedding_response):
        from knowledge import embedding

        v = embedding.embed("hello", type="query")
        assert len(v) == 1536
        assert all(isinstance(x, float) for x in v)

    def test_embed_batch_preserves_order(self, mock_embedding_response):
        from knowledge import embedding

        vecs = embedding.embed_batch(["alpha", "beta", "gamma"], type="db")
        assert len(vecs) == 3
        assert all(len(v) == 1536 for v in vecs)

    def test_embed_cache_hit(self, mock_embedding_response):
        from knowledge import embedding

        embedding.embed("cached_text", type="query")
        size_before = embedding.cache_size()
        embedding.embed("cached_text", type="query")  # 第二次走 cache
        # cache size 不变(fake_post 不被再调)
        assert embedding.cache_size() == size_before


# ──────────────────────────────────────────────────────────────────
# Milvus 集成测试(需 FAQ_MILVUS_HOST + 端口可达)
# ──────────────────────────────────────────────────────────────────

_MILVUS_SKIP_REASON = (
    "set FAQ_MILVUS_HOST=localhost (or remote IP) "
    "+ Milvus :19530 跑起来才跑该 case"
)


@pytest.mark.skipif(
    not os.getenv("FAQ_MILVUS_HOST"), reason=_MILVUS_SKIP_REASON
)
class TestMilvusStore:
    """Milvus 集成测试 — 需要 corpai-milvus 容器在跑。"""

    def test_upsert_and_search_round_trip(self, mock_embedding_response):
        from knowledge import milvus_store as ms

        ms.reset_for_tests()
        docs = [{"id": "T001", "text": "远程办公设备申请流程。"}, {"id": "T002", "text": "VPN 工单审批。"}]
        ms.upsert(docs)
        # 同一个 fixture mock 了 embedding,所以两个文本映射成不同 vector
        hits = ms.search("远程办公", top_k=2)
        assert isinstance(hits, list)
        ms.reset_for_tests()

    def test_search_returns_top_k(self, mock_embedding_response):
        from knowledge import milvus_store as ms

        ms.reset_for_tests()
        docs = [{"id": f"T{i:03d}", "text": f"测试文档 {i}"} for i in range(5)]
        ms.upsert(docs)
        hits = ms.search("测试", top_k=3)
        assert len(hits) <= 3
        ms.reset_for_tests()


if __name__ == "__main__":
    unittest.main()