"""VerificationAgent — M4。

执行 action 后,重新查 Prometheus/K8s 指标,对比 pre-state 判断恢复情况。
DRY_RUN 模式:80% 概率判定"已恢复",20% 概率"需 re-plan"。
生产:接真 metrics API + K8s API。

输入:ctx(pre-state metrics + k8s 都在 ctx.metrics / ctx.k8s_status)
      + post-state(executor 跑完后会塞 ctx.post_metrics)
输出:ctx.verification = {
    "verified": bool,
    "metrics_back_to_normal": bool,
    "evidence": [...],
    "replan_needed": bool,
    "replan_reason": str,
}
"""
from __future__ import annotations

import logging
import random
from typing import Any

from .base import BaseAgent, IncidentContext

logger = logging.getLogger(__name__)


class VerificationAgent(BaseAgent):
    name = "verification"

    async def run(self, ctx: IncidentContext) -> None:
        # 1. 模拟 post-state metrics(实际:从 Kafka sre.audit 拉 executor 跑完的 result)
        #    M4 简化:直接读 ctx.post_metrics(由 executor/M7 填充)
        pre_metrics = ctx.metrics or []
        post_metrics = getattr(ctx, "post_metrics", None) or pre_metrics  # 没填就当已恢复

        ctx.log_event(self.name, "对比 pre/post metrics")

        # 2. 简单判定:error_rate 从 > 5% 降到 < 5% = 恢复
        #    实际可以用更复杂的对比逻辑
        pre_error_rate = self._extract_error_rate(pre_metrics)
        post_error_rate = self._extract_error_rate(post_metrics)

        recovered = pre_error_rate is not None and post_error_rate is not None and post_error_rate < 5.0
        if pre_error_rate is None:
            # 没 pre 数据,DRY_RUN 用 80% 概率判定
            recovered = random.random() < 0.8

        evidence = [
            f"pre  error_rate: {pre_error_rate}%",
            f"post error_rate: {post_error_rate}%",
        ]
        if not recovered:
            evidence.append("→ 未恢复,需 re-plan")

        ctx.verification = {
            "verified": recovered,
            "metrics_back_to_normal": recovered,
            "evidence": evidence,
            "replan_needed": not recovered,
            "replan_reason": (
                "post-action 验证:metric 仍异常,需调整 plan 重做"
                if not recovered else None
            ),
            "ts": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        }
        ctx.log_event(
            self.name,
            "验证完成" if recovered else "验证未通过",
            verified=recovered,
            pre=pre_error_rate, post=post_error_rate,
        )

    @staticmethod
    def _extract_error_rate(metrics: list[dict]) -> float | None:
        """从 Prometheus-style 事件中抽 error_rate(%),找不到返 None。"""
        if not isinstance(metrics, list):
            return None
        for m in metrics:
            if not isinstance(m, dict):
                continue
            if m.get("metric") == "http_requests_error_rate" and "value" in m:
                try:
                    return float(m["value"])
                except (TypeError, ValueError):
                    continue
        return None


__all__ = ["VerificationAgent"]