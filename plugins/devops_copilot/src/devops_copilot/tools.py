"""devops_copilot plugin 工具 — 工单 / On-call / K8s 操作。

Phase 5 mock,Phase 6 接真实 Jira / kubernetes SDK。
"""
from __future__ import annotations

import json
import os
from typing import Optional

# Phase 5:mock — Phase 6 接真实 Jira / kubernetes SDK
_INCIDENTS = {
    "INC-001": {"id": "INC-001", "title": "API 网关 5xx 错误率激增", "priority": "P0",
                "status": "open", "assignee": "张工", "team": "platform",
                "created": "2026-08-06 14:30", "updated": "2026-08-07 09:15",
                "description": "线上 API 网关 5xx 比例从 0.1% 飙至 8%,影响订单/支付核心链路"},
    "INC-002": {"id": "INC-002", "title": "订单数据库慢查询", "priority": "P1",
                "status": "in_progress", "assignee": "李工", "team": "data",
                "created": "2026-08-07 08:00", "updated": "2026-08-07 10:20",
                "description": "订单表 full table scan,QPS 2000 时 P99 延迟 4.5s"},
    "INC-003": {"id": "INC-003", "title": "前端 CDN 缓存击穿", "priority": "P2",
                "status": "resolved", "assignee": "王工", "team": "platform",
                "created": "2026-08-05 11:00", "updated": "2026-08-06 16:00",
                "description": "热门商品详情页 CDN key 同时失效,回源打爆"},
    "INC-004": {"id": "INC-004", "title": "Kafka 消费延迟告警", "priority": "P1",
                "status": "open", "assignee": "赵工", "team": "data",
                "created": "2026-08-07 13:45", "updated": "2026-08-07 13:45",
                "description": "订单事件 topic lag 突破 10 万,消费者扩容未生效"},
    "INC-005": {"id": "INC-005", "title": "SSO 登录服务不可用", "priority": "P0",
                "status": "in_progress", "assignee": "陈工", "team": "security",
                "created": "2026-08-07 16:20", "updated": "2026-08-07 17:30",
                "description": "OIDC token 签发失败,全员无法登录内部系统"},
    "INC-006": {"id": "INC-006", "title": "ES 集群 master 切换", "priority": "P1",
                "status": "resolved", "assignee": "李工", "team": "data",
                "created": "2026-08-04 22:10", "updated": "2026-08-05 02:15",
                "description": "ES master 节点 OOM,自动 failover 后恢复,需优化 heap"},
    "INC-007": {"id": "INC-007", "title": "S3 存储桶访问权限问题", "priority": "P2",
                "status": "open", "assignee": "孙工", "team": "security",
                "created": "2026-08-07 09:00", "updated": "2026-08-07 09:00",
                "description": "新上线的日志 bucket policy 错误,部分服务无法写入"},
    "INC-008": {"id": "INC-008", "title": "Prometheus 自身高负载", "priority": "P3",
                "status": "open", "assignee": "张工", "team": "platform",
                "created": "2026-08-07 18:00", "updated": "2026-08-07 18:00",
                "description": "Prometheus TSDB 写放大导致 CPU 90%,告警延迟"},
}
_ONCALL = {
    "platform": {"team": "Platform Engineering", "primary": "张工", "phone": "+86-138-0000-0001",
                  "secondary": "陈工", "rotation_start": "2026-08-01", "rotation_end": "2026-08-14"},
    "data": {"team": "Data Platform", "primary": "李工", "phone": "+86-138-0000-0002",
              "secondary": "赵工", "rotation_start": "2026-08-01", "rotation_end": "2026-08-14"},
    "security": {"team": "Security & Compliance", "primary": "陈工", "phone": "+86-138-0000-0003",
                  "secondary": "孙工", "rotation_start": "2026-08-01", "rotation_end": "2026-08-14"},
    "network": {"team": "Network Operations", "primary": "周工", "phone": "+86-138-0000-0004",
                 "secondary": "吴工", "rotation_start": "2026-08-01", "rotation_end": "2026-08-14"},
}

# Phase 5:dry_run 默认 True,生产设 K8S_DRY_RUN=false 启用真操作
DRY_RUN = os.getenv("K8S_DRY_RUN", "true").lower() == "true"


# ────────── incident_mcp(:8020)──────────

def query_incident(incident_id: Optional[str] = None,
                   status: Optional[str] = None,
                   priority: Optional[str] = None,
                   limit: int = 5) -> str:
    """查工单。可按 id / status / priority 过滤,limit 限制返回数量(默认 5,按更新时间倒序)。"""
    items = list(_INCIDENTS.values())
    if incident_id:
        items = [i for i in items if i["id"].lower() == incident_id.lower()]
    if status:
        items = [i for i in items if i["status"] == status]
    if priority:
        items = [i for i in items if i["priority"].lower() == priority.lower()]
    items = sorted(items, key=lambda x: x["updated"], reverse=True)[:limit]
    return json.dumps({
        "status": "success" if items else "no_data",
        "data": items,
        "message": "未找到工单。" if not items else "",
    }, ensure_ascii=False)


def list_recent_incidents(limit: int = 5) -> str:
    """列最近更新的 N 条工单(默认 5,按更新时间倒序)。"""
    items = sorted(_INCIDENTS.values(), key=lambda x: x["updated"], reverse=True)[:limit]
    return json.dumps({
        "status": "success" if items else "no_data",
        "data": items,
        "message": "暂无工单记录。" if not items else "",
    }, ensure_ascii=False)


def query_oncall(team: str = "platform") -> str:
    """查 on-call 联系信息。team ∈ {platform, data, security, network}。"""
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