"""Pipeline — 跑 N 个 agent 的通用循环。

把"yield ctx 每步 + log_event + 失败 fail-fast"这套逻辑抽出来,供 IncidentWorkflow 复用。

Opt.7:每个 agent run 包 OTel span(供 Grafana Tempo / Jaeger 可视化 trace)。
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sre_copilot.agents import BaseAgent, IncidentContext

logger = logging.getLogger(__name__)


async def run_pipeline(
    ctx: IncidentContext,
    agents: list[BaseAgent],
) -> AsyncIterator[IncidentContext]:
    """顺序执行 agents,每步 yield 当前 ctx。

    失败 fail-fast:把异常塞 ctx.action_plan 然后 raise,让上层决定怎么重试。
    """
    for agent in agents:
        ctx.log_event("pipeline", f"阶段开始:{agent.name}")
        # Opt.7:每个 agent run 包 OTel span(若 init_otel 启用了 OTLP)
        try:
            from _0_CorpAI._2_platform.observability.otel import get_tracer
            tracer = get_tracer("sre_copilot.workflow")
            with tracer.start_as_current_span(
                f"agent.{agent.name}",
                attributes={
                    "agent.name": agent.name,
                    "run_id": ctx.run_id,
                    "alert": str(ctx.alert.get("alert", "")),
                },
            ) as span:
                await agent.run(ctx)
                # 关键字段记到 span(可视化时能看到)
                if ctx.diagnosis and agent.name == "diagnosis":
                    span.set_attribute("diagnosis.confidence", float(ctx.diagnosis.get("confidence", 0)))
                    span.set_attribute("diagnosis.root_cause", (ctx.diagnosis.get("root_cause") or "")[:200])
                if ctx.action_plan and agent.name == "action":
                    pa = ctx.action_plan.get("primary_action") or {}
                    span.set_attribute("action.primary", pa.get("action", ""))
                    span.set_attribute("action.risk", pa.get("risk", ""))
        except ImportError:
            # OTel 没装或 init 没跑,直接跑
            await agent.run(ctx)
        except Exception as exc:
            ctx.log_event("pipeline", f"阶段失败:{agent.name}", error=str(exc), level="error")
            if ctx.action_plan is None:
                ctx.action_plan = {
                    "plan_id": f"plan-{ctx.run_id}-failed",
                    "primary_action": None,
                    "secondary_action": None,
                    "error": str(exc),
                }
            raise
        ctx.log_event("pipeline", f"阶段完成:{agent.name}")
        yield ctx


__all__ = ["run_pipeline"]