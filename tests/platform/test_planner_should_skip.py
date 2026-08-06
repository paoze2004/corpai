"""
TaskPlanner.should_skip 测试 — 验证拆分后行为与 ChatService._should_skip_planning 完全一致。

锁定的 INDEPENDENT_INTENTS 集合(CorpAI/platform/orchestrator/planner.py):
    {weather, flight, train, concert, attraction, car_rental, tour_group, insurance, trip_order}
"""
from CorpAI.platform.orchestrator.planner import TaskPlanner, INDEPENDENT_INTENTS


class FakeMemory:
    """占位 memory(should_skip 不调用 memory,但 TaskPlanner.__init__ 需要 memory 参数)"""
    def get_short_term_text(self) -> str:
        return ""

    def get_profile_text(self) -> str:
        return ""


class FakeLLM:
    """占位 LLM(should_skip 不调用 LLM)"""
    pass


class TestTaskPlannerShouldSkip:
    """TaskPlanner.should_skip 行为锁定(应与 TestShouldSkipPlanning 一致)。"""

    def setup_method(self):
        self.planner = TaskPlanner(llm=FakeLLM(), memory=FakeMemory(), messages_provider=lambda: [])

    # ─── 单意图 / 空 ───
    def test_empty_intents_returns_true(self):
        assert self.planner.should_skip([]) is True

    def test_single_known_intent_returns_true(self):
        assert self.planner.should_skip(["weather"]) is True
        assert self.planner.should_skip(["flight"]) is True

    def test_single_complex_returns_true(self):
        assert self.planner.should_skip(["complex"]) is True

    def test_single_order_returns_true(self):
        assert self.planner.should_skip(["order"]) is True

    def test_single_out_of_scope_returns_true(self):
        assert self.planner.should_skip(["out_of_scope"]) is True

    def test_single_unknown_returns_true(self):
        assert self.planner.should_skip(["foobar"]) is True

    # ─── 多意图(全部独立) ───
    def test_multiple_all_independent_returns_true(self):
        assert self.planner.should_skip(["weather", "flight"]) is True
        assert self.planner.should_skip(["weather", "attraction", "tour_group"]) is True
        assert self.planner.should_skip(list(INDEPENDENT_INTENTS)) is True

    # ─── 多意图(含非独立) ───
    def test_multiple_with_complex_returns_false(self):
        assert self.planner.should_skip(["weather", "complex"]) is False

    def test_multiple_with_order_returns_false(self):
        assert self.planner.should_skip(["weather", "order"]) is False

    def test_multiple_with_out_of_scope_returns_false(self):
        assert self.planner.should_skip(["weather", "out_of_scope"]) is False

    def test_multiple_with_unknown_returns_false(self):
        assert self.planner.should_skip(["weather", "foobar"]) is False


class TestIndependentIntentsConstant:
    """INDEPENDENT_INTENTS 常量锁定(9 个 intent)。"""

    def test_has_9_intents(self):
        """独立意图集合恰好 9 个元素(防止遗漏/多写)。"""
        assert len(INDEPENDENT_INTENTS) == 9

    def test_required_intents_present(self):
        """必要 intent 都在集合内。"""
        required = {
            "weather", "flight", "train", "concert", "attraction",
            "car_rental", "tour_group", "insurance", "trip_order"
        }
        assert INDEPENDENT_INTENTS == required

    def test_complex_not_in_set(self):
        """complex 不在独立集合(否则会和 single_complex 返回 True 的现有行为冲突)。"""
        assert "complex" not in INDEPENDENT_INTENTS

    def test_order_not_in_set(self):
        """order 不在独立集合(多意图含 order 需要 planning)。"""
        assert "order" not in INDEPENDENT_INTENTS
