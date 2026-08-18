"""SRE Action Executor Kafka Consumer — M6.4。

替代 action_executor.py(Redis Stream 版)。M6 起所有 action 走 Kafka:
- 消费 `sre.actions` topic 拿到 ActionPlan
- 在 DRY_RUN 模式下:模拟执行,生成 success/failure 结果
- 发 `sre.audit` topic 给下游(verification / dashboard / M4 re-plan)

DRY_RUN=true 时不真调 K8s/Jira,只 mock 结果 + 写日志;生产改 env 切真执行。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timezone
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

logger = logging.getLogger(__name__)


class ActionExecutorKafka:
    """消费 sre.actions → 执行 → 发 sre.audit。

    用法:
        executor = ActionExecutorKafka(bootstrap_servers="localhost:9092")
        await executor.start()    # 后台跑 consume loop
        # ... 或 await executor.stop()
    """

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        actions_topic: str = "sre.actions",
        audit_topic: str = "sre.audit",
        consumer_group: str = "sre-executor",
        client_id: str = "sre-executor-001",
        dry_run: bool = True,
    ):
        self.bootstrap_servers = bootstrap_servers
        self.actions_topic = actions_topic
        self.audit_topic = audit_topic
        self.consumer_group = consumer_group
        self.client_id = client_id
        # SRE_DRY_RUN env 决定(默认 True)
        self.dry_run = (
            dry_run
            if dry_run is not None
            else os.getenv("SRE_DRY_RUN", "true").lower() == "true"
        )
        self.consumer: AIOKafkaConsumer | None = None
        self.producer: AIOKafkaProducer | None = None
        self._run_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._stats = {"consumed": 0, "executed": 0, "errors": 0}

    async def start(self) -> None:
        self.consumer = AIOKafkaConsumer(
            self.actions_topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.consumer_group,
            client_id=self.client_id,
            auto_offset_reset="earliest",
            enable_auto_commit=True,
        )
        self.producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            client_id=f"{self.client_id}-producer",
        )
        await self.consumer.start()
        await self.producer.start()
        logger.info(
            f"Action Executor 启动:订阅 {self.actions_topic},dry_run={self.dry_run}",
        )
        self._run_task = asyncio.create_task(self._consume_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._run_task:
            await self._run_task
        if self.consumer:
            await self.consumer.stop()
        if self.producer:
            await self.producer.stop()
        logger.info(f"Action Executor 停止:{self._stats}")

    def stats(self) -> dict:
        return dict(self._stats)

    # ── 内部 ─────────────────────────────────────────────

    async def _consume_loop(self) -> None:
        assert self.consumer is not None
        try:
            async for msg in self.consumer:
                if self._stop_event.is_set():
                    break
                try:
                    plan_msg = json.loads(msg.value.decode("utf-8"))
                    self._stats["consumed"] += 1
                    await self._execute_and_audit(plan_msg)
                except Exception as exc:
                    logger.exception(f"执行 action 失败:{exc}")
                    self._stats["errors"] += 1
        except asyncio.CancelledError:
            pass
        finally:
            logger.info(f"executor consume loop 退出:{self._stats}")

    async def _execute_and_audit(self, plan_msg: dict) -> None:
        """执行 ActionPlan,发结果到 sre.audit。"""
        alert_id = plan_msg.get("alert_id", "unknown")
        action_plan = plan_msg.get("action_plan", {})
        primary = action_plan.get("primary_action") or {}
        secondary = action_plan.get("secondary_action")

        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # 1. 执行 primary(auto,low/medium risk)
        primary_result = await self._do_action(primary, "primary", alert_id, ts)
        self._stats["executed"] += 1

        # 2. 执行 secondary(如果存在)
        secondary_result = None
        if secondary:
            # M3+ 应该有 approval gate;M6.4 简化为"已批准"
            secondary_result = await self._do_action(secondary, "secondary", alert_id, ts)
            self._stats["executed"] += 1

        # 3. 发 audit
        audit_payload = {
            "alert_id": alert_id,
            "primary_result": primary_result,
            "secondary_result": secondary_result,
            "ts": ts,
            "dry_run": self.dry_run,
        }
        raw = json.dumps(audit_payload, ensure_ascii=False, default=str).encode("utf-8")
        assert self.producer is not None
        await self.producer.send_and_wait(
            self.audit_topic, value=raw, key=alert_id.encode("utf-8"),
        )
        logger.info(
            f"Audit → {self.audit_topic}:alert={alert_id},"
            f"primary={primary_result['status']},"
            f"secondary={secondary_result['status'] if secondary_result else 'skipped'}",
        )

    async def _do_action(
        self, action: dict, kind: str, alert_id: str, ts: str,
    ) -> dict:
        """单条 action 执行(DRY_RUN 下 mock,生产调真 MCP Tool)。"""
        if not action:
            return {"status": "skipped", "reason": "no action"}

        action_name = action.get("action", "unknown")
        target = action.get("target", {})

        if self.dry_run:
            # DRY_RUN:模拟执行,90% 成功率(给 demo 一点戏剧性)
            await asyncio.sleep(0.1)  # 假装执行
            success = random.random() < 0.9
            return {
                "status": "success" if success else "failed",
                "action": action_name,
                "target": target,
                "kind": kind,
                "alert_id": alert_id,
                "ts": ts,
                "result": (
                    f"[DRY_RUN] 模拟执行 {action_name} on {target}"
                    + (" (失败,可触发 re-plan)" if not success else "")
                ),
            }

        # 真实执行(M7+ 接 MCP tool 替换)
        return {
            "status": "pending",
            "action": action_name,
            "target": target,
            "kind": kind,
            "alert_id": alert_id,
            "ts": ts,
            "note": "M6.4 暂未接真 MCP tool",
        }


__all__ = ["ActionExecutorKafka"]