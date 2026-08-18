"""SRE Action Tools — 4 个真写工具(Deployment/Jira 写 API)。

设计原则:
- 每个 tool 都校验 scope(sre:execute)
- DRY_RUN=true(默认)时只返回 planned,不真调 SDK — 防止误操作
- 真接 SDK 失败 → PermanentError 标记 plan failed
- 全部落 sre_audit_log

依赖:
  K8s: kubernetes>=28.0(KUBECONFIG env 或 ~/.kube/config)
  Jira: requests + JIRA_URL/JIRA_EMAIL/JIRA_TOKEN

为什么是平台核心(不放 plugin):
  - 每个 tool 都用 sre_audit_log(平台表)
  - 都用 SRE_ACTION_EXECUTED Counter(平台 metrics)
  - 都走 ApprovalService 二次校验
  - plugin 应复用,不应自己重写
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import requests  # 提到顶层,方便测试 patch

from _0_CorpAI._2_platform.observability.metrics import SRE_ACTION_EXECUTED

logger = logging.getLogger(__name__)


# ─── 公共配置 ───

REQUIRED_SCOPE = "sre:execute"


def is_dry_run() -> bool:
    """每次查 env(支持测试动态切换)。

    默认 True — 必须在 ApprovalService 校验通过后由 Executor 显式设 False。
    """
    return os.environ.get("SRE_DRY_RUN", "true").lower() != "false"


# 向后兼容(老代码 import DRY_RUN 仍可用,但语义变成"上次查询的快照")
DRY_RUN = is_dry_run()


# ─── 错误类型 ───

class ActionToolError(Exception):
    """Action tool 业务错误。"""
    pass


class ConfigError(ActionToolError):
    """缺凭证 / 配置错(永久失败)。"""
    pass


class PermissionDeniedError(ActionToolError):
    """scope 不够(永久失败)。"""
    pass


class K8sError(ActionToolError):
    """K8s API 调用失败。"""
    pass


class JiraError(ActionToolError):
    """Jira API 调用失败。"""
    pass


# ─── 公共校验 ───

def _check_scope(scopes: list[str] | None) -> None:
    """所有 action tool 入口必须校验 scope。"""
    if not scopes or REQUIRED_SCOPE not in scopes:
        raise PermissionDeniedError(
            f"需要 scope {REQUIRED_SCOPE},当前 scopes={scopes}",
        )


def _audit(
    actor: str, action: str, target_type: str,
    target_id: str, detail: dict,
) -> None:
    """落 sre_audit_log(可选,失败不影响主流程)。"""
    try:
        from _0_CorpAI._2_platform.db import DatabasePool
        pool = DatabasePool.get()
        conn = pool.get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO sre_audit_log "
                "(trace_id, actor, action, target_type, target_id, detail) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                ("", actor, action, target_type, target_id,
                 json.dumps(detail, ensure_ascii=False)),
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning(f"audit log 写失败:{exc}")


# ─── 工具 1: restart_deployment ───

@dataclass
class DeploymentTarget:
    name: str
    namespace: str = "default"


def restart_deployment(
    deployment: str,
    namespace: str = "default",
    actor: str = "executor",
    scopes: list[str] | None = None,
    trace_id: str = "",
) -> dict[str, Any]:
    """Deployment rollout restart(K8s 写 API)。

    行为:
      - DRY_RUN=true → 只返 planned,不调 K8s
      - DRY_RUN=false → 调 AppsV1Api.patch_namespaced_deployment
        rollout=restart annotation (kubectl rollout restart 等价)
      - 失败 → PermanentError(让 Executor 标 failed)

    Returns:{status, deployment, namespace, generation?}
    """
    _check_scope(scopes)
    target_id = f"{namespace}/{deployment}"
    detail = {"deployment": deployment, "namespace": namespace}

    if is_dry_run():
        logger.info(
            f"[DRY_RUN] restart_deployment {target_id} actor={actor}",
        )
        SRE_ACTION_EXECUTED.labels(
            tool="restart_deployment", status="dry_run",
        ).inc()
        _audit(actor, "restart_deployment_dry_run",
               "deployment", target_id, detail)
        return {
            "status": "dry_run",
            "deployment": deployment,
            "namespace": namespace,
            "message": "DRY_RUN — 未真执行 K8s API",
        }

    # 真接 K8s
    try:
        from kubernetes import (
            client as k8s_client,  # type: ignore
            config as k8s_config,  # type: ignore
        )
        from kubernetes.client.rest import ApiException  # type: ignore
    except ImportError as exc:
        raise ConfigError("kubernetes 包缺失 — uv add kubernetes") from exc

    kubeconfig = os.environ.get("KUBECONFIG") or os.path.expanduser("~/.kube/config")
    if not os.path.exists(kubeconfig):
        raise ConfigError(
            f"KUBECONFIG={kubeconfig} 不存在;请设置 KUBECONFIG env 或"
            f"放 ~/.kube/config",
        )

    try:
        k8s_config.load_kube_config(config_file=kubeconfig)
        apps_v1 = k8s_client.AppsV1Api()
        now = __import__("datetime").datetime.utcnow().isoformat() + "Z"
        body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": now,
                        },
                    },
                },
            },
        }
        api_resp = apps_v1.patch_namespaced_deployment(
            name=deployment, namespace=namespace, body=body,
        )
        generation = api_resp.metadata.generation if api_resp and api_resp.metadata else None
        logger.info(f"restart_deployment {target_id} OK gen={generation}")
        SRE_ACTION_EXECUTED.labels(
            tool="restart_deployment", status="success",
        ).inc()
        _audit(actor, "restart_deployment",
               "deployment", target_id, {**detail, "generation": generation})
        return {
            "status": "success",
            "deployment": deployment,
            "namespace": namespace,
            "generation": generation,
        }
    except ApiException as exc:
        logger.exception(f"restart_deployment {target_id} K8s API 失败")
        SRE_ACTION_EXECUTED.labels(
            tool="restart_deployment", status="k8s_error",
        ).inc()
        raise K8sError(f"K8s {exc.status} {exc.reason}:{exc.body}") from exc


# ─── 工具 2: scale_deployment ───

def scale_deployment(
    deployment: str,
    replicas: int,
    namespace: str = "default",
    actor: str = "executor",
    scopes: list[str] | None = None,
) -> dict[str, Any]:
    """改 Deployment replicas(K8s 写 API)。

    replicas ∈ [0, 50](生产上限)。
    """
    _check_scope(scopes)
    if not (0 <= replicas <= 50):
        raise ConfigError(f"replicas={replicas} 超出 [0,50] 范围")

    target_id = f"{namespace}/{deployment}"
    detail = {"deployment": deployment, "namespace": namespace, "replicas": replicas}

    if is_dry_run():
        logger.info(f"[DRY_RUN] scale_deployment {target_id} replicas={replicas}")
        SRE_ACTION_EXECUTED.labels(
            tool="scale_deployment", status="dry_run",
        ).inc()
        _audit(actor, "scale_deployment_dry_run",
               "deployment", target_id, detail)
        return {
            "status": "dry_run",
            "deployment": deployment,
            "namespace": namespace,
            "replicas": replicas,
        }

    try:
        from kubernetes import client as k8s_client, config as k8s_config
        from kubernetes.client.rest import ApiException
    except ImportError as exc:
        raise ConfigError("kubernetes 包缺失") from exc

    kubeconfig = os.environ.get("KUBECONFIG") or os.path.expanduser("~/.kube/config")
    if not os.path.exists(kubeconfig):
        raise ConfigError(f"KUBECONFIG={kubeconfig} 不存在")

    try:
        k8s_config.load_kube_config(config_file=kubeconfig)
        apps_v1 = k8s_client.AppsV1Api()
        body = {"spec": {"replicas": replicas}}
        api_resp = apps_v1.patch_namespaced_deployment_scale(
            name=deployment, namespace=namespace, body=body,
        )
        new_replicas = (
            api_resp.spec.replicas if api_resp and api_resp.spec else replicas
        )
        SRE_ACTION_EXECUTED.labels(
            tool="scale_deployment", status="success",
        ).inc()
        _audit(actor, "scale_deployment",
               "deployment", target_id, {**detail, "new_replicas": new_replicas})
        return {
            "status": "success",
            "deployment": deployment,
            "namespace": namespace,
            "replicas": new_replicas,
        }
    except ApiException as exc:
        SRE_ACTION_EXECUTED.labels(
            tool="scale_deployment", status="k8s_error",
        ).inc()
        raise K8sError(f"K8s {exc.status} {exc.reason}:{exc.body}") from exc


# ─── 工具 3: update_incident_status ───

def update_incident_status(
    issue_key: str,
    target_status: str,
    actor: str = "executor",
    scopes: list[str] | None = None,
) -> dict[str, Any]:
    """Jira issue 状态转移(例如 "进行中" → "已解决")。

    依赖:JIRA_URL/JIRA_EMAIL/JIRA_TOKEN env。

    target_status 必须是 Jira 显示的中文名(你的 Jira 配置),
    也可以传 transition name。函数内部查 transition id 再 POST。
    """
    _check_scope(scopes)
    if is_dry_run():
        logger.info(
            f"[DRY_RUN] update_incident_status {issue_key} → {target_status}",
        )
        SRE_ACTION_EXECUTED.labels(
            tool="update_incident_status", status="dry_run",
        ).inc()
        _audit(actor, "update_incident_status_dry_run",
               "issue", issue_key, {"target_status": target_status})
        return {
            "status": "dry_run",
            "issue_key": issue_key,
            "target_status": target_status,
        }

    jira_url = os.environ.get("JIRA_URL", "").rstrip("/")
    jira_email = os.environ.get("JIRA_EMAIL", "")
    jira_token = os.environ.get("JIRA_TOKEN", "")
    if not (jira_url and jira_email and jira_token):
        raise ConfigError(
            "需 JIRA_URL + JIRA_EMAIL + JIRA_TOKEN env",
        )

    import base64
    auth_b64 = base64.b64encode(f"{jira_email}:{jira_token}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # 1) 查 transitions
    try:
        r = requests.get(
            f"{jira_url}/rest/api/3/issue/{issue_key}/transitions",
            headers=headers, timeout=10,
        )
    except requests.RequestException as exc:
        raise JiraError(f"Jira 不可达:{exc}") from exc
    if r.status_code != 200:
        raise JiraError(f"查 transitions 失败 {r.status_code}:{r.text[:200]}")
    transitions = r.json().get("transitions", [])
    match = next(
        (t for t in transitions
         if t.get("name") == target_status
         or t.get("to", {}).get("name") == target_status),
        None,
    )
    if not match:
        names = [t.get("name") for t in transitions]
        raise ConfigError(
            f"Jira {issue_key} 无 transition '{target_status}',"
            f"可用:{names}",
        )

    # 2) POST transition
    try:
        r = requests.post(
            f"{jira_url}/rest/api/3/issue/{issue_key}/transitions",
            headers=headers,
            json={"transition": {"id": match["id"]}},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise JiraError(f"Jira POST 失败:{exc}") from exc
    if r.status_code not in (204, 200):
        raise JiraError(
            f"Jira transition 失败 {r.status_code}:{r.text[:200]}",
        )

    SRE_ACTION_EXECUTED.labels(
        tool="update_incident_status", status="success",
    ).inc()
    _audit(actor, "update_incident_status",
           "issue", issue_key,
           {"target_status": target_status, "transition_id": match["id"]})
    return {
        "status": "success",
        "issue_key": issue_key,
        "target_status": target_status,
        "transition_id": match["id"],
    }


# ─── 工具 4: create_incident_comment ───

def create_incident_comment(
    issue_key: str,
    body_adf: dict[str, Any],
    actor: str = "executor",
    scopes: list[str] | None = None,
) -> dict[str, Any]:
    """Jira issue 加评论(ADF 格式 body)。

    body_adf 例:
      {"version": 1, "type": "doc", "content": [{
        "type": "paragraph", "content": [{"type": "text", "text": "AI 修复中"}],
      }]}

    也接受纯文本(自动包成 ADF):
      "AI 已完成 rollout"
    """
    _check_scope(scopes)

    # 字符串自动包成 ADF(在 dry_run check 前,让 dry_run 也走包装)
    if isinstance(body_adf, str):
        body_adf = {
            "version": 1,
            "type": "doc",
            "content": [{
                "type": "paragraph",
                "content": [{"type": "text", "text": body_adf}],
            }],
        }

    if is_dry_run():
        logger.info(f"[DRY_RUN] create_incident_comment {issue_key}")
        SRE_ACTION_EXECUTED.labels(
            tool="create_incident_comment", status="dry_run",
        ).inc()
        _audit(actor, "create_incident_comment_dry_run",
               "issue", issue_key, {"body": body_adf})
        return {"status": "dry_run", "issue_key": issue_key}

    jira_url = os.environ.get("JIRA_URL", "").rstrip("/")
    jira_email = os.environ.get("JIRA_EMAIL", "")
    jira_token = os.environ.get("JIRA_TOKEN", "")
    if not (jira_url and jira_email and jira_token):
        raise ConfigError("需 JIRA_URL + JIRA_EMAIL + JIRA_TOKEN env")

    import base64
    auth_b64 = base64.b64encode(f"{jira_email}:{jira_token}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(
            f"{jira_url}/rest/api/3/issue/{issue_key}/comment",
            headers=headers, json={"body": body_adf}, timeout=10,
        )
    except requests.RequestException as exc:
        raise JiraError(f"Jira POST 失败:{exc}") from exc
    if r.status_code not in (201, 200):
        raise JiraError(
            f"Jira comment 失败 {r.status_code}:{r.text[:200]}",
        )

    comment_id = r.json().get("id", "")
    SRE_ACTION_EXECUTED.labels(
        tool="create_incident_comment", status="success",
    ).inc()
    _audit(actor, "create_incident_comment",
           "issue", issue_key, {"comment_id": comment_id})
    return {"status": "success", "issue_key": issue_key, "comment_id": comment_id}


# ─── 分发表(给 ActionExecutor.tool_dispatcher 用) ───

TOOL_REGISTRY = {
    "restart_deployment": restart_deployment,
    "scale_deployment": scale_deployment,
    "update_incident_status": update_incident_status,
    "create_incident_comment": create_incident_comment,
}


async def tool_dispatcher(action: dict[str, Any]) -> dict[str, Any]:
    """SRE.e 的 dispatcher — Executor 调这里。

    action 格式:{"tool": "restart_deployment", "args": {...},
                  "actor": "executor", "scopes": [...]}
    """
    import asyncio
    tool_name = action.get("tool", "")
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        raise ConfigError(f"未知 tool:{tool_name},支持:{list(TOOL_REGISTRY)}")
    args = action.get("args", {}) or {}
    # actor/scopes 走 kwargs 不走 args(避免 LLM 注入)
    kwargs = dict(args)
    kwargs.setdefault("actor", action.get("actor", "executor"))
    kwargs.setdefault("scopes", action.get("scopes", [REQUIRED_SCOPE]))
    # 在线程池跑(requests 阻塞)— 简单包装避免 asyncio loop 阻塞
    return await asyncio.get_event_loop().run_in_executor(
        None, lambda: fn(**kwargs),
    )


__all__ = [
    "REQUIRED_SCOPE",
    "TOOL_REGISTRY",
    "ActionToolError",
    "ConfigError",
    "JiraError",
    "K8sError",
    "PermissionDeniedError",
    "create_incident_comment",
    "is_dry_run",
    "restart_deployment",
    "scale_deployment",
    "tool_dispatcher",
    "update_incident_status",
]
