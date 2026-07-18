# SmartVoyage - 智能旅游助手

基于大模型 + MCP（Model Context Protocol）的智能旅游助手系统，支持天气查询、票务查询（火车票/机票/演唱会）、旅游团语义推荐等功能。

## 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.x | 开发语言 |
| MySQL | 业务数据存储（天气、票务、租车、保险等） |
| Milvus | 向量数据库，用于旅游团 RAG 语义检索 |
| FastMCP (python_a2a) | MCP 工具服务框架 |
| uvicorn | ASGI 服务器 |
| Qwen (DashScope) | 大模型 + Embedding API |
| 和风天气 API | 天气数据源 |
| schedule | 定时任务调度 |

## 项目结构

```
SmartVoyage/
├── config.py                     # 全局配置（大模型、数据库、API、意图路由）
├── create_logger.py              # 日志模块
├── a2a_server/                   # A2A 子代理服务（通过 A2A 协议与主助手通信）
│   ├── weather_server.py         # 天气查询 Agent（端口 5005，LangChain Agent + MCP Tools）
│   └── ticket_server.py          # 票务查询 Agent（端口 5006，LangChain Agent + MCP Tools）
├── mcp_server/                   # MCP 工具服务
│   ├── mcp_weather_server.py     # 天气查询 MCP Server（端口 8002）
│   └── mcp_ticket_server.py      # 票务查询 MCP Server（端口 8001）
├── sql/                          # 数据库相关
│   ├── create_all_tables.sql     # 全量建表脚本
│   ├── insert_june01_data.sql    # 6月1日票务及租车/保险初始数据
│   └── init_tour_group_rag.py    # 旅游团 RAG 初始化（Milvus 向量入库）
├── utils/                        # 工具模块
│   ├── format.py                 # JSON 编码器（date/Decimal 类型处理）
│   └── spider_weather.py         # 天气数据爬虫（和风天气 API + 定时更新）
├── test_weather_agent.py         # 天气 Agent 测试脚本
└── logs/                         # 日志文件目录
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

- 使用 Qwen `text-embedding-v3` 生成 1024 维向量
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

### 1. 初始化数据库

```bash
# 执行全量建表脚本
mysql -u smart_yoyage -p < sql/create_all_tables.sql
```

### 2. 初始化旅游团向量数据

```bash
python sql/init_tour_group_rag.py
```

### 3. 启动天气 MCP Server

```bash
python mcp_server/mcp_weather_server.py
# 访问地址：http://127.0.0.1:8002/mcp
```

### 4. 启动票务 MCP Server

```bash
python mcp_server/mcp_ticket_server.py
# 访问地址：http://127.0.0.1:8001/mcp
```

### 5. 启动 A2A 子代理

```bash
# 天气 Agent
python a2a_server/weather_server.py
# 访问地址：http://127.0.0.1:5005

# 票务 Agent
python a2a_server/ticket_server.py
# 访问地址：http://127.0.0.1:5006
```

### 6. 启动天气爬虫（可选）

```bash
python utils/spider_weather.py
```

## 配置说明

关键配置项在 `config.py` 的 `Config` 类中：

```python
# 大模型
self.base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
self.model_name = 'qwen-plus'

# 数据库
self.host = 'localhost'
self.user = 'smart_yoyage'
self.database = 'travel_rag'

# 连接池
self.pool_name = "smart_voyage_pool"
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
