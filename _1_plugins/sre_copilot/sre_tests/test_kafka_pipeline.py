"""Kafka pipeline + executor 关键逻辑单测(不需要真 Kafka)。

测试 SREPipelineConsumer 的 buffer 状态机和 ActionExecutorKafka 的 mock 执行。
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestBufferReadiness(unittest.TestCase):
    """_all_topics_ready 状态机 — 5 topic 齐了才触发。"""

    def _make_consumer(self):
        # 绕过 __init__ 的 Kafka 客户端(用 sentinel)
        from sre_copilot.kafka_pipeline import SREPipelineConsumer
        c = SREPipelineConsumer.__new__(SREPipelineConsumer)
        c._buffer = {}
        return c

    def test_empty_buffer_not_ready(self):
        c = self._make_consumer()
        self.assertFalse(c._all_topics_ready("alt-001"))

    def test_partial_buffer_not_ready(self):
        c = self._make_consumer()
        c._buffer["alt-001"] = {
            "sre.alerts": [{"alert_id": "alt-001"}],
            "sre.metrics": [],
        }
        self.assertFalse(c._all_topics_ready("alt-001"))

    def test_all_5_topics_ready(self):
        c = self._make_consumer()
        c._buffer["alt-001"] = {t: [{}] for t in [
            "sre.alerts", "sre.metrics", "sre.k8s", "sre.logs", "sre.historical"
        ]}
        self.assertTrue(c._all_topics_ready("alt-001"))

    def test_different_alert_ids_isolated(self):
        c = self._make_consumer()
        c._buffer["alt-001"] = {t: [{}] for t in [
            "sre.alerts", "sre.metrics", "sre.k8s", "sre.logs", "sre.historical"
        ]}
        c._buffer["alt-002"] = {"sre.alerts": [{}]}
        # alt-001 齐了,alt-002 不齐
        self.assertTrue(c._all_topics_ready("alt-001"))
        self.assertFalse(c._all_topics_ready("alt-002"))


class TestTopicToCtxMapping(unittest.TestCase):
    """证据 topic → IncidentContext 字段映射(诊断 agent 期望的格式)。"""

    def test_all_evidence_topics_mapped(self):
        from sre_copilot.kafka_pipeline import EVIDENCE_TOPICS, TOPIC_TO_CTX
        for topic in EVIDENCE_TOPICS:
            if topic == "sre.alerts":
                continue  # alert 是 workflow 输入,不走 ctx
            self.assertIn(topic, TOPIC_TO_CTX, f"{topic} 没映射到 ctx 字段")
        # 全 4 个 evidence 字段都映射
        self.assertEqual(len(TOPIC_TO_CTX), 4)


class TestActionExecutorMock(unittest.TestCase):
    """ActionExecutorKafka 在 DRY_RUN 下应该 mock 执行并返 success/failed。"""

    def test_dry_run_action_returns_status(self):
        from sre_copilot.kafka_executor import ActionExecutorKafka
        executor = ActionExecutorKafka(bootstrap_servers="x", dry_run=True)
        # 模拟 action 计划
        action = {
            "action": "scale_deployment",
            "target": {"deployment": "order-api", "namespace": "production"},
            "risk": "low",
            "approval_required": False,
        }
        result = asyncio.run(executor._do_action(
            action, "primary", "alt-test-001",
            "2026-08-13T10:00:00Z",
        ))
        self.assertIn("status", result)
        self.assertIn(result["status"], ["success", "failed", "skipped"])
        self.assertEqual(result["action"], "scale_deployment")
        self.assertEqual(result["alert_id"], "alt-test-001")

    def test_dry_run_secondary_skipped_if_no_action(self):
        from sre_copilot.kafka_executor import ActionExecutorKafka
        executor = ActionExecutorKafka(bootstrap_servers="x", dry_run=True)
        result = asyncio.run(executor._do_action(
            None, "secondary", "alt-test-002", "2026-08-13T10:00:00Z",
        ))
        self.assertEqual(result["status"], "skipped")


class TestKafkaFiles(unittest.TestCase):
    """模块级 sanity check — 文件能 import 且关键导出在。"""

    def test_kafka_pipeline_imports(self):
        from sre_copilot import kafka_pipeline
        self.assertTrue(hasattr(kafka_pipeline, "SREPipelineConsumer"))
        self.assertTrue(hasattr(kafka_pipeline, "EVIDENCE_TOPICS"))

    def test_kafka_executor_imports(self):
        from sre_copilot import kafka_executor
        self.assertTrue(hasattr(kafka_executor, "ActionExecutorKafka"))


if __name__ == "__main__":
    unittest.main()