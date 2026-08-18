"""Phase 4 test_call_record — write_call_record INSERT 字段 + DB raise → warning 不 raise。"""
import json
import logging
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from _0_CorpAI._2_platform.observability import call_record
from _0_CorpAI._2_platform.observability.trace import Span


class TestWriteCallRecord(unittest.TestCase):
    def _make_span(self, status="ok", error=None, attrs=None):
        return Span(
            name="test.span",
            trace_id="tr-abc",
            span_id="sp-abc",
            parent_span_id=None,
            start_ts=1700000000.0,
            end_ts=1700000001.5,  # duration = 1500ms
            status=status,
            attributes=attrs or {"tenant_id": "t1"},
            error=error,
        )

    def test_db_unreachable_logs_warning(self):
        """DB 不可达 → warning 不抛(辅助观测,不阻断业务)。"""
        from _0_CorpAI._2_platform.observability.call_record import write_call_record

        span = self._make_span()
        # 用一个 FakeDatabasePool 类替换,get() 返回 raise get_conn 的 mock
        class FakeDatabasePool:
            @staticmethod
            def get():
                m = MagicMock()
                m.get_conn.side_effect = ConnectionError("DB down")
                return m

        with patch.object(call_record, "DatabasePool", new=FakeDatabasePool):
            with self.assertLogs(
                "_0_CorpAI.observability", level="WARNING",
            ) as captured:
                write_call_record(span)

        self.assertTrue(any("call_records 写入失败" in m for m in captured.output))

    def test_happy_path_inserts_row(self):
        """fake cursor/conn 验证 INSERT 字段。"""
        from _0_CorpAI._2_platform.observability.call_record import write_call_record

        span = self._make_span(
            status="ok",
            attrs={"tenant_id": "t1", "user_id": "alice", "extra": "ok"},
        )

        cur = MagicMock()
        # 普通 class conn(非 MagicMock,避免 mock 链),有 cursor/commit/close
        class FakeConn:
            def cursor(self):
                return cur
            def commit(self):
                pass
            def close(self):
                pass
        real_conn = FakeConn()

        # FakeDatabasePool.get() 返回一个 wrapper:wrapper.get_conn() → real_conn
        class FakeDBPool:
            @staticmethod
            def get():
                wrapper = MagicMock()
                wrapper.get_conn.return_value = real_conn
                return wrapper

        with patch.object(call_record, "DatabasePool", new=FakeDBPool):
            write_call_record(span)

        # 验证 cursor.execute 被调一次,参数对
        cur.execute.assert_called_once()
        args, kwargs = cur.execute.call_args
        sql = args[0]
        values = args[1]
        self.assertIn("INSERT INTO call_records", sql)
        self.assertEqual(values[0], "tr-abc")      # trace_id
        self.assertEqual(values[1], "sp-abc")      # span_id
        self.assertEqual(values[3], "test.span")   # name
        self.assertEqual(values[6], 1500)          # duration_ms
        self.assertEqual(values[7], "ok")          # status
        self.assertEqual(values[10], "alice")      # user_id from attrs
        self.assertEqual(values[11], "t1")         # tenant_id from attrs

    def test_duration_ms_computed(self):
        from _0_CorpAI._2_platform.observability.call_record import write_call_record

        span = self._make_span()
        # end_ts 已设,duration_ms 应是 int((end - start) * 1000)
        self.assertEqual(span.duration_ms, 1500)

    def test_attrs_json_serialized(self):
        from _0_CorpAI._2_platform.observability.call_record import write_call_record

        span = self._make_span(attrs={"k": "v", "n": 42})

        cur = MagicMock()
        class FakeConn:
            def cursor(self): return cur
            def commit(self): pass
            def close(self): pass
        real_conn = FakeConn()

        class FakeDBPool:
            @staticmethod
            def get():
                wrapper = MagicMock()
                wrapper.get_conn.return_value = real_conn
                return wrapper

        with patch.object(call_record, "DatabasePool", new=FakeDBPool):
            write_call_record(span)

        # attributes_json 第 8 个 column,parse 应是 dict
        attrs_json = cur.execute.call_args[0][1][8]
        self.assertIsInstance(attrs_json, str)
        parsed = json.loads(attrs_json)
        self.assertEqual(parsed["k"], "v")
        self.assertEqual(parsed["n"], 42)


if __name__ == "__main__":
    unittest.main()