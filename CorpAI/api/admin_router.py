"""
Phase 3 Admin API Router — FastAPI APIRouter prefix=/admin/api。

端点(6 业务 + 1 占位):
    POST /login                公开  username/password → JWT
    GET  /users         admin  当前租户用户列表
    POST /users/{id}/role  super_admin  改 user role
    GET  /plugins        plugin:read  discover_all 列表
    POST /plugins/{n}/enable  plugin:write  占位(Phase 5 真 toggle)
    GET  /logs           log:read  按 page/size/user_id 过滤
    GET  /metrics        log:read  Phase 3 占位

所有 DB 操作走 DatabasePool.get().get_conn(),每次 try/finally close。
fail-closed:DB 不可达 → raise HTTPException(500/403)。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from CorpAI.platform.auth.audit import write_audit_log
from CorpAI.platform.auth.dependencies import (
    get_jwt_secret,
    get_current_user,
    require_role,
    require_scope,
)
from CorpAI.platform.auth.passwords import verify_password
from CorpAI.platform.auth.scopes import scopes_for_role
from CorpAI.platform.auth.tokens import make_access_token
from CorpAI.platform.db import DatabasePool
from CorpAI.platform.plugin_manager import PluginManifest, discover_all

router = APIRouter(prefix="/admin/api", tags=["admin"])


# ════════════════════════════════════════════════════════════════
# Helpers — 私有 DB 操作
# ════════════════════════════════════════════════════════════════
def _lookup_user(username: str) -> dict | None:
    """按 username 查 auth_users,返 dict 或 None。"""
    conn = None
    try:
        conn = DatabasePool.get().get_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """SELECT user_id, username, password_hash, tenant_id, role,
                      scopes, is_active
               FROM auth_users WHERE username = %s""",
            (username,),
        )
        row = cur.fetchone()
        cur.close()
        return row
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _list_users_for_tenant(tenant_id: str) -> list[dict]:
    """同租户用户列表。"""
    conn = None
    try:
        conn = DatabasePool.get().get_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """SELECT user_id, username, role, is_active, last_login_at
               FROM auth_users WHERE tenant_id = %s
               ORDER BY created_at""",
            (tenant_id,),
        )
        rows = cur.fetchall()
        cur.close()
        return rows
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _update_user_role(user_id: str, role: str) -> int:
    """返回 affected rows;0 = 不存在 / 无变化。"""
    conn = None
    try:
        conn = DatabasePool.get().get_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE auth_users SET role=%s WHERE user_id=%s",
            (role, user_id),
        )
        conn.commit()
        affected = cur.rowcount
        cur.close()
        return affected
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _list_logs(
    page: int, size: int, user_id_filter: str | None
) -> tuple[list[dict], int]:
    """分页查 audit log,返 (rows, total)。"""
    offset = (page - 1) * size
    conn = None
    try:
        conn = DatabasePool.get().get_conn()
        cur = conn.cursor(dictionary=True)
        where = ""
        params: list = []
        if user_id_filter:
            where = "WHERE user_id = %s"
            params.append(user_id_filter)
        cur.execute(
            f"""SELECT ts, user_id, tenant_id, action, target, ip,
                       user_agent, result, reason
                FROM auth_audit_log {where}
                ORDER BY ts DESC LIMIT %s OFFSET %s""",
            params + [size, offset],
        )
        rows = cur.fetchall()
        cur.execute(
            f"SELECT COUNT(*) AS c FROM auth_audit_log {where}",
            params,
        )
        total = cur.fetchone()["c"]
        cur.close()
        return rows, total
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ════════════════════════════════════════════════════════════════
# 端点
# ════════════════════════════════════════════════════════════════
@router.post("/login")
async def login(
    request: Request,
    username: str = Query(..., min_length=1),
    password: str = Query(..., min_length=1),
):
    """公开登录:username/password → JWT。失败写 audit log。"""
    user = _lookup_user(username)
    ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")

    if not user or not verify_password(password, user["password_hash"]):
        # audit 失败登录(无 user_id 时写 anonymous)
        write_audit_log(
            user_id=user["user_id"] if user else username,
            tenant_id=user["tenant_id"] if user else "unknown",
            action="login_fail",
            target=username,
            ip=ip, user_agent=user_agent,
            result="deny", reason="invalid_credentials",
        )
        raise HTTPException(401, "用户名或密码错误")
    if not user["is_active"]:
        raise HTTPException(403, "账号已停用")

    scopes = scopes_for_role(user["role"])
    token = make_access_token(
        user_id=user["user_id"], tenant_id=user["tenant_id"],
        role=user["role"], scopes=scopes,
        secret=get_jwt_secret(), ttl=7200,
    )
    write_audit_log(
        user_id=user["user_id"], tenant_id=user["tenant_id"],
        action="login", target=username,
        ip=ip, user_agent=user_agent,
        result="allow",
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 7200,
        "role": user["role"],
        "username": username,
    }


@router.get("/users")
async def list_users(user: dict = Depends(require_role("admin", "super_admin"))):
    """同租户用户列表。employee 看不到此端点。"""
    users = _list_users_for_tenant(user["tenant_id"])
    return {"data": users, "total": len(users)}


@router.post("/users/{user_id}/role")
async def change_user_role(
    user_id: str,
    role: str = Query(..., min_length=1),
    user: dict = Depends(require_role("super_admin")),
    request: Request = None,
):
    """super_admin 改 user role。"""
    if role not in ("employee", "agent_author", "admin", "super_admin"):
        raise HTTPException(400, f"无效 role: {role}")
    affected = _update_user_role(user_id, role)
    if affected == 0:
        raise HTTPException(404, f"user_id 不存在: {user_id}")
    # audit
    ip = request.client.host if request and request.client else "unknown"
    write_audit_log(
        user_id=user["user_id"], tenant_id=user["tenant_id"],
        action="admin_user_role_change", target=user_id,
        ip=ip, user_agent=(request.headers.get("user-agent", "") if request else ""),
        result="allow", reason=f"new_role={role}",
    )
    return {"status": "ok", "user_id": user_id, "role": role}


@router.get("/plugins")
async def list_plugins(user: dict = Depends(require_scope("plugin:read"))):
    """列出通过 entry_points 发现的所有 plugin。"""
    r = discover_all()
    return {
        "data": [
            {
                "name": m.name,
                "version": m.version,
                "description": m.description,
                "plugin_type": m.plugin_type,
                "endpoint": m.endpoint,
                "required_intents": m.required_intents,
                "tags": m.tags,
            }
            for m in r.list_all()
        ],
        "total": len(r.list_all()),
    }


@router.post("/plugins/{name}/enable")
async def enable_plugin(
    name: str,
    user: dict = Depends(require_scope("plugin:write")),
    request: Request = None,
):
    """toggle 占位 — Phase 3 只返回 ok,Phase 5 真禁用/启用。"""
    # audit
    ip = request.client.host if request and request.client else "unknown"
    write_audit_log(
        user_id=user["user_id"], tenant_id=user["tenant_id"],
        action="plugin_enable", target=name,
        ip=ip, user_agent=(request.headers.get("user-agent", "") if request else ""),
        result="allow", reason="phase3_placeholder",
    )
    return {"status": "ok", "name": name, "enabled": True, "note": "Phase 3 placeholder"}


@router.get("/logs")
async def list_logs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    user_id: str | None = Query(None),
    user: dict = Depends(require_scope("log:read")),
):
    """audit log 分页查询。"""
    rows, total = _list_logs(page, size, user_id)
    # date/datetime → ISO string
    out = []
    for r in rows:
        item = dict(r)
        if item.get("ts"):
            item["ts"] = item["ts"].isoformat() if hasattr(item["ts"], "isoformat") else str(item["ts"])
        out.append(item)
    return {"data": out, "total": total, "page": page, "size": size}


@router.get(
    "/metrics",
    dependencies=[Depends(require_scope("log:read"))],
)
async def prometheus_metrics():
    """Phase 4:Prometheus exposition 文本格式 — 同 app.py 公开 /metrics,但需要 JWT。"""
    return Response(
        generate_latest(),
        headers={"Content-Type": CONTENT_TYPE_LATEST},
    )


__all__ = ["router"]
