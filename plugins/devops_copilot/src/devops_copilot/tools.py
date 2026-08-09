"""devops_copilot plugin 工具 v3.0 — 生产化精简到 4 个真工具。

每个工具都接**真 SDK**(Phase 1 接入);Phase 0 stub 阶段显式 not_configured,绝不编造数据。

工具清单(4):
- query_incident     → Jira REST API(JIRA_URL + JIRA_TOKEN)
- query_oncall       → PagerDuty API(PAGERDUTY_API_KEY)
- query_alert        → Prometheus Alertmanager(PROMETHEUS_URL)
- get_pod_logs       → kubernetes-python(KUBECONFIG / in-cluster)

RBAC 校验:query_* 需 devops:read;K8s 操作需 devops:write。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

DRY_RUN = os.getenv("K8S_DRY_RUN", "true").lower() == "true"


# ────────── RBAC 校验 ──────────

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


# ════════════════════════════════════════════════════════════════
#  1. query_incident — Jira 工单查询
# ════════════════════════════════════════════════════════════════

def query_incident(incident_id: Optional[str] = None,
                   status: Optional[str] = None,
                   priority: Optional[str] = None,
                   limit: int = 10) -> str:
    """查工单(接 Jira REST API)。

    需要环境变量:
      - JIRA_URL      e.g. https://corp.atlassian.net
      - JIRA_TOKEN    Personal Access Token
      - JIRA_PROJECT  e.g. INC (默认项目 key)

    Phase 1:实现 _call_jira_search() 用 `requests` 调用
      GET {JIRA_URL}/rest/api/3/search?jql=...
    """
    jira_url = os.getenv("JIRA_URL")
    jira_token = os.getenv("JIRA_TOKEN")
    jira_project = os.getenv("JIRA_PROJECT", "INC")

    if not jira_url or not jira_token:
        logger.warning("query_incident: JIRA_URL 或 JIRA_TOKEN 未配置")
        return json.dumps({
            "status": "not_configured",
            "message": (
                "query_incident 需要配置 JIRA_URL + JIRA_TOKEN 环境变量。"
                "Phase 1 将通过 Jira REST API 实现真实查询。"
            ),
            "required_env": ["JIRA_URL", "JIRA_TOKEN"],
        }, ensure_ascii=False)

    # Phase 1 实现位
    return _call_jira_search(jira_url, jira_token, jira_project,
                              incident_id, status, priority, limit)


def _call_jira_search(jira_url: str, jira_token: str, project: str,
                       incident_id: Optional[str], status: Optional[str],
                       priority: Optional[str], limit: int) -> str:
    """Phase 1 占位:真实 Jira 查询。Phase 0 显式 not_implemented。"""
    # TODO(phase-1):用 requests 调 GET /rest/api/3/search
    #   jql = [f"project = {project}"]
    #   if incident_id: jql.append(f"key = {incident_id}")
    #   if status: jql.append(f"status = '{status}'")
    #   if priority: jql.append(f"priority = {priority}")
    #   resp = requests.get(f"{jira_url}/rest/api/3/search",
    #                       params={"jql": " AND ".join(jql), "maxResults": limit},
    #                       headers={"Authorization": f"Bearer {jira_token}"},
    #                       timeout=5)
    #   resp.raise_for_status()
    #   return _format_jira_incidents(resp.json()["issues"])
    return json.dumps({
        "status": "not_implemented",
        "message": (
            "Phase 1 待实现:Phase 0 stub 已通过 not_configured 检测。"
            "JIRA_URL 已配置,Phase 1 会调用 Jira REST API 真实查询。"
        ),
    }, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════
#  2. query_oncall — PagerDuty on-call 查询
# ════════════════════════════════════════════════════════════════

def query_oncall(team: str = "platform") -> str:
    """查 on-call 联系信息(接 PagerDuty API)。

    需要环境变量:
      - PAGERDUTY_API_KEY   REST API key (https://corp.pagerduty.com/api_keys)
      - PAGERDUTY_SCHEDULE_ID_<TEAM>  各 team 的 schedule ID

    Phase 1 实现位:_call_pagerduty_oncalls(team) 用 `requests` 调用
      GET https://api.pagerduty.com/oncalls?schedule_ids[]=...
    """
    pd_api_key = os.getenv("PAGERDUTY_API_KEY")

    if not pd_api_key:
        logger.warning("query_oncall: PAGERDUTY_API_KEY 未配置")
        return json.dumps({
            "status": "not_configured",
            "message": (
                "query_oncall 需要 PAGERDUTY_API_KEY 环境变量。"
                "Phase 1 将通过 PagerDuty API 实现真实查询。"
            ),
            "required_env": ["PAGERDUTY_API_KEY", "PAGERDUTY_SCHEDULE_ID_<TEAM>"],
        }, ensure_ascii=False)

    return _call_pagerduty_oncalls(pd_api_key, team)


def _call_pagerduty_oncalls(api_key: str, team: str) -> str:
    """Phase 1 占位。"""
    # TODO(phase-1):
    #   schedule_id = os.getenv(f"PAGERDUTY_SCHEDULE_ID_{team.upper()}")
    #   resp = requests.get("https://api.pagerduty.com/oncalls",
    #                       params={"schedule_ids[]": schedule_id, "earliest": True},
    #                       headers={"Authorization": f"Token token={api_key}",
    #                                "Accept": "application/json"},
    #                       timeout=5)
    #   resp.raise_for_status()
    #   return _format_pd_oncalls(resp.json()["oncalls"])
    return json.dumps({
        "status": "not_implemented",
        "message": "Phase 1:调 PagerDuty API /oncalls。Phase 0 stub 阶段显示此消息。",
    }, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════
#  3. query_alert — Prometheus Alertmanager 查询
# ════════════════════════════════════════════════════════════════

def query_alert(alert_id: Optional[str] = None,
                severity: Optional[str] = None,
                service: Optional[str] = None,
                state: Optional[str] = None) -> str:
    """查告警(接 Prometheus Alertmanager API v2)。

    需要环境变量:
      - PROMETHEUS_URL  e.g. http://alertmanager:9093

    Phase 1 实现位:_call_alertmanager() 用 `prometheus-api-client` 或 `requests` 调用
      GET {PROMETHEUS_URL}/api/v2/alerts
    """
    prom_url = os.getenv("PROMETHEUS_URL")

    if not prom_url:
        logger.warning("query_alert: PROMETHEUS_URL 未配置")
        return json.dumps({
            "status": "not_configured",
            "message": (
                "query_alert 需要 PROMETHEUS_URL 环境变量。"
                "Phase 1 将通过 Alertmanager API v2 实现真实查询。"
            ),
            "required_env": ["PROMETHEUS_URL"],
        }, ensure_ascii=False)

    return _call_alertmanager(prom_url, alert_id, severity, service, state)


def _call_alertmanager(prom_url: str, alert_id: Optional[str],
                        severity: Optional[str], service: Optional[str],
                        state: Optional[str]) -> str:
    """Phase 1 占位。"""
    # TODO(phase-1):
    #   resp = requests.get(f"{prom_url}/api/v2/alerts",
    #                       params={"filter": ...}, timeout=5)
    #   alerts = resp.json()
    #   if alert_id: alerts = [a for a in alerts if a["labels"]["alertname"] == alert_id]
    #   if severity: alerts = [a for a in alerts if a["labels"]["severity"] == severity]
    #   if state: alerts = [a for a in alerts if a["status"]["state"] == state]
    #   return _format_alerts(alerts)
    return json.dumps({
        "status": "not_implemented",
        "message": "Phase 1:调 Alertmanager /api/v2/alerts。Phase 0 stub 阶段。",
    }, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════
#  4. get_pod_logs — kubernetes-python Pod 日志
# ════════════════════════════════════════════════════════════════

def get_pod_logs(pod_name: str, namespace: str, tail_lines: int = 100,
                  authorization: Optional[str] = None) -> str:
    """查 Pod 日志(接 kubernetes-python)。

    需 devops:read scope。
    需要环境变量:
      - KUBECONFIG              K8s 配置文件路径(本地开发)
      - 或 in-cluster config    生产(K8s Pod 内)

    DRY_RUN=true(默认)→返 stub 日志;false→真实调 API。
    """
    _check_devops_read(authorization)

    if tail_lines < 1 or tail_lines > 10000:
        return json.dumps({"status": "invalid", "message": "tail_lines 越界(1-10000)"},
                          ensure_ascii=False)

    if DRY_RUN:
        import datetime as _dt
        now = _dt.datetime.now().isoformat()
        mock = [
            f"{now} INFO  {pod_name} ready",
            f"{now} INFO  {pod_name} request_id=abc status=200 latency=42ms",
            f"{now} WARN  {pod_name} connection pool 80% utilized",
        ]
        return json.dumps({
            "status": "dry_run",
            "pod": pod_name, "namespace": namespace,
            "tail_lines": tail_lines,
            "logs": mock[-tail_lines:],
            "warning": "K8S_DRY_RUN=true,设 false 调真实 kubernetes API",
        }, ensure_ascii=False)

    return _call_k8s_logs(pod_name, namespace, tail_lines)


def _call_k8s_logs(pod_name: str, namespace: str, tail_lines: int) -> str:
    """Phase 1 占位:真实 kubernetes-python 调用。"""
    # TODO(phase-1):
    #   from kubernetes import client, config
    #   try:
    #       config.load_incluster_config()
    #   except config.ConfigException:
    #       config.load_kube_config(os.getenv("KUBECONFIG"))
    #   v1 = client.CoreV1Api()
    #   logs = v1.read_namespaced_pod_log(name=pod_name, namespace=namespace,
    #                                     tail_lines=tail_lines)
    #   return json.dumps({"status": "success", "data": {
    #       "pod": pod_name, "namespace": namespace,
    #       "tail_lines": tail_lines, "logs": logs.splitlines(),
    #   }})
    return json.dumps({
        "status": "not_implemented",
        "message": "Phase 1:调 kubernetes.CoreV1Api.read_namespaced_pod_log。",
    }, ensure_ascii=False)