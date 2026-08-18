"""SRE Action Executor — Redis Stream consumer 异步执行 AI 生成的修复方案。

为什么用 Redis Stream(不用 Celery/Kafka):
- Celery 太重(Celery beat + worker + broker 三件套),本场景只需"异步执行 + 重试"
- Kafka 需要 Zookeeper/KRaft,本地起不来
- Redis Stream XADD + XREADGROUP 够用:幂等 + 阻塞读 + 自动 ACK

为什么需要 Executor(不能直接在 chat 同步执行):
- chat 流式响应超时最长 30s,但 K8s rollout 可能跑 2 分钟
- 一次重启多个 deployment 必须串行,不能并行写 K8s API
- 失败要重试,不能让用户等

设计:
  1. AI Agent 在 plan 写入 sre_action_plans(status=pending) 后,XADD 一条消息:
     XADD sre:actions:stream * plan_id 123 executor_group
  2. Executor 进程跑消费循环:
     XREADGROUP GROUP sre_workers COUNT 1 BLOCK 5000 STREAMS sre:actions:stream >
  3. 拿到 plan_id → 读 plan → status=approved → 执行 → 落 audit_log → ACK

数据流:
  ChatAgent → plan DB → XADD → Executor.consume() → tool.execute() → ACK + audit

幂等:
  XREADGROUP 同 consumer-group + 同 message_id 不会被第二个 consumer 读到
  Executor 内部用 plan_id 加 SELECT ... FOR UPDATE 行锁(双保险)

依赖:
  redis>=5.0 (用 redis.asyncio)
"""
from __future__ import annotations

import asyncio
import json
import logging

from redis.exceptions import TimeoutError as RedisTimeoutError
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from _0_CorpAI._2_platform.observability.metrics import SRE_ACTION_EXECUTED

logger = logging.getLogger(__name__)


# ─── Stream 名 + Consumer Group ───

STREAM_NAME = "sre:actions:stream"
CONSUMER_GROUP = "sre_workers"
DEDUP_KEY_PREFIX = "sre:action:done:"  # SETNX 幂等标记,值=timestamp


# ─── 数据模型 ───

@dataclass
class ActionMessage:
    """从 Redis Stream 读到的待执行消息。"""
    plan_id: int
    message_id: str
    enqueued_at: float


# ─── 错误类型 ───

class ExecutorError(Exception):
    """Executor 业务错误(可重试/不可重试细分)。"""
    pass


class RetryableError(ExecutorError):
    """网络超时/临时不可用 — 应该 XADD retry 或 XCLAIM 让别的 worker 接。"""
    pass


class PermanentError(ExecutorError):
    """代码 bug / 配置错 / 资源不存在 — 不重试,直接 failed + 通知。"""
    pass


# ─── Action Executor 主类 ───

class ActionExecutor:
    """消费 sre:actions:stream,执行已批的 action plan。

    用法:
        executor = ActionExecutor(redis_url="redis://localhost:6379/0")
        asyncio.run(executor.run())  # 阻塞跑
    """

    def __init__(
        self,
        redis_url: str | None = None,
        consumer_name: str | None = None,
        tool_dispatcher: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
        max_retries: int = 3,
    ) -> None:
        self.redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self.consumer_name = consumer_name or f"worker-{uuid.uuid4().hex[:8]}"
        self.max_retries = max_retries
        # 工具分发器(注入,默认 None → 用 _default_dispatcher)
        self.tool_dispatcher = tool_dispatcher or self._default_dispatcher
        self._redis: Any = None
        self._stop = asyncio.Event()

    async def _get_redis(self) -> Any:
        """Lazy init Redis async client + 创建 consumer group(幂等)。"""
        if self._redis is not None:
            return self._redis
        try:
            import redis.asyncio as redis_asyncio
        except ImportError as exc:
            raise ExecutorError("redis 包缺失 — uv add redis") from exc
        self._redis = redis_asyncio.from_url(self.redis_url, decode_responses=True)
        try:
            await self._redis.xgroup_create(
                name=STREAM_NAME, groupname=CONSUMER_GROUP,
                id="0", mkstream=True,
            )
            logger.info(f"consumer group {CONSUMER_GROUP} 已创建")
        except Exception as exc:
            # BUSYGROUP 表示已存在,幂等
            if "BUSYGROUP" not in str(exc):
                raise
        return self._redis

    async def enqueue(self, plan_id: int, extra: dict | None = None) -> str:
        """外部调用:XADD 一条 plan_id 进 stream。返回 message_id。"""
        r = await self._get_redis()
        payload = {"plan_id": str(plan_id), "enqueued_at": str(time.time())}
        if extra:
            payload.update({k: str(v) for k, v in extra.items()})
        msg_id = await r.xadd(STREAM_NAME, payload)
        logger.info(f"plan_id={plan_id} 已入队 message_id={msg_id}")
        return msg_id

    async def run(self) -> None:
        """消费循环:阻塞读 → 执行 → ACK / 报错。

        设计:阻塞 5s(超时返回空列表)→ 让 stop() 有机会退出。
        """
        r = await self._get_redis()
        logger.info(
            f"ActionExecutor 启动 consumer={self.consumer_name} "
            f"group={CONSUMER_GROUP} stream={STREAM_NAME}",
        )
        while not self._stop.is_set():
            try:
                # XREADGROUP BLOCK 5000 — 阻塞 5s
                resp = await r.xreadgroup(
                    groupname=CONSUMER_GROUP,
                    consumername=self.consumer_name,
                    streams={STREAM_NAME: ">"},
                    count=1,
                    block=5000,
                )
                if not resp:
                    continue  # 5s 超时,空轮询

                for _stream_name, messages in resp:
                    for msg_id, fields in messages:
                        await self._handle_message(msg_id, fields)
            except asyncio.CancelledError:
                logger.info("Executor 被取消,退出")
                break
            except RedisTimeoutError:
                # v3.2.2:redis-py 8.x 的 TimeoutError 不是 builtin TimeoutError 子类,
                # 必须单独抓。Redis BLOCK 超时是预期,刷 INFO 即可(不打 stacktrace)。
                logger.info("consumer idle,等待下一个 plan...")
            except Exception as exc:
                logger.exception(f"消费循环异常:{exc}")
                await asyncio.sleep(2)  # 防雪崩
        await self._close()

    def stop(self) -> None:
        """外部调用:通知 loop 退出(下次 block 超时后退出)。"""
        self._stop.set()

    async def _close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    # ─── 单条消息处理 ───

    async def _handle_message(
        self, msg_id: str, fields: dict[str, str],
    ) -> None:
        plan_id_str = fields.get("plan_id")
        if not plan_id_str:
            logger.warning(f"message {msg_id} 缺 plan_id,跳过")
            await self._ack(msg_id)
            return
        plan_id = int(plan_id_str)
        r = await self._get_redis()

        # 幂等:同一 plan_id 已 done → 直接 ACK 不重复执行
        dedup_key = f"{DEDUP_KEY_PREFIX}{plan_id}"
        already = await r.set(dedup_key, str(time.time()), ex=86400, nx=True)
        if not already:
            logger.info(f"plan_id={plan_id} 已执行过,跳过")
            await self._ack(msg_id)
            return

        try:
            await self._execute_plan(plan_id)
            SRE_ACTION_EXECUTED.labels(tool="unknown", status="success").inc()
            await self._ack(msg_id)
        except PermanentError as exc:
            logger.error(f"plan_id={plan_id} 永久失败:{exc}")
            await self._mark_failed(plan_id, str(exc))
            SRE_ACTION_EXECUTED.labels(tool="unknown", status="permanent_error").inc()
            await self._ack(msg_id)
        except RetryableError as exc:
            logger.warning(f"plan_id={plan_id} 临时失败(将重试):{exc}")
            await self._retry_or_fail(plan_id, str(exc), msg_id)
            SRE_ACTION_EXECUTED.labels(tool="unknown", status="retryable_error").inc()
        except Exception as exc:
            logger.exception(f"plan_id={plan_id} 未分类异常")
            await self._mark_failed(plan_id, f"unexpected:{exc}")
            SRE_ACTION_EXECUTED.labels(tool="unknown", status="error").inc()
            await self._ack(msg_id)

    async def _execute_plan(self, plan_id: int) -> None:
        """执行 plan 的核心逻辑。

        1. SELECT plan(status 必须 = approved,否则 PermanentError)
        2. 反序列化 plan_json.actions[]
        3. 按顺序 await self.tool_dispatcher(action)
        4. UPDATE plan SET status='executed', finished_at=NOW
        5. INSERT sre_audit_log
        """
        from _0_CorpAI._2_platform.db import DatabasePool
        pool = DatabasePool.get()

        conn = pool.get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, incident_id, plan_json, status, risk_level "
                "FROM sre_action_plans WHERE id=%s FOR UPDATE",
                (plan_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise PermanentError(f"plan_id={plan_id} 不存在")
            _, incident_id, plan_json, status, risk_level = row
            if status != "approved":
                raise PermanentError(
                    f"plan_id={plan_id} status={status},不是 approved,"
                    f"拒绝执行",
                )

            plan_data = json.loads(plan_json)
            actions = plan_data.get("actions", [])
            if not actions:
                raise PermanentError("plan_json.actions 为空")

            # 标 executing
            cur.execute(
                "UPDATE sre_action_plans SET status='executing', "
                "executed_at=NOW() WHERE id=%s",
                (plan_id,),
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()

        # 执行 actions(顺序)
        results = []
        for i, action in enumerate(actions):
            logger.info(f"plan_id={plan_id} 执行 action[{i}/{len(actions)}]:{action.get('tool')}")
            result = await self.tool_dispatcher(action)
            results.append(result)

        # 完成
        conn = pool.get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE sre_action_plans SET status='executed', "
                "finished_at=NOW() WHERE id=%s",
                (plan_id,),
            )
            cur.execute(
                "INSERT INTO sre_audit_log "
                "(trace_id, actor, action, target_type, target_id, detail) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    "", "executor", "execute_plan", "plan",
                    str(plan_id),
                    json.dumps({
                        "incident_id": incident_id,
                        "risk_level": risk_level,
                        "action_count": len(actions),
                        "results": results,
                    }, ensure_ascii=False),
                ),
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()
        logger.info(f"plan_id={plan_id} 执行完成:{len(actions)} actions")

    async def _retry_or_fail(self, plan_id: int, err: str, msg_id: str) -> None:
        """重试计数:超 max_retries 置 failed,否则 XADD 重新入队。"""
        # 简化:每次失败 +1 到 pending retry stream,失败累计在 plan 表的 extra 字段
        # 当前实现:重试 < max_retries → 重入队;否则 failed
        from _0_CorpAI._2_platform.db import DatabasePool
        pool = DatabasePool.get()

        conn = pool.get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT plan_json FROM sre_action_plans WHERE id=%s",
                (plan_id,),
            )
            row = cur.fetchone()
            if row is None:
                await self._ack(msg_id)
                return
            plan_data = json.loads(row[0])
            retries = plan_data.get("_retries", 0)
            if retries >= self.max_retries:
                cur.execute(
                    "UPDATE sre_action_plans SET status='failed', "
                    "finished_at=NOW(), error_message=%s WHERE id=%s",
                    (f"重试 {retries} 次后仍失败:{err}", plan_id),
                )
                conn.commit()
                cur.close()
                logger.error(f"plan_id={plan_id} 重试耗尽,置 failed")
                await self._ack(msg_id)
                return
            # 加 retry 计数 + 重入队
            plan_data["_retries"] = retries + 1
            plan_data["_last_error"] = err
            cur.execute(
                "UPDATE sre_action_plans SET plan_json=%s WHERE id=%s",
                (json.dumps(plan_data, ensure_ascii=False), plan_id),
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()
        # 重新 XADD
        await self.enqueue(plan_id)
        await self._ack(msg_id)
        logger.warning(f"plan_id={plan_id} 已重新入队 (retry {retries + 1}/{self.max_retries})")

    async def _mark_failed(self, plan_id: int, err: str) -> None:
        from _0_CorpAI._2_platform.db import DatabasePool
        pool = DatabasePool.get()
        try:
            conn = pool.get_conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE sre_action_plans SET status='failed', "
                    "finished_at=NOW(), error_message=%s WHERE id=%s",
                    (err, plan_id),
                )
                cur.execute(
                    "INSERT INTO sre_audit_log "
                    "(trace_id, actor, action, target_type, target_id, detail) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    ("", "executor", "execute_failed", "plan",
                     str(plan_id),
                     json.dumps({"error": err}, ensure_ascii=False)),
                )
                conn.commit()
                cur.close()
            finally:
                conn.close()
        except Exception as exc:
            logger.exception(f"写失败状态时又出错:{exc}")

    async def _ack(self, msg_id: str) -> None:
        try:
            r = await self._get_redis()
            await r.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
        except Exception as exc:
            logger.warning(f"XACK {msg_id} 失败:{exc}")

    # ─── 默认 tool dispatcher ───

    async def _default_dispatcher(
        self, action: dict[str, Any],
    ) -> dict[str, Any]:
        """默认分发器:SRE.e(action tools)还没接上时,只 dry-run + 返回 planned。

        真实接 K8s/Jira 后,SRE.e 会注册真 dispatcher 覆盖这个。
        """
        tool = action.get("tool", "unknown")
        logger.info(f"[default_dispatcher] 模拟执行 tool={tool}")
        return {"tool": tool, "status": "dry_run", "args": action.get("args", {})}


# ─── 指标 ───

def _metric_register():
    """惰性注册 Counter(避免 import 时崩)。"""
    pass  # 由 observability/metrics.py 在 import 时注册


__all__ = [
    "CONSUMER_GROUP",
    "STREAM_NAME",
    "ActionExecutor",
    "ActionMessage",
    "ExecutorError",
    "PermanentError",
    "RetryableError",
]
