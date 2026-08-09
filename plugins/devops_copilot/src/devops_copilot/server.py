"""devops_copilot A2A Server v3.0 — 35+ 工具路由 + bridge。"""
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
    """v3.0 A2A:35+ 工具 + 2 bridge,关键词路由。"""

    def __init__(self, llm: ChatOpenAI | None = None):
        card = AgentCard(
            name="devops_copilot",
            description="DevOps 副驾 v3.0 — incident(10)+ oncall(8)+ k8s(5)+ monitoring(6)+ cicd(4)+ logs(4)+ bridge(2)",
            url="http://localhost:5020",
            version="3.0.0",
            skills=[
                # Incident 10
                AgentSkill(id="query_incident", name="查工单", description="按 id/status/priority/team 过滤"),
                AgentSkill(id="list_recent_incidents", name="最近工单", description="按更新时间倒序"),
                AgentSkill(id="list_open_p0_incidents", name="P0 工单", description="P0 级未关闭"),
                AgentSkill(id="get_incident_stats", name="工单统计", description="按 status/priority/team"),
                AgentSkill(id="search_incidents_by_keyword", name="关键词搜工单", description="title+description"),
                AgentSkill(id="get_team_workload", name="团队负载", description="assignee 在处理数"),
                AgentSkill(id="create_incident", name="创建工单", description="需 devops:write"),
                AgentSkill(id="assign_incident", name="分配工单", description="需 devops:write"),
                AgentSkill(id="resolve_incident", name="关闭工单", description="需 devops:write"),
                AgentSkill(id="escalate_incident", name="升级工单", description="改优先级,需 devops:write"),
                # Oncall 8
                AgentSkill(id="query_oncall", name="On-call 查询", description="按 team"),
                AgentSkill(id="list_oncall_teams", name="On-call 团队列表", description=""),
                AgentSkill(id="get_primary_oncall", name="主 On-call", description="只看 primary"),
                AgentSkill(id="rotate_oncall", name="On-call 切班", description="需 devops:write"),
                AgentSkill(id="list_all_oncall_contacts", name="全部 On-call", description="扁平表"),
                AgentSkill(id="find_oncall_by_name", name="按名字反查", description=""),
                AgentSkill(id="get_rotation_schedule", name="排班周期", description=""),
                AgentSkill(id="page_oncall", name="呼叫 On-call", description="需 devops:write"),
                # K8s 5
                AgentSkill(id="restart_pod", name="重启 Pod", description="dry_run 默认,需 devops:write"),
                AgentSkill(id="rollback_deployment", name="回滚 Deployment", description="需 devops:write"),
                AgentSkill(id="scale_deployment", name="扩缩容", description="需 devops:write"),
                AgentSkill(id="get_pod_logs", name="Pod 日志", description="需 devops:read"),
                AgentSkill(id="cordon_node", name="Cordon Node", description="禁止调度,需 devops:write"),
                # 监控告警 6
                AgentSkill(id="query_alert", name="查告警", description="按 id/severity/service"),
                AgentSkill(id="list_firing_alerts", name="Firing 告警", description=""),
                AgentSkill(id="list_critical_alerts", name="Critical 告警", description=""),
                AgentSkill(id="get_service_health", name="服务健康", description="告警+工单摘要"),
                AgentSkill(id="silence_alert", name="静音告警", description="需 devops:write"),
                AgentSkill(id="get_alert_stats", name="告警统计", description="按 severity/state/service"),
                # CI/CD 4
                AgentSkill(id="query_pipeline", name="查流水线", description="按 id/status/branch"),
                AgentSkill(id="list_failed_pipelines", name="失败流水线", description=""),
                AgentSkill(id="trigger_pipeline", name="触发流水线", description="需 devops:write"),
                AgentSkill(id="get_pipeline_stats", name="流水线统计", description="成功率+平均时长"),
                # 日志 4
                AgentSkill(id="query_log_source", name="查日志源", description="host/index/retention"),
                AgentSkill(id="list_log_sources", name="日志源列表", description=""),
                AgentSkill(id="search_logs", name="日志检索", description="ES query string"),
                AgentSkill(id="get_log_retention_policy", name="日志保留策略", description=""),
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
        """关键词路由 39 工具。"""
        auth = metadata.get("authorization", "Bearer DEV_TOKEN")

        # ── INC-xxx 显式查询 ──
        m = re.search(r"\bINC-\d{3}\b", text, re.IGNORECASE)
        if m:
            return t.query_incident(incident_id=m.group(0).upper())

        # ── 工单状态过滤 ──
        if any(k in text for k in ["P0工单", "P1工单", "P2工单", "P3工单"]):
            pri = next(p for p in ["P0", "P1", "P2", "P3"] if p + "工单" in text)
            return t.query_incident(priority=pri)
        if any(k in text for k in ["未解决", "打开中", "in_progress", "open"]):
            return t.query_incident(status="open")
        if "已解决" in text or "resolved" in text:
            return t.query_incident(status="resolved")
        if "团队负载" in text or "工作量" in text or "workload" in text:
            return t.get_team_workload()
        if "工单统计" in text or "统计" in text:
            return t.get_incident_stats()
        if "P0" in text and "未关闭" in text:
            return t.list_open_p0_incidents()
        if "创建工单" in text or "新建工单" in text:
            return t.create_incident(title="用户报告工单", priority="P2",
                                     team="platform", description=text, authorization=auth)
        if "分配工单" in text or "assign" in text:
            return t.assign_incident("INC-001", assignee="张工", authorization=auth)
        if "关闭工单" in text or "解决工单" in text:
            return t.resolve_incident("INC-001", resolution_note="已修复",
                                      authorization=auth)
        if "升级" in text and "工单" in text:
            return t.escalate_incident("INC-008", new_priority="P1",
                                       reason="影响范围扩大", authorization=auth)
        if any(k in text for k in ["最近", "工单列表", "所有工单"]):
            return t.list_recent_incidents(limit=8)
        if any(k in text for k in ["工单", "incident"]):
            return t.query_incident(limit=5)

        # ── Oncall ──
        if any(k in text for k in ["呼叫 oncall", "page oncall", "发 oncall", "呼叫oncall"]):
            return t.page_oncall(team=_extract_team(text), message=text,
                                 authorization=auth)
        if "排班周期" in text or "rotation" in text:
            return t.get_rotation_schedule(team=_extract_team(text))
        if "切班" in text or "rotate" in text:
            return t.rotate_oncall(team=_extract_team(text),
                                   new_primary="张工", new_secondary="陈工",
                                   start="2026-08-15", end="2026-08-28",
                                   authorization=auth)
        if "按名字" in text and "oncall" in text:
            name = text.split("查")[-1].strip()
            return t.find_oncall_by_name(name)
        if "全部 oncall" in text or "oncall 列表" in text or "所有 oncall" in text:
            return t.list_all_oncall_contacts()
        if "主 oncall" in text or "primary" in text:
            return t.get_primary_oncall(team=_extract_team(text))
        if "oncall 团队" in text:
            return t.list_oncall_teams()
        if any(k in text for k in ["oncall", "on-call", "on call"]):
            return t.query_oncall(team=_extract_team(text))

        # ── K8s ──
        if "cordon" in text or "禁止调度" in text:
            return t.cordon_node("node-prod-07", unschedulable=True, authorization=auth)
        if "pod 日志" in text or "日志" in text and "pod" in text:
            return t.get_pod_logs("payment-api-abc123", "default", tail_lines=50,
                                  authorization=auth)
        if "回滚" in text and "deployment" in text.lower():
            return t.rollback_deployment("order-service", "default",
                                         authorization=auth)
        if "扩容" in text or "缩容" in text or "scale" in text:
            return t.scale_deployment("order-service", "default", replicas=5,
                                      authorization=auth)
        if any(k in text for k in ["pod", "restart", "重启"]):
            try:
                return t.restart_pod("payment-api-abc123", "default", authorization=auth)
            except PermissionError as exc:
                return json.dumps({"status": "deny", "reason": str(exc)}, ensure_ascii=False)

        # ── 监控告警 ──
        if "告警统计" in text:
            return t.get_alert_stats()
        if "静音告警" in text or "silence" in text:
            return t.silence_alert("ALR-002", duration_minutes=60,
                                   reason="已知问题排查中", authorization=auth)
        if "服务健康" in text:
            return t.get_service_health("api-gateway")
        if "critical 告警" in text or "严重告警" in text:
            return t.list_critical_alerts()
        if "firing 告警" in text or "未恢复告警" in text or "激活告警" in text:
            return t.list_firing_alerts()
        if any(k in text for k in ["告警", "alert"]):
            return t.query_alert()

        # ── CI/CD ──
        if "流水线统计" in text:
            return t.get_pipeline_stats()
        if "触发流水线" in text or "跑流水线" in text:
            return t.trigger_pipeline("order-service", branch="main", authorization=auth)
        if "失败流水线" in text or "pipeline 失败" in text:
            return t.list_failed_pipelines()
        if any(k in text for k in ["流水线", "pipeline", "cicd"]):
            return t.query_pipeline()

        # ── 日志 ──
        if "日志保留" in text or "retention" in text:
            return t.get_log_retention_policy("api-gateway")
        if "搜日志" in text or "日志检索" in text or "log search" in text:
            return t.search_logs(query=text, source="api-gateway", time_range_hours=1)
        if "日志源" in text:
            return t.list_log_sources()
        if any(k in text for k in ["日志", "log"]):
            return t.query_log_source()

        # ── Bridge ──
        if "hr 联动" in text or "hr 检查" in text:
            return b.cross_check_hr(authorization=auth, request_id="L-UNKNOWN")
        if "faq 兜底" in text or "faq 补全" in text:
            return b.cross_query_faq(query=text, top_k=2)

        return json.dumps({
            "status": "no_match",
            "message": "暂不支持该查询。devops_copilot 处理:工单/Oncall/K8s/告警/CI-CD/日志/跨插件桥接。",
        }, ensure_ascii=False)