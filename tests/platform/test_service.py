"""
OrchestratorService 行为测试 — 验证 7 模块协调正确。

测试用 fake 模块验证 OrchestratorService 正确:
- 调用 IntentRecognizer.extract()
- 调用 TaskPlanner.should_skip() / plan()
- 调用 ReActRunner.run() 或 simple_step_executor
- 调用 memory.add_message()
- 处理 out_of_scope / follow_up / 异常

注:不引入 pytest-asyncio,用 asyncio.run() 包装。

Phase 7 清理:删除 attraction_executor 相关测试(旅行 plugin 已删);
intent 改为企业域 hr / devops / faq。
"""
import asyncio
import json

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda


def run_async(coro):
    return asyncio.run(coro)


# ════════════════════════════════════════════════════════════════
# Fakes — 5 模块的 mock 实现
# ════════════════════════════════════════════════════════════════
class FakeIntent:
    """模拟 IntentRecognizer。"""
    def __init__(self, intents, user_queries=None, follow_up=""):
        self._intents = intents
        self._user_queries = user_queries or {}
        self._follow_up = follow_up
        self.calls = []

    def extract(self, user_input):
        self.calls.append(user_input)
        return self._intents, self._user_queries, self._follow_up


class FakePlanner:
    """模拟 TaskPlanner。"""
    def __init__(self, should_skip=True, plan=None):
        self._should_skip = should_skip
        self._plan = plan or {"need_plan": False, "reason": "fake", "steps": []}
        self.skip_calls = []
        self.plan_calls = []

    def should_skip(self, intents):
        self.skip_calls.append(intents)
        return self._should_skip

    def plan(self, intents, user_queries):
        self.plan_calls.append((intents, user_queries))
        return self._plan


class FakeReactRunner:
    """模拟 ReActRunner。"""
    def __init__(self, response="react_runner_result"):
        self._response = response
        self.run_calls = []

    async def run(self, steps, user_queries):
        self.run_calls.append((steps, user_queries))
        return self._response


class FakeMemory:
    """模拟 ConversationMemory。"""
    def __init__(self):
        self.messages = []
        self.add_calls = []

    def add_message(self, role, content):
        self.add_calls.append((role, content))
        self.messages.append({"role": role, "content": content})

    def get_short_term_text(self):
        return ""


def make_simple_step_executor(return_value="simple_result", captured=None):
    """构造 simple_step_executor async callable。"""
    async def executor(intent, query_str):
        if captured is not None:
            captured.append((intent, query_str))
        return return_value
    return executor


def make_service(
    intents=None,
    user_queries=None,
    follow_up="",
    should_skip=True,
    plan=None,
    react_response="react_result",
    simple_return="simple_result",
):
    """工厂:构造带所有 fake 的 OrchestratorService。"""
    from CorpAI.platform.orchestrator import OrchestratorService

    simple_captured = []

    service = OrchestratorService(
        intent=FakeIntent(intents or [], user_queries, follow_up),
        planner=FakePlanner(should_skip, plan),
        react_runner=FakeReactRunner(react_response),
        simple_step_executor=make_simple_step_executor(simple_return, simple_captured),
        memory=FakeMemory(),
    )
    service._simple_captured = simple_captured
    return service


# ════════════════════════════════════════════════════════════════
# chat() — 非流式测试
# ════════════════════════════════════════════════════════════════
class TestChatOutOfScope:
    """out_of_scope 意图 → 直接返回 follow_up_message,不走 agent。"""

    def test_out_of_scope_returns_followup(self):
        svc = make_service(
            intents=["out_of_scope"],
            follow_up="这个问题超出当前 Copilot 能力范围",
        )

        async def go():
            return await svc.chat("什么是宇宙的终极真理?")
        result = run_async(go())
        assert result == "这个问题超出当前 Copilot 能力范围"
        # 记录了 user + assistant 两条 message
        assert len(svc.memory.add_calls) == 2
        assert svc.memory.add_calls[0] == ("user", "什么是宇宙的终极真理?")
        assert svc.memory.add_calls[1] == ("assistant", "这个问题超出当前 Copilot 能力范围")


class TestChatFollowup:
    """follow_up_message 非空 → 直接返回,不走 agent。"""

    def test_followup_message_returns_directly(self):
        svc = make_service(
            intents=["hr"],
            follow_up="请告诉我您想查询的具体福利/政策",
        )

        async def go():
            return await svc.chat("查福利")
        result = run_async(go())
        assert result == "请告诉我您想查询的具体福利/政策"
        # planner 不应被调
        assert svc.planner.skip_calls == []


class TestChatSimplePath:
    """简单路径:启发式跳过 → 逐 intent 串行执行。"""

    def test_single_intent_uses_simple_executor(self):
        svc = make_service(
            intents=["hr"],
            user_queries={"hr": "公司有什么福利"},
            should_skip=True,
        )

        async def go():
            return await svc.chat("公司有什么福利")
        result = run_async(go())
        assert result == "simple_result"
        # simple_executor 被调
        assert svc._simple_captured == [("hr", "公司有什么福利")]

    def test_multiple_intents_joined_by_newline(self):
        svc = make_service(
            intents=["hr", "faq"],
            user_queries={"hr": "年假", "faq": "VPN"},
            should_skip=True,
        )

        async def go():
            return await svc.chat("年假和 VPN 怎么申请")
        result = run_async(go())
        # 多个 intent 用 \n\n 拼接
        assert result == "simple_result\n\nsimple_result"
        assert ("hr", "年假") in svc._simple_captured
        assert ("faq", "VPN") in svc._simple_captured


class TestChatPlannerPath:
    """规划路径:多 intent 含 order 等非独立 → 触发 ReAct。"""

    def test_need_plan_uses_react_runner(self):
        steps = [{"step": 1, "intent": "hr", "depends_on": 0}]
        svc = make_service(
            intents=["hr", "order"],
            user_queries={"hr": "年假", "order": "申请年假"},
            should_skip=False,  # 含 order,需要 planning
            plan={"need_plan": True, "reason": "复杂", "steps": steps},
            react_response="react综合回复",
        )

        async def go():
            return await svc.chat("复杂任务")
        result = run_async(go())
        assert result == "react综合回复"
        # react_runner 被调
        assert svc.react_runner.run_calls == [(steps, {"hr": "年假", "order": "申请年假"})]
        # simple_executor 不应被调
        assert svc._simple_captured == []


class TestChatExceptionHandling:
    """异常处理:JSON 解析失败 / 通用异常 → 返回 error_message。"""

    def test_json_decode_error_caught(self):
        from CorpAI.platform.orchestrator import OrchestratorService

        class RaisingIntent:
            def extract(self, user_input):
                raise json.JSONDecodeError("bad json", "x", 0)

        svc = OrchestratorService(
            intent=RaisingIntent(),
            planner=FakePlanner(),
            react_runner=FakeReactRunner(),
            simple_step_executor=make_simple_step_executor(),
            memory=FakeMemory(),
        )

        async def go():
            return await svc.chat("test")
        result = run_async(go())
        assert "意图识别JSON解析失败" in result
        # 错误也写入 memory
        assert any("意图识别JSON解析失败" in c[1] for c in svc.memory.add_calls)

    def test_generic_exception_caught(self):
        from CorpAI.platform.orchestrator import OrchestratorService

        class RaisingIntent:
            def extract(self, user_input):
                raise RuntimeError("服务挂了")

        svc = OrchestratorService(
            intent=RaisingIntent(),
            planner=FakePlanner(),
            react_runner=FakeReactRunner(),
            simple_step_executor=make_simple_step_executor(),
            memory=FakeMemory(),
        )

        async def go():
            return await svc.chat("test")
        result = run_async(go())
        assert "处理失败" in result
        assert "服务挂了" in result


class TestChatMemoryWrite:
    """每次 chat() 写 2 条 message:user + assistant。"""

    def test_records_user_and_assistant(self):
        svc = make_service(
            intents=["hr"],
            user_queries={"hr": "年假"},
            should_skip=True,
        )

        async def go():
            return await svc.chat("年假")
        run_async(go())
        assert svc.memory.add_calls == [
            ("user", "年假"),
            ("assistant", "simple_result"),
        ]


# ════════════════════════════════════════════════════════════════
# chat_stream() — 流式测试
# ════════════════════════════════════════════════════════════════
def collect_chunks(async_gen):
    """async generator → list(同步消费)。"""
    chunks = []
    async def consume():
        async for c in async_gen:
            chunks.append(c)
    run_async(consume())
    return chunks


class TestChatStream:
    """流式路径 — 完全等价于 chat(),但逐 chunk yield。"""

    def test_simple_intent_yields_full_result(self):
        """Phase 1.6 简化版:yield 完整结果(无 token streaming)。"""
        svc = make_service(
            intents=["hr"],
            user_queries={"hr": "年假"},
            should_skip=True,
        )

        chunks = collect_chunks(svc.chat_stream("年假"))
        # 简化版只 yield 一次完整结果
        assert "".join(chunks) == "simple_result"
        # 仍然写 memory
        assert len(svc.memory.add_calls) == 2

    def test_out_of_scope_yields_followup(self):
        svc = make_service(
            intents=["out_of_scope"],
            follow_up="超出范围",
        )
        chunks = collect_chunks(svc.chat_stream("test"))
        assert "".join(chunks) == "超出范围"

    def test_planner_path_uses_react_runner(self):
        steps = [{"step": 1, "intent": "hr", "depends_on": 0}]
        svc = make_service(
            intents=["hr", "order"],
            user_queries={"hr": "年假", "order": "申请"},
            should_skip=False,
            plan={"need_plan": True, "steps": steps},
            react_response="react流式回复",
        )
        chunks = collect_chunks(svc.chat_stream("复杂"))
        assert "".join(chunks) == "react流式回复"
        assert svc.react_runner.run_calls == [(steps, {"hr": "年假", "order": "申请"})]

    def test_exception_in_stream_yields_error(self):
        from CorpAI.platform.orchestrator import OrchestratorService

        class RaisingIntent:
            def extract(self, user_input):
                raise RuntimeError("流式异常")

        svc = OrchestratorService(
            intent=RaisingIntent(),
            planner=FakePlanner(),
            react_runner=FakeReactRunner(),
            simple_step_executor=make_simple_step_executor(),
            memory=FakeMemory(),
        )
        chunks = collect_chunks(svc.chat_stream("test"))
        assert any("流式异常" in c for c in chunks)