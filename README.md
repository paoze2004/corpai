# CorpAI - 企业 AI Copilot 平台

[![CI](https://github.com/paoze2004/CorpAI/actions/workflows/ci.yml/badge.svg)](https://github.com/paoze2004/CorpAI/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

> **多 Agent 企业 AI 平台** — 可插拔插件架构,统一 RBAC + 可观测性 + 管理后台。
> 业务范围:HR(社保/补充医疗/体检/培训)/ SRE(工单/on-call/K8s)/ FAQ(企业 KB RAG)。
> 详见 `CLAUDE.md` 与 `docs/REFACTOR_PLAN.md`。

## 核心架构

```
        ┌────────────────────────────────────────────┐
        │  平台核心 (CorpAI/platform/) — 写死,业务零污染 │
        │  ┌──────────┐  ┌──────────────┐  ┌────────┐ │
        │  │ Orchestr.│  │ Plugin Mgr   │  │  RBAC  │ │
        │  └──────────┘  └──────────────┘  └────────┘ │
        │  ┌──────────┐  ┌──────────────┐  ┌────────┐ │
        │  │ Auth/JWT │  │ Observability│  │ DB Pool│ │
        │  └──────────┘  └──────────────┘  └────────┘ │
        └────────┬────────────────────┬────────────────┘
                 │ A2A (entry_points) │
       ┌─────────┼────────────────────┼─────────┐
       │         │                    │         │
   ┌───▼───┐ ┌──▼────┐ ┌────────┐ ┌───▼────┐ ┌──▼─────┐
   │ hr_   │ │devops_│ │ faq    │ │admin UI│ │  SPA   │
   │assist │ │copilot│ │(RAG)   │ │ /admin │ │  /     │
   └───────┘ └───────┘ └────────┘ └────────┘ └────────┘
```

- **平台核心**(`CorpAI/platform/`)— RBAC / Orchestrator / Plugin Manager / Observability / DB,业务零依赖
- **业务 plugin**(`plugins/`)— 3 真 plugin(hr_assistant / sre_copilot / faq),`entry_points` 自动发现
- **A2A 子代理**:每个 plugin 一个 A2A 进程(Flask + python_a2a)
- **MCP 工具**:每个 plugin 自带 FastMCP 服务,`POST /tools/{name}` 调用
- **管理后台**:`/admin` 5 页(agents / tools / users / logs / metrics)
- **观测**:Prometheus `/metrics` + trace_id + 结构化日志 + `call_records` 表

## 工程化

- **CI/CD**:`.github/workflows/ci.yml` — push/PR 触发 lint + test + build;`.github/workflows/deploy.yml` — 手动 dispatch 多架构镜像到 GHCR
- **pre-commit**:`.pre-commit-config.yaml` — 本地 ruff check + format(commit 前自动跑)
- **Docker**:`Dockerfile.api` + `Dockerfile.plugin` 多阶段、非 root、healthcheck,3 个 plugin 复用同一镜像模板
- **Lint**:ruff(E/F/W/I/B/C4/UP/SIM/RUF,line-length=100)

## 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.11+ | 开发语言 |
| MySQL | 业务数据(用户/RBAC/记忆/调用记录) |
| Milvus | faq plugin 向量库 |
| FastMCP (python_a2a) | MCP 工具服务框架 |
| Flask | A2A 子代理 HTTP |
| LangChain | LLM 调用编排 |
| uvicorn | 主 API ASGI 服务器 |
| MiniMax | LLM (`MiniMax-Text-01`) + Embedding (`embo-01`, 1536 维) |
| Prometheus | 指标采集 |
| schedule | 定时任务 |

## 业务能力(3 真 plugin)

| Plugin | 场景 | A2A | MCP 工具 |
|--------|------|-----|---------|
| **hr_assistant** | 员工福利查询 + 人事政策 | :5010 | `query_benefits`(:8010) / `query_policy`(:8011) |
| **sre_copilot** | 工单查询 + on-call 联系 + Pod 重启 | :5020 | `query_incident`(:8020) / `restart_pod`(:8021, dry_run) |
| **faq** | 企业 KB 语义检索(VPN/远程办公/差旅等) | :5030 | `query_faq`(:8030) |

## 项目结构

```
CorpAI/                              ← 项目根
├── pyproject.toml                       # 依赖声明(uv 锁 pyproject + uv.lock)
├── uv.lock
├── Makefile                             # 常用命令(make help 查看)
├── README.md
├── CorpAI/                          ← Python 包
│   ├── config.py                       # .env 化配置
│   ├── logging.py                      # 结构化日志
│   ├── api/
│   │   ├── app.py                      # FastAPI :8080(SPA + admin + /api/chat)
│   │   └── admin_router.py             # 管理后台 5 页 API
│   ├── core/
│   │   ├── memory.py                   # 6 层 MemoryPool
│   │   └── prompts.py                  # intent / planning / react / system prompts
│   ├── platform/                       # 平台核心
│   │   ├── wiring.py                   # 组合根 — 唯一允许 import A2A/LangChain/MySQL
│   │   ├── orchestrator/               # 5 模块,≤300 LOC 每个
│   │   │   ├── service.py              # OrchestratorService — 唯一 high-level 入口
│   │   │   ├── intent.py               # IntentRecognizer(只识别 hr/devops/faq)
│   │   │   ├── planner.py              # TaskPlanner(INDEPENDENT_INTENTS = hr/devops/faq)
│   │   │   ├── react_loop.py           # ReActRunner
│   │   │   ├── streaming.py            # ThinkBlockFilter + SSE helpers
│   │   │   └── memory_gateway.py       # MemoryPool 6 层包装
│   │   ├── auth/                       # JWT / RBAC scopes / passwords / audit
│   │   ├── observability/              # trace / log / metrics / call_record
│   │   ├── db.py                       # MySQL pool 单例
│   │   └── plugin_manager.py           # entry_points 自动发现
│   ├── utils/
│   │   └── format.py                   # JSON encoder + strip_think
│   └── static/                         # 前端 SPA + admin/
├── plugins/                            # 业务 plugin(可插拔)
│   ├── hr_assistant/                   # 福利/政策 8+10 条数据
│   ├── sre_copilot/                 # 8 工单 + 4 on-call 团队
│   └── faq/                            # 12 条企业 KB(VPN/远程办公/差旅等)
├── tests/                              # pytest
│   ├── platform/                       # orchestrator 模块测试
│   ├── auth/                           # JWT/RBAC/scope 测试
│   ├── memory_pool/                    # 6 层记忆测试
│   └── observability/                  # trace/metrics/call_record 测试
├── scripts/
│   ├── bootstrap_super_admin.py        # 初始 super_admin 账号
│   ├── run_all.bat                     # 一键启全部 4 服务(Windows)
│   ├── stop_all.bat
│   └── migrate_add_*.py                # auth / observability / user_id
├── sql/
│   ├── create_all_tables.sql
│   ├── migrate_add_auth.sql
│   ├── migrate_add_observability.sql
│   └── migrate_add_user_id.sql
└── logs/
```

## 写新业务 plugin

```bash
mkdir -p plugins/my_plugin/src/my_plugin
# 写 pyproject.toml + plugin.py + prompts.py + server.py + entry.py
uv pip install -e plugins/my_plugin
# 自动被 discover_all() 通过 entry_points 发现
```

详见 `docs/PLUGINS.md`。

## 数据库表

| 表名 | 用途 |
|------|------|
| `user_profiles` / `query_history` / `short_term_messages` / `cross_agent_context` | 6 层记忆(`platform/orchestrator/memory_gateway.py`) |
| `auth_users` / `auth_audit_log` | RBAC 用户 + 审计(`platform/auth/`) |
| `call_records` | 可观测性调用记录(`platform/observability/call_record.py`) |

## 快速开始

### 0. 装依赖(首次克隆后)

```bash
# 装 uv(https://docs.astral.sh/uv/getting-started/installation/)
uv sync --group dev
```

### 1. 初始化数据库

```bash
mysql -u root -p < sql/create_all_tables.sql
$AUTH_JWT_SECRET=dev-secret uv run python scripts/migrate_add_user_id.py
$AUTH_JWT_SECRET=dev-secret uv run python scripts/migrate_add_auth.py
$AUTH_JWT_SECRET=dev-secret uv run python scripts/migrate_add_observability.py
$AUTH_JWT_SECRET=dev-secret uv run python scripts/bootstrap_super_admin.py
```

### 2. 装 3 个 plugin

```bash
make install-plugins
# 等价于:uv pip install -e plugins/hr_assistant -e plugins/sre_copilot -e plugins/faq
```

### 3. 启 plugin 服务(3 个进程)

```bash
make run-hr-assistant        # A2A :5010 + benefits_mcp :8010 + policy_mcp :8011
make run-sre-copilot      # A2A :5020 + incident_mcp :8020 + k8s_mcp :8021 (dry_run)
make run-faq                 # A2A :5030 + faq_query_mcp :8030
```

### 4. 启主服务

```bash
$AUTH_JWT_SECRET=dev-secret make run-api
# http://127.0.0.1:8080  (用户 SPA)
# http://127.0.0.1:8080/admin  (管理后台)
```

> Windows 一键启:`scripts/run_all.bat`(hr / devops / faq / main 4 服务全部后台启动)
> 停:`scripts/stop_all.bat`

### 5. 跑测试

```bash
make test           # 平台 + 3 plugin 全套
make test-unit      # 纯单元测试(无 MySQL/Milvus)
```

## 配置(.env)

26 个变量,参考 `.env.example`。核心变量:

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

# Milvus(faq plugin 用,docker compose -f corpai-milvus.yml up -d 启)
MILVUS_HOST=localhost
MILVUS_PORT=19530
EMBEDDING_MODEL=embo-01
EMBEDDING_DIM=1536

# RBAC(必须设置,否则 admin 端点启动失败)
AUTH_JWT_SECRET=<random-32-chars-min>
```

## 意图路由

意图路由由 `plugin_manager.agents_for_intent(intent)` 自动完成:

| Plugin | 处理意图 | Manifest 名 |
|--------|---------|------------|
| hr_assistant | hr / benefits | `hr_assistant` (A2A :5010) |
| sre_copilot | devops | `sre_copilot` (A2A :5020) |
| faq | faq | `faq` (A2A :5030) |

out_of_scope 走 LLM 直答兜底。

## 验证场景(8/8 通过)

```bash
curl -X POST http://127.0.0.1:8080/api/chat -H 'Content-Type: application/json' \
  -d '{"message":"公司有什么福利"}'
# → B001-B008 福利表

curl -X POST http://127.0.0.1:8080/api/chat -H 'Content-Type: application/json' \
  -d '{"message":"INC-001 现在什么状态"}'
# → INC-001 P0/open/张工/platform

curl -X POST http://127.0.0.1:8080/api/chat -H 'Content-Type: application/json' \
  -d '{"message":"VPN 怎么申请"}'
# → FAQ001 5 步骤
```

## 路线图

| Phase | 状态 | 内容 |
|-------|------|------|
| 0 | ✅ | 稳定基线 |
| 1.7 | ✅ | ChatService 拆分 7 模块 |
| 2 | ✅ | DB 集中化 + 记忆 per-user |
| 3 | ✅ | Plugin Manager + RBAC + Admin MVP |
| 4 | ✅ | Observability + CI/CD |
| 5 | ✅ | 3 真 plugin + 文档 |
| 6 | ✅ | 硬化(.env + Pydantic + async) |
| 7 | ✅ | 终版 — 抹旅游残留,纯企业 AI Copilot |

详见 `docs/REFACTOR_PLAN.md` 与 `docs/adr/`。