"""Phase 4 test_trace — ContextVar + Span + start_span + to_thread_propagating。

不依赖 DB(monkeypatch 屏蔽 call_record 写)。
"""
import asyncio
import unittest
from unittest.mock import patch

from CorpAI.platform.observability.trace import (
    Span,
    bind_trace_context,
    current_span_id,
    current_trace_id,
    new_span_id,
    new_trace_id,
    normalize_incoming_trace_id,
    reset_trace_context,
    start_span,
    to_thread_propagating,
)


# 屏蔽 write_call_record,避免单元测试写真实 DB
_noop_writer = lambda span: None


def _start_span_no_db(name, attrs=None):
    """包一层 patch,然后调 start_span。"""
    with patch(
        "CorpAI.platform.observability.call_record.write_call_record",
        _noop_writer,
    ):
        with start_span(name, attrs) as span:
            return span


class TestIDs(unittest.TestCase):
    def test_new_trace_id_length_32(self):
        tid = new_trace_id()
        self.assertEqual(len(tid), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in tid))

    def test_new_span_id_length_16(self):
        sid = new_span_id()
        self.assertEqual(len(sid), 16)
        self.assertTrue(all(c in "0123456789abcdef" for c in sid))

    def test_new_ids_unique(self):
        self.assertNotEqual(new_trace_id(), new_trace_id())
        self.assertNotEqual(new_span_id(), new_span_id())


class TestNormalize(unittest.TestCase):
    def test_valid_kept(self):
        self.assertEqual(normalize_incoming_trace_id("abc-123"), "abc-123")
        self.assertEqual(normalize_incoming_trace_id("a_b.c-d"), "a_b.c-d")

    def test_empty_none(self):
        self.assertIsNone(normalize_incoming_trace_id(None))
        self.assertIsNone(normalize_incoming_trace_id(""))
        self.assertIsNone(normalize_incoming_trace_id("   "))

    def test_invalid_chars_none(self):
        self.assertIsNone(normalize_incoming_trace_id("has spaces"))
        self.assertIsNone(normalize_incoming_trace_id("has\nnewline"))
        self.assertIsNone(normalize_incoming_trace_id("with/slash"))

    def test_too_long_none(self):
        self.assertIsNone(normalize_incoming_trace_id("a" * 65))


class TestContextVar(unittest.TestCase):
    def test_outside_context_none(self):
        # 在新测试中 ContextVar 默认 None(其他测试可能留下)
        # 不强断言,只确认 getter 不抛
        self.assertIn(current_trace_id(), (None,) + tuple())
        self.assertIn(current_span_id(), (None,) + tuple())


class TestStartSpan(unittest.TestCase):
    def setUp(self):
        # 全 patch write_call_record
        patcher = patch(
            "CorpAI.platform.observability.call_record.write_call_record",
            _noop_writer,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_basic_span(self):
        with start_span("basic") as span:
            self.assertEqual(span.name, "basic")
            self.assertEqual(span.status, "ok")  # 自动 end_ok
            self.assertIsNotNone(span.trace_id)
            self.assertIsNotNone(span.span_id)
        self.assertIsNone(current_trace_id())  # 退出后清
        self.assertIsNone(current_span_id())

    def test_nested_parent_relation(self):
        with start_span("parent") as p:
            with start_span("child") as c:
                self.assertEqual(c.trace_id, p.trace_id)
                self.assertEqual(c.parent_span_id, p.span_id)
        self.assertEqual(p.parent_span_id, None)

    def test_set_attr(self):
        with start_span("attr") as span:
            span.set_attr("user_id", "alice")
            self.assertEqual(span.attributes["user_id"], "alice")
            span.set_attr("count", 42)
            self.assertEqual(span.attributes["count"], 42)

    def test_exception_marks_error(self):
        captured = []
        with patch(
            "CorpAI.platform.observability.call_record.write_call_record",
            lambda s: captured.append(s),
        ):
            try:
                with start_span("err"):
                    raise ValueError("oops2")
            except ValueError:
                pass
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].status, "error")
        self.assertIn("oops2", captured[0].error)

    def test_explicit_end_err_not_overridden(self):
        captured = []
        with patch(
            "CorpAI.platform.observability.call_record.write_call_record",
            lambda s: captured.append(s),
        ):
            with start_span("explicit") as s:
                s.end_err("manual")
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].status, "error")
        self.assertEqual(captured[0].error, "manual")


class TestToThreadPropagating(unittest.TestCase):
    def setUp(self):
        patcher = patch(
            "CorpAI.platform.observability.call_record.write_call_record",
            _noop_writer,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_propagates_context_to_thread(self):
        async def main():
            with start_span("main"):
                # 子线程读 trace_id 应一致
                import contextvars
                def in_thread():
                    return current_trace_id()

                ctx = contextvars.copy_context()
                loop = asyncio.get_running_loop()
                tid_in_thread = await loop.run_in_executor(
                    None, ctx.run, in_thread,
                )
                self.assertEqual(tid_in_thread, current_trace_id())

        asyncio.run(main())

    def test_to_thread_propagating_helper(self):
        # to_thread_propagating 也要传 trace_id
        async def main():
            with start_span("outer"):
                def in_thread():
                    return current_trace_id()
                tid = await to_thread_propagating(in_thread)
                self.assertEqual(tid, current_trace_id())

        asyncio.run(main())


class TestBindReset(unittest.TestCase):
    def test_bind_then_reset(self):
        tokens = bind_trace_context("trace-x", "span-y", "parent-z")
        self.assertEqual(current_trace_id(), "trace-x")
        self.assertEqual(current_span_id(), "span-y")
        reset_trace_context(tokens)
        self.assertIsNone(current_trace_id())
        self.assertIsNone(current_span_id())


if __name__ == "__main__":
    unittest.main()