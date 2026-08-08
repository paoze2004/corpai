"""devops_copilot plugin 工具 — incident mock + k8s dry_run。"""
from __future__ import annotations

import json
import os
from typing import Optional

# Phase 5:mock — Phase 6 接真实 Jira / kubernetes SDK
_INCIDENTS = {
    "INC-001": {"id": "INC-001", "title": "API 网关 5xx 错误率激增", "priority": "P0",
                "status": "open", "assignee": "张工", "created": "2026-08-06 14:30",
                "updated": "2026-08-07 09:15"},
    "INC-002": {"id": "INC-002", "title": "订单数据库慢查询", "priority": "P1",
                "status": "in_progress", "assignee": "李工", "created": "2026-08-07 08:00",
                "updated": "2026-08-07 10:20"},
    "INC-003": {"id": "INC-003", "title": "前端 CDN 缓存击穿", "priority": "P2",
                "status": "resolved", "assignee": "王工", "created": "2026-08-05 11:00",
                "updated": "2026-08-06 16:00"},
}
_ONCALL = {
    "platform": {"team": "Platform Engineering", "primary": "张工", "phone": "+86-xxx-xxxx",
                  "secondary": "李工", "rotation_start": "2026-08-01"},
    "data": {"team": "Data Platform", "primary": "王工", "phone": "+86-xxx-yyyy",
              "secondary": "赵工", "rotation_start": "2026-08-01"},
}

# Phase 5:dry_run 默认 True,生产设 K8S_DRY_RUN=false 启用真操作
DRY_RUN = os.getenv("K8S_DRY_RUN", "true").lower() == "true"


# ────────── incident_mcp(:8020)──────────

def query_incident(incident_id: Optional[str] = None, status: Optional[str] = None) -> str:
    """查工单。Phase 5 stub。"""
    items = list(_INCIDENTS.values())
    if incident_id:
        items = [i for i in items if i["id"].lower() == incident_id.lower()]
    if status:
        items = [i for i in items if i["status"] == status]
    return json.dumps({
        "status": "success" if items else "no_data",
        "data": items,
        "message": "未找到工单。" if not items else "",
    }, ensure_ascii=False)


def query_oncall(team: str = "platform") -> str:
    """查 on-call 联系信息。"""
    info = _ONCALL.get(team)
    if info is None:
        return json.dumps({"status": "no_data", "message": f"无 team={team} 的 on-call 信息"}, ensure_ascii=False)
    return json.dumps({"status": "success", "data": info}, ensure_ascii=False)


# ────────── k8s_mcp(:8021)──────────

def restart_pod(pod_name: str, namespace: str, authorization: Optional[str] = None) -> str:
    """K8s Pod 重启(dry_run 默认)。Phase 5:RBAC devops:write 校验。"""
    # Phase 5:RBAC 二次校验
    _check_devops_write(authorization)
    if DRY_RUN:
        return json.dumps({
            "status": "dry_run", "pod": pod_name, "namespace": namespace,
            "warning": "未真实重启,设 K8S_DRY_RUN=false 启用",
        }, ensure_ascii=False)
    return json.dumps({"status": "ok", "pod": pod_name, "namespace": namespace,
                       "action": "restarted"}, ensure_ascii=False)


def _check_devops_write(authorization: Optional[str] = None) -> None:
    """检查 Bearer JWT 是否含 devops:write scope。Phase 5:RBAC 链路打通。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise PermissionError("restart_pod 需要 Bearer token")
    try:
        from CorpAI.platform.auth.tokens import jwt_decode
        from CorpAI.platform.auth.dependencies import get_jwt_secret
        from CorpAI.platform.auth.scopes import has_scope
        claims = jwt_decode(authorization[len("Bearer "):], get_jwt_secret())
    except Exception as e:
        raise PermissionError(f"token 解析失败: {e}")
    if not claims:
        raise PermissionError("token 无效或已过期")
    scopes = claims.get("scopes", [])
    if not has_scope("devops:write", scopes):
        raise PermissionError(f"restart_pod 需要 devops:write scope,实有 {scopes}")
