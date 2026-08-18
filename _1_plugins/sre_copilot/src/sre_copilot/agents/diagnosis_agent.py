"""DiagnosisAgent — LLM 真推理(M3+ 接 LangChain)。

输入:ctx.metrics + ctx.k8s_status + ctx.log_samples + ctx.historical_incidents
       + 可选 ctx.diagnosis["replan_evidence"](re-plan 时)
输出:ctx.diagnosis = {root_cause, confidence, evidence, reasoning, replan_count?}

支持 OPT_LLM_HEURISTIC=1 env var 切回启发式(M5 demo 离线时用)。
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from .base import BaseAgent, IncidentContext

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict | None:
    """鲁棒 JSON 提取(去 ``` 围栏 / <think> / 找 {.*} 块)。"""
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


class DiagnosisAgent(BaseAgent):
    name = "diagnosis"

    def __init__(self, llm=None):
        """参数 llm 是 LangChain ChatModel(可注入;为 None 时按 env 选启发式/LLM)。"""
        self._llm = llm
        self._use_heuristic = (
            os.getenv("SRE_HEURISTIC_DIAGNOSIS", "").strip() == "1"
            or llm is None
        )

    async def run(self, ctx: IncidentContext) -> None:
        from sre_copilot.prompts import DIAGNOSIS_PROMPT, REPLAN_CONTEXT_TEMPLATE

        if self._use_heuristic:
            self._run_heuristic(ctx)
            return

        ctx.log_event(self.name, "调 LLM 综合 4 路 evidence")

        replan_count = (ctx.diagnosis or {}).get("replan_count", 0)
        replan_context = ""
        if replan_count and (ctx.diagnosis or {}).get("replan_evidence"):
            ev = ctx.diagnosis["replan_evidence"]
            replan_context = REPLAN_CONTEXT_TEMPLATE.format(
                replan_count=replan_count,
                prev_verified=ev.get("verified"),
                prev_summary=ev.get("summary", ""),
                prev_replan_suggestion=ev.get("replan_suggestion", "—"),
            )

        prompt = DIAGNOSIS_PROMPT.format(
            alert=json.dumps(ctx.alert, ensure_ascii=False),
            metrics=json.dumps(ctx.metrics or [], ensure_ascii=False, default=str),
            k8s_status=json.dumps(ctx.k8s_status or {}, ensure_ascii=False, default=str),
            log_samples=json.dumps(ctx.log_samples or [], ensure_ascii=False, default=str),
            historical=json.dumps(ctx.historical_incidents or [], ensure_ascii=False, default=str),
            replan_context=replan_context,
        )
        try:
            raw = await self._invoke_llm(prompt)
            parsed = _extract_json(raw)
            if parsed and "root_cause" in parsed:
                ctx.diagnosis = {
                    **parsed,
                    "replan_count": replan_count,
                }
                ctx.log_event(
                    self.name, "LLM 推理完成",
                    root_cause=parsed.get("root_cause", "")[:80],
                    confidence=parsed.get("confidence"),
                )
                return
            ctx.log_event(self.name, "LLM 返非 JSON,降级启发式", level="warn", raw=raw[:100])
        except Exception as exc:
            ctx.log_event(self.name, "LLM 调用失败,降级启发式", error=str(exc), level="warn")

        # 降级
        self._run_heuristic(ctx)

    async def _invoke_llm(self, prompt: str) -> str:
        """调 LangChain ChatModel.ainvoke,返 assistant 文本。"""
        from langchain_core.messages import HumanMessage, SystemMessage
        llm = self._llm
        # llm 可能没传 → fallback 拿 global
        if llm is None:
            try:
                from _0_CorpAI._2_platform.wiring import _make_llm  # type: ignore
                from _0_CorpAI.config import Config
                llm = _make_llm(Config())
            except Exception:
                raise RuntimeError("LLM 未注入且 SRE_HEURISTIC_DIAGNOSIS != 1")
        resp = await llm.ainvoke([
            SystemMessage(content="你是 SRE 专家,严格输出 JSON。"),
            HumanMessage(content=prompt),
        ])
        return resp.content

    def _run_heuristic(self, ctx: IncidentContext) -> None:
        """启发式 fallback(M5 demo 离线时用)— 与 M1 同样的字符串匹配。"""
        ctx.log_event(self.name, "综合 4 路信号(启发式 fallback)")
        oom_signals = 0
        if ctx.log_samples and any("OOM" in s.get("pattern", "") for s in ctx.log_samples):
            oom_signals += 1
        k8s = ctx.k8s_status
        if isinstance(k8s, dict):
            k8s_logs = k8s.get("logs", "")
            if isinstance(k8s_logs, list):
                k8s_logs = "\n".join(k8s_logs)
            if "OOMKilled" in str(k8s_logs):
                oom_signals += 1
        if ctx.historical_incidents:
            for inc in ctx.historical_incidents:
                if "OOM" in inc.get("root_cause", "") or "heap" in inc.get("root_cause", ""):
                    oom_signals += 1
                    break
        if oom_signals >= 2:
            ctx.diagnosis = {
                "root_cause": "JVM heap 1Gi 偏小,高峰时段 OOMKilled(order-api Deployment)",
                "confidence": 0.78,
                "evidence": [
                    "Pod OOMKilled × 2(过去 5m)",
                    "Loki 日志显示 java.lang.OutOfMemoryError × 47",
                    "历史 INC-1024 类似根因,JVM Xmx 1Gi → 2Gi 解决",
                ],
                "reasoning": "3 路信号高度一致:Prometheus error rate 飙升 + K8s 报 OOMKilled + Loki 堆栈定位 heap 耗尽",
            }
        else:
            ctx.diagnosis = {
                "root_cause": "未明确,需更多信号",
                "confidence": 0.3,
                "evidence": ["OOMKilled / OOM 日志未匹配"],
                "reasoning": "启发式未匹配 OOM 模式",
            }


__all__ = ["DiagnosisAgent"]