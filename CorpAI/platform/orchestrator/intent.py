"""
意图识别模块 — Phase 1 拆分自 chat.py:378-447 intent_agent。

关键行为锁定(见 tests/chat/test_logic.py):
1. 用 LLM 调用 CorpAIPrompts.intent_prompt() 链
2. 三层 JSON 清理(strip_think + 去 fences + 贪婪抽取 {})
3. 容错:json.loads 失败返回 ([], {}, fallback_message)

未来扩展(ADR-008):
- extract_stream: 流式输出 intent JSON tokens

依赖注入:
- llm: LangChain ChatModel
- memory: 任何 duck-typed 对象(需 .get_short_term_text() / .get_profile_text() / .current_task)
- prompt: CorpAIPrompts.intent_prompt() 的 ChatPromptTemplate

注:Phase 1 仅做"只搬不改"。Phase 2+ 才换 memory 接口为 MemoryGateway。
"""
import json
import re
from datetime import datetime
from typing import Any

import pytz

from CorpAI.core.prompts import CorpAIPrompts
from CorpAI.logging import logger
from CorpAI.utils.format import strip_think


class IntentRecognizer:
    """意图识别器 — 从用户输入抽取 (intents, user_queries, follow_up_message)。

    等价于 ChatService.intent_agent(chat.py:378-447)。
    """

    def __init__(self, llm: Any, memory: Any, prompt: Any = None):
        """
        参数:
            llm: LangChain ChatModel 实例(ChatOpenAI 等)
            memory: 记忆对象,需有 .get_short_term_text() / .get_profile_text() / .current_task
            prompt: 可选自定义 prompt,默认 CorpAIPrompts.intent_prompt()
        """
        self.llm = llm
        self.memory = memory
        self.prompt = prompt if prompt is not None else CorpAIPrompts.intent_prompt()

    def extract(self, user_input: str) -> tuple[list[str], dict[str, str], str]:
        """
        意图识别 — 输入用户查询,输出 (intents, user_queries, follow_up_message)。

        完全等价于 ChatService.intent_agent(chat.py:378-447)。
        """
        # 组装 Prompt 模板 + 大模型
        chain = self.prompt | self.llm

        # 获取当前日期(Asia/Shanghai 时区)
        current_date = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')

        # 调用大模型
        intent_response = chain.invoke({
            "conversation_history": self.memory.get_short_term_text(),
            "query": user_input,
            "current_date": current_date,
            "user_profile": self.memory.get_profile_text(),
            "task_context": json.dumps(self.memory.current_task, ensure_ascii=False)
        }).content.strip()

        intent_response = strip_think(intent_response)
        logger.info(f"意图识别原始响应: {intent_response}")

        # 清理 LLM 返回的非 JSON 噪音
        # 1) <think>...</think>
        # 2) ```json ... ``` fences
        # 3) 兜底:第一个 {.*} 子串
        intent_response = re.sub(r'<think>.*?</think>\s*', '', intent_response, flags=re.DOTALL).strip()
        intent_response = re.sub(r'^```(?:json)?\s*|\s*```$', '', intent_response).strip()
        if not intent_response.startswith('{'):
            match = re.search(r'\{.*\}', intent_response, flags=re.DOTALL)
            if match:
                intent_response = match.group(0)
        logger.info(f"清理后响应: {intent_response}")

        # 解析 JSON
        try:
            intent_output = json.loads(intent_response)
            intents = intent_output.get("intents", [])
            user_queries = intent_output.get("user_queries", {})
            follow_up_message = intent_output.get("follow_up_message", "")
            logger.info(f"intents: {intents}||user_queries: {user_queries}||follow_up_message: {follow_up_message} ")
            return intents, user_queries, follow_up_message
        except json.JSONDecodeError:
            # 兜底:LLM 偶发输出非 JSON,整段当 follow_up_message
            logger.warning(f"意图识别未返回 JSON,按普通回复处理: {intent_response[:200]}")
            return [], {}, intent_response.strip() or "抱歉,我没能理解您的意思,请换个说法试试。"
