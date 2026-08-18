# CLAUDE.md — Claude Code 项目指南

> 这个文件会被 Claude Code **自动加载**,你不需要 `@CLAUDE.md` 或类似指令。

## 这是什么项目

**CorpAI** 是一个企业内部 AI Copilot 平台(FastAPI 后端 + 插件架构)。3 个内置插件:**hr_assistant**(HR 操作)、**sre_copilot**(SRE 故障响应)、**knowledge**(Milvus RAG)。

详细架构看 `ARCHITECTURE.md`,分层约定看 `LAYERS.md`。

## 必须知道的硬约束

1. **分层编号**:顶层 `_0_CorpAI/` `_1_plugins/` `_2_scripts/` `_3_sql/` `_4_tests/` `_5_static/`(项目根);包内 `_0_CorpAI/_0_api/` `_1_core/` `_2_platform/` `_3_utils/`。**别动编号**。详见 `LAYERS.md`。

2. **Composition Root 唯一性**:`_0_CorpAI/_2_platform/wiring.py` 是**唯一**允许 `import langchain` / `import python_a2a` / `import mysql.connector` 的地方。其他文件保持纯(只依赖 stdlib + 平台内部模块),否则 Composition Root 模式被破坏,后续换 LLM/DB 框架的难度指数级上升。

3. **Plugin manifest endpoint 必须对得上实际 MCP server 端口**:
   - `hr_assistant` 所有 mcp_tool manifest 全指向 `:8001`(1 server 跑 9 tools)
   - `sre_copilot` 5 个端口:8020/8021/8022/8027/8028
   - `knowledge` 全指向 `:8030`
   - 改 manifest 时必须同步改 `mcp_servers.py` 的 `SERVER_PORTS`

4. **MCP 协议是 Anthropic 官方 spec**(fastmcp 3.x + MCP SDK 2.x,JSON-RPC 2.0 over StreamableHTTP),**别再写自定义 HTTP 协议**。

5. **Plugin 必须有 `[build-system]` 用 hatchling** + `[tool.hatch.build.targets.wheel] packages = ["src/<name>"]` 才能正常打包;distribution 名 `corpai-plugin-<name>`,**不能下划线开头**(PEP 503)。

## 跑测试

```bash
# 平台测试(必须先 make install-plugins)
make install-plugins
make test-unit                       # 157 passed

# 单跑一类
make test-plugins                    # hr + sre + knowledge 一起跑(67 passed,无 ImportPathMismatchError)
.venv/Scripts/python.exe -m pytest _4_tests/observability -v
.venv/Scripts/python.exe -m pytest _4_tests/auth -v
.venv/Scripts/python.exe -m pytest _4_tests/platform -v
```

**集成测试需要真 MySQL/Milvus**(`-m integration`),本地默认 skip。要跑前设 `.env` 的 `MYSQL_*` / `MILVUS_*`。

## 关键路径速查

| 任务 | 路径 |
|---|---|
| 加新 API 端点 | `_0_CorpAI/_0_api/` |
| 加新 LLM agent / 编排逻辑 | `_0_CorpAI/_2_platform/orchestrator/` |
| 改记忆模型 | `_0_CorpAI/_1_core/memory.py` |
| 改数据库 schema | `_3_sql/` + 写 `_2_scripts/migrate_*.py` |
| 加新 plugin | `_1_plugins/<name>/`,参照 hr_assistant 模板 |
| 加新 MCP tool | `_1_plugins/<name>/src/<name>/mcp_servers.py` 的 `FastMCP` 实例 + `@server.tool()` |
| 加新跨 plugin bridge | `_1_plugins/<name>/src/<name>/bridges.py` 用 `fastmcp.Client` |
| 改 plugin 端口 | `mcp_servers.py` 的 `SERVER_PORTS` + `mcp_main.py` + `plugin.py` 的 manifest endpoint + `Makefile` |
| 改 LLM 模型配置 | `.env` 的 `MODEL` / `BASE_URL` / `API_KEY` |

## 不能动的禁区

- **`_0_CorpAI/_1_core/` 不准 import 框架**(FastAPI / LangChain / mysql.connector)
- **`_0_CorpAI/_3_utils/` 只放小工具**(dotenv、format),不放业务逻辑
- **plugin 的 `_1_plugins/<name>/src/<name>/__init__.py` 不要立刻 import plugin 模块** —— 避免循环 import(本地插件可能没装)
- **不要删 `.pytest_cache/` 或 `__pycache__/`** —— pytest 用它们找 module,删了会触发 ImportPathMismatchError

## commit 规范

参考 `CONTRIBUTING.md` 第 "Commit 规范" 一节。简版:

```
type(scope): 简短描述

- 详细点 1
- 详细点 2

关联 issue / ADR(可选)
```

`type` ∈ `feat` / `fix` / `refactor` / `docs` / `test` / `chore`。
**不要写**"改了一下"、"修复 bug"、"更新代码"这种没意义的描述。

## 加新 plugin checklist

1. `_1_plugins/<name>/` 拷一个 hr_assistant 改名字 + pyproject.toml + register 逻辑
2. pyproject.toml 里 `[tool.pytest.ini_options]` 配 `pythonpath` + `testpaths = ["<name>_tests"]`(避开同名 module 冲突)
3. `src/<name>/plugin.py` 写 manifest + register
4. `src/<name>/mcp_servers.py` + `mcp_main.py` + `mcp_one.py` 拷 hr_assistant 改
5. `make install-plugins` 装上
6. `make test-plugins` 验证
7. README.md 的 "插件一览" 表格加一行

## 加新 MCP tool checklist

1. `mcp_servers.py` 里建 `FastMCP` 实例(如需新端口)或在已有实例上 `@server.tool()`
2. tool 函数签名要有 type hints + docstring(scheme 自动推导)
3. RBAC scope 检查放在 tool 函数**内部**(`_check_sre_read` 模式),不在 manifest 端点
4. 配 `.env.example` 需要的 env vars
5. plugin.py 加 manifest 声明 `mcp_tool_name=<新 tool 名>`
6. `make run-mcp-<plugin>` 验证 `curl -X POST http://127.0.0.1:<port>/mcp` 返回 JSON-RPC 2.0

## 常见错误

| 错 | 原因 | 修 |
|---|---|---|
| `ModuleNotFoundError: No module named 'hr_assistant'` | plugin 没装 | `make install-plugins` |
| `ModuleNotFoundError: No module named '_0_CorpAI'` | 测试 sys.path 没注入 | 检查 plugin pyproject.toml 的 `pythonpath` |
| `ImportPathMismatchError` | 两个 plugin 同名 conftest.py 或 test_plugin.py | 别用 `tests/`,用 `<plugin>_tests/` |
| `port already in use` | 上次的服务没干净关 | `ps -ef \| grep python \| grep -v grep \| awk '{print $2}' \| xargs kill` |
| `401 Unauthorized` | JWT 没传或 `AUTH_JWT_SECRET` 不对 | `AUTH_JWT_SECRET=dev-secret make test-unit` |

## 改完代码后必跑

```bash
make test-unit && make test-plugins    # 224 passed 是基线
```

改 doc / yml / Makefile 不需要跑测试,但 commit 前**必须 grep 一遍**:

- `grep -rn "CorpAI/api\|CorpAI/core\|CorpAI/platform\|CorpAI/utils" --include='*.md' .` 应该 0 命中(老路径)
- `grep -rn "python-a2a.*FastMCP"` 应该 0 命中(老描述)
- `grep -rn "private.*HTTP\|POST.*mcp/tools/" --include='*.py'` 应该 0 命中(老私有 MCP 协议)

## 风格

- **测试**:unittest 风格(class TestX),不要 pytest function 风格混用
- **error envelope**:DB / 外部 API 失败用 `_err_envelope(action, kind, message, **extra)` 统一 JSON 错误,绝不 silent-fail
- **logging**:用 `_0_CorpAI.logging.logger`,不要 print
- **test fixtures**:plugin 测试用 `pyproject.toml` 的 `pythonpath` + `testpaths`,别再加 `tests/conftest.py`(会撞)
- **跨 plugin bridge**:`fastmcp.Client`,**别用 requests 自己调**