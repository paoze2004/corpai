"""SRE 飞书集成 — 发审批卡片 + 收审批 callback。

两个动作:
1. send_approval_card(plan_id, token, plan_summary, risk_level)
   → 飞书 interactive card + approve_url / reject_url
2. handle_callback(payload) 验证 token 后调 ApprovalService

依赖(待用户提供):
  FEISHU_APP_ID         — 应用 ID
  FEISHU_APP_SECRET     — 应用密钥
  FEISHU_BOT_WEBHOOK    — 群机器人 incoming webhook(快速通道)
  FEISHU_VERIFY_TOKEN   — 回调 URL 验证 token
  FEISHU_ENCRYPT_KEY    — 回调加密 key(可选)

飞书卡片格式见:https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/feishu-cards/card-template

为什么不用 钉钉/企业微信:
  - 用户明确指定飞书(国内生态)
  - Jira 保留(海外业务)
  - 飞书 interactive card 支持按钮回调,无需二次开发 UI

为什么不用邮件/SMS:
  - 邮件延迟 + 容易进垃圾箱
  - SMS 不能交互(只能 yes/no 不能给 reason)
  - 飞书卡片可一键 approve / reject,记录 reason,带 incident 详情
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

import requests

from CorpAI.platform.sre.approval import (
    ApprovalService,
    AlreadyDecided,
    InsufficientScope,
    PlanNotFound,
    TokenMismatch,
)

logger = logging.getLogger(__name__)


# ─── 配置(每次查 env,支持测试动态切换) ───

def _app_id() -> str:
    return os.environ.get("FEISHU_APP_ID", "")


def _app_secret() -> str:
    return os.environ.get("FEISHU_APP_SECRET", "")


def _verify_token() -> str:
    return os.environ.get("FEISHU_VERIFY_TOKEN", "")


def _encrypt_key() -> str:
    return os.environ.get("FEISHU_ENCRYPT_KEY", "")


# 向后兼容(老代码 import FEISHU_APP_ID 仍可用,语义=模块 load 时的快照)
FEISHU_APP_ID = _app_id()
FEISHU_APP_SECRET = _app_secret()
FEISHU_VERIFY_TOKEN = _verify_token()
FEISHU_ENCRYPT_KEY = _encrypt_key()


def is_configured() -> bool:
    """飞书凭证是否齐 — 没齐时所有发卡/解 callback 都返 not_configured。

    只检查发卡需要的 APP_ID + APP_SECRET。
    FEISHU_VERIFY_TOKEN 是可选的(只在「加密回调」模式下校验;新版事件订阅用
    GET ?challenge= url_verification,不强制带 token,留空不影响)。
    """
    return bool(_app_id() and _app_secret())


# ─── Tenant access token(发卡用) ───

_TENANT_TOKEN_CACHE: dict[str, Any] = {}


def _get_tenant_access_token() -> str | None:
    """取 tenant_access_token(缓存 2h)。

    飞书 Open API:
      POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal
      body: {"app_id": "...", "app_secret": "..."}
      resp: {"tenant_access_token": "...", "expire": 7200}
    """
    if not is_configured():
        return None
    cached = _TENANT_TOKEN_CACHE.get("token")
    if cached and cached["expire_at"] > time.time() + 60:
        return cached["token"]
    try:
        r = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": _app_id(), "app_secret": _app_secret()},
            timeout=10,
        )
        if r.status_code != 200:
            logger.error(f"飞书 tenant_access_token 失败:{r.text[:200]}")
            return None
        data = r.json()
        token = data.get("tenant_access_token")
        expire = data.get("expire", 7200)
        if not token:
            return None
        _TENANT_TOKEN_CACHE["token"] = {
            "token": token, "expire_at": time.time() + expire,
        }
        return token
    except requests.RequestException as exc:
        logger.error(f"飞书 tenant_access_token 网络失败:{exc}")
        return None


# ─── 错误类型 ───

class FeishuError(Exception):
    """飞书 API 业务错误。"""
    pass


class FeishuNotConfigured(FeishuError):
    """凭证缺失。"""
    pass


class FeishuSignatureError(FeishuError):
    """callback 签名校验失败。"""
    pass


# ─── 卡片构造 ───

def build_incident_card(
    incident_id: str,
    service: str,
    severity: str,
    plan_summary: str,
    risk_level: str,
    plan_id: int,
    approval_token: str,
) -> dict[str, Any]:
    """构造飞书 interactive card。

    按钮用 value 字段(而非 url) — 配合「事件订阅 → 卡片回调」
    实现后台审批。点击后飞书 POST 到我们配的回调 URL,body 含
    action.value = {plan_id, token, op}。

    返回 dict,直接 POST 给飞书 /open-apis/im/v1/messages。
    """
    severity_emoji = {
        "critical": "🔴", "error": "🟠",
        "warning": "🟡", "info": "🟢",
    }.get(severity, "⚪")
    risk_emoji = {
        "low": "🟢", "medium": "🟡", "high": "🔴",
    }.get(risk_level, "⚪")

    return {
        "msg_type": "interactive",
        "card": {
            # 飞书 v2 schema — 卡片被 callback 更新必须显式开启
            # config.update_multi: true(否则卡片无法被 PATCH/callback 响应更新)
            "config": {"update_multi": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"{severity_emoji} SRE Incident 修复审批",
                },
                "template": "red" if severity == "critical" else "orange",
            },
            "elements": [
                {
                    "tag": "div",
                    "fields": [
                        {"is_short": True, "text": {
                            "tag": "lark_md",
                            "content": f"**Incident**\n{incident_id}",
                        }},
                        {"is_short": True, "text": {
                            "tag": "lark_md",
                            "content": f"**Service**\n{service}",
                        }},
                        {"is_short": True, "text": {
                            "tag": "lark_md",
                            "content": f"**Severity**\n{severity}",
                        }},
                        {"is_short": True, "text": {
                            "tag": "lark_md",
                            "content": f"**Risk**\n{risk_emoji} {risk_level}",
                        }},
                    ],
                },
                {"tag": "hr"},
                {"tag": "div", "text": {
                    "tag": "lark_md",
                    "content": f"**AI 建议方案**\n{plan_summary}",
                }},
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {"tag": "button", "text": {
                            "tag": "plain_text", "content": "✅ 批准执行",
                        }, "type": "primary",
                           "value": {
                               "plan_id": plan_id,
                               "token": approval_token,
                               "op": "approve",
                           }},
                        {"tag": "button", "text": {
                            "tag": "plain_text", "content": "❌ 拒绝",
                        }, "type": "danger",
                           "value": {
                               "plan_id": plan_id,
                               "token": approval_token,
                               "op": "reject",
                           }},
                    ],
                },
                {"tag": "note", "elements": [{
                    "tag": "plain_text",
                    "content": (
                        "⏱ 30 分钟内未操作视为超时,Incident 将自动 escalated。"
                        "批准/拒绝前请确认 service 当前流量已切走。"
                    ),
                }]},
            ],
        },
    }


# ─── 发卡 ───

def send_approval_card(
    receive_id: str,
    receive_id_type: str,  # "email" | "open_id" | "chat_id"
    incident_id: str,
    service: str,
    severity: str,
    plan_summary: str,
    risk_level: str,
    plan_id: int,
    approval_token: str,
) -> dict[str, Any]:
    """发审批卡给飞书用户/群。

    按钮 value 字段塞 plan_id + token + op,
    飞书事件订阅 POST 到 /feishu/event 时原样回传,
    我们的 handler 据此分发 approve / reject。

    Returns:{status: 'sent' | 'not_configured' | 'error', ...}
    """
    if not is_configured():
        logger.warning("飞书未配置(缺 FEISHU_APP_ID/SECRET/VERIFY_TOKEN),跳过发卡")
        return {"status": "not_configured",
                "required_env": ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_VERIFY_TOKEN"]}

    card = build_incident_card(
        incident_id=incident_id, service=service, severity=severity,
        plan_summary=plan_summary, risk_level=risk_level,
        plan_id=plan_id, approval_token=approval_token,
    )
    token = _get_tenant_access_token()
    if not token:
        return {"status": "error", "kind": "no_token"}
    try:
        # 飞书 API 要求 content 是 JSON 字符串(不是嵌套对象)
        # schema: {receive_id, msg_type, content: "<json string>"}
        content_str = json.dumps(card["card"], ensure_ascii=False)
        r = requests.post(
            "https://open.feishu.cn/open-apis/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={
                "receive_id": receive_id,
                "msg_type": card["msg_type"],
                "content": content_str,
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.error(f"飞书发卡网络失败:{exc}")
        return {"status": "error", "kind": "unreachable"}
    if r.status_code != 200:
        logger.error(f"飞书发卡失败 {r.status_code}:{r.text}")
        return {"status": "error", "kind": f"http{r.status_code}",
                "body": r.text}
    data = r.json()
    if data.get("code", -1) != 0:
        return {"status": "error", "kind": "api_error",
                "code": data.get("code"), "msg": data.get("msg")}
    return {"status": "sent", "message_id": data.get("data", {}).get("message_id")}


# ─── Callback 签名校验 ───

def verify_signature(
    timestamp: str, nonce: str, body: str, signature: str,
) -> bool:
    """校验飞书 callback URL 签名。

    算法:HMAC-SHA256(timestamp + nonce + body, FEISHU_ENCRYPT_KEY),
    飞书把签名放在 X-Lark-Signature header。
    """
    key = _encrypt_key()
    if not key:
        # 没设 key → 不强制校验(开发期方便)
        logger.debug("FEISHU_ENCRYPT_KEY 未设,跳过签名校验")
        return True
    content = f"{timestamp}{nonce}{body}".encode()
    expected = hmac.new(
        key.encode(), content, hashlib.sha256,
    ).digest()
    expected_b64 = base64.b64encode(expected).decode()
    return hmac.compare_digest(expected_b64, signature)


# ─── Callback 处理 ───

def handle_approve_callback(
    plan_id: int, token: str, actor: str, scopes: list[str],
) -> dict[str, Any]:
    """飞书 callback 进来 → 调 ApprovalService.approve。

    actor/scopes 由飞书 user_id + 后端 RBAC 查询注入(这里直接传)。
    """
    try:
        result = ApprovalService().approve(
            plan_id=plan_id, token=token,
            actor=actor, scopes=scopes,
        )
        return {"status": "approved", "plan_id": plan_id, "result": result}
    except (AlreadyDecided,) as exc:
        # v3.2.5:重发 callback(plan 已批过/拒过)→ 不当错误,返 'already_approved'
        logger.info(f"飞书 approve 重复(plan_id={plan_id}):{exc}")
        return {"status": "already_approved", "plan_id": plan_id, "reason": str(exc)}
    except (PlanNotFound, TokenMismatch, InsufficientScope) as exc:
        logger.warning(f"飞书 approve callback 拒绝:{exc}")
        return {"status": "rejected", "reason": str(exc)}


def handle_reject_callback(
    plan_id: int, token: str, actor: str, scopes: list[str], reason: str,
) -> dict[str, Any]:
    try:
        result = ApprovalService().reject(
            plan_id=plan_id, token=token,
            actor=actor, scopes=scopes, reason=reason,
        )
        return {"status": "rejected", "plan_id": plan_id, "result": result}
    except AlreadyDecided as exc:
        logger.info(f"飞书 reject 重复(plan_id={plan_id}):{exc}")
        return {"status": "already_decided", "plan_id": plan_id, "reason": str(exc)}
    except (PlanNotFound, TokenMismatch, InsufficientScope) as exc:
        return {"status": "rejected", "reason": str(exc)}


__all__ = [
    "FeishuError",
    "FeishuNotConfigured",
    "FeishuSignatureError",
    "build_incident_card",
    "handle_approve_callback",
    "handle_reject_callback",
    "is_configured",
    "send_approval_card",
    "verify_signature",
]
