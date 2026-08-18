# CorpAI — 企业 AI Copilot 平台

> 可插拔多 Agent · 统一 RBAC · 端到端可观测 · LLM + RAG + 工具编排

CorpAI 是一个面向企业内部场景的 AI Copilot 平台:把对话、记忆、检索、工具调用、权限审批、可观测性收敛到一个 FastAPI 后端,业务能力通过插件协议(Anthropic 官方 A2A + MCP)独立部署、独立扩展。仓库内置三个真实生产化业务插件:**HR 助理**(请假/报销/证明/资产/培训)、**SRE Copilot**(告警响应 / 故障处置 / 飞书审批 / 7 步 incident 闭环)、**Knowledge**(Milvus 语义检索 RAG,被 SRE 调作为企业知识中心)。

---

## 🎯 v1 设计哲学(2026-08 定稿)

> **CorpAI 是一个面向企业的 Agent Runtime,以 Multi-Agent 协作完成复杂任务,以 Plugin 适配不同企业基础设施,以 MCP 安全调用企业系统,并结合 RAG、RBAC、Approval 和 Observability,形成从分析、决策、执行到验证的完整闭环。**

定位:不是 "Multi-Agent 平台" 也不是 "可插拔平台",而是 **Enterprise Agent Runtime**。Multi-Agent 是手段(任务复杂时),Plugin 是手段(企业差异时),MCP 是手段(调用协议时)。本体是 Runtime。

详细见 `LAYERS.md`(分层编号约定)+ `ARCHITECTURE.md`(架构细节)+ `CLAUDE.md`(Claude Code 项目指南)。

---

## ✨ 核心能力

- **多 Agent 编排**:IntentRecognizer → TaskPlanner → ReActRunner,按 `required_intents` 自动 dispatch 到对应 llm_agent 插件
- **6 层对话记忆**:per-user MemoryPool(短期 / 长期 / 任务上下文 / 跨 Agent / 偏好 / 摘要)
- **可插拔插件协议**:每个业务插件声明 `PluginManifest`(name / version / endpoint / permissions / structured_tools),通过 `importlib.metadata.entry_points` 自动发现
- **统一 RBAC**:JWT + scope → 角色 → 插件 permission → 端点二次校验的全链路
- **端到端可观测**:trace_id 贯穿 HTTP/LLM/工具调用;Prometheus `/metrics` + 结构化日志 + call_records 落库
- **A2A + 真 MCP 双协议**:插件通过 A2A Server 暴露 Agent 能力(LLM 推理入口),通过 **Anthropic 官方 MCP 协议**(fastmcp 3.x + MCP SDK 2.x,JSON-RPC 2.0 over StreamableHTTP)暴露工具能力;HR/SRE 互相 Bridge 调用
- **飞书集成**:审批结果通过飞书卡片推送 / 回调 (`/feishu/event`),含签名校验

---

## 🧱 架构

```
                ┌─────────────────────────────────────────────┐
                │        Frontend SPA  (_5_static/)            │
                └────────────────────┬────────────────────────┘
                                     │ HTTP / SSE
                ┌────────────────────▼────────────────────────┐
                │       _0_CorpAI FastAPI  (port 8080)        │
                │  /api/chat · /api/chat/stream · /admin ·   │
                │  /metrics · /health · /feishu/event         │
                ├─────────────────────────────────────────────┤
                │  _0_CorpAI/_0_api/  (HTTP 边界)             │
                │  _0_CorpAI/_1_core/ (business core 纯算法)   │
                │  _0_CorpAI/_2_platform/                     │
                │   ├─ orchestrator   (Intent / Plan / ReAct) │
                │   ├─ auth           (JWT + RBAC scopes)     │
                │   ├─ observability  (trace / log / metrics) │
                │   ├─ plugin_manager (entry_points 自动发现) │
                │   ├─ db             (MySQL 连接池)          │
                │   └─ wiring         (Composition Root)      │
                │  _0_CorpAI/_3_utils/ (dotenv / format)      │
                └────────┬───────────┬────────────┬───────────┘
                         │ A2A      │ A2A         │ A2A
              ┌──────────▼──┐ ┌─────▼──────┐ ┌────▼──────┐
              │  hr_assistant│ │ sre_copilot│ │ knowledge │
              │   :5010     │ │   :5020    │ │   :5030   │
              │  + 9 MCPs   │ │ + 6 MCPs   │ │ + 2 MCPs  │
              │   :8001     │ │ :8020/8021│ │   :8030   │
              │  (1 server) │ │ /8022/8027│ │ (1 server)│
              │             │ │  /8028     │ │           │
              └─────────────┘ └────────────┘ └───────────┘
                  MySQL (CorpAI) · Milvus :19530 · Redis :16379 · Prometheus
```

设计依据见 `ARCHITECTURE.md`,分层约定见 `LAYERS.md`。

---

## 📁 目录结构

```
_0_CorpAI/                         # 平台核心包(应用项目,不打包到 site-packages)
├── _0_api/                         # 入站适配层 ─ FastAPI app + admin/demo router
├── _1_core/                        # 业务核心 ─ memory(6 层 MemoryPool)· prompts(纯 Python)
├── _2_platform/                    # 基础设施层
│   ├── orchestrator/               # IntentRecognizer / TaskPlanner / ReActRunner / streaming
│   ├── auth/                       # RBAC scopes / JWT / passwords / dependencies / audit
│   ├── observability/              # trace / log / metrics / otel / call_record
│   ├── db.py                       # MySQL 连接池(DatabasePool 单例)
│   ├── plugin_manager.py           # PluginManifest + entry_points 自动发现
│   └── wiring.py                   # ★ Composition Root ─ 唯一允许引 LangChain / A2A / mysql 的地方
└── _3_utils/                       # dotenv / format / strip_think

_1_plugins/                         # 业务插件(各为独立包,pip install -e)
├── hr_assistant/                   # HR 操作类工具 + 跨插件 bridge(原 devops_copilot / faq 已合并)
│   ├── hr_tests/                   # 单元测试(改名前是 tests/,改名避免 plugin 间同名 module 冲突)
│   ├── pyproject.toml              # 含 [tool.pytest.ini_options] pythonpath + testpaths
│   ├── README.md
│   └── src/hr_assistant/...
├── sre_copilot/                    # 告警/故障 + 飞书审批
│   ├── sre_tests/
│   └── src/sre_copilot/...
└── knowledge/                      # Milvus RAG + MiniMax embo-01 embedding(原 faq plugin)
    ├── knowledge_tests/
    └── src/knowledge/...

_2_scripts/                         # 迁移脚本 + bootstrap(首 super_admin / 飞书测试 / sre mock producer)
_3_sql/                             # DDL:create_all_tables.sql + 各 phase 迁移
_4_tests/                           # 平台测试(conftest.py 统一 sys.path + fixture)
├── platform/                       # Phase 1.7 + Phase 2 orchestrator/memory_pool
├── auth/                           # Phase 3 RBAC + JWT
├── observability/                  # Phase 4 trace/log/metrics/call_record
└── memory_pool/                    # 5 层记忆测试
_5_static/                          # Admin Web 静态资源(index.html + admin/*)

pyproject.toml                      # 平台依赖(>=3.11,含 mcp + fastmcp)
uv.lock                             # uv 锁定(勿手动改)
.env.example                        # 配置样例(必填项:API_KEY / AUTH_JWT_SECRET)
Dockerfile.api                      # 平台镜像(端口 8080)
Dockerfile.plugin                   # 插件通用镜像(build-arg PLUGIN_NAME / PORT)
corpai-milvus.yml                   # Milvus standalone 依赖(etcd + minio + standalone + attu)
corpai-redis.yml                    # SRE async executor 用的 Redis Stream broker
Makefile                            # 同步/测试/迁移/启动入口
LAYERS.md                           # 分层编号约定(顶层 _0–_5 + 包内 _0_api/_1_core/_2_platform/_3_utils)
ARCHITECTURE.md                     # 详细架构:Composition Root、MCP 真协议、Memory 模型、plugin 协议
CLAUDE.md                           # Claude Code 项目指南
CONTRIBUTING.md                     # 开发指南:装环境 / 跑测试 / 加新 plugin / MCP 改动守则
CHANGELOG.md                        # 改动日志
docs/adr/                           # 架构决策记录
```

> **编号约定**:顶层 `_0`–`_5` = 平台 → 插件 → 脚本 → SQL → 测试 → 静态(IDE 排序友好,新人一眼看懂依赖方向)
> 包内 `_0_api`/`_1_core`/`_2_platform`/`_3_utils` = 入站适配 → 业务核心 → 基础设施 → 工具
> 详见 `LAYERS.md`

---

## 🛠️ 技术栈

| 层 | 选型 |
|---|---|
| Web | FastAPI 0.116+ · Uvicorn · Pydantic v2 |
| LLM 编排 | LangChain 1.0 · ChatPromptTemplate · ChatOpenAI |
| LLM 默认 | MiniMax `MiniMax-Text-01`(`base_url = https://api.minimaxi.com/v1`,可换 OpenAI 兼容接口) |
| Embedding | MiniMax `embo-01`(1536 维) |
| 关系库 | MySQL(`mysql-connector-python`,自带连接池) |
| 向量库 | Milvus 2.5+(独立 docker compose) |
| 缓存 / Stream | Redis(`SRE_DRY_RUN` async executor 用 Redis Stream) |
| Plugin A2A 协议 | `python-a2a`(A2AServer,LLM agent 入口) |
| Plugin MCP 协议 | **fastmcp 3.x + MCP SDK 2.x**(Anthropic 官方 spec,JSON-RPC 2.0 over StreamableHTTP) |
| 可观测 | `prometheus-client` / `/metrics` + 结构化日志 + `call_records` 表 |
| 依赖管理 | `uv`(锁文件 `uv.lock`) |

---

## 🚀 快速开始

### 前置依赖

- Python **3.11+**(`.python-version` 锁定)
- [`uv`](https://github.com/astral-sh/uv)(装包 / 跑脚本)
- MySQL 8(本地默认 `admin@localhost`)
- Milvus 2.5+(`docker compose -f corpai-milvus.yml up -d`)
- Redis 7(可选,仅 SRE async executor 需要;Windows 默认用 `:16379` 避开占用)
- Docker / Docker Compose(运行依赖服务时)

### 1. 克隆并装依赖

```bash
git clone <repo-url> CorpAI
cd CorpAI
uv sync --group dev                  # 平台核心 + 3 个 plugin + dev 测试依赖
make install-plugins                 # 把 3 个 plugin 装成 editable(否则 plugin import 失败)
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 必填(无 dev 缺省):
#   API_KEY            — LLM API key
#   AUTH_JWT_SECRET    — JWT 签名密钥(≥32 字节,生产用 secrets.token_urlsafe(48) 生成)
# 可选:MYSQL_* / MILVUS_* / JIRA_* / PAGERDUTY_* / FEISHU_* / K8S_DRY_RUN …
```

完整字段说明见 `.env.example` 顶部注释。Windows 默认 Redis 端口 `16379`(避开本机 6379 占用),改这里要同步改 `corpai-redis.yml`。

### 3. 初始化数据库

```bash
# 方式 A:用 _3_sql/ 全量 DDL
mysql -u admin -p CorpAI < _3_sql/create_all_tables.sql

# 方式 B:增量迁移(推荐)
make migrate-phase2                  # user_id + task_context + cross_agent_context
make migrate-phase3                  # RBAC 4 张表 (auth_*)
make migrate-phase4                  # call_records
```

### 4. 引导第一个 super_admin + 3 个 plugin 演示用户

```bash
make bootstrap-superadmin                       # 创建超管(交互式密码)
uv run python _2_scripts/bootstrap_plugin_users.py # 创建 3 个 plugin 演示用户
```

后者会创建:

| 用户名 | 角色 | scopes | 可用 |
|---|---|---|---|
| `hr_alice` | employee | + `hr:read,hr:write,knowledge:read` | HR plugin + 跨调 knowledge |
| `sre_bob` | employee | + `sre:read,sre:write,sre:approve,knowledge:read` | SRE plugin(含飞书审批)+ 跨调 knowledge |
| `knowledge_carol` | employee | + `knowledge:read` | 只读 knowledge plugin(演示 RBAC 隔离) |

**演示 RBAC 隔离**:
- `hr_alice` 问"请年假"→ HR plugin 响应
- `knowledge_carol` 问"请年假"→ 401(有 `knowledge:read` 但缺 `hr:write`)
- `sre_bob` 问"CPU 飙高"→ SRE plugin 响应,可发飞书审批卡

默认密码 `CorpAI2026`,生产必改。

### 5. 启动依赖服务(Milvus / Redis)

```bash
docker compose -f corpai-milvus.yml up -d
docker compose -f corpai-redis.yml up -d     # 仅 SRE 需要
```

### 6. 启动平台 + 插件

> 每个进程单独开一个终端。插件启动后 `discover_all()` 会通过 entry_points 自动加载,无需改平台代码。

```bash
# 终端 1 — 平台主服务
make run-api                          # → http://localhost:8080

# 终端 2 / 3 / 4 — 三个业务插件 A2A server
make run-hr-assistant                 # → http://localhost:5010
make run-sre-copilot                  # → http://localhost:5020
make run-knowledge                    # → http://localhost:5030
```

打开浏览器访问 `http://localhost:8080`,登录后在 chat 框里提问即可触发意图识别 + 插件 dispatch。

### 7. 启动 MCP server(可选,用于外部 MCP 客户端接入)

```bash
make run-mcp-hr-assistant             # 启 hr_assistant MCP server(:8001)
make run-mcp-sre-copilot              # 启 sre_copilot 5 个 MCP server
make run-mcp-knowledge                # 启 knowledge MCP server(:8030)
```

### 8. (可选)本地调试飞书

飞书后台要求公网 URL 才能回调。本地用 ngrok 暴露 8080:

```bash
# .env 填 NGROK_AUTHTOKEN 后
python _2_scripts/run_all.py            # 同时拉起平台 + ngrok + 飞书 webhook
```

---

## 🧪 测试

```bash
make test                            # 全部(含 integration,需 MySQL/Milvus)
make test-unit                       # 排除 -m integration 的纯单元测试(不依赖外部服务)

# 分阶段:
make test-platform                   # Phase 1.7 + Phase 2 orchestrator/memory_pool
make test-auth                       # Phase 3 RBAC + JWT 单元测试
make test-observability              # Phase 4 Observability 单元测试(trace/log/metrics/call_record)
make test-plugins                    # Phase 5 3 个真插件单元测试(需先 make install-plugins)
make test-phase3 / test-phase4 / test-phase5

# 单独跑一类:
.venv/Scripts/python.exe -m pytest _4_tests/observability -v   # observability 单独
.venv/Scripts/python.exe -m pytest _4_tests/auth -v            # auth 单独
.venv/Scripts/python.exe -m pytest _4_tests/platform -v        # orchestrator/platform 单独
```

测试用 `AUTH_JWT_SECRET=dev-secret uv run pytest …`(Makefile 已设)。

---

## 🐳 Docker 部署

```bash
# 平台主服务
docker build -f Dockerfile.api -t corpai-api:latest .
docker run -p 8080:8080 --env-file .env corpai-api:latest

# 插件镜像(参数化)
docker build -f Dockerfile.plugin \
  --build-arg PLUGIN_NAME=hr_assistant --build-arg PORT=5010 \
  -t corpai-hr:latest .
docker run -p 5010:5010 --env-file .env corpai-hr:latest
```

`Dockerfile.api` / `Dockerfile.plugin` 均:**多阶段构建**(builder + runtime 瘦身)+ **非 root 运行**(uid 1000 corpai)+ **HEALTHCHECK**(`/health`,纯 stdlib urllib,不依赖 curl)。

未来全栈编排(api + plugins + 依赖服务)计划通过单一 compose 文件拉起,目前各服务独立 compose(`corpai-milvus.yml` / `corpai-redis.yml`)。

---

## 🔌 插件一览

| Plugin | Type | A2A 端口 | MCP 端口 | 主要 intents | RBAC scopes | 关键能力 |
|---|---|---|---|---|---|---|
| **hr_assistant** v3.2 | llm_agent + 10 mcp_tool | 5010 | 8001(1 server,9 tools) | `hr / leave / reimbursement` | `hr:read · hr:write` | 请假 / 报销 / 在职证明 / 资产 / 培训 / 转正 / 审批 / 查询;2 个跨插件 bridge (knowledge/sre) |
| **sre_copilot** v3.1 | llm_agent + 6 mcp_tool | 5020 | 8020 (incident+oncall) / 8021 (k8s) / 8022 (alert) / 8027 (bridge-hr) / 8028 (bridge-knowledge) | `sre / incident / alert` | `sre:read · sre:write · sre:approve` | 告警响应 / 故障排查 / 飞书审批卡片 / 异步执行修复方案 (Redis Stream) / 跨插件桥 |
| **knowledge** v1.1 | llm_agent + 2 mcp_tool | 5030 | 8030 | `faq` | `knowledge:read` | Milvus 语义检索 RAG;启动时 `seed_default_kb()` 幂等注入默认企业 KB(原 faq plugin,已改名) |

新增插件的最短流程(详见 `_0_CorpAI/_2_platform/plugin_manager.py` 头注释):

1. 在 `_1_plugins/<name>/src/<name>/` 写 `plugin.py`,实现 `register(registry) -> None`
2. 在 `pyproject.toml` 的 `[project.entry-points."platform.plugins"]` 声明
3. `make install-plugins` 即可被 `discover_all()` 自动加载

每个 manifest 必须声明 `permissions`,至少 1 个 scope 字符串(如 `hr:read` / `sre:write`);`PluginRegistry.register` 会拒绝空列表。

---

## ⚙️ 配置项速查

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `API_KEY` | ✅ | — | LLM API key |
| `BASE_URL` |  | `https://api.minimaxi.com/v1` | OpenAI 兼容端点 |
| `MODEL` |  | `MiniMax-Text-01` | 对话模型 |
| `EMBEDDING_MODEL` |  | `embo-01` | Embedding 模型(1536 维) |
| `MYSQL_*` |  | `localhost / admin / CorpAI` | 连接池 `MYSQL_POOL_SIZE=5` |
| `MILVUS_HOST/PORT` |  | `localhost:19530` | 远程 dev 改 LAN IP |
| `AUTH_JWT_SECRET` | ✅ | — | JWT 签名密钥(fail-closed,没设则 admin 端点拒启) |
| `DEV_NO_AUTH=1` |  | — | **仅本地开发**:跳过 JWT 校验授予 `["*"]` 权限。生产禁用 |
| `FEISHU_APP_ID/SECRET/ENCRYPT_KEY` |  | — | 飞书卡片推送 + 签名校验 |
| `JIRA_* / PAGERDUTY_* / PROMETHEUS_URL` |  | — | SRE 工具真实 SDK 接入 |
| `K8S_DRY_RUN` |  | `true` | `false` 走真实 K8s API |
| `SRE_DRY_RUN` |  | `true` | async executor dry-run(不真调 K8s/Jira) |
| `REDIS_URL` |  | `redis://localhost:16379/0` | Windows 默认避开 6379 |
| `KNOWLEDGE_URL` |  | `http://localhost:8030` | knowledge MCP server(原 FAQ_URL,v3.2 改名) |

> `MYSQL_PASSWORD` 等凭据**严禁**提交到仓库。`.env` 已在 `.gitignore`。

---

## 🎬 Demo 流程(2026-08 新增)

admin → "Demo" 标签 → 触发 Incident → 7 步流水线实时推 SSE:

```
Alert → Metrics Agent → K8s Agent → Log Agent → Knowledge Agent
     → Diagnosis Agent(LLM 真推理)→ Action Agent(LLM 真规划)
     → Verification Agent(对比 pre/post metrics,80% 通过 / 20% re-plan)
     → Policy Engine 路由(auto/approval 分类)→ Feishu 卡构造(M3 简化:不真发)
     → Re-plan 闭环(verify fail → 把 evidence 喂回 DiagnosisAgent 重做,最多 2 次)
```

数据流两种走法:
- **不走 Kafka**(只 CorpAI + sre_copilot):`make run-api` + admin → Demo → 触发。数据由 agent 内部产生(demo 离线也能跑)
- **走 Kafka**(完整数据 pipeline):`docker compose -f corpai-kafka.yml up -d` + `bash _2_scripts/run_sre_demo.sh`。Mock Producer 推真实时序数据到 7 topic,SRE Pipeline / Action Executor 消费

---

## 📚 文档导航

| 文档 | 用途 |
|---|---|
| **README.md**(本文) | 项目门面:能力 / 架构 / 快速开始 / 测试 / 部署 / 插件一览 |
| **LAYERS.md** | 分层编号约定(顶层 `_0`–`_5` + 包内 4 层),新人 onboarding 第一站 |
| **ARCHITECTURE.md** | 详细架构:Composition Root 模式、MCP 真协议选型、Memory 模型、Plugin 注册机制、跨插件 Bridge 异步处理 |
| **CLAUDE.md** | Claude Code 项目指南:跑测试命令、不能碰的区域(Composition Root 唯一性)、commit message 规范 |
| **CONTRIBUTING.md** | 开发指南:装环境 → 跑测试 → 加新 plugin/agent → MCP 改动守则 → commit |
| **CHANGELOG.md** | 改动日志(layer 编号重构 / MCP 协议升级 / plugin hatchling / bridges async / test dir 改名) |
| **docs/adr/** | 架构决策记录(Clean Architecture 分层、Plugin entry_points 机制、MCP 协议选型、hatchling build-system) |
| **AUDIT_REPORT.md**(历史) | 2026-08-11 全量代码审计报告(50 个 finding),`feat: 安全硬化与异步化收敛` 之后已修复多个 P0 |

---

## 🔒 安全

仓库根的 `AUDIT_REPORT.md` 是 **2026-08-11 的全量代码审计报告**,共 50 个 finding(13 P0 / 7 P1 / 18 P2 / 12 P3),覆盖认证授权 / webhook 签名 / 配置注入 / RBAC scope 链路 / 测试 / CI / 文档 / 部署。`feat: 安全硬化与异步化收敛` 之后已修复多个 P0(包括未认证默认 super_admin、飞书签名校验可绕过、`.env` 含真实密钥等)。

> 上线前请务必:① 重读 `AUDIT_REPORT.md`;② `AUTH_JWT_SECRET` 用 `secrets.token_urlsafe(48)` 生成并从 secret manager 注入;③ `DEV_NO_AUTH=1` 仅本地;④ 飞书 `FEISHU_ENCRYPT_KEY` 必填开启签名校验;⑤ `K8S_DRY_RUN=false / SRE_DRY_RUN=false` 前确保 K8s / Jira / PagerDuty 凭据走最小权限 service account。

---

## 📜 文档索引

- `LAYERS.md` — 分层编号约定
- `ARCHITECTURE.md` — 架构细节
- `CLAUDE.md` — Claude Code 项目指南
- `CONTRIBUTING.md` — 开发指南
- `CHANGELOG.md` — 改动日志
- `docs/adr/` — 架构决策记录

---

## 🧭 项目状态

- 版本:`v1.0.0`(应用项目,非库;不打包到 site-packages)
- Python:3.11+
- 状态:生产就绪(3 个 plugin + 完整 RBAC + Observability)