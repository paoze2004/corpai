"""
ReAct 执行模块 — Phase 1 拆分自 chat.py:619-714(react_loop + execute_step)。

关键行为锁定(由 _4_tests/platform/test_react_loop.py 验证):
1. execute_step: 提取 intent + query_str,委托给外部 step_executor
2. react_loop: 按 depends_on 分组 + 组内并行(asyncio.gather) + 汇总
3. 异常处理:return_exceptions=True → 转为 "执行失败：{exc}"
4. 多步骤汇总用 react_summary_prompt;单步直接返回 observation

依赖注入:
- llm: LangChain ChatModel(用于多步骤汇总)
- step_executor: async callable(intent, query_str) → str
    Phase 1.6 时由 service.py 注入具体的 _call_agent_intent wrapper
- messages_provider: Callable[[], list] — 提供最近对话消息(用于汇总 prompt 的 query)
- summary_prompt: CorpAIPrompts.react_summary_prompt()(默认)

注:`messages_provider` 与 TaskPlanner 共享一个概念,Phase 1.6 整合到 service.py 统一注入。
"""
import asyncio
from collections import OrderedDict
from typing import Any, Awaitable, Callable

from _0_CorpAI._1_core.prompts import CorpAIPrompts
from _0_CorpAI.logging import logger
from _0_CorpAI._3_utils.format import strip_think

# step_executor 类型: async (intent: str, query_str: str) -> str
StepExecutor = Callable[[str, str], Awaitable[str]]


class ReActRunner:
    """ReAct 执行器 — 计划步骤执行与汇总。

    等价于 ChatService.execute_step + ChatService.react_loop(chat.py:619-714)。
    """

    def __init__(
        self,
        llm: Any,
        step_executor: StepExecutor,
        messages_provider: Callable[[], list],
        summary_prompt: Any = None,
    ):
        """
        参数:
            llm: LangChain ChatModel(用于 react_summary_prompt)
            step_executor: async callable(intent, query_str) → observation string
            messages_provider: 返回最近对话消息列表的 callable(用于汇总 prompt)
            summary_prompt: 可选自定义汇总 prompt,默认 react_summary_prompt()
        """
        self.llm = llm
        self.step_executor = step_executor
        self.messages_provider = messages_provider
        self.summary_prompt = summary_prompt if summary_prompt is not None else CorpAIPrompts.react_summary_prompt()

    async def execute_step(self, step: dict, user_queries: dict) -> str:
        """
        执行单个计划步骤。

        完全等价于 ChatService.execute_step(chat.py:619-641)。
        """
        intent = step.get("intent", "")
        # 优先从 user_queries 获取改写后的查询
        # 注意:原代码 fallback 到 self.messages[-1]["content"];这里 messages_provider 提供
        messages = self.messages_provider()
        fallback_query = messages[-1]["content"] if messages else ""
        query_str = user_queries.get(intent, fallback_query)
        logger.info(f"执行步骤:{step.get('action', '')},意图:{intent}")
        return await self.step_executor(intent, query_str)

    async def run(self, steps: list[dict], user_queries: dict[str, str]) -> str:
        """
        ReAct 循环:按规划步骤逐步执行,跳过 Thought 推理。

        完全等价于 ChatService.react_loop(chat.py:643-714)。

        流程:
            1. 按 depends_on 分组(OrderedDict 保持插入顺序)
            2. 组内并行(asyncio.gather + return_exceptions)
            3. 单组 → 直接 await(无 return_exceptions 包装)
            4. 多步骤 → 调 react_summary_prompt 汇总;单步 → 直接返回 observation
        """
        observations: list[str] = []
        step_results: list[dict] = []

        # 按依赖分组
        dep_groups: OrderedDict[Any, list[dict]] = OrderedDict()
        for step in steps:
            dep = step.get("depends_on", 0)
            dep_groups.setdefault(dep, []).append(step)

        # 逐组执行
        for dep_key, group_steps in dep_groups.items():
            if len(group_steps) > 1:
                logger.info(f"并行执行 {len(group_steps)} 个无依赖步骤")
                tasks = [self.execute_step(s, user_queries) for s in group_steps]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for step, result in zip(group_steps, results):
                    step_num = step.get("step", 0)
                    step_desc = step.get("description", step.get("action", ""))
                    if isinstance(result, Exception):
                        result = f"执行失败:{result}"
                    observations.append(result)
                    step_results.append({"step": step_num, "description": step_desc, "result": result})
                    logger.info(f"ReAct 步骤 {step_num} 结果: {result[:100]}...")
            else:
                step = group_steps[0]
                step_num = step.get("step", 0)
                step_desc = step.get("description", step.get("action", ""))
                result = await self.execute_step(step, user_queries)
                observations.append(result)
                step_results.append({"step": step_num, "description": step_desc, "result": result})
                logger.info(f"ReAct 步骤 {step_num} 结果: {result[:100]}...")

        # 最终汇总
        if len(step_results) > 1:
            summary_chain = self.summary_prompt | self.llm
            all_obs = "\n".join([
                f"步骤{s['step']} ({s['description']}): {s['result']}" for s in step_results
            ])
            messages = self.messages_provider()
            query = messages[-1]["content"] if messages else ""
            final_response = (await summary_chain.ainvoke({
                "query": query,
                "all_observations": all_obs
            })).content.strip()
            final_response = strip_think(final_response)
        else:
            final_response = observations[0] if observations else "暂无结果"

        return final_response
