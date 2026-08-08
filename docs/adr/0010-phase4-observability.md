# ADR-010: Phase 4 Observability 选型

## 状态
**Accepted** — 2026-08-06

## 背景

CLAUDE.md / REFACTOR_PLAN 把"Phase 4 Observability"列为路线图 W9-W10,目标:
- 结构化日志(JSON,trace_id 自动注入)
- 全链路 trace_id(从 HTTP middleware 到 LLM / A2A / DB)
- call_records 表(每个 Span 落库,辅助性能/错误/调用链分析)
- Prometheus `/metrics` 端点

## 决策

**采用 prometheus_client + 自写轻量 ContextVar trace + JSON logging + 独立 call_records;
本阶段不引入 OpenTelemetry。**

### 1. prometheus_client(准许的新 dep — 用户决策)

`prometheus-client>=0.20` 加在 `pyproject.toml`,生成:
- `HTTP_REQUESTS` / `HTTP_REQUEST_DURATION` / `DB_POOL_ACQUIRE_SECONDS` / `DB_POOL_EXHAUSTED_TOTAL` /
  `LLM_CALL_TOTAL` / `LLM_CALL_DURATION` / `A2A_CALL_TOTAL` / `APP_INFO`

理由:Python 生态事实标准,提供 Counter / Histogram / Gauge / Info / Enum + `generate_latest()` exposition。
零替代方案:手写 /metrics text format + dict in-memory metrics 跨进程不准;Phase 4 MVP 不能容忍。

### 2. 自写轻量 trace(stdlib `contextvars`,不引 OTel)

- `contextvars.ContextVar[str | None]` 存 `trace_id` / `span_id` / `parent_span_id`
- `Span` dataclass + `@contextmanager start_span(name, attributes)`
- `to_thread_propagating(func)` — `copy_context().run()` + `run_in_executor`,解决 `asyncio.to_thread` 不传 ContextVar 的问题

理由:OpenTelemetry 完整 SDK + OTLP exporter + collector + 5+ 间接 dep(SDK / exporter / instrumentation-fastapi / instrumentation-httpx / instrumentation-sqlalchemy...);
当前部署是单机 FastAPI + 3 个 A2A 进程,暂无 collector 基础设施。Span 数据模型保留未来映射 OTel 能力(trace_id/span_id/parent_span_id/attributes 字段直接对应)。

### 3. JSON logging

`setup_json_logger(name, log_file)` 替换 `setup_logger` 入口(17 个调用方零改):
- `JsonFormatter`:每行一 JSON(UTC RFC3339 + 毫秒,固定字段 + extra 透传 + `default=str` 兜底)
- `TraceContextFilter`:每次 log 自动注入 `record.trace_id` / `record.span_id`,业务方 `extra={"trace_id": "x"}` 不覆盖
- 重复调用幂等(handler 加 `_corpai_json_handler` 标记)

### 4. 独立 call_records 表(不复用 auth_audit_log)

`call_records(id, trace_id, span_id, parent_span_id, name, ts_start, ts_end, duration_ms, status,
attributes_json, error_message, user_id, tenant_id)`,
`scriptsmigrate_add_observability.py` INFORMATION_SCHEMA 守卫幂等。

**双 trace 表语义边界**:
| 表 | 写入策略 | 失败行为 |
|---|---|---|
| `auth_audit_log`(Phase 3) | 安全审计(RBAC 决策) | **fail-closed** — raise HTTPException 500,阻断业务 |
| `call_records`(Phase 4) | 性能/调用链观测 | **warning 不阻断** — DB 不可用时只 log + metric 计数 |

## 后果

### 正面
- 端到端 trace_id 透传:HTTP middleware → OrchestratorService.chat() → A2A / LLM spans → 落 call_records
- 任何 LLM/A2A/DB 慢调用,查 call_records 即可定位
- Prometheus scrape `/metrics` 即可接 Grafana / 告警
- call_records + auth_audit_log 双表边界清晰,业务影响零

### 负面
- 同步 call_record INSERT 阻塞 event loop(每次 span 结束都借连接)— Phase 4 MVP 接受,Phase 6 改 batch writer
- call_records 无 retention / partition — 上线前必须配置外部定期清理
- /metrics 公开端点无 auth(Prometheus scraper 不能加 JWT)— 通过 NetworkPolicy 限制内网访问

### 中性
- A2A 跨进程 trace 不完整 — 本次只保证当前进程及 worker thread;Phase 6+ 评估 W3C `traceparent` 注入
- `chat_stream()` 未加 trace span(用户明确 Out)
- 实际无 OTel collector — Span 数据落 call_records 是唯一导出路径

## 未来重新评估 OTel 的触发条件

任一满足即重新评估:
- 部署 ≥ 3 个 A2A 微服务,需要 Jaeger/Tempo 跨进程 trace 关联
- 需要 trace_sample / tail-based sampling(目前全量写入 call_records)
- 出现 OTel 已大量被 Python 生态采用(otel-instrumentation-fastapi 自动埋点)
- 需要 OpenLineage / DataHub 等数据血缘集成

## 验证

- `make migrate-phase4` 幂等:第一次 applied=1 skipped=0,第二次 applied=0 skipped=1
- `make test-observability` 41 passed
- `make test-phase4` 153 passed(原 112 + 41)
- `curl -i -H "X-Trace-ID: phase4-test" /api/agents` 响应 header 含 `X-Trace-ID: phase4-test`
- `curl /metrics` 返 Prometheus text,含 `http_requests_total` / `db_pool_acquire_seconds` / `corpai_app_info` 等
- MySQL `SELECT * FROM call_records` 应能看到 `chat` / `a2a_call.*` / `llm_summarize` span,共享 trace_id

## 参考引用

- 设计: `docs/REFACTOR_PLAN.md:32, 61, 249`
- ADR-005 (RBAC) — `call_records` 与 `auth_audit_log` 双表边界
- ADR-009 (no LangGraph) — `call_records` 替代 LangGraph time travel
- 前置:`CorpAI/platform/wiring.py:177, 217` `asyncio.to_thread` 双 event-loop — Phase 4 用 `to_thread_propagating` 修
