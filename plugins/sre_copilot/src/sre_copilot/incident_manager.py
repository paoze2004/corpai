"""SRE Incident Manager — 关联 alert → incident(去重 + 状态机)。

设计:
- 多个 Alert(同 service + 5min 时间窗)合并成一个 Incident
- Incident 状态机:open → investigating → mitigated → resolved
- fingerprint = sha256(service + sorted(labels) + 5min_window)
- 同 fingerprint 的 alert → 关联到现有 incident(只更新 labels 聚合 + last_alert_at)

数据流:
  Alertmanager webhook → IncidentManager.ingest(alert) → incident_id
  → AI Agent 拿 incident_id 去查询上下文 → 生成 plan

为什么不是用 Redis Stream 做关联:
  - Redis Stream 是 Executor 通信用(approval → execute)
  - Incident 关联走 MySQL(sre_incidents + sre_alerts 1:N)
  - 关联需要在 webhook 入口同步完成(<100ms),不能异步
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# ─── 状态机 ───

class IncidentStatus:
    """Incident 状态机(枚举常量)。"""
    OPEN = "open"               # 刚收到第一个 alert
    INVESTIGATING = "investigating"  # AI Agent 正在分析
    PLAN_PENDING = "plan_pending"    # plan 已生成,等人工批准
    APPROVED = "approved"       # 人已批准,等 Executor 执行
    EXECUTING = "executing"     # Executor 正在执行
    MITIGATED = "mitigated"     # action 已执行,等验证
    RESOLVED = "resolved"       # 验证通过,incident 关闭
    FAILED = "failed"           # 验证失败,需人工接管


# 合法状态转换图
VALID_TRANSITIONS: dict[str, set[str]] = {
    IncidentStatus.OPEN: {IncidentStatus.INVESTIGATING, IncidentStatus.RESOLVED, IncidentStatus.FAILED},
    IncidentStatus.INVESTIGATING: {
        IncidentStatus.PLAN_PENDING, IncidentStatus.RESOLVED, IncidentStatus.FAILED,
    },
    IncidentStatus.PLAN_PENDING: {IncidentStatus.APPROVED, IncidentStatus.FAILED},
    IncidentStatus.APPROVED: {IncidentStatus.EXECUTING, IncidentStatus.FAILED},
    IncidentStatus.EXECUTING: {IncidentStatus.MITIGATED, IncidentStatus.FAILED},
    IncidentStatus.MITIGATED: {IncidentStatus.RESOLVED, IncidentStatus.FAILED},
    IncidentStatus.RESOLVED: set(),  # 终态
    IncidentStatus.FAILED: {IncidentStatus.INVESTIGATING, IncidentStatus.RESOLVED},  # 可重试
}


# ─── 数据模型 ───

@dataclass
class IncidentAlert:
    """单条 alert(从 Alertmanager webhook payload 解出来的最小子集)。"""
    fingerprint: str        # Alertmanager 给的 alert fingerprint
    alertname: str
    severity: str
    service: str
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    starts_at: str = ""
    generator_url: str = ""

    @classmethod
    def from_prometheus(cls, payload: dict[str, Any]) -> IncidentAlert:
        """Alertmanager v4 webhook payload → IncidentAlert。

        真实 webhook 格式:
          {
            "version": "4",
            "status": "firing",
            "alerts": [{
              "status": "firing",
              "labels": {"alertname": "HighCPU", "severity": "critical", "service": "payment"},
              "annotations": {"summary": "...", "description": "..."},
              "startsAt": "2026-08-09T10:00:00Z",
              "fingerprint": "abc123",
              "generatorURL": "http://prometheus/..."
            }],
            "groupLabels": {...}
          }
        """
        return cls(
            fingerprint=payload.get("fingerprint", ""),
            alertname=payload.get("labels", {}).get("alertname", "unknown"),
            severity=payload.get("labels", {}).get("severity", "info"),
            service=payload.get("labels", {}).get("service", "unknown"),
            labels=payload.get("labels", {}),
            annotations=payload.get("annotations", {}),
            starts_at=payload.get("startsAt", ""),
            generator_url=payload.get("generatorURL", ""),
        )


@dataclass
class Incident:
    """合并后的 incident(sre_incidents 表单行)。"""
    incident_id: str            # 内部 UUID
    service: str
    severity: str               # 取所有 alert 中最高的
    status: str = IncidentStatus.OPEN
    title: str = ""
    fingerprint: str = ""       # 用于去重
    alert_count: int = 1        # 关联的 alert 数
    first_alert_at: str = ""
    last_alert_at: str = ""
    alert_fingerprints: list[str] = field(default_factory=list)
    aggregated_labels: dict[str, str] = field(default_factory=dict)
    aggregated_annotations: dict[str, str] = field(default_factory=dict)
    jira_issue_key: str = ""    # 如果已创建 Jira 工单
    plan_id: str = ""           # 关联的 sre_action_plans.id(如有)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ─── 关联逻辑 ───

# 同 incident 的合并窗口(默认 5 分钟,5min 内的 alert 视为同一事故)
DEDUP_WINDOW = timedelta(minutes=5)

# severity 排序(从高到低)
SEVERITY_ORDER = {"critical": 4, "error": 3, "warning": 2, "info": 1}


def compute_incident_fingerprint(service: str, labels: dict[str, str], now: datetime) -> str:
    """算 incident 的去重 fingerprint。

    规则:同 service + 5min 时间窗 → 同 incident。
    alertname / severity / 具体 labels **不**作为分桶 key,因为:
      - 一个服务的多个 alert(HighCPU + DBConnectionError)通常同根因,应合并
      - severity 会随时间升级(critical 在升级时不该分裂成新 incident)
      - 实际生产可加 cluster/region/namespace 作为二级分桶

    labels 参数保留用于未来 cluster 分桶扩展,当前不参与 hash。
    """
    # 5min 时间窗
    bucket = int(now.timestamp() // DEDUP_WINDOW.total_seconds())
    payload = f"{service}|{bucket}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def aggregate_severity(existing: str, new: str) -> str:
    """取多个 alert 中 severity 最高的。"""
    return new if SEVERITY_ORDER.get(new, 0) > SEVERITY_ORDER.get(existing, 0) else existing


def merge_labels(a: dict[str, str], b: dict[str, str]) -> dict[str, str]:
    """合并 labels(b 覆盖 a,值不同的 key 加 _conflict 标记)。"""
    merged = dict(a)
    for k, v in b.items():
        if k not in merged:
            merged[k] = v
        elif merged[k] != v:
            merged[f"{k}_conflict"] = v  # 标记冲突
    return merged


# ─── Incident Manager 主类 ───

class IncidentManager:
    """关联 alert → incident(内存实现,生产可换 MySQL 持久化)。

    用法:
        mgr = IncidentManager()
        for alert_payload in webhook_payload["alerts"]:
            alert = IncidentAlert.from_prometheus(alert_payload)
            incident = mgr.ingest(alert)
            # incident.incident_id 给 AI Agent 去查询上下文
    """

    def __init__(self, window: timedelta = DEDUP_WINDOW) -> None:
        self.window = window
        # incident_fingerprint → Incident
        self._incidents: dict[str, Incident] = {}
        # alert_fingerprint → incident_fingerprint(反向索引)
        self._alert_index: dict[str, str] = {}

    def ingest(self, alert: IncidentAlert, now: datetime | None = None) -> Incident:
        """接 alert:找现有 incident 关联 / 或建新 incident。

        返回关联后的 Incident(新或更新)。
        """
        now = now or datetime.now()
        incident_fp = compute_incident_fingerprint(
            alert.service, alert.labels, now,
        )

        if incident_fp in self._incidents:
            return self._associate(alert, incident_fp, now)
        return self._create(alert, incident_fp, now)

    def _associate(
        self, alert: IncidentAlert, incident_fp: str, now: datetime,
    ) -> Incident:
        """alert 关联到现有 incident。"""
        inc = self._incidents[incident_fp]
        # 同 alert fingerprint 不重复加
        if alert.fingerprint in inc.alert_fingerprints:
            logger.debug(f"alert {alert.fingerprint} 已关联,跳过")
            return inc

        inc.alert_count += 1
        inc.last_alert_at = alert.starts_at or now.isoformat()
        inc.alert_fingerprints.append(alert.fingerprint)
        inc.severity = aggregate_severity(inc.severity, alert.severity)
        inc.aggregated_labels = merge_labels(inc.aggregated_labels, alert.labels)
        inc.aggregated_annotations = merge_labels(inc.aggregated_annotations, alert.annotations)
        inc.updated_at = now.isoformat()

        self._alert_index[alert.fingerprint] = incident_fp
        logger.info(
            f"alert 关联到现有 incident:{inc.incident_id} "
            f"service={inc.service} alert_count={inc.alert_count} "
            f"severity={inc.severity}",
        )
        return inc

    def _create(
        self, alert: IncidentAlert, incident_fp: str, now: datetime,
    ) -> Incident:
        """alert 不在现有 incident → 建新 incident。"""
        inc = Incident(
            incident_id=f"INC-{now.strftime('%Y%m%d%H%M%S')}-{incident_fp[:6]}",
            service=alert.service,
            severity=alert.severity,
            status=IncidentStatus.OPEN,
            title=alert.annotations.get("summary", alert.alertname),
            fingerprint=incident_fp,
            alert_count=1,
            first_alert_at=alert.starts_at or now.isoformat(),
            last_alert_at=alert.starts_at or now.isoformat(),
            alert_fingerprints=[alert.fingerprint],
            aggregated_labels=dict(alert.labels),
            aggregated_annotations=dict(alert.annotations),
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )
        self._incidents[incident_fp] = inc
        self._alert_index[alert.fingerprint] = incident_fp
        logger.info(
            f"新 incident:{inc.incident_id} service={inc.service} "
            f"severity={inc.severity} alertname={alert.alertname}",
        )
        return inc

    def get_by_id(self, incident_id: str) -> Incident | None:
        """按 incident_id 查(用于 AI Agent 反查)。"""
        for inc in self._incidents.values():
            if inc.incident_id == incident_id:
                return inc
        return None

    def get_by_alert_fingerprint(self, alert_fingerprint: str) -> Incident | None:
        """按 alert fingerprint 反查 incident(给 webhook resolved 路径用)。

        用 _alert_index 反向索引 O(1)。
        """
        incident_fp = self._alert_index.get(alert_fingerprint)
        if incident_fp is None:
            return None
        return self._incidents.get(incident_fp)

    def transition(self, incident_id: str, new_status: str) -> Incident:
        """状态机转换:校验合法性 + 更新。"""
        inc = self.get_by_id(incident_id)
        if not inc:
            raise KeyError(f"incident {incident_id} 不存在")

        allowed = VALID_TRANSITIONS.get(inc.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"非法状态转换:{inc.status} → {new_status} "
                f"(允许:{sorted(allowed)})",
            )

        old_status = inc.status
        inc.status = new_status
        inc.updated_at = datetime.now().isoformat()
        logger.info(f"incident {incident_id} 状态:{old_status} → {new_status}")
        return inc

    def list_active(self) -> list[Incident]:
        """返回未关闭的 incident(供监控/报表)。"""
        return [i for i in self._incidents.values()
                if i.status not in (IncidentStatus.RESOLVED,)]

    def stats(self) -> dict[str, Any]:
        """统计信息(供 /metrics 或 admin 仪表盘)。"""
        by_status: dict[str, int] = {}
        for inc in self._incidents.values():
            by_status[inc.status] = by_status.get(inc.status, 0) + 1
        return {
            "total": len(self._incidents),
            "active": len(self.list_active()),
            "by_status": by_status,
        }


__all__ = [
    "DEDUP_WINDOW",
    "VALID_TRANSITIONS",
    "Incident",
    "IncidentAlert",
    "IncidentManager",
    "IncidentStatus",
    "aggregate_severity",
    "compute_incident_fingerprint",
    "merge_labels",
]
