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

logger = logging.getLogger(__name__)

try:
    # Phase SRE.a-h 的 approval 引擎;若模块未到位则降级(测试场景 / 未部署完)
    from CorpAI.platform.sre.approval import (
        ApprovalService,
        AlreadyDecided,
        InsufficientScope,
        PlanNotFound,
        TokenMismatch,
    )
    _APPROVAL_AVAILABLE = True
except ImportError:
    ApprovalService = None  # type: ignore[assignment]
    AlreadyDecided = Exception  # type: ignore[assignment,misc]
    InsufficientScope = Exception  # type: ignore[assignment,misc]
    PlanNotFound = Exception  # type: ignore[assignment,misc]
    TokenMismatch = Exception  # type: ignore[assignment,misc]
    _APPROVAL_AVAILABLE = False
    logger.warning("CorpAI.platform.sre.approval 未加载,飞书审批回调降级处理")


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
            # 飞书 v2 schema — schema 字段是飞书识别新版卡片的标记,
            # 没有 schema 字段的卡 PATCH 更新可能静默失败。
            # config.update_multi: true 让原卡可被多人同步更新。
            # v3.4.3:elements 必须包在 body 里(v2 schema 要求),
            # 不在顶层 — 否则飞书报 'parse card json err: unknown property elements'
            "config": {"update_multi": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"{severity_emoji} SRE Incident 修复审批",
                },
                "template": "red" if severity == "critical" else "orange",
            },
            # v3.4.11:回退到 v1 飞书消息卡片格式 — GET 验证显示飞书 sandbox
# 拒绝 v2 schema 的内容(降级成"请升级客户端" fallback),改成:
#   {config, header, elements: [...]} 顶层平铺(无 body 包裹,无 schema 字段)
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
                    # v3.4.11:用 column_set+column+div(原 v2 多列布局) — 这种 element 在 v1 也支持
                    "tag": "column_set",
                    "flex_mode": "stretch",
                    "columns": [
                        {
                            "tag": "column", "width": "weighted",
                            "elements": [{"tag": "div", "text": {
                                "tag": "lark_md",
                                "content": f"**Incident**\n{incident_id}",
                            }}],
                        },
                        {
                            "tag": "column", "width": "weighted",
                            "elements": [{"tag": "div", "text": {
                                "tag": "lark_md",
                                "content": f"**Service**\n{service}",
                            }}],
                        },
                    ],
                },
                {
                    "tag": "column_set",
                    "flex_mode": "stretch",
                    "columns": [
                        {
                            "tag": "column", "width": "weighted",
                            "elements": [{"tag": "div", "text": {
                                "tag": "lark_md",
                                "content": f"**Severity**\n{severity}",
                            }}],
                        },
                        {
                            "tag": "column", "width": "weighted",
                            "elements": [{"tag": "div", "text": {
                                "tag": "lark_md",
                                "content": f"**Risk**\n{risk_emoji} {risk_level}",
                            }}],
                        },
                    ],
                },
                {"tag": "hr"},
                {"tag": "div", "text": {
                    "tag": "lark_md",
                    "content": f"**AI 建议方案**\n{plan_summary}",
                }},
                {"tag": "hr"},
                {
                    "tag": "column_set",
                    "flex_mode": "stretch",
                    "columns": [
                        {
                            "tag": "column",
                            "width": "weighted",
                            "elements": [
                                {
                                    "tag": "button",
                                    "text": {
                                        "tag": "plain_text",
                                        "content": "✅ 批准执行",
                                    },
                                    "type": "primary",
                                    "value": {
                                        "plan_id": plan_id,
                                        "token": approval_token,
                                        "op": "approve",
                                    },
                                },
                            ],
                        },
                        {
                            "tag": "column",
                            "width": "weighted",
                            "elements": [
                                {
                                    "tag": "button",
                                    "text": {
                                        "tag": "plain_text",
                                        "content": "❌ 拒绝",
                                    },
                                    "type": "danger",
                                    "value": {
                                        "plan_id": plan_id,
                                        "token": approval_token,
                                        "op": "reject",
                                    },
                                },
                            ],
                        },
                    ],
                },
                {"tag": "div", "text": {
                    "tag": "plain_text",
                    "content": (
                        "⏱ 30 分钟内未操作视为超时,Incident 将自动 escalated。"
                        "批准/拒绝前请确认 service 当前流量已切走。"
                    ),
                }},
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
        # v3.4.7:debug — 实际发给飞书的卡片结构(检查有没有 v1 标签残留)
        logger.info(
            f"[SEND] card schema={card['card'].get('schema')!r}"
            f" tags={[e.get('tag') for e in card['card'].get('body', {}).get('elements', [])]}"
        )
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

    安全修复:未配置 FEISHU_ENCRYPT_KEY 时返回 False(fail-closed),
    而非原来的 True(完全跳过校验)。
    调用方(app.py)负责判断是否在开发模式下跳过校验。
    """
    key = _encrypt_key()
    if not key:
        # 没设 key → fail-closed,拒绝请求
        # 调用方应检查 FEISHU_ENCRYPT_KEY 是否配置,并在开发模式下显式跳过
        logger.warning("FEISHU_ENCRYPT_KEY 未设,签名校验失败(fail-closed)")
        return False
    content = f"{timestamp}{nonce}{body}".encode()
    expected = hmac.new(
        key.encode(), content, hashlib.sha256,
    ).digest()
    expected_b64 = base64.b64encode(expected).decode()
    return hmac.compare_digest(expected_b64, signature)


# ─── Callback 处理 ───
def update_message_card(
    message_id: str,
    card: dict,
) -> dict[str, Any]:
    """
    更新飞书 interactive card
    """

    token = _get_tenant_access_token()

    if not token:
        return {
            "status": "error",
            "kind": "no_token",
        }


    try:

        content_str = json.dumps(
            card,
            ensure_ascii=False,
        )


        payload = {
            "content": content_str
        }


        # v3.4.8:确认 PATCH 发的 card 结构对(schema + body.elements)
        logger.info(
            "飞书 PATCH card payload schema=%s tags=%s",
            card.get("schema"),
            [e.get("tag") for e in card.get("body", {}).get("elements", [])],
        )


        r = requests.patch(
            f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )


    except requests.RequestException as exc:

        logger.error(
            f"飞书更新卡片网络失败:{exc}"
        )

        return {
            "status":"error",
            "kind":"network",
        }


    if r.status_code != 200:

        logger.error(
            f"飞书更新卡片失败 {r.status_code}:{r.text}"
        )

        return {
            "status":"error",
            "kind":f"http{r.status_code}",
            "body":r.text,
        }


    data=r.json()


    if data.get("code",0)!=0:

        return {
            "status":"error",
            "kind":"api_error",
            "body":data,
        }

    # v3.4.9:反向验证 PATCH 真的存了 — GET 消息回来看 content
    # 飞书 PATCH API 返 200 updated 但客户端重拉显示原卡,
    # 怀疑 PATCH 实际没写入。GET 验证能区分。
    try:
        verify_r = requests.get(
            f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        verify_data = verify_r.json()
        # 打印完整 response(前 500 字符) — 看清结构
        logger.info(
            f"[PATCH-VERIFY] msg={message_id}"
            f" http_status={verify_r.status_code}"
            f" code={verify_data.get('code')}"
            f" msg={verify_data.get('msg')!r}"
            f" data_keys={list((verify_data.get('data') or {}).keys())}"
            f" full_data={json.dumps(verify_data, ensure_ascii=False)[:500]}"
        )
        verify_items = (verify_data.get("data") or {}).get("items") or []
        if verify_items:
            stored = verify_items[0].get("body", {}).get("content") or "{}"
            try:
                parsed = json.loads(stored)
                elements = (parsed.get("body") or {}).get("elements") or []
                first_text = ""
                for el in elements:
                    if el.get("tag") == "div":
                        first_text = (el.get("text") or {}).get("content", "")[:60]
                        break
                logger.info(
                    f"[PATCH-VERIFY] msg={message_id} server-stored"
                    f" schema={parsed.get('schema')!r}"
                    f" first_div_text={first_text!r}"
                )
            except Exception as pe:
                logger.warning(f"[PATCH-VERIFY] parse stored failed:{pe}")
        else:
            logger.warning(
                f"[PATCH-VERIFY] GET 返空 items,verify_data={verify_data}"
            )
    except Exception as ve:
        logger.warning(f"[PATCH-VERIFY] GET 失败:{ve}")

    return {
        "status":"updated",
        "message_id":message_id,
    }


def build_approved_card(
    incident_id: str,
    service: str,
    severity: str,
    risk_level: str,
    plan_summary: str,
    decision_text: str,
    decision_emoji: str,
) -> dict[str, Any]:
    """构造审批后状态卡(无按钮,锁定状态)。

    跟 build_incident_card 共享字段,但 elements 是 note + 决策行,
    没有 [批准][拒绝] 按钮。
    """
    severity_emoji = {
        "critical": "🔴", "error": "🟠",
        "warning": "🟡", "info": "🟢",
    }.get(severity, "⚪")
    risk_emoji = {
        "low": "🟢", "medium": "🟡", "high": "🔴",
    }.get(risk_level, "⚪")
    return {
        # v3.4.11:v1 飞书消息卡片格式 — 顶层平铺 elements,飞书 sandbox 验证通过
        "config": {"update_multi": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"{decision_emoji} SRE Incident 修复审批",
            },
            "template": "green",
        },
        "elements": [
            {"tag": "div", "fields": [
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
            ]},
            {"tag": "hr"},
            {"tag": "div", "text": {
                "tag": "lark_md",
                "content": f"**AI 建议方案**\n{plan_summary}",
            }},
            {"tag": "hr"},
            {"tag": "div", "text": {
                "tag": "lark_md",
                "content": decision_text,
            }},
            {"tag": "div", "text": {
                "tag": "plain_text",
                "content": "卡片已锁定,不再可操作。如需重新审批,请发起新 plan。",
            }},
        ],
    }


def get_feishu_user_name(open_id: str) -> str:
    """open_id → 用户名(调飞书 contact/v3/users/{open_id})。

    飞书 callback 不直接返中文名,只返 open_id。要展示"张三"得主动查。

    失败 fallback 回 open_id(总是返 str,不抛)。
    """
    if not open_id or not is_configured():
        return open_id
    token = _get_tenant_access_token()
    if not token:
        return open_id
    try:
        r = requests.get(
            f"https://open.feishu.cn/open-apis/contact/v3/users/{open_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"user_id_type": "open_id"},
            timeout=5,
        )
        if r.status_code != 200:
            logger.warning(f"飞书用户查询失败 {r.status_code}:{r.text[:200]}")
            return open_id
        data = r.json()
        if data.get("code", -1) != 0:
            logger.warning(f"飞书用户查询业务错:{data}")
            return open_id
        user = (data.get("data") or {}).get("user") or {}
        return (
            user.get("name")
            or user.get("en_name")
            or open_id
        )
    except Exception as exc:
        logger.warning(f"飞书用户查询异常:{exc}")
        return open_id


def _fetch_plan_for_card_update(plan_id: int) -> dict | None:
    """从 DB 拉 plan 全字段(供 callback 后 PATCH 卡片用)。返 None = plan 不存在。"""
    try:
        from CorpAI.platform.db import DatabasePool
        pool = DatabasePool.get()
        conn = pool.get_conn()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                "SELECT ap.id, ap.message_id, ap.plan_json, ap.risk_level, "
                "  ap.status, ap.approved_by, ap.approved_at, "
                "  i.incident_id, i.service, i.severity "
                "FROM sre_action_plans ap "
                "LEFT JOIN sre_incidents i ON ap.incident_id = i.incident_id "
                "WHERE ap.id = %s",
                (plan_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            # 从 plan_json 拿 AI 建议给卡片用
            summary = ""
            try:
                import json as _json
                pj = _json.loads(row.get("plan_json") or "{}")
                if isinstance(pj.get("actions"), list) and pj["actions"]:
                    summary = (
                        f"执行 {len(pj['actions'])} 个动作:" +
                        "; ".join(a.get("tool", "?") for a in pj["actions"])
                    )
                elif pj.get("summary"):
                    summary = pj["summary"]
            except Exception:
                summary = "(plan 解析失败)"
            return {
                "plan_id": row["id"],
                "message_id": row["message_id"],
                "risk_level": row["risk_level"] or "medium",
                "incident_id": row["incident_id"] or "?",
                "service": row["service"] or "?",
                "severity": row["severity"] or "info",
                "plan_summary": summary,
                "approved_by": row.get("approved_by") or "",
                "approved_at": row.get("approved_at"),
            }
        finally:
            conn.close()
    except Exception as exc:
        logger.error(f"拉 plan={plan_id} 失败:{exc}")
        return None


def _patch_card_after_decision(
    plan_id: int,
    decision_emoji: str,
    decision_text: str,
) -> None:
    """approve / reject 成功后 PATCH 飞书卡片。失败只记 WARNING,不抛。"""
    logger.info(f"[PATCH-1] enter plan_id={plan_id} emoji={decision_emoji}")

    plan = _fetch_plan_for_card_update(plan_id)

    if not plan:
        logger.warning(f"[PATCH-2] plan 不存在 plan_id={plan_id}")
        return
    if not plan.get("message_id"):
        logger.warning(
            f"[PATCH-2] plan 没有 message_id — bootstrap 写真失败?"
            f"plan_id={plan_id} msg_id={plan.get('message_id')!r}"
        )
        return

    msg_id = plan["message_id"]
    logger.info(f"[PATCH-3] start plan_id={plan_id} msg_id={msg_id}")

    new_card = build_approved_card(
        incident_id=plan["incident_id"],
        service=plan["service"],
        severity=plan["severity"],
        risk_level=plan["risk_level"],
        plan_summary=plan["plan_summary"],
        decision_text=decision_text,
        decision_emoji=decision_emoji,
    )
    # v3.4.2 debug:确认卡片是 v2 schema(None = 飞书可能不更新)
    logger.info(
        f"[PATCH-3.5] card.schema={new_card.get('schema')!r}"
        f" header_keys={list(new_card.get('header', {}).keys())}"
        f" elements_count={len(new_card.get('elements', []))}"
    )

    patch_result = update_message_card(msg_id, new_card)

    logger.info(
        f"[PATCH-4] result plan_id={plan_id} status={patch_result.get('status')}"
        f" body={str(patch_result)[:200]}"
    )

    if patch_result.get("status") != "updated":
        logger.warning(
            f"飞书卡片 PATCH 失败(plan_id={plan_id}, msg_id={msg_id}):"
            f"{patch_result}"
        )


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
        # v3.3:成功后 PATCH 飞书卡片(按钮换成"✅ 已批准")
        decision_text = f"✅ 已批准\n操作人:{actor}\n时间:{result.get('approved_at') or '刚刚'}"
        _patch_card_after_decision(plan_id, "✅", decision_text)
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
        # v3.3:成功后 PATCH 飞书卡片(按钮换成"❌ 已拒绝")
        decision_text = f"❌ 已拒绝\n操作人:{actor}\n理由:{reason or '无'}"
        _patch_card_after_decision(plan_id, "❌", decision_text)
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
