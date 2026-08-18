"""Policy Step — 评估 ActionPlan + 构造飞书卡。

从 IncidentWorkflow 抽出来,policy 决策可以独立测。
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from sre_copilot.agents import IncidentContext
from sre_copilot.policy import PolicyEngine

logger = logging.getLogger(__name__)


def apply_policy(
    ctx: IncidentContext,
    policy_engine: PolicyEngine,
    feishu_card_builder: Callable[..., dict] | None = None,
) -> None:
    """评估 ctx.action_plan → 填 policy_decision + approval_cards(in-place)。

    Args:
        ctx: 当前 incident 上下文(必须有 action_plan)
        policy_engine: PolicyEngine 实例
        feishu_card_builder: 可选,飞书卡构造器(M3 简化:只 build 不真发)
    """
    if not (ctx.action_plan and ctx.action_plan.get("primary_action")):
        return

    evaluated = policy_engine.evaluate(ctx.action_plan)
    ctx.action_plan["policy_decision"] = {
        "auto_execute": [
            {"action": d.action_name, "target": d.target, "reason": d.reason}
            for d in evaluated.auto_execute
        ],
        "requires_approval": [
            {"action": d.action_name, "target": d.target, "risk": d.risk, "reason": d.reason}
            for d in evaluated.requires_approval
        ],
        "skipped": [
            {"action": d.action_name, "reason": d.reason}
            for d in evaluated.skipped
        ],
    }
    ctx.log_event(
        "policy", "Policy 评估",
        auto=len(evaluated.auto_execute),
        approval=len(evaluated.requires_approval),
        skipped=len(evaluated.skipped),
    )

    if feishu_card_builder is None:
        return
    for d in evaluated.requires_approval:
        card = feishu_card_builder(
            alert_id=ctx.run_id,
            alert_summary=(
                f"{ctx.alert.get('alert', '')} "
                f"({ctx.alert.get('service', '')})"
            ),
            decision={
                "action_name": d.action_name,
                "target": d.target,
                "risk": d.risk,
                "reason": d.reason,
            },
            run_id=ctx.run_id,
        )
        ctx.action_plan.setdefault("approval_cards", []).append(card)
        ctx.log_event("policy", f"飞书卡构造:{d.action_name}", level="info")


__all__ = ["apply_policy"]