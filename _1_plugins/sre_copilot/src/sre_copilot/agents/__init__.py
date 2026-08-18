"""sre_copilot.agents — Incident 流水线的 6 个 Agent。

设计:
- 每个 agent 接收 IncidentContext(共享 dataclass),就地修改
- agent 之间不直接传值,只通过 ctx — 易测试 + 可视化
- agent 是"思考"层:Metrics/K8s/Log 调 tool 收集证据;Knowledge 调 knowledge plugin;
  Diagnosis 用 LLM 综合;Action 用 LLM 生成 plan
- 真正的执行在 action_executor / MCP layer(不是 agent)
"""
from .base import BaseAgent, IncidentContext
from .metrics_agent import MetricsAgent
from .k8s_agent import K8sAgent
from .log_agent import LogAgent
from .knowledge_agent import KnowledgeAgent
from .diagnosis_agent import DiagnosisAgent
from .action_agent import ActionAgent
from .verification_agent import VerificationAgent

__all__ = [
    "BaseAgent",
    "IncidentContext",
    "MetricsAgent",
    "K8sAgent",
    "LogAgent",
    "KnowledgeAgent",
    "DiagnosisAgent",
    "ActionAgent",
    "VerificationAgent",
]