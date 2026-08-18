"""
Phase 3 Platform auth 模块 — RBAC + JWT + audit。

子模块:
    passwords — PBKDF2 密码 hash(无 PyJWT/argon2-cffi)
    tokens    — 自实现 HS256 JWT
    scopes    — 4 角色 × scope 权限矩阵
    audit     — loud-fail 审计日志
    dependencies — FastAPI Depends(get_current_user/require_role/require_scope)

公开 API(统一从此 import):
    from _0_CorpAI._2_platform.auth import (
        hash_password, verify_password,
        jwt_encode, jwt_decode, make_access_token,
        get_current_user, require_role, require_scope,
        write_audit_log, ROLE_SCOPES, has_scope, scopes_for_role,
        get_jwt_secret,
    )

注:`require_scope` 同名在 dependencies(returns FastAPI dep)和本文件没有冲突。
scopes 模块的纯函数是 `has_scope`。
"""
from _0_CorpAI._2_platform.auth.audit import write_audit_log
from _0_CorpAI._2_platform.auth.dependencies import (
    get_current_user,
    get_jwt_secret,
    require_role,
    require_scope,
)
from _0_CorpAI._2_platform.auth.passwords import hash_password, verify_password
from _0_CorpAI._2_platform.auth.scopes import ROLE_SCOPES, has_scope, scopes_for_role
from _0_CorpAI._2_platform.auth.tokens import jwt_decode, jwt_encode, make_access_token

__all__ = [
    # passwords
    "hash_password",
    "verify_password",
    # tokens
    "jwt_encode",
    "jwt_decode",
    "make_access_token",
    # scopes
    "ROLE_SCOPES",
    "has_scope",
    "scopes_for_role",
    # audit
    "write_audit_log",
    # dependencies
    "get_current_user",
    "require_role",
    "require_scope",
    "get_jwt_secret",
]
