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


def _extract_text(task: Task) -> str:
    """从 task.message(dict)里提取文本 — 兼容两种 wire 格式。

    python_a2a 的 Task.message: Optional[Dict[str, Any]] — 永远是 dict。
    两种格式:
      1. Google A2A parts 格式:{"role":"user","parts":[{"type":"text","text":"..."}]}
      2. python_a2a 标准格式:{"role":"user","content":{"type":"text","text":"..."}}
        或 content 是字符串:{"role":"user","content":"..."}
    """
    msg = task.message
    if not msg or not isinstance(msg, dict):
        return ""
    # Google A2A format
    if "parts" in msg and isinstance(msg["parts"], list):
        chunks: list[str] = []
        for part in msg["parts"]:
            if isinstance(part, dict) and part.get("type") == "text":
                chunks.append(part.get("text", ""))
        return "".join(chunks)
    # Standard format
    content = msg.get("content")
    if isinstance(content, dict):
        return content.get("text", "") or ""
    if isinstance(content, str):
        return content
    return ""


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

    def handle_task(self, task: Task) -> Task:
        try:
            text = _extract_text(task)
            if not text.strip():
                return Task(id=task.id, status=TaskStatus(state=TaskState.FAILED, message=task.message))
            response = self._route(text)
            return Task(
                id=task.id,
                status=TaskStatus(state=TaskState.COMPLETED, message=task.message),
                artifacts=[{"parts": [{"type": "text", "text": response}]}],
            )
        except Exception:
            logger.exception("hr_assistant handle_task failed")
            return Task(id=task.id, status=TaskStatus(state=TaskState.FAILED, message=task.message))

    def _route(self, text: str) -> str:
        # 福利类:社保/公积金/体检/团建/设备/培训/餐饮/通讯/benefit
        benefit_keywords = ["福利", "社保", "公积金", "体检", "团建", "设备", "培训",
                            "餐补", "通讯", "benefit", "五险", "六险", "保险方案"]
        # 政策类:假期/出勤/调休/婚产丧/离职/考勤/报销/policy
        policy_keywords = ["政策", "假期", "年假", "病假", "缺勤", "policy",
                           "婚假", "产假", "丧假", "调休", "离职", "考勤", "报销", "陪产"]
        if any(k in text for k in benefit_keywords):
            # 简单按 category 提取
            category = next((kw for kw in ["社保", "公积金", "体检", "团建", "设备",
                                            "培训", "餐饮", "通讯"]
                             if kw in text), None)
            return t.query_benefits(category=category)
        if any(k in text for k in policy_keywords):
            topic = next((kw for kw in ["年假", "病假", "缺勤", "报销", "调休",
                                        "婚假", "产假", "丧假", "离职", "考勤"]
                          if kw in text), "")
            return t.query_policy(topic=topic)
        return json.dumps({
            "status": "no_match",
            "message": "暂不支持该查询。hr_assistant 仅处理员工福利(社保/公积金/体检/团建/设备/培训等)与人事政策(年假/病假/缺勤/报销等)。",
        }, ensure_ascii=False)
