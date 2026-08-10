"""sre_copilot 跨插件 bridge 工具 v3.0 — 显式失败,绝不 silent-fail。

设计(v3.0 改造):
- bridge 失败时显式返回 `{"status": "bridge_unavailable", "kind": "timeout|unreachable|http5xx|error", "message": "..."}`
- 绝不吞错(对照 CLAUDE.md "不要 silent-fail DB 写入")
- 仍用 HR_BRIDGE_ERRORS_TOTAL Counter 累加(target=hr|faq, kind=具体失败类型)
- timeout 严格 2s(防 hang 主流程)
- 目标 URL 走 env: HR_URL(默认 http://localhost:5010)、FAQ_URL(默认 http://localhost:8030)
"""
from __future__ import annotations

import json
import logging
import os

import requests

logger = logging.getLogger(__name__)

from CorpAI.platform.observability.metrics import HR_BRIDGE_ERRORS_TOTAL  # 复用

_HR_URL = os.getenv("HR_URL", "http://localhost:5010")
_FAQ_URL = os.getenv("FAQ_URL", "http://localhost:8030")
_BRIDGE_TIMEOUT = 2.0


def _bridge_call(target: str, url: str, tool_name: str, **kwargs) -> dict:
    """跨插件桥接调用。

    返回:
      - 成功:{...} 原始 dict
      - 失败:{"status": "bridge_unavailable", "kind": "...",
              "message": "..."} (绝不返回 None,显式告知)
    """
    try:
        resp = requests.post(
            f"{url}/mcp/tools/{tool_name}",
            json=kwargs, timeout=_BRIDGE_TIMEOUT,
        )
    except requests.Timeout:
        HR_BRIDGE_ERRORS_TOTAL.labels(target=target, kind="timeout").inc()
        return {
            "status": "bridge_unavailable",
            "kind": "timeout",
            "message": (f"bridge {target} {tool_name} 超时({_BRIDGE_TIMEOUT}s);"
                       f"检查 {url} 是否可达"),
        }
    except requests.ConnectionError as exc:
        HR_BRIDGE_ERRORS_TOTAL.labels(target=target, kind="unreachable").inc()
        return {
            "status": "bridge_unavailable",
            "kind": "unreachable",
            "message": f"bridge {target} 不可达 ({url});{exc.__class__.__name__}",
        }
    except Exception as exc:
        HR_BRIDGE_ERRORS_TOTAL.labels(target=target, kind="error").inc()
        logger.warning(f"bridge {target} {tool_name} 未知异常:{exc}")
        return {
            "status": "bridge_unavailable",
            "kind": "error",
            "message": f"bridge {target} 异常:{exc}",
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


def cross_check_hr(authorization: str, request_id: str) -> str:
    """跨插件:hr 申请触发时,查 hr 找关联申请。

    适用:用户请假触发 devops oncall 备份。

    返回:
      - {"status": "success", "data": {...}}
      - {"status": "bridge_unavailable", "kind": "...", "message": "..."}
    """
    result = _bridge_call("hr", _HR_URL, "query_my_requests",
                          authorization=authorization, request_id=request_id)

    # 失败:显式告知(绝不 silent)
    if result.get("status") == "bridge_unavailable":
        return json.dumps({
            "status": "bridge_unavailable",
            "kind": result.get("kind"),
            "message": result.get("message"),
            "request_id": request_id,
        }, ensure_ascii=False)

    # 成功:包装
    return json.dumps({
        "status": "success",
        "data": {"request_id": request_id, "hr_check": result.get("data", {})},
        "message": "hr 联动查询成功",
    }, ensure_ascii=False)


def cross_query_faq(query: str, top_k: int = 2) -> str:
    """跨插件:faq 兜底补全 — devops KB 不全时用 faq 补。

    适用:用户问"为什么我的服务挂了",devops 兜底查 faq 看有没有 SOP。

    返回:
      - {"status": "success", "data": [...]}
      - {"status": "bridge_unavailable", "kind": "...", "message": "..."}
      - {"status": "no_data", "data": [], "message": "faq 未命中"}
    """
    result = _bridge_call("faq", _FAQ_URL, "query_faq",
                          query_text=query, limit=top_k)

    if result.get("status") == "bridge_unavailable":
        return json.dumps({
            "status": "bridge_unavailable",
            "kind": result.get("kind"),
            "message": result.get("message"),
            "query": query,
        }, ensure_ascii=False)

    # faq 返回 no_data:返 no_data,不算失败
    if result.get("status") == "no_data":
        return json.dumps({
            "status": "no_data",
            "data": [],
            "message": "faq 未命中",
            "query": query,
        }, ensure_ascii=False)

    # 成功
    return json.dumps({
        "status": "success",
        "data": result.get("data", []),
        "count": len(result.get("data", [])),
        "query": query,
    }, ensure_ascii=False)
