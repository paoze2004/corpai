"""
Phase 4 call_records — Span 落库辅助函数。

设计:
- 每次 start_span() 退出时自动调 write_call_record(span) (见 trace.py:start_span finally)
- DB 不可用/失败 → logger.warning + 不 raise(辅助观测,不阻断业务;与 auth_audit_log 不同策略)
- 失败时尝试 rollback + 关闭 conn,避免泄漏
- user_id / tenant_id 从 span.attributes 读取(Phase 4 不强求注入;Phase 5 再接 JWT)
- attributes 用 json.dumps(default=str) 兜底任何不可序列化对象

为何 TYPE_CHECKING:
- trace.py -> call_record -> db.py -> metrics.py 可能循环
- 但 call_record 仅在 start_span 的 finally 中按名调用,不需要静态类型
- TYPE_CHECKING 让 ruff/mypy 不报,运行时也不真导入 trace
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING

from _0_CorpAI._2_platform.db import DatabasePool

if TYPE_CHECKING:
    from _0_CorpAI._2_platform.observability.trace import Span

logger = logging.getLogger("_0_CorpAI.observability")


def write_call_record(span: "Span") -> None:
    """Span.end_*() 后自动调;DB 不可用 warning 不 raise。"""
    if span.end_ts is None:
        span.end_ts = time.time()

    conn = None
    try:
        conn = DatabasePool.get().get_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO call_records
               (trace_id, span_id, parent_span_id, name, ts_start, ts_end,
                duration_ms, status, attributes_json, error_message,
                user_id, tenant_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                span.trace_id,
                span.span_id,
                span.parent_span_id,
                span.name,
                datetime.utcfromtimestamp(span.start_ts),
                datetime.utcfromtimestamp(span.end_ts),
                span.duration_ms,
                span.status,
                json.dumps(span.attributes, ensure_ascii=False, default=str),
                span.error,
                span.attributes.get("user_id"),
                span.attributes.get("tenant_id"),
            ),
        )
        conn.commit()
        cur.close()
    except Exception as exc:
        # loud-but-non-blocking:观测失败不阻断业务
        logger.warning(
            "call_records 写入失败: %s", exc,
            extra={"trace_id": span.trace_id, "span_id": span.span_id},
        )
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


__all__ = ["write_call_record"]