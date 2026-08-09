"""devops_copilot A2A Server v3.0 — 4 真工具 + 2 bridge,显式 not_configured。

删掉所有 in-memory 玩具路由(query_incident 之前的 list_recent/list_open_p0 等,
list_log_sources/search_logs/get_pipeline_stats 等),只留 4 真工具 + 2 bridge。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from devops_copilot import tools as t
from devops_copilot import bridges as b
from devops_copilot.prompts import DEVOPS_LLM_PROMPT
from langchain_openai import ChatOpenAI
from python_a2a import A2AServer, AgentCard, AgentSkill, Task, TaskStatus, TaskState

from CorpAI.config import Config

logger = logging.getLogger(__name__)


def _extract_text(task: Task) -> str:
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


def _extract_team(text: str) -> str:
    """从文本提取 team 关键词。"""
    table = {"数据": "data", "data": "data", "安全": "security", "security": "security",
             "网络": "network", "network": "network", "移动": "mobile", "mobile": "mobile",
             "前端": "frontend", "frontend": "frontend", "devops": "devops", "qa": "qa"}
    for k, v in table.items():
        if k in text.lower() or k in text:
            return v
    return "platform"


class DevopsCopilotServer(A2AServer):
    """v3.0 A2A:4 真工具 + 2 bridge,显式 not_configured。"""

    def __init__(self, llm: ChatOpenAI | None = None):
        card = AgentCard(
            name="devops_copilot",
            description="DevOps 副驾 v3.0 — 4 真工具(Jira/PagerDuty/Prometheus/K8s)+ 2 桥接,无 in-memory 玩具",
            url="http://localhost:5020",
            version="3.0.0",
            skills=[
                AgentSkill(id="query_incident", name="查工单", description="Jira REST API"),
                AgentSkill(id="query_oncall", name="On-call 查询", description="PagerDuty API"),
                AgentSkill(id="query_alert", name="查告警", description="Alertmanager API"),
                AgentSkill(id="get_pod_logs", name="Pod 日志", description="kubernetes-python"),
                # Bridge 2
                AgentSkill(id="cross_check_hr", name="HR 联动", description="请假触发 oncall 备份"),
                AgentSkill(id="cross_query_faq", name="FAQ 兜底", description="SOP 兜底补全"),
            ],
        )
        super().__init__(agent_card=card)
        self.llm = llm or ChatOpenAI(
            model=Config().model_name, api_key=Config().api_key,
            base_url=Config().base_url, temperature=0.1,
        )

    def handle_task(self, task: Task) -> Task:
        try:
            text = _extract_text(task)
            if not text.strip():
                return Task(id=task.id, status=TaskStatus(state=TaskState.FAILED, message=task.message))
            response = self._route(text, task.metadata or {})
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

    def _route(self, text: str, metadata: dict) -> str:
        """v3.0:仅 4 真工具 + 2 bridge 路由。"""
        auth = metadata.get("authorization", "Bearer DEV_TOKEN")

        # ── INC-xxx 显式查询 → Jira ──
        m = re.search(r"\bINC-\d{3}\b", text, re.IGNORECASE)
        if m:
            return t.query_incident(incident_id=m.group(0).upper())

        # ── 工单优先级/状态过滤 → Jira ──
        if any(k in text for k in ["P0工单", "P1工单", "P2工单", "P3工单"]):
            pri = next(p for p in ["P0", "P1", "P2", "P3"] if p + "工单" in text)
            return t.query_incident(priority=pri)
        if "未解决" in text or "打开中" in text or "in_progress" in text or "open" in text:
            return t.query_incident(status="open")
        if "已解决" in text or "resolved" in text:
            return t.query_incident(status="resolved")
        if any(k in text for k in ["工单", "incident"]):
            return t.query_incident(limit=5)

        # ── On-call → PagerDuty ──
        if any(k in text for k in ["oncall", "on-call", "on call", "oncall 团队"]):
            return t.query_oncall(team=_extract_team(text))

        # ── 告警 → Prometheus ──
        if any(k in text for k in ["告警", "alert"]):
            return t.query_alert()

        # ── Pod 日志 → kubernetes-python ──
        if "pod 日志" in text or ("日志" in text and "pod" in text):
            return t.get_pod_logs("payment-api-abc123", "default", tail_lines=50,
                                  authorization=auth)

        # ── Bridge ──
        if "hr 联动" in text or "hr 检查" in text:
            return b.cross_check_hr(authorization=auth, request_id="L-UNKNOWN")
        if "faq 兜底" in text or "faq 补全" in text:
            return b.cross_query_faq(query=text, top_k=2)

        return json.dumps({
            "status": "no_match",
            "message": ("暂不支持该查询。devops_copilot 处理:"
                       "工单(Jira)/ On-call(PagerDuty)/ 告警(Prometheus)/ Pod 日志(K8s)/ 跨插件桥接。"),
        }, ensure_ascii=False)