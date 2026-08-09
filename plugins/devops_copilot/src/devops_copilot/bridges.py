"""devops_copilot 跨插件 bridge 工具 v3.0 — 跨 hr / faq 联动。

设计:
- 失败静默降级 + Counter 增(参考 hr_assistant/actions.py:_bridge_call 模式)
- timeout 严格 2s
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

from CorpAI.platform.observability.metrics import HR_BRIDGE_ERRORS_TOTAL  # 复用

_HR_URL = os.getenv("HR_URL", "http://localhost:5010")
_FAQ_URL = os.getenv("FAQ_URL", "http://localhost:8030")
_BRIDGE_TIMEOUT = 2.0


def _bridge_call(target: str, url: str, tool_name: str, **kwargs) -> Optional[dict]:
    try:
        resp = requests.post(
            f"{url}/mcp/tools/{tool_name}",
            json=kwargs, timeout=_BRIDGE_TIMEOUT,
        )
        if resp.status_code != 200:
            HR_BRIDGE_ERRORS_TOTAL.labels(target=target, kind=f"http{resp.status_code}").inc()
            logger.warning(f"devops bridge {target} {tool_name} HTTP {resp.status_code}")
            return None
        return resp.json()
    except requests.Timeout:
        HR_BRIDGE_ERRORS_TOTAL.labels(target=target, kind="timeout").inc()
        return None
    except requests.ConnectionError:
        HR_BRIDGE_ERRORS_TOTAL.labels(target=target, kind="unreachable").inc()
        return None
    except Exception as e:
        HR_BRIDGE_ERRORS_TOTAL.labels(target=target, kind="error").inc()
        logger.warning(f"devops bridge {target} {tool_name} {e}")
        return None


def cross_check_hr(authorization: str, request_id: str) -> str:
    """跨插件:hr 申请触发时,查 devops 找关联事故(如 oncall 假)。

    适用:用户请假触发 devops oncall 备份。
    """
    try:
        _check = _bridge_call("hr", _HR_URL, "query_my_requests",
                              request_id=request_id)
        # 即使 hr 不可达也返降级
        if not _check:
            return json.dumps({"status": "fallback", "data": {"request_id": request_id},
                               "message": "hr 不可达,跳过 hr 联动检查"}, ensure_ascii=False)
        return json.dumps({"status": "success", "data": {
            "request_id": request_id,
            "hr_check": _check.get("data", {}),
        }, "message": "hr 联动查询成功"}, ensure_ascii=False)
    except Exception as e:
        HR_BRIDGE_ERRORS_TOTAL.labels(target="hr", kind="error").inc()
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def cross_query_faq(query: str, top_k: int = 2) -> str:
    """跨插件:faq 兜底补全 — devops KB 不全时用 faq 补。

    适用:用户问"为什么我的服务挂了",devops 兜底查 faq 看有没有 SOP。
    """
    try:
        result = _bridge_call("faq", _FAQ_URL, "query_faq",
                              query_text=query, limit=top_k)
        if not result or result.get("status") == "no_data":
            return json.dumps({"status": "no_data", "data": [],
                               "message": "faq 未命中"}, ensure_ascii=False)
        return json.dumps({"status": "success", "data": result.get("data", []),
                           "count": len(result.get("data", []))}, ensure_ascii=False)
    except Exception as e:
        HR_BRIDGE_ERRORS_TOTAL.labels(target="faq", kind="error").inc()
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)