# CONTRIBUTING.md — 开发指南

## 目录

1. [开发环境搭建](#1-开发环境搭建)
2. [跑测试](#2-跑测试)
3. [加新 Plugin](#3-加新-plugin)
4. [加新 MCP Tool](#4-加新-mcp-tool)
5. [加新 LLM Agent](#5-加新-llm-agent)
6. [改 RBAC Scope](#6-改-rbac-scope)
7. [改数据库 Schema](#7-改数据库-schema)
8. [Commit 规范](#8-commit-规范)
9. [Code Review 检查表](#9-code-review-检查表)

---

## 1. 开发环境搭建

```bash
# 装 uv(如果还没有)
# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# 装依赖
cd CorpAI
uv sync --group dev                  # 平台 + dev 测试
make install-plugins                # 装 3 个 plugin(editable)

# 配环境变量
cp .env.example .env
# 改 .env 填 API_KEY / AUTH_JWT_SECRET / MYSQL_PASSWORD

# 启依赖服务(可选,集成测试需要)
docker compose -f corpai-milvus.yml up -d

# 跑平台
make run-api                         # http://localhost:8080
```

**目录约定**(完整分层见 `LAYERS.md`):
- 项目根 `_0_CorpAI/` `_1_plugins/` `_2_scripts/` `_3_sql/` `_4_tests/` `_5_static/`
- 包内 `_0_api/` `_1_core/` `_2_platform/` `_3_utils/`

---

## 2. 跑测试

```bash
# 必须先装 plugin
make install-plugins

# 全套单元测试(224 passed 是基线)
make test-unit
make test-plugins

# 单跑一类
.venv/Scripts/python.exe -m pytest _4_tests/observability -v
.venv/Scripts/python.exe -m pytest _4_tests/auth -v
.venv/Scripts/python.exe -m pytest _4_tests/platform -v

# 集成测试(需 MySQL/Milvus)
.venv/Scripts/python.exe -m pytest -m integration
```

**集成测试**默认 skip(`-m "not integration"` 默认开启)。要跑前确保 `.env` 里的 `MYSQL_*` 和 `MILVUS_*` 可用。

---

## 3. 加新 Plugin

模板:**完整拷一个 hr_assistant**,改以下位置:

```bash
# 1. 拷结构
cp -r _1_plugins/hr_assistant _1_plugins/<new_name>
# 改内部所有 'hr_assistant' → '<new_name>'(大小写敏感)

# 2. pyproject.toml
# - name = "corpai-plugin-<new_name>"
# - [project.entry-points."platform.plugins"] <new_name> = "<new_name>.plugin:register"
# - [tool.hatch.build.targets.wheel] packages = ["src/<new_name>"]
# - [tool.pytest.ini_options] pythonpath = ["../..", "../../_0_CorpAI"] + testpaths = ["<new_name>_tests"]
#   ⚠️ 测试目录名必须 plugin-specific,不要用 tests/(其他 plugin 也会用 → ImportPathMismatchError)

# 3. src/<new_name>/plugin.py
# 写 AGENT_MANIFEST / TOOL 清单 + register(registry)

# 4. src/<new_name>/mcp_servers.py + mcp_main.py + mcp_one.py
# 拷 hr_assistant 改 server 名 + 端口

# 5. 安装 + 测试
make install-plugins
make test-plugins
make run-mcp-<new_name>             # 验证 MCP 启动
```

---

## 4. 加新 MCP Tool

在已有 plugin 里加,不需要新建 plugin:

```python
# _1_plugins/<plugin>/src/<plugin>/mcp_servers.py

# 在已有 FastMCP 实例上加
@hr_server.tool()
def new_tool(authorization: str, param1: str) -> str:
    """简短描述,会自动变成 tool description。
    
    Args:
        authorization: Bearer token(传 user JWT)
        param1: 参数说明
    """
    # 1. RBAC 校验(强制)
    from _0_CorpAI._2_platform.auth.tokens import jwt_decode
    from _0_CorpAI._2_platform.auth.dependencies import get_jwt_secret
    from _0_CorpAI._2_platform.auth.scopes import has_scope
    try:
        claims = jwt_decode(authorization[len("Bearer "):], get_jwt_secret())
        if not has_scope("hr:write", claims.get("scopes", [])):
            raise PermissionError("need hr:write")
    except Exception as e:
        raise PermissionError(f"auth failed: {e}")
    
    # 2. 业务逻辑
    from hr_assistant import actions as a
    return a.new_tool_impl(authorization=authorization, param1=param1)
```

```python
# _1_plugins/<plugin>/src/<plugin>/plugin.py
NEW_TOOL = PluginManifest(
    name="<plugin>_new_tool_mcp",
    version="3.2.0",
    description="新工具:干什么的",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8001",  # 跟实际 mcp_server.SERVER_PORTS 对齐
    mcp_tool_name="new_tool",
    permissions=["hr:write"],
    tags=["..."],
)

def register(registry):
    for m in (AGENT_MANIFEST, ..., NEW_TOOL):
        registry.register(m)
```

`make run-mcp-<plugin>` 验证:

```bash
curl -X POST http://127.0.0.1:8001/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}'
```

应返回带 `serverInfo.name="hr_assistant"` 的 JSON-RPC 2.0 响应。

---

## 5. 加新 LLM Agent

LLM agent 通过 A2A 暴露。在 plugin 的 `server.py` 里:

```python
# _1_plugins/<plugin>/src/<plugin>/server.py

class NewAgent(A2AServer):
    def __init__(self, llm=None):
        card = AgentCard(
            name="new_agent",
            description="新 agent 干什么的",
            url="http://localhost:5011",
            version="1.0.0",
            skills=[AgentSkill(id="new_skill", name="新技能", description="...")],
        )
        super().__init__(agent_card=card)
        self.llm = llm or ChatOpenAI(model=Config().model_name, ...)
    
    def handle_task(self, task: Task) -> Task:
        # 提取用户消息
        text = _extract_text(task)
        # 调 LLM / MCP tool
        response = self.llm.invoke(text)
        return Task(
            id=task.id,
            status=TaskStatus(state=TaskState.COMPLETED, message=task.message),
            artifacts=[{"parts": [{"type": "text", "text": response.content}]}],
        )

def main():
    server = NewAgent()
    run_server(server, host="0.0.0.0", port=5011)
```

加 entry.py 启动入口,加 plugin.py manifest,加 Makefile target。

---

## 6. 改 RBAC Scope

**scope 是字符串**(`hr:read`, `sre:approve`),三层定义:

| 位置 | 作用 |
|---|---|
| `auth/scopes.py` 的 `Role` enum / `ROLE_DEFAULT_SCOPES` | 默认 scope(角色 → scope 列表) |
| PluginManifest.permissions | 这个 plugin 需要哪些 scope |
| `_check_scope(authorization, "hr:write")` 在 tool/action 函数内 | 运行时校验 |

**改 scope 三件套**(任一加新 scope):
1. `auth/scopes.py`:加进 `ROLE_DEFAULT_SCOPES`
2. plugin.py:加进对应 manifest 的 `permissions`
3. tool/action 函数:加 `_check_scope(authorization, "<new_scope>")`

---

## 7. 改数据库 Schema

```bash
# 1. 在 _3_sql/ 加新的 DDL 文件(_3_sql/migrate_<phase>.sql)
# 2. 写 _2_scripts/migrate_<phase>.py 跑 DDL
# 3. 在 Makefile 加 migrate-<phase> target
# 4. 更新 _3_sql/create_all_tables.sql(全量)
```

**绝不要**直接改生产 DB schema。永远走 migrate 脚本 + 版本号。

---

## 8. Commit 规范

格式:

```
type(scope): 简短描述

- 详细点 1
- 详细点 2

关联 issue / ADR(可选)
```

**type**:
- `feat` — 新功能
- `fix` — 修 bug
- `refactor` — 重构(无功能变化)
- `docs` — 文档
- `test` — 加/改测试
- `chore` — 杂事(依赖更新、rename、build-system)

**scope**(可选):
- `orchestrator` / `auth` / `memory` / `observability`
- `hr_assistant` / `sre_copilot` / `knowledge`
- `mcp` / `a2a` / `bridge`
- `plugin` / `platform`

**示例**:
```
refactor(layer): 顶层目录加 _0-_5 编号前缀

- _0_CorpAI/ 平台核心包
- _1_plugins/ 3 个业务能力包
- _2_scripts/ 运维脚本
- _3_sql/ DDL
- _4_tests/ 测试
- _5_static/ Web 静态资源
- 新建 LAYERS.md 固化编号约定
- 174 处 import 路径已替换为 _0_CorpAI._0_api 等

破 plugin 端点统一到 :8001(单端口 9 tools)
```

**避免**:
- ❌ "改了一下"、"修复 bug"、"更新代码"
- ❌ 一句话超长 wrap(用 body 拆行)
- ❌ 一次 commit 改 N 个不相关的东西(拆 commit)

---

## 9. Code Review 检查表

提交前自查:

- [ ] **测试通过**:`make test-unit && make test-plugins`(224 passed 基线)
- [ ] **新代码有测试**:`pytest` 单元测试覆盖
- [ ] **错误不 silent**:外部 API / DB 失败用 `_err_envelope` 或 raise
- [ ] **RBAC 校验**:tool 函数入口有 `_check_scope`
- [ ] **文档同步**:README / plugin README / CLAUDE.md 跟新代码对齐
- [ ] **不破 Composition Root**:`_1_core/` 不 import 框架,`_2_platform/wiring.py` 是唯一引外部 SDK 的地方
- [ ] **plugin manifest endpoint 对得上实际 MCP server 端口**
- [ ] **MCP tool 用 `@server.tool()` decorator,别写自定义 HTTP**
- [ ] **没有遗留 `print()` 调试代码**:用 `logger.debug()`
- [ ] **没有遗留 `.egg-info/` 目录**(git mv 后会有,要清)
- [ ] **grep 旧路径/旧协议**:
  ```bash
  grep -rn "CorpAI/api\|CorpAI/core\|CorpAI/platform\|CorpAI/utils" --include='*.md' .
  grep -rn "private.*HTTP\|POST.*mcp/tools/" --include='*.py' .
  ```
  应该都 0 命中

---

## 调试小贴士

```bash
# 哪个进程占了端口?
netstat -ano | grep :5010

# 看 MCP server 实时日志
make run-mcp-sre-copilot              # 子进程日志写到 /tmp/mcp-*.log

# 手动测 MCP endpoint
curl -X POST http://127.0.0.1:8020/mcp -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",...}'

# 看 JWT 是否过期
python -c "from _0_CorpAI._2_platform.auth.tokens import jwt_decode; print(jwt_decode('...'))"

# 重置 Milvus(本地 dev)
docker compose -f corpai-milvus.yml down -v && docker compose -f corpai-milvus.yml up -d
```