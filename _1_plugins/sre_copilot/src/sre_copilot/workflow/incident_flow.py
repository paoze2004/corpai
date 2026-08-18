"""IncidentWorkflow — 编排 Pipeline + Policy + Re-plan(M1+M3+M4 + Opt.1-3)。

Opt.4 拆分后,本文件只剩"编排"逻辑 — pipeline / policy / replan 都是组装块。
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from sre_copilot.agents import (
    ActionAgent,
    BaseAgent,
    DiagnosisAgent,
    IncidentContext,
    K8sAgent,
    KnowledgeAgent,
    LogAgent,
    MetricsAgent,
    VerificationAgent,
)
from sre_copilot.constants import MAX_REPLANS
from sre_copilot.policy import PolicyEngine
from sre_copilot.policy.feishu_card import build_approval_card

from .pipeline import run_pipeline
from .policy_step import apply_policy
from .replan import run_replan_cycle

logger = logging.getLogger(__name__)

# MAX_REPLANS 移到了 sre_copilot.constants(Opt.5)— 保持向后兼容再 export 一次
__all__ = ["IncidentWorkflow", "MAX_REPLANS"]


# 流水线顺序 — 改这里就改流程
_DEFAULT_PIPELINE: list[type[BaseAgent]] = [
    MetricsAgent,
    K8sAgent,
    LogAgent,
    KnowledgeAgent,
    DiagnosisAgent,
    ActionAgent,
    VerificationAgent,  # M4
]


class IncidentWorkflow:
    """SRE Incident 7 步流水线 + Policy + Re-plan(M1+M3+M4 + Opt.1-3)。

    用法:
        workflow = IncidentWorkflow()
        async for ctx in workflow.run(alert={"alert": "OOMKilled", ...}, run_id="run-001"):
            print(f"step done: events={len(ctx.events)}")
        # ctx.action_plan 有完整 plan + policy_decision + approval_cards + verification
    """

    def __init__(self, pipeline: list[type[BaseAgent]] | None = None):
        self.pipeline_classes = pipeline or _DEFAULT_PIPELINE
        self.agents: list[BaseAgent] = [cls() for cls in self.pipeline_classes]
        self.policy_engine = PolicyEngine()
        self.feishu_card_builder = build_approval_card

    async def run(
        self,
        alert: dict[str, Any],
        run_id: str,
        user_token: str | None = None,
    ) -> AsyncIterator[IncidentContext]:
        """跑 7 步流水线 + Policy 评估 + Re-plan 闭环。"""
        ctx = IncidentContext(
            run_id=run_id,
            alert=alert,
            user_token=user_token,
        )
        ctx.log_event("workflow", f"开始 {len(self.agents)} 步 pipeline", run_id=run_id)

        replan_count = 0
        for round_idx in range(MAX_REPLANS + 1):
            if round_idx > 0:
                async for c in run_replan_cycle(ctx, self.agents, replan_count):
                    yield c
            else:
                async for c in run_pipeline(ctx, self.agents):
                    yield c

            # M3:Policy 评估 + 飞书卡
            apply_policy(ctx, self.policy_engine, self.feishu_card_builder)

            # M4:Verification 判 re-plan
            if (ctx.verification or {}).get("verified"):
                ctx.log_event("workflow", f"Verification 通过(第 {round_idx+1} 轮)")
                break
            replan_count += 1
            if replan_count > MAX_REPLANS:
                ctx.log_event("workflow", f"已达 re-plan 上限 {MAX_REPLANS},停止")
                break
            ctx.log_event(
                "workflow", f"Verification 未通过,准备 re-plan ({replan_count}/{MAX_REPLANS})",
            )

        ctx.log_event(
            "workflow",
            f"流水线完成:{len(self.agents)} 步 + re-plan x {replan_count}",
            run_id=run_id,
        )
        yield ctx


__all__ = ["IncidentWorkflow", "MAX_REPLANS"]