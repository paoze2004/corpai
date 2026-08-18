"""sre_copilot 常量集中。

避免 magic number 散落各处。改这里一处生效。
"""
from __future__ import annotations


# ── Re-plan(M4) ──
MAX_REPLANS = 2  # 防止 verify fail 无限循环


# ── Demo Runner(M5) ──
SSE_HEARTBEAT_TIMEOUT_SEC = 120  # SSE 客户端心跳超时(>此时间没事件,推 heartbeat)


# ── Agent Prompt 注入(M3) ──
# 历史 incident 最多返回条数(避免 LLM prompt 过长)
MAX_HISTORICAL_INCIDENTS = 3
# Log samples 最多保留条数(只保留关键 error pattern)
MAX_LOG_SAMPLES = 5
# 每个 log sample 截断字符数(避免 prompt 爆)
LOG_SAMPLE_MAX_CHARS = 300


# ── Kafka Pipeline(M6) ──
KAFKA_EVIDENCE_TOPICS = (
    "sre.alerts", "sre.metrics", "sre.k8s", "sre.logs", "sre.historical",
)
KAFKA_ACTIONS_TOPIC = "sre.actions"
KAFKA_AUDIT_TOPIC = "sre.audit"
KAFKA_PIPELINE_GROUP = "sre-pipeline"
KAFKA_EXECUTOR_GROUP = "sre-executor"


# ── Verification(M4)──
# DRY_RUN 验证通过概率(80% 通过 / 20% re-plan)— 演示需要一些戏剧性
DRY_RUN_VERIFY_PASS_RATE = 0.8


# ── Feishu(M3)──
# 是否真发飞书 webhook(默认 false,只构造 payload)
# 生产设 true 需要配置飞书 webhook + handle_approve_callback
FEISHU_WEBHOOK_ENABLED = False


__all__ = [
    "MAX_REPLANS",
    "SSE_HEARTBEAT_TIMEOUT_SEC",
    "MAX_HISTORICAL_INCIDENTS",
    "MAX_LOG_SAMPLES",
    "LOG_SAMPLE_MAX_CHARS",
    "KAFKA_EVIDENCE_TOPICS",
    "KAFKA_ACTIONS_TOPIC",
    "KAFKA_AUDIT_TOPIC",
    "KAFKA_PIPELINE_GROUP",
    "KAFKA_EXECUTOR_GROUP",
    "DRY_RUN_VERIFY_PASS_RATE",
    "FEISHU_WEBHOOK_ENABLED",
]