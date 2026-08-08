"""
需求：CorpAI FastAPI后端服务器，提供REST API接口
"""
import json
import os
import re
import time

from fastapi import FastAPI, Header, Response
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn

from CorpAI.api import admin_router as _admin
from CorpAI.platform.observability.metrics import (
    HTTP_REQUESTS,
    HTTP_REQUEST_DURATION,
    endpoint_label,
)
from CorpAI.platform.observability.trace import (
    new_span_id,
    new_trace_id,
    normalize_incoming_trace_id,
)
from CorpAI.platform.plugin_manager import discover_all
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


app = FastAPI(title="CorpAI API", description="基于A2A的旅行智能助手")
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
