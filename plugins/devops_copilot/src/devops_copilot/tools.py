"""devops_copilot plugin 工具 v3.0 — 35+ 工具覆盖 incident/oncall/k8s/monitoring/cicd/log。

设计:
- Phase 5 mock 数据 + 真 RBAC
- Phase 6 留 SDK 接入位(Jira/kubernetes-python/prometheus-client/elasticsearch/...)
- DRY_RUN 默认 true,生产设 K8S_DRY_RUN=false
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ────────── RBAC 校验(Phase 5 已实现,保留)──────────

def _check_devops_read(authorization: Optional[str] = None) -> dict:
    """校验 token 含 devops:read 或 *。返回 claims。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise PermissionError("需要 Bearer token (scope=devops:read)")
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
    if not has_scope("devops:read", scopes):
        raise PermissionError(f"需要 devops:read,实有 {scopes}")
    return claims


def _check_devops_write(authorization: Optional[str] = None) -> dict:
    """校验 token 含 devops:write 或 *。返回 claims。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise PermissionError("需要 Bearer token (scope=devops:write)")
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
        raise PermissionError(f"需要 devops:write,实有 {scopes}")
    return claims


# ────────── Mock 数据(Phase 5)— Phase 6 替换成 Jira/SDK ──────────

_INCIDENTS: dict[str, dict] = {
    # 平台团队
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
    "INC-009": {"id": "INC-009", "title": "Redis 大 key 频繁触发淘汰", "priority": "P2",
                "status": "open", "assignee": "张工", "team": "platform",
                "created": "2026-08-07 11:20", "updated": "2026-08-07 11:20",
                "description": "session cache 单 key 占用 800MB,触发 maxmemory-policy"},
    "INC-010": {"id": "INC-010", "title": "移动端推送服务掉线", "priority": "P1",
                "status": "in_progress", "assignee": "陈工", "team": "security",
                "created": "2026-08-07 07:00", "updated": "2026-08-07 14:00",
                "description": "APNs/FCM 推送证书过期,客户端收不到通知"},
    "INC-011": {"id": "INC-011", "title": "支付回调丢失", "priority": "P0",
                "status": "in_progress", "assignee": "李工", "team": "data",
                "created": "2026-08-07 19:00", "updated": "2026-08-07 19:30",
                "description": "微信支付回调 5xx 重试队列堆积,部分订单状态不一致"},
    "INC-012": {"id": "INC-012", "title": "图片处理服务内存泄漏", "priority": "P2",
                "status": "open", "assignee": "赵工", "team": "data",
                "created": "2026-08-06 22:00", "updated": "2026-08-06 22:00",
                "description": "imagemagick 进程 RSS 单调上涨,24h 内 OOM 一次"},
    "INC-013": {"id": "INC-013", "title": "数据库主从延迟告警", "priority": "P1",
                "status": "open", "assignee": "李工", "team": "data",
                "created": "2026-08-07 20:00", "updated": "2026-08-07 20:00",
                "description": "主从延迟突破 30s,影响 BI 报表实时性"},
    "INC-014": {"id": "INC-014", "title": "日志采集 agent 失联", "priority": "P3",
                "status": "open", "assignee": "孙工", "team": "security",
                "created": "2026-08-07 05:30", "updated": "2026-08-07 05:30",
                "description": "30% 节点 Filebeat 心跳丢失,排查中"},
    "INC-015": {"id": "INC-015", "title": "订单导出 CSV 任务超时", "priority": "P2",
                "status": "resolved", "assignee": "王工", "team": "platform",
                "created": "2026-08-06 09:00", "updated": "2026-08-06 18:00",
                "description": "百万级订单导出 OOM,已切流式 + 分片"},
    # 安全 / 网络 / 移动端
    "INC-016": {"id": "INC-016", "title": "WAF 误拦截合规请求", "priority": "P2",
                "status": "open", "assignee": "陈工", "team": "security",
                "created": "2026-08-07 12:00", "updated": "2026-08-07 12:00",
                "description": "新规则导致部分 API 调用被拦,影响 B 端合作方"},
    "INC-017": {"id": "INC-017", "title": "DNS 解析异常", "priority": "P1",
                "status": "open", "assignee": "周工", "team": "network",
                "created": "2026-08-07 15:00", "updated": "2026-08-07 15:00",
                "description": "内部 DNS 集群某节点故障,部分域名解析超时"},
    "INC-018": {"id": "INC-018", "title": "iOS 客户端闪退率上升", "priority": "P1",
                "status": "in_progress", "assignee": "陈工", "team": "security",
                "created": "2026-08-07 16:00", "updated": "2026-08-07 18:00",
                "description": "iOS 18 兼容性问题,启动闪退率 5%"},
    "INC-019": {"id": "INC-019", "title": "负载均衡器健康检查抖动", "priority": "P2",
                "status": "open", "assignee": "周工", "team": "network",
                "created": "2026-08-07 10:00", "updated": "2026-08-07 10:00",
                "description": "ALB 健康检查间歇性失败,误摘除健康节点"},
    "INC-020": {"id": "INC-020", "title": "灰度发布策略失效", "priority": "P2",
                "status": "open", "assignee": "王工", "team": "platform",
                "created": "2026-08-07 13:00", "updated": "2026-08-07 13:00",
                "description": "新版本灰度比例配置未生效,全量发布"},
    "INC-021": {"id": "INC-021", "title": "内部 Wiki 502", "priority": "P3",
                "status": "resolved", "assignee": "张工", "team": "platform",
                "created": "2026-08-06 14:00", "updated": "2026-08-06 15:00",
                "description": "Confluence 后端 DB 连接池耗尽,已调大"},
    "INC-022": {"id": "INC-022", "title": "移动端 H5 页面加载慢", "priority": "P2",
                "status": "open", "assignee": "王工", "team": "platform",
                "created": "2026-08-07 09:30", "updated": "2026-08-07 09:30",
                "description": "H5 首屏 P95 4.2s,首屏 JS 体积过大"},
    "INC-023": {"id": "INC-023", "title": "数据同步延迟", "priority": "P2",
                "status": "open", "assignee": "赵工", "team": "data",
                "created": "2026-08-07 17:00", "updated": "2026-08-07 17:00",
                "description": "binlog→ES 同步滞后 15 分钟,排查中"},
    "INC-024": {"id": "INC-024", "title": "用户反馈搜索结果不准", "priority": "P3",
                "status": "open", "assignee": "王工", "team": "platform",
                "created": "2026-08-07 16:00", "updated": "2026-08-07 16:00",
                "description": "ES 同义词词典不全,商品召回率下降"},
    "INC-025": {"id": "INC-025", "title": "备份任务失败", "priority": "P1",
                "status": "open", "assignee": "孙工", "team": "security",
                "created": "2026-08-07 22:00", "updated": "2026-08-07 22:00",
                "description": "凌晨 DB 备份脚本异常退出,排查中"},
}


_ONCALL: dict[str, dict] = {
    "platform": {"team": "Platform Engineering", "primary": "张工", "phone": "+86-138-0000-0001",
                  "secondary": "陈工", "rotation_start": "2026-08-01", "rotation_end": "2026-08-14"},
    "data": {"team": "Data Platform", "primary": "李工", "phone": "+86-138-0000-0002",
              "secondary": "赵工", "rotation_start": "2026-08-01", "rotation_end": "2026-08-14"},
    "security": {"team": "Security & Compliance", "primary": "陈工", "phone": "+86-138-0000-0003",
                  "secondary": "孙工", "rotation_start": "2026-08-01", "rotation_end": "2026-08-14"},
    "network": {"team": "Network Operations", "primary": "周工", "phone": "+86-138-0000-0004",
                 "secondary": "吴工", "rotation_start": "2026-08-01", "rotation_end": "2026-08-14"},
    "mobile": {"team": "Mobile Engineering", "primary": "陈工", "phone": "+86-138-0000-0005",
                "secondary": "吴工", "rotation_start": "2026-08-01", "rotation_end": "2026-08-14"},
    "frontend": {"team": "Frontend Engineering", "primary": "王工", "phone": "+86-138-0000-0006",
                  "secondary": "郑工", "rotation_start": "2026-08-01", "rotation_end": "2026-08-14"},
    "devops": {"team": "DevOps / SRE", "primary": "张工", "phone": "+86-138-0000-0007",
                "secondary": "周工", "rotation_start": "2026-08-01", "rotation_end": "2026-08-14"},
    "qa": {"team": "Quality Assurance", "primary": "郑工", "phone": "+86-138-0000-0008",
            "secondary": "吴工", "rotation_start": "2026-08-01", "rotation_end": "2026-08-14"},
}


# ────────── 监控告警(6 个工具)— Phase 6 接 Prometheus ──────────

_ALERTS = {
    "ALR-001": {"id": "ALR-001", "name": "API 5xx > 1%", "severity": "critical",
                "service": "api-gateway", "active_since": "2026-08-07 09:00",
                "state": "firing", "value": "8.2%"},
    "ALR-002": {"id": "ALR-002", "name": "DB 连接池 > 80%", "severity": "warning",
                "service": "order-db", "active_since": "2026-08-07 10:00",
                "state": "firing", "value": "85%"},
    "ALR-003": {"id": "ALR-003", "name": "Kafka lag > 100k", "severity": "critical",
                "service": "kafka-order-events", "active_since": "2026-08-07 13:45",
                "state": "firing", "value": "123456"},
    "ALR-004": {"id": "ALR-004", "name": "Disk usage > 90%", "severity": "warning",
                "service": "node-prod-07", "active_since": "2026-08-06 22:00",
                "state": "firing", "value": "92%"},
    "ALR-005": {"id": "ALR-005", "name": "Cert expires < 7d", "severity": "warning",
                "service": "api.internal.com", "active_since": "2026-08-05 08:00",
                "state": "firing", "value": "5 days"},
    "ALR-006": {"id": "ALR-006", "name": "Pod OOMKilled > 3/h", "severity": "critical",
                "service": "image-svc", "active_since": "2026-08-07 18:00",
                "state": "firing", "value": "5 / hour"},
}


# ────────── CI/CD(4 个工具)— Phase 6 接 Jenkins/GitHub Actions ──────────

_PIPELINES = {
    "PIPE-001": {"id": "PIPE-001", "name": "order-service main", "status": "success",
                  "branch": "main", "last_run": "2026-08-07 18:00",
                  "duration_seconds": 245, "trigger": "git push"},
    "PIPE-002": {"id": "PIPE-002", "name": "payment-service release/v3", "status": "failed",
                  "branch": "release/v3", "last_run": "2026-08-07 17:30",
                  "duration_seconds": 89, "trigger": "manual",
                  "error": "单元测试 12 个失败"},
    "PIPE-003": {"id": "PIPE-003", "name": "frontend nightly", "status": "success",
                  "branch": "main", "last_run": "2026-08-07 03:00",
                  "duration_seconds": 612, "trigger": "schedule"},
    "PIPE-004": {"id": "PIPE-004", "name": "image-svc release/v2.5", "status": "running",
                  "branch": "release/v2.5", "last_run": "2026-08-07 19:00",
                  "duration_seconds": 120, "trigger": "git tag"},
}


# ────────── 日志(4 个工具)— Phase 6 接 ES/Loki ──────────

_LOG_SOURCES = {
    "api-gateway": {"type": "structured-json", "retention_days": 30,
                     "host": "es-prod-01.internal:9200", "index": "logs-api-gateway-*"},
    "order-db": {"type": "slow-query-log", "retention_days": 14,
                  "host": "es-prod-01.internal:9200", "index": "logs-order-db-*"},
    "k8s-events": {"type": "kube-events", "retention_days": 7,
                    "host": "es-prod-01.internal:9200", "index": "logs-k8s-events-*"},
    "audit": {"type": "audit-trail", "retention_days": 365,
               "host": "es-prod-02.internal:9200", "index": "logs-audit-*"},
}


# ────────── K8s(dry_run 默认)— Phase 6 接 kubernetes-python ──────────

DRY_RUN = os.getenv("K8S_DRY_RUN", "true").lower() == "true"


# ════════════════════════════════════════════════════════════════
#  Incident 工具(10 个)— :8020
# ════════════════════════════════════════════════════════════════

def query_incident(incident_id: Optional[str] = None,
                   status: Optional[str] = None,
                   priority: Optional[str] = None,
                   team: Optional[str] = None,
                   limit: int = 5) -> str:
    """查工单,多维过滤: id / status / priority / team。"""
    items = list(_INCIDENTS.values())
    if incident_id:
        items = [i for i in items if i["id"].lower() == incident_id.lower()]
    if status:
        items = [i for i in items if i["status"] == status]
    if priority:
        items = [i for i in items if i["priority"].lower() == priority.lower()]
    if team:
        items = [i for i in items if i["team"] == team]
    items = sorted(items, key=lambda x: x["updated"], reverse=True)[:limit]
    return json.dumps({
        "status": "success" if items else "no_data",
        "data": items,
        "message": "未找到工单。" if not items else "",
    }, ensure_ascii=False)


def list_recent_incidents(limit: int = 5) -> str:
    """列最近更新的 N 条工单。"""
    items = sorted(_INCIDENTS.values(), key=lambda x: x["updated"], reverse=True)[:limit]
    return json.dumps({
        "status": "success" if items else "no_data",
        "data": items,
        "message": "暂无工单记录。" if not items else "",
    }, ensure_ascii=False)


def list_open_p0_incidents() -> str:
    """列 P0 级未关闭工单(应急优先)。"""
    items = [i for i in _INCIDENTS.values() if i["priority"] == "P0" and i["status"] != "resolved"]
    return json.dumps({"status": "success" if items else "no_data",
                       "data": items}, ensure_ascii=False)


def get_incident_stats() -> str:
    """工单统计:总数 + 按 status / priority / team 分布。"""
    items = list(_INCIDENTS.values())
    stats = {
        "total": len(items),
        "by_status": {},
        "by_priority": {},
        "by_team": {},
        "open_count": sum(1 for i in items if i["status"] != "resolved"),
    }
    for i in items:
        stats["by_status"][i["status"]] = stats["by_status"].get(i["status"], 0) + 1
        stats["by_priority"][i["priority"]] = stats["by_priority"].get(i["priority"], 0) + 1
        stats["by_team"][i["team"]] = stats["by_team"].get(i["team"], 0) + 1
    return json.dumps({"status": "success", "data": stats}, ensure_ascii=False)


def search_incidents_by_keyword(keyword: str, limit: int = 10) -> str:
    """关键词搜工单(title + description 命中)。"""
    kw = keyword.lower()
    items = [i for i in _INCIDENTS.values()
             if kw in i["title"].lower() or kw in i["description"].lower()]
    items = sorted(items, key=lambda x: x["updated"], reverse=True)[:limit]
    return json.dumps({"status": "success" if items else "no_data",
                       "data": items, "keyword": keyword}, ensure_ascii=False)


def get_team_workload() -> str:
    """各团队在处理工单数(assignee 维度)。"""
    workload: dict[str, int] = {}
    for i in _INCIDENTS.values():
        if i["status"] != "resolved":
            workload[i["assignee"]] = workload.get(i["assignee"], 0) + 1
    workload = dict(sorted(workload.items(), key=lambda x: -x[1]))
    return json.dumps({"status": "success", "data": workload}, ensure_ascii=False)


def create_incident(title: str, priority: str, team: str,
                     description: str, authorization: Optional[str] = None) -> str:
    """创建工单(写库,Phase 6 接 Jira)。需 devops:write。"""
    _check_devops_write(authorization)
    if priority not in {"P0", "P1", "P2", "P3"}:
        return json.dumps({"status": "invalid", "message": f"priority 非法:{priority}"},
                          ensure_ascii=False)
    inc_id = f"INC-{len(_INCIDENTS) + 1:03d}"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    new_inc = {"id": inc_id, "title": title, "priority": priority, "status": "open",
               "assignee": "未分配", "team": team, "created": now, "updated": now,
               "description": description}
    _INCIDENTS[inc_id] = new_inc
    return json.dumps({"status": "success", "data": new_inc,
                       "message": f"工单 {inc_id} 已创建,优先级 {priority}"}, ensure_ascii=False)


def assign_incident(incident_id: str, assignee: str,
                     authorization: Optional[str] = None) -> str:
    """分配工单给指定人。需 devops:write。"""
    _check_devops_write(authorization)
    inc = _INCIDENTS.get(incident_id)
    if not inc:
        return json.dumps({"status": "not_found", "message": f"无 {incident_id}"}, ensure_ascii=False)
    inc["assignee"] = assignee
    inc["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return json.dumps({"status": "success", "data": inc,
                       "message": f"工单 {incident_id} 已分配给 {assignee}"}, ensure_ascii=False)


def resolve_incident(incident_id: str, resolution_note: str,
                       authorization: Optional[str] = None) -> str:
    """关闭工单(填解决方案)。需 devops:write。"""
    _check_devops_write(authorization)
    inc = _INCIDENTS.get(incident_id)
    if not inc:
        return json.dumps({"status": "not_found", "message": f"无 {incident_id}"}, ensure_ascii=False)
    inc["status"] = "resolved"
    inc["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    inc["resolution_note"] = resolution_note
    return json.dumps({"status": "success", "data": inc,
                       "message": f"工单 {incident_id} 已解决"}, ensure_ascii=False)


def escalate_incident(incident_id: str, new_priority: str, reason: str,
                       authorization: Optional[str] = None) -> str:
    """工单升级/降级(改优先级)。需 devops:write。"""
    _check_devops_write(authorization)
    if new_priority not in {"P0", "P1", "P2", "P3"}:
        return json.dumps({"status": "invalid", "message": f"priority 非法:{new_priority}"},
                          ensure_ascii=False)
    inc = _INCIDENTS.get(incident_id)
    if not inc:
        return json.dumps({"status": "not_found", "message": f"无 {incident_id}"}, ensure_ascii=False)
    old = inc["priority"]
    inc["priority"] = new_priority
    inc["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    inc["escalation_history"] = inc.get("escalation_history", []) + [
        {"from": old, "to": new_priority, "reason": reason,
         "at": datetime.now().strftime("%Y-%m-%d %H:%M")}]
    return json.dumps({"status": "success", "data": inc,
                       "message": f"工单 {incident_id} 优先级从 {old} 改为 {new_priority}"},
                      ensure_ascii=False)


# ════════════════════════════════════════════════════════════════
#  On-call 工具(8 个)— :8020
# ════════════════════════════════════════════════════════════════

def query_oncall(team: str = "platform") -> str:
    """查 on-call 联系信息。team ∈ {platform, data, security, network, mobile, frontend, devops, qa}。"""
    info = _ONCALL.get(team)
    if info is None:
        return json.dumps({"status": "no_data", "message": f"无 team={team} 的 on-call 信息"},
                          ensure_ascii=False)
    return json.dumps({"status": "success", "data": info}, ensure_ascii=False)


def list_oncall_teams() -> str:
    """列出所有 on-call 团队。"""
    return json.dumps({"status": "success", "data": list(_ONCALL.keys())}, ensure_ascii=False)


def get_primary_oncall(team: str) -> str:
    """获取主 oncall(只看 primary)。"""
    info = _ONCALL.get(team)
    if not info:
        return json.dumps({"status": "no_data", "message": f"无 team={team}"}, ensure_ascii=False)
    return json.dumps({"status": "success", "data": {"team": info["team"],
                                                      "primary": info["primary"],
                                                      "phone": info["phone"]}}, ensure_ascii=False)


def rotate_oncall(team: str, new_primary: str, new_secondary: str,
                   start: str, end: str, authorization: Optional[str] = None) -> str:
    """切换 oncall 排班。需 devops:write。"""
    _check_devops_write(authorization)
    info = _ONCALL.get(team)
    if not info:
        return json.dumps({"status": "not_found", "message": f"无 team={team}"}, ensure_ascii=False)
    info["primary"] = new_primary
    info["secondary"] = new_secondary
    info["rotation_start"] = start
    info["rotation_end"] = end
    return json.dumps({"status": "success", "data": info,
                       "message": f"{team} oncall 已切换 {start}~{end}"}, ensure_ascii=False)


def list_all_oncall_contacts() -> str:
    """列出所有团队 oncall 联系方式(扁平表)。"""
    contacts = [{"team": k, **v} for k, v in _ONCALL.items()]
    return json.dumps({"status": "success", "data": contacts}, ensure_ascii=False)


def find_oncall_by_name(name: str) -> str:
    """按名字反查 oncall 归属。"""
    hits = [{"team": t, **info} for t, info in _ONCALL.items()
            if name in info.get("primary", "") or name in info.get("secondary", "")]
    return json.dumps({"status": "success" if hits else "no_data", "data": hits}, ensure_ascii=False)


def get_rotation_schedule(team: str) -> str:
    """查团队排班周期(rotation window)。"""
    info = _ONCALL.get(team)
    if not info:
        return json.dumps({"status": "no_data", "message": f"无 team={team}"}, ensure_ascii=False)
    return json.dumps({"status": "success", "data": {
        "team": info["team"],
        "window": {"start": info["rotation_start"], "end": info["rotation_end"]},
        "primary": info["primary"], "secondary": info["secondary"],
    }}, ensure_ascii=False)


def page_oncall(team: str, message: str, authorization: Optional[str] = None) -> str:
    """发 oncall 呼叫(真发需 Twilio/PagerDuty,Phase 6 接 PagerDuty)。需 devops:write。

    返回 page_id,代表已记录呼叫意图。Phase 5 mock。
    """
    _check_devops_write(authorization)
    info = _ONCALL.get(team)
    if not info:
        return json.dumps({"status": "not_found", "message": f"无 team={team}"}, ensure_ascii=False)
    page_id = f"PAGE-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    return json.dumps({"status": "success", "data": {
        "page_id": page_id,
        "team": team, "primary": info["primary"], "phone": info["phone"],
        "message": message, "sent_at": datetime.now().isoformat(),
    }, "message": f"已呼叫 {team} {info['primary']} {info['phone']}"}, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════
#  K8s 操作工具(5 个)— :8021 dry_run 默认
# ════════════════════════════════════════════════════════════════

def restart_pod(pod_name: str, namespace: str, authorization: Optional[str] = None) -> str:
    """K8s Pod 重启。需 devops:write。"""
    _check_devops_write(authorization)
    if DRY_RUN:
        return json.dumps({
            "status": "dry_run", "pod": pod_name, "namespace": namespace,
            "warning": "未真实重启,设 K8S_DRY_RUN=false 启用",
        }, ensure_ascii=False)
    return json.dumps({"status": "ok", "pod": pod_name, "namespace": namespace,
                       "action": "restarted", "executed_at": datetime.now().isoformat()},
                      ensure_ascii=False)


def rollback_deployment(deployment: str, namespace: str, revision: Optional[str] = None,
                         authorization: Optional[str] = None) -> str:
    """K8s Deployment 回滚(到指定 revision,默认 previous)。需 devops:write。"""
    _check_devops_write(authorization)
    target_rev = revision or "previous"
    if DRY_RUN:
        return json.dumps({
            "status": "dry_run", "deployment": deployment, "namespace": namespace,
            "target_revision": target_rev,
            "warning": "未真实回滚,设 K8S_DRY_RUN=false 启用",
        }, ensure_ascii=False)
    return json.dumps({"status": "ok", "deployment": deployment, "namespace": namespace,
                       "action": "rolled_back", "revision": target_rev,
                       "executed_at": datetime.now().isoformat()}, ensure_ascii=False)


def scale_deployment(deployment: str, namespace: str, replicas: int,
                      authorization: Optional[str] = None) -> str:
    """K8s Deployment 扩缩容(目标副本数)。需 devops:write。"""
    _check_devops_write(authorization)
    if replicas < 0 or replicas > 100:
        return json.dumps({"status": "invalid", "message": f"replicas 越界:{replicas}"},
                          ensure_ascii=False)
    if DRY_RUN:
        return json.dumps({
            "status": "dry_run", "deployment": deployment, "namespace": namespace,
            "target_replicas": replicas,
            "warning": "未真实扩容,设 K8S_DRY_RUN=false 启用",
        }, ensure_ascii=False)
    return json.dumps({"status": "ok", "deployment": deployment, "namespace": namespace,
                       "action": "scaled", "replicas": replicas,
                       "executed_at": datetime.now().isoformat()}, ensure_ascii=False)


def get_pod_logs(pod_name: str, namespace: str, tail_lines: int = 100,
                  authorization: Optional[str] = None) -> str:
    """查 Pod 日志(返 tail N 行)。需 devops:read。"""
    _check_devops_read(authorization)
    if tail_lines < 1 or tail_lines > 10000:
        return json.dumps({"status": "invalid", "message": "tail_lines 越界"}, ensure_ascii=False)
    # Phase 5:mock 日志
    mock_logs = [
        f"{datetime.now().isoformat()} INFO  {pod_name} ready",
        f"{datetime.now().isoformat()} INFO  {pod_name} request_id=abc status=200 latency=42ms",
        f"{datetime.now().isoformat()} WARN  {pod_name} connection pool 80% utilized",
    ]
    return json.dumps({"status": "success", "data": {
        "pod": pod_name, "namespace": namespace,
        "tail_lines": tail_lines,
        "logs": mock_logs[-tail_lines:],
    }}, ensure_ascii=False)


def cordon_node(node_name: str, unschedulable: bool = True,
                 authorization: Optional[str] = None) -> str:
    """K8s Node 标记 unschedulable(驱逐/禁止调度)。需 devops:write。"""
    _check_devops_write(authorization)
    if DRY_RUN:
        return json.dumps({
            "status": "dry_run", "node": node_name,
            "unschedulable": unschedulable,
            "warning": "未真实操作,设 K8S_DRY_RUN=false 启用",
        }, ensure_ascii=False)
    return json.dumps({"status": "ok", "node": node_name,
                       "unschedulable": unschedulable,
                       "executed_at": datetime.now().isoformat()}, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════
#  监控告警(6 个)— :8022
# ════════════════════════════════════════════════════════════════

def query_alert(alert_id: Optional[str] = None, severity: Optional[str] = None,
                service: Optional[str] = None, state: Optional[str] = None) -> str:
    """查告警,按 id / severity / service / state 过滤。"""
    items = list(_ALERTS.values())
    if alert_id:
        items = [a for a in items if a["id"].lower() == alert_id.lower()]
    if severity:
        items = [a for a in items if a["severity"] == severity]
    if service:
        items = [a for a in items if a["service"] == service]
    if state:
        items = [a for a in items if a["state"] == state]
    return json.dumps({"status": "success" if items else "no_data", "data": items}, ensure_ascii=False)


def list_firing_alerts() -> str:
    """列所有 firing 状态告警。"""
    items = [a for a in _ALERTS.values() if a["state"] == "firing"]
    return json.dumps({"status": "success" if items else "no_data", "data": items}, ensure_ascii=False)


def list_critical_alerts() -> str:
    """列 critical 级告警。"""
    items = [a for a in _ALERTS.values() if a["severity"] == "critical"]
    return json.dumps({"status": "success" if items else "no_data", "data": items}, ensure_ascii=False)


def get_service_health(service: str) -> str:
    """查服务健康摘要:所有告警 + 未关闭工单数。"""
    alerts = [a for a in _ALERTS.values() if a["service"] == service]
    incidents = [i for i in _INCIDENTS.values()
                 if service.lower() in i["title"].lower() and i["status"] != "resolved"]
    return json.dumps({"status": "success", "data": {
        "service": service,
        "active_alerts": len(alerts),
        "open_incidents": len(incidents),
        "alerts": alerts,
        "incidents": incidents,
    }}, ensure_ascii=False)


def silence_alert(alert_id: str, duration_minutes: int, reason: str,
                    authorization: Optional[str] = None) -> str:
    """静音告警。需 devops:write。"""
    _check_devops_write(authorization)
    a = _ALERTS.get(alert_id)
    if not a:
        return json.dumps({"status": "not_found", "message": f"无 {alert_id}"}, ensure_ascii=False)
    a["silenced_until"] = (datetime.now().isoformat(),
                            f"+{duration_minutes}m")
    a["silence_reason"] = reason
    return json.dumps({"status": "success", "data": a,
                       "message": f"告警 {alert_id} 已静音 {duration_minutes} 分钟"}, ensure_ascii=False)


def get_alert_stats() -> str:
    """告警统计:按 severity / state / service 分布。"""
    items = list(_ALERTS.values())
    stats = {
        "total": len(items),
        "by_severity": {},
        "by_state": {},
        "by_service": {},
    }
    for a in items:
        stats["by_severity"][a["severity"]] = stats["by_severity"].get(a["severity"], 0) + 1
        stats["by_state"][a["state"]] = stats["by_state"].get(a["state"], 0) + 1
        stats["by_service"][a["service"]] = stats["by_service"].get(a["service"], 0) + 1
    return json.dumps({"status": "success", "data": stats}, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════
#  CI/CD(4 个)— :8023
# ════════════════════════════════════════════════════════════════

def query_pipeline(pipeline_id: Optional[str] = None, status: Optional[str] = None,
                    branch: Optional[str] = None, limit: int = 5) -> str:
    """查流水线状态。"""
    items = list(_PIPELINES.values())
    if pipeline_id:
        items = [p for p in items if p["id"].lower() == pipeline_id.lower()]
    if status:
        items = [p for p in items if p["status"] == status]
    if branch:
        items = [p for p in items if p["branch"] == branch]
    items = sorted(items, key=lambda x: x["last_run"], reverse=True)[:limit]
    return json.dumps({"status": "success" if items else "no_data", "data": items}, ensure_ascii=False)


def list_failed_pipelines() -> str:
    """列失败流水线。"""
    items = [p for p in _PIPELINES.values() if p["status"] == "failed"]
    return json.dumps({"status": "success" if items else "no_data", "data": items}, ensure_ascii=False)


def trigger_pipeline(pipeline_name: str, branch: str = "main",
                       authorization: Optional[str] = None) -> str:
    """触发流水线(手动跑)。需 devops:write。Phase 5:mock。"""
    _check_devops_write(authorization)
    run_id = f"RUN-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    return json.dumps({"status": "success", "data": {
        "run_id": run_id, "pipeline": pipeline_name, "branch": branch,
        "triggered_at": datetime.now().isoformat(),
    }, "message": f"已触发 {pipeline_name} (branch={branch})"}, ensure_ascii=False)


def get_pipeline_stats() -> str:
    """流水线统计:成功率 + 平均时长。"""
    items = list(_PIPELINES.values())
    if not items:
        return json.dumps({"status": "no_data"}, ensure_ascii=False)
    success = sum(1 for p in items if p["status"] == "success")
    return json.dumps({"status": "success", "data": {
        "total": len(items),
        "success_rate": f"{success / len(items) * 100:.1f}%",
        "avg_duration_seconds": sum(p["duration_seconds"] for p in items) // len(items),
        "by_status": {s: sum(1 for p in items if p["status"] == s) for s in set(p["status"] for p in items)},
    }}, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════
#  日志(4 个)— :8024
# ════════════════════════════════════════════════════════════════

def query_log_source(source_name: Optional[str] = None) -> str:
    """查日志源元数据(host/index/retention)。"""
    items = list(_LOG_SOURCES.values()) if not source_name else [
        _LOG_SOURCES.get(source_name)]
    items = [i for i in items if i]
    return json.dumps({"status": "success" if items else "no_data", "data": items}, ensure_ascii=False)


def list_log_sources() -> str:
    """列所有日志源。"""
    return json.dumps({"status": "success",
                       "data": [{"name": k, **v} for k, v in _LOG_SOURCES.items()]},
                      ensure_ascii=False)


def search_logs(query: str, source: str, time_range_hours: int = 1) -> str:
    """日志检索(ES query string)。需 devops:read。Phase 5:mock 命中。"""
    # Phase 6 接 ES:
    #   es.search(index=src["index"], body={"query": {"query_string": {"query": query}}, ...})
    items = [
        {"timestamp": datetime.now().isoformat(), "level": "INFO",
         "service": source, "message": f"matched: {query} (mock hit 1)"},
        {"timestamp": datetime.now().isoformat(), "level": "WARN",
         "service": source, "message": f"matched: {query} (mock hit 2)"},
    ]
    return json.dumps({"status": "success", "data": {
        "query": query, "source": source, "time_range_hours": time_range_hours,
        "hits": items, "total_hits": len(items),
    }}, ensure_ascii=False)


def get_log_retention_policy(source: str) -> str:
    """查日志保留策略。"""
    info = _LOG_SOURCES.get(source)
    if not info:
        return json.dumps({"status": "no_data", "message": f"无 source={source}"}, ensure_ascii=False)
    return json.dumps({"status": "success", "data": {
        "source": source, "type": info["type"],
        "retention_days": info["retention_days"], "host": info["host"],
    }}, ensure_ascii=False)