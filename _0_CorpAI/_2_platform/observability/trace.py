"""
Phase 4 trace — contextvars + Span + start_span + to_thread_propagating。

公开 API:
    current_trace_id() / current_span_id() / current_parent_span_id()
    new_trace_id() / new_span_id() / normalize_incoming_trace_id()
    Span dataclass
    start_span(name, attributes=None) — contextmanager
    bind_trace_context(trace_id, span_id, parent_span_id) → TraceTokens
    reset_trace_context(tokens) — restore
    to_thread_propagating(func, /, *args, **kwargs) — asyncio helper

设计要点:
- trace_id 用 UUID hex 32 字符(给上游 header 用)
- span_id 用 UUID hex 16 字符(短,够唯一)
- normalize_incoming_trace_id 限制字符集 + 64 长度,防恶意污染
- start_span 自动 end_ok/end_err,except 路径只填 end_ts=None 的;不覆盖显式 end_err
- to_thread_propagating 解决 asyncio.to_thread 不传 ContextVar 的问题:
  copy_context().run() + loop.run_in_executor(None, ctx.run, fn)
"""
from __future__ import annotations

import asyncio
import contextvars
import functools
import re
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator

_trace_id_var: contextvars.ContextVar[str | None] = ContextVar("trace_id", default=None)
_span_id_var: contextvars.ContextVar[str | None] = ContextVar("span_id", default=None)
_parent_span_id_var: contextvars.ContextVar[str | None] = ContextVar(
    "parent_span_id", default=None,
)


def current_trace_id() -> str | None:
    return _trace_id_var.get()


def current_span_id() -> str | None:
    return _span_id_var.get()


def current_parent_span_id() -> str | None:
    return _parent_span_id_var.get()


def new_trace_id() -> str:
    return uuid.uuid4().hex  # 32 hex


def new_span_id() -> str:
    return uuid.uuid4().hex[:16]  # 16 hex


# 只允许 [A-Za-z0-9._-],长度 1-64
_VALID_TRACE_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def normalize_incoming_trace_id(raw: str | None) -> str | None:
    """校验并清洗上游 X-Trace-ID;非法值返 None,调用方决定重新生成。"""
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    if not _VALID_TRACE_RE.match(raw):
        return None
    return raw


@dataclass
class TraceTokens:
    trace: contextvars.Token | None = None
    span: contextvars.Token | None = None
    parent: contextvars.Token | None = None


def bind_trace_context(
    trace_id: str, span_id: str, parent_span_id: str | None,
) -> TraceTokens:
    tokens = TraceTokens()
    tokens.trace = _trace_id_var.set(trace_id)
    tokens.span = _span_id_var.set(span_id)
    if parent_span_id is not None:
        tokens.parent = _parent_span_id_var.set(parent_span_id)
    return tokens


def reset_trace_context(tokens: TraceTokens) -> None:
    if tokens.parent is not None:
        try:
            _parent_span_id_var.reset(tokens.parent)
        except (ValueError, LookupError):
            pass
    try:
        _span_id_var.reset(tokens.span)
    except (ValueError, LookupError):
        pass
    try:
        _trace_id_var.reset(tokens.trace)
    except (ValueError, LookupError):
        pass


@dataclass
class Span:
    """一次调用的 trace 单元。start_span 自动 new + set,异常/退出自动 end_*。"""
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    start_ts: float = field(default_factory=time.time)
    end_ts: float | None = None
    status: str = "ok"  # ok / error / timeout
    attributes: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def set_attr(self, k: str, v: Any) -> None:
        self.attributes[k] = v

    def end_ok(self) -> None:
        if self.end_ts is None:
            self.end_ts = time.time()
        self.status = "ok"

    def end_err(self, msg: str, status: str = "error") -> None:
        if self.end_ts is None:
            self.end_ts = time.time()
        self.status = status
        self.error = msg

    def end_timeout(self, msg: str) -> None:
        self.end_err(msg, status="timeout")

    @property
    def duration_ms(self) -> int:
        end = self.end_ts if self.end_ts is not None else time.time()
        return int((end - self.start_ts) * 1000)


@contextmanager
def start_span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Span]:
    """上下文管理器:
      1. 自动用 current_span_id 作 parent
      2. 无 trace 时自动 new_trace_id
      3. yield span 给业务方用
      4. 正常退出 → end_ok(若未 end_*)
      5. 异常退出 → end_err(若未 end_*),异常继续 raise
      6. finally reset ContextVar + 调 write_call_record
    """
    parent_id = current_span_id()
    trace_id = current_trace_id() or new_trace_id()
    span_id = new_span_id()
    span = Span(
        name=name,
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_id,
        attributes=dict(attributes or {}),
    )
    tokens = bind_trace_context(trace_id, span_id, parent_id)
    try:
        yield span
        if span.end_ts is None:
            span.end_ok()
    except BaseException as exc:
        if span.end_ts is None:
            span.end_err(str(exc))
        raise
    finally:
        reset_trace_context(tokens)
        # 局部 import 防循环依赖(observability.__init__ ← call_record ← db ← metrics)
        from .call_record import write_call_record
        try:
            write_call_record(span)
        except Exception:
            # write_call_record 内部已 warning 不 raise;这里再兜一次保险
            pass


async def to_thread_propagating(func, /, *args, **kwargs):
    """asyncio.to_thread 替代版 — 把当前 ContextVar 复制到 worker thread。

    使用 `copy_context()` + `loop.run_in_executor(None, ctx.run, call)`
    显式传播(普通 asyncio.to_thread 也复制 contextvars,但显式更稳)。
    """
    ctx = contextvars.copy_context()
    call = functools.partial(func, *args, **kwargs)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, ctx.run, call)


__all__ = [
    "current_trace_id",
    "current_span_id",
    "current_parent_span_id",
    "new_trace_id",
    "new_span_id",
    "normalize_incoming_trace_id",
    "TraceTokens",
    "Span",
    "start_span",
    "bind_trace_context",
    "reset_trace_context",
    "to_thread_propagating",
]