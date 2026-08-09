"""faq plugin — MiniMax embedding 客户端。

设计:
- 单 host(来自 CorpAI.config.Config().embedding_url)
- batch API 一次跑多 text(seed 12 条 → 1 次)
- 模块级 _EMBED_CACHE:dict[text → vector];重启清零
- 网络异常一律 raise,让 milvus_store / retriever 决定降级
- 不重试 5xx(避免拖慢查询)
"""
from __future__ import annotations

import logging

import requests

from CorpAI.config import Config

logger = logging.getLogger(__name__)

_cfg = Config()  # faq plugin 进程单例

_EMBED_CACHE: dict[str, list[float]] = {}


def _post_embed(texts: list[str], input_type: str) -> list[list[float]]:
    """POST /v1/embeddings — MiniMax embo-01 协议(非 OpenAI 兼容)。

    入参 body: {"model", "texts":[...], "type":"db|query"}(type 必须在 body)
    返回: {"vectors": [[float,...],...], "total_tokens": int, "base_resp":{...}}
    type 影响语义检索质量 — db 入库用,query 检索用。

    Raises:
        requests.HTTPError / requests.ConnectionError / KeyError
        让调用方(milvus_store / retriever)决定 fallback。
    """
    body = {
        "model": _cfg.embedding_model_name,
        "texts": texts,
        "type": input_type,
    }
    headers = {
        "Authorization": f"Bearer {_cfg.embedding_api_key}",
        "Content-Type": "application/json",
    }
    resp = requests.post(_cfg.embedding_url, json=body, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data["vectors"]


def embed(text: str, *, type: str = "query") -> list[float]:
    """单条 embedding — query_faq 路径用。命中缓存直接返。"""
    cached = _EMBED_CACHE.get(text)
    if cached is not None:
        return cached
    vecs = _post_embed([text], input_type=type)
    vec = vecs[0]
    _EMBED_CACHE[text] = vec
    return vec


def embed_batch(texts: list[str], *, type: str = "db") -> list[list[float]]:
    """批量 embedding — seed 启动路径。

    1 次 HTTP 拿到所有 texts 的向量;命中缓存的不重算。
    返回 list 与输入 texts 一一对应(同序)。
    """
    out: list[list[float] | None] = []
    missing_idx: list[int] = []
    missing_txt: list[str] = []
    for i, t in enumerate(texts):
        if t in _EMBED_CACHE:
            out.append(_EMBED_CACHE[t])
        else:
            out.append(None)
            missing_idx.append(i)
            missing_txt.append(t)
    if missing_txt:
        new_vecs = _post_embed(missing_txt, input_type=type)
        for i, v in zip(missing_idx, new_vecs):
            _EMBED_CACHE[texts[i]] = v
            out[i] = v
    return [v if v is not None else [] for v in out]


def cache_size() -> int:
    """供测试断言:seed 后 cache 应被填充。"""
    return len(_EMBED_CACHE)


def clear_cache() -> None:
    """测试间清理 — 防止跨测试污染。"""
    _EMBED_CACHE.clear()