"""sre_copilot.policy — Policy Engine + Feishu 审批卡片。

Policy Engine 根据 ActionPlan 中每个 action 的 risk + 类型,判定:
- auto_execute(直接执行,不需要人批)
- requires_approval(需飞书卡批准,等用户点)

规则(简化版):
- low risk → auto
- medium risk → approval
- high risk → approval
- 读类 action(query_*)→ auto
- 写类 action(scale/restart/rollback/delete)→ approval(中等风险)
- 删除/回滚类 → approval + 多人审批(high risk 简化版)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# 不需要审批的"读类"action(M3 简化版:直接判定)
READ_ACTIONS = frozenset({
    "query_metrics", "query_alert", "query_incident", "query_oncall",
    "get_pod_logs", "query_knowledge", "search_knowledge", "verify",
    "wait_and_observe",
})


@dataclass
class PolicyDecision:
    """Policy Engine 对一条 action 的判定结果。"""
    action_name: str
    target: dict
    risk: str
    auto_execute: bool
    requires_approval: bool
    reason: str


@dataclass
class EvaluatedPlan:
    """Policy Engine 对整个 ActionPlan 的判定。"""
    auto_execute: list[PolicyDecision] = field(default_factory=list)
    requires_approval: list[PolicyDecision] = field(default_factory=list)
    skipped: list[PolicyDecision] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.auto_execute) + len(self.requires_approval) + len(self.skipped)


class PolicyEngine:
    """根据 risk + action 类型判定是否需审批。"""

    def evaluate(self, action_plan: dict) -> EvaluatedPlan:
        result = EvaluatedPlan()
        for kind, target_list_key in [
            ("primary", "primary_action"),
            ("secondary", "secondary_action"),
        ]:
            action = action_plan.get(target_list_key)
            if not action:
                continue
            decision = self._decide(action, kind)
            if decision.auto_execute:
                result.auto_execute.append(decision)
            elif decision.requires_approval:
                result.requires_approval.append(decision)
            else:
                result.skipped.append(decision)
        return result

    def _decide(self, action: dict, kind: str) -> PolicyDecision:
        name = action.get("action", "unknown")
        target = action.get("target", {})
        risk = action.get("risk", "medium")
        reason = action.get("reason", "")

        # 规则 1:读类 action → auto
        if name in READ_ACTIONS:
            return PolicyDecision(
                action_name=name, target=target, risk=risk,
                auto_execute=True, requires_approval=False,
                reason=f"读类 action,无需审批;{reason}",
            )

        # 规则 2:风险等级判定
        if risk == "low":
            return PolicyDecision(
                action_name=name, target=target, risk=risk,
                auto_execute=True, requires_approval=False,
                reason=f"low risk,自动执行;{reason}",
            )
        # medium / high → approval
        return PolicyDecision(
            action_name=name, target=target, risk=risk,
            auto_execute=False, requires_approval=True,
            reason=f"{risk} risk,需人批;{reason}",
        )


__all__ = ["PolicyEngine", "PolicyDecision", "EvaluatedPlan", "READ_ACTIONS"]