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
│   │   ├── chat.py                   # ChatService（意图识别 + ReAct 编排）
│   │   ├── memory.py                 # 对话记忆
│   │   └── prompts.py                # 提示模板
│   ├── agents/                       # A2A 智能体层（独立进程，对外 A2A 协议）
│   │   ├── __init__.py
│   │   ├── weather.py                # 端口 5005
│   │   ├── ticket.py                 # 端口 5006
│   │   └── trip.py                   # 端口 5007
│   ├── tools/                        # MCP 工具层（暴露结构化工具）
│   │   ├── __init__.py
│   │   ├── weather.py                # 端口 8002
│   │   ├── ticket.py                 # 端口 8001
│   │   └── trip.py                   # 端口 8003
│   ├── utils/                        # 通用工具
│   │   ├── __init__.py
│   │   ├── format.py                 # JSON 编码器
│   │   └── weather_crawler.py        # 天气数据爬虫
│   └── static/                       # 前端静态资源
├── tests/                            # pytest 测试
│   ├── conftest.py                   # pytest 配置和 fixtures
│   ├── test_mcp_servers.py           # MCP 服务测试（零依赖 + DB 集成）
│   ├── test_mcp_services.py          # MCP 业务服务测试
│   ├── test_agent_services.py        # Agent 端到端测试
│   └── test_*_agent.py               # 各 Agent 单测(manual style)
├── scripts/                          # 一次性脚本（数据初始化等）
│   └── init_tour_group_rag.py        # 旅游团 RAG 数据初始化
├── sql/                              # 数据库脚本（仅 .sql 文件）
│   ├── create_all_tables.sql
│   └── insert_june01_data.sql
└── logs/                             # 运行日志目录
```

## 核心模块说明

### A2A 子代理服务

基于 A2A（Agent2Agent）协议的子代理，运行在独立进程中，通过 LangChain Agent + MCP Tools 模式处理任务：
- **天气 Agent（端口 5005）**：接收天气查询任务，LLM 提取城市/日期参数 → 调用 MCP 参数化工具 → 格式化中文回复
- **票务 Agent（端口 5006）**：接收票务查询/预定任务，LLM 自主选择 MCP 工具（火车票/机票/演唱会查询/预定）→ 格式化中文回复
- **追问检测**：Prompt 约定 `[追问]` 前缀 + `has_data` 关键词兜底，避免 LLM 礼貌用语误判为追问

### 天气 MCP Server（端口 8002）

- **双数据源**：支持 MySQL 数据库 / 和风天气 API 切换（通过 `config.py` 的 `weather_source` 配置）
- **连接池**：使用 `MySQLConnectionPool` 管理数据库连接，连接池大小可配置
- **日期兜底**：`start_date` 为空默认当天，`end_date` 为空默认当天 +29 天；格式错误返回友好提示

### 票务 MCP Server（端口 8001）

- **连接池**：与天气服务共用连接池配置（`pool_name` / `pool_size`），每次查询从池中取连接，用完在 `finally` 中归还
- 火车票查询/预定（`query_train` / `order_train`）
- 机票查询/预定（`query_flight` / `order_flight`）
- 演唱会票查询/预定（`query_concert` / `order_concert`）

### 天气爬虫

- 从和风天气 API 定时拉取 30 天预报数据
- 使用 UPSERT（`ON DUPLICATE KEY UPDATE`）避免重复插入
- 支持定时调度（默认每天 01:00 更新）

### 旅游团 RAG

- 使用 MiniMax `embo-01` 生成 1536 维向量（可在 .env 改 `EMBEDDING_MODEL`）
- 存入 Milvus，支持自然语言语义搜索旅游团

## 数据库表

| 表名 | 说明 |
|------|------|
| `weather_data` | 天气数据（30 天预报） |
| `train_tickets` | 火车票信息 |
| `flight_tickets` | 航班机票信息 |
| `concert_tickets` | 演唱会门票信息 |
| `car_rentals` | 租车信息 |
| `insurances` | 旅行保险信息 |
| `user_profiles` | 用户偏好 |
| `query_history` | 查询历史 |
| `short_term_messages` | 短期对话记录 |

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

### 2. 初始化旅游团向量数据

```bash
uv run python scripts/init_tour_group_rag.py
```

### 3. 启动 MCP Server（用 `make` 或 `python -m`）

```bash
# 用 Makefile（推荐）
make run-weather      # 端口 8002
make run-ticket       # 端口 8001
make run-trip         # 端口 8003

# 或直接命令
uv run python -m CorpAI.tools.weather
uv run python -m CorpAI.tools.ticket
uv run python -m CorpAI.tools.trip
```

### 4. 启动 A2A 智能体

```bash
make run-agent-weather    # 端口 5005
make run-agent-ticket     # 端口 5006
make run-agent-trip       # 端口 5007
```

### 5. 启动 FastAPI 后端

```bash
make run-api
# 访问地址：http://127.0.0.1:8080
```

### 6. 运行测试

```bash
make test           # 全部测试
make test-unit      # 纯单元测试
make test-mcp       # MCP 服务测试（需 MySQL）
make test-agent     # Agent 端到端测试（需 MCP + A2A 服务都在跑）
```

## 配置说明

关键配置项在 `config.py` 的 `Config` 类中：

```python
# 大模型（MiniMax - OpenAI 兼容协议）
self.base_url = 'https://api.minimaxi.com/v1'
self.model_name = 'MiniMax-Text-01'

# 数据库
self.host = 'localhost'
self.user = 'smart_yoyage'
self.database = 'travel_rag'

# 连接池
self.pool_name = "corp_ai_pool"
self.pool_size = 5

# 天气数据源："database" 或 "api"
self.weather_source = "api"
```

## 意图路由

系统通过 `config.py` 中的 `intent` 字典将用户意图路由到对应的 Agent：

| 意图 | Agent |
|------|-------|
| weather | WeatherQueryAssistant |
| flight / train / concert / order | TicketAssistant |
| car_rental / tour_group / insurance / trip_order | TripAssistant |
