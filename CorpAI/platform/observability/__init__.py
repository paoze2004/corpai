"""
Phase 4 Observability 子包。

公开 API(从此统一 import):
    trace 模块:Span / start_span / new_trace_id / current_trace_id 等
    log 模块:JsonFormatter / TraceContextFilter / setup_json_logger
    metrics 模块:HTTP_REQUESTS / HTTP_REQUEST_DURATION / DB_POOL_ACQUIRE_SECONDS 等
    call_record 模块:write_call_record(span)

双表边界:
    auth_audit_log(Phase 3) = RBAC 安全审计,写失败 fail-closed,raise
    call_records  (Phase 4) = 性能观测,写失败 warning 不阻断业务

write_call_record 用 lazy import 防循环依赖(__init__ → call_record → db)。
"""
from .log import JsonFormatter, TraceContextFilter, setup_json_logger
from .metrics import (
    A2A_CALL_TOTAL,
    APP_INFO,
    DB_POOL_ACQUIRE_SECONDS,
    DB_POOL_EXHAUSTED_TOTAL,
    HTTP_REQUESTS,
    HTTP_REQUEST_DURATION,
    LLM_CALL_DURATION,
    LLM_CALL_TOTAL,
    endpoint_label,
)
from .trace import (
    Span,
    bind_trace_context,
    current_parent_span_id,
    current_span_id,
    current_trace_id,
    new_span_id,
    new_trace_id,
    normalize_incoming_trace_id,
    reset_trace_context,
    start_span,
    to_thread_propagating,
)


def write_call_record(span: Span) -> None:
    """Span 退出时调用 — 局部 import 防循环(包顶 eager import 会触发循环)。"""
    from .call_record import write_call_record as _write
    _write(span)


__all__ = [
    # log
    "JsonFormatter",
    "TraceContextFilter",
    "setup_json_logger",
    # metrics
    "HTTP_REQUESTS",
    "HTTP_REQUEST_DURATION",
    "DB_POOL_ACQUIRE_SECONDS",
    "DB_POOL_EXHAUSTED_TOTAL",
    "LLM_CALL_TOTAL",
    "LLM_CALL_DURATION",
    "A2A_CALL_TOTAL",
    "APP_INFO",
    "endpoint_label",
    # trace
    "Span",
    "bind_trace_context",
    "current_parent_span_id",
    "current_span_id",
    "current_trace_id",
    "new_span_id",
    "new_trace_id",
    "normalize_incoming_trace_id",
    "reset_trace_context",
    "start_span",
    "to_thread_propagating",
    # call_record
    "write_call_record",
]