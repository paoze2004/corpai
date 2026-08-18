"""
SRE Mock Data Producer — M6。

用途:启动后持续(或单次)模拟企业监控系统输出,向 Kafka 推"看起来像真的"
incident 关联数据。SRE Copilot Pipeline 消费这些 topic 后,行为跟接真
Prometheus/K8s/Loki 一样。

设计:
- 3 个 scenario(OOM / CPU 飙高 / 慢响应),每个都生成一组**关联事件**:
    sre.alerts  → sre.metrics → sre.k8s → sre.logs → sre.historical
  这模拟真实世界里"alert 先触发 → 各系统几乎同时(±秒)汇报证据"的时序。
- 数据 deterministic(同 scenario + 同 alert_id 跑两次结果一致),demo 可复现。
- CLI:`python _2_scripts/sre_mock_producer.py --scenario oom [--count 1]`
- 也可作为模块 import:`from _2_scripts.sre_mock_producer import produce_scenario`

Topic 约定(见 corpai-kafka.yml 注释):
  sre.alerts / sre.metrics / sre.k8s / sre.logs / sre.historical
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

# ── Kafka producer ─────────────────────────────────────────────
# aiokafka 是 async client,跟现有 codebase 一致(fastapi 全 async)
try:
    from aiokafka import AIOKafkaProducer
except ImportError:
    print("❌ aiokafka 未装,跑:uv add aiokafka", file=sys.stderr)
    raise


# ── Topic 名 ───────────────────────────────────────────────
TOPICS = {
    "alerts": "sre.alerts",
    "metrics": "sre.metrics",
    "k8s": "sre.k8s",
    "logs": "sre.logs",
    "historical": "sre.historical",
}


# ── 工具函数 ───────────────────────────────────────────────

def _now() -> str:
    """ISO8601 UTC,精确到秒。"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _alert_id() -> str:
    return f"alt-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _kafka_key(alert_id: str, sub_key: str = "") -> bytes:
    """Kafka message key — 用 alert_id 让同一 alert 的事件落同一 partition。"""
    return f"{alert_id}:{sub_key}".encode("utf-8")


async def _send(producer: AIOKafkaProducer, topic: str, key: str, payload: dict) -> None:
    """推一条 JSON event 到指定 topic。"""
    raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    # key 可能是 str 或 bytes(_kafka_key 返 bytes) — aiokafka 都要 bytes
    key_bytes = key if isinstance(key, bytes) else key.encode("utf-8") if key else None
    await producer.send_and_wait(topic, value=raw, key=key_bytes)
    # 打印用 str
    key_str = key if isinstance(key, str) else key.decode("utf-8") if key else ""
    print(f"  [{topic:20s}] {key_str[:40]:40s} {len(raw):5d} bytes")


# ── Scenario 数据模板 ─────────────────────────────────────────

def _oom_scenario(alert_id: str) -> dict[str, list[dict]]:
    """OOMKilled 场景:order-api JVM heap 满,pod 重启循环。

    返回 5 类 topic 的事件列表。"""
    started = _now()
    pod1, pod2 = f"order-api-abc-123", f"order-api-abc-124"

    return {
        "alerts": [{
            "alert_id": alert_id,
            "alert": "OrderServiceHighErrorRate",
            "service": "order-api",
            "severity": "P2",
            "started_at": started,
            "labels": {
                "alertname": "OrderServiceHighErrorRate",
                "severity": "P2",
                "service": "order-api",
                "namespace": "production",
            },
            "annotations": {
                "summary": "order-api 5xx error rate 23% (threshold 5%)",
                "description": "Pod OOMKilled, JVM heap exhausted",
            },
        }],
        "metrics": [
            {"alert_id": alert_id, "metric": "http_requests_error_rate",
             "service": "order-api", "value": 23.4, "unit": "%", "window": "5m",
             "timestamp": started, "severity": "critical"},
            {"alert_id": alert_id, "metric": "http_requests_p99_latency",
             "service": "order-api", "value": 8.2, "unit": "s", "window": "5m",
             "timestamp": started, "severity": "critical"},
            {"alert_id": alert_id, "metric": "jvm_heap_used_ratio",
             "service": "order-api", "value": 99.1, "unit": "%", "window": "1m",
             "timestamp": started, "severity": "critical"},
        ],
        "k8s": [
            {"alert_id": alert_id, "event_type": "pod_oomkilled",
             "pod": pod1, "namespace": "production",
             "timestamp": (datetime.now(timezone.utc) - timedelta(seconds=22)).isoformat().replace("+00:00", "Z"),
             "memory_limit": "1Gi", "restart_count": 23},
            {"alert_id": alert_id, "event_type": "pod_oomkilled",
             "pod": pod2, "namespace": "production",
             "timestamp": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat().replace("+00:00", "Z"),
             "memory_limit": "1Gi", "restart_count": 24},
            {"alert_id": alert_id, "event_type": "pod_restart_loop",
             "pod": pod1, "namespace": "production",
             "timestamp": started,
             "restarts_last_1h": 47, "backoff_active": True},
            {"alert_id": alert_id, "event_type": "pod_state",
             "pod": pod1, "namespace": "production",
             "timestamp": started, "phase": "CrashLoopBackOff"},
        ],
        "logs": [
            {"alert_id": alert_id, "pod": pod1, "level": "ERROR",
             "timestamp": (datetime.now(timezone.utc) - timedelta(seconds=23)).isoformat().replace("+00:00", "Z"),
             "message": "java.lang.OutOfMemoryError: Java heap space",
             "stack": [
                 "at com.order.payment.PaymentService.process(PaymentService.java:142)",
                 "at com.order.payment.PaymentService.handleRequest(PaymentService.java:89)",
                 "at org.springframework.web.servlet.DispatcherServlet.doDispatch(DispatcherServlet.java:1067)",
             ]},
            {"alert_id": alert_id, "pod": pod2, "level": "ERROR",
             "timestamp": (datetime.now(timezone.utc) - timedelta(seconds=6)).isoformat().replace("+00:00", "Z"),
             "message": "java.lang.OutOfMemoryError: Java heap space",
             "stack": [
                 "at com.order.payment.PaymentService.process(PaymentService.java:142)",
             ]},
            {"alert_id": alert_id, "pod": pod1, "level": "WARN",
             "timestamp": (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat().replace("+00:00", "Z"),
             "message": "Tomcat JDBC pool exhausted, connection wait timeout",
             "stack": []},
        ],
        "historical": [{
            "alert_id": alert_id,
            "incidents": [
                {
                    "id": "INC-1024",
                    "occurred_at": "2025-08-01T10:23:00+08:00",
                    "service": "payment-service",
                    "similarity": 0.87,
                    "root_cause": "JVM heap 配 1Gi 偏小,高峰时段 OOMKilled",
                    "solution": [
                        "JVM Xmx 调到 2Gi",
                        "deployment 滚动重启",
                        "加 Prometheus heap_usage > 80% 告警",
                    ],
                    "runbook": "RUNBOOK-007-jvm-oom.md",
                },
                {
                    "id": "INC-1156",
                    "occurred_at": "2026-06-15T14:08:00+08:00",
                    "service": "order-service",
                    "similarity": 0.62,
                    "root_cause": "OrderCache 内存泄漏(连接未关)",
                    "solution": [
                        "fix ConnectionPool.close() 调用",
                        "deployment 滚动重启",
                    ],
                    "runbook": "RUNBOOK-012-memory-leak.md",
                },
            ],
        }],
    }


def _cpu_scenario(alert_id: str) -> dict[str, list[dict]]:
    """CPU 飙高 场景:order-api CPU 95%,可能死循环或外部慢调用。"""
    started = _now()
    pod = "order-api-xyz-789"

    return {
        "alerts": [{
            "alert_id": alert_id,
            "alert": "OrderServiceHighCPU",
            "service": "order-api",
            "severity": "P3",
            "started_at": started,
            "labels": {"alertname": "OrderServiceHighCPU", "severity": "P3", "service": "order-api"},
            "annotations": {
                "summary": "order-api CPU 95% (threshold 80%)",
                "description": "Sustained high CPU, possible infinite loop or slow external call",
            },
        }],
        "metrics": [
            {"alert_id": alert_id, "metric": "cpu_usage",
             "service": "order-api", "value": 95.3, "unit": "%", "window": "10m",
             "timestamp": started, "severity": "warning"},
            {"alert_id": alert_id, "metric": "gc_pause_total",
             "service": "order-api", "value": 12.4, "unit": "s/min", "window": "5m",
             "timestamp": started, "severity": "warning"},
        ],
        "k8s": [
            {"alert_id": alert_id, "event_type": "pod_state",
             "pod": pod, "namespace": "production",
             "timestamp": started, "phase": "Running",
             "cpu_throttled": False, "cpu_limit": "2"},
            {"alert_id": alert_id, "event_type": "hpa_status",
             "deployment": "order-api", "namespace": "production",
             "timestamp": started, "current_replicas": 5, "desired_replicas": 5,
             "cpu_avg": 95.3},
        ],
        "logs": [
            {"alert_id": alert_id, "pod": pod, "level": "WARN",
             "timestamp": started,
             "message": "GC overhead limit exceeded, 12s/min spent on GC",
             "stack": []},
            {"alert_id": alert_id, "pod": pod, "level": "WARN",
             "timestamp": started,
             "message": "Thread pool executor queue size: 847 (threshold 100)",
             "stack": []},
        ],
        "historical": [{
            "alert_id": alert_id,
            "incidents": [
                {
                    "id": "INC-2001",
                    "occurred_at": "2026-03-12T09:00:00+08:00",
                    "service": "order-api",
                    "similarity": 0.79,
                    "root_cause": "死循环 — 数据导出任务没限速,前端 polling 触发",
                    "solution": [
                        "加 rate limit",
                        "下线 buggy 客户端",
                    ],
                    "runbook": "RUNBOOK-021-cpu-loop.md",
                },
            ],
        }],
    }


def _slow_scenario(alert_id: str) -> dict[str, list[dict]]:
    """慢响应 场景:DB 慢查询导致接口 P99 超阈值。"""
    started = _now()
    pod = "order-api-def-456"

    return {
        "alerts": [{
            "alert_id": alert_id,
            "alert": "OrderServiceSlowResponse",
            "service": "order-api",
            "severity": "P3",
            "started_at": started,
            "labels": {"alertname": "OrderServiceSlowResponse", "severity": "P3", "service": "order-api"},
            "annotations": {
                "summary": "order-api P99 latency 5.2s (threshold 1s)",
                "description": "Slow DB queries detected",
            },
        }],
        "metrics": [
            {"alert_id": alert_id, "metric": "http_requests_p99_latency",
             "service": "order-api", "value": 5.2, "unit": "s", "window": "10m",
             "timestamp": started, "severity": "warning"},
            {"alert_id": alert_id, "metric": "db_query_avg_duration",
             "service": "order-api", "value": 4.8, "unit": "s", "window": "5m",
             "timestamp": started, "severity": "warning"},
        ],
        "k8s": [
            {"alert_id": alert_id, "event_type": "pod_state",
             "pod": pod, "namespace": "production",
             "timestamp": started, "phase": "Running"},
        ],
        "logs": [
            {"alert_id": alert_id, "pod": pod, "level": "WARN",
             "timestamp": started,
             "message": "Slow query detected: SELECT * FROM order_items WHERE ... (4.8s)",
             "stack": []},
            {"alert_id": alert_id, "pod": pod, "level": "WARN",
             "timestamp": started,
             "message": "DB connection pool 95% utilized",
             "stack": []},
        ],
        "historical": [{
            "alert_id": alert_id,
            "incidents": [
                {
                    "id": "INC-3001",
                    "occurred_at": "2026-04-22T16:00:00+08:00",
                    "service": "order-api",
                    "similarity": 0.81,
                    "root_cause": "DB 慢查询 — 缺索引 on order_items.user_id",
                    "solution": ["加复合索引 (user_id, created_at)"],
                    "runbook": "RUNBOOK-031-slow-query.md",
                },
            ],
        }],
    }


SCENARIOS = {
    "oom": _oom_scenario,
    "cpu": _cpu_scenario,
    "slow": _slow_scenario,
}


# ── Producer 主流程 ─────────────────────────────────────────

async def produce_scenario(
    producer: AIOKafkaProducer,
    scenario: str,
    alert_id: str | None = None,
    delay_ms: int = 50,
) -> str:
    """单次 scenario 推 5 topic 一组事件。返回 alert_id。"""
    if scenario not in SCENARIOS:
        raise ValueError(f"未知 scenario {scenario!r},可选: {list(SCENARIOS)}")
    aid = alert_id or _alert_id()
    print(f"\n=== Scenario: {scenario} | alert_id={aid} ===")

    events = SCENARIOS[scenario](aid)
    # 按"先 alert 后证据"顺序推,模拟真实时序
    for topic_key in ["alerts", "metrics", "k8s", "logs", "historical"]:
        topic = TOPICS[topic_key]
        for ev in events[topic_key]:
            # aiokafka 自动建 topic(若 KAFKA_AUTO_CREATE_TOPICS_ENABLE=true)
            # 但首次可能要等 metadata 同步,加个 retry
            for attempt in range(3):
                try:
                    await _send(producer, topic, _kafka_key(aid, topic_key), ev)
                    break
                except Exception as exc:
                    if attempt < 2 and "metadata" in str(exc).lower():
                        await asyncio.sleep(1)
                        continue
                    raise
            await asyncio.sleep(delay_ms / 1000)

    print(f"[OK] Scenario {scenario} done, 5 topics x N events sent, alert_id={aid}")
    return aid


async def main():
    parser = argparse.ArgumentParser(description="SRE Mock Data Producer")
    parser.add_argument(
        "--scenario", "-s", choices=list(SCENARIOS) + ["all"],
        default="oom", help="模拟的 incident 场景,all = 跑全部 3 个",
    )
    parser.add_argument(
        "--count", "-n", type=int, default=1,
        help="每个 scenario 跑几次(每次新 alert_id,模拟多个 incident)",
    )
    parser.add_argument(
        "--bootstrap-servers", "-b", default="localhost:9092",
        help="Kafka bootstrap servers",
    )
    parser.add_argument(
        "--delay-ms", type=int, default=50,
        help="每条 event 之间的间隔(ms),模拟真实时序",
    )
    args = parser.parse_args()

    scenarios = list(SCENARIOS) if args.scenario == "all" else [args.scenario]

    print(f"Mock Producer → Kafka: {args.bootstrap_servers}")
    print(f"Scenarios: {scenarios} × {args.count} 次")

    producer = AIOKafkaProducer(
        bootstrap_servers=args.bootstrap_servers,
        value_serializer=lambda v: v,  # 我们已经在 _send 里 encode 了
        client_id="sre-mock-producer",
    )
    await producer.start()
    try:
        for i in range(args.count):
            for s in scenarios:
                await produce_scenario(
                    producer, s,
                    alert_id=f"alt-batch{i}-{_alert_id().split('-')[-1]}",
                    delay_ms=args.delay_ms,
                )
                await asyncio.sleep(0.5)  # scenario 之间间隔
    finally:
        await producer.stop()
    print("\n✅ Mock Producer 全部完成。")


if __name__ == "__main__":
    asyncio.run(main())