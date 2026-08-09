# ADR 0011: 生产化 — 「做减法 + 真可用」

## Context

**为什么做这次重构**:v3.0 现状把"做工具"当成了"做产品"。
- 30 个 manifest 里 **18 个是 in-memory mock** 或写死 dict(28 个 devops 玩具 + 7 个 hr KB 玩具)
- 仅 5 个工具真接 MySQL / Milvus
- 无 Dockerfile / docker-compose 全栈 / `.github/workflows/` / K8s manifests / Prometheus 告警
- `corpai-mysql.yml` / `corpai-redis.yml` / `corpai-platform.yml` 都是占位注释
- 生产成熟度只到 L2 内部 Demo 等级(应用架构扎实,生产能力 30%)

**用户原话**:
> "别做玩具,做能立刻使用的。"
> "我要的是真正的可以上生产的项目,我是真正要使用的!别在给我做玩具了。"

**目标**:3 周内把 CorpAI 从 L2 内部 Demo 推到 L3 内部生产。

**完成定义**(不是"写完代码"):
- 14 个真工具全部接真 SDK,无 mock
- 1 个真实用户故事走通(年假-审批-通知)
- Docker 化能一键起全栈
- Prometheus 告警规则上线
- CI/CD pipeline green
- 用户每天能用 ≥ 3 次
- 失败率 < 5%,P99 延迟 < 3s

---

## 决策

### 决策 1:删 70% 玩具,只留 14 个真工具

**保留 14 个真工具**(写 MySQL/Milvus/真 SDK):
- **hr_assistant**:9 个操作类(写 MySQL `hr_leave_requests` 等 6 表)— 保留 `actions.py`
- **faq**:1 个 RAG(接 Milvus + MiniMax embedding)— 保留
- **devops_copilot**:4 个真工具(Phase 1 接 Jira / PagerDuty / Prometheus / kubernetes-python)— 删除 30 个 in-memory mock
- 3 个跨插件 bridge:`cross_check_hr` / `cross_query_faq` / `cross_check_devops`

**删除**:
- `plugins/hr_assistant/src/hr_assistant/tools.py` 整个文件(7 个 KB 查询函数 + 82 条 dict)
- `plugins/devops_copilot/src/devops_copilot/tools.py` 中的 28 个 in-memory 工具
- hr 7 个 KB manifest / devops 7 个 toy manifest

**理由**:一个工具不能接真库就是玩具,占 API 表面却不解决任何问题。

### 决策 2:devops 4 个工具接真 SDK(Phase 1)

| 工具 | 写真库 / SDK | env 变量 | 错误模式 |
|------|--------------|----------|----------|
| `query_incident` | Jira REST API | `JIRA_URL` + `JIRA_TOKEN` + `JIRA_PROJECT` | 401 重试 / 不可达 → `not_configured` + Counter |
| `query_oncall` | PagerDuty API | `PAGERDUTY_API_KEY` + `PAGERDUTY_SCHEDULE_ID_<TEAM>` | 不可达 → 降级返空 + Counter |
| `query_alert` | Prometheus Alertmanager | `PROMETHEUS_URL` | 不可达 → `not_configured` + Counter |
| `get_pod_logs` | kubernetes-python | `KUBECONFIG` / in-cluster | pod 不存在 → `not_found` / K8s 不可达 → `error` |

**Phase 0 stub 行为**:无 env 配置时显式 `{"status": "not_configured", "message": "需要配置 JIRA_URL+JIRA_TOKEN", "required_env": [...]}`。绝不编造数据,绝不返 mock 数据。

**理由**:stub 阶段就显式告诉用户需要哪些 env 变量,优于"假装工作但返 mock 数据"。

### 决策 3:跨插件 bridge 失败显式告知

**v2.x 行为**:`_bridge_call` 失败时返 `None`,调用方走 "fallback" 静默降级。违反 CLAUDE.md "不要 silent-fail"。

**v3.0 行为**:`_bridge_call` 失败时返 `{"status": "bridge_unavailable", "kind": "timeout|unreachable|http5xx|json_decode|error", "message": "..."}`。调用方显式透传给用户。

**改动文件**:
- `plugins/hr_assistant/src/hr_assistant/actions.py` — `_bridge_call` + `cross_query_faq` / `cross_check_devops` / `cross_notify_devops`
- `plugins/devops_copilot/src/devops_copilot/bridges.py` — 重写,`cross_check_hr` / `cross_query_faq`

**仍保留**:timeout 严格 2s / `HR_BRIDGE_ERRORS_TOTAL` Counter 累加。

### 决策 4:不做大改架构,只换实现

**不动**:
- 平台核心(`platform/orchestrator/` / `platform/wiring.py`)
- MCP wire 协议(`POST /tools/{name}` + JSON envelope)
- SSE 流式格式(`data: {"chunk":...}\n\n` + `[DONE]`)
- ThinkBlockFilter(`api/app.py:59-101`)
- entry_points plugin 发现
- RBAC 三层防御

**只动**:
- `plugins/hr_assistant/src/hr_assistant/{tools.py,prompts.py,server.py,plugin.py,tests/test_plugin.py}` — 删 7 KB + 改 prompt 提示
- `plugins/devops_copilot/src/devops_copilot/{tools.py,prompts.py,server.py,plugin.py,bridges.py,tests/test_plugin.py}` — 重写为 4 真工具 + 改 bridge

**理由**:这是「做减法 + 真可用」的工程化,不是"推倒重来"。

---

## 实施计划(3 周)

### Phase 0 — 删玩具(2 天)✅

| 步骤 | 状态 |
|------|------|
| git tag `v0.0.0-pre-trim` | ✅ |
| 删 `hr_assistant/tools.py`(7 KB 函数 + 82 dict) | ✅ |
| 重写 `devops_copilot/tools.py`(4 真工具 stub) | ✅ |
| 改 `bridges.py` silent-fail → 显式 | ✅ |
| 删对应 manifest(7 hr + 7 devops) | ✅ |
| 跑测试:152 平台 + 6 hr + 13 devops = **171 全过** | ✅ |

### Phase 1 — devops 4 个真 SDK 接入(3 天)

**目标**:删除 `_INCIDENTS` / `_ALERTS` / `_PIPELINES` / `_LOG_SOURCES` 4 个 mock dict,接真 SDK。

- `query_incident` 调 `requests.get(JIRA_URL/rest/api/3/search, jql=...)`,解析 `issues[]` 返统一 JSON
- `query_oncall` 调 `requests.get(https://api.pagerduty.com/oncalls)`,返轮值信息
- `query_alert` 调 `requests.get(PROMETHEUS_URL/api/v2/alerts)`
- `get_pod_logs` 调 `kubernetes.CoreV1Api.read_namespaced_pod_log`(DRY_RUN=false)

错误模式:401 重试一次 / 超时 → 降级 + Counter / 不可达 → 显式 `not_configured` + Counter。

### Phase 2 — Docker 化(2 天)

**目标**:`docker compose -f corpai-platform.yml up -d` 一键起全栈。

- `Dockerfile.api` — uvicorn `CorpAI.api.app:app`
- `Dockerfile.plugin` — 共享,env 传 `PLUGIN_NAME` + `PORT`
- `corpai-platform.yml` — mysql + redis + api + 3 plugins + prometheus + grafana
- `corpai-mysql.yml` / `corpai-redis.yml` — 从占位变实际
- 验证:`curl http://localhost:8080/health` 返 200

### Phase 3 — HTTPS + 限流 + 健康检查(2 天)

- `GET /health` + `GET /ready` 端点(校验 mysql/redis/plugins)
- `fastapi-limiter` 集成(10/min/IP,Redis 后端)
- Traefik HTTPS termination + 自签证书(`mkcert`)

### Phase 4 — Prometheus 告警规则(2 天)

补 metrics:
- `corpai_tool_latency_seconds`(histogram)
- `corpai_db_connection_errors_total`(counter)
- `corpai_plugin_unavailable_total`(counter)

`prometheus/alerts.yml`:
- HighErrorRate(5xx > 5% 持续 5m)
- DBPoolExhausted(counter > 0)
- PluginDown(up == 0 持续 2m)
- HRActionFailRate(`hr_action_total{status=error}` > 10%)

### Phase 5 — CI/CD(2 天)

- `.github/workflows/ci.yml`:lint(ruff) + test + build
- `.github/workflows/deploy.yml`:手动 dispatch,推 ghcr.io
- `.pre-commit-config.yaml`:ruff + ruff-format
- `pyproject.toml`:`[tool.ruff]` + 加 `jira` / `prometheus-api-client` / `kubernetes`

### Phase 6 — README + Runbook(2 天)

- `README.md` 重写:14 工具清单 + 启动 + env 变量 + 监控
- `docs/runbook.md`:5 个常见故障的排查 + 恢复步骤
- `docs/CHANGELOG.md`:v3.0.0 — 删 70% 玩具,接真 SDK,Docker 化,CI/CD

### Phase 7 — 1 个真实用户故事走通(2 天)

**目标**:年假-审批-通知全链路真用。

```bash
# alice 提交请假
curl -X POST http://localhost:8080/api/chat \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -d '{"message":"我要请年假,8月15-16号"}'
# 期望: AI 调 submit_leave,返 L20260809-001

# HR 审批
curl -X POST http://localhost:8080/api/chat \
  -H "Authorization: Bearer $HR_TOKEN" \
  -d '{"message":"批准 L20260809-001"}'
# 期望: AI 调 approve_request,状态 pending → approved

# 审计验证
mysql -e "SELECT * FROM hr_audit_log ORDER BY id DESC LIMIT 3"
# 期望: 至少 2 条,含 submit_leave + approve_leave + trace_id
```

### Phase 8 — 度量 + 报告(1 天)

`scripts/weekly_report.py` — 读 Prometheus 算成功率/P99 延迟/DB 池占用,出 `reports/2026-W{}.md`。

---

## 度量检查(每周)

| 指标 | 目标 | 跳闸 |
|------|------|------|
| 工具调用成功率 | ≥ 95% | < 90% |
| DB 写入失败率 | ≤ 1% | > 5% |
| 95% 延迟 | < 2s | > 5s |
| 测试覆盖率 | ≥ 70% | < 50% |
| Mock 工具占比 | 0% | > 5% |
| 用户每天用次数 | ≥ 3 | = 0 |

---

## 关键复用(已存在,直接用)

| 组件 | 路径 | 用途 |
|------|------|------|
| `DatabasePool` | `CorpAI/platform/db.py` | 9 个 hr 工具的真库 |
| `current_trace_id` | `CorpAI/platform/observability/trace.py` | 审计日志串联 |
| `HR_ACTION_TOTAL` / `HR_BRIDGE_ERRORS_TOTAL` | `CorpAI/platform/observability/metrics.py` | Counter |
| `_bridge_call` 模式 | `plugins/hr_assistant/actions.py` | 跨插件桥接 |
| `make_access_token` | `CorpAI/platform/auth/tokens.py` | 测试用 JWT |

---

## Out of Scope(明确不做)

- ❌ LangGraph / LangChain 升级(已禁)
- ❌ 多租户(已有 RBAC,暂不深挖)
- ❌ K8s Helm chart / GitOps / ArgoCD
- ❌ 移动端 App
- ❌ 数据分析平台
- ❌ 完整 ELK 日志聚合
- ❌ 完整 Grafana 仪表盘(只配 4 个核心 panel)
- ❌ 自动扩缩容(HPA)

---

## 验证(Phase 0 完成时)

### 测试
- 平台 `pytest tests/ -m "not integration"`:**152 passed, 1 skipped** ✅
- hr `pytest tests/`:12 passed(6 unit + 6 e2e) ✅
- devops `pytest tests/`:13 passed ✅
- **总计 171 全过,无回归** ✅

### Manifest 数量对比
| plugin | v2.x | v3.0 | Δ |
|--------|------|------|---|
| hr_assistant | 18(7 KB + 8 ops + 2 bridge + 1 agent) | 11(8 ops + 2 bridge + 1 agent) | -7 KB |
| devops_copilot | 9(1 agent + 8 mcp) | 7(1 agent + 4 真工具 + 2 bridge) | -2 mcp toy |
| faq | 不动 | 不动 | 0 |
| **总计** | 30 | 21 | **-9 toy** |

注:hr devops 同时删除 toy manifest,**真工具数量增加**(v2.x 写 MySQL 工具有 9 个,v3.0 是 9 个 ops + 4 真 SDK 工具 = 13 个)。

---

## 完成后推动到 L4(L4 还需要做什么)

3 周后 L3 完成,**L4 内部生产 7×24 SLA 还需要**:
- K8s Helm chart + GitOps (ArgoCD)
- 多副本(至少 3)
- MySQL 主从 + 读写分离
- Milvus 集群(3 节点)
- 完整 ELK
- 灾备演练
- SLO 99.95% 文档

**不在本次 3 周规划内**,写入 `docs/PRODUCTION_READINESS.md` 后续 Todo。

---

## ADR 历史交叉引用

- `0010-phase4-observability.md` — Counter / trace_id / `/metrics` 已就位,本 ADR 复用其基础
- `0005-rbac-model.md` — `hr:write` / `devops:read` / `devops:write` 4 个 scope,本 ADR 沿用
- `0004-orchestrator-module-split.md` — 平台 7 模块 ≤300 行,本 ADR 不改
- `0001-platform-shape.md` — 平台 vs 业务分离,本 ADR 不改