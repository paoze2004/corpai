# CorpAI - 智能旅游助手

> ⚠️ **项目转型中**:本项目正在从单一旅游助手重构为**企业 AI Copilot 平台**(多 Agent 中台)。详见 `docs/REFACTOR_PLAN.md` 与 `CLAUDE.md`。
>
> 当前 Phase: **0 (稳定基线)**。业务代码未动,只清理 dead code + 修文档。

基于大模型 + MCP（Model Context Protocol）的智能旅游助手系统，支持天气查询、票务查询（火车票/机票/演唱会）、旅游团语义推荐等功能。

## 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.x | 开发语言 |
| MySQL | 业务数据存储（天气、票务、租车、保险等） |
| Milvus | 向量数据库，用于旅游团 RAG 语义检索 |
| FastMCP (python_a2a) | MCP 工具服务框架 |
| uvicorn | ASGI 服务器 |
| MiniMax | 大模型 + Embedding API(`embo-01`,1536 维) |
| 和风天气 API | 天气数据源 |
| schedule | 定时任务调度 |

## 项目结构

```
CorpAI/                          ← 项目根
├── pyproject.toml                    # 依赖声明（pyproject.toml + uv.lock 是事实来源）
├── uv.lock                           # 精确版本锁
├── Makefile                          # 常用命令入口（make help 查看）
├── README.md
├── CorpAI/                      ← Python 包（业务代码）
│   ├── __init__.py
│   ├── config.py                     # 全局配置（大模型、数据库、API）
│   ├── logging.py                    # 日志模块
│   ├── api/                          # FastAPI 后端
│   │   ├── __init__.py
│   │   └── app.py                    # 端口 8080
│   ├── core/                         # 核心业务逻辑
│   │   ├── __init__.py
│   │   ├── memory.py                 # 对话记忆
│   │   └── prompts.py                # 提示模板
│   ├── platform/                     # 平台核心（写死，业务不污染）
│   │   ├── __init__.py
│   │   ├── wiring.py                # 组合根 — 组装 OrchestratorService（A2A/LLM/DB/闭包）
│   │   └── orchestrator/            # 5 个编排模块，≤300 LOC 每个
│   │       ├── service.py           # OrchestratorService（唯一 high-level 入口）
│   │       ├── intent.py            # IntentRecognizer
│   │       ├── planner.py           # TaskPlanner
│   │       ├── react_loop.py        # ReActRunner
│   │       └── streaming.py         # ThinkBlockFilter + SSE helpers
│   │   ├── auth/                     # JWT / RBAC / passwords / audit
│   │   ├── observability/            # trace / log / metrics / call_record
│   │   └── db.py                     # MySQL pool singleton
│   ├── utils/                        # 通用工具
│   │   ├── __init__.py
│   │   └── format.py                 # JSON 编码器 + strip_think
│   └── static/                       # 前端静态资源(用户 SPA + admin/)
├── plugins/                          # 业务 plugin(可插拔)
│   ├── hr_assistant/                 # A2A :5010 + insurance_mcp :8010 + policy_mcp :8011
│   ├── devops_copilot/               # A2A :5020 + incident_mcp :8020 + k8s_mcp :8021 (dry_run)
│   └── faq/                          # A2A :5030 + faq_query_mcp :8030
├── tests/                            # pytest 测试
│   ├── conftest.py                   # pytest 配置
│   ├── platform/                     # orchestrator 拆分后的模块测试
│   ├── auth/                         # JWT / RBAC / scope 测试
│   ├── memory_pool/                  # 6 层记忆测试
│   └── observability/                # trace / metrics / call_record 测试
├── scripts/                          # 一次性脚本（数据初始化等）
│   ├── bootstrap_super_admin.py      # 初始 super_admin 账号
│   └── migrate_add_*.py              # 迁移脚本(auth / observability / user_id)
├── sql/                              # 数据库脚本
│   ├── create_all_tables.sql
│   ├── migrate_add_auth.sql
│   ├── migrate_add_observability.sql
│   └── migrate_add_user_id.sql
└── logs/                             # 运行日志目录
```

## 核心架构

CorpAI 已从"写死旅游助手"转型为**可插拔企业 AI Copilot 平台**:

- **平台核心**(`CorpAI/platform/`)— RBAC / Orchestrator / Plugin Manager / Observability / DB,业务零依赖
- **业务 plugin**(`plugins/`)— 3 真 plugin(hr_assistant / devops_copilot / faq),通过 entry_points 自动发现
- **A2A 子代理**:每个 plugin 一个 A2A 进程,LangChain ReAct + MCP tools 模式
- **MCP 工具**:每个 plugin 自带 FastMCP 服务,通过 `POST /tools/{name}` 调用
- **管理后台**:`/admin` 5 页(agents/tools/users/logs/metrics)
- **观测**:Prometheus `/metrics` + trace_id + 结构化日志 + `call_records` 表

### 写新业务

```bash
mkdir -p plugins/my_plugin/src/my_plugin
# 写 pyproject.toml + plugin.py + prompts.py
uv pip install -e plugins/my_plugin
# 自动被 discover_all() 发现
```

详见 `docs/PLUGINS.md`。

### 天气数据(已退役 — Phase 7 删 customer_service plugin)

原 customer_service plugin 的天气 MCP,演示了:
- **双数据源**:MySQL / 和风 API,通过 `.env` 的 `WEATHER_SOURCE` 切换
- **连接池**:`platform/db.py` 统一管理
- **日期兜底**:`start_date` 默认当天,`end_date` 默认当天 +29 天

新 plugin 如需天气能力,参考 `corpaidev` skill 重新实现。

### FAQ RAG(plugins/faq 内)

- 使用 MiniMax `embo-01` 生成向量(可在 `.env` 改 `EMBEDDING_MODEL`)
- 存入 Milvus,语义搜索 FAQ 知识库

## 数据库表

| 表名 | 说明 |
|------|------|
| `user_profiles` / `query_history` / `short_term_messages` | 用户记忆(`platform/orchestrator/memory_gateway.py`) |
| `cross_agent_context` | 跨 agent 上下文(`platform/orchestrator/memory_gateway.py` Layer 5) |
| `user_profiles` / `query_history` / `short_term_messages` | 用户记忆(`platform/orchestrator/memory_gateway.py`) |
| `auth_users` / `auth_audit_log` | RBAC 用户 + 审计(`platform/auth/`) |
| `call_records` | 可观测性调用记录(`platform/observability/call_record.py`) |

## 快速开始

### 0. 安装依赖（首次克隆项目后）

```bash
# 安装 uv（如果还没装）：https://docs.astral.sh/uv/getting-started/installation/
# 然后同步依赖（运行时 + 开发依赖）
uv sync --group dev
```

> 推荐用 `make` 命令管理项目：`make help` 查看所有命令。

### 1. 初始化数据库

```bash
mysql -u root -p < sql/create_all_tables.sql
```

### 2. 初始化数据(MySQL + Milvus)

```bash
mysql -u root -p < sql/create_all_tables.sql
$AUTH_JWT_SECRET=dev-secret uv run python scripts/migrate_add_user_id.py
$AUTH_JWT_SECRET=dev-secret uv run python scripts/migrate_add_auth.py
$AUTH_JWT_SECRET=dev-secret uv run python scripts/migrate_add_observability.py
$AUTH_JWT_SECRET=dev-secret uv run python scripts/bootstrap_super_admin.py
```

### 3. 装 plugin

```bash
make install-plugins
# 等价于:uv pip install -e plugins/hr_assistant -e plugins/devops_copilot -e plugins/faq
```

### 4. 启 plugin 服务(每个 plugin 一个进程)

```bash
make run-customer-service    # A2A :5005 + weather_mcp :8002 + ticket_mcp :8001
make run-hr-assistant        # A2A :5010 + insurance_mcp :8010 + policy_mcp :8011
make run-devops-copilot      # A2A :5020 + incident_mcp :8020 + k8s_mcp :8021 (dry_run)
make run-faq                 # A2A :5030 + faq_query_mcp :8030
```

### 5. 启主服务

```bash
$AUTH_JWT_SECRET=dev-secret make run-api
# 访问:http://127.0.0.1:8080(用户 SPA)+ http://127.0.0.1:8080/admin(管理后台)
```

### 6. 跑测试

```bash
make test           # 平台 + 4 plugin 全套
make test-unit      # 纯单元测试(无 MySQL/Milvus)
```

## 配置(.env)

所有配置走 `.env`,参考 `.env.example`(26 个变量):

```bash
# LLM
BASE_URL=https://api.minimaxi.com/v1
MODEL_NAME=MiniMax-Text-01
API_KEY=<your-key>

# MySQL
MYSQL_HOST=localhost
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_DATABASE=travel_rag

# Milvus(可选,faq plugin 用)
MILVUS_HOST=localhost
MILVUS_PORT=19530
EMBEDDING_MODEL=embo-01

# Auth
AUTH_JWT_SECRET=dev-secret
BASE_URL=http://localhost:8080

# Weather
WEATHER_SOURCE=api            # "database" 或 "api"
WEATHER_API_KEY=<your-key>
```

详见 `.env.example`。

## 意图路由

意图路由通过 `plugin_manager.find_by_intent(intent)` 自动完成:

| Plugin | 处理意图 | Manifest 名 |
|--------|---------|------------|
| hr_assistant | insurance | `hr_assistant` (A2A) |
| devops_copilot | incident / oncall / pod_restart | `devops_copilot` (A2A) |
| faq | faq | `faq` (A2A) |
