"""
Phase 3 RBAC scopes + 4 角色权限矩阵。

`*` scope = 通配,super_admin 用。`has_scope` 检查具体 scope 或 `*`。

4 角色定义(ADR-005 §角色定义):
    super_admin    → *,可管理用户/插件/租户
    admin          → chat:write, plugin:read, plugin:write, user:read, log:read
    agent_author   → chat:write, plugin:write
    employee       → chat:write

scope 命名规范:`<资源>:<动作>`(如 `chat:write` `plugin:read`)。

注意:`require_scope` 这个名字让给 platform.auth.dependencies(FastAPI Depends 工厂),
本文件普通函数用 `has_scope`,避开命名冲突。
"""
from __future__ import annotations


ROLE_SCOPES: dict[str, list[str]] = {
    "employee": ["chat:write"],
    "agent_author": ["chat:write", "plugin:write"],
    "admin": [
        "chat:write",
        "plugin:read",
        "plugin:write",
        "user:read",
        "log:read",
    ],
    "super_admin": ["*"],
}


def has_scope(needed: str, user_scopes: list[str]) -> bool:
    """检查 user_scopes 是否包含 needed。`*` 通配。"""
    if "*" in user_scopes:
        return True
    return needed in user_scopes


def scopes_for_role(role: str) -> list[str]:
    """查 role 对应的 scope 列表(优先 auth_role_scopes 表,fallback ROLE_SCOPES dict)。"""
    return ROLE_SCOPES.get(role, ["chat:write"])


__all__ = ["ROLE_SCOPES", "has_scope", "scopes_for_role"]
