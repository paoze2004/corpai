"""devops_copilot plugin A2A Server — Phase 5 简化版(RBAC showcase)。"""
from __future__ import annotations

import json
import logging
from typing import Any

from devops_copilot import tools as t
from devops_copilot.prompts import DEVOPS_LLM_PROMPT
from langchain_openai import ChatOpenAI
from python_a2a import A2AServer, AgentCard, AgentSkill, Task, TaskStatus, TaskState, TextContent

from CorpAI.config import Config

logger = logging.getLogger(__name__)


class DevopsCopilotServer(A2AServer):
    """Phase 5 简化版 A2A:关键词路由 + 工具调用。

    restart_pod 是 RBAC showcase:必须 devops:write scope 才允许。
    """

    def __init__(self, llm: ChatOpenAI | None = None):
        card = AgentCard(
            name="devops_copilot",
            description="DevOps 副驾 — 工单查询 + On-call 联系 + Pod 重启(dry_run)",
            url="http://localhost:5020",
            version="1.0.0",
            skills=[
                AgentSkill(id="incident", name="工单查询", description="查工单状态"),
                AgentSkill(id="oncall", name="On-call 查询", description="查 on-call 联系信息"),
                AgentSkill(id="k8s", name="K8s Pod 重启", description="重启 Pod,需 devops:write scope"),
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
            text = ""
            if task.message and task.message.parts:
                for part in task.message.parts:
                    if isinstance(part, TextContent):
                        text += part.text
            if not text.strip():
                return Task(id=task.id, status=TaskStatus(state=TaskState.FAILED, message=task.message))
            response = self._route(task.id, text, task.metadata or {})
            return Task(
                id=task.id,
                status=TaskStatus(
                    state=TaskState.COMPLETED,
                    message=task.message,
                    artifacts=[{"parts": [{"type": "text", "text": response}]}],
                ),
            )
        except Exception as exc:
            logger.exception("devops_copilot handle_task failed")
            return Task(
                id=task.id,
                status=TaskStatus(state=TaskState.FAILED, message=task.message),
                artifacts=[{"parts": [{"type": "text", "text": f"错误:{exc}"}]}],
            )

    def _route(self, task_id: str, text: str, metadata: dict) -> str:
        """关键词路由:incident → query_incident;oncall → query_oncall;pod/restart → restart_pod。"""
        if any(k in text for k in ["工单", "incident", "INC"]):
            return t.query_incident()
        if any(k in text for k in ["oncall", "on-call", "联系"]):
            return t.query_oncall("platform")
        if any(k in text for k in ["pod", "restart", "重启"]):
            # Phase 5:RBAC 校验,authorization 从 task metadata 传过来
            auth = metadata.get("authorization")
            try:
                return t.restart_pod("payment-api-abc123", "default", authorization=auth)
            except PermissionError as exc:
                return json.dumps({"status": "deny", "reason": str(exc)}, ensure_ascii=False)
        return json.dumps({"status": "no_match", "message": "暂不支持该查询(devops_copilot Phase 5 简化版)。"}, ensure_ascii=False)
