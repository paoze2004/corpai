"""
Phase 4 结构化日志 — JsonFormatter + TraceContextFilter + setup_json_logger。

公开 API:
    TraceContextFilter — 每次 log 自动注入 trace_id / span_id
    JsonFormatter     — 每行一 JSON,UTC RFC3339 + 毫秒
    setup_json_logger(name, log_file) — Phase 4 实现,CorpAI/logging.py:setup_logger 委托给它

设计要点:
- 保留旧 logger 名字 + 参数,17 个业务文件零改
- handler 加 `_corpai_json_handler=True` 标识,setup_json_logger 重复调用幂等
- 仅透传真正的 extra(不是 LogRecord 内部 args/msg/levelno)
- `json.dumps(default=str)` 防止不可序列化对象导致日志本身抛错
- 中文不 escape(ensure_ascii=False)
- exc_info 输出完整 traceback
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from CorpAI.platform.observability.trace import current_span_id, current_trace_id


# LogRecord 内部字段,不应进入 payload
_STD_LOGRECORD_KEYS = frozenset({
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName",
    "taskName",
})


class TraceContextFilter(logging.Filter):
    """每次 log 记录时把 current_trace_id/span_id 注入 record。

    若业务方已经 `extra={"trace_id": "x", "span_id": "y"}` 显式给值,不覆盖。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if "trace_id" not in record.__dict__:
            record.trace_id = current_trace_id()
        if "span_id" not in record.__dict__:
            record.span_id = current_span_id()
        return True


class JsonFormatter(logging.Formatter):
    """每行输出一个 JSON object:固定字段 + 真实 extra + 可选 exc_info。"""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc)
        payload: dict[str, Any] = {
            "ts": ts.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "ts_epoch": record.created,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "trace_id": getattr(record, "trace_id", None),
            "span_id": getattr(record, "span_id", None),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }
        # 透传真实 extra
        for k, v in record.__dict__.items():
            if k in _STD_LOGRECORD_KEYS or k.startswith("_") or k in payload:
                continue
            payload[k] = v
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_json_logger(name: str, log_file: str = "logs/app.log") -> logging.Logger:
    """Phase 4 实现 — 兼容 CorpAI/logging.py:setup_logger 调用形态。

    handler 加 `_corpai_json_handler=True` 标记,本 logger 已配过则 skip(幂等)。
    """
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # 幂等:已配置过本 logger 直接返回
    for h in logger.handlers:
        if getattr(h, "_corpai_json_handler", False):
            return logger

    fmt = JsonFormatter()
    trace_filter = TraceContextFilter()

    file_handler = logging.FileHandler(log_file, encoding="utf-8", mode="a")
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)
    file_handler.addFilter(trace_filter)
    file_handler._corpai_json_handler = True
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    console_handler.setLevel(logging.INFO)
    console_handler.addFilter(trace_filter)
    console_handler._corpai_json_handler = True
    logger.addHandler(console_handler)

    return logger


__all__ = ["TraceContextFilter", "JsonFormatter", "setup_json_logger"]