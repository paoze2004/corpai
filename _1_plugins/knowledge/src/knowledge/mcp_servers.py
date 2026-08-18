"""knowledge MCP servers — 官方 MCP 协议实现(fastmcp 3.x)。

暴露 retriever.py 的语义检索为标准 MCP tools。
StreamableHTTP transport, JSON-RPC 2.0 wire。

启动方式:`python -m knowledge.mcp_main`
"""
from __future__ import annotations

import logging
from typing import Optional

from fastmcp import FastMCP

from knowledge import retriever as r

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════
#  :8030 ─ Knowledge 检索
# ═══════════════════════════════════════════════════════════════════════

knowledge_server = FastMCP(
    name="knowledge",
    instructions=(
        "Knowledge 检索服务:基于 Milvus 的语义检索 RAG。"
        "需要 faq:read scope。"
    ),
)


@knowledge_server.tool()
def query_knowledge(
    query_text: str,
    collection: Optional[str] = None,
    limit: int = 3,
) -> str:
    """语义检索(Milvus 优先,不可达时返错误 envelope)。

    Args:
        query_text: 查询文本
        collection: collection 名(可选,默认 knowledge_docs)
        limit: 返回 top 几(默认 3)
    """
    return r.query_knowledge(
        query_text=query_text, collection=collection, limit=limit,
    )


@knowledge_server.tool()
def add_document(
    text: str,
    collection: Optional[str] = None,
    doc_id: Optional[str] = None,
) -> str:
    """注入 1 条 doc 到 in-memory store。Milvus upsert 走 seed.py。

    Args:
        text: 文档文本
        collection: collection 名(可选)
        doc_id: 文档 ID(可选,默认 hash(text))
    """
    return r.add_document(text=text, collection=collection, doc_id=doc_id)


SERVER_PORTS = [
    (knowledge_server, 8030),
]