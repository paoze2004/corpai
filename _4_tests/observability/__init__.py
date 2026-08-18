"""Phase 4 Observability 测试套件 — 纯 stdlib,真 DB 仅 integration case 需要。

- test_trace.py     — contextvars / Span / start_span / to_thread_propagating
- test_log.py       — JSON formatter + TraceContextFilter
- test_metrics.py   — Counter/Histogram + generate_latest + _get_or_create 兜底
- test_call_record.py — write_call_record INSERT 字段 + DB raise → warning 不 raise
"""