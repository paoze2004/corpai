"""
ReActRunner 行为测试 — 验证拆分后行为与 ChatService.execute_step + ChatService.react_loop 完全一致。

注:不引入 pytest-asyncio 依赖,用 asyncio.run() 包装 async 测试。
   不直接 mock LLM,而用 langchain RunnableLambda 包装 fake 函数,这样
   `summary_prompt | llm` LangChain chain 能正常工作,并能记录调用。
"""
import asyncio
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda


def run_async(coro):
    return asyncio.run(coro)


def make_recording_llm(response: str = "综合回复"):
    """返回 (llm, calls) — llm 是 RunnableLambda,calls 记录每次 invoke 输入。"""
    calls: list = []
    def fake_llm_func(prompt_value):
        calls.append(str(prompt_value))
        return AIMessage(content=response)
    llm = RunnableLambda(fake_llm_func)
    return llm, calls


async def fake_step_executor(intent: str, query_str: str) -> str:
    return f"{intent}:{query_str}"


def make_messages_provider(messages: list[dict] | None = None):
    msgs = messages if messages is not None else [{"role": "user", "content": "原始查询"}]
    return lambda: msgs


# 导入放在最后(避免模块加载时的循环)
from CorpAI.platform.orchestrator.react_loop import ReActRunner


def make_runner(llm=None, executor=None, messages=None):
    if messages is None:
        messages = [{"role": "user", "content": "原始查询"}]
    return ReActRunner(
        llm=llm if llm is not None else RunnableLambda(lambda x: AIMessage(content="ok")),
        step_executor=executor if executor is not None else fake_step_executor,
        messages_provider=make_messages_provider(messages),
    )


class TestExecuteStep:
    """ReActRunner.execute_step 行为。"""

    def test_query_from_user_queries(self):
        runner = make_runner()

        async def go():
            return await runner.execute_step(
                {"step": 1, "action": "查天气", "intent": "weather"},
                {"weather": "北京明天天气"},
            )

        assert run_async(go()) == "weather:北京明天天气"

    def test_query_fallback_to_messages(self):
        runner = make_runner()

        async def go():
            return await runner.execute_step(
                {"step": 1, "action": "查天气", "intent": "weather"},
                {},
            )

        assert run_async(go()) == "weather:原始查询"

    def test_empty_messages_fallback(self):
        runner = make_runner(messages=[])

        async def go():
            return await runner.execute_step(
                {"step": 1, "intent": "weather"},
                {},
            )

        assert run_async(go()) == "weather:"


class TestReactLoopRun:
    """ReActRunner.run 行为。"""

    def test_single_step_returns_observation_directly(self):
        """单步骤 → 不调 LLM,直接返回 observation。"""
        llm, calls = make_recording_llm()
        runner = make_runner(llm=llm)

        async def go():
            return await runner.run(
                [{"step": 1, "action": "查天气", "intent": "weather", "depends_on": 0}],
                {"weather": "北京天气"},
            )

        result = run_async(go())
        assert result == "weather:北京天气"
        assert calls == []  # 单步不调 LLM

    def test_multiple_steps_same_dep_runs_in_parallel(self):
        """多步骤同 depends_on → 并行执行 + 汇总调 LLM。"""
        llm, calls = make_recording_llm(response="汇总后的回复")
        runner = make_runner(llm=llm)

        async def go():
            return await runner.run(
                [
                    {"step": 1, "action": "查天气", "intent": "weather", "depends_on": 0},
                    {"step": 2, "action": "查机票", "intent": "flight", "depends_on": 0},
                ],
                {"weather": "北京天气", "flight": "北京到上海"},
            )

        result = run_async(go())
        assert result == "汇总后的回复"
        assert len(calls) == 1
        all_obs_input = calls[0]
        # PromptValue 转 str 后含格式化文本
        assert "weather:北京天气" in all_obs_input
        assert "flight:北京到上海" in all_obs_input
        # query 也注入
        assert "原始查询" in all_obs_input

    def test_multiple_steps_different_dep_groups_sequentially(self):
        """不同 depends_on 分组,按 OrderedDict 顺序串行执行。"""
        llm, calls = make_recording_llm(response="汇总回复")
        runner = make_runner(llm=llm)

        async def go():
            return await runner.run(
                [
                    {"step": 1, "action": "step1", "intent": "weather", "depends_on": 0},
                    {"step": 2, "action": "step2", "intent": "flight", "depends_on": 1},
                    {"step": 3, "action": "step3", "intent": "attraction", "depends_on": 1},
                ],
                {"weather": "w", "flight": "f", "attraction": "a"},
            )

        result = run_async(go())
        assert result == "汇总回复"
        assert len(calls) == 1
        # 3 个 step 都被执行
        for marker in ["weather:w", "flight:f", "attraction:a"]:
            assert marker in calls[0]

    def test_empty_steps_returns_fallback(self):
        """空步骤 → '暂无结果',不调 LLM。"""
        llm, calls = make_recording_llm()
        runner = make_runner(llm=llm)

        async def go():
            return await runner.run([], {})

        result = run_async(go())
        assert result == "暂无结果"
        assert calls == []

    def test_exception_in_step_caught_and_formatted(self):
        """组内某步骤抛异常 → '执行失败:{exc}' 注入到 all_observations。"""
        async def failing_executor(intent: str, query_str: str) -> str:
            if intent == "weather":
                raise RuntimeError("API timeout")
            return f"ok:{query_str}"

        llm, calls = make_recording_llm(response="含失败信息的回复")
        runner = make_runner(llm=llm, executor=failing_executor)

        async def go():
            return await runner.run(
                [
                    {"step": 1, "intent": "weather", "depends_on": 0},
                    {"step": 2, "intent": "flight", "depends_on": 0},
                ],
                {"weather": "w", "flight": "f"},
            )

        result = run_async(go())
        assert len(calls) == 1
        all_obs = calls[0]
        assert "执行失败" in all_obs
        assert "API timeout" in all_obs
        assert "ok:f" in all_obs

    def test_step_executor_called_with_intent_and_query(self):
        """验证 step_executor 收到正确的 (intent, query_str) 参数。"""
        captured = []

        async def capturing_executor(intent: str, query_str: str) -> str:
            captured.append((intent, query_str))
            return "ok"

        runner = make_runner(executor=capturing_executor)

        async def go():
            return await runner.run(
                [
                    {"step": 1, "intent": "weather", "depends_on": 0},
                    {"step": 2, "intent": "flight", "depends_on": 0},
                ],
                {"weather": "北京", "flight": "上海"},
            )

        run_async(go())
        assert ("weather", "北京") in captured
        assert ("flight", "上海") in captured


class TestReactLoopStepDescriptionFallback:
    """step description 字段 fallback:description → action → ''。"""

    def test_uses_description_when_present(self):
        llm, calls = make_recording_llm()
        runner = make_runner(llm=llm)

        async def go():
            return await runner.run(
                [
                    {"step": 1, "description": "详细描述", "action": "action", "intent": "weather", "depends_on": 0},
                    {"step": 2, "description": "其他", "action": "x", "intent": "flight", "depends_on": 0},
                ],
                {"weather": "w", "flight": "f"},
            )

        run_async(go())
        assert "详细描述" in calls[0]
        assert "其他" in calls[0]

    def test_falls_back_to_action_when_no_description(self):
        llm, calls = make_recording_llm()
        runner = make_runner(llm=llm)

        async def go():
            return await runner.run(
                [
                    {"step": 1, "action": "action描述", "intent": "weather", "depends_on": 0},
                    {"step": 2, "action": "action2", "intent": "flight", "depends_on": 0},
                ],
                {"weather": "w", "flight": "f"},
            )

        run_async(go())
        assert "action描述" in calls[0]
        assert "action2" in calls[0]

    def test_falls_back_to_empty_when_no_desc_or_action(self):
        llm, calls = make_recording_llm()
        runner = make_runner(llm=llm)

        async def go():
            return await runner.run(
                [
                    {"step": 1, "intent": "weather", "depends_on": 0},
                    {"step": 2, "intent": "flight", "depends_on": 0},
                ],
                {"weather": "w", "flight": "f"},
            )

        run_async(go())
        # 无 description/action → "步骤1 (): weather:w"
        assert "步骤1 (): weather:w" in calls[0]
        assert "步骤2 (): flight:f" in calls[0]
