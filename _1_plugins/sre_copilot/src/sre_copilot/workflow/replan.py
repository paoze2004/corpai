"""Re-plan — verify fail 后只跑 diagnosis + action + verification。

Opt.3:把 verification evidence 喂回 DiagnosisAgent(LLM 看到前一轮结果会改 plan)。
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sre_copilot.agents import BaseAgent, IncidentContext

logger = logging.getLogger(__name__)

# Re-plan 跑哪几个 agent(diagnosis + action + verification 三个)
REPLAN_AGENT_NAMES = ("diagnosis", "action", "verification")


async def run_replan_cycle(
    ctx: IncidentContext,
    agents: list[BaseAgent],
    replan_count: int,
) -> AsyncIterator[IncidentContext]:
    """跑 re-plan 一个周期:把 verification 喂回 diagnosis,只跑 diag+action+verify。

    Args:
        ctx: 当前 ctx(verification 已填,diagnosis 即将被覆盖)
        agents: 全 7 agent(从中选 3 个)
        replan_count: 第几次 re-plan(用于 prompt 上下文)
    """
    ctx.log_event(
        "workflow", f"Re-plan 第 {replan_count} 次",
        last_verified=ctx.verification,
    )
    # 把 verification evidence 喂给 DiagnosisAgent
    if ctx.diagnosis is None:
        ctx.diagnosis = {}
    ctx.diagnosis["replan_evidence"] = ctx.verification
    ctx.diagnosis["replan_count"] = replan_count

    by_name = {a.name: a for a in agents}
    for name in REPLAN_AGENT_NAMES:
        agent = by_name.get(name)
        if not agent:
            continue
        ctx.log_event("workflow", f"Re-plan 阶段:{agent.name}")
        try:
            await agent.run(ctx)
        except Exception as exc:
            ctx.log_event(
                "workflow", f"Re-plan 失败:{agent.name}",
                error=str(exc), level="error",
            )
            raise
        yield ctx


__all__ = ["run_replan_cycle", "REPLAN_AGENT_NAMES"]