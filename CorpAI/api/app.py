"""
需求：CorpAI FastAPI后端服务器，提供REST API接口
"""
import json
import logging
import os
import re
import time

import uvicorn
from fastapi import FastAPI, Header, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from CorpAI.utils.dotenv import load_env

# v3.2:加载 .env(单一配置源)
load_env()

from CorpAI.api import admin_router as _admin
from CorpAI.platform.observability.metrics import (
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS,
    endpoint_label,
)
from CorpAI.platform.observability.trace import (
    new_span_id,
    new_trace_id,
    normalize_incoming_trace_id,
)
from CorpAI.platform.plugin_manager import discover_all
from sre_copilot.feishu import (
    handle_approve_callback,
    handle_reject_callback,
    verify_signature,
)

logger = logging.getLogger(__name__)
from CorpAI.platform.sre.webhook import router as sre_webhook_router
from CorpAI.platform.wiring import build_default_service


def _strip_think_blocks(text: str) -> str:
    """
    去掉 LLM 输出里的 <think>...</think> 推理过程
    （Qwen3 / DeepSeek 等推理模型会输出思考过程，前端不应该展示给用户）
    """
    if not text:
        return text
    return re.sub(r'<think>.*?</think>\s*', '', text, flags=re.DOTALL).strip()


class TraceContextMiddleware(BaseHTTPMiddleware):
    """每个请求自动分配 trace_id / span_id,回 X-Trace-ID header,计 HTTP metrics。

    异常路径也在 finally 中设 status='500',保证 Counter 总被 inc。
    """
    async def dispatch(self, request, call_next):
        trace_id = (
            normalize_incoming_trace_id(request.headers.get("X-Trace-ID"))
            or new_trace_id()
        )
        span_id = new_span_id()
        request.state.trace_id = trace_id
        request.state.span_id = span_id
        status = "500"
        started = time.perf_counter()
        try:
            response = await call_next(request)
            status = str(response.status_code)
            response.headers["X-Trace-ID"] = trace_id
            return response
        finally:
            endpoint = endpoint_label(request.scope)
            elapsed = time.perf_counter() - started
            HTTP_REQUESTS.labels(
                method=request.method, endpoint=endpoint, status=status,
            ).inc()
            HTTP_REQUEST_DURATION.labels(
                method=request.method, endpoint=endpoint,
            ).observe(elapsed)


app = FastAPI(title="CorpAI API", description="企业 AI Copilot 平台 — 可插拔多 Agent")
app.add_middleware(TraceContextMiddleware)

# Phase 4:公开 Prometheus /metrics 端点(给 scraper;不需 JWT)
@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics():
    return Response(generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})

# Phase 3:include admin router + mount /admin static + plugin_manager 注入到 build_default_service
app.include_router(_admin.router)
_static_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
_static_admin = os.path.join(_static_root, "admin")
if os.path.isdir(_static_admin):
    app.mount("/admin", StaticFiles(directory=_static_admin, html=True), name="admin")

# Phase SRE:Alertmanager webhook 入口 + 飞书 callback
app.include_router(sre_webhook_router)


# ─── 飞书事件订阅统一入口 ───
# 飞书后台「事件与回调 → 回调配置」填这个 URL
# 飞书会 POST 过来两种东西:
#   1. URL 验证:{challenge: "xxx"} → 返 {"challenge": "xxx"} 让飞书确认 URL 归属
#   2. 卡片点击:{type: "card_action_trigger", action: {value: {...}}, operator: {...}}
#      → 调 handle_approve_callback / handle_reject_callback
# 为什么走这个(而不是按钮 url 跳转):
#   - 按钮 url 跳转要飞书服务器访问我们 callback,localhost 不可达
#   - 事件订阅 POST 到 ngrok/公网 URL,可穿透 NAT
# signature 校验(pass-through,真接时飞书会带 X-Lark-Signature header)

from fastapi import Request


@app.get("/feishu/event")
async def feishu_event_verify(challenge: str = "") -> dict:
    """飞书「订阅保存」时的 URL 验证(GET 探活)。

    飞书会发 GET /feishu/event?challenge=xxx,期望返 {"challenge": "xxx"}。
    不返合法 JSON → 飞书后台显示"返回数据不是合法的JSON格式",保存失败。
    """
    if challenge:
        return {"challenge": challenge}
    return {"code": 0, "msg": "ok"}


@app.post("/feishu/event")
async def feishu_event_handler(request: Request) -> dict:
    """飞书事件订阅统一入口。

    1) URL 验证(POST 也可能来):
        body = {"challenge": "..."}
        → 返 {"challenge": "..."}
    2) 卡片回调 (card.action.trigger):
        body = {
          "type": "card_action_trigger",
          "action": {
            "value": {"plan_id": 1, "token": "...", "op": "approve"|"reject"}
          },
          "operator": {"open_id": "ou_xxx", "user_id": "..."}
        }
        → 调 ApprovalService
    3) 其他事件 → 返 200 + code=0(飞书要求成功 ack)
    """
    raw = await request.body()
    # 调试日志:看飞书实际发什么(完整 body,不截断)
    logger.info(f"飞书 POST body 长度={len(raw)} 完整={raw!r}")
    # signature 校验(如果 FEISHU_ENCRYPT_KEY 设了)
    sig = request.headers.get("X-Lark-Signature", "")
    ts = request.headers.get("X-Lark-Request-Timestamp", "")
    nonce = request.headers.get("X-Lark-Request-Nonce", "")
    if sig and not verify_signature(ts, nonce, raw.decode(), sig):
        logger.warning("飞书 callback 签名校验失败")
        return {"code": -1, "msg": "signature_invalid"}

    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        return {"code": -1, "msg": f"json_parse_failed:{exc}"}

    # URL 验证(POST 形式,部分老版本飞书仍用)
    if "challenge" in payload:
        # 如果飞书带了 token,顺手校验(可选 — 没设 VERIFY_TOKEN 就跳过)
        expected = os.getenv("FEISHU_VERIFY_TOKEN", "").strip()
        presented = payload.get("token", "")
        if expected and presented and presented != expected:
            logger.warning(f"飞书 URL 验证 token 不匹配:{presented[:8]}... vs expected")
            return {"code": -1, "msg": "verify_token_mismatch"}
        return {"challenge": payload["challenge"]}

    # 卡片按钮点击
    # 飞书新版 schema v2: {schema:"2.0", header:{event_type:"card.action.trigger"}, event:{action:{value:{...}}, operator:{...}}}
    # 飞书老版 schema v1: {type:"card_action_trigger", action:{value:{...}}, operator:{...}}(没 event 包裹)
    # 两条路径都支持,根据 event_type / type 字段判断走哪条
    event_type = payload.get("header", {}).get("event_type", "")
    legacy_type = payload.get("type", "")

    # v3.4.1:移除 header.token 校验 — 之前我把它和 FEISHU_VERIFY_TOKEN 混淆了
    # 真正的安全凭证是 action.value.token(approval_token),由 ApprovalService 校验
    # FEISHU_VERIFY_TOKEN 只用于 URL challenge 验证(下面那一段 GET challenge 处理)

    if event_type == "card.action.trigger" or legacy_type == "card_action_trigger":
        # v2 走 payload.event.{action,operator};v1 走 payload.{action,operator}
        if event_type == "card.action.trigger":
            event = payload.get("event", {}) or {}
            action = event.get("action", {}) or {}
            operator = event.get("operator", {}) or {}
        else:
            action = payload.get("action", {}) or {}
            operator = payload.get("operator", {}) or {}
        value = action.get("value", {}) or {}
        try:
            plan_id = int(value.get("plan_id", 0))
            token = str(value.get("token", ""))
            op = str(value.get("op", "approve"))
        except (TypeError, ValueError) as exc:
            return {"code": -1, "msg": f"value_invalid:{exc}"}
        if not (plan_id and token):
            logger.warning(f"飞书 callback 缺 plan_id/token:{value}")
            return {"code": -1, "msg": "missing_plan_id_or_token"}
        actor_open_id = operator.get("open_id") or operator.get("user_id") or "feishu_user"
        # v3.4:open_id → 真名(调飞书 contact/v3/users/{open_id}),失败回退 open_id
        try:
            from sre_copilot.feishu import get_feishu_user_name
            actor = get_feishu_user_name(actor_open_id)
        except Exception as exc:
            logger.warning(f"open_id→name 转换失败,fallback:{exc}")
            actor = actor_open_id
        scopes = ["sre:approve"]
        logger.info(
            f"飞书卡片 callback op={op} plan_id={plan_id} actor={actor}",
        )
        if op == "reject":
            result = handle_reject_callback(
                plan_id=plan_id, token=token,
                actor=actor, scopes=scopes,
                reason="rejected_via_feishu",
            )
        else:
            result = handle_approve_callback(
                plan_id=plan_id, token=token,
                actor=actor, scopes=scopes,
            )
        # 飞书 callback 响应 — v3.4.1 只返 toast,不返 card:
        # - 卡片更新走 PATCH 路径(_patch_card_after_decision 在 handle_approve/reject 内部已做)
        # - 飞书收到 callback 响应只需要 toast,返 card 反而触发 200672(原卡 v2,响应 v1 错配)
        status = result.get("status")
        # v3.2.5:"already_approved" / "already_decided" 也是正常状态(重发 callback)
        ok = status in ("approved", "rejected", "already_approved", "already_decided")
        decision_text = (
            f"已批准 by {actor}" if status == "approved" and op == "approve"
            else f"已拒绝 by {actor}" if status == "rejected"
            else f"已批过了(刚才是重复点击):{actor}" if status == "already_approved"
            else f"已拒过了(刚才是重复点击):{actor}" if status == "already_decided"
            else f"操作失败:{result.get('reason', 'unknown')}"
        )
        return {
            "toast": {
                "type": "success" if ok else "error",
                "content": decision_text,
            },
        }

    # 其它事件(用户消息等)— ack 不处理
    return {"code": 0, "msg": "ignored"}

# 全局服务实例
chat_service = build_default_service(plugin_manager=discover_all())


class ChatRequest(BaseModel):
    message: str


class ProfileRequest(BaseModel):
    profile: dict


@app.get("/")
async def index():
    """返回前端页面"""
    # 静态资源在 CorpAI/static/，不是 CorpAI/api/static/
    # __file__ = CorpAI/api/app.py → dirname 是 api/，需要再上一层
    static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
    index_path = os.path.join(static_dir, "index.html")
    if not os.path.exists(index_path):
        raise FileNotFoundError(f"前端文件不存在: {index_path}")
    return FileResponse(index_path)


@app.post("/api/chat")
async def chat(
    request: ChatRequest,
    authorization: str | None = Header(None),
):
    """发送消息,获取回复。Phase 5:可选 JWT,带 scope 时 wiring 校验 RBAC。"""
    if authorization and authorization.startswith("Bearer "):
        try:
            from CorpAI.platform.auth.dependencies import get_jwt_secret
            from CorpAI.platform.auth.tokens import jwt_decode
            from CorpAI.platform.wiring import set_user_scopes
            claims = jwt_decode(authorization[7:], get_jwt_secret())
        except Exception:
            claims = None
        if claims:
            set_user_scopes(claims.get("scopes", []))
    response = await chat_service.chat(request.message)
    return {"status": "success", "message": _strip_think_blocks(response)}


class ThinkBlockFilter:
    """跨 chunk 过滤 <think>...</think> 的状态机"""

    def __init__(self):
        self.in_think = False
        self.buffer = ""

    def feed(self, chunk: str) -> str:
        """
        喂入一个新的 chunk，返回可以安全发给前端的文本。
        残留未匹配的字符（开标签、think 内部）会缓存在内部 buffer。
        """
        self.buffer += chunk
        out = []
        while self.buffer:
            if not self.in_think:
                start = self.buffer.find('<think>')
                if start == -1:
                    out.append(self.buffer)
                    self.buffer = ""
                else:
                    if start > 0:
                        out.append(self.buffer[:start])
                    self.buffer = self.buffer[start + len('<think>'):]
                    self.in_think = True
            else:
                end = self.buffer.find('</think>')
                if end == -1:
                    # think 块还没闭合，剩余内容继续缓存
                    self.buffer = ""
                    break
                else:
                    self.buffer = self.buffer[end + len('</think>'):]
                    self.in_think = False
        return ''.join(out)

    def flush(self) -> str:
        """流结束时调用，吐出 buffer 里残留的内容（兜底）"""
        if not self.buffer.strip():
            return ""
        leftover = self.buffer.strip()
        self.buffer = ""
        return leftover  # 极端兜底：没闭合的 think 块，宁可显示也别吞掉


async def sse_generator(message: str):
    """SSE 生成器，逐字流式返回回复（已过滤 <think> 块）"""
    flt = ThinkBlockFilter()

    async for chunk in chat_service.chat_stream(message):
        cleaned = flt.feed(chunk)
        if cleaned:
            yield f"data: {json.dumps({'chunk': cleaned}, ensure_ascii=False)}\n\n"

    # 流结束，吐出兜底残留
    leftover = flt.flush()
    if leftover:
        yield f"data: {json.dumps({'chunk': leftover}, ensure_ascii=False)}\n\n"

    # 发送结束标记
    yield "data: [DONE]\n\n"


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """发送消息，流式获取回复（SSE）"""
    return StreamingResponse(sse_generator(request.message), media_type="text/event-stream")


@app.get("/api/memory")
async def get_memory():
    """获取记忆状态"""
    return {"status": "success", "data": chat_service.get_memory_state()}


@app.post("/api/memory/clear")
async def clear_memory():
    """清空记忆"""
    chat_service.clear_memory()
    return {"status": "success", "message": "记忆已清空"}


@app.post("/api/memory/profile")
async def update_profile(request: ProfileRequest):
    """更新用户偏好"""
    chat_service.update_user_profile(request.profile)
    return {"status": "success", "message": "用户偏好已更新"}


@app.get("/api/agents")
async def get_agents():
    """获取代理卡片信息"""
    return {"status": "success", "data": chat_service.get_agent_cards()}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="info")
