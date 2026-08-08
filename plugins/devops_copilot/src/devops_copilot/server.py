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


def _extract_text(task: Task) -> str:
    """从 task.message(dict)里提取文本 — 兼容 Google A2A parts + 标准 content 两种 wire 格式。"""
    msg = task.message
    if not msg or not isinstance(msg, dict):
        return ""
    if "parts" in msg and isinstance(msg["parts"], list):
        chunks: list[str] = []
        for part in msg["parts"]:
            if isinstance(part, dict) and part.get("type") == "text":
                chunks.append(part.get("text", ""))
        return "".join(chunks)
    content = msg.get("content")
    if isinstance(content, dict):
        return content.get("text", "") or ""
    if isinstance(content, str):
        return content
    return ""


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

    def handle_task(self, task: Task) -> Task:
        try:
            text = _extract_text(task)
            if not text.strip():
                return Task(id=task.id, status=TaskStatus(state=TaskState.FAILED, message=task.message))
            response = self._route(task.id, text, task.metadata or {})
            return Task(
                id=task.id,
                status=TaskStatus(state=TaskState.COMPLETED, message=task.message),
                artifacts=[{"parts": [{"type": "text", "text": response}]}],
            )
        except Exception as exc:
            logger.exception("devops_copilot handle_task failed")
            return Task(
                id=task.id,
                status=TaskStatus(state=TaskState.FAILED, message=task.message),
                artifacts=[{"parts": [{"type": "text", "text": f"错误:{exc}"}]}],
            )

    def _route(self, task_id: str, text: str, metadata: dict) -> str:
        """关键词路由:
        - INC-xxx / 工单状态 / 列出最近工单 → query_incident 或 list_recent_incidents
        - oncall / on-call / 联系 → query_oncall
        - pod / restart / 重启 → restart_pod (需 devops:write scope)
        """
        # INC- 显式 ID 查询
        import re
        m = re.search(r"\bINC-\d{3}\b", text, re.IGNORECASE)
        if m:
            return t.query_incident(incident_id=m.group(0).upper())
        # 按状态/优先级过滤
        if any(k in text for k in ["P0工单", "P1工单", "P2工单", "P3工单"]):
            pri = next(p for p in ["P0", "P1", "P2", "P3"] if p + "工单" in text)
            return t.query_incident(priority=pri)
        if any(k in text for k in ["未解决", "打开中", "in_progress", "open"]):
            return t.query_incident(status="open")
        if any(k in text for k in ["最近", "工单列表", "所有工单"]):
            return t.list_recent_incidents(limit=8)
        if any(k in text for k in ["工单", "incident"]):
            return t.query_incident(limit=5)
        # on-call 查询(支持 team 关键词)
        if any(k in text for k in ["oncall", "on-call", "联系", "on call"]):
            team = "platform"
            for t_name in ["security", "数据", "data", "网络", "network"]:
                if t_name in text.lower() or t_name in text:
                    team = {"数据": "data", "data": "data", "安全": "security",
                            "security": "security", "网络": "network", "network": "network"}[t_name]
                    break
            return t.query_oncall(team=team)
        if any(k in text for k in ["pod", "restart", "重启"]):
            # Phase 5:RBAC 校验,authorization 从 task metadata 传过来
            auth = metadata.get("authorization")
            try:
                return t.restart_pod("payment-api-abc123", "default", authorization=auth)
            except PermissionError as exc:
                return json.dumps({"status": "deny", "reason": str(exc)}, ensure_ascii=False)
        return json.dumps({
            "status": "no_match",
            "message": "暂不支持该查询。devops_copilot 仅处理工单查询、On-call 联系、K8s Pod 重启。",
        }, ensure_ascii=False)
