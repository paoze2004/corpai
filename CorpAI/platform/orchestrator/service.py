"""
OrchestratorService — 调度核心(Phase 1.6 唯一协调器)。

设计原则(ADR-004):
- OrchestratorService 是唯一 high-level 入口
- 不直接调 LLM/Agent,只协调 5 个模块
- 模块边界严格(intent/planner/react_loop/streaming/外部 step_executor)
- DI 注入所有依赖(不依赖全局 config)

依赖注入:
- intent: IntentRecognizer(意图识别)
- planner: TaskPlanner(skip heuristic + plan)
- react_runner: ReActRunner(ReAct 执行 + 汇总)
- simple_step_executor: async (intent, query_str) → str
    简单路径上,单步执行 callable(由 Phase 1.7 chat.py alias 提供具体实现)
- attraction_executor: async (query_str) → str
    attraction 意图不走 A2A,直接调 LLM(由 Phase 1.7 提供)
- memory: 任何 duck-typed(add_message / get_short_term_text / ...)

未来扩展(Phase 2+):
- memory: 替换为 MemoryGateway(per-user scoping)
- simple_step_executor: 替换为 ToolsGateway(插件化)

chat() 与 chat_stream() 行为:
- 等价于 ChatService.chat + ChatService.chat_stream(chat.py:716-953)
- intent → planner → execute → memory 写入 → 返回
"""
import json
from typing import Any, Awaitable, Callable

from CorpAI.logging import logger
from CorpAI.platform.orchestrator.intent import IntentRecognizer
from CorpAI.platform.orchestrator.planner import TaskPlanner
from CorpAI.platform.orchestrator.react_loop import ReActRunner


# 类型别名
SimpleStepExecutor = Callable[[str, str], Awaitable[str]]
AttractionExecutor = Callable[[str], Awaitable[str]]


class OrchestratorService:
    """调度核心 — 唯一 high-level 入口。

    等价于 ChatService.chat + ChatService.chat_stream(chat.py:716-953),
    但不再直接调 A2A / LLM,全部通过 DI 注入。
    """

    def __init__(
        self,
        intent: IntentRecognizer,
        planner: TaskPlanner,
        react_runner: ReActRunner,
        simple_step_executor: SimpleStepExecutor,
        attraction_executor: AttractionExecutor,
        memory: Any,
    ):
        """
        参数:
            intent: IntentRecognizer 实例
            planner: TaskPlanner 实例
            react_runner: ReActRunner 实例
            simple_step_executor: async (intent, query_str) → str
                处理非 attraction 的单步执行(由 ToolsGateway 或 ChatService._call_agent_intent 实现)
            attraction_executor: async (query_str) → str
                attraction 意图直接调 LLM 生成推荐(不走 A2A)
            memory: 记忆对象,需 .add_message() / .get_short_term_text()
        """
        self.intent = intent
        self.planner = planner
        self.react_runner = react_runner
        self.simple_step_executor = simple_step_executor
        self.attraction_executor = attraction_executor
        self.memory = memory

    # ════════════════════════════════════════════════════════════════
    # chat() — 非流式入口
    # ════════════════════════════════════════════════════════════════
    async def chat(self, user_input: str) -> str:
        """
        处理用户输入,返回完整回复。

        完全等价于 ChatService.chat(chat.py:716-813)。
        """
        # 记录用户消息
        self.memory.add_message("user", user_input)

        try:
            # 1. 意图识别
            intents, user_queries, follow_up_message = self.intent.extract(user_input)

            # 2. 处理特殊情况
            if "out_of_scope" in intents:
                response = follow_up_message
            elif follow_up_message != "":
                response = follow_up_message
            else:
                # 3. 任务规划(启发式跳过)
                if self.planner.should_skip(intents):
                    plan = {"need_plan": False, "reason": "启发式判断:任务简单,可直接执行", "steps": []}
                    logger.info(f"跳过规划: {plan['reason']}")
                else:
                    plan = self.planner.plan(intents, user_queries)
                need_plan = plan.get("need_plan", False)
                logger.info(f"规划结果: need_plan={need_plan}, reason={plan.get('reason', '')}")

                # 4. 执行
                if need_plan:
                    steps = plan.get("steps", [])
                    response = await self.react_runner.run(steps, user_queries)
                else:
                    # 简单任务:逐个 intent 串行执行
                    responses: list[str] = []
                    for intent in intents:
                        logger.info(f"处理意图:{intent}")
                        query_str = user_queries.get(intent, "")
                        if intent == "attraction":
                            result = await self.attraction_executor(query_str)
                        else:
                            result = await self.simple_step_executor(intent, query_str)
                        responses.append(result)
                    response = "\n\n".join(responses)

            # 5. 记录助手回复
            self.memory.add_message("assistant", response)
            return response

        except json.JSONDecodeError as e:
            logger.error(f"意图识别JSON解析失败")
            error_message = f"意图识别JSON解析失败:{str(e)}。请重试。"
            self.memory.add_message("assistant", error_message)
            return error_message
        except Exception as e:
            logger.error(f"处理异常: {str(e)}")
            error_message = f"处理失败:{str(e)}。请重试。"
            self.memory.add_message("assistant", error_message)
            return error_message

    # ════════════════════════════════════════════════════════════════
    # chat_stream() — 流式入口
    # ════════════════════════════════════════════════════════════════
    async def chat_stream(self, user_input: str):
        """
        流式处理用户输入,逐 chunk yield 文本。

        完全等价于 ChatService.chat_stream(chat.py:878-953)。
        """
        self.memory.add_message("user", user_input)

        try:
            # 1. 意图识别(同步,无流式)
            intents, user_queries, follow_up_message = self.intent.extract(user_input)

            # 2. 特殊情况
            if "out_of_scope" in intents:
                response = follow_up_message
                yield response
            elif follow_up_message != "":
                response = follow_up_message
                yield response
            else:
                # 3. 任务规划
                if self.planner.should_skip(intents):
                    plan = {"need_plan": False, "reason": "启发式判断:任务简单,stream 路径", "steps": []}
                    logger.info(f"跳过规划(stream): {plan['reason']}")
                else:
                    plan = self.planner.plan(intents, user_queries)
                need_plan = plan.get("need_plan", False)
                logger.info(f"规划结果(stream): need_plan={need_plan}, reason={plan.get('reason', '')}")

                # 4. 执行
                if need_plan:
                    steps = plan.get("steps", [])
                    parts: list[str] = []
                    async for chunk in self._react_loop_stream(steps, user_queries):
                        parts.append(chunk)
                        yield chunk
                    response = "".join(parts)
                else:
                    responses: list[str] = []
                    for intent in intents:
                        logger.info(f"处理意图(stream):{intent}")
                        query_str = user_queries.get(intent, "")
                        parts = []
                        async for chunk in self._call_agent_intent_stream(intent, query_str):
                            parts.append(chunk)
                            yield chunk
                        responses.append("".join(parts))
                    response = "\n\n".join(responses)

            self.memory.add_message("assistant", response)

        except json.JSONDecodeError as e:
            logger.error(f"意图识别JSON解析失败")
            error_message = f"意图识别JSON解析失败:{str(e)}。请重试。"
            self.memory.add_message("assistant", error_message)
            yield error_message
        except Exception as e:
            logger.error(f"处理异常: {str(e)}")
            error_message = f"处理失败:{str(e)}。请重试。"
            self.memory.add_message("assistant", error_message)
            yield error_message

    # ════════════════════════════════════════════════════════════════
    # 流式内部辅助(从 chat.py:955-1063 简化)
    # ════════════════════════════════════════════════════════════════
    async def _call_agent_intent_stream(self, intent: str, query_str: str):
        """流式单 intent 执行 — attraction 走 attraction_executor,其他走 simple_step_executor。

        注:Phase 1.6 简化版,直接 yield 完整结果(无 token-level streaming)。
        Phase 4+ 才引入真正的 token streaming(ADR-008)。
        """
        if intent == "attraction":
            result = await self.attraction_executor(query_str)
            yield result
        else:
            result = await self.simple_step_executor(intent, query_str)
            yield result

    async def _react_loop_stream(self, steps: list[dict], user_queries: dict[str, str]):
        """流式 ReAct — 简化版:先 await run,再 yield 整个结果。

        Phase 4+ 才引入真正的 token streaming。
        """
        result = await self.react_runner.run(steps, user_queries)
        yield result
