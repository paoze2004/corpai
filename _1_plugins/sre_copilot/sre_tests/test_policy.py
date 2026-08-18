"""Policy Engine + Feishu 卡 单测(M3)。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestPolicyEngine(unittest.TestCase):
    """PolicyEngine.evaluate() 决策逻辑。"""

    def test_low_risk_action_auto_executes(self):
        from sre_copilot.policy import PolicyEngine
        pe = PolicyEngine()
        plan = {
            "primary_action": {
                "action": "scale_deployment",
                "target": {"deployment": "x"},
                "risk": "low",
                "reason": "OOM 扩容",
            }
        }
        ev = pe.evaluate(plan)
        self.assertEqual(len(ev.auto_execute), 1)
        self.assertEqual(len(ev.requires_approval), 0)
        self.assertEqual(ev.auto_execute[0].action_name, "scale_deployment")

    def test_medium_risk_action_requires_approval(self):
        from sre_copilot.policy import PolicyEngine
        pe = PolicyEngine()
        plan = {
            "primary_action": {
                "action": "restart_pods",
                "target": {"deployment": "x"},
                "risk": "medium",
                "reason": "拉起 pod",
            }
        }
        ev = pe.evaluate(plan)
        self.assertEqual(len(ev.auto_execute), 0)
        self.assertEqual(len(ev.requires_approval), 1)
        self.assertEqual(ev.requires_approval[0].action_name, "restart_pods")

    def test_read_action_always_auto(self):
        """查询类 action 无论 risk 都 auto。"""
        from sre_copilot.policy import PolicyEngine
        pe = PolicyEngine()
        for action in ["query_metrics", "query_alert", "get_pod_logs", "query_knowledge"]:
            plan = {
                "primary_action": {
                    "action": action,
                    "target": {},
                    "risk": "high",  # 故意高
                    "reason": "查询",
                }
            }
            ev = pe.evaluate(plan)
            self.assertEqual(len(ev.auto_execute), 1, f"{action} 应该 auto")
            self.assertEqual(len(ev.requires_approval), 0, f"{action} 不应 approval")

    def test_no_actions_returns_empty(self):
        from sre_copilot.policy import PolicyEngine
        pe = PolicyEngine()
        ev = pe.evaluate({})
        self.assertEqual(ev.total, 0)

    def test_primary_and_secondary_split(self):
        from sre_copilot.policy import PolicyEngine
        pe = PolicyEngine()
        plan = {
            "primary_action": {
                "action": "query_metrics", "target": {}, "risk": "low", "reason": "查"
            },
            "secondary_action": {
                "action": "restart_pods", "target": {"d": "x"}, "risk": "medium", "reason": "拉"
            },
        }
        ev = pe.evaluate(plan)
        self.assertEqual(len(ev.auto_execute), 1)
        self.assertEqual(len(ev.requires_approval), 1)


class TestFeishuCard(unittest.TestCase):
    """build_approval_card 输出格式。"""

    def test_card_contains_required_fields(self):
        from sre_copilot.policy.feishu_card import build_approval_card
        card = build_approval_card(
            alert_id="alt-001",
            alert_summary="OOMKilled order-api (order-api)",
            decision={
                "action_name": "restart_pods",
                "target": {"deployment": "order-api"},
                "risk": "medium",
                "reason": "拉起 OOMKilled pods",
            },
            run_id="run-001",
        )
        self.assertEqual(card["msg_type"], "interactive")
        self.assertEqual(card["card"]["schema"], "2.0")
        # 应该有批准/拒绝 2 个 button
        actions = card["card"]["elements"][-1]["actions"]
        labels = [a["text"]["content"] for a in actions]
        self.assertIn("✅ 批准", labels)
        self.assertIn("❌ 拒绝", labels)
        # button value 应该带 alert_id / run_id(回调时用)
        approve_btn = next(a for a in actions if "批准" in a["text"]["content"])
        self.assertEqual(approve_btn["value"]["action"], "approve")
        self.assertEqual(approve_btn["value"]["alert_id"], "alt-001")
        self.assertEqual(approve_btn["value"]["run_id"], "run-001")


if __name__ == "__main__":
    unittest.main()