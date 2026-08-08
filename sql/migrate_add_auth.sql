-- ============================================================
-- Phase 3 RBAC:4 张 auth_ 表 + 4 角色 → scope 种子数据
-- 纯 DDL — 幂等性由 scripts/migrate_add_auth.py 用
-- INFORMATION_SCHEMA 守卫
--
-- 关联文档:docs/adr/0005-rbac-model.md(Accepted 2026-08-06,Phase 3 修订)
--
-- Phase 3 修订:
--   password_hash 列从 ARGON2 改 PBKDF2(user 决定不引 PyJWT/argon2-cffi)
--   hash 格式:`pbkdf2:sha256:200000:<salt_hex>:<dk_hex>`
--   Phase 6+ 可换 Argon2id(ADR §验证)
-- ============================================================

-- ==================== 1. auth_tenants ====================
CREATE TABLE IF NOT EXISTS auth_tenants (
    tenant_id   VARCHAR(64)  PRIMARY KEY,
    name        VARCHAR(128) NOT NULL,
    is_active   BOOLEAN      DEFAULT TRUE,
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Phase 3:多租户表 — 一个 tenant_id 隔离一组用户';

-- ==================== 2. auth_users ====================
CREATE TABLE IF NOT EXISTS auth_users (
    user_id        VARCHAR(64)  PRIMARY KEY,
    username       VARCHAR(64)  UNIQUE NOT NULL,
    password_hash  VARCHAR(256) NOT NULL COMMENT 'pbkdf2:sha256:200000:salt:hash 格式',
    tenant_id      VARCHAR(64)  NOT NULL,
    role           VARCHAR(32)  NOT NULL COMMENT 'employee|agent_author|admin|super_admin',
    scopes         TEXT COMMENT '冗余:逗号分隔的额外 scopes(主表 auth_role_scopes)',
    is_active      BOOLEAN      DEFAULT TRUE,
    created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
    last_login_at  DATETIME     NULL,
    INDEX idx_tenant (tenant_id),
    INDEX idx_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Phase 3:平台用户表';

-- ==================== 3. auth_role_scopes(角色 → scope 多对多)====================
CREATE TABLE IF NOT EXISTS auth_role_scopes (
    role   VARCHAR(32) NOT NULL,
    scope  VARCHAR(64) NOT NULL,
    PRIMARY KEY (role, scope)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Phase 3:角色→scope 映射表(super_admin 用 * 通配)';

-- ==================== 4. auth_audit_log ====================
CREATE TABLE IF NOT EXISTS auth_audit_log (
    id         BIGINT       AUTO_INCREMENT PRIMARY KEY,
    ts         DATETIME(3)  DEFAULT CURRENT_TIMESTAMP(3),
    user_id    VARCHAR(64)  NOT NULL,
    tenant_id  VARCHAR(64)  NOT NULL,
    action     VARCHAR(64)  NOT NULL COMMENT 'login|logout|plugin_invoke|admin_user_create|...',
    target     VARCHAR(256) COMMENT '资源标识',
    ip         VARCHAR(64),
    user_agent TEXT,
    result     VARCHAR(32)  NOT NULL COMMENT 'allow|deny',
    reason     TEXT,
    INDEX idx_user_ts   (user_id, ts),
    INDEX idx_tenant_ts (tenant_id, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Phase 3:审计日志(永不 silent-fail — ADR §Audit)';

-- ==================== 5. 种子数据:角色 → scope 映射(4 角色 × 8 scope)====================
INSERT IGNORE INTO auth_role_scopes (role, scope) VALUES
  ('employee',     'chat:write'),
  ('agent_author', 'chat:write'),
  ('agent_author', 'plugin:write'),
  ('admin',        'chat:write'),
  ('admin',        'plugin:read'),
  ('admin',        'plugin:write'),
  ('admin',        'user:read'),
  ('admin',        'log:read'),
  ('super_admin',  '*');
