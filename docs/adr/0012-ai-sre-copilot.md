# ADR-0012: AI SRE Copilot 架构(从聊天机器人到真业务闭环)

## 状态

**Accepted** — 2026-08-09(Phase SRE.a-h 完成)

## 背景

CLAUDE.md 列出的项目定位是"企业 AI Copilot 平台",但 Phase 0-7 落地的是:
- HR 助理(提交请假/报销等 8 个真写 MySQL)
- SRE Copilot(Jira/PagerDuty/Prometheus/K8s 4 个真接 SDK)
- FAQ(Milvus RAG)

**问题**:这些是"工具"而非"产品"。用户原话:"不要演示版本和demo了,我要的是能上线的能投入生产的对接真实业务的"。

用户给的指导方向:**风险递进 + 真实业务链路**。从只读 → 写(dry_run)→ 真写 → 接 alert 来源。

最终决定:**做 AI SRE Copilot**(incident → AI 分析 → AI 生成 plan → 人工审批 → 自动修复 → 验证 → 关闭)。这是 SRE 工作的最核心闭环,且能:

1. **真业务**:生产事故**真的**发生,真的需要快速响应
2. **闭环可观测**:从 alert 接入到 incident 关闭全链路可观测
3. **企业级风险模式**:写操作必须有人审批,不能 AI 直接动生产
4. **可量化**:每个 incident 处理时间 / 误报率 / 自动恢复率都有 metric

## 决策

**新增 `platform/sre/` 子包,7 个模块化组件串联 incident 生命周期。所有 K8s 写操作必须经人工审批(AI 不能直接动生产)。**

### 1. 子包结构(7 模块,均 ≤ 300 LOC)

```
platform/sre/
├── __init__.py
├── incident_manager.py  # Alert 关联 → Incident(去重 + 状态机)
├── webhook.py           # Alertmanager POST /webhook/alertmanager 入口
├── approval.py          # Human Approval(approval_token + 二次 scope 校验)
├── action_executor.py   # Redis Stream consumer(异步执行 plan)
├── action_tools.py      # 4 个真写工具(restart_deployment / scale_deployment / ...)
├── feishu.py            # 飞书发卡 + 收 callback(国内生态)
└── cli.py               # scripts/run_sre_executor.py 入口
```

### 2. 数据流

```
Alertmanager ──webhook──▶ IncidentManager.ingest(alert)
                                │
                                ▼
                         sre_incidents(状态: open)
                                │
                                ▼
                     AI Agent 生成修复方案
                                │
                                ▼
              sre_action_plans(状态: pending, approval_token=uuid4)
                                │
                ┌───────────────┴───────────────┐
                ▼                               ▼
       飞书卡片(员工)              admin UI(ops)
                │                               │
                └───────────────┬───────────────┘
                                ▼
       ApprovalService.approve(plan_id, token, actor, scopes)
       ├─ 二次校验 scope: sre:approve
       ├─ 校验 token 匹配 + 清空(防复用)
       └─ status='approved'
                                │
                                ▼
              ActionExecutor.enqueue(plan_id)  XADD
                                │
                                ▼
        Redis Stream: sre:actions:stream(sre_workers consumer group)
                                │
                                ▼
              ActionExecutor.consume()
              ├─ XREADGROUP 阻塞读
              ├─ 调 action_tools.tool_dispatcher(action)
              │     ├─ restart_deployment(K8s AppsV1Api)
              │     ├─ scale_deployment(K8s AppsV1Api)
              │     ├─ update_incident_status(Jira transitions)
              │     └─ create_incident_comment(Jira comments)
              ├─ 写 sre_audit_log
              └─ UPDATE plan SET status='executed'
                                │
                                ▼
                       Prometheus 验证 + resolved
```

### 3. 状态机(8 个状态,合法转换表)

```
open → investigating → plan_pending → approved → executing → mitigated → resolved
  │                       │              │            │
  └──→ failed(任意一步) ──┴──────────────┴────────────┘
                              │
                              ▼
                  failed → investigating(可重试)
                  resolved → 终态(不能再动)
```

### 4. 安全红线(必须遵守)

| 操作 | 谁能做 | 校验 |
|------|--------|------|
| Alertmanager webhook 入站 | Alertmanager | IP 白名单 + HMAC 签名(待加) |
| IncidentManager 关联/创建 | webhook | 无 — 数据可信 |
| 生成 plan(写 sre_action_plans) | AI Agent(chat) | chat:write scope |
| **批准 plan** | **人(admin)** | **sre:approve scope + approval_token** |
| **执行 K8s/Jira 写** | **Executor** | **sre:execute scope + DRY_RUN=false** |
| 改 Incident 状态 | webhook(只 resolved) | 无 — Alertmanager 已签 |

**为什么执行也要 scope**:即使 approval_token 通过,Executor 也要校验 `sre:execute`(防止 Executor 进程本身被劫持)。**二次校验**是 fail-closed 的核心。

### 5. DRY_RUN 是平台级开关,不是 user 级

`SRE_DRY_RUN=true`(默认)→ 所有 action tool 不调 SDK,只返 planned。
切到 false:
- **K8s 需要 KUBECONFIG**(用户尚未提供)
- **Jira 用现有 JIRA_URL/JIRA_EMAIL/JIRA_TOKEN** ✅(已验证)

未来加 user 级 DRY_RUN(force=true 才能真写)— 需要 ExecutionContext 加 actor + per-action bypass 字段。

### 6. 为什么不引 Airflow/Celery/Temporal

- **Celery**:太重(beat+worker+broker 三件套),本场景只需"异步执行 + 重试"
- **Airflow**:DAG 概念太重,我们的 plan 是 list of actions,不是 DAG
- **Temporal**:工作流语义过强(信号/查询/子工作流),杀鸡用牛刀
- **Redis Stream + 自写 consumer**:200 行 Python 解决问题,可控可测

### 7. 飞书选型 vs PagerDuty

- 用户明确指定飞书(国内生态)
- 飞书 interactive card 支持按钮回调,无需二次开发 UI
- PagerDuty 保留作 oncall 查询(SRE 工具)— 两边不冲突

### 8. 持久化策略

| 表 | 用途 | 落库时机 |
|----|------|----------|
| sre_incidents | incident 状态 + 关联 alerts | webhook 入口 |
| sre_action_plans | plan + approval_token + 审批状态 | AI 生成 / 审批回调 |
| sre_audit_log | 谁/什么时候/改了什么/为什么 | 所有写操作 |

**为什么三张表分开**:sre_incidents 由 webhook 写(高频),sre_action_plans 由 chat 写(中频),sre_audit_log 由所有写操作追加(只 append)。读写分离 + 各自的索引。

### 9. 指标

- `sre_action_executed_total{tool, status}` — Action 工具执行计数
- `sre_incidents_total{severity, source}` — Incident 计数

未来加:`sre_incident_resolution_seconds`(MTTR histogram)、`sre_plan_approval_lag_seconds`(审批延迟)。

## 风险 + 缓解

| 风险 | 缓解 |
|------|------|
| AI 直接动生产 → 灾难 | Human Approval gate 强制 + scope 二次校验 |
| Webhook 被刷 → Incident 洪水 | IP 白名单 + Alertmanager 共享 secret HMAC |
| Executor 重启丢任务 | Redis Stream pending list + XAUTOCLAIM |
| Plan 生成幻觉 → 误操作 | dry_run 默认 true + 每次执行前查最新 metric 验证 |
| K8s 真接写错 namespace | replicas [0,50] 边界 + 必须填 namespace |

## 验证

- 7 模块 + 69 单测全过
- 真 Jira 凭证 → status 转移 + comment 已验证(Phase 1.7)
- K8s 真接需 KUBECONFIG(用户待提供)
- 飞书发卡需 FEISHU_APP_ID/SECRET(用户待提供)

## 后续

- 加 webhook HMAC 签名校验
- 加 plan 验证步骤(K8s rollout 后查 Pod Ready + Prometheus 指标)
- 加 MTTR / approval lag histogram
- 加 per-user DRY_RUN bypass(高权限 ops)
- 接飞书真凭证后跑 e2e:Alertmanager 真告警 → 飞书卡片 → 审批 → K8s rollout → Jira 关单

## 相关

- ADR-0010: Observability 选型(已为 SRE 提供 trace/metrics 基础)
- ADR-0005: RBAC 模型(scope sre:approve / sre:execute 已纳入)
- Phase 6 硬化:action_tools DRY_RUN 通过 env 控制,不硬编码