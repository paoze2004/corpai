"""faq plugin — MiniMax embedding 客户端(httpx + Redis 双层缓存)。

设计要点(对比 enterprise_qa 的 redis_client.py):
- L1:进程内 dict cache(热路径,零网络)
- L2:Redis cache(跨进程共享,重启不丢,7 天 TTL 兜底)
- Lazy expire refresh:命中时调用 EXPIRE 续期(enterprise_qa 风格"惰性延期",
  热问题永不淘汰,冷问题 7 天后自动清)
- httpx.Client 同步单例(连接池复用,KnowledgeServer Flask 进程跑),
  改 httpx 而非 requests:TCP 连接复用 + 超时/重试统一管理

依赖:httpx / redis 均在主 pyproject.toml(Phase 6 统一管理)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from typing import Any

import httpx
import redis

from _0_CorpAI.config import Config
from _0_CorpAI._2_platform.observability.metrics import (
    EMBEDDING_CACHE_HIT_TOTAL,
    EMBEDDING_REQUEST_SECONDS,
)

logger = logging.getLogger(__name__)
_cfg = Config()  # faq plugin 进程单例

# ── L1 缓存(进程内,hot path)────────────────────────────
_EMBED_CACHE_L1: dict[str, list[float]] = {}

# ── L2 缓存(Redis,跨进程共享)─────────────────────────
_REDIS: "redis.Redis | None" = None
_REDIS_TRIED: bool = False  # 试过连一次,失败就不再重试(避免每次都阻塞启动)
_REDIS_LOCK = threading.Lock()

# TTL(s):db 类型 KB 文档基本不变,7 天;query 类型一般热问题复用,24h + lazy 续期
_TTL_KB = 7 * 24 * 3600
_TTL_QUERY = 24 * 3600

# ── httpx 客户端(同步,连接池复用)──────────────────────
_HTTPX: httpx.Client | None = None
_HTTPX_LOCK = threading.Lock()


def _get_httpx() -> httpx.Client:
    """懒初始化 httpx 客户端;带连接池,faq 进程并发检索时复用 TCP。"""
    global _HTTPX
    if _HTTPX is None:
        with _HTTPX_LOCK:
            if _HTTPX is None:
                _HTTPX = httpx.Client(
                    timeout=httpx.Timeout(10.0, connect=3.0),
                    limits=httpx.Limits(
                        max_connections=20,
                        max_keepalive_connections=5,
                    ),
                )
    return _HTTPX


def _get_redis() -> "redis.Redis | None":
    """懒初始化 Redis 客户端(同步版)。失败降级为 L1-only,不打 ERROR 噪声。"""
    global _REDIS, _REDIS_TRIED
    if _REDIS is not None:
        return _REDIS
    if _REDIS_TRIED:
        return None
    with _REDIS_LOCK:
        if _REDIS_TRIED:
            return None
        url = os.getenv("REDIS_URL", "").strip()
        if not url:
            logger.debug("REDIS_URL 未配置,跳过 L2 embedding 缓存")
            _REDIS_TRIED = True
            return None
        try:
            client = redis.Redis.from_url(url, decode_responses=False)
            client.ping()
            _REDIS = client
            logger.info("embedding L2 缓存启用(Redis OK)")
        except Exception as exc:
            logger.warning(f"Redis 不可用,L2 缓存降级为 L1-only: {exc}")
            _REDIS = None
        finally:
            _REDIS_TRIED = True
    return _REDIS


def _ttl_for(type_: str) -> int:
    return _TTL_KB if type_ == "db" else _TTL_QUERY


def _cache_key(text: str, type_: str) -> str:
    """缓存 key — 含 model 名 + type 避免切换 embedding 模型时污染。

    sha1 截 16 位足够(hash 冲突概率 < 1/2^64,KB 量级可忽略)。
    """
    h = hashlib.sha1(
        f"{_cfg.embedding_model_name}|{type_}|{text}".encode("utf-8")
    ).hexdigest()[:16]
    return f"emb:{_cfg.embedding_model_name}:{type_}:{h}"


def _post_embed(texts: list[str], input_type: str) -> list[list[float]]:
    """POST /v1/embeddings — MiniMax embo-01 协议(非 OpenAI 兼容)。

    入参 body: {"model", "texts":[...], "type":"db|query"}(type 必须在 body)
    返回: {"vectors": [[float,...],...], "total_tokens": int, "base_resp":{...}}
    type 影响语义检索质量 — db 入库用,query 检索用。

    Raises:
        httpx.HTTPError / redis.RedisError 让调用方(milvus_store / retriever)决定 fallback。
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
    with EMBEDDING_REQUEST_SECONDS.labels(type=input_type).time():
        resp = _get_httpx().post(_cfg.embedding_url, json=body, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    return data["vectors"]


def _l2_get(key: str, type_: str) -> "list[float] | None":
    """Redis 读 + lazy expire 续期(enterprise_qa 模式)。

    命中后调 expire(key, TTL) 让热 key 永不淘汰,冷 key 自然 24h/7d 后过期。
    """
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = r.get(key)
        if raw is None:
            return None
        r.expire(key, _ttl_for(type_))  # lazy 续期
        return json.loads(raw)
    except Exception as exc:
        logger.debug(f"Redis L2 get 失败({exc.__class__.__name__}): {exc}")
        return None


def _l2_set(key: str, vec: list[float], type_: str) -> None:
    """Redis 写。失败仅 debug 级别(L1 命中即可服务)。"""
    r = _get_redis()
    if r is None:
        return
    try:
        r.set(key, json.dumps(vec), ex=_ttl_for(type_))
    except Exception as exc:
        logger.debug(f"Redis L2 set 失败({exc.__class__.__name__}): {exc}")


def embed(text: str, *, type: str = "query") -> list[float]:
    """单条 embedding — query_knowledge 路径用。

    查找顺序:L1 → L2 → API。命中即返;未命中调 API 后回填两级缓存。
    """
    key = _cache_key(text, type)
    # L1
    if key in _EMBED_CACHE_L1:
        EMBEDDING_CACHE_HIT_TOTAL.labels(layer="l1").inc()
        return _EMBED_CACHE_L1[key]
    # L2
    cached = _l2_get(key, type)
    if cached is not None:
        EMBEDDING_CACHE_HIT_TOTAL.labels(layer="l2").inc()
        _EMBED_CACHE_L1[key] = cached
        return cached
    # miss → API
    EMBEDDING_CACHE_HIT_TOTAL.labels(layer="miss").inc()
    vecs = _post_embed([text], input_type=type)
    vec = vecs[0]
    _EMBED_CACHE_L1[key] = vec
    _l2_set(key, vec, type)
    return vec


def embed_batch(texts: list[str], *, type: str = "db") -> list[list[float]]:
    """批量 embedding — seed 启动路径。

    1 次 HTTP 拿到所有未命中 texts 的向量;命中缓存的不重算(L1 + L2 双重查)。
    返回 list 与输入 texts 一一对应(同序)。
    """
    out: list[list[float] | None] = []
    missing_idx: list[int] = []
    missing_txt: list[str] = []
    for i, t in enumerate(texts):
        key = _cache_key(t, type)
        # L1
        if key in _EMBED_CACHE_L1:
            EMBEDDING_CACHE_HIT_TOTAL.labels(layer="l1").inc()
            out.append(_EMBED_CACHE_L1[key])
            continue
        # L2
        cached = _l2_get(key, type)
        if cached is not None:
            EMBEDDING_CACHE_HIT_TOTAL.labels(layer="l2").inc()
            _EMBED_CACHE_L1[key] = cached
            out.append(cached)
            continue
        # miss
        EMBEDDING_CACHE_HIT_TOTAL.labels(layer="miss").inc()
        out.append(None)
        missing_idx.append(i)
        missing_txt.append(t)
    if missing_txt:
        new_vecs = _post_embed(missing_txt, input_type=type)
        for i, v in zip(missing_idx, new_vecs):
            key = _cache_key(texts[i], type)
            _EMBED_CACHE_L1[key] = v
            _l2_set(key, v, type)
            out[i] = v
    return [v if v is not None else [] for v in out]


def cache_size() -> int:
    """供测试断言:seed 后 L1 cache 应被填充。"""
    return len(_EMBED_CACHE_L1)


def clear_cache() -> None:
    """测试间清理 — 防止跨测试污染。仅清 L1,L2 留在 Redis(下次启动仍可用)。"""
    _EMBED_CACHE_L1.clear()


def close() -> None:
    """进程退出时关闭 httpx 客户端(测试 fixture / atexit 调用)。"""
    global _HTTPX
    if _HTTPX is not None:
        _HTTPX.close()
        _HTTPX = None