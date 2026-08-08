"""
任务规划模块 — Phase 1 拆分自 chat.py:449-482 (_should_skip_planning) + chat.py:484-520 (planning_agent)。

关键行为锁定(见 tests/chat/test_logic.py):
- should_skip: 单意图或全部独立意图 → True;多意图含非独立 → False
- plan: LLM 调用 + JSON 解析(无容错)

独立意图集合(Phase 7 重置 — 仅 3 个企业意图):
    hr, devops, faq

依赖注入:
- llm: LangChain ChatModel
- memory: duck-typed(需 .get_short_term_text())
- messages_provider: callable 返回最近一条消息(用于 query 上下文);Phase 1 暂传 list
- prompt: CorpAIPrompts.planning_prompt()(默认)
"""
import json
import re
from typing import Any, Callable

from CorpAI.core.prompts import CorpAIPrompts
from CorpAI.logging import logger
from CorpAI.utils.format import strip_think


# 独立意图集合 — 多意图全在此集合内可跳过 planning
# Phase 7:删除 weather/flight/train/concert/attraction/car_rental/tour_group/insurance/trip_order,
# 这些旅行意图已不在 intent_prompt 列表里,出现时直接由 out_of_scope 处理。
INDEPENDENT_INTENTS = frozenset({
    "hr", "devops", "faq",
})


class TaskPlanner:
    """任务规划器 — 启发式 + LLM plan。

    等价于 ChatService._should_skip_planning + ChatService.planning_agent
    (chat.py:449-520)。
    """

    def __init__(
        self,
        llm: Any,
        memory: Any,
        messages_provider: Callable[[], list],
        prompt: Any = None,
    ):
        """
        参数:
            llm: LangChain ChatModel
            memory: 记忆对象,需 .get_short_term_text()
            messages_provider: 返回最近对话消息列表的 callable
                (chat.py:505 用了 self.messages[-1]["content"])
            prompt: 可选自定义 prompt,默认 CorpAIPrompts.planning_prompt()
        """
        self.llm = llm
        self.memory = memory
        self.messages_provider = messages_provider
        self.prompt = prompt if prompt is not None else CorpAIPrompts.planning_prompt()

    def should_skip(self, intents: list[str]) -> bool:
        """
        启发式判断:是否可以跳过 planning_agent,直接执行。

        完全等价于 ChatService._should_skip_planning(chat.py:449-482)。
        行为锁定(由 tests/chat/test_logic.py::TestShouldSkipPlanning 覆盖):
            1. len(intents) <= 1 → True(包括空、单个 complex/order/out_of_scope/unknown)
            2. 多意图全部 ∈ INDEPENDENT_INTENTS → True
            3. 多意图任一 ∉ INDEPENDENT_INTENTS → False
        """
        # 规则1:单意图直接跳过
        if len(intents) <= 1:
            return True

        # 规则2:多意图但全部为独立查询类,无需分步规划
        for intent in intents:
            if intent not in INDEPENDENT_INTENTS:
                # 存在需要分步的意图(如 order),不跳过
                # TODO 如果大模型认为意图非常复杂,使用 complex。这里命中 False
                return False
        return True

    def plan(self, intents: list[str], user_queries: dict[str, str]) -> dict:
        """
        任务规划 — 调用 LLM 拆解步骤。

        完全等价于 ChatService.planning_agent(chat.py:484-520)。

        返回值:
            dict: 简单任务 → {"need_plan": false, "reason": "...", "steps": []}
                  复杂任务 → {"need_plan": true, "reason": "...", "steps": [{"step": 1, ...}, ...]}
        """
        chain = self.prompt | self.llm

        messages = self.messages_provider()
        planning_response = chain.invoke({
            "conversation_history": self.memory.get_short_term_text(),
            "query": messages[-1]["content"] if messages else "",
            "intents": json.dumps(intents, ensure_ascii=False),
            "user_queries": json.dumps(user_queries, ensure_ascii=False)
        }).content.strip()
        planning_response = strip_think(planning_response)
        logger.info(f"规划响应: {planning_response}")

        # 同 intent_agent:三层 JSON 清理(但本方法无 json 解析失败的容错 — 与原代码一致)
        planning_response = re.sub(r'<think>.*?</think>\s*', '', planning_response, flags=re.DOTALL).strip()
        planning_response = re.sub(r'^```(?:json)?\s*|\s*```$', '', planning_response).strip()
        if not planning_response.startswith('{'):
            match = re.search(r'\{.*\}', planning_response, flags=re.DOTALL)
            if match:
                planning_response = match.group(0)

        # 注意:原代码此处无 try/except,LLM 失败会 raise
        plan = json.loads(planning_response)
        return plan
