"""hr_assistant 操作类工具 — v2.0 真写 MySQL + RBAC + 状态机 + 审计。

复用 src/hr_assistant/tools.py 已有 KB 数据(82 条);这文件只做"操作类"。

设计原则:
- 每个操作都接受 authorization: str(Bearer JWT),入口调用 _check_scope 二次校验
- user_id 强制从 token 拿(不接受 user_id 作入参)— 防越权
- 状态机:pending → approved/rejected/cancelled
- 每次操作写 hr_audit_log(含 trace_id)
- DB 错误不吞,logger.warning + raise
- 失败路径补 HR_ACTION_TOTAL{status=error/forbidden} counter
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# 平台复用
from CorpAI.platform.db import DatabasePool
from CorpAI.platform.observability.metrics import HR_ACTION_TOTAL, HR_BRIDGE_ERRORS_TOTAL
from CorpAI.platform.observability.trace import current_trace_id, new_trace_id

# ────────────────── RBAC 校验(照搬 sre_copilot/tools.py:_check_sre_write)────────

def _check_scope(authorization: str | None, needed: str) -> dict:
    """校验 Bearer JWT 含 needed scope。返回 claims dict。

    Raises:
        PermissionError: 缺 token / token 无效 / scope 不足
    """
    if not authorization or not authorization.startswith("Bearer "):
        HR_ACTION_TOTAL.labels(action="auth", status="forbidden").inc()
        raise PermissionError(f"需要 Bearer token (scope={needed})")
    try:
        from CorpAI.platform.auth.dependencies import get_jwt_secret
        from CorpAI.platform.auth.scopes import has_scope
        from CorpAI.platform.auth.tokens import jwt_decode
        claims = jwt_decode(authorization[len("Bearer "):], get_jwt_secret())
    except Exception as e:
        HR_ACTION_TOTAL.labels(action="auth", status="error").inc()
        raise PermissionError(f"token 解析失败: {e}") from e
    if not claims:
        HR_ACTION_TOTAL.labels(action="auth", status="forbidden").inc()
        raise PermissionError("token 无效或已过期")
    if not has_scope(needed, claims.get("scopes", [])):
        HR_ACTION_TOTAL.labels(action="auth", status="forbidden").inc()
        raise PermissionError(f"需要 scope {needed},实有 {claims.get('scopes', [])}")
    return claims


def _current_user(authorization: str | None) -> str:
    """从 token 拿 user_id。"""
    claims = _check_scope(authorization, "chat:write")
    return claims.get("user_id", "")


# ────────────────── 单号生成 + 审计 ──────────────────

def _gen_request_id(prefix: str) -> str:
    """生成 L20260808-001 单号(prefix + 日期 + 毫秒级序号,防 e2e 重复)。"""
    now = datetime.now()
    today = now.strftime("%Y%m%d")
    # 用毫秒级时间戳后 3 位做序号(并发场景仍然可能撞,生产应 MAX(id)+1)
    seq = now.microsecond // 1000
    return f"{prefix}{today}-{seq:03d}"


def _write_audit(cur, user_id: str, action: str, entity_type: str,
                 entity_id: str, detail: str = "") -> None:
    """写 hr_audit_log。失败不 raise(审计失败不阻塞业务,CLAUDE.md 约定写法)。"""
    try:
        cur.execute(
            """INSERT INTO hr_audit_log
               (request_id, user_id, action, entity_type, entity_id, detail, trace_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (entity_id, user_id, action, entity_type, entity_id,
             detail[:1000], current_trace_id() or new_trace_id()),
        )
    except Exception as e:
        logger.warning(f"hr_audit_log write failed (action={action}, entity={entity_id}): {e}")


def _ok(action: str, data: dict, message: str = "") -> str:
    HR_ACTION_TOTAL.labels(action=action, status="ok").inc()
    return json.dumps({"status": "success", "data": data, "message": message}, ensure_ascii=False)


def _err(action: str, status: str, message: str) -> str:
    HR_ACTION_TOTAL.labels(action=action, status=status).inc()
    return json.dumps({"status": status, "data": None, "message": message}, ensure_ascii=False)


# ────────────────── 8 个操作类工具 ──────────────────

def submit_leave(
    authorization: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    days: float,
    reason: str,
) -> str:
    """提交请假申请。员工自填,user_id 从 token 强制提取。

    Args:
        leave_type: annual / sick / personal / marriage / maternity / bereavement / compensatory
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
        days: 0.5 / 1.0 / 2.5 ...
        reason: 请假事由
    """
    action = "submit_leave"
    try:
        user_id = _current_user(authorization)
        if leave_type not in {"annual", "sick", "personal", "marriage",
                              "maternity", "bereavement", "compensatory"}:
            return _err(action, "invalid", f"leave_type 非法:{leave_type}")
        if not reason or len(reason) > 512:
            return _err(action, "invalid", "reason 必填且 ≤ 512 字符")

        conn = DatabasePool.get().get_conn()
        try:
            cur = conn.cursor()
            req_id = _gen_request_id("L")
            cur.execute(
                """INSERT INTO hr_leave_requests
                   (request_id, user_id, leave_type, start_date, end_date,
                    days, reason, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')""",
                (req_id, user_id, leave_type, start_date, end_date, days, reason),
            )
            _write_audit(cur, user_id, action, "leave", req_id,
                         f"{leave_type} {start_date}~{end_date} {days}天")
            conn.commit()
            cur.close()
        finally:
            conn.close()
        return _ok(action, {"request_id": req_id, "status": "pending",
                            "leave_type": leave_type, "days": days},
                   f"请假申请 {req_id} 已提交,等待 HR 审批")
    except PermissionError as e:
        return _err(action, "forbidden", str(e))
    except Exception as e:
        logger.warning(f"submit_leave failed: {e}")
        return _err(action, "error", f"提交失败: {e}")


def cancel_leave(authorization: str, request_id: str) -> str:
    """取消请假申请。仅 pending 状态可取消,user_id 必须匹配。"""
    action = "cancel_leave"
    try:
        user_id = _current_user(authorization)
        conn = DatabasePool.get().get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """UPDATE hr_leave_requests SET status = 'cancelled'
                   WHERE request_id = %s AND user_id = %s AND status = 'pending'""",
                (request_id, user_id),
            )
            if cur.rowcount == 0:
                cur.close()
                return _err(action, "not_found",
                            f"找不到 pending 状态的 {request_id} 或不属于你")
            _write_audit(cur, user_id, action, "leave", request_id, "user cancel")
            conn.commit()
            cur.close()
        finally:
            conn.close()
        return _ok(action, {"request_id": request_id, "status": "cancelled"},
                   f"请假 {request_id} 已撤销")
    except PermissionError as e:
        return _err(action, "forbidden", str(e))
    except Exception as e:
        logger.warning(f"cancel_leave failed: {e}")
        return _err(action, "error", str(e))


def submit_reimbursement(
    authorization: str,
    category: str,
    amount: float,
    description: str,
    currency: str = "CNY",
    invoice_url: str | None = None,
) -> str:
    """提交报销申请。"""
    action = "submit_reimbursement"
    try:
        user_id = _current_user(authorization)
        if category not in {"travel", "office", "training", "meal", "other"}:
            return _err(action, "invalid", f"category 非法:{category}")
        if amount <= 0 or amount > 100000:
            return _err(action, "invalid", "amount 必须在 (0, 100000]")

        conn = DatabasePool.get().get_conn()
        try:
            cur = conn.cursor()
            req_id = _gen_request_id("R")
            cur.execute(
                """INSERT INTO hr_reimbursements
                   (request_id, user_id, category, amount, currency,
                    description, invoice_url, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')""",
                (req_id, user_id, category, amount, currency, description, invoice_url),
            )
            _write_audit(cur, user_id, action, "reimbursement", req_id,
                         f"{category} {amount} {currency}")
            conn.commit()
            cur.close()
        finally:
            conn.close()
        return _ok(action, {"request_id": req_id, "status": "pending",
                            "amount": amount, "category": category},
                   f"报销 {req_id} 已提交 {amount} {currency}")
    except PermissionError as e:
        return _err(action, "forbidden", str(e))
    except Exception as e:
        logger.warning(f"submit_reimbursement failed: {e}")
        return _err(action, "error", str(e))


def apply_certificate(
    authorization: str,
    cert_type: str,
    purpose: str,
    language: str = "zh",
    quantity: int = 1,
    deliver_method: str = "email",
    delivery_addr: str | None = None,
) -> str:
    """申请证明(在职/收入/离职/工作居住证)。"""
    action = "apply_certificate"
    try:
        user_id = _current_user(authorization)
        if cert_type not in {"employment", "income", "separation", "work_permit"}:
            return _err(action, "invalid", f"cert_type 非法:{cert_type}")
        if deliver_method not in {"email", "pickup", "mail"}:
            return _err(action, "invalid", f"deliver_method 非法:{deliver_method}")

        conn = DatabasePool.get().get_conn()
        try:
            cur = conn.cursor()
            req_id = _gen_request_id("C")
            cur.execute(
                """INSERT INTO hr_certificates
                   (request_id, user_id, cert_type, purpose, language,
                    quantity, deliver_method, delivery_addr, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')""",
                (req_id, user_id, cert_type, purpose, language,
                 quantity, deliver_method, delivery_addr),
            )
            _write_audit(cur, user_id, action, "certificate", req_id,
                         f"{cert_type} x{quantity} {deliver_method}")
            conn.commit()
            cur.close()
        finally:
            conn.close()
        return _ok(action, {"request_id": req_id, "status": "pending",
                            "cert_type": cert_type, "quantity": quantity},
                   f"证明 {req_id} 已申请,预计 5 工作日内出具")
    except PermissionError as e:
        return _err(action, "forbidden", str(e))
    except Exception as e:
        logger.warning(f"apply_certificate failed: {e}")
        return _err(action, "error", str(e))


def request_asset(
    authorization: str,
    asset_type: str,
    reason: str,
    sku: str | None = None,
    estimated_cost: float | None = None,
) -> str:
    """申请资产(笔记本/显示器/键盘/耳机/手机/其他)。"""
    action = "request_asset"
    try:
        user_id = _current_user(authorization)
        if asset_type not in {"laptop", "monitor", "keyboard", "mouse", "headset", "phone", "other"}:
            return _err(action, "invalid", f"asset_type 非法:{asset_type}")

        conn = DatabasePool.get().get_conn()
        try:
            cur = conn.cursor()
            req_id = _gen_request_id("A")
            cur.execute(
                """INSERT INTO hr_asset_requests
                   (request_id, user_id, asset_type, sku, reason,
                    estimated_cost, status)
                   VALUES (%s, %s, %s, %s, %s, %s, 'pending')""",
                (req_id, user_id, asset_type, sku, reason, estimated_cost),
            )
            _write_audit(cur, user_id, action, "asset", req_id,
                         f"{asset_type} {sku or ''} cost={estimated_cost}")
            conn.commit()
            cur.close()
        finally:
            conn.close()
        return _ok(action, {"request_id": req_id, "status": "pending",
                            "asset_type": asset_type, "estimated_cost": estimated_cost},
                   f"资产 {req_id} 已申请,IT 审批中")
    except PermissionError as e:
        return _err(action, "forbidden", str(e))
    except Exception as e:
        logger.warning(f"request_asset failed: {e}")
        return _err(action, "error", str(e))


def register_training(
    authorization: str,
    training_name: str,
    training_type: str,
    business_relevance: str,
    provider: str | None = None,
    expected_cost: float | None = None,
    expected_date: str | None = None,
) -> str:
    """报名培训(外部/内部/认证)。"""
    action = "register_training"
    try:
        user_id = _current_user(authorization)
        if training_type not in {"external", "internal", "certification"}:
            return _err(action, "invalid", f"training_type 非法:{training_type}")

        conn = DatabasePool.get().get_conn()
        try:
            cur = conn.cursor()
            req_id = _gen_request_id("T")
            cur.execute(
                """INSERT INTO hr_training_registrations
                   (request_id, user_id, training_name, training_type, provider,
                    expected_cost, expected_date, business_relevance, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')""",
                (req_id, user_id, training_name, training_type, provider,
                 expected_cost, expected_date, business_relevance),
            )
            _write_audit(cur, user_id, action, "training", req_id,
                         f"{training_type} {training_name}")
            conn.commit()
            cur.close()
        finally:
            conn.close()
        return _ok(action, {"request_id": req_id, "status": "pending",
                            "training_name": training_name},
                   f"培训 {req_id} 报名已提交,等待审批")
    except PermissionError as e:
        return _err(action, "forbidden", str(e))
    except Exception as e:
        logger.warning(f"register_training failed: {e}")
        return _err(action, "error", str(e))


def apply_regularization(
    authorization: str,
    probation_start: str,
    probation_end: str,
    achievements: str,
    self_assessment: str | None = None,
) -> str:
    """申请转正。achievements 必填,self_assessment 可选。"""
    action = "apply_regularization"
    try:
        user_id = _current_user(authorization)
        if not achievements or len(achievements) > 4000:
            return _err(action, "invalid", "achievements 必填且 ≤ 4000 字符")

        conn = DatabasePool.get().get_conn()
        try:
            cur = conn.cursor()
            req_id = _gen_request_id("P")
            cur.execute(
                """INSERT INTO hr_regularization
                   (request_id, user_id, probation_start, probation_end,
                    achievements, self_assessment, status)
                   VALUES (%s, %s, %s, %s, %s, %s, 'pending')""",
                (req_id, user_id, probation_start, probation_end,
                 achievements, self_assessment),
            )
            _write_audit(cur, user_id, action, "regularization", req_id,
                         f"{probation_start}~{probation_end}")
            conn.commit()
            cur.close()
        finally:
            conn.close()
        return _ok(action, {"request_id": req_id, "status": "pending"},
                   f"转正 {req_id} 已申请,等待答辩安排")
    except PermissionError as e:
        return _err(action, "forbidden", str(e))
    except Exception as e:
        logger.warning(f"apply_regularization failed: {e}")
        return _err(action, "error", str(e))


def approve_request(
    authorization: str,
    request_id: str,
    target_type: str,
    action: str,
    approval_note: str | None = None,
) -> str:
    """审批通用接口。HR 视角(需 hr:write scope),能审批任意用户的 request。

    Args:
        target_type: leave / reimbursement / certificate / asset / training / regularization
        action: approve / reject
        approval_note: 驳回时必填
    """
    op = "approve_request"
    try:
        approver_id = _check_scope(authorization, "hr:write").get("user_id", "")
        if target_type not in {"leave", "reimbursement", "certificate", "asset",
                               "training", "regularization"}:
            return _err(op, "invalid", f"target_type 非法:{target_type}")
        if action not in {"approve", "reject"}:
            return _err(op, "invalid", f"action 非法:{action}")
        if action == "reject" and not approval_note:
            return _err(op, "invalid", "驳回必须填 approval_note")

        table_map = {
            "leave": "hr_leave_requests",
            "reimbursement": "hr_reimbursements",
            "certificate": "hr_certificates",
            "asset": "hr_asset_requests",
            "training": "hr_training_registrations",
            "regularization": "hr_regularization",
        }
        table = table_map[target_type]
        new_status = "approved" if action == "approve" else "rejected"

        conn = DatabasePool.get().get_conn()
        try:
            cur = conn.cursor()
            sql = f"""UPDATE {table} SET status = %s, approver_id = %s,
                       approval_note = %s
                       WHERE request_id = %s AND status = 'pending'"""
            cur.execute(sql, (new_status, approver_id, approval_note, request_id))
            if cur.rowcount == 0:
                cur.close()
                return _err(op, "not_found",
                            f"找不到 pending 状态的 {request_id} 或已审批")
            _write_audit(cur, approver_id, f"{action}_{target_type}", target_type,
                         request_id, approval_note or "")
            conn.commit()
            cur.close()
        finally:
            conn.close()
        return _ok(op, {"request_id": request_id, "status": new_status,
                        "approver_id": approver_id},
                   f"{request_id} 已{new_status}")
    except PermissionError as e:
        return _err(op, "forbidden", str(e))
    except Exception as e:
        logger.warning(f"approve_request failed: {e}")
        return _err(op, "error", str(e))


def query_my_requests(
    authorization: str,
    target_type: str | None = None,
    status: str | None = None,
    limit: int = 10,
) -> str:
    """查"我的"申请(员工只能查自己的)。HR 视角查所有人需用权限路径(暂未实现)。"""
    action = "query_my_requests"
    try:
        user_id = _current_user(authorization)
        table_map = {
            "leave": "hr_leave_requests",
            "reimbursement": "hr_reimbursements",
            "certificate": "hr_certificates",
            "asset": "hr_asset_requests",
            "training": "hr_training_registrations",
            "regularization": "hr_regularization",
        }
        types = [target_type] if target_type else list(table_map.keys())
        conn = DatabasePool.get().get_conn()
        try:
            cur = conn.cursor(dictionary=True)
            results: list[dict] = []
            for t in types:
                tname = table_map[t]
                sql = f"SELECT * FROM {tname} WHERE user_id = %s"
                params: list[Any] = [user_id]
                if status:
                    sql += " AND status = %s"
                    params.append(status)
                sql += " ORDER BY created_at DESC LIMIT %s"
                params.append(limit)
                cur.execute(sql, tuple(params))
                for row in cur.fetchall():
                    row["entity_type"] = t
                    for k, v in list(row.items()):
                        if hasattr(v, "isoformat"):
                            row[k] = v.isoformat()
                        elif hasattr(v, "__float__"):  # Decimal → float(JSON 序列化)
                            try:
                                row[k] = float(v)
                            except (TypeError, ValueError):
                                pass
                    results.append(row)
            cur.close()
        finally:
            conn.close()
        # 按 created_at 排序合并
        results.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return _ok(action, {"total": len(results), "items": results[:limit]},
                   f"查到 {len(results)} 条" if results else "暂无申请记录")
    except PermissionError as e:
        return _err(action, "forbidden", str(e))
    except Exception as e:
        logger.warning(f"query_my_requests failed: {e}")
        return _err(action, "error", str(e))


# ════════════════════════════════════════════════════════════════
#  3 个跨插件 bridge 工具(task #124)
# ════════════════════════════════════════════════════════════════

import requests

_FAQ_URL = os.getenv("FAQ_URL", "http://localhost:8030")
# v3.1 backward compat:同时读 SRE_* 新名 和 DEVOPS_* 旧名,后者优先(SRE_* 没配就用旧)
_SRE_INCIDENT_URL = (
    os.getenv("SRE_INCIDENT_URL")
    or os.getenv("DEVOPS_INCIDENT_URL")
    or "http://localhost:8020"
)
_SRE_K8S_URL = (
    os.getenv("SRE_K8S_URL")
    or os.getenv("DEVOPS_K8S_URL")
    or "http://localhost:8021"
)
_BRIDGE_TIMEOUT = 2.0  # 秒,跨插件 bridge 严格控时


def _bridge_call(target: str, url: str, tool_name: str, **kwargs) -> dict:
    """跨插件 HTTP 调用。v3.0:失败时显式返 `bridge_unavailable` 状态(绝不 silent)。

    返回:
      - 成功:{...} 原始 dict
      - 失败:{"status": "bridge_unavailable", "kind": "timeout|unreachable|..."}
    """
    try:
        resp = requests.post(
            f"{url}/mcp/tools/{tool_name}",
            json=kwargs,
            timeout=_BRIDGE_TIMEOUT,
        )
    except requests.Timeout:
        HR_BRIDGE_ERRORS_TOTAL.labels(target=target, kind="timeout").inc()
        return {
            "status": "bridge_unavailable",
            "kind": "timeout",
            "message": f"bridge {target} {tool_name} 超时({_BRIDGE_TIMEOUT}s)",
        }
    except requests.ConnectionError as exc:
        HR_BRIDGE_ERRORS_TOTAL.labels(target=target, kind="unreachable").inc()
        return {
            "status": "bridge_unavailable",
            "kind": "unreachable",
            "message": f"bridge {target} 不可达 ({url});{exc.__class__.__name__}",
        }
    except Exception as e:
        HR_BRIDGE_ERRORS_TOTAL.labels(target=target, kind="error").inc()
        logger.warning(f"bridge {target} {tool_name} {e}")
        return {
            "status": "bridge_unavailable",
            "kind": "error",
            "message": f"bridge {target} 异常:{e}",
        }

    if resp.status_code != 200:
        kind = f"http{resp.status_code}"
        HR_BRIDGE_ERRORS_TOTAL.labels(target=target, kind=kind).inc()
        return {
            "status": "bridge_unavailable",
            "kind": kind,
            "message": f"bridge {target} HTTP {resp.status_code};{resp.text[:200]}",
        }

    try:
        return resp.json()
    except Exception as exc:
        HR_BRIDGE_ERRORS_TOTAL.labels(target=target, kind="json_decode").inc()
        return {
            "status": "bridge_unavailable",
            "kind": "json_decode",
            "message": f"bridge {target} 返非 JSON:{exc}",
        }


def cross_query_faq(authorization: str, query: str, top_k: int = 2) -> str:
    """跨插件:调 faq mcp 拿语义检索结果(兜底补全)。

    适用:hr KB 不覆盖时,自动用 faq 共同回答。
    失败:v3.0 显式返 bridge_unavailable(不再 silent-fail)。
    """
    action = "cross_query_faq"
    try:
        _current_user(authorization)  # 校验起码 chat:write
        result = _bridge_call("faq", _FAQ_URL, "query_faq",
                              query_text=query, limit=top_k)
        if result.get("status") == "bridge_unavailable":
            # v3.0:不再 silent,显式告诉用户 bridge 失败 + kind
            return _ok(action, {
                "hits": [],
                "bridge_status": "bridge_unavailable",
                "kind": result.get("kind"),
                "message": result.get("message"),
            }, "faq 兜底 bridge 失败,仅本插件结果")
        if result.get("status") == "no_data":
            return _ok(action, {"hits": [], "hint": "faq 兜底未命中"},
                       "faq 兜底未命中,仅本插件结果")
        hits = result.get("data", [])
        return _ok(action, {"hits": hits, "count": len(hits)},
                   f"faq 兜底返回 {len(hits)} 条")
    except PermissionError as e:
        return _err(action, "forbidden", str(e))
    except Exception as e:
        HR_BRIDGE_ERRORS_TOTAL.labels(target="faq", kind="error").inc()
        return _err(action, "error", str(e))


def cross_check_sre(authorization: str, asset_type: str, reason: str) -> str:
    """跨插件:请求资产前,先查 SRE 工单看是否已有相关请求(去重)。

    适用:request_asset 提交前,避免重复申请。
    v3.0:失败显式告诉用户 bridge 状态(不再 silent)。
    """
    action = "cross_check_sre"
    try:
        _current_user(authorization)
        result = _bridge_call("sre", _SRE_INCIDENT_URL, "query_incident",
                              limit=5)
        if result.get("status") == "bridge_unavailable":
            # v3.0:告诉用户 bridge 失败,让用户决定是否继续
            return _ok(action, {
                "duplicate": False,
                "bridge_status": "bridge_unavailable",
                "kind": result.get("kind"),
                "message": result.get("message"),
            }, "SRE bridge 失败,未做去重检查(继续 process request_asset 由用户决定)")
        items = result.get("data", [])
        for it in items:
            title = it.get("title", "")
            if it.get("status") in ("open", "in_progress") and any(
                kw in title for kw in reason.split() if len(kw) >= 2
            ):
                return _ok(action, {"duplicate": True,
                                    "existing": {"id": it["id"], "title": title,
                                                 "status": it["status"]}},
                           f"已有相似工单 {it['id']}:{title}")
        return _ok(action, {"duplicate": False}, "未发现重复工单")
    except PermissionError as e:
        return _err(action, "forbidden", str(e))
    except Exception as e:
        HR_BRIDGE_ERRORS_TOTAL.labels(target="sre", kind="error").inc()
        return _err(action, "error", str(e))


def cross_notify_sre(authorization: str, request_id: str, target_type: str) -> str:
    """跨插件:HR 审批后,查 SRE oncall 联系方式(返给真人去发通知)。

    本工具**不**真发通知 — 仅返 oncall 邮箱/电话,真人接管(IM/邮件)。
    """
    action = "cross_notify_sre"
    try:
        claims = _check_scope(authorization, "hr:write")
        result = _bridge_call("sre", _SRE_K8S_URL, "query_oncall",
                              team="platform")
        if result.get("status") == "bridge_unavailable":
            return _err(action, "bridge_unavailable",
                       f"SRE 不可达:{result.get('message')}")
        return _ok(action, {
            "request_id": request_id,
            "target_type": target_type,
            "approver_id": claims.get("user_id"),
            "oncall": result.get("data", {}),
        }, "已查询 oncall,请真人发通知")
    except PermissionError as e:
        return _err(action, "forbidden", str(e))
    except Exception as e:
        HR_BRIDGE_ERRORS_TOTAL.labels(target="sre", kind="error").inc()
        return _err(action, "error", str(e))
