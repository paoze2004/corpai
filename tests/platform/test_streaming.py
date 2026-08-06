"""
streaming.py 行为测试 — ThinkBlockFilter 状态机 + SSE 格式。

注:不引入 pytest-asyncio 依赖,用 asyncio.run() 包装 async 测试。
"""
import asyncio
import json

from CorpAI.platform.orchestrator.streaming import (
    ThinkBlockFilter,
    apply_think_filter,
    collect_stream,
    format_sse_chunk,
    format_sse_done,
    wrap_sse,
)


def run_async(coro):
    return asyncio.run(coro)


# ════════════════════════════════════════════════════════════════
# ThinkBlockFilter — 状态机测试(从 api/app.py:59-101 原样锁行为)
# ════════════════════════════════════════════════════════════════
class TestThinkBlockFilter:
    def test_no_think_block_passes_through(self):
        flt = ThinkBlockFilter()
        assert flt.feed("hello world") == "hello world"
        assert flt.flush() == ""

    def test_single_think_block_filtered(self):
        flt = ThinkBlockFilter()
        assert flt.feed("before<think>secret</think>after") == "beforeafter"

    def test_think_block_at_start(self):
        flt = ThinkBlockFilter()
        assert flt.feed("<think>secret</think>hello") == "hello"

    def test_think_block_at_end(self):
        flt = ThinkBlockFilter()
        assert flt.feed("hello<think>secret</think>") == "hello"

    def test_think_split_across_chunks(self):
        flt = ThinkBlockFilter()
        assert flt.feed("hello<think>sec") == "hello"
        assert flt.feed("ret</think>after") == "after"

    def test_multiple_think_blocks(self):
        flt = ThinkBlockFilter()
        assert flt.feed("a<think>1</think>b<think>2</think>c") == "abc"

    def test_unclosed_think_block_content_discarded(self):
        """未闭合 think 块的内部内容在 feed 阶段被丢弃(buffer 清空)。"""
        flt = ThinkBlockFilter()
        # "before" 在 think 之前保留,unfinished 在 think 块内被丢弃
        out = flt.feed("before<think>unfinished")
        assert out == "before"
        # flush 此时 buffer 已空,返回 ""
        assert flt.flush() == ""

    def test_partial_think_tag_full_match(self):
        """完整 <think> (6字符)被识别,后续内容进入 think 块被丢弃。"""
        flt = ThinkBlockFilter()
        # '<think>' 是完整 6 字符,被识别
        out = flt.feed("a<think>b")
        assert out == "a"
        # 'b' 在 think 块内,buffer 已清空
        assert flt.flush() == ""

    def test_partial_think_prefix_not_matched(self):
        """仅 '<think' 5 字符不构成完整 <think>,被当普通文本。"""
        flt = ThinkBlockFilter()
        # 'think' 缺 '<' 前缀,不识别
        out = flt.feed("a<thinkb")
        assert out == "a<thinkb"

    def test_think_with_newlines(self):
        flt = ThinkBlockFilter()
        out = flt.feed("before<think>line1\nline2\nline3</think>after")
        assert out == "beforeafter"

    def test_chinese_text_preserved(self):
        flt = ThinkBlockFilter()
        out = flt.feed("你好<think>thinking</think>世界")
        assert out == "你好世界"

    def test_feed_returns_empty_when_buffering(self):
        flt = ThinkBlockFilter()
        assert flt.feed("<think>part1") == ""
        assert flt.feed("part2") == ""
        assert flt.feed("part3</think>after") == "after"

    def test_buffer_clears_after_flush(self):
        flt = ThinkBlockFilter()
        flt.feed("<think>incomplete")
        flt.flush()
        assert flt.flush() == ""


# ════════════════════════════════════════════════════════════════
# SSE 格式测试
# ════════════════════════════════════════════════════════════════
class TestSSEFormat:
    def test_format_chunk_basic(self):
        assert format_sse_chunk("hello") == 'data: {"chunk": "hello"}\n\n'

    def test_format_chunk_preserves_chinese(self):
        result = format_sse_chunk("你好世界")
        assert "你好世界" in result
        assert "\\u" not in result

    def test_format_chunk_handles_newlines(self):
        result = format_sse_chunk("line1\nline2")
        assert '"chunk": "line1\\nline2"' in result

    def test_format_chunk_handles_quotes(self):
        result = format_sse_chunk('he said "hi"')
        assert '\\"hi\\"' in result

    def test_format_done(self):
        assert format_sse_done() == "data: [DONE]\n\n"

    def test_format_chunk_is_valid_json(self):
        result = format_sse_chunk("test content")
        payload = result[len("data: "):].rstrip("\n")
        parsed = json.loads(payload)
        assert parsed == {"chunk": "test content"}


# ════════════════════════════════════════════════════════════════
# apply_think_filter / wrap_sse / collect_stream — async 测试
# ════════════════════════════════════════════════════════════════
def async_to_list(async_iter):
    """async iterator → list(同步消费)。"""
    items = []
    async def consume():
        async for item in async_iter:
            items.append(item)
    run_async(consume())
    return items


def make_source(chunks):
    async def source():
        for c in chunks:
            yield c
    return source()


class TestApplyThinkFilter:
    def test_basic_through(self):
        result = async_to_list(apply_think_filter(make_source(["hello", " world"])))
        assert "".join(result) == "hello world"

    def test_filter_across_chunks(self):
        result = async_to_list(apply_think_filter(make_source(["hello", "<think>secret", "</think>after"])))
        assert "".join(result) == "helloafter"

    def test_unclosed_think_flushed_at_end(self):
        """未闭合 think 块的内容在 feed 阶段被丢弃(实际行为)。"""
        result = async_to_list(apply_think_filter(make_source(["before", "<think>incomplete"])))
        # "incomplete" 被丢弃,只剩 "before"
        assert "".join(result) == "before"

    def test_empty_source(self):
        async def source():
            if False:
                yield ""
        result = async_to_list(apply_think_filter(source()))
        assert result == []


class TestWrapSSE:
    def test_basic_sse_flow(self):
        lines = async_to_list(wrap_sse(make_source(["hello", " ", "world"])))
        assert lines[0].startswith("data: ")
        assert lines[-1] == "data: [DONE]\n\n"
        assert len(lines) >= 2

    def test_sse_filters_think_block(self):
        lines = async_to_list(wrap_sse(make_source(["hello", "<think>secret</think>", "world"])))
        chunks = []
        for line in lines[:-1]:
            payload = line[len("data: "):].rstrip("\n")
            parsed = json.loads(payload)
            chunks.append(parsed["chunk"])
        full = "".join(chunks)
        assert "secret" not in full
        assert "hello" in full
        assert "world" in full

    def test_sse_done_at_end(self):
        lines = async_to_list(wrap_sse(make_source(["a", "b"])))
        assert lines[-1] == "data: [DONE]\n\n"

    def test_sse_with_chinese(self):
        lines = async_to_list(wrap_sse(make_source(["你好", "世界"])))
        first_payload = lines[0][len("data: "):].rstrip("\n")
        parsed = json.loads(first_payload)
        assert "你好" in parsed["chunk"]


class TestCollectStream:
    def test_collects_all_chunks(self):
        async def go():
            return await collect_stream(make_source(["a", "b", "c"]))
        full, chunks = run_async(go())
        assert full == "abc"
        assert chunks == ["a", "b", "c"]

    def test_empty_source(self):
        async def source():
            if False:
                yield ""
        async def go():
            return await collect_stream(source())
        full, chunks = run_async(go())
        assert full == ""
        assert chunks == []
