"""ActionAgent — LLM 真推理 + re-plan aware(M3+ Opt.2)。

输入:ctx.diagnosis(LLM 推的 root_cause)
输出:ctx.action_plan = {primary_action, secondary_action, based_on_diagnosis}

OPT:接 LLM 真推理 action;re-plan 时把 verification 证据塞 prompt 提示调整。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from .base import BaseAgent, IncidentContext

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict | None:
    text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    if not text.startswith("{"):
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            text = m.group(0)
    try:
        return json.loads(text)
    except Exception:
        return None


class ActionAgent(BaseAgent):
    name = "action"

    def __init__(self, llm=None):
        self._llm = llm
        self._use_heuristic = (
            os.getenv("SRE_HEURISTIC_ACTION", "").strip() == "1"
            or llm is None
        )

    async def run(self, ctx: IncidentContext) -> None:
        from sre_copilot.prompts import ACTION_PROMPT, REPLAN_CONTEXT_TEMPLATE

        diagnosis = ctx.diagnosis or {}
        if not diagnosis.get("root_cause"):
            ctx.log_event(self.name, "无 diagnosis 上下文,降级 wait_and_observe", level="warn")
            self._fallback_wait(ctx, "无 diagnosis")
            return

        if self._use_heuristic:
            self._run_heuristic(ctx, diagnosis)
            return

        # LLM 真推理
        replan_count = diagnosis.get("replan_count", 0)
        replan_context = ""
        if replan_count and diagnosis.get("replan_evidence"):
            ev = diagnosis["replan_evidence"]
            replan_context = REPLAN_CONTEXT_TEMPLATE.format(
                replan_count=replan_count,
                prev_verified=ev.get("verified"),
                prev_summary=ev.get("summary", ""),
                prev_replan_suggestion=ev.get("replan_suggestion", "—"),
            )

        prompt = ACTION_PROMPT.format(
            diagnosis=json.dumps(diagnosis, ensure_ascii=False),
            alert=json.dumps(ctx.alert, ensure_ascii=False),
            replan_context=replan_context,
        )
        try:
            raw = await self._invoke_llm(prompt)
            parsed = _extract_json(raw)
            if parsed and parsed.get("primary_action"):
                parsed["plan_id"] = f"plan-{ctx.run_id}-{int(time.time())}"
                if "based_on_diagnosis" not in parsed:
                    parsed["based_on_diagnosis"] = diagnosis.get("root_cause", "")[:120]
                ctx.action_plan = parsed
                ctx.log_event(
                    self.name, "LLM 推 ActionPlan 完成",
                    primary=parsed["primary_action"].get("action"),
                    risk=parsed["primary_action"].get("risk"),
                    replan=replan_count,
                )
                return
            ctx.log_event(self.name, "LLM 返非 JSON,降级启发式", level="warn")
        except Exception as exc:
            ctx.log_event(self.name, "LLM 失败降级启发式", error=str(exc), level="warn")

        # 降级
        self._run_heuristic(ctx, diagnosis)

    async def _invoke_llm(self, prompt: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage
        llm = self._llm
        if llm is None:
            try:
                from _0_CorpAI._2_platform.wiring import _make_llm  # type: ignore
                from _0_CorpAI.config import Config
                llm = _make_llm(Config())
            except Exception:
                raise RuntimeError("LLM 未注入且 SRE_HEURISTIC_ACTION != 1")
        resp = await llm.ainvoke([
            SystemMessage(content="你是 SRE 专家,严格输出 JSON。"),
            HumanMessage(content=prompt),
        ])
        return resp.content

    def _run_heuristic(self, ctx: IncidentContext, diagnosis: dict) -> None:
        """M1 启发式 fallback(LLM 不可用时)。"""
        ctx.log_event(self.name, "生成 ActionPlan(启发式)")
        root_cause = diagnosis.get("root_cause", "")
        confidence = diagnosis.get("confidence", 0.0)
        service = ctx.alert.get("service", "unknown")
        if confidence < 0.5:
            self._fallback_wait(ctx, f"Diagnosis 置信度 {confidence:.0%} 不足")
            return
        ctx.action_plan = {
            "plan_id": f"plan-{ctx.run_id}-{int(time.time())}",
            "primary_action": {
                "action": "scale_deployment",
                "target": {"deployment": service, "namespace": "production"},
                "args": {"replicas": 5, "memory_limit": "2Gi"},
                "reason": f"OOMKilled × 2,{root_cause[:60]}",
                "risk": "low",
                "approval_required": False,
            },
            "secondary_action": {
                "action": "restart_pods",
                "target": {"deployment": service, "namespace": "production"},
                "reason": "拉起被 OOMKilled 的 pod",
                "risk": "medium",
                "approval_required": True,
            },
            "based_on_diagnosis": root_cause,
        }
        ctx.log_event(
            self.name, "ActionPlan 完成(启发式)",
            primary=ctx.action_plan["primary_action"]["action"],
        )

    def _fallback_wait(self, ctx: IncidentContext, reason: str) -> None:
        ctx.action_plan = {
            "plan_id": f"plan-{ctx.run_id}-{int(time.time())}",
            "primary_action": {
                "action": "wait_and_observe",
                "target": {"service": ctx.alert.get("service", "unknown")},
                "args": {"duration": "5m"},
                "reason": reason,
                "risk": "low",
                "approval_required": False,
            },
            "secondary_action": None,
            "based_on_diagnosis": "",
        }
        ctx.log_event(self.name, "降级 wait_and_observe", reason=reason)


__all__ = ["ActionAgent"]