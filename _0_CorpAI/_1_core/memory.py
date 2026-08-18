"""
需求：实现CorpAI的记忆管理模块，包括短期对话记忆、用户偏好记忆和当前任务上下文
支持 MySQL 数据库持久化，服务重启后自动恢复记忆数据

架构图：

┌────────────────────────────────────────────────────────────────────────────┐
│                         ConversationMemory  类                             │
│                                                                            │
│  ┌─────────────────── 内存层 (Memory) ───────────────────┐                │
│  │                                                        │                │
│  │  short_term_messages[]  ── 短期对话 (最多 10 条)        │                │
│  │  user_profile{}         ── 用户偏好 KV                  │                │
│  │  current_task{}         ── 当前任务上下文               │                │
│  │  entity_history[]       ── 提取的实体历史 (最多 50 条)  │                │
│  └────────────────────┬──────────────────────────────────┘                │
│                       │ add / update / get                                 │
│                       ▼                                                    │
│  ┌─────────────────── 持久层 (MySQL) ────────────────────┐                │
│  │                                                        │                │
│  │  _db_conn ── mysql.connector 连接                      │                │
│  │  set_db_connection() / _ensure_db()  连接管理          │                │
│  │                                                        │                │
│  │  ┌──────────────────────────────────────────────┐     │                │
│  │  │  user_profiles 表                             │     │                │
│  │  │  (profile_key PK, profile_value)              │     │                │
│  │  │  save_profile_to_db()  ← INSERT ... UPSERT   │     │                │
│  │  │  load_profile_from_db()  ← SELECT            │     │                │
│  │  └──────────────────────────────────────────────┘     │                │
│  │  ┌──────────────────────────────────────────────┐     │                │
│  │  │  query_history 表                             │     │                │
│  │  │  (id PK, intent_type, query_content,          │     │                │
│  │  │   query_time)                                 │     │                │
│  │  │  save_entity_to_db()   ← INSERT               │     │                │
│  │  │  load_entities_from_db() ← SELECT ORDER BY    │     │                │
│  │  └──────────────────────────────────────────────┘     │                │
│  │  ┌──────────────────────────────────────────────┐     │                │
│  │  │  short_term_messages 表                       │     │                │
│  │  │  (id PK, role, content, message_time,         │     │                │
│  │  │   message_order)                              │     │                │
│  │  │  save_messages_to_db()   ← INSERT + trim       │     │                │
│  │  │  load_messages_from_db() ← SELECT ORDER BY    │     │                │
│  │  └──────────────────────────────────────────────┘     │                │
│  │                                                        │                │
│  │  clear_all_from_db()  ← 清空三张表                     │                │
│  └────────────────────────────────────────────────────────┘                │
│                                                                            │
│  ┌─────────────────── 序列化层 ──────────────────────────┐                │
│  │                                                        │                │
│  │  to_dict()   → 导出记忆为 dict (实体仅取最近5条)       │                │
│  │  from_dict() ← 从 dict 恢复记忆 (@classmethod)         │                │
│  └────────────────────────────────────────────────────────┘                │
└────────────────────────────────────────────────────────────────────────────┘

数据流向：

    用户消息 → add_message() → short_term_messages[] → save_messages_to_db()
                                                      → MySQL: short_term_messages 表
                                                      → (单条 INSERT + DELETE NOT IN trim)

    偏好更新 → update_profile() → user_profile{}     → save_profile_to_db()
                                                      → MySQL: user_profiles 表
                                                      → (INSERT ... ON DUPLICATE KEY UPDATE)

    实体提取 → extract_entities() → entity_history[]  → save_entity_to_db()
                                                      → MySQL: query_history 表
                                                      → (单条 INSERT)

    服务重启 → load_profile_from_db()   → 恢复 user_profile{}
              load_messages_from_db()   → 恢复 short_term_messages[]
              load_entities_from_db()   → 恢复 entity_history[]

方法分类：

    写操作 (Write)          读操作 (Read)           序列化 (Serialize)
    ──────────────────     ──────────────────      ──────────────────
    add_message()          get_short_term_text()   to_dict()
    update_profile()       get_profile_text()      from_dict()
    update_task_context()
    extract_entities()
    clear()

    持久化 (DB Write)       加载 (DB Read)          连接管理
    ──────────────────     ──────────────────      ──────────────────
    save_messages_to_db()  load_messages_from_db() set_db_connection()
    save_profile_to_db()   load_profile_from_db()  _ensure_db()
    save_entity_to_db()    load_entities_from_db()
    clear_all_from_db()
"""
import asyncio
from datetime import datetime
import json
from typing import Optional
import mysql.connector
import pytz

from _0_CorpAI.logging import logger


class ConversationMemory:
    """管理对话记忆的类，包括短期对话、用户偏好和任务上下文"""

    def __init__(self, short_term_limit: int = 10):
        self.short_term_messages = []  # 短期对话消息列表，最多保留short_term_limit条
        self.user_profile = {}  # 用户偏好，如 {"座位喜好": "二等座", "cabin_type": "经济舱"}
        self.current_task = {}  # 当前任务上下文，如 {"type": "train", "departure_city": "北京", "arrival_city": "上海"}
        self.short_term_limit = short_term_limit  # 短期记忆最大长度
        self.entity_history = []  # 历史提取的关键实体
        self._db_conn = None  # 数据库连接

    def set_db_connection(self, db_conn):
        """设置数据库连接（由 OrchestratorService/build_default_service 注入）"""
        self._db_conn = db_conn

    def _ensure_db(self):
        """确保数据库连接有效，断开则自动重连"""
        if self._db_conn is None:
            raise RuntimeError("数据库连接未初始化")
        try:
            self._db_conn.ping(reconnect=True)
        except Exception:
            raise RuntimeError("数据库连接已断开")

    def add_message(self, role: str, content: str) -> "Optional[asyncio.Task]":
        """追加到 in-memory 并持久化到数据库。

        返回:
            - 在 event loop 中:后台 asyncio.Task(持久化在 worker 线程跑,不阻塞 SSE);
              调用方 fire-and-forget 或 await 均可。
            - 无 event loop(同步测试):None,持久化已同步完成。

        设计动机:
            旧实现每次 add_message 都同步执行 save_messages_to_db,在 FastAPI 异步端点里
            会阻塞 event loop,导致 SSE [DONE] 推送被 DB 写延迟。
            流式场景下流式期间不持 DB 连接(本来就没 DB 调用),只需保证开始/结束的
            DB 写不阻塞响应关闭。
        """
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%H:%M:%S'),
        }
        self.short_term_messages.append(msg)
        # 超过限制则移除最旧的消息
        if len(self.short_term_messages) > self.short_term_limit:
            self.short_term_messages = self.short_term_messages[-self.short_term_limit:]
        # 尝试在后台线程持久化;无 event loop 时退化同步
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 同步调用场景(测试 / 启动初始化)
            self._persist_one_message(msg)
            return None
        # closure 捕获 msg,避免两个并发后台 Task 读 in-memory "last" 造成重复 INSERT
        return loop.create_task(asyncio.to_thread(self._persist_one_message, msg))

    def get_short_term_text(self) -> str:
        """获取短期对话的文本格式，用于意图识别和代理调用"""
        lines = []
        for msg in self.short_term_messages:
            role_label = "User" if msg["role"] == "user" else "Assistant"
            lines.append(f"{role_label}: {msg['content']}")
        return '\n'.join(lines)

    def update_profile(self, profile_update: dict):
        """更新用户偏好，并持久化到数据库"""
        self.user_profile.update(profile_update)
        self.save_profile_to_db()

    def update_task_context(self, task_update: dict):
        """更新当前任务上下文"""
        self.current_task.update(task_update)

    def extract_entities(self, intent_type: str, query: str):
        """从查询中提取关键实体到历史，并持久化到数据库"""
        self.entity_history.append({
            "type": intent_type,
            "query": query,
            "timestamp": datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
        })
        # 只保留最近50条实体记录
        if len(self.entity_history) > 50:
            self.entity_history = self.entity_history[-50:]
        # 持久化单条到数据库
        self.save_entity_to_db(intent_type, query)

    def get_profile_text(self) -> str:
        """获取用户偏好的文本描述，用于注入到prompt中"""
        if not self.user_profile:
            return "无已知的用户偏好"
        items = [f"{k}: {v}" for k, v in self.user_profile.items()]
        return "，".join(items)

    def clear(self):
        """清空所有记忆，同时清除数据库数据"""
        self.short_term_messages = []
        self.user_profile = {}
        self.current_task = {}
        self.entity_history = []
        self.clear_all_from_db()

    def to_dict(self) -> dict:
        """导出记忆为字典，用于序列化"""
        return {
            "short_term_messages": self.short_term_messages,
            "user_profile": self.user_profile,
            "current_task": self.current_task,
            "entity_history": self.entity_history[-5:]  # 只导出最近5条
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ConversationMemory':
        """从字典导入记忆"""
        memory = cls()
        memory.short_term_messages = data.get("short_term_messages", [])
        memory.user_profile = data.get("user_profile", {})
        memory.current_task = data.get("current_task", {})
        memory.entity_history = data.get("entity_history", [])
        return memory

    # ==================== 数据库持久化 ====================

    def save_profile_to_db(self):
        """将用户偏好持久化到数据库（UPSERT）"""
        if self._db_conn is None:
            return
        try:
            self._ensure_db()
            cursor = self._db_conn.cursor()
            for key, value in self.user_profile.items():
                cursor.execute(
                    "INSERT INTO user_profiles (profile_key, profile_value) "
                    "VALUES (%s, %s) ON DUPLICATE KEY UPDATE profile_value = %s",
                    (key, str(value), str(value))
                )
            self._db_conn.commit()
            cursor.close()
        except Exception as e:
            logger.warning(f"profile save failed: {e}")
            raise  # Phase 2: loud-fail(ADR-006: ADR§Loud-Fail)

    def load_profile_from_db(self):
        """从数据库加载用户偏好"""
        if self._db_conn is None:
            return
        try:
            self._ensure_db()
            cursor = self._db_conn.cursor(dictionary=True)
            cursor.execute("SELECT profile_key, profile_value FROM user_profiles")
            rows = cursor.fetchall()
            cursor.close()
            self.user_profile = {row["profile_key"]: row["profile_value"] for row in rows}
        except Exception as e:
            print(f"从数据库加载用户偏好失败: {e}")

    def save_entity_to_db(self, intent_type: str, query: str):
        """将单条查询实体持久化到数据库"""
        if self._db_conn is None:
            return
        try:
            self._ensure_db()
            cursor = self._db_conn.cursor()
            now = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                "INSERT INTO query_history (intent_type, query_content, query_time) "
                "VALUES (%s, %s, %s)",
                (intent_type, json.dumps({"query": query}, ensure_ascii=False), now)
            )
            self._db_conn.commit()
            cursor.close()
        except Exception as e:
            logger.warning(f"entity save failed: {e}")
            raise  # Phase 2: loud-fail

    def load_entities_from_db(self, limit: int = 50):
        """从数据库加载查询历史，按时间倒序取最近N条"""
        if self._db_conn is None:
            return
        try:
            self._ensure_db()
            cursor = self._db_conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT intent_type, query_content, query_time FROM query_history "
                "ORDER BY query_time DESC LIMIT %s",
                (limit,)
            )
            rows = cursor.fetchall()
            cursor.close()
            # 按时间正序排列（倒序取出来后翻转）
            rows.reverse()
            self.entity_history = []
            for row in rows:
                try:
                    query_data = json.loads(row["query_content"])
                    query_text = query_data.get("query", "")
                except Exception:
                    query_text = ""
                self.entity_history.append({
                    "type": row["intent_type"],
                    "query": query_text,
                    "timestamp": row["query_time"].strftime('%Y-%m-%d %H:%M:%S') if row["query_time"] else ""
                })
        except Exception as e:
            print(f"从数据库加载查询历史失败: {e}")

    def _persist_one_message(self, msg: dict) -> None:
        """持久化指定一条消息 + trim(append-only,避免 race)。

        为什么用 closure 捕获 msg 而不是读 in-memory last:
            流式聊天场景下,user/assistant 两次 add_message 各自启动后台 Task,
            两个 Task 同时跑时会读到同一个"最后一条",造成重复 INSERT。
            把 msg 作为参数传入,每个 Task 持久化自己捕获的那条,天然 race-free。

        Phase 6 DB loud-fail:失败抛回 caller(由 add_message 的 to_thread wrapper 接收)。
        """
        if self._db_conn is None:
            return
        try:
            self._ensure_db()
            cursor = self._db_conn.cursor()
            cursor.execute(
                "INSERT INTO short_term_messages (role, content, message_time, message_order) "
                "VALUES (%s, %s, %s, %s)",
                (msg["role"], msg["content"], msg["timestamp"],
                 len(self.short_term_messages)),
            )
            cursor.execute(
                "DELETE FROM short_term_messages WHERE id NOT IN ("
                "  SELECT id FROM ("
                "    SELECT id FROM short_term_messages ORDER BY id DESC LIMIT %s"
                "  ) AS t"
                ")",
                (self.short_term_limit,),
            )
            self._db_conn.commit()
            cursor.close()
        except Exception as e:
            logger.warning(f"messages save failed: {e}")
            raise  # Phase 2: loud-fail

    def save_messages_to_db(self):
        """向后兼容入口:持久化最后一条 in-memory 消息。

        老调用方(包括 chat() 同步路径、单元测试)仍可直接调;
        新代码优先用 _persist_one_message(msg) + add_message 的异步包装。
        """
        if self.short_term_messages:
            self._persist_one_message(self.short_term_messages[-1])

    def load_messages_from_db(self):
        """从数据库加载短期对话"""
        if self._db_conn is None:
            return
        try:
            self._ensure_db()
            cursor = self._db_conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT role, content, message_time FROM short_term_messages ORDER BY message_order ASC"
            )
            rows = cursor.fetchall()
            cursor.close()
            self.short_term_messages = [
                {"role": row["role"], "content": row["content"], "timestamp": row["message_time"]}
                for row in rows
            ]
        except Exception as e:
            print(f"从数据库加载短期对话失败: {e}")

    def clear_all_from_db(self):
        """清空数据库中所有记忆数据"""
        if self._db_conn is None:
            return
        try:
            self._ensure_db()
            cursor = self._db_conn.cursor()
            cursor.execute("DELETE FROM short_term_messages")
            cursor.execute("DELETE FROM query_history")
            cursor.execute("DELETE FROM user_profiles")
            self._db_conn.commit()
            cursor.close()
        except Exception as e:
            logger.warning(f"memory clear failed: {e}")
            raise  # Phase 2: loud-fail (ADR-006 §Loud-Fail)
