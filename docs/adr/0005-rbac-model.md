# ADR-005: RBAC 4 角色 + 多租户 + Fail-Closed

## 状态
**Accepted → Implemented (Phase 3)** — 2026-08-06

Phase 3 实施位置:
- `CorpAI/platform/auth/` 6 文件(stdlib-only password+token+scope+audit+depends)
- `CorpAI/api/admin_router.py` (6 端点 + audit log)
- `sql/migrate_add_auth.sql` + `scripts/migrate_add_auth.py`
- `scripts/bootstrap_super_admin.py`

## Phase 3 修订记录(2026-08-06)

| 改动 | 原 ADR-005 | Phase 3 实施 | 原因 |
|------|------------|---------------|------|
| 密码哈希 | `argon2-cffi` | `hashlib.pbkdf2_hmac('sha256', ..., 200_000)` | 用户决定"不引新 auth 依赖",用 stdlib 替代 |
| JWT | `PyJWT` 库 | 自实现 `jwt_encode/jwt_decode`(HS256 + base64url + hmac) | 同上,stdlib-only |
| 测试进度 | 未列 | 在 `tests/auth/` 加 6 文件,`make test-auth` / `make test-phase3` | 配套收尾 |

## 背景

CorpAI 当前是**零认证** FastAPI(`api/app.py:26` 裸 `FastAPI()`):
- 任何能访问 8080 的人都能调聊天
- 没有 CORS middleware,跨域直接挂
- 没有 rate limiting
- 没有任何用户概念,所有记忆全局共享

### 企业标准要求
- 至少 3 个角色(管理员 / 普通员工 / 业务作者)
- 多租户支持(一个平台服务多家公司)
- 插件级 scope 控制(谁能用什么插件)
- 审计日志(谁在什么时候做了什么)
- 失败安全(配置未就绪时拒绝访问,绝不 fail-open)

## 决策

实现 **4 角色 + 多租户 + Fail-Closed** 的 RBAC 系统。

### 角色定义

```
super_admin     ── 一切 scope,可管理用户/插件/租户
admin           ── 管理插件、看日志,scope 受租户限制
agent_author    ── 在自己租户下注册/更新插件
employee        ── 只能聊天,Agent 可见性按租户 + role 过滤
```

### 数据模型

新增 4 张表到现有 MySQL(`config.py` 数据库 `CorpAI`):

```sql
CREATE TABLE auth_tenants (
    tenant_id   VARCHAR(64) PRIMARY KEY,
    name        VARCHAR(128) NOT NULL,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE auth_users (
    user_id        VARCHAR(64) PRIMARY KEY,
    username       VARCHAR(64) UNIQUE NOT NULL,
    password_hash  VARCHAR(256) NOT NULL,   -- argon2-cffi
    tenant_id      VARCHAR(64) NOT NULL,
    role           VARCHAR(32) NOT NULL,    -- 4 选 1
    scopes         TEXT,                    -- 逗号分隔的额外 scopes
    is_active      BOOLEAN DEFAULT TRUE,
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_login_at  DATETIME,
    INDEX idx_tenant (tenant_id)
);

CREATE TABLE auth_role_scopes (
    role    VARCHAR(32) NOT NULL,
    scope   VARCHAR(64) NOT NULL,
    PRIMARY KEY (role, scope)
);

-- 种子数据(部署时插入):
-- employee → chat:write
-- agent_author → chat:write, plugin:write
-- admin → chat:write, plugin:write, plugin:read, user:read, log:read
-- super_admin → 全部 scope

CREATE TABLE auth_audit_log (
    id        BIGINT AUTO_INCREMENT PRIMARY KEY,
    ts        DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
    user_id   VARCHAR(64) NOT NULL,
    tenant_id VARCHAR(64) NOT NULL,
    action    VARCHAR(64) NOT NULL,    -- 'login', 'plugin_invoke', 'admin_user_create', ...
    target    VARCHAR(256),           -- 资源标识
    ip        VARCHAR(64),
    user_agent TEXT,
    result    VARCHAR(32) NOT NULL,   -- 'allow' | 'deny'
    reason    TEXT,
    INDEX idx_user_ts (user_id, ts),
    INDEX idx_tenant_ts (tenant_id, ts)
);
```

### 强制执行点

```
api/jwt_middleware.py        -- 验证 Bearer token, 注入 request.state.user
tools_gateway.require_scope  -- 每个插件 invoke 调用前检查(永不绕过)
admin_ui/views.py            -- admin 端点二次校验(纵深防御)
```

### JWT 方案
- 库:`PyJWT` (无原生依赖)
- 签名:HS256 + 服务端 secret(env 注入)
- Payload:`{user_id, tenant_id, role, scopes, exp, iat}`
- 过期:24 小时 refresh token,2 小时 access token
- 不实现 refresh token 端点(MVP),过期用户重新登录

### 密码哈希
- 库:`argon2-cffi`(无原生编译,跨平台)
- Argon2id + 默认参数(memory=64MB, time=3, parallelism=4)
- 不使用 bcrypt(老旧,Argon2 是 PHC 2015 winner)

### Fail-Closed 原则

```python
# ❌ 不允许(fail-open 风险)
def require_scope(user, scope):
    if DB_DOWN:  # 配置未就绪
        return True  # 错误!这会让所有人都能访问
    ...

# ✅ 必须(fail-closed)
def require_scope(user, scope):
    if DB_DOWN or user is None or scope not in user.scopes:
        raise HTTPException(403, "Access denied")
```

### Audit Log 不 Silent-Fail

```python
# � 不允许(对比 core/memory.py:214/246/296)
def write_audit_log(...):
    try:
        db.execute(INSERT, ...)
    except Exception:
        pass  # 错误!审计失败应该让请求失败

# ✅ 必须
def write_audit_log(...):
    try:
        db.execute(INSERT, ...)
    except Exception as e:
        logger.critical(f"Audit log write failed: {e}")
        raise HTTPException(500, "Audit unavailable, request denied")
```

## 后果

### 正面
1. **企业可上生产**:满足 SOC2/ISO27001 的基本访问控制要求
2. **多租户隔离**:一家公司的员工看不到别家公司的数据
3. **审计可追溯**:任何敏感操作有日志,合规审计能交差
4. **插件 scope 化**:每个插件可声明所需 scope,UI 隐藏用户无权限的插件

### 负面
1. **开发期摩擦**:每个 admin 端点要写 `Depends(require_scope("admin:read"))`,比裸函数啰嗦
2. **冷启动依赖**:没有用户表就不能用,首次部署必须 bootstrap 一个 super_admin
3. **JWT secret 管理**:必须进 env,K8s secret 注入
4. **Argon2 计算开销**:每次登录 ~100ms,高并发需考虑 cache

### 中性
1. **不实现 OAuth/SSO**:MVP 用本地账号;SSO 留待 Phase 6+ 评估
2. **不实现 rate limiting**:Phase 4+ 用 Nginx/traefik 层做;应用层不做
3. **不实现 API key**:只支持 JWT,API key 留待未来

## 权衡

| 备选方案 | 取舍 |
|---------|------|
| **OAuth 2.0 完整实现** | ❌ 拒绝 — MVP 不需要,本地账号够用;复杂度爆炸 |
| **Basic Auth** | ❌ 拒绝 — 不支持多角色,不适合企业 |
| **Session cookie** | ❌ 拒绝 — 前后端分离架构下,JWT 更合适 |
| **Casbin / 自带策略引擎** | �️ 备选 — Phase 6+ 如策略复杂到需要 ABAC,再评估 |
| **共享 JWT secret** | ❌ 拒绝 — HS256 + 单一 secret;多实例部署时 secret 同步即可 |

## 验证

- **Phase 3 验收**:`uv run pytest tests/auth/` 全绿
  - 登录流程、token 验证、scope 检查、租户隔离、audit log 写入
- **Phase 3 手工验收**:
  - `super_admin` 登录 → 看到所有租户 + 所有插件
  - `admin`(tenant A)登录 → 只看到 tenant A 的插件
  - `employee` 登录 → 看不到 `sre_copilot` 插件
  - 删除 `employee` 的 `cs:read` scope → 聊天触发客服插件 → 403
- **Phase 4 验收**:audit log 写入失败时返回 500(不是静默通过)

## 参考引用

- 当前零认证:`CorpAI/api/app.py:26`
- 反面教材(silent-fail):`CorpAI/core/memory.py:214/246/296`
- 未来 admin UI:5 页(`/admin/agents` `/admin/tools` `/admin/users` `/admin/logs` `/admin/metrics`)
