-- ============================================================
-- Phase 2 增量迁移:per-user_id 隔离 + Layer 4/5 新表
-- 纯 DDL(无逻辑守卫);幂等性由 _2_scripts/migrate_add_user_id.py
-- 通过 INFORMATION_SCHEMA.COLUMNS / STATISTICS / TABLES 守卫
--
-- 适用 MySQL 5.7+(不依赖 8.0.29+ 的 IF NOT EXISTS)
-- 跑法:uv run python _2_scripts/migrate_add_user_id.py
--   (或 make migrate-phase2)
-- ============================================================

-- ==================== 1. 加 user_id / session_id 列(老数据全标 legacy)====================
ALTER TABLE short_term_messages  ADD COLUMN user_id    VARCHAR(64) NOT NULL DEFAULT 'legacy';
ALTER TABLE short_term_messages  ADD COLUMN session_id VARCHAR(64) NOT NULL DEFAULT 'legacy';
ALTER TABLE user_profiles        ADD COLUMN user_id    VARCHAR(64) NOT NULL DEFAULT 'legacy';
ALTER TABLE query_history        ADD COLUMN user_id    VARCHAR(64) NOT NULL DEFAULT 'legacy';

-- ==================== 2. 重构 user_profiles PK(允许不同用户同名 key)====================
-- 原 PK 是 profile_key 单独;加 user_id 后必须复合 PK
-- 守卫:有重复数据时 SKIP(在 .py 里 SELECT HAVING c>1 检测)
ALTER TABLE user_profiles DROP PRIMARY KEY, ADD PRIMARY KEY (user_id, profile_key);

-- ==================== 3. per-user 查询索引(性能)====================
CREATE INDEX idx_short_user   ON short_term_messages(user_id, session_id, message_order);
CREATE INDEX idx_entity_user  ON query_history(user_id, query_time);
CREATE INDEX idx_profile_user ON user_profiles(user_id);

-- ==================== 4. 新表:Layer 4 TaskContext (TTL-based 进程间共享)====================
CREATE TABLE task_context (
    task_id      VARCHAR(64)  PRIMARY KEY,
    user_id      VARCHAR(64)  NOT NULL,
    session_id   VARCHAR(64)  NOT NULL,
    context_json JSON         NOT NULL,
    created_at   DATETIME     DEFAULT CURRENT_TIMESTAMP,
    expires_at   DATETIME     NOT NULL,
    INDEX idx_ttl  (expires_at),
    INDEX idx_user (user_id, session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Layer 4: 跨 Agent 共享任务上下文 (TTL 30min)';

-- ==================== 5. 新表:Layer 5 CrossAgentContext (per-user/session/agent upsert)====================
CREATE TABLE cross_agent_context (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id      VARCHAR(64)  NOT NULL,
    session_id   VARCHAR(64)  NOT NULL,
    agent_id     VARCHAR(64)  NOT NULL,
    context_json JSON         NOT NULL,
    updated_at   DATETIME     DEFAULT CURRENT_TIMESTAMP
                             ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_user_agent (user_id, session_id, agent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Layer 5: 单 Agent 私有上下文(upsert 模式)';
