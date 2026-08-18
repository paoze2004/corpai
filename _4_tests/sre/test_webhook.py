"""Alertmanager Webhook 测试 — 验证 webhook payload → Incident 关联。

覆盖:
- firing alert → 新 incident
- 同 service 5min 内多 alert → 关联到同一 incident
- resolved alert → 反查 incident 标 resolved
- 空 alerts 列表 → received=0
- 无效 JSON → 400
- 缺 labels.service → 仍能处理(默认 unknown)
"""
import unittest

from fastapi.testclient import TestClient

# 用单测 client 跑 webhook 路由(挂到一个临时 FastAPI app)
from _0_CorpAI._2_platform.sre.webhook import get_incident_manager, router


def _make_client() -> TestClient:
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _alertmanager_payload(alerts: list[dict], version: str = "4") -> dict:
    return {"version": version, "status": "firing", "alerts": alerts}


def _alert(
    fp: str = "fp1",
    alertname: str = "HighCPU",
    severity: str = "critical",
    service: str = "payment",
    status: str = "firing",
    starts_at: str = "2026-08-09T10:00:00Z",
) -> dict:
    return {
        "status": status,
        "labels": {
            "alertname": alertname, "severity": severity, "service": service,
        },
        "annotations": {"summary": f"{alertname} 触发"},
        "startsAt": starts_at,
        "fingerprint": fp,
        "generatorURL": "http://prometheus/graph",
    }


class TestWebhook(unittest.TestCase):
    def setUp(self):
        # 每个 test 重新初始化 manager
        from _0_CorpAI._2_platform.sre import webhook as _webhook
        _webhook._incident_manager = None
        self.client = _make_client()

    def test_single_firing_alert(self):
        body = _alertmanager_payload([_alert(fp="a1")])
        resp = self.client.post("/webhook/alertmanager", json=body)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["received"], 1)
        self.assertEqual(len(data["incidents"]), 1)
        inc = data["incidents"][0]
        self.assertEqual(inc["service"], "payment")
        self.assertEqual(inc["severity"], "critical")
        self.assertEqual(inc["alert_count"], 1)

    def test_related_alerts_same_incident(self):
        body = _alertmanager_payload([
            _alert(fp="a1", alertname="HighCPU"),
            _alert(fp="a2", alertname="DBConnectionError"),
        ])
        resp = self.client.post("/webhook/alertmanager", json=body)
        data = resp.json()
        # 同 service → 同一 incident
        self.assertEqual(len(data["incidents"]), 2)
        self.assertEqual(
            data["incidents"][0]["incident_id"],
            data["incidents"][1]["incident_id"],
        )
        # 第 2 个 alert_count=2
        self.assertEqual(data["incidents"][1]["alert_count"], 2)

    def test_resolved_alert_marks_incident(self):
        # 先 firing 一个
        body = _alertmanager_payload([_alert(fp="a1")])
        resp = self.client.post("/webhook/alertmanager", json=body)
        incident_id = resp.json()["incidents"][0]["incident_id"]

        # 再 resolved 同一个
        body2 = _alertmanager_payload([_alert(fp="a1", status="resolved")])
        resp2 = self.client.post("/webhook/alertmanager", json=body2)
        data = resp2.json()
        self.assertEqual(data["incidents"][0]["action"], "resolved")
        self.assertEqual(data["incidents"][0]["incident_id"], incident_id)
        # 状态应是 resolved
        inc = get_incident_manager().get_by_id(incident_id)
        self.assertEqual(inc.status, "resolved")

    def test_empty_alerts(self):
        body = _alertmanager_payload([])
        resp = self.client.post("/webhook/alertmanager", json=body)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["received"], 0)

    def test_invalid_json(self):
        resp = self.client.post(
            "/webhook/alertmanager",
            data="not json",
            headers={"content-type": "application/json"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_missing_service_label(self):
        """alert 没 service label → 默认 'unknown',仍能处理。"""
        alert = _alert(fp="x")
        del alert["labels"]["service"]
        body = _alertmanager_payload([alert])
        resp = self.client.post("/webhook/alertmanager", json=body)
        data = resp.json()
        self.assertEqual(data["received"], 1)
        self.assertEqual(data["incidents"][0]["service"], "unknown")

    def test_health_endpoint(self):
        resp = self.client.get("/webhook/alertmanager/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_resolved_unknown_alert_does_nothing(self):
        """resolved 一个从未见过的 fingerprint → 无 incident_id。"""
        body = _alertmanager_payload([_alert(fp="never_seen", status="resolved")])
        resp = self.client.post("/webhook/alertmanager", json=body)
        data = resp.json()
        self.assertIsNone(data["incidents"][0]["incident_id"])


if __name__ == "__main__":
    unittest.main()
