"""
需求：为CorpAI项目创建和配置日志记录器

Phase 4:delegate to platform.observability.log:setup_json_logger。
保持 setup_logger(name, log_file=...) 入口形态不变,17 个业务文件零改。

输出格式从纯文本 (例如 "_0_CorpAI - 2026-... - INFO - message")
升级为每行 JSON ({"ts":..., "level":"INFO", "trace_id":..., "msg":...})。
trace_id/span_id 通过 TraceContextFilter 自动从 contextvars 注入。
"""
import logging

from _0_CorpAI.config import Config
from _0_CorpAI._2_platform.observability.log import setup_json_logger


def setup_logger(name, log_file='logs/app.log'):
    """Phase 4:委托给 setup_json_logger — JSON 输出 + trace_id 自动注入。"""
    return setup_json_logger(name, log_file)


logger = setup_logger('_0_CorpAI', Config().log_file)