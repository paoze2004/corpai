# CorpAI → Enterprise AI Copilot Platform 重构方案

> 本文件是 `C:\Users\NEWPAO\.claude\plans\validated-honking-valley.md` 的镜像(去除 Plan mode 退出执行部分)。
> 项目级概要记忆见根目录 `CLAUDE.md`;架构决策详细版见 `docs/adr/`。

---

## Context

**业务方向**:CorpAI 原是一个面向旅游场景的中文聊天助手,经过 12 周重构转型为**企业 AI Copilot 平台** —— 一个可插拔的多 Agent 中台,支持企业内部多业务接入(HR / 研发 / 知识库等)。

**工程标准**:对齐"企业工程项目"标准,需要 RBAC 权限、可观测性、CI/CD、管理后台四项能力。当前项目在以下方面严重不足:
- 无认证/无 CORS(`api/app.py:26` 裸 FastAPI,零信任边界)
- ~~`ChatService` 单文件 880 行 11 方法(`core/chat.py:185-1063`),零测试覆盖~~ → **Phase 1.7 已完成**:`core/chat.py` 已删除,编排迁到 `platform/orchestrator/service.py`(5 模块)+ `platform/wiring.py`(组合根),详见 ADR-0004
- 3 个 agent 各自手写 30+ 行相同的 HTTP 桥接(`agents/weather.py:133-152`、`agents/ticket.py:224-243`、`agents/trip.py:170-190`)避开 `to_langchain_tool` bug
- MySQL/Milvus/intent-mapping 硬编码(`config.py:45-99`)
- 全局单例 `ConversationMemory` 无 user_id 区分(`core/memory.py:99-105`)
- README 提到 `main.py` 不存在;3 个 stub 测试 import 错误模块

**保留**:LangChain + FastMCP + Milvus + A2A 技术栈;`ThinkBlockFilter`(`api/app.py:59-101`);SSE wire 格式;`uv run python -m <module>` 启动模式;MCP `POST /tools/{name}` 协议;Pydantic `StructuredTool` 模式;`[追问]` 协议。

---

## 目标架构

### 形态
- **1 个 Orchestrator**(替换 880 行 ChatService,拆分为 7 个 ≤300 行模块)
- **N 个可注册业务 Agent**(替换 3 个硬编码 agent)
- **N×M 个可注册 MCP 工具**(保留 FastMCP 协议,替换 3 个硬编码 server)
- **MemoryPool 6 层**(3 层现有 + 3 层新增)
- **RBAC 4 角色**(super_admin/admin/agent_author/employee)
- **Observability**(结构化日志 + trace_id + Prometheus 指标 + call_records 表)
- **2 个 UI**(用户聊天窗口沿用 + 新增管理后台)

### 三层多 Agent 结构

```
Orchestrator (唯一写死的核心,意图识别 + 任务规划 + 协同)
    ↓ 调度
业务 Agent (N 个,可注册,如:客服 Agent / HR Agent / 研发 Agent)
    ↓ 调用
工具 MCP (N×M 个,可注册,FastMCP 协议,对接真实系统)
```

**4 种协作模式**:
1. **路由式**:单意图 → 单 Agent(最简单)
2. **协作式**:多 Agent 并行处理(Orchestrator 协调)
3. **委派式**:Agent 调 Agent(子任务)
4. **监督式**:Orchestrator 监控降级(异常处理)

---

## 分阶段路线图

| Phase | 周 | 目标 | 关键产出 |
|-------|---|------|---------|
| **0** | 第 1 周 | 稳定基线(零行为变化) | 修 3 个 stub 测试、删 dead imports、修 README、写 9 个 ADR |
| **1** | 第 2-4 周 | ChatService 模块拆分(7 个 ≤300 行) | `orchestrator/{service,intent,planner,react_loop,streaming,tools_gateway,memory_gateway}.py` + 特性测试 |
| **2** | 第 5 周 | DB 集中化 + 记忆 per-user 化 | `platform/db.py:DatabasePool` + ALTER TABLE 加 user_id/session_id(默认 'legacy' 兼容) |
| **3** | 第 6-8 周 | Plugin Manager + RBAC + 管理后台 MVP | `platform/plugin_manager.py`(entry_points 发现)+ `platform/auth/` + `/admin/*` 5 个页面 |
| **4** | 第 9 周 | Observability + CI/CD | 结构化日志 + trace_id + `/metrics` + GitHub Actions + Dockerfile |
| **5** | 第 10-11 周 | 3 个真插件 + 文档(Phase 7 起 customer_service 已删) | hr_assistant / sre_copilot / faq |
| **6** | 第 12 周 | 硬化(剩余硬编码 → env + Pydantic at MCP 边界 + async 清理) | 全面 .env 化、输入验证、asyncio.run 反模式修复 |

**总计:12 周(1 个经验开发者,~525 LOC/周)**,约 6300 LOC 新增/重写

---

## 关键架构决策(ADR 摘要)

### ADR-001:保留 FastMCP wire 协议
- **不破坏** `POST /tools/{name}` + JSON kwargs + JSON envelope 返回
- 现有 3 个 MCP server 直接作为插件注册,无需重写
- **风险**:协议变更会让 3 个后端同时挂掉(Risk #2)

### ADR-002:Orchestrator 用 Python entry_points 发现插件

```toml
# 插件 pyproject.toml
[project.entry-points."platform.plugins"]
customer_service = "my_plugin:register"
```

**不用文件系统扫描**;**不用 importlib magic**

### ADR-003:Plugin 两种类型,统一 Manifest

```python
class PluginManifest(BaseModel):
    name: str
    version: str
    description: str
    plugin_type: Literal["mcp_tool", "llm_agent"]
    endpoint: str | None                    # mcp_tool: 远程 URL,None=进程内
    mcp_tool_name: str | None               # mcp_tool: 工具名
    llm_prompt: str | None                  # llm_agent: 系统 prompt
    structured_tools: list[ToolDef]         # llm_agent: 工具列表
    required_intents: list[str]             # 哪些意图由该 Agent 处理
    input_schema: dict
    output_schema: dict
    permissions: list[str]                  # RBAC scopes
    tags: list[str]
    agent_card: AgentCard | None
```

### ADR-004:ChatService → 7 模块拆分

```
platform/orchestrator/
├── service.py        (180)  OrchestratorService:唯一协调器,无 LLM 调用
├── intent.py         (220)  IntentRecognizer:JSON 抽取 + 容错
├── planner.py        (250)  TaskPlanner:_should_skip_planning + LLM plan
├── react_loop.py     (260)  ReActRunner:depends_on 分组 + asyncio.gather
├── streaming.py      (170)  StreamMux:ThinkBlockFilter + SSE 适配
├── tools_gateway.py  (220)  PluginManager + RBAC 强制
└── memory_gateway.py (180)  MemoryPool 封装,per-user scoping
```

**强制边界**:用 `import-linter` 配置在 `pyproject.toml` 防止跨模块引用

### ADR-005:RBAC 4 角色 + 多租户

- `auth_users(user_id, tenant_id, role, scopes CSV)` 新表
- 强制:argon2-cffi 哈希;**fail-closed**(DB 未配置时拒绝,绝不 fail-open)
- 强制:`audit_log` 写入**不能 silent-fail**(对比 `core/memory.py:214/246/296`)
- 强制:每个插件调用前 `require_scope`;每个 admin endpoint 二次校验

### ADR-006:MemoryPool 6 层(向后兼容迁移)

| 层 | 范围 | 新增 |
|---|------|------|
| 1. ShortTerm | per (user_id, session_id), limit 20 | 加 user_id/session_id |
| 2. UserProfile | per user_id | 加 user_id |
| 3. EntityHistory | per user_id, limit 50 | 加 user_id |
| 4. TaskContext | per (user_id, session_id), TTL 30min | **新增** 跨 Agent scratch |
| 5. CrossAgentContext | per (user_id, session_id, agent_id) | **新增** Agent 私有 scratch |
| 6. LongTerm | per user_id, 向量 | **新增** 反思抽取的事实 |

迁移 SQL:`ALTER TABLE x ADD COLUMN user_id VARCHAR(64) NOT NULL DEFAULT 'legacy'`

### ADR-007:不引入框架,管理后台保持 Vanilla JS

- 当前 `static/index.html` 485 行 vanilla SPA 证明团队能 ship
- 管理后台 MVP 5 页(agents/tools/users/logs/metrics)+ 列表/增/改/删
- **风险**:admin UI 容易 scope creep(Risk #4)
- 后备:复杂度超过 1500 LOC 时升级到 HTMX(无构建);超过 3000 LOC 时再考虑 React+Vite

### ADR-008:流式输出扩展到意图/规划阶段

- 当前 `chat_stream`(`core/chat.py:878`)只流最终响应
- 改造:intent JSON tokens + planning steps + agent 调用结果**全部流式**
- 增量:~150 LOC;收益:用户体验跃升,无新依赖

### ADR-009:不引入 LangGraph

- LangGraph 适合全新设计;ChatService 当前 ReAct 逻辑能保留
- 拆分模块后,代码量 -50% 已经足够;不引入学习成本
- 未来如果需要复杂状态机,再评估

---

## 关键文件清单

### Phase 0-1(必须先动,影响最大)

- **修改** `CorpAI/core/chat.py:185-1063`(880 行 → 拆分为 7 个模块)
- **修改** `CorpAI/core/memory.py`(加 user_id/session_id;改 silent-fail 为 logger.warning)
- **修改** `CorpAI/config.py`(MySQL/Milvus/intent-mapping 全 env 化)
- **修改** `CorpAI/api/app.py:26`(加 CORS、Depends(get_current_user))
- **修改** `CorpAI/agents/{weather,ticket,trip}.py`(桥接逻辑迁到 `tools_gateway.py`)
- **修改** `CorpAI/tools/{weather,ticket,trip}.py`(`POST /tools/{name}` 协议保留;加 Pydantic 边界验证)
- **修改** `tests/test_*_server.py`(3 个 stub 修对 import)
- **修改** `README.md`(删 main.py 错误引用;写新启动说明)

### Phase 2-3(新增平台核心)

- **新增** `platform/db.py:DatabasePool`(集中连接池,替换 `core/memory.py:107-119`、`tools/weather.py:128-136` 模块级 pool)
- **新增** `platform/plugin_manager.py`(entry_points 发现 + 注册表)
- **新增** `platform/auth/{jwt,scopes,router}.py`
- **新增** `platform/orchestrator/{service,intent,planner,react_loop,streaming,tools_gateway,memory_gateway,call_record,errors}.py`
- **新增** `platform/observability/{log,trace,metrics}.py`
- **新增** `platform/migrations/`(原始 SQL + 未来 Alembic)

### Phase 3-5(新增管理后台 + 示范插件)

- **新增** `static/admin/{index,agents,tools,users,logs,metrics}.html`(vanilla JS,5 页)
- **Phase 5 计划**:`plugins/customer_service_demo/{plugin.py,README.md}`(17 行 scaffold,验证 `discover_all()`)— **已整体删除**;真业务由 `hr_assistant` / `sre_copilot` / `faq` 3 个真 plugin 承担
- **新增** `plugins/hr_assistant/{plugin.py,prompts.py,server.py,tools.py}`(从 `tools/trip.py:477-512` `query_insurance` 改造 + 新政策 KB)
- **新增** `plugins/sre_copilot/{plugin.py,prompts.py,server.py,tools.py}`(从 `tools/trip.py:394-425` 改造 + 新 K8s/Jira 适配器)
- **新增** `plugins/faq/{plugin.py,prompts.py,server.py,retriever.py,seed.py}`(从 `tools/trip.py:88-287` 改造 RAG,Phase 7 已删旅游脚本)

### Phase 4(CI/CD)

- **新增** `.github/workflows/{test,lint,build}.yml`
- **新增** `Dockerfile`(单进程打包 orchestrator)
- **新增** `docker-compose.platform.yml`(全栈:orchestrator + plugins + DB + Milvus + Attu)

---

## 3 个真插件映射表(Phase 7:customer_service 已删)

| 新插件 | 复用现有代码 | 企业场景 |
|--------|------------|---------|
| `hr_assistant` | `tools/trip.py:477-512` (`query_insurance`) + 新政策 KB | 员工福利(B001-B008) + 人事政策(P001-P010) |
| `sre_copilot` | `tools/trip.py:394-425` + 新 K8s/Jira 适配器 | 工单查询(INC-001~008) + On-call + Pod 重启 |
| `faq` (RAG) | `tools/trip.py:88-287` | 企业 KB 语义检索(FAQ001~012) |

**每个插件必须声明至少 1 个 RBAC scope** 并演示强制效果(例:`admin` 才能调 `sre_copilot:reboot_pod`)

---

## 复用现有函数/工具

- `utils/format.py:strip_think` — 所有 LLM 输出后处理必须用,**不要重新实现**
- `api/app.py:59-101` ThinkBlockFilter — 必须原样复制到 `orchestrator/streaming.py`,**不要改**
- `core/prompts.py:40-77` `intent_prompt` — 迁到 `orchestrator/intent.py`,**保留全部 prompts**(8 个,不是 6 个)
- `agents/weather.py:153-159` Pydantic `StructuredTool.from_function(args_schema=...)` 模式 — 抽到 `platform/plugin_manager.py` 作为推荐模式
- `tools/weather.py:174-180` `{"status": "success|no_data|error|missing_params"}` envelope — **保留**,plugin 输出统一用此格式
- `make run-*` 模式 + `uv run python -m <module>` — 保留作为插件启动方式

---

## 验证方法(端到端)

每个 Phase 结束时必须通过以下验证才能进入下一阶段:

### Phase 0
- `uv run pytest tests/` 全绿
- `make test-unit` 全绿
- README 无 main.py 引用

### Phase 1
- `uv run pytest tests/orchestrator/` 全绿(特性测试覆盖每个拆分模块)
- 手工 e2e:启动 `make run-api`,聊天"北京天气" → 返回正确结果(行为与重构前一致)
- `import-linter` 检查通过(无跨模块引用违规)

### Phase 2
- `uv run pytest tests/db/` 全绿
- 手工:alice 聊天 → bob 聊天 → alice 看不到 bob 的记忆(`SELECT * FROM short_term_messages WHERE user_id`)

### Phase 3
- `uv run pytest tests/auth/` + `tests/plugin_manager/` 全绿
- 手工:`admin` 登录 → 看到所有 4 个插件;`employee` 登录 → 看不到 `sre_copilot`
- 手工:管理后台 `/admin/agents` 能 CRUD 插件;`/admin/users` 能改 role

### Phase 4
- 手工:`curl /metrics` 返回 Prometheus 文本格式
- 手工:跨插件调用日志都有相同 `trace_id`
- GitHub Actions PR 检查全绿

### Phase 5
- 4 个示范插件完整 e2e:聊天触发每个插件 → 返回正确结果
- 管理后台 5 页全部可点

### Phase 6
- 所有 DB/Milvus 配置通过 `.env` 注入
- Pydantic 边界验证:故意传错类型 → MCP 返回结构化 422 错误
- 所有 `asyncio.run` 反模式清零

---

## 5 大最高风险

### Risk 1:ChatService 零测试覆盖下拆分 ⚠️ HIGH

- **表现**:880 行 11 方法,任何拆分都有回归风险
- **缓解**:Phase 1 先写**特性测试**锁当前行为,再**只拆不改**逻辑;e2e 测试持续跑

### Risk 2:破坏 MCP wire 协议让 3 后端同时挂 ⚠️ MEDIUM

- **表现**:`agents/{weather,ticket,trip}.py` 都通过 `POST /tools/{name}` 调 MCP
- **缓解**:Phase 1 加 wire-protocol 契约测试锁定请求/响应;任何协议变更推迟到 Phase 6

### Risk 3:`ConversationMemory` 全局单例阻塞 per-user 化 ⚠️ HIGH

- **表现**:`core/memory.py:99-105` 无 user_id 区分;alice 看 bob 记忆
- **缓解**:Phase 2 用 `DEFAULT 'legacy'` 迁移,新代码走 `MemoryPool`(带 user_id);保留旧路径到下个 release

### Risk 4:管理后台 scope creep ⚠️ HIGH

- **表现**:admin UI 容易越加越多(图表/钻取/RBAC 矩阵)
- **缓解**:硬上限 5 页 + 列表/增/改/删;**不做**自定义 dashboard;vanilla JS 不引 React

### Risk 5:无 CI/CD 导致演示时崩溃 ⚠️ MEDIUM

- **表现**:没有 `.github/workflows`、没有 `Dockerfile`,本地测试不能保证部署通过
- **缓解**:Phase 4 CI 是非协商项;Phase 5/6 演示前必须 CI 全绿

---

## 当前进度

- ✅ Phase 0 启动:CLAUDE.md + REFACTOR_PLAN.md + ADR 创建
- ⏳ Phase 0 进行中:修 stub 测试 / 删 dead imports / 修 README
- ⏸ Phase 1-6 待启动

每个 Phase 结束更新本节。
