"""sre_copilot 跨插件 bridge 工具 v3.1 — 用官方 fastmcp Client 调真 MCP。

设计(v3.1 改造):
- bridge 失败时显式返回 `{"status": "bridge_unavailable", "kind": "timeout|unreachable|http5xx|error", "message": "..."}`
- 绝不吞错(对照 CLAUDE.md "不要 silent-fail DB 写入")
- 仍用 HR_BRIDGE_ERRORS_TOTAL Counter 累加(target=hr|faq, kind=具体失败类型)
- timeout 严格 2s(防 hang 主流程)
- 目标 URL 走 env: HR_URL(默认 http://localhost:8001/mcp)、KNOWLEDGE_URL(默认 http://localhost:8030/mcp)

异步 / 同步双接口:
- `async def _bridge_call_async` — 真正的 MCP 调用
- `async def cross_check_hr` / `cross_query_knowledge` — async 公开 API
- `def cross_check_hr` / `cross_query_knowledge`(重载) — sync 包装,用 `asyncio.run()`
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

from fastmcp import Client

logger = logging.getLogger(__name__)

from _0_CorpAI._2_platform.observability.metrics import HR_BRIDGE_ERRORS_TOTAL  # 复用

# 走官方 MCP 协议,路径统一是 /mcp
_HR_URL = os.getenv("HR_URL", "http://localhost:8001") + "/mcp"
_FAQ_URL = os.getenv("KNOWLEDGE_URL", "http://localhost:8030") + "/mcp"
_BRIDGE_TIMEOUT = 2.0


# ═══════════════════════════════════════════════════════════════════════
#  底层:async MCP client 调用
# ═══════════════════════════════════════════════════════════════════════

async def _bridge_call_async(target: str, url: str, tool_name: str, **kwargs) -> dict:
    """跨插件桥接调用(官方 MCP 协议 — JSON-RPC 2.0 over StreamableHTTP)。

    返回:
      - 成功:{...} 原始 dict(从 JSON 解析)
      - 失败:{"status": "bridge_unavailable", "kind": "...",
              "message": "..."} (绝不返回 None,显式告知)
    """
    try:
        client = Client(url, timeout=_BRIDGE_TIMEOUT)
        async with client:
            result = await client.call_tool(tool_name, kwargs)
    except asyncio.TimeoutError:
        HR_BRIDGE_ERRORS_TOTAL.labels(target=target, kind="timeout").inc()
        return {
            "status": "bridge_unavailable",
            "kind": "timeout",
            "message": (f"bridge {target} {tool_name} 超时({_BRIDGE_TIMEOUT}s);"
                       f"检查 {url} 是否可达"),
        }
    except Exception as exc:
        err_name = exc.__class__.__name__
        if "Connection" in err_name:
            kind = "unreachable"
        else:
            kind = "error"
        HR_BRIDGE_ERRORS_TOTAL.labels(target=target, kind=kind).inc()
        logger.warning(f"bridge {target} {tool_name} 异常:{exc}")
        return {
            "status": "bridge_unavailable",
            "kind": kind,
            "message": f"bridge {target} 异常:{exc}",
        }

    # MCP 返的 content 是 list[TextContent],text 字段是 JSON 字符串
    if result.is_error:
        HR_BRIDGE_ERRORS_TOTAL.labels(target=target, kind="tool_error").inc()
        return {
            "status": "bridge_unavailable",
            "kind": "tool_error",
            "message": f"bridge {target} tool error:{result.content}",
        }

    try:
        text = result.content[0].text if result.content else ""
        return json.loads(text) if text else {}
    except Exception as exc:
        HR_BRIDGE_ERRORS_TOTAL.labels(target=target, kind="json_decode").inc()
        return {
            "status": "bridge_unavailable",
            "kind": "json_decode",
            "message": f"bridge {target} 返非 JSON:{exc}",
        }


class BridgeAsyncioConflictError(RuntimeError):
    """sync bridge wrapper 在 async 上下文被调用。

    当 A2A server.py 改成 async handle_task 后,这里会炸 —— 不要在 async 上下文
    调 sync bridge,要直接 await 那个 *_async 函数。
    """


def _run_async(coro):
    """从 sync 上下文跑 async(用 asyncio.run,clean 创建/关闭 loop)。

    限制:不能从已有 running event loop 的 async 上下文调。
    真要混用请直接 await 那个 async 函数(cross_check_hr_async / cross_query_knowledge_async)。
    """
    try:
        return asyncio.run(coro)
    except RuntimeError as e:
        # asyncio.run() 在已有 running loop 时抛这个。转成带指南的明确错误。
        if "cannot be called from a running event loop" in str(e):
            raise BridgeAsyncioConflictError(
                "sync bridge wrapper (cross_check_hr / cross_query_knowledge) "
                "在 async 上下文被调用。请改用对应的 *_async 版本并直接 await。"
            ) from e
        raise


# ═══════════════════════════════════════════════════════════════════════
#  Public API:async 版本(供真 async 上下文,例如未来 ReAct loop)
# ═══════════════════════════════════════════════════════════════════════

async def cross_check_hr_async(authorization: str, request_id: str) -> str:
    """async 版。跨插件:hr 申请触发时,查 hr 找关联申请。

    Args:
        authorization: Bearer token(传 user JWT)
        request_id: HR 申请 ID(L 开头)
    """
    result = await _bridge_call_async("hr", _HR_URL, "query_my_requests",
                                      authorization=authorization)
    if result.get("status") == "bridge_unavailable":
        return json.dumps({
            "status": "bridge_unavailable",
            "kind": result.get("kind"),
            "message": result.get("message"),
            "request_id": request_id,
        }, ensure_ascii=False)
    return json.dumps({
        "status": "success",
        "data": {"request_id": request_id, "hr_check": result.get("data", {})},
        "message": "hr 联动查询成功",
    }, ensure_ascii=False)


async def cross_query_knowledge_async(query: str, top_k: int = 2) -> str:
    """async 版。跨插件:knowledge 兜底补全(SOP 兜底)。

    Args:
        query: 用户查询文本
        top_k: 返回 top 几
    """
    result = await _bridge_call_async("knowledge", _FAQ_URL, "query_knowledge",
                                      query_text=query, limit=top_k)
    if result.get("status") == "bridge_unavailable":
        return json.dumps({
            "status": "bridge_unavailable",
            "kind": result.get("kind"),
            "message": result.get("message"),
            "query": query,
        }, ensure_ascii=False)
    if result.get("status") == "no_data":
        return json.dumps({
            "status": "no_data",
            "data": [],
            "message": "knowledge 未命中",
            "query": query,
        }, ensure_ascii=False)
    return json.dumps({
        "status": "success",
        "data": result.get("data", []),
        "count": len(result.get("data", [])),
        "query": query,
    }, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════
#  Public API:sync 版本(供 A2A handle_task 等 sync 上下文)
# ═══════════════════════════════════════════════════════════════════════

def cross_check_hr(authorization: str, request_id: str) -> str:
    """sync 版 — A2A server 用,内部用 asyncio.run 包一层。

    注意:不能在已有 running event loop 的 async 上下文调,要混用请用 `cross_check_hr_async`。
    """
    return _run_async(cross_check_hr_async(authorization, request_id))


def cross_query_knowledge(query: str, top_k: int = 2) -> str:
    """sync 版 — A2A server 用,内部用 asyncio.run 包一层。

    注意:不能在已有 running event loop 的 async 上下文调,要混用请用 `cross_query_knowledge_async`。
    """
    return _run_async(cross_query_knowledge_async(query, top_k))