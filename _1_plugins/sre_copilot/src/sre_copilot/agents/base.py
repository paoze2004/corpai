"""Agent base + IncidentContext 共享状态。

IncidentContext 是流水线的唯一状态容器,每个 agent 跑完往里塞自己的 result,
下一个 agent 读。便于 SSE 推送中间状态(每步 yield 当前 ctx)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class IncidentContext:
    """Incident 流水线的共享状态。

    字段累积顺序:
      alert (input)
        → metrics (MetricsAgent)
        → k8s_status (K8sAgent)
        → log_samples (LogAgent)
        → historical_incidents (KnowledgeAgent)
        → diagnosis (DiagnosisAgent)
        → action_plan (ActionAgent)
    """
    run_id: str
    alert: dict[str, Any]  # {alert, service, severity, started_at}
    user_token: str | None = None  # A2A 透传给下游 tool
    events: list[dict] = field(default_factory=list)  # 时间线(给 SSE / log)

    # 阶段结果(每个 agent 跑完填充)
    metrics: dict | None = None
    k8s_status: dict | None = None
    log_samples: list | None = None
    historical_incidents: list | None = None
    diagnosis: dict | None = None
    action_plan: dict | None = None

    def log_event(self, agent: str, msg: str, **extra: Any) -> None:
        """记录事件(给 SSE 推送 / audit log 用)。"""
        import datetime as _dt
        self.events.append({
            "ts": _dt.datetime.utcnow().isoformat() + "Z",
            "agent": agent,
            "msg": msg,
            **extra,
        })


class BaseAgent:
    """Agent 抽象基类。每个 agent 实现 run(ctx) — 就地修改 ctx。

    设计原则:
    - run() 不返值,只改 ctx(简单、明确)
    - run() 失败 raise,workflow 决定是否容错(默认 fail-fast)
    - 同步/异步混合:tool 调用是 sync (requests);LLM 调用是 async (ChatOpenAI.ainvoke)
    """
    name: str = "base"

    async def run(self, ctx: IncidentContext) -> None:
        raise NotImplementedError


__all__ = ["IncidentContext", "BaseAgent"]