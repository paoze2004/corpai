# ADR-002: 保留 FastMCP Wire 协议

## 状态
**Accepted** — 2026-08-06

## 背景

CorpAI 当前有 3 个 MCP server(`tools/{weather,ticket,trip}.py`),各自跑在 8001/8002/8003 端口,通过 HTTP 协议暴露工具。3 个 agent(`agents/{weather,ticket,trip}.py`)通过 `POST {MCP_URL}/tools/{tool_name}` 调用,JSON kwargs 作为请求体,JSON envelope 作为响应。

### 为什么不直接用 LangChain `to_langchain_tool`?
历史 bug(详见 `agents/weather.py:128-131` 注释):LangChain 的 `to_langchain_tool` 把多参数工具折叠成 `{"input": ...}` 形式,FastMCP 拒绝(报 `unexpected keyword argument 'input'`)。三个 agent 因此各自手写了 30+ 行 `requests.post` + `StructuredTool.args_schema` 桥接代码。

### 当前 wire 协议契约
```
POST {MCP_URL}/tools/{tool_name}
Content-Type: application/json
Body: { "city": "北京", "start_date": "2026-08-07", ...kwargs }

Response:
{
  "content": [{"type": "text", "text": "{\"status\": \"success\", \"data\": [...]}}"]
}
```

工具结果用 envelope 字符串:`{"status": "success|no_data|error|missing_params", ...}`

## 决策

**保留 FastMCP wire 协议契约,不做协议层修改**。

具体含义:
1. **不修改** `POST /tools/{name}` 路由
2. **不修改** JSON kwargs 请求体
3. **不修改** `{"status": ...}` envelope 格式
4. **不修改** 端口分配(8001/8002/8003)
5. **现有 3 个 MCP server 直接作为插件注册**,不重写工具实现

### 唯一允许的改动(推迟到 Phase 6)
**Pydantic 边界验证**:在 MCP server 接收请求时,用 Pydantic `BaseModel` 替代当前的"Python type annotation + 手工 default"模式,返回结构化 422 错误而非 500。但**请求/响应 envelope 形状不变**。

## 后果

### 正面
1. **零回归风险**:Phase 1-5 重构过程中,3 个后端不挂
2. **零迁移成本**:现有 3 个 MCP server 字节级保留,作为插件内嵌即可
3. **向后兼容**:任何外部依赖 MCP 协议的下游(如未来其他团队的服务)继续工作
4. **契约测试**:可以写 wire-protocol 测试锁定请求/响应形状

### 负面
1. **协议僵化**:未来要做协议级优化(如 streaming、批调用)代价高
2. **手工桥接代码**:3 个 agent 的 `requests.post` 桥接仍然需要(Phase 1 抽到 `tools_gateway.py`,但协议不变)

### 中性
1. **Pydantic 边界验证延后**:Phase 6 才加,Phase 1-5 沿用 Python annotation

## 权衡

| 备选方案 | 取舍 |
|---------|------|
| **升级到官方 MCP SDK `langchain_mcp_adapters`** | ❌ 拒绝 — 当前被注释掉的 import(`agents/ticket.py:111-112,125-126`)显示官方 SDK 仍未修复多参数 bug;升级会破坏现有 3 个后端 |
| **换成 gRPC / 自定义二进制协议** | ❌ 拒绝 — 没有性能压力;JSON over HTTP 足够;换协议=重写 3 个 server |
| **MCP 工具改成进程内调用**(不再走 HTTP) | ⚠️ 部分采用 — Phase 3 的 PluginManager 同时支持 `endpoint=None`(进程内)和 `endpoint="http://..."`(远程);现有 server 仍走 HTTP,新插件可内嵌 |
| **重写为 Pydantic-first 协议** | ⏸ 推迟到 Phase 6 — 边界验证可以加,但 envelope 形状不变 |

## 验证

- **Phase 1 验收**:wire-protocol 契约测试通过(`test_mcp_wire_protocol.py`)
  - POST `/tools/query_weather` with `{city, start_date, end_date}` → 返回 `{"status": "success", "data": [...]}`
  - POST `/tools/query_concert` 缺参数 → 返回 `{"status": "missing_params", ...}`
- **Phase 6 验收**:故意传错类型(如 `city=123`) → 返回 422 错误而非 500

## 参考引用

- 桥接代码:`CorpAI/agents/weather.py:133-152`
- MCP server 模板:`CorpAI/tools/weather.py:252-340`
- Envelope 格式:`CorpAI/tools/weather.py:174-180`
