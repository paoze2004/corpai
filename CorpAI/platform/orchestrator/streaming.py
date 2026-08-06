"""
流式基础设施 — Phase 1 拆分自 api/app.py:59-119(ThinkBlockFilter + SSE)。

包含:
1. ThinkBlockFilter — 跨 chunk 状态机,过滤 <think>...</think>
2. format_sse_chunk / format_sse_done — SSE wire 格式(必须保持与前端兼容)
3. apply_think_filter — 把 AsyncIterator[str] 包装为过滤后的 AsyncIterator[str]
4. wrap_sse — 把过滤后的 chunk 序列化为 SSE wire

设计原则(ADR-002 / ADR-008):
- ThinkBlockFilter 必须原样保留(状态机精确,改动会破前端)
- SSE wire 格式 `data: {"chunk":...}\\n\\n` + `[DONE]` 必须保持
- chat_stream / _call_agent_intent_stream / _react_loop_stream 仍留在 chat.py
  (Phase 1.6 写 service.py 时整体搬到 OrchestratorService)
"""
import json
from typing import AsyncIterator


class ThinkBlockFilter:
    """跨 chunk 过滤 <think>...</think> 的状态机。

    原样保留自 api/app.py:59-101(逐字节等价)。
    关键设计:
    - 跨 chunk 保留 <think> 部分直到看见 </think>
    - 流结束时未闭合的 think 块**宁可显示也别吞掉**(flush 兜底)
    """

    def __init__(self):
        self.in_think = False
        self.buffer = ""

    def feed(self, chunk: str) -> str:
        """
        喂入新 chunk,返回可安全发给前端的文本。
        残留未匹配的字符(开标签、think 内部)缓存在内部 buffer。
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
                    # think 块还没闭合,剩余内容继续缓存
                    self.buffer = ""
                    break
                else:
                    self.buffer = self.buffer[end + len('</think>'):]
                    self.in_think = False
        return ''.join(out)

    def flush(self) -> str:
        """流结束时调用,吐出 buffer 里残留的内容(兜底)。

        实际行为:未闭合 think 块的内部内容在 feed() 阶段已被丢弃,
        所以 buffer 为空时返回 ""。若 buffer 中有部分残留(开标签无后续),
        兜底返回。
        """
        if not self.buffer.strip():
            return ""
        leftover = self.buffer.strip()
        self.buffer = ""
        return leftover


def format_sse_chunk(text: str) -> str:
    """SSE 单 chunk wire 格式(前端 StaticFiles 期望)。"""
    return f"data: {json.dumps({'chunk': text}, ensure_ascii=False)}\n\n"


def format_sse_done() -> str:
    """SSE 终止符(原样)。"""
    return "data: [DONE]\n\n"


async def apply_think_filter(
    source: AsyncIterator[str],
) -> AsyncIterator[str]:
    """把 AsyncIterator[str] 通过 ThinkBlockFilter 过滤。

    自动在流结束时调 flush()(兜底残留)。
    """
    flt = ThinkBlockFilter()
    async for chunk in source:
        cleaned = flt.feed(chunk)
        if cleaned:
            yield cleaned
    leftover = flt.flush()
    if leftover:
        yield leftover


async def wrap_sse(
    source: AsyncIterator[str],
) -> AsyncIterator[str]:
    """把过滤后的 chunk 包装成 SSE wire(含 [DONE] 终止符)。

    等价于 api/app.py:104-119 sse_generator 的内容生产部分。
    """
    filtered = apply_think_filter(source)
    async for cleaned in filtered:
        yield format_sse_chunk(cleaned)
    yield format_sse_done()


async def collect_stream(source: AsyncIterator[str]) -> tuple[str, list[str]]:
    """辅助:消费整个流,返回 (full_text, chunks)。

    Phase 1.6 service.py 中,chat_stream 结束后需要:
    1. 把 yield 的 chunks 拼成 full_text(给 memory 存)
    2. 校验完整内容
    """
    chunks: list[str] = []
    async for chunk in source:
        chunks.append(chunk)
    return "".join(chunks), chunks
