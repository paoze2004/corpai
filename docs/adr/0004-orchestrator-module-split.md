# ADR-004: ChatService → 7 模块拆分

## 状态
**Accepted** — 2026-08-06

## 背景

`CorpAI/core/chat.py` 当前是一个 880 行 11 方法的 god class(`ChatService`, 185-1063 行),承担了:

1. 意图识别 LLM 调用(`intent_agent`, 378-449)
2. Planning 跳过启发式(`_should_skip_planning`, 449-484)
3. Planning LLM 调用(`planning_agent`, 484-519)
4. Agent 网络管理(A2A AgentNetwork)
5. 单 Agent 调用(`_call_agent_intent`, 522-616)
6. ReAct 步骤执行(`execute_step`, 619-640)
7. ReAct 循环(`react_loop`, 643-713)
8. 顶层 chat 入口(`chat`, 716-812)
9. Agent cards 暴露(`get_agent_cards`, 815-843)
10. 记忆状态暴露(`get_memory_state`, 846-864)
11. 流式输出(`chat_stream`, 878-953 + 子方法 955-1063)

### 痛点
- **零测试覆盖**:任何修改都心惊胆战
- **违反 SRP**:11 个职责混在一个类
- **流式/非流式代码重复**:`_react_loop` vs `_react_loop_stream`(逻辑几乎一致,只是 yield vs return)
- **混合 sync/async**:多个 sync LLM `.invoke` 调用在 async 方法里

## 决策

将 `ChatService` 拆分为 7 个 ≤300 行模块,每个模块单一职责:

```
platform/orchestrator/
├── service.py        (180 LOC)  OrchestratorService:唯一协调器,无 LLM 调用
├── intent.py         (220 LOC)  IntentRecognizer:JSON 抽取 + 容错
├── planner.py        (250 LOC)  TaskPlanner:_should_skip_planning + LLM plan
├── react_loop.py     (260 LOC)  ReActRunner:depends_on 分组 + asyncio.gather
├── streaming.py      (170 LOC)  StreamMux:ThinkBlockFilter + SSE 适配
├── tools_gateway.py  (220 LOC)  PluginManager 封装 + RBAC 强制
└── memory_gateway.py (180 LOC)  MemoryPool 封装,per-user scoping
```

### 强制模块边界

```python
# service.py 可以调:
service -> intent, planner, react_loop, tools_gateway, memory_gateway, call_record, streaming

# intent, planner, react_loop 只能调 tools_gateway(互不调)
intent, planner, react_loop -> tools_gateway  # 唯一共享模块

# tools_gateway -> plugin_manager (封装)
# memory_gateway -> pool (封装)
```

**强制方式**:`pyproject.toml` 配置 `import-linter`,提交前跑 `lint-imports` 检查。

### 拆分原则
- **只拆不改**:Phase 1 的拆分**不修改任何业务逻辑**,只重命名 + 移动 + 重新组织调用关系
- **行为保留**:每个新模块必须有**特性测试**,对比拆分前后的输出
- **接口稳定**:外部调用方(`api/app.py`)看到的是同一个 `OrchestratorService` 接口

## 模块职责详细说明

### `service.py` — OrchestratorService (180 LOC)
- **责任**:唯一协调器,无 LLM 调用,无 Agent 调用
- **API**:
  ```python
  class OrchestratorService:
      def __init__(self, intent, planner, react, tools, memory, recorder, stream_mux): ...
      async def chat(self, user_id, session_id, user_input) -> str: ...
      async def chat_stream(self, user_id, session_id, user_input) -> AsyncIterator[str]: ...
      def get_agent_cards(self, user_id) -> list[AgentCard]: ...  # 已被 RBAC 过滤
      def get_memory_state(self, user_id) -> dict: ...
      def clear_memory(self, user_id): ...
  ```

### `intent.py` — IntentRecognizer (220 LOC)
- **责任**:调用 LLM 抽取意图,解析 JSON,容错
- **API**:
  ```python
  class IntentRecognizer:
      def __init__(self, llm, prompt_template): ...
      def extract(self, user_input, history, profile, task_ctx) -> IntentResult: ...
      async def extract_stream(self, user_input, history, profile, task_ctx) -> AsyncIterator[IntentEvent]: ...  # 新增
  ```

### `planner.py` — TaskPlanner (250 LOC)
- **责任**:判断是否跳过 planning;若不跳过,调用 LLM 生成 plan
- **API**:
  ```python
  class TaskPlanner:
      def __init__(self, llm, prompt_template): ...
      def should_skip(self, intents: list[str]) -> bool: ...
      async def plan(self, intents, user_queries, history) -> Plan: ...
  ```

### `react_loop.py` — ReActRunner (260 LOC)
- **责任**:执行 plan 的步骤,depends_on 分组并行,最后汇总
- **API**:
  ```python
  class ReActRunner:
      def __init__(self, tools_gateway, llm, summary_prompt): ...
      async def run(self, steps, user_queries, ctx) -> str: ...
      async def run_stream(self, steps, user_queries, ctx) -> AsyncIterator[str]: ...
  ```

### `streaming.py` — StreamMux (170 LOC)
- **责任**:ThinkBlockFilter 状态机 + SSE 适配 + agent stream → user stream
- **必须保留的代码**:`api/app.py:59-101` ThinkBlockFilter 字节级复制
- **API**:
  ```python
  class StreamMux:
      class ThinkBlockFilter: ...       # 原样保留
      def aformat_sse(self, chunks) -> AsyncIterator[str]: ...   # data: {}\n\n + [DONE]
      def adapt_agent_stream(self, raw) -> AsyncIterator[str]: ...
  ```

### `tools_gateway.py` — ToolsGateway (220 LOC)
- **责任**:封装 PluginManager,加 RBAC 强制 + trace_id 传播 + 指标埋点 + 缓存
- **API**:
  ```python
  class ToolsGateway:
      def __init__(self, plugin_manager, rbac, metrics): ...
      async def invoke(self, agent_name, payload, ctx) -> AgentResult: ...
      async def invoke_stream(self, agent_name, payload, ctx) -> AsyncIterator[AgentChunk]: ...
  ```

### `memory_gateway.py` — MemoryGateway (180 LOC)
- **责任**:封装 MemoryPool,加 per-user scoping(Phase 2 引入)
- **API**:
  ```python
  class MemoryGateway:
      def __init__(self, pool): ...
      def recall(self, user_id, session_id) -> MemorySnapshot: ...
      def record_message(self, user_id, session_id, role, content): ...
      def record_profile_update(self, user_id, key, value): ...
      def cross_agent_share(self, user_id, session_id, key, value): ...  # 新增 Layer 4
  ```

## 后果

### 正面
1. **可测试性**:每个模块独立测试,目标覆盖率 Orchestrator ≥70%
2. **可维护性**:改 streaming 不影响 intent,改 RBAC 不影响 planner
3. **可演进**:未来加 LangGraph 只需替换 `react_loop.py`,其他模块不动
4. **可复用**:插件作者可以单独引用 `streaming.py` 的 ThinkBlockFilter

### 负面
1. **重构工作量**:Phase 1 耗时 3 周(880 行拆分 + 600 行特性测试)
2. **导入开销**:7 个模块的 import 关系增加,需要 `import-linter` 强制
3. **依赖注入**:`service.py` 需要 DI 注入 7 个依赖(原 god class 是 self.*)

### 中性
1. ~~chat.py 保留为兼容 alias~~ → **Phase 1.7 已删除**(见下文"Phase 1.7 收尾")
2. ~~旧 deprecation 警告~~ → 不再需要

## Phase 1.7 收尾 — 删除 `core/chat.py`

Phase 1 完成的 5 个模块(intent/planner/react_loop/streaming/service)在 Phase 1.6 之后只把 `ChatService.chat` / `chat_stream` 内嵌委托给 `OrchestratorService`,但 `ChatService` 本身仍是 880 行,`api/app.py` 仍 `from CorpAI.core.chat import ChatService`,违反 ADR-004 "OrchestratorService 是唯一 high-level 入口"。

**Phase 1.7 完成**:
1. 新增 `CorpAI/platform/wiring.py` 作为**组合根**(composition root),把 A2A 网络、ChatOpenAI、ConversationMemory、DB 加载、A2A → LLM summary 闭包全部装配成 `OrchestratorService`
2. `OrchestratorService` 增加 4 个 sync 门面方法(`get_memory_state` / `clear_memory` / `update_user_profile` / `get_agent_cards`),与原 `ChatService` 对应方法字节级一致;`api/app.py` 6 个端点零改动
3. `OrchestratorService.__init__` 增加第 7 个可选 DI 参数 `agent_card_provider`(`Callable[[], list[dict]]`);不传时返回空列表(原有 6 参数测试兼容)
4. `api/app.py`:只动 2 行(import + 构造);6 个方法调用点零改动
5. **删除 `CorpAI/core/chat.py`(原 1000 行 god class)**
6. **删除 `tests/chat/`**(已被 `tests/platform/` 全量替代)

平台边界:platform/orchestrator/* 保持纯(不导入 A2A / LangChain / MySQL),所有基础实施接线只在 platform/wiring.py 一处。

## 权衡

| 备选方案 | 取舍 |
|---------|------|
| **微内核架构**(plugin 调度可换) | ❌ 拒绝 — 当前不需要调度策略可插拔,YAGNI |
| **保留 god class,只拆 streaming** | ❌ 拒绝 — 880 行太大,后续每个改动都痛苦 |
| **拆分 4 个模块**(更大) | ⚠️ 备选 — 如果 streaming 与 intent 强耦合,可合并为 `flow.py` |
| **wiring.py 放在 `CorpAI/wiring.py`(包外)** | ❌ 拒绝 — `platform/` 才是写死部分;放包外有"应用 vs 平台"语义混乱风险 |
| **wiring.py 在 orchestrator 内** | ❌ 拒绝 — orchestrator 模块必须保持纯,组合根是单独的一层 |

## 验证

- **Phase 1.7 验收**:`pytest tests/platform --tb=short -q` 全绿(70/70)
- **Phase 1.7 验收**:`from CorpAI.core.chat import ChatService` 报 `ModuleNotFoundError`
- **Phase 1.7 验收**:`python -c "from CorpAI.api.app import chat_service; print(type(chat_service).__name__)"` 输出 `OrchestratorService`
- **Phase 1.7 验收**:6 端点方法(`chat` / `chat_stream` / `get_memory_state` / `clear_memory` / `update_user_profile` / `get_agent_cards`)都存在
- **Phase 1 验收**:原 `tests/orchestrator/` 路径已迁移到 `tests/platform/`(实际目录)
- **手工 e2e**:聊天"北京天气" → 返回与拆分前一致(ChatService.chat_stream → OrchestratorService.chat_stream)
- **未做(留待 Phase 4)**:`import-linter` 当前未配置;平台纯度靠代码约束(grep 检查 platform/* 不 import `tools/`/`agents/`)

## 参考引用

- `OrchestratorService`:`CorpAI/platform/orchestrator/service.py:42`(原 god class 已删除)
- 组合根:`CorpAI/platform/wiring.py`
- 5 模块:`intent.py:31` / `planner.py:34` / `react_loop.py:31` / `streaming.py:20` / `service.py:42`
- App 兼容门面(7 个 DI 后的 6 端点对应方法):`service.py` 内 `get_memory_state` / `clear_memory` / `update_user_profile` / `get_agent_cards`
- 流式参考:`CorpAI/platform/orchestrator/streaming.py:20` `ThinkBlockFilter`(状态机字节级保留自 `api/app.py:59-101`)
