# ADR-009: 不引入 LangGraph

## 状态
**Accepted** — 2026-08-06

## 背景

LangGraph 是 LangChain 团队推出的图编排框架(2024 GA),适合:
- 复杂多 Agent 状态机(循环、条件分支、并行)
- 强类型 State(typed dict / Pydantic model)
- Checkpointing + time travel 调试
- Human-in-the-loop 节点

### 现有 ChatService 的 ReAct 实现

`CorpAI/core/chat.py:643-713` 的 `react_loop`:
- 用 `depends_on` 整数分组(`OrderedDict` 按 key 插入顺序)
- `asyncio.gather(*tasks, return_exceptions=True)` 并行
- 收集所有 observation 后,调 `react_summary_prompt` 汇总
- 简单、无状态机、无 checkpoint

### LangGraph 优势分析

| LangGraph 卖点 | 我们是否需要 |
|---------------|-------------|
| 状态机(节点 + 边) | ❌ 当前 plan→execute→summarize 是线性的,不是状态机 |
| Checkpointing | ⚠️ Phase 4 Observability 包含 call_records,可代替部分需求 |
| Time travel 调试 | ❌ 演示为主,生产问题靠日志 |
| 强类型 State | ✅ 有用,但 Pydantic 已能解决 |
| Human-in-the-loop | ⏸ Phase 5+ 评估 |

### 不引入的成本
- 不引入 LangGraph:代码量 -50%(拆分后)+ 现有 ReAct 逻辑保留
- 引入 LangGraph:重写 react_loop + State schema + checkpoint storage,预计 +800 LOC + 学习成本

## 决策

**不引入 LangGraph,保留 LangChain ReAct + 自建 react_loop**。

### 边界

1. **Phase 0-3**:不引入 LangGraph;继续用 LangChain `AgentExecutor` + 自建 `react_loop`
2. **Phase 4+**:如果出现以下需求,**重新评估** LangGraph:
   - 需要 checkpointing(例如长时间任务中断恢复)
   - 需要 human-in-the-loop 节点(审批后才能继续)
   - State 变得非常复杂(>5 个状态字段,互相依赖)
3. **永远不引入的条件**:演示 demo 能跑通 + 4 周内能完成

### react_loop.py 的设计(已包含在 ADR-004)

```python
class ReActRunner:
    async def run(self, steps: list[PlanStep], user_queries: dict, ctx: Context) -> str:
        dep_groups = OrderedDict()
        for step in steps:
            dep = step.get("depends_on", 0)
            dep_groups.setdefault(dep, []).append(step)
        
        observations = []
        for dep_key, group_steps in dep_groups.items():
            if len(group_steps) > 1:
                tasks = [self.execute_step(s, user_queries, ctx) for s in group_steps]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                # 处理结果...
            else:
                result = await self.execute_step(group_steps[0], user_queries, ctx)
                # ...
        
        return await self.summarize(observations, ctx.query)
```

逻辑保持简单:分组 → 并行 → 汇总。不引入图模型。

### 未来引入的触发条件(明确记录)

如以下任一情况发生,**重新评估** LangGraph:

1. **状态爆炸**:State 字段超过 5 个,且互相有 derived 关系
2. **复杂分支**:出现"if step1.result == X then step3 else step4" 这种条件边
3. **长时间任务**:有需要暂停/恢复/审核的步骤(>30 秒)
4. **可观测性需求**:需要 time-travel 调试(回到任意步骤看当时状态)

**任一条件满足** → 写新的 ADR 评估 LangGraph 迁移成本。

## 后果

### 正面
1. **代码量低**:react_loop.py 260 LOC,LangGraph 重写需 ~600 LOC
2. **学习成本低**:团队已熟 LangChain
3. **零迁移工作**:Phase 1 拆分时直接保留现有逻辑
4. **依赖少**:不引入新依赖,pyproject.toml 不变

### 负面
1. **状态管理简单**:无法表达复杂状态机(但当前不需要)
2. **调试靠日志**:没有 LangGraph 的 time travel(但 call_records 可替代)
3. **未来重写风险**:如果需求增长到上述触发条件,需要重写 react_loop

### 中性
1. **决策可逆**:如果将来需要,引入 LangGraph 是局部重写,不影响其他模块
2. **架构灵活性**:ADR-004 已把 react_loop 隔离成单一模块,未来替换影响范围小

## 权衡

| 备选方案 | 取舍 |
|---------|------|
| **立即引入 LangGraph** | ❌ 拒绝 — 当前不需要;引入 = 重写 4 周工作 |
| **保留 LangChain 0.2 老版 ReAct** | ❌ 拒绝 — 当前已用 LangChain 0.3 + `create_tool_calling_agent` |
| **引入 PydanticAI(独立框架)** | � 拒绝 — 学习曲线高;与 LangChain 生态不兼容 |
| **自建 state machine(yet-another-framework)** | ❌ 拒绝 — 不要重复造轮子 |
| **观望,Phase 5 评估** | ⚠️ 备选 — 当前不引入,但保留 trigger 条件 |

## 验证

- **Phase 0**:LangGraph 不在 `pyproject.toml` 依赖中
- **Phase 1**:`platform/orchestrator/react_loop.py` 独立模块,逻辑与原 `core/chat.py:643-713` 等价
- **Phase 5 复盘**:若 State 复杂度增加,写新 ADR 评估 LangGraph

## 参考引用

- 现有 react_loop:`CorpAI/core/chat.py:643-713`
- 拆分目标:`platform/orchestrator/react_loop.py`(Phase 1)
- LangGraph 文档:https://langchain-ai.github.io/langgraph/
