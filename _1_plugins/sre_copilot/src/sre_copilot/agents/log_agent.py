"""LogAgent — 查 Loki 日志(找异常堆栈)。

M1 占位:复用 tools.get_pod_logs 的 output 抽 log samples(K8s + Log 信息合并)。
M3+:接真 Loki(独立 endpoint)。
"""
from __future__ import annotations

import logging
import re

from .base import BaseAgent, IncidentContext

logger = logging.getLogger(__name__)

# 常见错误模式 → 高亮提取
_ERROR_PATTERNS = [
    r"OutOfMemoryError",
    r"OOMKilled",
    r"NullPointerException",
    r"ConnectionTimeout",
    r"connection refused",
    r"too many open files",
    r"disk full",
    r"segmentation fault",
    r"panic:",
]


class LogAgent(BaseAgent):
    name = "log"

    async def run(self, ctx: IncidentContext) -> None:
        # 复用 K8s agent 的 pod logs 抽 error patterns
        # 未来 M3+ 接真 Loki 独立 endpoint
        k8s = ctx.k8s_status or {}
        raw_logs = k8s.get("logs", "")

        ctx.log_event(self.name, "查 Loki:OutOfMemoryError,OOMKilled...")

        samples: list[dict] = []
        # 兼容 logs 是 list(str) 或 str
        if isinstance(raw_logs, list):
            lines = raw_logs
        else:
            lines = str(raw_logs).splitlines() if raw_logs else []

        for line in lines:
            matched = [p for p in _ERROR_PATTERNS if re.search(p, line)]
            if matched:
                samples.append({
                    "pattern": matched[0],
                    "line": line.strip()[:300],
                })
                if len(samples) >= 5:
                    break

        ctx.log_samples = samples
        ctx.log_event(self.name, "Log 抽取完成", error_samples=len(samples))


__all__ = ["LogAgent"]