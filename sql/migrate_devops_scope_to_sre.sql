-- ============================================================
-- v3.1 RBAC scope rename:devops:* → sre:*
-- 关联:plugins/sre_copilot/ 重命名 + sre:read/sre:write 取代 devops:read/devops:write
--
-- 范围:
--   auth_role_scopes 表(scope 列)
--   auth_users.scopes 列(冗余 TEXT 字段)
--
-- 幂等性:REPLACE 已经替换过的字符串(sre:sre → sre:sre 是 no-op)
-- 已迁移的 scope 不会被重复处理
-- ============================================================

-- ==================== 1. auth_role_scopes(主表)====================
UPDATE auth_role_scopes
   SET scope = REPLACE(scope, 'devops:', 'sre:')
 WHERE scope LIKE 'devops:%';

-- ==================== 2. auth_users.scopes(冗余 TEXT)====================
UPDATE auth_users
   SET scopes = REPLACE(scopes, 'devops:', 'sre:')
 WHERE scopes LIKE '%devops:%';

-- ==================== 验证查询(手跑 SELECT 看效果)====================
-- SELECT * FROM auth_role_scopes WHERE scope LIKE 'devops:%';
-- 期望:0 行
-- SELECT * FROM auth_role_scopes WHERE scope LIKE 'sre:%';
-- 期望:之前 devops:read/write 行,scope 已是 sre:read/sre:write