"""
需求：CorpAI FastAPI后端服务器，提供REST API接口
"""
import json
import os
import re

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn

from CorpAI.core.chat import ChatService


def _strip_think_blocks(text: str) -> str:
    """
    去掉 LLM 输出里的 <think>...</think> 推理过程
    （Qwen3 / DeepSeek 等推理模型会输出思考过程，前端不应该展示给用户）
    """
    if not text:
        return text
    return re.sub(r'<think>.*?</think>\s*', '', text, flags=re.DOTALL).strip()

app = FastAPI(title="CorpAI API", description="基于A2A的旅行智能助手")

# 全局服务实例
chat_service = ChatService()


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
async def chat(request: ChatRequest):
    """发送消息，获取回复"""
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
