"""Incident Manager 测试 — 关联告警 + 状态机 + 去重。

覆盖:
- 单 alert → 新 incident
- 多 alert 同 service 5min 内 → 关联
- 多 alert 不同 service → 各自 incident
- severity 取最高
- alert fingerprint 重复 → 跳过(不重复计数)
- 状态机:合法转换 + 非法转换拒绝
- 5min 外的 alert → 新 incident(换 bucket)
- 聚合 labels + annotations
- stats / list_active / get_by_id
"""
import unittest
from datetime import datetime, timedelta

from sre_copilot.incident_manager import (
    IncidentAlert,
    IncidentManager,
    IncidentStatus,
    compute_incident_fingerprint,
)


def _alert(
    fingerprint: str = "abc123",
    alertname: str = "HighCPU",
    severity: str = "critical",
    service: str = "payment",
    labels: dict | None = None,
    annotations: dict | None = None,
) -> IncidentAlert:
    return IncidentAlert(
        fingerprint=fingerprint,
        alertname=alertname,
        severity=severity,
        service=service,
        labels=labels or {"alertname": alertname, "severity": severity, "service": service},
        annotations=annotations or {"summary": f"{alertname} 触发"},
    )


class TestSingleAlert(unittest.TestCase):
    def test_first_alert_creates_incident(self):
        mgr = IncidentManager()
        now = datetime(2026, 8, 9, 10, 0, 0)
        inc = mgr.ingest(_alert(fingerprint="fp1"), now=now)
        self.assertEqual(inc.alert_count, 1)
        self.assertEqual(inc.service, "payment")
        self.assertEqual(inc.severity, "critical")
        self.assertEqual(inc.status, IncidentStatus.OPEN)
        self.assertIn("INC-", inc.incident_id)
        self.assertEqual(inc.alert_fingerprints, ["fp1"])

    def test_inc_id_contains_service_and_severity(self):
        mgr = IncidentManager()
        now = datetime(2026, 8, 9, 10, 0, 0)
        inc = mgr.ingest(_alert(service="auth"), now=now)
        self.assertIn("auth", inc.aggregated_labels["service"])


class TestCorrelation(unittest.TestCase):
    def test_same_service_within_window_associates(self):
        mgr = IncidentManager()
        now = datetime(2026, 8, 9, 10, 0, 0)
        inc1 = mgr.ingest(_alert(fingerprint="a1", alertname="HighCPU"), now=now)
        # 同一窗口(2 分钟后再来一个相关 alert)
        inc2 = mgr.ingest(
            _alert(fingerprint="a2", alertname="DBConnectionError"),
            now=now + timedelta(minutes=2),
        )
        self.assertEqual(inc1.incident_id, inc2.incident_id)
        self.assertEqual(inc2.alert_count, 2)
        self.assertEqual(set(inc2.alert_fingerprints), {"a1", "a2"})

    def test_different_services_create_separate_incidents(self):
        mgr = IncidentManager()
        now = datetime(2026, 8, 9, 10, 0, 0)
        inc_payment = mgr.ingest(_alert(fingerprint="p1", service="payment"), now=now)
        inc_auth = mgr.ingest(_alert(fingerprint="a1", service="auth"), now=now)
        self.assertNotEqual(inc_payment.incident_id, inc_auth.incident_id)

    def test_outside_window_creates_new_incident(self):
        mgr = IncidentManager()
        now = datetime(2026, 8, 9, 10, 0, 0)
        # 第 1 个
        inc1 = mgr.ingest(_alert(fingerprint="a1"), now=now)
        # 6 分钟后(超过 5min 窗口,落进新 bucket)
        inc2 = mgr.ingest(
            _alert(fingerprint="a2"), now=now + timedelta(minutes=6),
        )
        self.assertNotEqual(inc1.incident_id, inc2.incident_id)

    def test_duplicate_alert_fingerprint_skipped(self):
        mgr = IncidentManager()
        now = datetime(2026, 8, 9, 10, 0, 0)
        inc1 = mgr.ingest(_alert(fingerprint="same"), now=now)
        inc2 = mgr.ingest(_alert(fingerprint="same"), now=now)
        self.assertEqual(inc2.alert_count, 1)
        self.assertEqual(inc1.incident_id, inc2.incident_id)


class TestSeverityAggregation(unittest.TestCase):
    def test_takes_higher_severity(self):
        mgr = IncidentManager()
        now = datetime(2026, 8, 9, 10, 0, 0)
        mgr.ingest(_alert(fingerprint="w", severity="warning"), now=now)
        inc = mgr.ingest(_alert(fingerprint="c", severity="critical"), now=now)
        self.assertEqual(inc.severity, "critical")

    def test_keeps_higher_severity_when_new_is_lower(self):
        mgr = IncidentManager()
        now = datetime(2026, 8, 9, 10, 0, 0)
        mgr.ingest(_alert(fingerprint="c", severity="critical"), now=now)
        inc = mgr.ingest(_alert(fingerprint="w", severity="warning"), now=now)
        self.assertEqual(inc.severity, "critical")


class TestLabelAggregation(unittest.TestCase):
    def test_labels_merged(self):
        mgr = IncidentManager()
        now = datetime(2026, 8, 9, 10, 0, 0)
        mgr.ingest(
            _alert(fingerprint="a1", labels={"a": "1", "b": "2"}),
            now=now,
        )
        inc = mgr.ingest(
            _alert(fingerprint="a2", labels={"a": "1", "b": "3", "c": "4"}),
            now=now,
        )
        self.assertEqual(inc.aggregated_labels["a"], "1")  # 同值
        self.assertIn("b_conflict", inc.aggregated_labels)  # 冲突标记
        self.assertEqual(inc.aggregated_labels["b_conflict"], "3")
        self.assertEqual(inc.aggregated_labels["c"], "4")  # 新增


class TestStateMachine(unittest.TestCase):
    def setUp(self):
        self.mgr = IncidentManager()
        now = datetime(2026, 8, 9, 10, 0, 0)
        self.inc = self.mgr.ingest(_alert(), now=now)

    def test_open_to_investigating(self):
        self.mgr.transition(self.inc.incident_id, IncidentStatus.INVESTIGATING)
        self.assertEqual(self.mgr.get_by_id(self.inc.incident_id).status,
                         IncidentStatus.INVESTIGATING)

    def test_full_happy_path(self):
        mgr = self.mgr
        for nxt in [IncidentStatus.INVESTIGATING, IncidentStatus.PLAN_PENDING,
                    IncidentStatus.APPROVED, IncidentStatus.EXECUTING,
                    IncidentStatus.MITIGATED, IncidentStatus.RESOLVED]:
            mgr.transition(self.inc.incident_id, nxt)
        self.assertEqual(mgr.get_by_id(self.inc.incident_id).status,
                         IncidentStatus.RESOLVED)

    def test_invalid_transition_rejected(self):
        # open → approved 跳过中间,非法
        with self.assertRaises(ValueError) as ctx:
            self.mgr.transition(self.inc.incident_id, IncidentStatus.APPROVED)
        self.assertIn("非法状态转换", str(ctx.exception))

    def test_resolved_is_terminal(self):
        self.mgr.transition(self.inc.incident_id, IncidentStatus.RESOLVED)
        with self.assertRaises(ValueError):
            self.mgr.transition(self.inc.incident_id, IncidentStatus.INVESTIGATING)

    def test_failed_can_retry(self):
        self.mgr.transition(self.inc.incident_id, IncidentStatus.FAILED)
        # failed → investigating 合法(可重试)
        self.mgr.transition(self.inc.incident_id, IncidentStatus.INVESTIGATING)
        self.assertEqual(self.mgr.get_by_id(self.inc.incident_id).status,
                         IncidentStatus.INVESTIGATING)


class TestQueries(unittest.TestCase):
    def test_get_by_id(self):
        mgr = IncidentManager()
        now = datetime(2026, 8, 9, 10, 0, 0)
        inc = mgr.ingest(_alert(), now=now)
        self.assertEqual(mgr.get_by_id(inc.incident_id).incident_id, inc.incident_id)
        self.assertIsNone(mgr.get_by_id("INC-nonexistent"))

    def test_list_active(self):
        mgr = IncidentManager()
        now = datetime(2026, 8, 9, 10, 0, 0)
        inc1 = mgr.ingest(_alert(fingerprint="1", service="payment"), now=now)
        inc2 = mgr.ingest(_alert(fingerprint="2", service="auth"), now=now)
        # 关闭 inc1
        mgr.transition(inc1.incident_id, IncidentStatus.RESOLVED)
        active = mgr.list_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].incident_id, inc2.incident_id)

    def test_stats(self):
        mgr = IncidentManager()
        now = datetime(2026, 8, 9, 10, 0, 0)
        mgr.ingest(_alert(), now=now)
        stats = mgr.stats()
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["active"], 1)
        self.assertEqual(stats["by_status"]["open"], 1)


class TestFingerprint(unittest.TestCase):
    def test_same_inputs_same_fingerprint(self):
        now = datetime(2026, 8, 9, 10, 0, 0)
        labels = {"alertname": "HighCPU", "service": "payment"}
        fp1 = compute_incident_fingerprint("payment", labels, now)
        fp2 = compute_incident_fingerprint("payment", labels, now)
        self.assertEqual(fp1, fp2)

    def test_different_service_different_fingerprint(self):
        now = datetime(2026, 8, 9, 10, 0, 0)
        labels = {"alertname": "HighCPU"}
        fp1 = compute_incident_fingerprint("payment", labels, now)
        fp2 = compute_incident_fingerprint("auth", labels, now)
        self.assertNotEqual(fp1, fp2)

    def test_different_bucket_different_fingerprint(self):
        labels = {"alertname": "HighCPU"}
        fp1 = compute_incident_fingerprint(
            "payment", labels, datetime(2026, 8, 9, 10, 0, 0),
        )
        fp2 = compute_incident_fingerprint(
            "payment", labels, datetime(2026, 8, 9, 10, 10, 0),  # 跨 5min 窗口
        )
        self.assertNotEqual(fp1, fp2)


if __name__ == "__main__":
    unittest.main()
