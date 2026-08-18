"""Phase 4 test_metrics — Counter / Histogram / Info / _get_or_create 兜底。"""
import unittest

from prometheus_client import REGISTRY, Counter, Histogram, Info

from _0_CorpAI._2_platform.observability.metrics import (
    A2A_CALL_TOTAL,
    APP_INFO,
    DB_POOL_ACQUIRE_SECONDS,
    DB_POOL_EXHAUSTED_TOTAL,
    HTTP_REQUESTS,
    HTTP_REQUEST_DURATION,
    LLM_CALL_DURATION,
    LLM_CALL_TOTAL,
    _get_or_create,
    endpoint_label,
)


def _sample(name, labels=None):
    """读 sample 数值 — 用 REGISTRY.get_sample_value,不返回 collector。"""
    return REGISTRY.get_sample_value(name, labels or {})


class TestGetOrCreate(unittest.TestCase):
    def test_returns_same_for_same_name(self):
        c1 = _get_or_create(Counter, "_test_c", "doc", ["l"])
        c2 = _get_or_create(Counter, "_test_c", "doc", ["l"])
        self.assertIs(c1, c2)

    def test_raises_for_type_mismatch(self):
        # 先创建一个 Counter;再尝试以 Histogram 同名创建 → 触发异常
        c = _get_or_create(Counter, "_test_ty", "d", [])
        # 它已存在;Histogram 找同名(去 _total suffix)找不到,且不是 Histogram 类型
        with self.assertRaises(Exception):
            _get_or_create(Histogram, "_test_ty", "d", [])


class TestCounters(unittest.TestCase):
    """仅验证 inc 后 sample 数值 delta,不断言绝对值。"""

    def test_http_requests_delta(self):
        labels = {
            "method": "TEST",
            "endpoint": "/__observ_test__",
            "status": "299",
        }
        before = _sample("http_requests_total", labels) or 0
        HTTP_REQUESTS.labels(**labels).inc()
        after = _sample("http_requests_total", labels)
        self.assertEqual(after, before + 1)

    def test_a2a_label_status_independent(self):
        labels1 = {"agent": "TEST_A", "status": "ok"}
        labels2 = {"agent": "TEST_A", "status": "error"}
        b1 = _sample("a2a_call_total", labels1) or 0
        b2 = _sample("a2a_call_total", labels2) or 0
        A2A_CALL_TOTAL.labels(**labels1).inc()
        A2A_CALL_TOTAL.labels(**labels2).inc(2)
        self.assertEqual(_sample("a2a_call_total", labels1), b1 + 1)
        self.assertEqual(_sample("a2a_call_total", labels2), b2 + 2)

    def test_db_pool_exhausted_delta(self):
        before = _sample("db_pool_exhausted_total") or 0
        DB_POOL_EXHAUSTED_TOTAL.inc()
        after = _sample("db_pool_exhausted_total")
        self.assertEqual(after, before + 1)

    def test_llm_call_delta(self):
        labels = {"model": "TEST_M", "intent": "TEST_I"}
        before = _sample("llm_call_total", labels) or 0
        LLM_CALL_TOTAL.labels(**labels).inc()
        self.assertEqual(_sample("llm_call_total", labels), before + 1)


class TestHistogram(unittest.TestCase):
    def test_observe_delta_count(self):
        # Histogram 有 _count + _sum + _bucket 等 sample
        before = _sample("db_pool_acquire_seconds_count") or 0
        DB_POOL_ACQUIRE_SECONDS.observe(0.01)
        after = _sample("db_pool_acquire_seconds_count")
        self.assertEqual(after, before + 1)

    def test_llm_duration_observe(self):
        before = _sample("llm_call_duration_seconds_count", {"model": "TEST_M"}) or 0
        LLM_CALL_DURATION.labels(model="TEST_M").observe(0.1)
        after = _sample("llm_call_duration_seconds_count", {"model": "TEST_M"})
        self.assertEqual(after, before + 1)


class TestInfo(unittest.TestCase):
    def test_app_info_in_registry(self):
        # Info 会被转成 *_info gauge,value=1
        # 验证 corpai_app_info 在 generate_latest 输出里
        from prometheus_client import generate_latest
        out = generate_latest().decode()
        self.assertIn("corpai_app_info", out)
        self.assertIn("component=\"observability\"", out)
        self.assertIn("version=\"phase4\"", out)


class TestEndpointLabel(unittest.TestCase):
    def test_with_route(self):
        class FakeRoute:
            path = "/admin/users"
        scope = {"route": FakeRoute()}
        self.assertEqual(endpoint_label(scope), "/admin/users")

    def test_without_route(self):
        self.assertEqual(endpoint_label({}), "__unmatched__")

    def test_none_route(self):
        self.assertEqual(endpoint_label({"route": None}), "__unmatched__")


if __name__ == "__main__":
    unittest.main()