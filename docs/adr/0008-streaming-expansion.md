# ADR-008: 流式输出扩展到意图/规划阶段

## 状态
**Accepted** — 2026-08-06

## 背景

CorpAI 当前流式输出(`core/chat.py:878-953` `chat_stream`)**只流最终响应**:

```python
async def chat_stream(self, user_input):
    # 1. 同步调意图识别(invoke,不流)
    intents, user_queries, follow_up = self.intent_agent(...)
    # 2. 同步调 planning(若需要)
    if not self._should_skip_planning(intents):
        steps = self.planning_agent(...)
    # 3. 同步执行所有步骤(不流)
    if simple:
        result = await self._call_agent_intent_stream(...)
        # 上面这个会流式输出,但只流"最后一步的 summary"
    # 4. 把完整响应 yield 出去
```

**用户看到的是**:
- 输入消息 → **静默 1-3 秒**(等待意图识别 + planning + agent 调用)
- 突然开始流式输出最终响应
- 体验:**"AI 在想什么我看不到"**

### 业务痛点

1. **等待感强**:企业用户问复杂问题时(多意图),等待时间可能 5+ 秒,容易以为系统挂了
2. **意图不透明**:用户看不到"AI 把它当作出差订票任务处理"这种意图识别结果
3. **进度无反馈**:Planning 出 4 个步骤时,用户不知道现在到哪一步了

## 决策

**扩展流式输出到意图识别、规划、所有 Agent 调用阶段**。

### 流式阶段设计

```
[用户输入] → 
  ↓
[Stream Event] intent_start
  ↓ (流式)
[Stream Event] intent_tokens { partial_json }
  ↓
[Stream Event] intent_done { intents: [...], user_queries: {...} }
  ↓
[Stream Event] plan_start (若需 planning)
  ↓ (流式)
[Stream Event] plan_tokens { partial_steps }
  ↓
[Stream Event] plan_done { steps: [...] }
  ↓
[Stream Event] step_start { step: 1, action: "查天气" }
  ↓
[Stream Event] step_done { step: 1, result: "..." }
  ↓
[Stream Event] step_start { step: 2, action: "订票" }
  ↓
[Stream Event] step_done { step: 2, result: "..." }
  ↓
[Stream Event] summary_start
  ↓ (流式)
[Stream Event] summary_tokens
  ↓
[Stream Event] summary_done { full_text: "..." }
  ↓
[Stream Event] done
```

### SSE Wire 格式

保持现有格式(`data: {"chunk":...}\n\n` + `[DONE]`),扩展 `chunk` 字段:

```json
// 普通文本 chunk(现状)
data: {"chunk": "北京今天", "type": "text"}\n\n

// 新增 chunk 类型
data: {"chunk": "", "type": "intent_start"}\n\n
data: {"chunk": "{\"intents\":[\"weather\"", "type": "intent_tokens"}\n\n
data: {"chunk": "]", "type": "intent_tokens"}\n\n
data: {"chunk": "", "type": "intent_done", "intents": ["weather"]}\n\n
data: {"chunk": "", "type": "plan_start"}\n\n
data: {"chunk": "{\"steps\":[{\"step\":1,...", "type": "plan_tokens"}\n\n
data: {"chunk": "]", "type": "plan_done", "steps": [...]}\n\n
data: {"chunk": "", "type": "step_start", "step": 1, "action": "查天气"}\n\n
data: {"chunk": "北京天气:晴,25°C", "type": "step_done", "step": 1}\n\n
data: {"chunk": "", "type": "summary_start"}\n\n
data: {"chunk": "好的,", "type": "summary_tokens"}\n\n
data: {"chunk": "明天北京天气晴朗", "type": "summary_tokens"}\n\n
data: {"chunk": "", "type": "summary_done"}\n\n

// 终止符(不变)
data: [DONE]\n\n
```

### 前端适配

`static/index.html` 当前只显示 `parsed.chunk`(默认 `type=text`)。扩展为:

```javascript
const event = parsed;
// 现有逻辑:文本 chunk 直接 append
if (event.type === "text" || event.type === "summary_tokens") {
    bubbleText += event.chunk;
    render();
}
// 新增:进度事件
else if (event.type === "intent_start") {
    showProgress("识别意图...");
}
else if (event.type === "intent_done") {
    showProgress(`意图: ${event.intents.join(", ")}`);
}
else if (event.type === "step_start") {
    showProgress(`步骤 ${event.step}: ${event.action}`);
}
else if (event.type === "step_done") {
    appendIntermediateResult(event.step, event.chunk);
}
```

### 实现要点

1. **IntentRecognizer.extract_stream** 新增:用 `llm.astream()` 替代 `llm.invoke()`,逐 chunk 累积 JSON
2. **TaskPlanner.plan_stream** 新增:同上
3. **ReActRunner.run_stream** 改造:每一步执行后 yield `step_done` 事件
4. **OrchestratorService.chat_stream** 改造:用 AsyncGenerator 串联所有阶段

### 增量成本

- **LOC**:`streaming.py` +20、`intent.py` +30、`planner.py` +30、`react_loop.py` +20、`service.py` +30 = **~130 LOC**
- **测试**:每个流式方法的异步测试,~150 LOC
- **前端**:`static/index.html` 新增 ~80 LOC 处理进度事件
- **总计**:**~360 LOC 增量**

### 收益

1. **用户体验跃升**:用户看到"AI 在做什么",等待不再焦虑
2. **调试透明**:开发期可看到意图/规划 JSON,加快 bug 定位
3. **新功能基础**:未来可加"取消当前任务"按钮(监听 step_done 即可知道进度)
4. **零新依赖**:LangChain 已有 `astream()`,前端 `fetch` 已有

## 后果

### 正面
1. **UX**:从"黑盒"变"白盒"
2. **调试**:开发期可看到每一步
3. **未来扩展**:可加 cancel、retry、step-level RBAC

### 负面
1. **代码量增加**:~360 LOC
2. **测试复杂度**:异步流式测试比同步测试难写
3. **前端处理复杂**:需要处理多种 event type
4. **JSON 解析脆弱**:intent JSON 流式累积时,半截 JSON 可能让前端崩溃(需要 buffer + 累积)

### 中性
1. **SSE 协议向后兼容**:现有 `data: [DONE]` 终止符不变
2. **ThinkBlockFilter 保留**:对 `summary_tokens` 仍然有效
3. **可选特性**:前端若不处理新 event type,自动降级为"纯文本流"(因为 `type=text` 仍能工作)

## 权衡

| 备选方案 | 取舍 |
|---------|------|
| **不流式,前端轮询状态** | ❌ 拒绝 — 轮询开销大 + 实时性差 |
| **WebSocket 替代 SSE** | ❌ 拒绝 — WebSocket 双向但 admin UI 不需要双向;SSE 简单够用 |
| **只流式 summary,不流式 intent/plan** | ⚠️ 备选 — 工作量减半但 UX 改进有限;用户最焦虑的就是"开始到 summary 之间" |
| **加 cancel 按钮** | ⏸ 推迟到 Phase 5+ — 需要先有 step_done 事件;Phase 4 仅做流式,不实现 cancel |

## 验证

- **Phase 1 验收**(同步版):`/api/chat` 行为与当前一致(零回归)
- **Phase 4 验收**(完整流式):
  - 手工 e2e:聊天"明天北京天气怎么样,顺便查后天到上海的机票"
    - 看到 `intent_start` → `intent_tokens`(JSON 累积)→ `intent_done` (intents=["weather", "flight"])
    - 看到 `plan_start` → `plan_done` (steps=[...])
    - 看到 `step_start` × 2 → `step_done` × 2
    - 看到 `summary_start` → 流式 summary → `done`
- **Phase 4 验收**:故意传空 message → 收到 `intent_done` with `intents=[]` + `done`
- **前端验收**:`static/index.html` 显示进度信息,不卡顿

## 参考引用

- 当前 chat_stream:`CorpAI/core/chat.py:878-953`
- 当前 ThinkBlockFilter:`CorpAI/api/app.py:59-101`
- 当前 SSE wire:`CorpAI/api/app.py:104-119`
- 前端消费:`CorpAI/static/index.html:285-349`
