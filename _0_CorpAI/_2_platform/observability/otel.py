"""
OpenTelemetry 接入层 —— 跟现有 trace.py 并行,加法不替代。

设计要点:
- 现有 trace.py 走自家 Span dataclass + call_records DB 落库(平台核心),不动
- OTel 在此层独立初始化 + 导出,默认**关闭**(没装 collector 不影响运行)
- 通过环境变量启用:OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4317
- 自动 instrument FastAPI(每个 HTTP 请求一个 span,无需手动埋点)
- service.name=corpai,版本号从 __version__ 读

OTel SpanContext 跟现有 contextvars 是两套,但 FastAPIInstrumentor 只在请求生命周期内创建子 OTel Span,
跟 trace.py 的 start_span 互不干扰。call_records 该怎么写还怎么写。
"""
from __future__ import annotations

import logging
import os
from typing import Any

from _0_CorpAI import __version__

logger = logging.getLogger(__name__)

_initialized = False


def init_otel(app: Any | None = None) -> bool:
    """初始化 OTel TracerProvider + (可选)FastAPI 自动 instrument。

    调用时机:app.py 启动早期(在 FastAPI app 创建后、middleware 注册前/后都行)。
    幂等:多次调用只初始化一次。

    Args:
        app: FastAPI app 实例。传 None 时只初始化 TracerProvider,不 auto-instrument。

    Returns:
        True = OTel 启用(有 OTLP endpoint);False = 仅初始化 provider,无导出。
    """
    global _initialized
    if _initialized:
        return _is_exporter_enabled()
    _initialized = True

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
    except ImportError as exc:
        logger.warning(f"opentelemetry 未安装,跳过 OTel 初始化: {exc}")
        return False

    # Resource —— OTel 标准属性,Jaeger/Grafana/Tempo 都认
    resource = Resource.create({
        "service.name": "corpai",
        "service.version": __version__,
    })
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)

    # Span exporter:OTLP endpoint 设了才开,否则只挂 console(开发可见)
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
            )
            logger.info(f"OTel OTLP exporter 已启用 → {otlp_endpoint}")
        except Exception as exc:
            logger.warning(f"OTLP exporter 启动失败,降级为 console: {exc}")
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    elif os.getenv("OTEL_CONSOLE_EXPORTER", "").strip() == "1":
        # 调试用:OTEL_CONSOLE_EXPORTER=1 启用 console exporter(每个 span 打 stdout)
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        logger.info("OTel console exporter 已启用(调试模式)")
    else:
        logger.debug("OTel TracerProvider 已初始化,无 exporter(设 OTEL_EXPORTER_OTLP_ENDPOINT 启用)")

    # FastAPI 自动 instrument
    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app)
            logger.info("FastAPI OTel instrument 已启用")
        except Exception as exc:
            logger.warning(f"FastAPI instrument 失败: {exc}")

    return bool(otlp_endpoint)


def _is_exporter_enabled() -> bool:
    return bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip())


def get_tracer(name: str = "corpai"):
    """拿 OTel tracer(供业务代码手动埋点用)。

    即使 init_otel 没被调用,这个函数也安全(返回 no-op tracer)。
    """
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except ImportError:
        # 返回一个 no-op 类,避免 import 时挂
        class _NoopTracer:
            def start_as_current_span(self, name, **kw):
                from contextlib import nullcontext
                return nullcontext(None)
        return _NoopTracer()


__all__ = ["init_otel", "get_tracer"]