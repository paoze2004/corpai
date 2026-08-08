"""hr_assistant plugin A2A Server — Phase 5 简化版。"""
from __future__ import annotations

import json
import logging
from typing import Any

from hr_assistant import tools as t
from hr_assistant.prompts import HR_ASSISTANT_LLM_PROMPT
from langchain_openai import ChatOpenAI
from python_a2a import A2AServer, AgentCard, AgentSkill, Task, TaskStatus, TaskState

from CorpAI.config import Config

logger = logging.getLogger(__name__)


class HrAssistantServer(A2AServer):
    """Phase 5 简化版 A2A:关键词路由 + 工具调用,不走 LangChain tool_calling。"""

    def __init__(self, llm: ChatOpenAI | None = None):
        card = AgentCard(
            name="hr_assistant",
            description="HR 助手 — 保险方案比较 + 假期政策 + 缺勤申报",
            url="http://localhost:5010",
            version="1.0.0",
            skills=[
                AgentSkill(id="insurance", name="保险查询", description="查保险产品"),
                AgentSkill(id="policy", name="政策查询", description="查 HR 政策 KB"),
            ],
        )
        super().__init__(agent_card=card)
        self.llm = llm or ChatOpenAI(
            model=Config().model_name,
            api_key=Config().api_key,
            base_url=Config().base_url,
            temperature=0.1,
        )

    async def handle_task(self, task: Task) -> Task:
        try:
            from python_a2a import TextContent
            text = ""
            if task.message and task.message.parts:
                for part in task.message.parts:
                    if isinstance(part, TextContent):
                        text += part.text
            if not text.strip():
                return Task(id=task.id, status=TaskStatus(state=TaskState.FAILED, message=task.message))
            response = self._route(text)
            return Task(
                id=task.id,
                status=TaskStatus(
                    state=TaskState.COMPLETED,
                    message=task.message,
                    artifacts=[{"parts": [{"type": "text", "text": response}]}],
                ),
            )
        except Exception:
            logger.exception("hr_assistant handle_task failed")
            return Task(id=task.id, status=TaskStatus(state=TaskState.FAILED, message=task.message))

    def _route(self, text: str) -> str:
        if any(k in text for k in ["保险", "意外", "医疗", "insurance"]):
            return t.query_insurance(insurance_type="全部")
        if any(k in text for k in ["政策", "假期", "年假", "病假", "缺勤", "policy"]):
            return t.query_policy(topic="")
        return json.dumps({"status": "no_match", "message": "暂不支持该查询(hr_assistant Phase 5 简化版)。"}, ensure_ascii=False)
