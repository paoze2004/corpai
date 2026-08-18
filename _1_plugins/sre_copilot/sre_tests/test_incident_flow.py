"""SRE Incident workflow 单元测试 — M1。

验证 6 agent 串行编排 + IncidentContext 累积状态。
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import patch

# 把 plugin 加进 path(editable install 应已加,保险起见)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestIncidentContext(unittest.TestCase):
    """IncidentContext 共享状态 dataclass。"""

    def test_log_event_appends(self):
        from sre_copilot.agents.base import IncidentContext
        ctx = IncidentContext(run_id="t1", alert={"alert": "OOM"})
        ctx.log_event("metrics", "test")
        self.assertEqual(len(ctx.events), 1)
        self.assertEqual(ctx.events[0]["agent"], "metrics")


class TestAgentsRun(unittest.TestCase):
    """每个 agent 独立跑,验证往 ctx 写入了对应字段。"""

    def setUp(self):
        from sre_copilot.agents.base import IncidentContext
        self.ctx = IncidentContext(
            run_id="t1",
            alert={"alert": "OOMKilled order-api", "service": "order-api", "severity": "P2"},
            user_token=None,
        )

    def test_metrics_agent_runs(self):
        """metrics_agent 跑后一定往 ctx.metrics 写结构(dict),不管 PROMETHEUS_URL 配没配。

        配了:status="success"(或 "no_data"),有 "data" 键
        没配:status="not_configured",有 "message" 和 "required_env"

        之前测试硬编码 "data" 键,导致没配 PROMETHEUS_URL 时直接 AssertionError —— 不可靠。
        """
        from sre_copilot.agents.metrics_agent import MetricsAgent
        asyncio.run(MetricsAgent().run(self.ctx))
        self.assertIsInstance(self.ctx.metrics, dict, "metrics 必须写 dict")
        self.assertIn("status", self.ctx.metrics, "metrics 必须含 status 键")
        if self.ctx.metrics["status"] == "not_configured":
            self.assertIn("required_env", self.ctx.metrics)
        else:
            self.assertIn("data", self.ctx.metrics)

    def test_k8s_agent_augments_oom_in_dry_run(self):
        from sre_copilot.agents.k8s_agent import K8sAgent
        asyncio.run(K8sAgent().run(self.ctx))
        # alert 含 OOM,DRY_RUN 增强必须生效
        self.assertEqual(self.ctx.k8s_status.get("oomkilled_pods"),
                         ["order-api-abc-123", "order-api-abc-124"])
        self.assertEqual(self.ctx.k8s_status.get("pod_count"), 5)
        # logs 必须有 OOMKilled 字符串
        self.assertTrue(
            any("OOM" in l for l in self.ctx.k8s_status.get("logs", [])),
            "logs 必须含 OOM 信号",
        )

    def test_log_agent_extracts_error_patterns(self):
        from sre_copilot.agents.k8s_agent import K8sAgent
        from sre_copilot.agents.log_agent import LogAgent
        asyncio.run(K8sAgent().run(self.ctx))
        asyncio.run(LogAgent().run(self.ctx))
        # 至少应有 1 条 sample
        self.assertGreater(len(self.ctx.log_samples), 0)
        for s in self.ctx.log_samples:
            self.assertIn("pattern", s)
            self.assertIn("line", s)

    def test_knowledge_agent_returns_incidents(self):
        from sre_copilot.agents.knowledge_agent import KnowledgeAgent
        asyncio.run(KnowledgeAgent().run(self.ctx))
        self.assertEqual(len(self.ctx.historical_incidents), 2)
        for inc in self.ctx.historical_incidents:
            self.assertIn("id", inc)
            self.assertIn("root_cause", inc)
            self.assertIn("solution", inc)
            self.assertIn("similarity", inc)

    def test_diagnosis_agent_confidence_high_for_oom(self):
        from sre_copilot.agents.diagnosis_agent import DiagnosisAgent
        from sre_copilot.agents.k8s_agent import K8sAgent
        from sre_copilot.agents.knowledge_agent import KnowledgeAgent
        from sre_copilot.agents.log_agent import LogAgent
        # 先让 3 路 evidence 跑出来
        asyncio.run(K8sAgent().run(self.ctx))
        asyncio.run(LogAgent().run(self.ctx))
        asyncio.run(KnowledgeAgent().run(self.ctx))
        asyncio.run(DiagnosisAgent().run(self.ctx))
        # OOM 信号足够,confidence 应 >= 0.5
        self.assertGreaterEqual(self.ctx.diagnosis["confidence"], 0.5)
        self.assertIn("OOM", self.ctx.diagnosis["root_cause"])

    def test_action_agent_generates_plan(self):
        from sre_copilot.agents.action_agent import ActionAgent
        from sre_copilot.agents.diagnosis_agent import DiagnosisAgent
        from sre_copilot.agents.k8s_agent import K8sAgent
        from sre_copilot.agents.knowledge_agent import KnowledgeAgent
        from sre_copilot.agents.log_agent import LogAgent
        asyncio.run(K8sAgent().run(self.ctx))
        asyncio.run(LogAgent().run(self.ctx))
        asyncio.run(KnowledgeAgent().run(self.ctx))
        asyncio.run(DiagnosisAgent().run(self.ctx))
        asyncio.run(ActionAgent().run(self.ctx))
        plan = self.ctx.action_plan
        self.assertIn("primary_action", plan)
        self.assertIn("action", plan["primary_action"])
        self.assertIn("risk", plan["primary_action"])
        # OOM scenario 应生成 scale + restart 组合
        self.assertEqual(plan["primary_action"]["action"], "scale_deployment")
        if plan.get("secondary_action"):
            self.assertEqual(plan["secondary_action"]["action"], "restart_pods")


class TestWorkflowPipeline(unittest.TestCase):
    """6 agent 串行编排(端到端)。"""

    def test_full_pipeline_yields_each_step(self):
        from sre_copilot.workflow import IncidentWorkflow
        async def run():
            wf = IncidentWorkflow()
            alert = {"alert": "OOMKilled order-api", "service": "order-api", "severity": "P2"}
            yielded = 0
            final = None
            async for ctx in wf.run(alert=alert, run_id="run-e2e"):
                yielded += 1
                final = ctx
            return yielded, final
        yielded, final = asyncio.run(run())
        # 7 步(6 agent + 1 final)→ yield 7 次;verification 通过时正好 7,
        # 不通过时 re-plan 还会多 yield(M4 行为)。这里 verification random 80% 通过。
        self.assertGreaterEqual(yielded, 7)
        self.assertLessEqual(yielded, 22)  # 7(初) + 7(re-plan 1 次) + 7(re-plan 2 次) + 1 = 22
        # 完整状态被填上
        self.assertIsNotNone(final.metrics)
        self.assertIsNotNone(final.k8s_status)
        self.assertIsNotNone(final.log_samples)
        self.assertIsNotNone(final.historical_incidents)
        self.assertIsNotNone(final.diagnosis)
        self.assertIsNotNone(final.action_plan)
        # M4:verification 字段被填
        self.assertIsNotNone(getattr(final, "verification", None))
        # 完整状态被填上
        self.assertIsNotNone(final.metrics)
        self.assertIsNotNone(final.k8s_status)
        self.assertIsNotNone(final.log_samples)
        self.assertIsNotNone(final.historical_incidents)
        self.assertIsNotNone(final.diagnosis)
        self.assertIsNotNone(final.action_plan)


if __name__ == "__main__":
    unittest.main()