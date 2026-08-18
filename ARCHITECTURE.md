# ARCHITECTURE.md — 详细架构

## 目录

1. [分层架构](#1-分层架构)
2. [Composition Root 模式](#2-composition-root-模式)
3. [Plugin 协议](#3-plugin-协议)
4. [MCP 真协议](#4-mcp-真协议)
5. [Memory 模型](#5-memory-模型)
6. [RBAC 链路](#6-rbac-链路)
7. [Observability 链路](#7-observability-链路)
8. [跨 plugin Bridge](#8-跨-plugin-bridge)
9. [编排:ReAct + Stream](#9-编排react--stream)
10. [数据流图](#10-数据流图)

---

## 1. 分层架构

```
_0_CorpAI/
├── _0_api/          ← 入站适配(FastAPI 边界)
├── _1_core/         ← 业务核心(纯算法,框架无关)
├── _2_platform/     ← 基础设施 + 横切关注点
└── _3_utils/        ← 工具(dotenv, format)
```

依赖规则(单向,绝不反向):

```
_0_api  ─→  _2_platform  ─→  _3_utils
   │            │
   └────────────└─→  _3_utils

_1_core  ←───(无外部依赖)──────────
```

| 层 | 职责 | 能做什么 | 不能做 |
|---|---|---|---|
| `_0_api` | FastAPI app、HTTP 边界 | import `_2_platform` / `_3_utils` / 业务 router | 写业务逻辑 |
| `_1_core` | 业务实体(`ConversationMemory`、prompts) | 纯 stdlib + 平台内部 | **import 任何框架**(FastAPI / LangChain / mysql) |
| `_2_platform` | orchestrator / auth / observability / db / plugin_manager / wiring | import `_1_core` / `_3_utils` / LangChain / python_a2a / mysql(只在 `wiring.py`) | 暴露 HTTP 端点 |
| `_3_utils` | dotenv / format / strip_think | 纯 stdlib | 业务逻辑 |

**核心约束**:`_1_core/` 是孤岛。任何方向都不能跨 —— 这是 Clean Architecture 依赖倒置的实际落地。

---

## 2. Composition Root 模式

**原则**:依赖倒置 + 单一装配点。

`_0_CorpAI/_2_platform/wiring.py` 是**唯一**允许 import 外部 SDK 的位置:

```python
# wiring.py ─ 唯一允许以下 import
import mysql.connector
from langchain_openai import ChatOpenAI
from python_a2a import AgentNetwork, Message, MessageRole, Task, TextContent
from python_a2a.client import A2AClient

# 把这些实例组装成 OrchestratorService
```

**为什么**:改 LLM / DB / A2A 框架时只动这一个文件,其他模块保持纯。

### `_2_platform/orchestrator/*` 保持纯净

`_2_platform/` 下的其他文件(`orchestrator/`, `auth/`, `observability/`)**不**直接 import 框架。它们通过 wiring 注入的抽象接口工作。

如果发现 `orchestrator/service.py` 里 `import mysql.connector`,那是 bug —— 必须通过 wiring 注入。

---

## 3. Plugin 协议

### 注册机制:Python entry_points

每个 plugin 是独立 Python 包,通过 `pyproject.toml` 的 entry_points 注册:

```toml
[project.entry-points."platform.plugins"]
hr_assistant = "hr_assistant.plugin:register"
```

`platform` 启动时调 `importlib.metadata.entry_points()` 扫,自动加载。

### PluginManifest

```python
PluginManifest(
    name="hr_assistant_leave_mcp",     # 全局唯一
    version="3.2.0",
    description="请假申请",
    plugin_type="mcp_tool",            # "llm_agent" | "mcp_tool"
    endpoint="http://localhost:8001",   # A2A / MCP server URL
    mcp_tool_name="submit_leave",      # 调哪个 tool 函数
    permissions=["hr:write"],          # RBAC scope(至少 1 个)
    tags=[...],
)
```

### 双类型

| type | 含义 | endpoint 语义 |
|---|---|---|
| `llm_agent` | LLM agent 入口 | A2A server URL(LLM 推理) |
| `mcp_tool` | 工具入口 | MCP server URL(工具调用) |

### 端口分配

| Plugin | A2A | MCP |
|---|---|---|
| `hr_assistant` | :5010 | :8001(1 server 跑 9 tools) |
| `sre_copilot` | :5020 | :8020/8021/8022/8027/8028(5 servers) |
| `knowledge` | :5030 | :8030 |

**manifest endpoint 必须 = 实际 MCP server 的端口**。否则 `PluginRegistry.discover_all()` 加载 manifest,但 dispatch 时打到错的端口 → MCP client `tools/list` 失败 → `bridge_unavailable`。

### hr_assistant 端点统一

v3.2 把 hr_assistant 的 10 个 mcp_tool manifest endpoint **全改成 :8001**(单端口 9 tools),废弃老的"每 tool 一端口"(8017-8026)架构。**单端口 + `@server.tool()` 多 tool** 是官方 MCP 推荐做法。

---

## 4. MCP 真协议

### 不用 python_a2a 自带的 FastMCP

python_a2a 的 `FastMCP` 走**私有 HTTP 协议**(`POST /mcp/tools/{tool_name}`),**不是** Anthropic MCP spec。

### 用 Anthropic 官方 SDK

```toml
# pyproject.toml
"mcp>=1.0",
"fastmcp>=3.4.7",
```

- `mcp` 是官方 SDK,提供 `mcp.server.fastmcp.FastMCP`(在 2.x 版本里被 deprecated 移出,改名为 `MCPServer`)
- `fastmcp` 是 Prefect 的独立包(被官方 SDK 吸收),3.x 是社区标准

### Tool 定义

```python
from fastmcp import FastMCP

hr_server = FastMCP(name="hr_assistant", instructions="...")

@hr_server.tool()
def submit_leave(authorization: str, leave_type: str, ...) -> str:
    """提交请假申请。需 hr:write scope。"""
    return a.submit_leave(authorization=..., leave_type=...)
```

`@tool()` decorator 自动从函数签名 + docstring 推导 **JSON Schema**(Anthropic MCP spec 标准格式)。

### Transport:StreamableHTTP

```python
hr_server.run_http_async(
    transport="streamable-http",   # Anthropic MCP 标准 transport
    host="0.0.0.0",
    port=8001,
    log_level="INFO",
)
```

不是 SSE(老 transport),不是 stdio(子进程模式)。StreamableHTTP 是 2025-03 spec 的现代 transport。

### 协议验证

curl 测一下:

```bash
curl -X POST http://127.0.0.1:8020/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",...}'
```

应该返回:
- `HTTP/1.1 200 OK`
- `mcp-session-id` header
- `content-type: text/event-stream`
- JSON-RPC 2.0 响应,`serverInfo.name="sre_copilot_incident"` 等

---

## 5. Memory 模型

**6 层对话记忆**,per-user 隔离:

| 层 | 存储 | 用途 | 实现 |
|---|---|---|---|
| L1 短期消息 | 短期对话 history | 当前会话上下文 | `MemoryPool.short_term_messages` |
| L2 用户偏好 | KV | 跨 session 偏好 | `MemoryPool.user_profile` |
| L3 实体历史 | 提取的人物/地点 | 实体引用 | `MemoryPool.entity_history` |
| L4 任务上下文 | 当前任务 state | 多轮任务跟踪 | `MemoryPool.task_context` |
| L5 跨 Agent | agent 间共享 | 多 agent 协作 | `MemoryPool.cross_agent_context` |
| L6 摘要 | 长对话压缩 | 长 session 滚动 | `MemoryPool.summary` |

`_1_core/memory.py` 是纯 Python(无 mysql connector),DB 连接通过 `_2_platform/db.py` 的 `DatabasePool` 单例注入。

---

## 6. RBAC 链路

**端到端**:

```
JWT token
  → decode (auth/tokens.py)
  → claims.scopes (e.g. ["hr:read", "hr:write"])
  → role + per_user merge (auth/scopes.py)
  → PluginManifest.permissions 比对
  → endpoint 二次校验 (tools.py 内 _check_scope)
```

**两层校验**:
1. **平台层**:manifest 注册时,`PluginRegistry.register` 拒绝空 `permissions`
2. **工具层**:tool 函数入口调 `_check_scope(authorization, "hr:write")`,缺 scope 抛 `PermissionError`

---

## 7. Observability 链路

```
HTTP request
  → x-trace-id middleware (observability/trace.py)
  → ContextVar propagation (thread + asyncio)
  → structured JSON log (observability/log.py)
  → Prometheus /metrics counter (observability/metrics.py)
  → call_records table 落库 (observability/call_record.py)
```

`trace_id` 贯穿 HTTP → LLM → 工具调用,失败时一个 trace_id 能查到完整链路。

---

## 8. 跨 plugin Bridge

### 协议层

bridge 走**真 MCP client**(不是自定义 HTTP):

```python
# sre_copilot/bridges.py
from fastmcp import Client

async def _bridge_call_async(target, url, tool_name, **kwargs):
    async with Client(url, timeout=_BRIDGE_TIMEOUT) as c:
        result = await c.call_tool(tool_name, kwargs)
        return json.loads(result.content[0].text)
```

### 双接口:async + sync

- `async def cross_check_hr_async(...)`:真异步,ReAct loop 用
- `def cross_check_hr(...)`:同步包装,`asyncio.run()` 包一层,给 sync 上下文(A2A server.handle_task 当前是 sync)

### 错误契约

失败返回 `{status: bridge_unavailable, kind: timeout|unreachable|tool_error|json_decode, message}`,**绝不 silent**。

bridge 计数:`HR_BRIDGE_ERRORS_TOTAL{target, kind}`(复用 hr metrics 因为跨 plugin)。

---

## 9. 编排:ReAct + Stream

`_0_CorpAI/_2_platform/orchestrator/`:
- `intent.py` — IntentRecognizer,从用户消息识别 intent
- `planner.py` — TaskPlanner,把 intent 拆成 action list
- `react_loop.py` — ReActRunner,Thought → Action → Observation 循环
- `streaming.py` — SSE 流式输出
- `service.py` — OrchestratorService 抽象基类

dispatch 流程:
1. IntentRecognizer 识别 intent(如 `hr / leave`)
2. PluginRegistry 按 `required_intents` 找到对应 llm_agent
3. 调 A2A server(task metadata 透传 user JWT)
4. llm_agent 用 ReAct 循环,可能调 MCP tool(包括跨 plugin bridge)
5. 结果 SSE 流式回前端

---

## 10. 数据流图

```
[User chat] → [_0_api/app.py FastAPI]
                   ↓ POST /api/chat
              [orchestrator/service.py]
                   ↓ IntentRecognizer → TaskPlanner
                   ↓ required_intents match
              [plugin_manager.PluginRegistry]
                   ↓ _resolve_plugin(intent)
              [A2A client → plugin llm_agent]
                   ↓ POST task (含 JWT)
              [plugin/server.py handle_task]
                   ↓ _route (keyword match)
                   ↓ [plugin/tools.py 或 plugin/actions.py]
                          ↓ MCP tool call
                          ↓ return JSON envelope
                   ↓ return response
              [orchestrator/react_loop.py]
                   ↓ stream SSE
              [_0_api/app.py SSE response]
                   ↓
              [Frontend _5_static/index.html]
```

---

## 关键设计决策(完整 ADR 见 `docs/adr/`)

| 决策 | 选择 | 理由 |
|---|---|---|
| 分层架构 | Clean Architecture 轻量版 | 新人 onboarding 直观,Composition Root 隔离外部依赖 |
| Plugin 协议 | Python entry_points | 标准机制,自动发现,无需中心注册表 |
| MCP 协议 | Anthropic 官方 spec | 互操作,可被 Claude Desktop / Cursor 等客户端消费 |
| LLM provider | LangChain + ChatOpenAI | 支持任意 OpenAI 兼容 API(MiniMax / OpenAI / 智谱 / …) |
| 记忆存储 | MySQL(6 层 JSON) | 企业内部易部署,SQL 即可查 |
| 流式输出 | SSE | FastAPI 原生支持,代理友好 |
| Bridge 协议 | 真 MCP | 跨 plugin 跟外部 client 一致,不用私有协议 |