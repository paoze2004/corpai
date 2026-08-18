"""Feishu approval card — M3.2。

接收 PolicyDecision + alert 上下文,生成飞书卡 payload + 模拟"批准/拒绝"事件。

M3 简化版:不真发飞书 webhook,只生成 card payload 并写到 audit log。
M4+ 接真 Feishu:已存在的 `sre_copilot.feishu.handle_approve_callback` 仍然 work。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any


def build_approval_card(
    alert_id: str,
    alert_summary: str,
    decision: dict,
    run_id: str,
) -> dict:
    """生成飞书卡 payload(M3 简化版:不真发,只构造 payload)。

    实际接入 Feishu webhook 时,把 payload POST 到飞书"消息推送"endpoint。
    用户在卡上点"批准/拒绝",飞书回调到 _0_CorpAI 的 feishu callback handler。
    """
    action = decision.get("action_name", "unknown")
    target = decision.get("target", {})
    risk = decision.get("risk", "medium")
    reason = decision.get("reason", "")

    # 飞书卡 v2 schema(简化)
    card = {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "header": {
                "template": "orange" if risk == "medium" else "red",
                "title": {
                    "tag": "plain_text",
                    "content": f"🤖 AI 建议:{action} {risk} risk",
                },
            },
            "elements": [
                {
                    "tag": "div",
                    "fields": [
                        {
                            "is_short": True,
                            "text": {
                                "tag": "lark_md",
                                "content": f"**Alert:**\n{alert_summary}",
                            },
                        },
                        {
                            "is_short": True,
                            "text": {
                                "tag": "lark_md",
                                "content": f"**Target:**\n{json.dumps(target, ensure_ascii=False)}",
                            },
                        },
                    ],
                },
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**理由:**\n{reason}",
                    },
                },
                {
                    "tag": "hr",
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "✅ 批准"},
                            "type": "primary",
                            "value": {
                                "action": "approve",
                                "alert_id": alert_id,
                                "run_id": run_id,
                                "decision_id": str(uuid.uuid4()),
                            },
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "❌ 拒绝"},
                            "type": "danger",
                            "value": {
                                "action": "reject",
                                "alert_id": alert_id,
                                "run_id": run_id,
                                "decision_id": str(uuid.uuid4()),
                            },
                        },
                    ],
                },
            ],
        },
    }
    return card


def simulate_approval_response(decision_id: str, approved: bool, actor: str = "demo_user") -> dict:
    """模拟飞书回调(M3 简化版,不真发 webhook)。

    生产:实际收到飞书 callback 时,调 `sre_copilot.feishu.handle_approve_callback` 解析。
    """
    return {
        "decision_id": decision_id,
        "approved": approved,
        "actor": actor,
        "ts": time.time(),
        "source": "feishu_simulated",
    }


__all__ = ["build_approval_card", "simulate_approval_response"]