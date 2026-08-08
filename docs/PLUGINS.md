# CorpAI Plugin 开发指南

Phase 5 落地后,所有业务都通过 plugin 实现。本文档解释如何编写/发布/调试自定义 plugin。

## 1. 概述

- 每个 plugin 是独立 Python 包,根目录在 `plugins/<your-plugin>/`
- 通过 **entry_points** 自动加载(无需手动注册)
- 必须声明至少 1 个 **RBAC scope**(`permissions=[]` 在 `register()` 时抛 ValueError)
- 平台 `platform/plugin_manager.py` 用 `importlib.metadata.entry_points(group="platform.plugins")` 扫描
- 加载失败 plugin 自动 warning 不挂,其他 plugin 照常工作(软启动)

## 2. 最小可行 plugin(5 步)

### Step 1: 创建目录
```bash
mkdir -p plugins/my_plugin/src/my_plugin
```

### Step 2: `pyproject.toml`
```toml
[project]
name = "corpai-plugin-my-plugin"
version = "0.1.0"
description = "My new plugin"
requires-python = ">=3.11"
dependencies = []   # 平台已装的 langchain / fastapi / uvicorn 等不需重复声明

[project.entry-points."platform.plugins"]
my_plugin = "my_plugin.plugin:register"
```

### Step 3: `src/my_plugin/__init__.py`
```python
from my_plugin.plugin import register
__all__ = ["register"]
```

### Step 4: `src/my_plugin/plugin.py`
```python
from CorpAI.platform.plugin_manager import PluginManifest, PluginRegistry

MANIFEST = PluginManifest(
    name="my_plugin",
    version="0.1.0",
    description="My new plugin",
    plugin_type="llm_agent",  # 或 "mcp_tool"
    endpoint="http://localhost:5050",
    llm_prompt="You are a helpful assistant.",  # 仅 llm_agent 必填
    summary_prompt="summarize",  # 可选:在 plugin.prompts 找同名函数
    required_intents=["my_intent"],
    permissions=["my_plugin:read"],
    tags=["my-domain"],
)

def register(registry: PluginRegistry) -> None:
    registry.register(MANIFEST)
```

### Step 5: 安装 + 验证
```bash
cd D:\develop\PycharmProjects\CorpAI
uv pip install -e plugins/my_plugin
.venv\Scripts\python.exe -c "
from CorpAI.platform.plugin_manager import discover_all
r = discover_all()
print([m.name for m in r.list_all()])
# 期望:['hr_assistant', 'devops_copilot', 'faq', 'my_plugin']
"
```

## 3. PluginManifest 字段

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| `name` | str | ✓ | 唯一标识,1-64 字符 |
| `version` | str | ✓ | semver,正则 `^\d+\.\d+\.\d+$` |
| `description` | str | ✓ | 1-512 字符 |
| `plugin_type` | `Literal["mcp_tool", "llm_agent"]` | ✓ | 形态 |
| `endpoint` | str \| None | mcp_tool 必填 | `http://host:port` |
| `mcp_tool_name` | str \| None | - | MCP 工具名,UI 展示 |
| `llm_prompt` | str \| None | llm_agent 必填 | 系统 prompt 模板 |
| `summary_prompt` | str \| None | - | 在 plugin.prompts 找同名函数 |
| `required_intents` | list[str] | - | 路由匹配 |
| `permissions` | list[str] | ✓(非空) | RBAC scopes |
| `tags` | list[str] | - | 领域标签 |
| `structured_tools` | list[dict] | - | LangChain 工具定义(Phase 6 规约化) |

## 4. register() 模式

### 单 manifest
```python
def register(registry: PluginRegistry) -> None:
    registry.register(MANIFEST)
```

### 多 manifest(同一 plugin 同时提供 A2A + MCP)
```python
def register(registry: PluginRegistry) -> None:
    for m in (AGENT_MANIFEST, MCP_TOOL_1, MCP_TOOL_2):
        registry.register(m)
```

## 5. RBAC scope 强制机制(Phase 5)

- `permissions=[]` → `register()` 抛 `ValueError`
- `/api/chat` 接受可选 `Authorization: Bearer <token>`(Phase 5 加)
- 解析 token → 取 `claims["scopes"]` → `wiring.set_user_scopes(scopes)`
- `wiring._call_a2a_and_summarize` 调 `has_scope(manifest.permissions[0], _get_current_user_scopes())`
- 失败 → `raise PermissionError` → `OrchestratorService.chat` 顶层 try/except 捕获 → 返 error_message

**RBAC 设计模式**:
| 角色 | 期望 scope | 用例 |
|------|------------|------|
| super_admin | `["*"]` | 可调所有 plugin |
| admin | `["hr:read", "devops:read", "faq:read"]` | 跨 plugin 读 |
| employee | `["chat:write"]` | 普通聊天(无 plugin 直接权限) |
| agent_author | `["chat:write", "plugin:write"]` | 注册/管理 plugin |

**devops_copilot 双 scope 示范**:`permissions: ["devops:read", "devops:write"]` — 同一 plugin 多个 scope。`restart_pod` 单独要 `devops:write`(由 plugin 内部 `has_scope` 校验)。

## 6. summary_prompt dispatch 机制

`manifest.summary_prompt = "summarize_x"` 时,wiring 通过反射从 `plugin.prompts` 模块查同名函数并调,得到 `ChatPromptTemplate`。

### 范例:`hr_assistant` plugin
```python
# plugins/hr_assistant/src/hr_assistant/prompts.py
from langchain_core.prompts import ChatPromptTemplate

def summarize_benefits() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_template("...")
```

`AGENT_MANIFEST.summary_prompt = "summarize_benefits"` 即可。`wiring._resolve_summary_prompt`:
```python
mod = plugin_manager._plugin_modules[manifest.name]  # "hr_assistant"
prompts_pkg = getattr(mod, "prompts", None)
fn = getattr(prompts_pkg, "summarize_benefits", None)
return fn() if fn else None
```

**找不到 → fallback 返 `agent_result`**(Phase 4 行为)。

## 7. 测试 plugin

每个 plugin 自带 `tests/` 目录,模式:
```python
# plugins/my_plugin/tests/test_plugin.py
import sys
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT))  # 让 `import CorpAI` 找到

import unittest
from CorpAI.platform.plugin_manager import PluginRegistry
from my_plugin.plugin import register, MANIFEST

class TestRegister(unittest.TestCase):
    def test_register(self):
        r = PluginRegistry()
        register(r)
        self.assertEqual(r.get("my_plugin").name, "my_plugin")
```

**conftest.py** 必须设项目根:
```python
import sys
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
```

跑:`cd plugins/my_plugin && uv run pytest`

## 8. e2e 流程

1. 启 A2A server:`cd plugins/my_plugin && uv run python -m my_plugin.entry`
2. curl 测试:`curl -X POST http://localhost:5050 -d '{...}'`
3. 启 FastAPI:`make run-api`
4. chat 测试:`curl -X POST http://127.0.0.1:8080/api/chat -H "Authorization: Bearer $TOKEN" -d '{"message":"..."}'`

## 9. FAQ

### 9.1 manifest 字段不识别?
Pydantic v2 `model_config = ConfigDict(extra="forbid")` — 任何拼错的字段会立即 raise。检查 `name` 长度、`version` semver 格式、`permissions` 非空。

### 9.2 entry_points 缓存?
`uv pip install -e` 后需重启 Python 进程(entry_points 元数据在 import 时读)。`uv pip cache purge` 清缓存。

### 9.3 plugin 私有依赖隔离?
- **Phase 5 决策**:0 新 platform dep;plugin 可在 `pyproject.toml:dependencies` 声明自己私有依赖,platform 不受影响。
- 不允许修改平台代码来适配 plugin;反过来平台升级也不能改 plugin。

### 9.4 与 plugins/customer_service_demo 的关系?
`customer_service_demo` 是 Phase 3 占位脚手架 — Phase 7 已删,改为 `tests/_fixtures/customer_service_scaffold/` 仅作 CI 验证 entry_points 发现。

### 9.5 性能 / trace / 监控?
- `manifest.name` 落到 `corpai_app_info` 的 `version=phase4` 元数据(Phase 4)
- 每次 `wiring._call_a2a_and_summarize` 自动写 `call_records` 一行(trace_id / span_id / duration_ms)
- `_call_a2a_and_summarize` 自动 inc `A2A_CALL_TOTAL` Counter
- summary LLM 自动 inc `LLM_CALL_TOTAL` + 计时

## 10. 已交付的 3 个真 plugin

| Plugin | A2A 端口 | MCP 端口 | 业务 | RBAC scopes |
|--------|----------|----------|------|------------|
| `hr_assistant` | 5010 | 8010, 8011 | 员工福利(B001-B008) + HR 政策 KB(P001-P010) | `hr:read, hr:write` |
| `devops_copilot` | 5020 | 8020, 8021 | 工单(INC-001~008) + On-call(4 团队) + Pod 重启(RBAC showcase) | `devops:read, devops:write` |
| `faq` | 5030 | 8030 | 企业 KB RAG(FAQ001~012,VPN/远程办公/差旅等) | `faq:read` |

## 11. 引用

- `CorpAI/platform/plugin_manager.py` — 公开 API
- `CorpAI/platform/wiring.py` — `_resolve_summary_prompt` / `set_user_scopes`
- `CorpAI/api/app.py` — `/api/chat` 可选 JWT
- `CorpAI/api/admin_router.py` — `/admin/api/plugins` 展示
- `docs/adr/0003-plugin-registration.md` — entry_points 设计
- `docs/REFACTOR_PLAN.md:200-207` — 4 个示范插件映射表
