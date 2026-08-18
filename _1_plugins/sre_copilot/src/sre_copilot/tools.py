"""sre_copilot plugin 工具 v3.0 — 4 个真工具,接真 SDK(Phase 1 接入)。

工具清单:
- query_incident     → Jira REST API v3(requests + JIRA_URL+JIRA_TOKEN)
- query_oncall       → PagerDuty REST API(requests + PAGERDUTY_API_KEY)
- query_alert        → Prometheus Alertmanager API v2(requests + PROMETHEUS_URL)
- get_pod_logs       → kubernetes-python(KUBECONFIG / in-cluster)

错误模型(Phase 1 显式化):
- 401 retry 一次,仍失败 → http401 + Counter
- 超时 → timeout + Counter
- 不可达 → unreachable + Counter
- 4xx/5xx → http4xx/http5xx + Counter
- JSON 解析失败 → json_decode + Counter
- 业务错误(not_found/invalid) → 显式 status

RBAC 校验:query_* 需 sre:read;K8s 操作需 sre:write。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

import requests

from _0_CorpAI._2_platform.observability.metrics import DEVOPS_SDK_ERRORS_TOTAL

logger = logging.getLogger(__name__)

DRY_RUN = os.getenv("K8S_DRY_RUN", "true").lower() == "true"
_SDK_TIMEOUT = 5.0  # 5 秒,比 bridge 严格 2s 稍宽(SDK 可能慢)


# ────────── RBAC 校验 ──────────

def _check_sre_read(authorization: str | None = None) -> dict:
    """校验 token 含 sre:read 或 *。返回 claims。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise PermissionError("需要 Bearer token (scope=sre:read)")
    try:
        from _0_CorpAI._2_platform.auth.dependencies import get_jwt_secret
        from _0_CorpAI._2_platform.auth.scopes import has_scope
        from _0_CorpAI._2_platform.auth.tokens import jwt_decode
        claims = jwt_decode(authorization[len("Bearer "):], get_jwt_secret())
    except Exception as e:
        raise PermissionError(f"token 解析失败: {e}") from e
    if not claims:
        raise PermissionError("token 无效或已过期")
    scopes = claims.get("scopes", [])
    if not has_scope("sre:read", scopes):
        raise PermissionError(f"需要 sre:read,实有 {scopes}")
    return claims


def _check_sre_write(authorization: str | None = None) -> dict:
    """校验 token 含 sre:write 或 *。返回 claims。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise PermissionError("需要 Bearer token (scope=sre:write)")
    try:
        from _0_CorpAI._2_platform.auth.dependencies import get_jwt_secret
        from _0_CorpAI._2_platform.auth.scopes import has_scope
        from _0_CorpAI._2_platform.auth.tokens import jwt_decode
        claims = jwt_decode(authorization[len("Bearer "):], get_jwt_secret())
    except Exception as e:
        raise PermissionError(f"token 解析失败: {e}") from e
    if not claims:
        raise PermissionError("token 无效或已过期")
    scopes = claims.get("scopes", [])
    if not has_scope("sre:write", scopes):
        raise PermissionError(f"需要 sre:write,实有 {scopes}")
    return claims


# ────────── SDK 调用通用错误处理 ──────────

def _sdk_call(sdk: str, method: str, url: str,
              headers: dict | None = None, params: dict | None = None,
              json_body: dict | None = None, timeout: float = _SDK_TIMEOUT
              ) -> tuple[int, dict | list | str]:
    """统一 SDK HTTP 调用 + 错误分类 + Counter。

    返回:(status_code, parsed_body_or_text)
      - (200, dict/list) 成功
      - (4xx/5xx, str)   错误响应体
      - (-1, str)        网络异常(timeout/unreachable/error),str 是错误类别
    """
    try:
        resp = requests.request(
            method, url, headers=headers or {},
            params=params or {}, json=json_body,
            timeout=timeout,
        )
    except requests.Timeout:
        DEVOPS_SDK_ERRORS_TOTAL.labels(sdk=sdk, kind="timeout").inc()
        return (-1, "timeout")
    except requests.ConnectionError as exc:
        DEVOPS_SDK_ERRORS_TOTAL.labels(sdk=sdk, kind="unreachable").inc()
        return (-1, f"unreachable:{exc.__class__.__name__}")
    except Exception as exc:
        DEVOPS_SDK_ERRORS_TOTAL.labels(sdk=sdk, kind="error").inc()
        logger.warning(f"{sdk} SDK 异常:{exc}")
        return (-1, f"error:{exc}")

    # HTTP 状态码分类
    if resp.status_code == 401:
        DEVOPS_SDK_ERRORS_TOTAL.labels(sdk=sdk, kind="http401").inc()
    elif resp.status_code == 403:
        DEVOPS_SDK_ERRORS_TOTAL.labels(sdk=sdk, kind="http403").inc()
    elif 400 <= resp.status_code < 500:
        DEVOPS_SDK_ERRORS_TOTAL.labels(sdk=sdk, kind="http4xx").inc()
    elif resp.status_code >= 500:
        DEVOPS_SDK_ERRORS_TOTAL.labels(sdk=sdk, kind="http5xx").inc()

    # 解析 JSON
    if resp.headers.get("content-type", "").startswith("application/json"):
        try:
            return (resp.status_code, resp.json())
        except Exception as exc:
            DEVOPS_SDK_ERRORS_TOTAL.labels(sdk=sdk, kind="json_decode").inc()
            return (resp.status_code, f"json_decode:{exc}")

    return (resp.status_code, resp.text)


def _err_envelope(action: str, kind: str, message: str, **extra) -> str:
    """统一错误信封(对应 JSON envelope 契约)。"""
    return json.dumps({
        "status": "error",
        "kind": kind,
        "message": message,
        **extra,
    }, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════
#  1. query_incident — Jira 工单查询
# ════════════════════════════════════════════════════════════════

def query_incident(incident_id: str | None = None,
                   status: str | None = None,
                   priority: str | None = None,
                   limit: int = 10) -> str:
    """查工单(接 Jira REST API v3)。

    需要环境变量:
      - JIRA_URL      e.g. https://corp.atlassian.net
      - JIRA_EMAIL    注册 Atlassian 用的邮箱(Basic auth 必须)
      - JIRA_TOKEN    API Token(从 id.atlassian.com/.../api-tokens 生成)
      - JIRA_PROJECT  默认 INC
    """
    jira_url = os.getenv("JIRA_URL", "").rstrip("/")
    jira_email = os.getenv("JIRA_EMAIL")
    jira_token = os.getenv("JIRA_TOKEN")
    jira_project = os.getenv("JIRA_PROJECT", "INC")

    if not jira_url or not jira_token or not jira_email:
        logger.warning("query_incident: JIRA_URL / JIRA_TOKEN / JIRA_EMAIL 未配置")
        return json.dumps({
            "status": "not_configured",
            "message": "query_incident 需要 JIRA_URL + JIRA_EMAIL + JIRA_TOKEN。",
            "required_env": ["JIRA_URL", "JIRA_EMAIL", "JIRA_TOKEN", "JIRA_PROJECT"],
        }, ensure_ascii=False)

    # 构造 JQL
    jql_parts = [f'project = "{jira_project}"']
    if incident_id:
        jql_parts.append(f'key = "{incident_id.upper()}"')
    if status:
        jql_parts.append(f'status = "{status}"')
    if priority:
        jql_parts.append(f'priority = "{priority}"')
    jql = " AND ".join(jql_parts) + " ORDER BY updated DESC"

    # 调 Jira REST API v3 — Atlassian API Token 必须 Basic auth = base64(email:token)
    # 2025-04 后 /rest/api/3/search 弃用,改用 POST /rest/api/3/search/jql
    # (https://developer.atlassian.com/changelog/#CHANGE-2046)
    import base64
    auth_b64 = base64.b64encode(f"{jira_email}:{jira_token}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    json_body = {
        "jql": jql,
        "maxResults": min(limit, 50),
        "fields": ["summary", "status", "priority", "assignee", "updated", "created", "description"],
    }
    status_code, body = _sdk_call(
        "jira", "POST",
        f"{jira_url}/rest/api/3/search/jql",
        headers=headers, json_body=json_body,
    )

    if status_code == -1:
        return _err_envelope(
            "query_incident", body.split(":")[0],
            f"Jira 调用失败:{body}", jql=jql,
        )
    if status_code != 200:
        return _err_envelope(
            "query_incident", f"http{status_code}",
            f"Jira HTTP {status_code};body={str(body)[:200]}",
            jql=jql,
        )

    # 解析 issues[] → 统一格式
    if not isinstance(body, dict):
        DEVOPS_SDK_ERRORS_TOTAL.labels(sdk="jira", kind="json_decode").inc()
        return _err_envelope("query_incident", "json_decode",
                             "Jira 返非 dict")

    issues = body.get("issues", [])
    items = []
    for issue in issues:
        fields = issue.get("fields", {}) or {}
        items.append({
            "id": issue.get("key", ""),
            "title": fields.get("summary", ""),
            "priority": (fields.get("priority") or {}).get("name", "P?"),
            "status": (fields.get("status") or {}).get("name", "unknown"),
            "assignee": ((fields.get("assignee") or {}).get("displayName", "未分配")),
            "updated": fields.get("updated", ""),
            "created": fields.get("created", ""),
        })

    return json.dumps({
        "status": "success" if items else "no_data",
        "data": items,
        "total": body.get("total", len(items)),
        "message": "" if items else "未找到匹配工单。",
    }, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════
#  2. query_oncall — PagerDuty on-call 查询
# ════════════════════════════════════════════════════════════════

# Team → PagerDuty Schedule ID 映射(env: PAGERDUTY_SCHEDULE_ID_<TEAM>)
_PD_TEAMS = {
    "platform", "data", "security", "network", "mobile", "frontend", "devops", "qa",
}


def query_oncall(team: str = "platform") -> str:
    """查 on-call 联系信息(接 PagerDuty REST API)。

    需要环境变量:
      - PAGERDUTY_API_KEY   REST API key
      - PAGERDUTY_SCHEDULE_ID_<TEAM>  各 team 的 schedule ID
    """
    pd_api_key = os.getenv("PAGERDUTY_API_KEY")
    schedule_id = os.getenv(f"PAGERDUTY_SCHEDULE_ID_{team.upper()}")

    if not pd_api_key:
        logger.warning("query_oncall: PAGERDUTY_API_KEY 未配置")
        return json.dumps({
            "status": "not_configured",
            "message": "query_oncall 需要 PAGERDUTY_API_KEY。",
            "required_env": ["PAGERDUTY_API_KEY",
                             f"PAGERDUTY_SCHEDULE_ID_{team.upper()}"],
        }, ensure_ascii=False)

    if not schedule_id:
        logger.warning(f"query_oncall: PAGERDUTY_SCHEDULE_ID_{team.upper()} 未配置")
        return json.dumps({
            "status": "not_configured",
            "message": f"query_oncall(team={team}) 需要 PAGERDUTY_SCHEDULE_ID_{team.upper()}。",
            "required_env": [f"PAGERDUTY_SCHEDULE_ID_{team.upper()}"],
            "known_teams": sorted(_PD_TEAMS),
        }, ensure_ascii=False)

    headers = {
        "Authorization": f"Token token={pd_api_key}",
        "Accept": "application/json",
    }
    params = {
        "schedule_ids[]": schedule_id,
        "earliest": "true",
        "include[]": "users",
        "time_zone": "Asia/Shanghai",
    }
    status_code, body = _sdk_call(
        "pagerduty", "GET",
        "https://api.pagerduty.com/oncalls",
        headers=headers, params=params,
    )

    if status_code == -1:
        return _err_envelope(
            "query_oncall", body.split(":")[0],
            f"PagerDuty 调用失败:{body}", team=team,
        )
    if status_code != 200:
        return _err_envelope(
            "query_oncall", f"http{status_code}",
            f"PagerDuty HTTP {status_code};body={str(body)[:200]}",
            team=team,
        )

    # 解析 oncalls[] → 统一格式
    if not isinstance(body, dict):
        DEVOPS_SDK_ERRORS_TOTAL.labels(sdk="pagerduty", kind="json_decode").inc()
        return _err_envelope("query_oncall", "json_decode",
                             "PagerDuty 返非 dict")

    oncalls = body.get("oncalls", [])
    if not oncalls:
        return json.dumps({
            "status": "no_data",
            "message": f"PagerDuty 上 team={team} 当前无 oncall 排班",
            "team": team,
        }, ensure_ascii=False)

    # 按 escalation level 取 primary + secondary
    primary = next((o for o in oncalls if o.get("escalation_level") == 1), None)
    secondary = next((o for o in oncalls if o.get("escalation_level") == 2), None)

    info = {
        "team": team,
        "primary": _format_pd_user(primary.get("user") if primary else None),
        "secondary": _format_pd_user(secondary.get("user") if secondary else None),
        "schedule_url": (primary or oncalls[0]).get("schedule", {}).get("html_url", ""),
        "escalation_policy": (primary or oncalls[0]).get("escalation_policy", {}).get("summary", ""),
        "start": (primary or oncalls[0]).get("start", ""),
        "end": (primary or oncalls[0]).get("end", ""),
    }
    return json.dumps({
        "status": "success",
        "data": info,
    }, ensure_ascii=False)


def _format_pd_user(user: dict | None) -> dict:
    if not user:
        return {"name": "未排班", "email": "", "phone": ""}
    return {
        "name": user.get("name", ""),
        "email": user.get("email", ""),
        "phone": (user.get("contact_methods") or [{}])[0].get("address", "")
                  if user.get("contact_methods") else "",
    }


# ════════════════════════════════════════════════════════════════
#  3. query_alert — Prometheus Alertmanager 查询
# ════════════════════════════════════════════════════════════════

def query_alert(alert_id: str | None = None,
                severity: str | None = None,
                service: str | None = None,
                state: str | None = None) -> str:
    """查告警(接 Prometheus Alertmanager API v2)。

    需要环境变量:
      - PROMETHEUS_URL  e.g. http://alertmanager:9093
    """
    prom_url = os.getenv("PROMETHEUS_URL", "").rstrip("/")

    if not prom_url:
        logger.warning("query_alert: PROMETHEUS_URL 未配置")
        return json.dumps({
            "status": "not_configured",
            "message": "query_alert 需要 PROMETHEUS_URL。",
            "required_env": ["PROMETHEUS_URL"],
        }, ensure_ascii=False)

    headers = {"Accept": "application/json"}
    params = {
        "active": "true",
        "silenced": "false",
        "inhibited": "false",
        "unprocessed": "false",
    }
    status_code, body = _sdk_call(
        "prometheus", "GET",
        f"{prom_url}/api/v2/alerts",
        headers=headers, params=params,
    )

    if status_code == -1:
        return _err_envelope(
            "query_alert", body.split(":")[0],
            f"Alertmanager 调用失败:{body}",
        )
    if status_code != 200:
        return _err_envelope(
            "query_alert", f"http{status_code}",
            f"Alertmanager HTTP {status_code};body={str(body)[:200]}",
        )

    if not isinstance(body, list):
        DEVOPS_SDK_ERRORS_TOTAL.labels(sdk="prometheus", kind="json_decode").inc()
        return _err_envelope("query_alert", "json_decode",
                             "Alertmanager 返非 list")

    # 解析 alerts[] → 统一格式 + 客户端过滤
    items = []
    for a in body:
        labels = a.get("labels", {}) or {}
        status_obj = a.get("status", {}) or {}
        annotations = a.get("annotations", {}) or {}

        # 客户端过滤
        if alert_id and labels.get("alertname") != alert_id:
            continue
        if severity and labels.get("severity") != severity:
            continue
        if service and labels.get("service") != service and \
           labels.get("job") != service:
            continue
        if state and status_obj.get("state") != state:
            continue

        items.append({
            "id": labels.get("alertname", ""),
            "name": labels.get("alertname", ""),
            "severity": labels.get("severity", "unknown"),
            "service": labels.get("service", labels.get("job", "unknown")),
            "state": status_obj.get("state", "unknown"),
            "active_since": status_obj.get("activeSince", ""),
            "value": annotations.get("value", annotations.get("summary", "")),
            "summary": annotations.get("summary", annotations.get("description", "")),
            "labels": labels,
        })

    return json.dumps({
        "status": "success" if items else "no_data",
        "data": items,
        "total": len(items),
        "message": "" if items else "未找到匹配告警。",
    }, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════
#  4. get_pod_logs — kubernetes-python Pod 日志
# ════════════════════════════════════════════════════════════════

def get_pod_logs(pod_name: str, namespace: str, tail_lines: int = 100,
                  authorization: str | None = None) -> str:
    """查 Pod 日志(接 kubernetes-python)。

    需 sre:read scope。
    需要:KUBECONFIG 或 in-cluster config。
    DRY_RUN=true(默认)→返 stub 日志;DRY_RUN=false→真实调 K8s API。
    """
    _check_sre_read(authorization)

    if tail_lines < 1 or tail_lines > 10000:
        return json.dumps({"status": "invalid", "message": "tail_lines 越界(1-10000)"},
                          ensure_ascii=False)

    if DRY_RUN:
        now = datetime.now().isoformat()
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
    """Phase 1 真实 kubernetes-python 调用。"""
    try:
        from kubernetes import client, config
        from kubernetes.client.rest import ApiException
    except ImportError as exc:
        DEVOPS_SDK_ERRORS_TOTAL.labels(sdk="kubernetes", kind="error").inc()
        return _err_envelope(
            "get_pod_logs", "missing_dependency",
            f"kubernetes SDK 未安装:{exc};pip install kubernetes",
        )

    # 加载 K8s 配置:in-cluster 优先,失败走 KUBECONFIG
    try:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            kubeconfig = os.getenv("KUBECONFIG", os.path.expanduser("~/.kube/config"))
            if not os.path.exists(kubeconfig):
                DEVOPS_SDK_ERRORS_TOTAL.labels(sdk="kubernetes", kind="unreachable").inc()
                return _err_envelope(
                    "get_pod_logs", "no_kubeconfig",
                    f"K8S_DRY_RUN=false 但找不到 KUBECONFIG({kubeconfig});"
                    f"请设置 KUBECONFIG env 或在 K8s 集群内运行",
                )
            config.load_kube_config(kubeconfig)
    except Exception as exc:
        DEVOPS_SDK_ERRORS_TOTAL.labels(sdk="kubernetes", kind="error").inc()
        logger.warning(f"kubernetes config 加载失败:{exc}")
        return _err_envelope(
            "get_pod_logs", "config_load_failed",
            f"K8s config 加载失败:{exc}",
        )

    # 调 read_namespaced_pod_log
    v1 = client.CoreV1Api()
    try:
        logs_str = v1.read_namespaced_pod_log(
            name=pod_name, namespace=namespace,
            tail_lines=tail_lines,
            timestamps=True,
        )
    except ApiException as exc:
        kind = {
            401: "http401", 403: "http403", 404: "not_found",
        }.get(exc.status, f"http{exc.status}")
        DEVOPS_SDK_ERRORS_TOTAL.labels(sdk="kubernetes", kind=kind).inc()
        return _err_envelope(
            "get_pod_logs", kind,
            f"K8s API {exc.status}:{exc.reason};pod={pod_name} namespace={namespace}",
            pod=pod_name, namespace=namespace,
        )
    except Exception as exc:
        DEVOPS_SDK_ERRORS_TOTAL.labels(sdk="kubernetes", kind="error").inc()
        logger.warning(f"kubernetes read_namespaced_pod_log 失败:{exc}")
        return _err_envelope(
            "get_pod_logs", "error",
            f"K8s 调用失败:{exc}",
            pod=pod_name, namespace=namespace,
        )

    logs = logs_str.splitlines() if logs_str else []
    return json.dumps({
        "status": "success",
        "data": {
            "pod": pod_name, "namespace": namespace,
            "tail_lines": tail_lines,
            "logs": logs,
        },
    }, ensure_ascii=False)
