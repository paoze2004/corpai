"""
OrchestratorService — 调度核心(ADR-004 唯一 high-level 入口)。

设计原则:
- OrchestratorService 是唯一 high-level 入口(api/app.py 直接消费)
- 不直接调 LLM/Agent/A2A,只协调 5 个模块
- 模块边界严格(intent/planner/react_loop/streaming/外部 step_executor)
- DI 注入所有依赖(不依赖全局 config)
- 业务接线(A2A 网络 / ChatOpenAI / DB 加载)在 platform/wiring.py 组合根

依赖注入:
- intent: IntentRecognizer(意图识别)
- planner: TaskPlanner(skip heuristic + plan)
- react_runner: ReActRunner(ReAct 执行 + 汇总)
- simple_step_executor: async (intent, query_str) → str
    单步执行(由 wiring.py 提供 closure,Phase 7 起 plugin manifest 优先)
- memory: 任何 duck-typed(add_message / get_short_term_text / ...)
- agent_card_provider: 可选 Callable[[], list[dict]],由 wiring.py 注入真实 A2A provider

Phase 7:移除 attraction_executor(旅行 plugin 已删,不再有"景点推荐"直答路径)。

App 兼容门面(Phase 1.7 从 ChatService 迁移过来):
- get_memory_state / clear_memory / update_user_profile:委托给 self.memory
- get_agent_cards:委托给注入的 provider
"""
import json
from typing import Any, Awaitable, Callable

from CorpAI.logging import logger
from CorpAI.platform.observability.trace import start_span
from CorpAI.platform.orchestrator.intent import IntentRecognizer
from CorpAI.platform.orchestrator.planner import TaskPlanner
from CorpAI.platform.orchestrator.react_loop import ReActRunner


# 类型别名
SimpleStepExecutor = Callable[[str, str], Awaitable[str]]
# A2A Agent Card 同步供应者 — 由 wiring.py 注入,OrchestratorService 不直接持有 AgentNetwork
AgentCardProvider = Callable[[], list[dict]]


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
        memory: Any,
        agent_card_provider: AgentCardProvider | None = None,
    ):
        """
        参数:
            intent: IntentRecognizer 实例
            planner: TaskPlanner 实例
            react_runner: ReActRunner 实例
            simple_step_executor: async (intent, query_str) → str
                单步执行(由 ToolsGateway 或 ChatService._call_agent_intent 实现)
            memory: 记忆对象,需 .add_message() / .get_short_term_text()
            agent_card_provider: 可选,返回 A2A Agent Card 列表的同步 callable
                (Phase 1.7 用,Phase 3 替换为 ToolsGateway 提供者)。未注入时空列表。
        """
        self.intent = intent
        self.planner = planner
        self.react_runner = react_runner
        self.simple_step_executor = simple_step_executor
        self.memory = memory
        # agent_card_provider 注入;未注入 → 空列表,API 层调用 get_agent_cards() 返回 []
        self._agent_card_provider: AgentCardProvider = (
            agent_card_provider if agent_card_provider is not None else (lambda: [])
        )

    # ════════════════════════════════════════════════════════════════
    # App 兼容门面(Phase 1.7,从 ChatService 搬过来)
    # — api/app.py 的 4 个非 chat 端点(get/clear/update/get_cards)
    # — 这些方法名/签名与原 ChatService 完全一致,零行为变化
    # ════════════════════════════════════════════════════════════════
    def get_memory_state(self) -> dict:
        """
        获取当前记忆状态摘要(短期消息/偏好/任务/实体历史)。

        等价于 ChatService.get_memory_state(原 core/chat.py:834-853)。
        """
        return {
            "short_term_messages": [
                {
                    "role": "用户" if m["role"] == "user" else "助手",
                    "content": m["content"],
                    "timestamp": m["timestamp"],
                }
                for m in self.memory.short_term_messages[-5:]
            ],
            "user_profile": self.memory.user_profile,
            "current_task": self.memory.current_task,
            "entity_history": self.memory.entity_history[-5:],
        }

    def clear_memory(self) -> None:
        """
        清空所有记忆(短期/偏好/任务/实体,含 DB 三张表)。

        等价于 ChatService.clear_memory(原 core/chat.py:855-864)。
        原代码中 self.messages.clear() / self.conversation_history reset 不再需要
        (OrchestratorService 不再维护这两份冗余状态,内存里只有 self.memory)。
        """
        self.memory.clear()

    def update_user_profile(self, profile: dict) -> None:
        """
        合并更新用户偏好(新增/覆盖,不删除已有项),持久化到 DB。

        等价于 ChatService.update_user_profile(原 core/chat.py:420-429)。
        """
        self.memory.update_profile(profile)
        logger.info(f"更新用户偏好: {profile}")

    def get_agent_cards(self) -> list[dict]:
        """
        获取 A2A 代理卡片列表(name/skills/description/url/status)。

        等价于 ChatService.get_agent_cards(原 core/chat.py:803-832)。
        数据由 wiring.py 注入的 provider 提供;未注入时返回 []。
        """
        return self._agent_card_provider()

    # ════════════════════════════════════════════════════════════════
    # chat() — 非流式入口
    # ════════════════════════════════════════════════════════════════
    async def chat(self, user_input: str) -> str:
        """
        处理用户输入,返回完整回复。

        完全等价于 ChatService.chat(chat.py:716-813)。

        Phase 4:整个 chat() 包在 start_span("chat") 里 — 落 call_records,
        metrics 通过 LLM/A2A spans 自动累计,trace_id 由 HTTP middleware 注入。
        """
        # 记录用户消息
        with start_span("chat", {"input_len": len(user_input), "mode": "sync"}) as span:
            self.memory.add_message("user", user_input)

            try:
                # 1. 意图识别
                intents, user_queries, follow_up_message = self.intent.extract(user_input)
                span.set_attr("intents", intents)

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
                            result = await self.simple_step_executor(intent, query_str)
                            responses.append(result)
                        response = "\n\n".join(responses)

                # 5. 记录助手回复
                self.memory.add_message("assistant", response)
                return response

            except json.JSONDecodeError as e:
                logger.error(f"意图识别JSON解析失败")
                span.end_err(f"json_decode: {e}")
                error_message = f"意图识别JSON解析失败:{str(e)}。请重试。"
                self.memory.add_message("assistant", error_message)
                return error_message
            except Exception as e:
                logger.error(f"处理异常: {str(e)}")
                span.end_err(str(e))
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
        """流式单 intent 执行 — 全部走 simple_step_executor。

        注:Phase 1.6 简化版,直接 yield 完整结果(无 token-level streaming)。
        Phase 4+ 才引入真正的 token streaming(ADR-008)。
        """
        result = await self.simple_step_executor(intent, query_str)
        yield result

    async def _react_loop_stream(self, steps: list[dict], user_queries: dict[str, str]):
        """流式 ReAct — 简化版:先 await run,再 yield 整个结果。

        Phase 4+ 才引入真正的 token streaming。
        """
        result = await self.react_runner.run(steps, user_queries)
        yield result
