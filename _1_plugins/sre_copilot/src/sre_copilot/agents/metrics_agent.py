"""MetricsAgent — 调 Prometheus Alertmanager API 查 alert 详情 + 错误率。

Phase 1:DRY_RUN 模式返 mock 数据;真接时 K8S_DRY_RUN=false。
"""
from __future__ import annotations

import logging
from typing import Any

from .base import BaseAgent, IncidentContext

logger = logging.getLogger(__name__)


class MetricsAgent(BaseAgent):
    name = "metrics"

    async def run(self, ctx: IncidentContext) -> None:
        import sre_copilot.tools as t

        ctx.log_event(self.name, "查 Prometheus:rate(http_requests_total{status=~5..,service=...}[5m])")

        # query_alert() 不接 authorization 参数(它内部用 PROMETHEUS_URL env 调真 API)
        # 在 M5 demo 阶段,没配 PROMETHEUS_URL 会返 not_configured,这里 catch 住
        try:
            import json as _json
            alerts_raw = t.query_alert()
            alerts = _json.loads(alerts_raw) if isinstance(alerts_raw, str) else alerts_raw
            ctx.log_event(self.name, "Prometheus 返结果", alert_count=len(alerts.get("data", [])))
            ctx.metrics = alerts
        except Exception as exc:
            ctx.log_event(self.name, "Prometheus 调用失败", error=str(exc), level="warn")
            ctx.metrics = {"status": "error", "data": [], "message": str(exc)}


__all__ = ["MetricsAgent"]