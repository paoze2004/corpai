"""faq plugin retriever — Milvus 语义检索(失败 raise,CLAUDE.md 不 silent-fail)。"""
from __future__ import annotations

import hashlib
import json
import logging
import os

logger = logging.getLogger(__name__)

try:
    from CorpAI.config import Config

    _DEFAULT_COLLECTION = Config().faq_collection if hasattr(Config, "faq_collection") else "faq_docs"
except Exception:
    _DEFAULT_COLLECTION = os.getenv("FAQ_COLLECTION", "faq_docs")

# Phase 7+: 保留 fallback _DOC_STORE 给 retriever 内部使用
# (避免 import 循环:milvus_store → embedding → config)
_DOC_STORE: dict[str, list[dict]] = {}


def _get_collection(name: str) -> list[dict]:
    return _DOC_STORE.setdefault(name, [])


def _dedup_append(name: str, doc: dict) -> None:
    """同 id 重复注入视为覆盖(保留先入)。"""
    arr = _get_collection(name)
    if any(d["id"] == doc["id"] for d in arr):
        return
    arr.append(doc)


def add_document(text: str, collection: str | None = None, doc_id: str | None = None) -> str:
    """Ingest 入口 — 1 条 doc 写到 in-memory store。Milvus upsert 走 seed.py。"""
    name = collection or _DEFAULT_COLLECTION
    did = doc_id or hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    _dedup_append(name, {"id": did, "text": text})
    return did


def query_faq(query_text: str, collection: str | None = None, limit: int = 3) -> str:
    """Phase 7 语义检索入口 — Milvus 优先;Milvus 不可达时 raise MilvusUnreachable。

    合同(JSON envelope 不变,summarize_faq prompt 依赖):
    - status ∈ {"success", "no_data"}
    - data: list[{id, text, score}](Milvus 命中)或 list[{id, text}](in-memory)
    - message: 中文提示

    失败处理(用户决定硬失败):
    - Milvus 不可达 → raise MilvusUnreachable,FaqServer 捕获后返 TaskState.FAILED
    - Embedding API 失败 → 同样上抛(网络层异常)
    """
    from faq import milvus_store as ms

    # Milvus 路径
    try:
        hits = ms.search(query_text, top_k=limit)
    except ms.MilvusUnreachable:
        # 硬失败 — 不降级 in-memory(用户决策)
        raise

    if not hits:
        # Milvus 在线但 0 命中 — 返 no_data
        return json.dumps(
            {
                "status": "no_data",
                "data": [],
                "message": "Milvus 中未找到匹配文档。",
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {"status": "success", "data": hits, "message": ""},
        ensure_ascii=False,
    )


def query_faq_inmemory_fallback(query_text: str, collection: str | None = None, limit: int = 3) -> str:
    """降级路径 — 仅供 Milvus 不可达时的测试 / 运维兜底使用,生产 chat 不会走这里。

    与 query_faq 同合同(JSON envelope)。
    """
    from faq import milvus_store as ms

    name = collection or _DEFAULT_COLLECTION
    items = _get_collection(name)
    if not items:
        ms.RAG_QUERY_TOTAL.labels(backend="inmemory").inc()
        return json.dumps(
            {
                "status": "no_data",
                "data": [],
                "message": "collection 为空,先用 add_document 注入文档。",
            },
            ensure_ascii=False,
        )
    q = query_text.strip()
    q_lower = q.lower()
    q_tokens = set(q_lower.split())
    scored: list[tuple[int, dict]] = []
    for it in items:
        doc = it["text"]
        doc_lower = doc.lower()
        substring_hit = 1 if q in doc or q_lower in doc_lower else 0
        doc_tokens = set(doc_lower.split())
        token_overlap = len(q_tokens & doc_tokens)
        score = substring_hit * 100 + token_overlap
        if score > 0:
            scored.append((score, it))
    scored.sort(key=lambda x: -x[0])
    top = [it for _, it in scored[:limit]]
    ms.RAG_QUERY_TOTAL.labels(backend="inmemory").inc()
    return json.dumps(
        {
            "status": "success" if top else "no_data",
            "data": top,
            "message": "" if top else "未找到匹配的 FAQ 文档。",
        },
        ensure_ascii=False,
    )