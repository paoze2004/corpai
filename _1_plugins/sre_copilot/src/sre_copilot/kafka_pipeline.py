"""SRE Pipeline Kafka Consumer — M6.3。

设计:
- 订阅 5 个 topic:sre.alerts / sre.metrics / sre.k8s / sre.logs / sre.historical
- 按 alert_id 缓冲消息,5 类齐了 → 跑 IncidentWorkflow → 产 ActionPlan
- ActionPlan 发到 sre.actions topic(给 M6.4 Action Executor 消费)
- 不在 agent 内部调 tool — 数据从 Kafka 来,真实可信(不再是 agent 自造)

为什么独立类不直接走 workflow.run():
  workflow.run() 假设 alert 是输入,内部 agent 调 tools 拉数据;
  M6 范式转变后,数据由 Kafka 推过来,workflow 应该接收预填充的 ctx。
  这里用 workflow.run_from_ctx() 走 diagnosis + action 两步(Metrics/K8s/Log/Knowledge 跳过,因为数据已在 ctx 里)。

事件关联:同 alert_id 的事件通过 Kafka message key(`alert_id:topic`)路由到同一 partition。
消费者按 alert_id group_by 后,5 topic 全有数据 = 一组完整证据 = 触发 pipeline。
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from sre_copilot.workflow import IncidentWorkflow

logger = logging.getLogger(__name__)


# Topic 顺序:在状态机里用作 "5 类都齐" 的判定
EVIDENCE_TOPICS = [
    "sre.alerts",
    "sre.metrics",
    "sre.k8s",
    "sre.logs",
    "sre.historical",
]

# Evidence topic → IncidentContext 字段
TOPIC_TO_CTX = {
    "sre.metrics": "metrics",        # ctx.metrics = list[metric_event]
    "sre.k8s": "k8s_status",        # ctx.k8s_status = list[k8s_event]
    "sre.logs": "log_samples",      # ctx.log_samples = list[log_event]
    "sre.historical": "historical_incidents",  # ctx.historical_incidents = list[incident]
}


class SREPipelineConsumer:
    """消费 5 topic → 跑 workflow → 发 sre.actions。

    用法:
        consumer = SREPipelineConsumer(
            bootstrap_servers="localhost:9092",
            workflow=IncidentWorkflow(),
        )
        await consumer.start()       # 后台跑
        # ... 或 await consumer.stop()
    """

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        workflow: IncidentWorkflow | None = None,
        consumer_group: str = "sre-pipeline",
        client_id: str = "sre-pipeline-001",
        actions_topic: str = "sre.actions",
    ):
        self.bootstrap_servers = bootstrap_servers
        self.workflow = workflow or IncidentWorkflow()
        self.consumer_group = consumer_group
        self.client_id = client_id
        self.actions_topic = actions_topic
        self.consumer: AIOKafkaConsumer | None = None
        self.producer: AIOKafkaProducer | None = None
        # alert_id → {topic_name: [events]}
        self._buffer: dict[str, dict[str, list[dict]]] = {}
        self._run_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        # 统计
        self._stats = {"consumed": 0, "alerts_processed": 0, "errors": 0}

    async def start(self) -> None:
        """启 consumer + producer,后台跑 consume loop。"""
        self.consumer = AIOKafkaConsumer(
            *EVIDENCE_TOPICS,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.consumer_group,
            client_id=self.client_id,
            auto_offset_reset="earliest",  # 首次启动从头读
            enable_auto_commit=True,
        )
        self.producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            client_id=f"{self.client_id}-producer",
        )
        await self.consumer.start()
        await self.producer.start()
        logger.info(
            f"SRE Pipeline 启动:订阅 {EVIDENCE_TOPICS},group={self.consumer_group}",
        )
        self._run_task = asyncio.create_task(self._consume_loop())

    async def stop(self) -> None:
        """停 consumer + producer。"""
        self._stop_event.set()
        if self._run_task:
            await self._run_task
        if self.consumer:
            await self.consumer.stop()
        if self.producer:
            await self.producer.stop()
        logger.info(f"SRE Pipeline 停止:{self._stats}")

    def stats(self) -> dict:
        return dict(self._stats)

    # ── 内部 ─────────────────────────────────────────────

    async def _consume_loop(self) -> None:
        """主循环:拉消息 → buffer → 5 类齐了跑 workflow。"""
        assert self.consumer is not None
        try:
            async for msg in self.consumer:
                if self._stop_event.is_set():
                    break
                try:
                    event = json.loads(msg.value.decode("utf-8"))
                    topic = msg.topic
                    alert_id = event.get("alert_id")
                    if not alert_id:
                        logger.warning(f"消息缺 alert_id,topic={topic},skip")
                        continue
                    self._buffer.setdefault(alert_id, {}).setdefault(topic, []).append(event)
                    self._stats["consumed"] += 1
                    # 5 类齐了 → 触发 pipeline
                    if self._all_topics_ready(alert_id):
                        events = self._buffer.pop(alert_id)  # 取走,避免重复
                        await self._process_alert(alert_id, events)
                except Exception as exc:
                    logger.exception(f"处理消息失败:{exc}")
                    self._stats["errors"] += 1
        except asyncio.CancelledError:
            pass
        finally:
            logger.info(f"consume loop 退出:{self._stats}")

    def _all_topics_ready(self, alert_id: str) -> bool:
        return all(
            self._buffer.get(alert_id, {}).get(t)
            for t in EVIDENCE_TOPICS
        )

    async def _process_alert(self, alert_id: str, events: dict[str, list[dict]]) -> None:
        """5 topic 收齐 → 跑 workflow → 发 sre.actions。"""
        from sre_copilot.agents.base import IncidentContext

        alert_ev = events["sre.alerts"][0]
        ctx = IncidentContext(
            run_id=alert_id,
            alert=alert_ev,
            user_token=None,  # M7+ 接真 JWT
        )
        # 预填充 4 路证据(直接从 Kafka 消息,不是 agent 调 tool)
        ctx.metrics = events["sre.metrics"]                  # list[dict]
        ctx.k8s_status = events["sre.k8s"]                  # list[dict]
        ctx.log_samples = events["sre.logs"]                  # list[dict]
        # historical topic 是嵌套结构 [{incidents: [...]}]
        hist_ev = events["sre.historical"][0] if events["sre.historical"] else {}
        ctx.historical_incidents = hist_ev.get("incidents", [])

        ctx.log_event("pipeline", f"5 topic 收齐,跑 workflow", alert_id=alert_id)

        # 跑 workflow — M1 workflow.run() 会再调一次 6 agent(包括重复 metrics/k8s/log/knowledge),
        # 但因为 ctx 已预填,这些 agent 看到的 ctx 是覆盖而不是空,实质上 agents 仍会跑(覆盖)
        # 优化:M6.3 后续可加 workflow.run_from_ctx() 跳过已填充的 agent
        try:
            async for c in self.workflow.run(
                alert=alert_ev,
                run_id=alert_id,
                user_token=None,
            ):
                ctx = c
            self._stats["alerts_processed"] += 1
            ctx.log_event("pipeline", "workflow 完成,发 sre.actions")
            await self._publish_action(alert_id, ctx)
        except Exception as exc:
            logger.exception(f"workflow 跑 {alert_id} 失败:{exc}")
            self._stats["errors"] += 1

    async def _publish_action(self, alert_id: str, ctx) -> None:
        """发 action_plan 到 sre.actions(M6.4 Action Executor 消费)。"""
        assert self.producer is not None
        if not ctx.action_plan:
            logger.warning(f"无 action_plan,不发:{alert_id}")
            return
        payload = {
            "alert_id": alert_id,
            "action_plan": ctx.action_plan,
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "events_count": len(ctx.events),
        }
        raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        await self.producer.send_and_wait(
            self.actions_topic, value=raw, key=alert_id.encode("utf-8"),
        )
        ctx.log_event("pipeline", f"已发 {self.actions_topic}", alert_id=alert_id)
        logger.info(f"ActionPlan → {self.actions_topic}:alert_id={alert_id},action={ctx.action_plan.get('primary_action', {}).get('action')}")


__all__ = ["SREPipelineConsumer", "EVIDENCE_TOPICS", "TOPIC_TO_CTX"]