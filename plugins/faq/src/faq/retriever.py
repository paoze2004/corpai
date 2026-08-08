"""faq plugin Milvus RAG — Phase 5 简化版(可选 Milvus,无则降级内存搜索)。"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Phase 5:无 Milvus 时降级 — 简单内存 doc store(用 SHA1 做 similarity)
_DOC_STORE: dict[str, list[dict]] = {}

try:
    from CorpAI.config import Config
    _DEFAULT_COLLECTION = Config().faq_collection if hasattr(Config, "faq_collection") else "faq_docs"
except Exception:
    _DEFAULT_COLLECTION = os.getenv("FAQ_COLLECTION", "faq_docs")


def _get_collection(name: str) -> list[dict]:
    return _DOC_STORE.setdefault(name, [])


def add_document(text: str, collection: str = None, doc_id: str = None) -> str:
    """Phase 5 ingest 入口:添加 1 条 doc 到 collection。"""
    name = collection or _DEFAULT_COLLECTION
    doc_id = doc_id or hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    _get_collection(name).append({"id": doc_id, "text": text})
    return doc_id


def query_faq(query_text: str, collection: str = None, limit: int = 3) -> str:
    """Phase 5 简化 RAG:无 Milvus 时做子串 + token overlap scoring。

    Phase 6 集成 pymilvus 重写为真 Milvus 语义检索。
    """
    name = collection or _DEFAULT_COLLECTION
    items = _get_collection(name)
    if not items:
        return json.dumps({
            "status": "no_data",
            "data": [],
            "message": "collection 为空,先用 add_document 注入文档。",
        }, ensure_ascii=False)
    # Phase 5 简化:对 CJK 文本用子串包含,英文/数字用 token overlap
    q = query_text.strip()
    q_lower = q.lower()
    q_tokens = set(q_lower.split())
    scored = []
    for it in items:
        doc = it["text"]
        doc_lower = doc.lower()
        # 子串匹配(对 CJK 友好)
        substring_hit = 1 if q in doc or q_lower in doc_lower else 0
        # token overlap(对英文友好)
        doc_tokens = set(doc_lower.split())
        token_overlap = len(q_tokens & doc_tokens)
        score = substring_hit * 100 + token_overlap
        if score > 0:
            scored.append((score, it))
    scored.sort(key=lambda x: -x[0])
    top = [it for _, it in scored[:limit]]
    return json.dumps({
        "status": "success" if top else "no_data",
        "data": top,
        "message": "" if top else "未找到匹配的 FAQ 文档。",
    }, ensure_ascii=False)
