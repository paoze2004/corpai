"""sre_copilot MCP servers — 官方 MCP 协议实现(fastmcp 3.x + Anthropic MCP SDK)。

替换原 python_a2a FastMCP(私有 HTTP)。每个端口一个 FastMCP server,
用 StreamableHTTP transport 暴露 tool。tool schema 自动从函数签名 +
docstring + type hints 推导(JSON Schema)。

启动方式:`python -m sre_copilot.mcp_main`
"""
from __future__ import annotations

import logging
from typing import Optional

from fastmcp import FastMCP

from sre_copilot import bridges as b
from sre_copilot import tools as t

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════
#  :8020 ─ Incident + Oncall (Jira + PagerDuty)
# ═══════════════════════════════════════════════════════════════════════

incident_server = FastMCP(
    name="sre_copilot_incident",
    instructions=(
        "SRE incident + on-call 查询。接 Jira REST API v3 和 PagerDuty REST API。"
        "需 sre:read scope。"
    ),
)


@incident_server.tool()
def query_incident(
    incident_id: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 10,
) -> str:
    """查工单(接 Jira REST API v3)。

    至少传一个过滤参数,或仅查 limit 条最近工单。
    需要 JIRA_URL/JIRA_EMAIL/JIRA_TOKEN/JIRA_PROJECT 环境变量。
    """
    return t.query_incident(
        incident_id=incident_id, status=status,
        priority=priority, limit=limit,
    )


@incident_server.tool()
def query_oncall(team: str = "platform") -> str:
    """查 on-call 联系信息(接 PagerDuty REST API)。

    team ∈ {platform, data, security, network, mobile, frontend, devops, qa}
    需要 PAGERDUTY_API_KEY 和 PAGERDUTY_SCHEDULE_ID_<TEAM> 环境变量。
    """
    return t.query_oncall(team=team)


# ═══════════════════════════════════════════════════════════════════════
#  :8021 ─ K8s Pod 日志
# ═══════════════════════════════════════════════════════════════════════

k8s_server = FastMCP(
    name="sre_copilot_k8s",
    instructions="Kubernetes pod 日志查询(DRY_RUN 默认,设 K8S_DRY_RUN=false 走真实 API)。",
)


@k8s_server.tool()
def get_pod_logs(pod_name: str, namespace: str, tail_lines: int = 100) -> str:
    """查 Pod 日志(接 kubernetes-python)。

    Args:
        pod_name: Pod 名
        namespace: Namespace
        tail_lines: 返回尾部行数(1-10000)

    DRY_RUN 模式返 stub;真实模式需 KUBECONFIG 或 in-cluster config。
    """
    return t.get_pod_logs(pod_name=pod_name, namespace=namespace, tail_lines=tail_lines)


# ═══════════════════════════════════════════════════════════════════════
#  :8022 ─ Prometheus 告警
# ═══════════════════════════════════════════════════════════════════════

alert_server = FastMCP(
    name="sre_copilot_alert",
    instructions="Prometheus Alertmanager 告警查询。需要 PROMETHEUS_URL 环境变量。",
)


@alert_server.tool()
def query_alert(
    alert_id: Optional[str] = None,
    severity: Optional[str] = None,
    service: Optional[str] = None,
    state: Optional[str] = None,
) -> str:
    """查告警(接 Prometheus Alertmanager API v2)。

    所有参数可选,过滤后返回列表。
    """
    return t.query_alert(
        alert_id=alert_id, severity=severity,
        service=service, state=state,
    )


# ═══════════════════════════════════════════════════════════════════════
#  :8027 ─ Bridge: SRE → HR
# ═══════════════════════════════════════════════════════════════════════

bridge_hr_server = FastMCP(
    name="sre_copilot_bridge_hr",
    instructions="SRE → HR 跨插件桥接:请假触发 oncall 备份检查。",
)


@bridge_hr_server.tool()
def cross_check_hr(authorization: str, request_id: str) -> str:
    """跨插件:HR 申请触发时,查 HR 找关联申请(请年假触发 oncall 备份)。

    Args:
        authorization: Bearer token(传 user JWT)
        request_id: HR 申请 ID(L 开头)
    """
    return b.cross_check_hr(authorization=authorization, request_id=request_id)


# ═══════════════════════════════════════════════════════════════════════
#  :8028 ─ Bridge: SRE → FAQ
# ═══════════════════════════════════════════════════════════════════════

bridge_faq_server = FastMCP(
    name="sre_copilot_bridge_faq",
    instructions="SRE → FAQ 跨插件桥接:SOP 兜底补全。",
)


@bridge_faq_server.tool()
def cross_query_knowledge(query: str, top_k: int = 2) -> str:
    """跨插件:FAQ 兜底补全(SOP 补全)。

    Args:
        query: 用户查询文本
        top_k: 返回 top 几
    """
    return b.cross_query_knowledge(query=query, top_k=top_k)


# 每个 server 的端口(用 list 保持顺序,跟 plugin.py 里的 manifest 对齐)
SERVER_PORTS = [
    (incident_server, 8020),
    (k8s_server, 8021),
    (alert_server, 8022),
    (bridge_hr_server, 8027),
    (bridge_faq_server, 8028),
]