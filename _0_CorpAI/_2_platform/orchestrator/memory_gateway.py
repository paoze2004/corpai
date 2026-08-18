"""
Phase 2 MemoryPool — 5 层(实际;Layer 6 Milvus 推迟)。

文档:`docs/adr/0006-memory-pool.md`(ADR-006)

对外暴露 4 个属性 + 7 个方法全部 duck-type 转发给内部 `_conv`
(`ConversationMemory`),保证现有 8 个调用方
(IntentRecognizer / TaskPlanner / OrchestratorService.get_memory_state /
wiring._make_*_executor / messages_provider 等)零改动。

新增 Layer 4 (TaskContext,内存 dict + TTL) 和 Layer 5 (CrossAgentContext,
持久化到 cross_agent_context 表)API。
"""
from datetime import datetime, timedelta
import json
from typing import Any

from _0_CorpAI._1_core.memory import ConversationMemory
from _0_CorpAI.logging import logger


class MemoryPool:
    """Phase 2 5 层 MemoryPool(ADR-006)。"""

    def __init__(self, user_id: str, session_id: str, db_conn: Any = None):
        self.user_id = user_id
        self.session_id = session_id

        # 内部 ConversationMemory(保留原 short_term_limit=20,ADR 第 30 行)
        self._conv = ConversationMemory(short_term_limit=20)
        if db_conn is not None:
            self._conv.set_db_connection(db_conn)

        # Layer 4 TaskContext — 进程内 dict 缓存 (TTL 30min)
        self._task_ctx: dict[str, dict] = {}
        # Layer 5 CrossAgentContext — 持久化到 MySQL 表,本地仅保留最近一次 read 的
        # mirror(避免每次回 round-trip;按需刷新)
        self._cross_ctx_cache: dict[str, dict] = {}

    # ════════════════════════════════════════════════════════════════
    # Duck-type 兼容层(原有 8 个调用方安全)
    # ════════════════════════════════════════════════════════════════
    @property
    def short_term_messages(self) -> list[dict]:
        return self._conv.short_term_messages

    @property
    def user_profile(self) -> dict:
        return self._conv.user_profile

    @property
    def current_task(self) -> dict:
        return self._conv.current_task

    @property
    def entity_history(self) -> list[dict]:
        return self._conv.entity_history

    def add_message(self, role: str, content: str) -> "asyncio.Task | None":
        """透传到 _conv;在 event loop 中返后台 Task,否则 None。"""
        return self._conv.add_message(role, content)

    def update_profile(self, profile_update: dict) -> None:
        self._conv.update_profile(profile_update)

    def update_task_context(self, task_update: dict) -> None:
        self._conv.update_task_context(task_update)

    def extract_entities(self, intent_type: str, query: str) -> None:
        self._conv.extract_entities(intent_type, query)

    def get_short_term_text(self) -> str:
        return self._conv.get_short_term_text()

    def get_profile_text(self) -> str:
        return self._conv.get_profile_text()

    def clear(self) -> None:
        self._conv.clear()
        # Layer 4/5 也清
        self._task_ctx.clear()
        self._cross_ctx_cache.clear()

    # ════════════════════════════════════════════════════════════════
    # Layer 4 — TaskContext(进程内 TTL dict)
    # ════════════════════════════════════════════════════════════════
    def set_task_context(self, task_id: str, ctx: dict, ttl_min: int = 30) -> None:
        """设置任务级上下文,30min TTL。"""
        now = datetime.utcnow()
        self._task_ctx[task_id] = {
            "context": ctx,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "expires_at": now + timedelta(minutes=ttl_min),
        }

    def get_task_context(self, task_id: str) -> dict | None:
        """读 TaskContext。per-user 隔离:user_id 不匹配返回 None。"""
        self._purge_expired_task_contexts()
        entry = self._task_ctx.get(task_id)
        if entry is None:
            return None
        if entry["user_id"] != self.user_id:
            return None  # per-user 隔离(防止串号)
        return entry["context"]

    def clear_task_context(self, task_id: str) -> None:
        """主动清除一个 TaskContext。"""
        self._task_ctx.pop(task_id, None)

    def _purge_expired_task_contexts(self) -> None:
        """懒清除过期项(每次 get 时触发)。"""
        now = datetime.utcnow()
        expired = [
            tid for tid, e in self._task_ctx.items()
            if e["expires_at"] < now
        ]
        for tid in expired:
            del self._task_ctx[tid]
            logger.debug(f"TaskContext {tid} 过期被清除")

    # ════════════════════════════════════════════════════════════════
    # Layer 5 — CrossAgentContext(持久化到 MySQL cross_agent_context)
    # ════════════════════════════════════════════════════════════════
    def set_cross_agent_context(self, agent_id: str, ctx: dict) -> None:
        """upsert 写入 cross_agent_context 表。loud-fail:DB 不可用时 raise。"""
        conn = self._conv._db_conn
        if conn is None:
            raise RuntimeError("DB 未连接,CrossAgentContext 必须落库")
        cursor = conn.cursor()
        try:
            cursor.execute(
                """INSERT INTO cross_agent_context
                   (user_id, session_id, agent_id, context_json)
                   VALUES (%s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE context_json = VALUES(context_json)""",
                (self.user_id, self.session_id, agent_id,
                 json.dumps(ctx, ensure_ascii=False)),
            )
            conn.commit()
            self._cross_ctx_cache[agent_id] = ctx  # 本地缓存
            logger.debug(f"CrossAgentContext[{agent_id}] 已写入")
        except Exception as e:
            logger.warning(f"CrossAgentContext set 失败: {e}")
            raise  # Phase 2 loud-fail
        finally:
            cursor.close()

    def get_cross_agent_context(self, agent_id: str) -> dict | None:
        """读单 agent 的私有上下文。per-user 隔离。"""
        conn = self._conv._db_conn
        if conn is None:
            raise RuntimeError("DB 未连接")
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """SELECT context_json FROM cross_agent_context
                   WHERE user_id = %s AND session_id = %s AND agent_id = %s""",
                (self.user_id, self.session_id, agent_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            ctx = json.loads(row["context_json"]) if row["context_json"] else None
            self._cross_ctx_cache[agent_id] = ctx
            return ctx
        except Exception as e:
            logger.warning(f"CrossAgentContext get 失败: {e}")
            raise  # Phase 2 loud-fail
        finally:
            cursor.close()


__all__ = ["MemoryPool"]
