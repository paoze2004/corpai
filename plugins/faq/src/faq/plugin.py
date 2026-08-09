"""faq plugin — 2 manifest + register(RAG)。"""
from CorpAI.platform.plugin_manager import PluginManifest, PluginRegistry

from faq.prompts import FAQ_LLM_PROMPT

AGENT_MANIFEST = PluginManifest(
    name="faq",
    version="1.1.0",
    description="FAQ RAG:跨企业 KB 语义检索(Milvus + MiniMax embo-01 embedding;查询 Milvus 不可达时硬失败)。",
    plugin_type="llm_agent",
    endpoint="http://localhost:5030",
    llm_prompt=FAQ_LLM_PROMPT,
    summary_prompt="summarize_faq",
    required_intents=["faq"],
    permissions=["faq:read"],
    tags=["rag", "knowledge-base", "search", "milvus", "embedding"],
)

QUERY_TOOL = PluginManifest(
    name="faq_query_mcp",
    version="1.1.0",
    description="Milvus 语义检索 — query_faq(query_text, collection=None, limit=3)。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8030",
    mcp_tool_name="query_faq",
    permissions=["faq:read"],
    tags=["rag", "milvus", "embedding"],
)


def register(registry: PluginRegistry) -> None:
    for m in (AGENT_MANIFEST, QUERY_TOOL):
        registry.register(m)
