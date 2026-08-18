"""Phase 4 test_log — JsonFormatter + TraceContextFilter + setup_json_logger。"""
import json
import logging
import os
import tempfile
import unittest
from unittest.mock import patch

from _0_CorpAI._2_platform.observability.log import (
    JsonFormatter,
    TraceContextFilter,
    setup_json_logger,
)
from _0_CorpAI._2_platform.observability.trace import (
    bind_trace_context,
    current_span_id,
    current_trace_id,
    reset_trace_context,
)


class TestJsonFormatter(unittest.TestCase):
    def setUp(self):
        self.fmt = JsonFormatter()

    def _make_record(self, msg, extra=None, exc_info=None):
        rec = logging.LogRecord(
            name="test", level=logging.INFO, pathname="x.py", lineno=10,
            msg=msg, args=(), exc_info=exc_info, func=None, sinfo=None,
        )
        if extra:
            for k, v in extra.items():
                setattr(rec, k, v)
        return rec

    def test_basic_format_is_json(self):
        rec = self._make_record("hello world")
        out = self.fmt.format(rec)
        payload = json.loads(out)
        self.assertEqual(payload["msg"], "hello world")
        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["logger"], "test")
        self.assertEqual(payload["module"], "x")  # LogRecord.module 是无扩展名
        self.assertEqual(payload["line"], 10)

    def test_chinese_not_escaped(self):
        rec = self._make_record("中文消息")
        out = self.fmt.format(rec)
        self.assertIn("中文消息", out)
        self.assertNotIn("\\u4e2d\\u6587", out)

    def test_extra_fields_passthrough(self):
        rec = self._make_record("ev", extra={"tenant_id": "t1", "count": 3})
        out = self.fmt.format(rec)
        payload = json.loads(out)
        self.assertEqual(payload["tenant_id"], "t1")
        self.assertEqual(payload["count"], 3)

    def test_default_str_on_unserializable(self):
        class Opaque:
            def __repr__(self): return "<opaque>"
        rec = self._make_record("o", extra={"obj": Opaque()})
        out = self.fmt.format(rec)  # 不抛
        self.assertIn("<opaque>", out)

    def test_exc_info_included(self):
        try:
            raise ValueError("test")
        except ValueError:
            import sys
            rec = self._make_record("err", exc_info=sys.exc_info())
        out = self.fmt.format(rec)
        payload = json.loads(out)
        self.assertIn("exc", payload)
        self.assertIn("ValueError", payload["exc"])
        self.assertIn("test", payload["exc"])


class TestTraceContextFilter(unittest.TestCase):
    def setUp(self):
        self.filt = TraceContextFilter()
        self.tokens = bind_trace_context("trace-test", "span-test", None)

    def tearDown(self):
        reset_trace_context(self.tokens)

    def _make_record(self):
        return logging.LogRecord(
            name="x", level=logging.INFO, pathname="x.py", lineno=1,
            msg="m", args=(), exc_info=None, func=None, sinfo=None,
        )

    def test_filter_injects_context(self):
        rec = self._make_record()
        self.filt.filter(rec)
        self.assertEqual(rec.trace_id, "trace-test")
        self.assertEqual(rec.span_id, "span-test")

    def test_filter_preserves_existing(self):
        rec = self._make_record()
        rec.trace_id = "explicit"
        rec.span_id = "explicit-span"
        self.filt.filter(rec)
        self.assertEqual(rec.trace_id, "explicit")  # 不覆盖
        self.assertEqual(rec.span_id, "explicit-span")


class TestSetupJsonLogger(unittest.TestCase):
    def test_idempotent(self):
        # 不使用 TemporaryDirectory(Windows 上 open file 不能删除),改用独立路径
        log_dir = os.path.join(tempfile.gettempdir(), "test_setup_json_logger")
        log_file = os.path.join(log_dir, "test.log")
        os.makedirs(log_dir, exist_ok=True)
        try:
            logger1 = setup_json_logger("test_idem", log_file=log_file)
            n_handlers_1 = len(logger1.handlers)
            # 第二次调用应不重复加 handler
            logger2 = setup_json_logger("test_idem", log_file=log_file)
            n_handlers_2 = len(logger2.handlers)
            self.assertEqual(n_handlers_1, n_handlers_2)
            self.assertIs(logger1, logger2)
        finally:
            # 关闭 file handler 才能在 Windows 上删除
            for h in logger1.handlers:
                try:
                    h.close()
                except Exception:
                    pass

    def test_logger_outputs_json(self):
        log_dir = os.path.join(tempfile.gettempdir(), "test_logger_outputs")
        log_file = os.path.join(log_dir, "test.log")
        os.makedirs(log_dir, exist_ok=True)
        try:
            logger = setup_json_logger("test_outputs", log_file=log_file)
            with patch(
                "_0_CorpAI._2_platform.observability.log.current_trace_id",
                lambda: "tr-x",
            ), patch(
                "_0_CorpAI._2_platform.observability.log.current_span_id",
                lambda: "sp-x",
            ):
                logger.info("hello", extra={"tenant_id": "t1"})

            # 读日志文件验证
            with open(log_file, encoding="utf-8") as f:
                line = f.readline().strip()
            payload = json.loads(line)
            self.assertEqual(payload["msg"], "hello")
            self.assertEqual(payload["trace_id"], "tr-x")
            self.assertEqual(payload["tenant_id"], "t1")
        finally:
            for h in logger.handlers:
                try:
                    h.close()
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()