# CorpAI — 企业 AI Copilot 平台

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

> 多 Agent 企业 AI 平台。可插拔插件架构,统一 RBAC + 可观测性 + 管理后台。
> 业务范围:HR(请假/报销/证明/资产/培训/转正/审批) / SRE(工单/on-call/告警/K8s) / FAQ(企业 KB RAG)。

## 架构

```
       ┌─────────────────────────────────────────────┐
       │  平台核心 (CorpAI/platform/) — 写死,业务零污染  │
       │  ┌──────────┐ ┌─────────────┐ ┌────────────┐ │
       │  │Orchestr. │ │ Plugin Mgr  │ │   RBAC     │ │
       │  └──────────┘ └─────────────┘ └────────────┘ │
       │  ┌──────────┐ ┌─────────────┐ ┌────────────┐ │
       │  │Auth/JWT  │ │Observability │ │  DB Pool   │ │
       │  └──────────┘ └─────────────┘ └────────────┘ │
       └──────┬──────────────────┬────────────────────┘
              │  entry_points    │
    ┌─────────┼──────────────────┼─────────┐
    │         │                  │         │
┌───▼────┐ ┌─▼────────┐ ┌──────▼─┐ ┌─────▼────┐
│  hr_   │ │  sre_    │ │  faq   │ │ admin UI │
│ assist │ │ copilot  │ │ (RAG)  │ │  /admin  │
└────────┘ └──────────┘ └────────┘ └──────────┘
```

- **平台核心**(`CorpAI/platform/`) — Orchestrator / Plugin Manager / RBAC / Auth / Observability / DB Pool,业务零依赖
- **业务 plugin**(`plugins/`) — `entry_points` 自动发现,新增业务 = 写一个新 plugin 包
- **A2A 子代理** — 每个 plugin 跑一个 A2A 进程(Flask + `python_a2a`)
- **MCP 工具** — 每个 plugin 自带 FastMCP 服务,`POST /tools/{name}` 调用(JSON envelope)
- **管理后台** — `/admin` 5 页(agents / tools / users / logs / metrics)
- **可观测性** — Prometheus `/metrics` + trace_id + 结构化日志 + `call_records` 表

## 业务能力(3 个真 plugin)

| Plugin | 场景 | A2A | Manifest |
|--------|------|-----|----------|
| **hr_assistant** v3.0 | 员工福利 + 8 操作 + 2 跨插件 bridge | `:5010` | 1 agent + 8 ops + 2 bridge = **11** |
| **sre_copilot** v3.1 | 工单/on-call/告警/K8s + 2 跨插件 bridge | `:5020` | 1 agent + 4 真工具 + 2 bridge = **7** |
| **faq** v1.1 | 企业 KB 语义检索(Milvus) | `:5030` | 1 agent + 1 tool = **2** |

详细清单见 plugin 各自的 README(`plugins/<name>/README.md`)。

### MCP 工具端口速查

| Plugin | MCP 服务 | 端口 | 工具 |
|--------|---------|------|------|
| hr_assistant | leave / reim / cert / asset / train / reg / approve / my / bridge_faq / bridge_sre | `:8017-8026` | `submit_leave` 等 8 个 ops + 2 bridge |
| sre_copilot | incident / oncall / alert / k8s / bridge_hr / bridge_faq | `:8020-8022 / :8027-8028` | `query_incident` / `query_oncall` / `query_alert` / `get_pod_logs` + 2 bridge |
| faq | query_mcp | `:8030` | `query_faq` |

## 项目结构

```
CorpAI/                            ← 仓库根 (paoze2004/corpai)
├── pyproject.toml                 # 依赖 (uv 锁)
├── uv.lock
├── Makefile                       # make help 查看所有命令
├── README.md
├── CorpAI/                        ← Python 包
│   ├── config.py                  # .env 化配置
│   ├── logging.py                 # 结构化日志
│   ├── api/
│   │   ├── app.py                 # FastAPI :8080 (SPA + admin + /api/chat)
│   │   └── admin_router.py        # 管理后台 5 页 API
│   ├── core/
│   │   ├── memory.py              # 6 层 MemoryPool(向后兼容迁移)
│   │   └── prompts.py             # intent / planning / react / system prompts
│   ├── platform/                  # 平台核心
│   │   ├── wiring.py              # 组合根 — 唯一允许 import A2A/LangChain/MySQL 的文件
│   │   ├── orchestrator/          # 7 模块,≤300 LOC 每个
│   │   │   ├── service.py         # OrchestratorService — 唯一 high-level 入口
│   │   │   ├── intent.py          # IntentRecognizer
│   │   │   ├── planner.py         # TaskPlanner (INDEPENDENT_INTENTS)
│   │   │   ├── react_loop.py      # ReActRunner
│   │   │   ├── streaming.py       # ThinkBlockFilter + SSE helpers
│   │   │   ├── tools_gateway.py   # MCP 工具调用网关
│   │   │   └── memory_gateway.py  # MemoryPool 6 层包装
│   │   ├── auth/                  # JWT / RBAC scopes / passwords / audit
│   │   ├── observability/         # trace / log / metrics / call_record
│   │   ├── db.py                  # MySQL pool 单例
│   │   └── plugin_manager.py      # entry_points 自动发现
│   ├── utils/format.py            # JSON encoder + strip_think
│   └── static/                    # 前端 SPA + admin/
├── plugins/                       # 业务 plugin(可插拔)
│   ├── hr_assistant/              # 8 ops + 2 bridge + 11 manifest
│   ├── sre_copilot/               # 4 真工具 + 2 bridge + 7 manifest
│   └── faq/                       # Milvus RAG + 2 manifest
├── tests/                         # pytest
│   ├── platform/                  # orchestrator 模块测试
│   ├── auth/                      # JWT/RBAC/scope 测试
│   ├── memory_pool/               # 6 层记忆测试
│   └── observability/             # trace/metrics/call_record 测试
├── scripts/                       # 迁移 / 引导 / 启停
├── sql/                           # create_all_tables.sql + 迁移脚本
├── docs/                          # (gitignored)项目本地文档,不入公开仓库
├── logs/                          # (gitignored)运行时日志
├── Dockerfile.api
├── Dockerfile.plugin
└── corpai-{mysql,milvus,redis,platform}.yml
```

## 快速开始

### 0. 装依赖

```bash
# 装 uv: https://docs.astral.sh/uv/
uv sync --group dev
```

### 1. 初始化数据库

```bash
mysql -u root -p < sql/create_all_tables.sql
make migrate-phase2        # user_id + task_context + cross_agent_context
make migrate-phase3        # auth_users / auth_roles / auth_permissions / auth_audit_log
make migrate-phase4        # call_records
make bootstrap-superadmin  # 第一个 super_admin(要求 AUTH_JWT_SECRET 已设)
```

### 2. 装 3 个 plugin

```bash
make install-plugins       # uv pip install -e plugins/{hr_assistant,sre_copilot,faq}
```

### 3. 启 plugin 服务(每个 1 A2A + N MCP)

```bash
make run-hr-assistant      # A2A :5010 + MCP :8017-8026 (8 ops + 2 bridge)
make run-sre-copilot       # A2A :5020 + MCP :8020-8028 (4 tools + 2 bridge)
make run-faq               # A2A :5030 + MCP :8030 (1 tool)
```

### 4. 启主服务

```bash
make run-api               # FastAPI :8080 (用户 SPA + admin 后台 + /api/chat)
```

访问:
- 用户 SPA: <http://127.0.0.1:8080>
- 管理后台: <http://127.0.0.1:8080/admin>

### 5. 跑测试

```bash
make test                  # 全部(平台 + 3 plugin)
make test-unit             # 纯单元(无 MySQL/Milvus)
make test-platform         # orchestrator + memory_pool
make test-auth             # JWT/RBAC/scope
make test-observability    # trace/metrics/call_record
make test-plugins          # 3 plugin
```

## 配置 (.env)

**41 个变量**,参考 `.env.example`。核心:

```bash
# LLM
BASE_URL=https://api.minimaxi.com/v1
MODEL=MiniMax-Text-01
API_KEY=<your-key>

# MySQL
MYSQL_HOST=localhost
MYSQL_USER=admin
MYSQL_PASSWORD=<your-password>
MYSQL_DATABASE=CorpAI

# Milvus (faq plugin RAG)
MILVUS_HOST=localhost
MILVUS_PORT=19530
EMBEDDING_MODEL=embo-01
EMBEDDING_DIM=1536

# RBAC (必须设,否则 admin 端点启动失败)
AUTH_JWT_SECRET=<random-32-chars-min>

# SRE 真 SDK (Phase 6 接入)
JIRA_URL=
PAGERDUTY_API_KEY=
PROMETHEUS_URL=
KUBECONFIG=

# 飞书审批 (SRE)
FEISHU_APP_ID=
FEISHU_APP_SECRET=
```

## 意图路由

意图路由由 `platform/plugin_manager.py` 的 `agents_for_intent(intent)` 自动完成:

| Plugin | 处理 intent | Manifest |
|--------|---------|----------|
| hr_assistant | `hr` / `leave` / `reimbursement` | `:5010` |
| sre_copilot | `sre` / `incident` / `oncall` / `alert` / `pod` | `:5020` |
| faq | `faq` | `:5030` |

out_of_scope 走 LLM 直答兜底。

## 路线图

| Phase | 状态 | 内容 |
|-------|------|------|
| 0 | ✅ | 稳定基线 — 修测试、删 dead code、ADR |
| 1.7 | ✅ | ChatService 拆分 7 模块(orchestrator/) |
| 2 | ✅ | DB 集中化 + 记忆 per-user |
| 3 | ✅ | Plugin Manager + RBAC + Admin 后台 5 页 |
| 4 | ✅ | Observability(trace/metrics/call_records) |
| 5 | ✅ | 3 真 plugin(hr / sre / faq) |
| 6 | ✅ | 硬化(.env + Pydantic + async + 真 SDK) |
| 7 | ✅ | 收敛到企业 AI Copilot 形态 |

## License

未声明(公开仓库,默认适用各国著作权法)。如需明确许可,请提交 issue 或 PR 注明偏好(MIT / Apache-2.0 / BSD-3-Clause)。