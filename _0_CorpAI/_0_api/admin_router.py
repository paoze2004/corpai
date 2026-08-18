"""
Phase 3 Admin API Router — FastAPI APIRouter prefix=/admin/api。

端点(6 业务 + 1 占位):
    POST /login                公开  username/password → JWT
    GET  /users         admin  当前租户用户列表
    POST /users/{id}/role  super_admin  改 user role
    GET  /_1_plugins        plugin:read  discover_all 列表
    POST /_1_plugins/{n}/enable  plugin:write  占位(Phase 5 真 toggle)
    GET  /logs           log:read  按 page/size/user_id 过滤
    GET  /metrics        log:read  Phase 3 占位

所有 DB 操作走 DatabasePool.get().get_conn(),每次 try/finally close。
fail-closed:DB 不可达 → raise HTTPException(500/403)。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from _0_CorpAI._2_platform.auth.audit import write_audit_log
from _0_CorpAI._2_platform.auth.dependencies import (
    get_jwt_secret,
    get_current_user,
    require_role,
    require_scope,
)
from _0_CorpAI._2_platform.auth.passwords import verify_password
from _0_CorpAI._2_platform.auth.scopes import scopes_for_role
from _0_CorpAI._2_platform.auth.tokens import make_access_token
from _0_CorpAI._2_platform.db import DatabasePool
from _0_CorpAI._2_platform.plugin_manager import PluginManifest, discover_all

router = APIRouter(prefix="/admin/api", tags=["admin"])


# ════════════════════════════════════════════════════════════════
# Helpers — 私有 DB 操作
# ════════════════════════════════════════════════════════════════
def _merge_role_and_user_scopes(role: str, user_scopes_csv: str) -> list[str]:
    """合并 role 默认 scope + auth_users.scopes 列(逗号分隔)。

    演示核心:不同用户登录不同业务系统的 scope 链构建。
    - role=employee 默认 [chat:write]
    - user.scopes='hr:read,hr:write,knowledge:read' → 合并后 [chat:write, hr:read, hr:write, knowledge:read]
    - 去重保序:role 默认在前,per-user 补充
    """
    role_scopes = scopes_for_role(role)
    extra_scopes = [s.strip() for s in user_scopes_csv.split(",") if s.strip()]
    seen: set[str] = set()
    merged: list[str] = []
    for s in role_scopes + extra_scopes:
        if s not in seen:
            seen.add(s)
            merged.append(s)
    return merged


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
    username: str = Body(..., min_length=1),
    password: str = Body(..., min_length=1),
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

    scopes = _merge_role_and_user_scopes(
        role=user["role"],
        user_scopes_csv=user.get("scopes") or "",
    )

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


# ═══════════════════════════════════════════════════════════════
# HTML Fragment 端点 — 给 HTMX 用的服务端渲染片段
# ═══════════════════════════════════════════════════════════════
# 设计:JSON 端点(/admin/api/users)保留不动(给测试 / 外部客户端);
# HTML fragment 端点(/admin/api/fragments/...)只服务 admin SPA 的 hx-get。
# 这样不破坏现有契约,渐进迁移。

_ROLES = ("employee", "agent_author", "admin", "super_admin")


def _esc(s: object) -> str:
    """HTML escape helper — f-string 默认不安全,统一过这里。"""
    from html import escape
    return escape(str(s), quote=True)


def _render_plugin_access(effective_scopes: list[str]) -> str:
    """根据 effective scopes 渲染 plugin 访问列的 HTML。

    3 个 plugin(hr/sre/faq)用 ✓/✗ 图标 + 颜色 + hover 提示缺哪个 scope。
    设计:面试官能一眼看出"这个 user 能调哪些 plugin",而且能看到"为什么" —
    hover 上去就知道是缺 hr:read 还是 hr:write。
    """
    from _0_CorpAI._2_platform.auth.scopes import has_scope
    # 真实 plugin 权限(简化:每个 plugin 看是否至少有 1 个权限 scope)
    plugins = [
        ("hr", "hr:read"),       # HR plugin 至少需要 hr:read
        ("sre", "sre:read"),     # SRE plugin 至少需要 sre:read
        ("knowledge", "knowledge:read"),     # FAQ plugin 至少需要 knowledge:read
    ]
    cells = []
    for label, needed in plugins:
        if has_scope(needed, effective_scopes):
            cells.append(
                f'<span class="inline-block px-1.5 py-0.5 rounded text-[10px] '
                f'bg-green-600/20 text-green-400 border border-green-600/40" '
                f'title="{label}: 已授权(有 {needed})">'
                f'{label} ✓</span>'
            )
        else:
            cells.append(
                f'<span class="inline-block px-1.5 py-0.5 rounded text-[10px] '
                f'bg-red-600/20 text-red-400 border border-red-600/40" '
                f'title="{label}: 拒绝(缺 {needed})">'
                f'{label} ✗</span>'
            )
    return " ".join(cells)


def _render_user_row(u: dict, is_super: bool) -> str:
    """单行用户 HTML(tbody tr)。"""
    user_id = _esc(u["user_id"])
    username = _esc(u["username"])
    role = _esc(u["role"])
    active_badge = (
        '<span class="px-2 py-1 rounded text-xs bg-green-600/20 text-green-400">active</span>'
        if u.get("is_active")
        else '<span class="px-2 py-1 rounded text-xs bg-red-600/20 text-red-400">disabled</span>'
    )
    last_login = _esc(u.get("last_login_at") or "—")

    # Phase 6+:plugin 访问列 — 算 effective scopes(role 默认 + per-user 额外),
    # 展示 3 个 plugin(hr/sre/faq) 的 ✓/✗ + hover 显示缺哪个 scope。
    # 这是面试"RBAC 链路可视化"最直观的展示。
    effective_scopes = _merge_role_and_user_scopes(
        role=u["role"], user_scopes_csv=u.get("scopes") or "",
    )
    plugin_access = _render_plugin_access(effective_scopes)

    if is_super:
        options = "".join(
            f'<option value="{_esc(r)}"{" selected" if r == u["role"] else ""}>{_esc(r)}</option>'
            for r in _ROLES
        )
        actions = (
            f'<select class="bg-[#16213e] border border-[#0f3460] rounded px-2 py-1 text-xs text-[#e0e0e0]" '
            f'hx-post="/admin/api/users/{user_id}/role" '
            f'hx-vals=\'{{"role":"REPLACE_ME"}}\' '
            f'hx-ext="json-enc" '
            f'hx-trigger="change" '
            f'hx-confirm="确定将 {username} 改为 REPLACE_ME ?" '
            f'onchange="if(this.value){{this.dataset.prev=this.value;}}">'
            f'{options}</select>'
        )
    else:
        actions = '<span class="text-xs text-gray-500">—</span>'
    return (
        f'<tr id="user-row-{user_id}" class="border-b border-[#0f3460] hover:bg-[#0f3460]/20">'
        f'<td class="px-3 py-2 text-sm">{username}</td>'
        f'<td class="px-3 py-2 text-sm">{role}</td>'
        f'<td class="px-3 py-2">{active_badge}</td>'
        f'<td class="px-3 py-2 text-xs text-gray-400">{last_login}</td>'
        f'<td class="px-3 py-2 text-xs font-mono whitespace-nowrap">{plugin_access}</td>'
        f'<td class="px-3 py-2">{actions}</td>'
        f'</tr>'
    )


@router.get(
    "/fragments/users",
    response_class=HTMLResponse,
    dependencies=[Depends(require_role("admin", "super_admin"))],
)
async def users_fragment(user: dict = Depends(get_current_user)):
    """返用户列表的 tbody rows(HTMX 用,hx-swap="innerHTML")。

    返回纯 `<tr>...</tr><tr>...</tr>` 片段,客户端页面包 thead 渲染。
    空列表时返一个 hint 行。
    """
    is_super = user.get("role") == "super_admin"
    users = _list_users_for_tenant(user["tenant_id"])
    if not users:
        return HTMLResponse(
            '<tr><td colspan="5" class="px-3 py-8 text-center text-gray-500">无用户</td></tr>'
        )
    return HTMLResponse(
        "".join(_render_user_row(u, is_super) for u in users)
    )


@router.post(
    "/fragments/users/{user_id}/role",
    dependencies=[Depends(require_role("super_admin"))],
)
async def change_user_role_htmx(
    user_id: str,
    role: str = Body(..., embed=True),
    user: dict = Depends(get_current_user),
):
    """HTMX 兼容的角色变更端点(JSON body)。

    旧 /admin/api/users/{user_id}/role?role=X 走 query string,保留给老 admin.js 用;
    HTMX 的 hx-vals 默认 form-encoded / JSON body,跟旧契约不兼容,这里加新端点。
    返回更新后的整行(给 hx-swap="outerHTML" 用)。
    """
    if role not in _ROLES:
        raise HTTPException(400, f"role 必须 ∈ {_ROLES}")
    affected = _update_user_role(user_id, role)
    if affected == 0:
        raise HTTPException(404, "user 不存在或 role 无变化")
    write_audit_log(
        actor=user["username"],
        action="change_role",
        target_type="user", target_id=user_id,
        detail=f"role→{role}",
    )
    # 查回新行数据返给 HTMX outerHTML 替换
    conn = None
    try:
        conn = DatabasePool.get().get_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """SELECT user_id, username, role, is_active, last_login_at
               FROM auth_users WHERE user_id=%s AND tenant_id=%s""",
            (user_id, user["tenant_id"]),
        )
        u = cur.fetchone()
        cur.close()
    finally:
        if conn is not None:
            try: conn.close()
            except Exception: pass
    if not u:
        raise HTTPException(404, "user 不存在")
    return HTMLResponse(_render_user_row(u, is_super=True))


def _render_plugin_row(p: dict) -> str:
    """单行 plugin HTML(tbody tr)。"""
    type_badge_color = "#e94560" if p.get("plugin_type") == "llm_agent" else "#0f3460"
    intents = " ".join(
        f'<span class="px-2 py-0.5 rounded text-xs bg-[#0f3460] text-gray-300 mr-1">{_esc(i)}</span>'
        for i in (p.get("required_intents") or [])
    ) or "—"
    tags = " ".join(
        f'<span class="px-2 py-0.5 rounded text-xs bg-[#0f3460]/60 text-gray-400 mr-1">{_esc(t)}</span>'
        for t in (p.get("tags") or [])
    ) or "—"
    return (
        f'<tr class="border-b border-[#0f3460] hover:bg-[#0f3460]/20">'
        f'<td class="px-3 py-2 text-sm font-medium">{_esc(p["name"])}</td>'
        f'<td class="px-3 py-2 text-xs text-gray-400">{_esc(p["version"])}</td>'
        f'<td class="px-3 py-2"><span class="px-2 py-1 rounded text-xs" style="background:{type_badge_color}33;color:{type_badge_color};border:1px solid {type_badge_color}66">{_esc(p["plugin_type"])}</span></td>'
        f'<td class="px-3 py-2 text-xs font-mono">{_esc(p.get("endpoint") or "—")}</td>'
        f'<td class="px-3 py-2">{intents}</td>'
        f'<td class="px-3 py-2">{tags}</td>'
        f'<td class="px-3 py-2 text-xs text-gray-400 max-w-md truncate" title="{_esc(p.get("description") or "")}">{_esc(p.get("description") or "—")}</td>'
        f'</tr>'
    )


@router.get("/fragments/agents", response_class=HTMLResponse)
async def agents_fragment(user: dict = Depends(require_scope("plugin:read"))):
    """所有 plugin(llm_agent + mcp_tool)的 tbody rows。"""
    r = discover_all()
    plugins = [
        {
            "name": m.name, "version": m.version, "description": m.description,
            "plugin_type": m.plugin_type, "endpoint": m.endpoint,
            "required_intents": m.required_intents, "tags": m.tags,
        }
        for m in r.list_all()
    ]
    if not plugins:
        return HTMLResponse(
            '<tr><td colspan="7" class="px-3 py-8 text-center text-gray-500">'
            '无插件。Agent 通过 entry_points 注册,见 docs/adr/0003-plugin-registration.md。</td></tr>'
        )
    return HTMLResponse("".join(_render_plugin_row(p) for p in plugins))


@router.get("/fragments/tools", response_class=HTMLResponse)
async def tools_fragment(user: dict = Depends(require_scope("plugin:read"))):
    """只 mcp_tool 类型插件。"""
    r = discover_all()
    tools = [
        {
            "name": m.name, "version": m.version, "description": m.description,
            "plugin_type": m.plugin_type, "endpoint": m.endpoint,
            "required_intents": m.required_intents, "tags": m.tags,
        }
        for m in r.list_all() if m.plugin_type == "mcp_tool"
    ]
    if not tools:
        return HTMLResponse(
            '<tr><td colspan="5" class="px-3 py-8 text-center text-gray-500">'
            '无 mcp_tool 类型插件。</td></tr>'
        )
    return HTMLResponse("".join(_render_plugin_row(t) for t in tools))


@router.get("/fragments/logs", response_class=HTMLResponse)
async def logs_fragment(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    user_id: str | None = Query(None),
    user: dict = Depends(require_scope("log:read")),
):
    """audit log 分页 — 返 tbody rows + 分页控件(都放一个 HTMLResponse 里)。"""
    rows, total = _list_logs(page, size, user_id)
    for r in rows:
        if r.get("ts") and hasattr(r["ts"], "isoformat"):
            r["ts"] = r["ts"].isoformat()
    if not rows:
        body = '<tr><td colspan="6" class="px-3 py-8 text-center text-gray-500">无日志</td></tr>'
    else:
        body_parts = []
        for r in rows:
            ts = _esc(r.get("ts") or "—")
            uid = _esc(r.get("user_id") or "—")
            action = _esc(r.get("action") or "—")
            result = _esc(r.get("result") or "other")
            target = _esc(r.get("target") or "—")
            ip = _esc(r.get("ip") or "—")
            reason = _esc(r.get("reason") or "")
            color = "#4caf50" if result == "allow" else "#f44336"
            body_parts.append(
                f'<tr class="border-b border-[#0f3460] hover:bg-[#0f3460]/20">'
                f'<td class="px-3 py-2 text-xs font-mono text-gray-400">{ts}</td>'
                f'<td class="px-3 py-2 text-sm">{uid}</td>'
                f'<td class="px-3 py-2 text-sm">{action}</td>'
                f'<td class="px-3 py-2"><span class="px-2 py-0.5 rounded text-xs" style="background:{color}33;color:{color};border:1px solid {color}66">{result}</span></td>'
                f'<td class="px-3 py-2 text-sm">{target}</td>'
                f'<td class="px-3 py-2 text-xs text-gray-400 max-w-md truncate" title="{reason}">{reason or "—"}</td>'
                f'</tr>'
            )
        body = "".join(body_parts)
    total_pages = max(1, (total + size - 1) // size)
    pages_html = "".join(
        f'<button hx-get="/admin/api/fragments/logs?page={p}&size={size}'
        f'{"&user_id=" + _esc(user_id) if user_id else ""}" '
        f'hx-target="#logs-result" hx-swap="innerHTML" '
        f'class="px-3 py-1 rounded text-xs border '
        f'{("border-[#e94560] text-[#e94560]" if p == page else "border-[#0f3460] text-gray-400 hover:text-[#e0e0e0]")} '
        f'ml-1">{p}</button>'
        for p in range(1, min(total_pages, 20) + 1)
    )
    pagination = (
        f'<div class="flex items-center mt-4 text-xs text-gray-500">'
        f'<span>共 {total} 条 · 第 {page} / {total_pages} 页</span>'
        f'<span class="flex-1"></span>'
        f'{pages_html}'
        f'</div>'
    )
    return HTMLResponse(body + pagination)


@router.get("/fragments/metrics", response_class=HTMLResponse)
async def metrics_fragment(user: dict = Depends(require_scope("log:read"))):
    """Prometheus exposition 文本 → HTML <pre> 包起来(textContent 防注入)。

    完整 Prometheus 数据量大,这里不解析(原始文本更准,UI 后期想美化再加 parser)。
    """
    from prometheus_client import generate_latest
    exposition = generate_latest().decode("utf-8")
    # 防 HTML 注入:用 <pre> + 后端转义(HTMX 拿到的是 innerHTML,得 escape)
    return HTMLResponse(
        f'<pre class="bg-[#0d0d1a] text-gray-300 p-4 rounded text-xs overflow-auto max-h-96">'
        f'{_esc(exposition)}</pre>'
    )


@router.get("/fragments/role-dist", response_class=HTMLResponse)
async def role_dist_fragment(user: dict = Depends(require_role("admin", "super_admin"))):
    """角色分布 — metrics 页用。"""
    users = _list_users_for_tenant(user["tenant_id"])
    dist: dict[str, int] = {}
    for u in users:
        r = u["role"]
        dist[r] = dist.get(r, 0) + 1
    if not dist:
        return HTMLResponse('<p class="text-gray-500 text-sm">无用户</p>')
    rows = "".join(
        f'<tr class="border-b border-[#0f3460]"><td class="px-3 py-2 text-sm">{_esc(r)}</td>'
        f'<td class="px-3 py-2 text-sm font-mono">{c}</td></tr>'
        for r, c in sorted(dist.items())
    )
    return HTMLResponse(
        f'<table class="w-full text-sm">{rows}</table>'
    )


@router.get("/fragments/audit-dist", response_class=HTMLResponse)
async def audit_dist_fragment(user: dict = Depends(require_scope("log:read"))):
    """近 100 条 audit allow/deny/other 分布 — metrics 页用。"""
    rows, _ = _list_logs(page=1, size=100, user_id=None)
    dist = {"allow": 0, "deny": 0, "other": 0}
    for r in rows:
        k = r.get("result")
        if k == "allow":
            dist["allow"] += 1
        elif k == "deny":
            dist["deny"] += 1
        else:
            dist["other"] += 1
    color = {"allow": "#4caf50", "deny": "#f44336", "other": "#888"}
    rows_html = "".join(
        f'<tr class="border-b border-[#0f3460]"><td class="px-3 py-2 text-sm">{k}</td>'
        f'<td class="px-3 py-2"><span class="px-2 py-0.5 rounded text-xs" '
        f'style="background:{color[k]}33;color:{color[k]};border:1px solid {color[k]}66">{c}</span></td></tr>'
        for k, c in dist.items()
    )
    return HTMLResponse(f'<table class="w-full text-sm">{rows_html}</table>')


__all__ = ["router"]
