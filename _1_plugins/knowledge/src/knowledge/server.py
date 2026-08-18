"""faq plugin A2A Server — Phase 5 简化版。"""
from __future__ import annotations

import json
import logging
from typing import Any

from knowledge import retriever as r
from knowledge.prompts import FAQ_LLM_PROMPT
from langchain_openai import ChatOpenAI
from python_a2a import A2AServer, AgentCard, AgentSkill, Task, TaskStatus, TaskState, TextContent

from _0_CorpAI.config import Config

logger = logging.getLogger(__name__)


def _extract_text(task: Task) -> str:
    """从 task.message(dict)里提取文本 — 兼容 Google A2A parts + 标准 content 两种 wire 格式。"""
    msg = task.message
    if not msg or not isinstance(msg, dict):
        return ""
    if "parts" in msg and isinstance(msg["parts"], list):
        chunks: list[str] = []
        for part in msg["parts"]:
            if isinstance(part, dict) and part.get("type") == "text":
                chunks.append(part.get("text", ""))
        return "".join(chunks)
    content = msg.get("content")
    if isinstance(content, dict):
        return content.get("text", "") or ""
    if isinstance(content, str):
        return content
    return ""


class KnowledgeServer(A2AServer):
    """Phase 5 简化版 A2A:关键词路由 + retriever 调。"""

    def __init__(self, llm: ChatOpenAI | None = None):
        card = AgentCard(
            name="knowledge",
            description="FAQ RAG — 跨企业文档语义检索",
            url="http://localhost:5030",
            version="1.0.0",
            skills=[
                AgentSkill(id="knowledge", name="FAQ 检索", description="基于 Milvus 检索 + LLM 改写"),
            ],
        )
        super().__init__(agent_card=card)
        self.llm = llm or ChatOpenAI(
            model=Config().model_name,
            api_key=Config().api_key,
            base_url=Config().base_url,
            temperature=0.1,
        )

    def handle_task(self, task: Task) -> Task:
        try:
            text = _extract_text(task)
            if not text.strip():
                return Task(id=task.id, status=TaskStatus(state=TaskState.FAILED, message=task.message))
            # FAQ server 直接全文转给 query_knowledge 做 substring + token overlap
            response = r.query_knowledge(text, limit=3)
            return Task(
                id=task.id,
                status=TaskStatus(state=TaskState.COMPLETED, message=task.message),
                artifacts=[{"parts": [{"type": "text", "text": response}]}],
            )
        except Exception:
            logger.exception("faq handle_task failed")
            return Task(id=task.id, status=TaskStatus(state=TaskState.FAILED, message=task.message))


# Phase 5 简化:Phase 6 接真 Milvus
def add_doc_for_testing(text: str, collection: str = None) -> str:
    """Phase 5 暴露的 ingest helper,测试时用。"""
    return r.add_document(text, collection)
