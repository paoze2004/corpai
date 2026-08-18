"""KnowledgeAgent — 调 Knowledge Plugin (A2A) 查历史 Incident / SOP。

M1 stub:K-A Plugin 还在 M2 重命名,这里先 mock 返回一条典型历史 incident;
M2 完成后切到真 A2A 调用。
"""
from __future__ import annotations

import json
import logging
import os
import uuid

from .base import BaseAgent, IncidentContext

logger = logging.getLogger(__name__)


class KnowledgeAgent(BaseAgent):
    name = "knowledge"

    async def run(self, ctx: IncidentContext) -> None:
        # M1:stub。返回 1 条 mock 历史 incident 演示知识检索能力
        # M2:换成真 A2A 调 knowledge plugin 的 search_incident()
        ctx.log_event(self.name, "A2A → Knowledge Plugin:search_incident(alert.reason)")

        # Mock:根据 alert 类型返回"匹配的历史案例"
        alert_type = ctx.alert.get("alert", "")
        if "OOM" in alert_type or "Memory" in alert_type:
            ctx.historical_incidents = [
                {
                    "id": "INC-1024",
                    "service": "payment-service",
                    "occurred_at": "2025-08-01T10:23:00+08:00",
                    "root_cause": "JVM heap 配 1Gi 偏小,高峰时段 OOMKilled",
                    "solution": [
                        "JVM Xmx 调到 2Gi",
                        "deployment 重启(滚动)",
                        "后续加 Prometheus heap_usage > 80% 告警",
                    ],
                    "similarity": 0.87,
                },
                {
                    "id": "INC-1156",
                    "service": "order-service",
                    "occurred_at": "2026-06-15T14:08:00+08:00",
                    "root_cause": "OrderCache 内存泄漏(连接未关)",
                    "solution": [
                        "fix ConnectionPool.close() 调用",
                        "重启 deployment",
                    ],
                    "similarity": 0.62,
                },
            ]
        else:
            ctx.historical_incidents = []

        ctx.log_event(
            self.name,
            "知识检索完成",
            hits=len(ctx.historical_incidents),
        )


__all__ = ["KnowledgeAgent"]