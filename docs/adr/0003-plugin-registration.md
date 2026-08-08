# ADR-003: 插件注册机制 — Python entry_points

## 状态
**Accepted → Implemented (Phase 3)** — 2026-08-06

Phase 3 实施位置:
- `CorpAI/platform/plugin_manager.py` (Pydantic v2 PluginManifest + PluginRegistry + discover_all)
- `CorpAI/api/admin_router.py` (GET /admin/api/plugins,POST .../enable)
- `plugins/customer_service_demo/` (脚手架 entry_points demo)

## 背景

平台需要支持 N 个业务 Agent + N×M 个 MCP 工具的运行时注册。当前 CorpAI 是硬编码的:3 个 A2A Agent 在 `core/chat.py:210-214`(`agent_urls` 字典),3 个 MCP server 各自独立进程。

### 现有注册方式
- **Agent**:`chat.py:209-213` 硬编码 `agent_urls = {"WeatherQueryAssistant": "http://127.0.0.1:5005", ...}`
- **意图路由**:`config.py:63-73` 硬编码 `intent` 字典,key 是 intent 名,value 是 Agent 名
- **工具**:每个 MCP server 独立进程,端口硬编码在 `tools/{weather,ticket,trip}.py`

### 新增业务的工作量
当前模式:编辑 `config.py` + `core/prompts.py` + `agents/<new>.py` + `tools/<new>.py` + 重启 2 个新进程 = **半天工作量 + 容易遗漏导致 demo 挂**

## 决策

使用 **Python entry_points** 作为插件注册机制,具体形式:

### 1. 插件作者声明(在插件 `pyproject.toml`)
```toml
[project.entry-points."platform.plugins"]
customer_service = "smartvoy_customer_service.plugin:register"
hr_assistant = "smartvoy_hr_assistant.plugin:register"
devops_copilot = "smartvoy_devops_copilot.plugin:register"
```

### 2. 插件作者实现 `register()` 函数
```python
# plugins/customer_service/plugin.py
from platform.plugin_manager import PluginRegistry

def register(registry: PluginRegistry) -> None:
    registry.register_agent(AgentManifest(
        name="customer_service",
        version="1.0.0",
        description="企业客服助手,处理工单查询、出差订票、团队外出",
        plugin_type="llm_agent",
        llm_prompt=CUSTOMER_SERVICE_PROMPT,
        structured_tools=[query_ticket, order_ticket, query_weather, ...],
        required_intents=["weather", "train", "flight", "concert", "order"],
        permissions=["cs:read", "cs:write"],
        tags=["customer-service", "travel"],
    ))
```

### 3. 平台启动时自动发现
```python
# platform/plugin_manager.py
import importlib.metadata as md

def discover_all() -> PluginRegistry:
    registry = PluginRegistry()
    eps = md.entry_points(group="platform.plugins")
    for ep in eps:
        register_fn = ep.load()  # load "smartvoy_customer_service.plugin:register"
        register_fn(registry)
    return registry
```

## 后果

### 正面
1. **标准 Python 实践**:entry_points 是 PEP 621 / setuptools 官方机制
2. **零配置发现**:`uv sync` 后立即可见,无需扫描文件系统
3. **类型安全**:register 函数签名明确,IDE 可补全
4. **独立发布**:插件可以单独打包到 PyPI,平台只装需要的插件
5. **零修改平台核心**:加业务 = 加 entry_point,**平台代码不动**

### 负面
1. **依赖 uv/pip install**:必须 `uv sync` 或 `pip install -e .` 才能发现新插件,纯文件添加不会自动加载
2. **entry_points 缓存**:Python 会缓存 entry_points 元数据,加新插件后可能需要重启
3. **调试稍麻烦**:插件加载失败时错误信息指向 `pyproject.toml` 而非代码

### 中性
1. **插件版本管理**:依赖标准 `pip install plugin==1.2.3`,无平台内特殊机制
2. **插件依赖隔离**:插件可以带自己的依赖(uv 自动管理)

## 权衡

| 备选方案 | 取舍 |
|---------|------|
| **文件系统扫描 `plugins/*/`** | ❌ 拒绝 — 难以处理依赖、版本、隔离;且要求 `__init__.py` 标准路径 |
| **`importlib.import_module` 反射** | ❌ 拒绝 — 需要约定路径,易出错,无版本管理 |
| **YAML/TOML 配置文件** | ❌ 拒绝 — 配置和代码分离,插件逻辑复杂时配置膨胀 |
| **数据库存储 + REST 注册** | ⚠️ 部分采用 — Phase 3 的管理后台允许 admin 通过 UI 注册/反注册插件,但底层仍用 entry_points(管理后台只是 toggle 开关) |
| **`pluggy`(pytest 用的 hookspec)** | ⚠️ 备选 — 备选方案,如有 hookspec 需求可换 |

## Plugin Manifest 完整 schema

```python
class PluginManifest(BaseModel):
    name: str                           # 唯一标识,如 "customer_service"
    version: str                        # semver, 如 "1.0.0"
    description: str                    # 一句话描述(展示给 LLM + UI)
    plugin_type: Literal["mcp_tool", "llm_agent"]
    
    # ─── For mcp_tool ───
    endpoint: str | None = None         # "http://host:port" 远程;None = 进程内
    mcp_tool_name: str | None = None    # e.g. "query_weather"
    
    # ─── For llm_agent ───
    llm_prompt: str | None = None       # 系统 prompt 模板
    structured_tools: list[ToolDef] = [] # 工具列表(Pydantic StructuredTool)
    
    # ─── Common ───
    required_intents: list[str] = []    # 该插件处理哪些意图
    input_schema: dict = {}             # 从 Pydantic 自动生成
    output_schema: dict = {}            # JSON schema
    permissions: list[str] = []         # RBAC scopes,如 ["cs:read"]
    tags: list[str] = []                # 域标签,如 ["customer-service"]
    agent_card: AgentCard | None = None # 兼容 python-a2a 的 AgentCard
```

## 验证

- **Phase 3 验收**:`uv sync` 后 `python -c "from platform.plugin_manager import discover_all; print(discover_all().list_names())"` 输出所有注册插件名
- **Phase 3 验收**:管理后台 `/admin/agents` 显示插件清单,与 entry_points 一致
- **Phase 5 验收**:4 个示范插件全部 entry_points 声明正确,启动后自动加载

## 参考引用

- 当前硬编码:`CorpAI/core/chat.py:209-213`(`agent_urls` 字典)
- 当前意图路由:`CorpAI/config.py:63-73`
- 插件目录结构(目标):`plugins/{customer_service,hr_assistant,devops_copilot,faq}/`
