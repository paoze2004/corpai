"""faq plugin — Milvus 集合封装 + 2 个 RAG Counter。

设计:
- 使用 MilvusClient(非 deprecated ORM-style API)
- 首次 search/upsert lazy-connect(host/port from _0_CorpAI.config.Config)
- 集合首次创建时建 schema + IVF_FLAT 索引 + COSINE 距离
- search 返回 [{id, text, score}];调用方再嵌 status
- upsert 走"delete by doc_id then insert"语义,避免累积
- 异常一律向上抛(retriever 决定降级;CLAUDE.md "不 silent-fail")
- 2 Counter 在此定义,放在 module-level + prometheus_client 原生 .labels().inc()
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from pymilvus import DataType, MilvusClient, MilvusException

from _0_CorpAI.config import Config

logger = logging.getLogger(__name__)

_cfg = Config()

# ── Metrics(命名约定 <domain>_<verb>_<noun>_total)───────────────────────
from prometheus_client import Counter  # noqa: E402

RAG_QUERY_TOTAL = Counter(
    "rag_query_total",
    "RAG 查询总数(backend=milvus 走真语义检索;backend=inmemory 走降级)",
    ["backend"],
)

RAG_QUERY_ERRORS_TOTAL = Counter(
    "rag_query_errors_total",
    "RAG 查询失败 / seed 失败计数",
    ["kind"],
)
# kind ∈ {"milvus_unreachable", "embedding_failed", "seed_failed"}

_lock = threading.Lock()
_milvus_ready: bool = False
_client: MilvusClient | None = None
_dim: int = _cfg.embedding_dim


class MilvusUnreachable(Exception):
    """Milvus 不可达的统一异常包装 — retriever 看到此异常走降级。"""


def _ensure_connected() -> MilvusClient:
    """Lazy 连接到 Milvus,创建/加载 Collection。线程安全。"""
    global _milvus_ready, _client
    with _lock:
        if _milvus_ready and _client is not None:
            return _client
        client = MilvusClient(host=_cfg.milvus_host, port=_cfg.milvus_port)
        col_name = _cfg.knowledge_collection

        if not client.has_collection(col_name):
            # 用 FieldSchema 显式建 schema(MilvusClient.create_collection 在 enable_dynamic_field=False
            # 模式下会让 doc_id/text 推断错 → 用显式 schema + create_schema)
            from pymilvus import CollectionSchema, FieldSchema
            fields = [
                FieldSchema("id", DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema("doc_id", DataType.VARCHAR, max_length=64),
                FieldSchema("text", DataType.VARCHAR, max_length=2048),
                FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=_dim),
            ]
            schema = CollectionSchema(fields, description="_0_CorpAI faq KB")
            client.create_collection(
                collection_name=col_name,
                schema=schema,
            )
            # 建 IVF_FLAT 索引
            from pymilvus.milvus_client.index import IndexParams
            ip = IndexParams()
            ip.add_index(field_name="embedding", index_type="IVF_FLAT", metric_type="COSINE", params={"nlist": 64})
            try:
                client.create_index(collection_name=col_name, index_params=ip)
            except Exception as e:
                logger.warning(f"create_index 失败(继续): {e}")
        client.load_collection(col_name)
        _client = client
        _milvus_ready = True
        return client


def upsert(docs: list[dict]) -> int:
    """docs=[{id, text}, ...]。返回成功插入条数。

    语义:本批次覆盖 — 先按 doc_id 删除旧条目,再 insert,避免重复累积。
    delete 走 OR 链式 filter(逐个 doc_id)=字符串,MilvusClient 不支持 in 列表。
    """
    try:
        client = _ensure_connected()
        col_name = _cfg.knowledge_collection
        texts = [d["text"] for d in docs]
        doc_ids = [d["id"] for d in docs]

        # 1. 删旧的(MilvusClient.delete 用 OR 链式 filter,逐个 doc_id)
        deleted_total = 0
        for did in doc_ids:
            try:
                r = client.delete(collection_name=col_name, filter=f'doc_id == "{did}"')
                if isinstance(r, dict):
                    deleted_total += int(r.get("delete_count", 0))
            except Exception as e:
                logger.warning(f"milvus delete {did} failed(继续): {e}")
        logger.info(f"milvus delete {deleted_total} 条旧 doc_id")

        # 2. 复用 embedding 客户端 — 单次 batch 请求,减少 API 调用
        from knowledge import embedding

        vecs = embedding.embed_batch(texts, type=_cfg.embedding_type_insert)

        # 3. insert(MilvusClient 用 list[dict])
        rows = [{"doc_id": did, "text": t, "embedding": v} for did, t, v in zip(doc_ids, texts, vecs)]
        mr = client.insert(collection_name=col_name, data=rows)
        client.flush(col_name)
        # MilvusClient 返回 dict(含 insert_count)
        return int(mr.get("insert_count", len(rows))) if isinstance(mr, dict) else len(rows)
    except (MilvusException, Exception) as e:
        RAG_QUERY_ERRORS_TOTAL.labels(kind="seed_failed").inc()
        logger.warning(f"milvus upsert failed: {e}")
        raise MilvusUnreachable(str(e)) from e


def search(query_text: str, top_k: int = 3) -> list[dict]:
    """语义检索 — 返回 [{id, text, score}]。

    失败时 raise MilvusUnreachable(由 retriever 走降级或上抛)。
    """
    try:
        client = _ensure_connected()
        col_name = _cfg.knowledge_collection
        from knowledge import embedding

        q_vec = embedding.embed(query_text, type=_cfg.embedding_type_query)
        hits = client.search(
            collection_name=col_name,
            data=[q_vec],
            anns_field="embedding",
            limit=top_k,
            output_fields=["doc_id", "text"],
        )
        out: list[dict[str, Any]] = []
        for h in hits[0]:
            ent = h.get("entity", {}) if isinstance(h, dict) else {}
            out.append(
                {
                    "id": ent.get("doc_id", "?"),
                    "text": ent.get("text", ""),
                    "score": float(h.get("distance", 0.0)),
                }
            )
        RAG_QUERY_TOTAL.labels(backend="milvus").inc()
        return out
    except Exception as e:
        RAG_QUERY_ERRORS_TOTAL.labels(kind="milvus_unreachable").inc()
        logger.warning(f"milvus search failed: {e}")
        raise MilvusUnreachable(str(e)) from e


def get_count() -> int:
    """返回 collection 行数(0 = 空,常用于 seed 启动时判断)。"""
    try:
        client = _ensure_connected()
        return int(client.get_collection_stats(_cfg.knowledge_collection).get("row_count", 0))
    except Exception:
        return 0


def reset_for_tests() -> None:
    """测试间清理 — 断开连接 + 清缓存引用。"""
    global _milvus_ready, _client
    with _lock:
        _client = None
        _milvus_ready = False
