# ADR-006: MemoryPool 6 层 + 向后兼容迁移

## 状态
**Accepted + Phase 2 已实施** — 2026-08-06

Phase 2 实际落地文件:
- `CorpAI/platform/db.py` — DatabasePool 单例
- `CorpAI/platform/orchestrator/memory_gateway.py` — MemoryPool 类(5 层,Layer 6 推迟)
- `CorpAI/core/memory.py:214/246/296/331` — 4 处 silent-fail → loud-fail
- `sql/migrate_add_user_id.sql` + `scripts/migrate_add_user_id.py` — DDL 迁移
- `CorpAI/platform/wiring.py` — `_make_memory_pool` 注入;tools/* / utils/crawler 改用 DatabasePool
- `tests/memory_pool/` — 6 文件(Layer 1-5 + duck-type)

## 背景

CorpAI 当前 `ConversationMemory`(`core/memory.py:96-332`)有 **3 层记忆**:

1. **短期对话**(`short_term_messages` 表):最近 10 条消息,角色 + 内容 + 时间戳
2. **用户偏好**(`user_profiles` 表):KV 形式,如 `{"座位喜好": "二等座"}`
3. **实体历史**(`query_history` 表):用户问过的意图 + 查询内容,最多 50 条

### 现有痛点

1. **零 user_id 区分**:`core/memory.py:99-105` 是单例,alice 聊完 bob 接着聊,bob 能看到 alice 的"上次问的"
2. **Silent-fail DB 写入**:`memory.py:214/246/296` 三个 save_* 方法捕获异常后**什么都不做**,导致生产环境丢数据无感知
3. **模块级连接池**:`memory.py:107-119` 是注入的 conn;`tools/weather.py:128-136` 又独立建 pool;两份连接池资源浪费且难管理
4. **跨 Agent 上下文缺失**:平台模式需要多个 Agent 协同,但当前记忆是单一 ChatService 内部用,无法跨 Agent 共享

## 决策

实现 **6 层 MemoryPool**,**3 层现有 + 3 层新增**,用向后兼容的迁移策略。

### 6 层结构

| 层 | 范围 | 实现 | 来源 |
|---|------|------|------|
| 1. **ShortTerm** | per (user_id, session_id), limit 20 | `short_term_messages` 表 + 新增 user_id/session_id | 现有 + 扩展 |
| 2. **UserProfile** | per user_id | `user_profiles` 表 + 新增 user_id | 现有 + 扩展 |
| 3. **EntityHistory** | per user_id, limit 50 | `query_history` 表 + 新增 user_id | 现有 + 扩展 |
| 4. **TaskContext** | per (user_id, session_id), TTL 30min | **新增** Redis 或 MySQL JSON 列 | 新增 |
| 5. **CrossAgentContext** | per (user_id, session_id, agent_id) | **新增** MySQL JSON 列 | 新增 |
| 6. **LongTerm** | per user_id, 向量 | **新增** Milvus 集合 | 新增 |

### 各层职责

**Layer 1 — ShortTerm**:对话上下文,LLM prompt 用
```python
{
  "user_id": "alice",
  "session_id": "s-2026-08-06-001",
  "messages": [
    {"role": "user", "content": "北京天气怎么样", "ts": "..."},
    {"role": "assistant", "content": "...", "ts": "..."},
    ...
  ]
}
```

**Layer 2 — UserProfile**:用户偏好,跨会话持久
```python
{
  "user_id": "alice",
  "preferences": {
    "座位喜好": "二等座",
    "语言": "zh-CN"
  }
}
```

**Layer 3 — EntityHistory**:用户查询历史,用于推荐/补全
```python
{
  "user_id": "alice",
  "history": [
    {"intent": "weather", "query": "北京天气", "ts": "..."},
    ...
  ]
}
```

**Layer 4 — TaskContext**(新增):当前任务的跨 Agent 共享状态
```python
{
  "user_id": "alice",
  "session_id": "s-2026-08-06-001",
  "task_id": "t-...",
  "context": {
    "departure_city": "北京",
    "arrival_city": "上海",
    "target_date": "2026-08-10"
  },
  "ttl": "2026-08-06T11:00:00"  # 30min 后过期
}
```

**Layer 5 — CrossAgentContext**(新增):单个 Agent 私有上下文
```python
{
  "user_id": "alice",
  "session_id": "s-2026-08-06-001",
  "agent_id": "customer_service",
  "context": {
    "last_booking_attempt": {"train_number": "G1", "seats": 1}
  }
}
```

**Layer 6 — LongTerm**(新增):向量化的用户事实,跨长期回忆
```python
{
  "user_id": "alice",
  "facts": [
    {"text": "alice 喜欢坐高铁", "embedding": [...], "ts": "..."}
  ]
}
```

### 向后兼容迁移

**Phase 2 关键 SQL**:
```sql
-- 加列(向后兼容,旧代码不需要改)
ALTER TABLE short_term_messages ADD COLUMN user_id VARCHAR(64) NOT NULL DEFAULT 'legacy';
ALTER TABLE short_term_messages ADD COLUMN session_id VARCHAR(64) NOT NULL DEFAULT 'legacy';
ALTER TABLE user_profiles ADD COLUMN user_id VARCHAR(64) NOT NULL DEFAULT 'legacy';
ALTER TABLE query_history ADD COLUMN user_id VARCHAR(64) NOT NULL DEFAULT 'legacy';

-- 加索引(查询性能)
CREATE INDEX idx_short_user ON short_term_messages(user_id, session_id, message_order);
CREATE INDEX idx_entity_user ON query_history(user_id, query_time);
CREATE INDEX idx_profile_user ON user_profiles(user_id);

-- 新表(平台新增)
CREATE TABLE task_context (
    task_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    context_json JSON NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    INDEX idx_ttl (expires_at),
    INDEX idx_user (user_id, session_id)
);

CREATE TABLE cross_agent_context (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    agent_id VARCHAR(64) NOT NULL,
    context_json JSON NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_user_agent (user_id, session_id, agent_id)
);
```

**迁移策略**:
1. **Phase 2 第一步**:加列(默认 `'legacy'`),旧代码继续工作
2. **Phase 2 第二步**:新代码 `MemoryPool` 显式写 user_id
3. **Phase 2 第三步**:保留旧 `ConversationMemory` 路径**至少一个 release cycle**(作为 fallback)
4. **Phase 2 第四步**:监控新路径写入量,稳定后删除旧路径

### DatabasePool 集中化

**当前**:
- `core/memory.py:107-119` 注入 conn
- `tools/weather.py:128-136` 模块级 `MySQLConnectionPool`
- 各自维护,资源浪费

**目标**(`platform/db.py`):
```python
class DatabasePool:
    """单例,所有模块共享"""
    _instance = None
    
    @classmethod
    def get(cls) -> DatabasePool:
        if cls._instance is None:
            cls._instance = cls._create()
        return cls._instance
    
    def get_conn(self) -> Connection: ...
    def transactional(self, fn) -> Result: ...
    def healthcheck(self) -> bool: ...
    def stats(self) -> dict: ...  # 连接数/活跃数/错误数
```

**强制**:所有模块从 `DatabasePool.get().get_conn()` 取连接,不再自己 new pool。

### Loud-Fail 替换 Silent-Fail

```python
# 现有(core/memory.py:214 等):
def save_profile_to_db(self):
    try:
        db.execute(INSERT, ...)
        db.commit()
    except Exception as e:
        logger.error(f"保存失败: {e}")  # 只 log,不 raise
        # 数据丢了

# 目标(platform/memory_gateway.py):
def save_profile_to_db(self):
    try:
        db.execute(INSERT, ...)
        db.commit()
    except Exception as e:
        logger.warning(f"profile save failed for user={self.user_id}: {e}")
        self._save_failure_counter.inc()  # Prometheus 计数
        # 仍 raise 给调用方决策;默认调用方选择 fail-closed
```

## 后果

### 正面
1. **per-user 隔离**:alice 看不到 bob 的记忆,RBAC 真正生效
2. **跨 Agent 协同**:TaskContext 让多 Agent 共享"出差订票任务"的当前状态,无需重复问用户
3. **长期记忆**:Layer 6 向量化,可做"用户上次喜欢 A,这次推荐相似 B"
4. **资源集中**:DatabasePool 单例,连接数可控,无重复连接池
5. **数据完整性**:Loud-fail 让丢数据有感知

### 负面
1. **迁移工作量大**:ALTER TABLE + 新表 + 新代码路径
2. **新表维护**:task_context 需要 TTL 清理(后台 cron)
3. **跨 Agent 调试复杂**:Layer 4/5 是新的,出问题难定位
4. **Layer 6 向量化成本**:每次反思抽取要调 embedding API

### 中性
1. **Layer 6 暂不实现**:MVP 只做 Layer 1-5;Layer 6 留待 Phase 6+ 评估(需要向量库和反思 prompt)
2. **旧路径保留**:Phase 2-3 旧 `ConversationMemory` 仍可工作,Phase 4 后删除

## 权衡

| 备选方案 | 取舍 |
|---------|------|
| **Redis 做 Layer 4/5** | ⚠️ 备选 — 性能更好,但增加基础设施依赖;MVP 用 MySQL JSON 列 |
| **用 SQLite 存 memory** | ❌ 拒绝 — 单机部署可以,但多并发/多实例场景下不行 |
| **不引入 Layer 6(向量长期记忆)** | ⚠️ MVP 推迟 — Phase 5/6 再加;Layer 6 风险大收益慢 |
| **强制所有旧数据迁移 user_id** | ❌ 拒绝 — 旧数据本来就是全局共享,无法追溯;直接标 'legacy' 即可 |
| **保留 silent-fail(向后兼容)** | � 拒绝 — silent-fail 是已知 bug,Phase 2 必修 |

## 验证

- **Phase 2 验收**:`uv run pytest tests/memory_pool/` 全绿
  - 6 层读写测试、TTL 过期测试、并发测试、per-user 隔离测试
- **Phase 2 手工验收**:
  - alice 登录 + 聊天 → SELECT short_term_messages WHERE user_id='alice' 有记录
  - bob 登录 + 聊天 → alice 看不到 bob 的记录
  - 故意拔掉 MySQL → loud-fail 让请求 500(不是静默通过)
- **Phase 4 验收**:Prometheus 看到 `_save_failure_counter` 指标

## 参考引用

- 现有 3 层:`CorpAI/core/memory.py:99-105`
- Silent-fail 反面教材:`CorpAI/core/memory.py:214/246/296`
- 模块级 pool:`CorpAI/tools/weather.py:128-136`
- 数据库表:`sql/create_all_tables.sql:136-159`
