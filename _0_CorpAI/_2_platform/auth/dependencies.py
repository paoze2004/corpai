"""
Phase 3 FastAPI Depends — 鉴权 / Role / Scope 检查。

- `get_jwt_secret()` 读 env AUTH_JWT_SECRET(fail-closed:未设 raise RuntimeError)
- `get_current_user` 解析 `Authorization: Bearer <token>` → claims dict
- `require_role(*roles)` 工厂 — 校验 user.role ∈ roles 或 scope `*`
- `require_scope(needed_scope)` 工厂 — 校验 user 有 needed_scope 或 `*`

所有依赖:DB 不可达 / token 无效 / 权限不足 → raise HTTPException(401/403)。
"""
import os

from fastapi import Depends, Header, HTTPException

from _0_CorpAI._2_platform.auth.tokens import jwt_decode


def get_jwt_secret() -> str:
    """Fail-closed:env AUTH_JWT_SECRET 未设置 → RuntimeError。"""
    secret = os.getenv("AUTH_JWT_SECRET")
    if not secret:
        raise RuntimeError("AUTH_JWT_SECRET 未配置(fail-closed)")
    return secret


def get_current_user(authorization: str | None = Header(None)) -> dict:
    """解析 Bearer token,失败 → 401。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Bearer token")
    token = authorization[len("Bearer "):]
    claims = jwt_decode(token, get_jwt_secret())
    if not claims:
        raise HTTPException(401, "Invalid or expired token")
    if not claims.get("user_id"):
        raise HTTPException(401, "Token 缺少 user_id")
    return claims


def require_role(*allowed_roles: str):
    """依赖工厂:校验 role ∈ allowed 或 scope 含 `*`(super_admin)。"""
    def checker(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in allowed_roles and "*" not in user.get("scopes", []):
            raise HTTPException(403, f"Role 不足,需要 {allowed_roles},实有 {user['role']}")
        return user
    return checker


def require_scope(needed_scope: str):
    """依赖工厂:校验 scope ≥ needed 或 `*` 通配。"""
    def checker(user: dict = Depends(get_current_user)) -> dict:
        if needed_scope not in user.get("scopes", []) and "*" not in user.get("scopes", []):
            raise HTTPException(403, f"Scope {needed_scope} 缺失")
        return user
    return checker


__all__ = ["get_jwt_secret", "get_current_user", "require_role", "require_scope"]
