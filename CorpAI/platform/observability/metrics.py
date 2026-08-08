"""
Phase 4 prometheus_client Counter/Histogram + Info + _get_or_create 兜底。

设计:
- 7 个 metric:HTTP_REQUESTS / HTTP_REQUEST_DURATION / DB_POOL_ACQUIRE_SECONDS /
  DB_POOL_EXHAUSTED_TOTAL / LLM_CALL_TOTAL / LLM_CALL_DURATION / A2A_CALL_TOTAL
- APP_INFO 元数据
- endpoint_label(scope):从 scope['route'].path 取 route template;未匹配 → __unmatched__
- _get_or_create:prometheus_client duplicate 注册(ValueError)时从 REGISTRY 找回,
  防止 reload / 测试 reload 重复 import 时崩溃
"""
from __future__ import annotations

from typing import Any

from prometheus_client import (
    REGISTRY,
    Counter,
    Histogram,
    Info,
    CollectorRegistry,
)


def _get_or_create(metric_type: Any, name: str, doc: str, labels: list[str]) -> Any:
    """正常创建 collector;duplicate(ValueError)时从 registry 找回已注册实例。

    不使用 get_sample_value()(那是数值,不是 collector)。
    """
    try:
        return metric_type(name, doc, labels)
    except ValueError:
        collectors = getattr(REGISTRY, "_names_to_collectors", {})
        c = collectors.get(name)
        # Counter 自动 _total 后缀;Histogram/Info 不加
        if c is None and metric_type is Counter and name.endswith("_total"):
            c = collectors.get(name[:-6])
        if not isinstance(c, metric_type):
            raise
        return c


# ─── HTTP metrics ───
HTTP_REQUESTS = _get_or_create(
    Counter, "http_requests_total",
    "Total HTTP requests", ["method", "endpoint", "status"],
)
HTTP_REQUEST_DURATION = _get_or_create(
    Histogram, "http_request_duration_seconds",
    "HTTP request latency", ["method", "endpoint"],
)

# ─── DB pool metrics ───
DB_POOL_ACQUIRE_SECONDS = _get_or_create(
    Histogram, "db_pool_acquire_seconds",
    "DB pool conn acquire latency", [],
)
DB_POOL_EXHAUSTED_TOTAL = _get_or_create(
    Counter, "db_pool_exhausted_total",
    "DB pool exhausted count", [],
)

# ─── LLM metrics ───
LLM_CALL_TOTAL = _get_or_create(
    Counter, "llm_call_total",
    "LLM calls", ["model", "intent"],
)
LLM_CALL_DURATION = _get_or_create(
    Histogram, "llm_call_duration_seconds",
    "LLM call latency", ["model"],
)

# ─── A2A metrics ───
A2A_CALL_TOTAL = _get_or_create(
    Counter, "a2a_call_total",
    "A2A calls", ["agent", "status"],
)

# ─── App metadata ───
APP_INFO = _get_or_create(Info, "corpai_app", "CorpAI app metadata", [])
APP_INFO.info({"version": "phase4", "component": "observability"})


def endpoint_label(scope: dict) -> str:
    """从 ASGI scope['route'].path 取 route template;未匹配路由标 __unmatched__。

    防止 /users/a, /users/b 产生高基数(必须用 route.path,而非 request.url.path)。
    """
    route = scope.get("route")
    return getattr(route, "path", "__unmatched__") if route is not None else "__unmatched__"


__all__ = [
    "HTTP_REQUESTS",
    "HTTP_REQUEST_DURATION",
    "DB_POOL_ACQUIRE_SECONDS",
    "DB_POOL_EXHAUSTED_TOTAL",
    "LLM_CALL_TOTAL",
    "LLM_CALL_DURATION",
    "A2A_CALL_TOTAL",
    "APP_INFO",
    "endpoint_label",
    "_get_or_create",
]