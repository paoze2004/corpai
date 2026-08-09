"""devops_copilot plugin v3.0 — 35+ manifest + register。"""
from CorpAI.platform.plugin_manager import PluginManifest, PluginRegistry

from devops_copilot.prompts import DEVOPS_LLM_PROMPT

AGENT_MANIFEST = PluginManifest(
    name="devops_copilot",
    version="3.0.0",
    description="DevOps 副驾 v3.0:incident(10)+ oncall(8)+ k8s(5)+ monitoring(6)+ cicd(4)+ logs(4)+ bridge(2),共 39 工具。",
    plugin_type="llm_agent",
    endpoint="http://localhost:5020",
    llm_prompt=DEVOPS_LLM_PROMPT,
    summary_prompt="summarize_incident",
    required_intents=["devops", "incident", "oncall", "pod_restart", "alert", "pipeline", "logs"],
    permissions=["devops:read", "devops:write"],
    tags=["devops", "k8s", "incident", "oncall", "alert", "cicd", "logs"],
)

# ─── Incident(10 个)— :8020 ───
INCIDENT_TOOL = PluginManifest(
    name="devops_copilot_incident_mcp",
    version="3.0.0",
    description="工单查询/操作:query_incident / list_recent / list_open_p0 / get_stats / search / get_workload。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8020",
    mcp_tool_name="query_incident",
    permissions=["devops:read"],
    tags=["incident", "jira", "mcp"],
)

INCIDENT_CREATE_TOOL = PluginManifest(
    name="devops_copilot_incident_create_mcp",
    version="3.0.0",
    description="创建工单:create_incident / assign / resolve / escalate。需 devops:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8025",
    mcp_tool_name="create_incident",
    permissions=["devops:write"],
    tags=["incident", "action", "mcp"],
)

# ─── Oncall(8 个)— :8020 ───
ONCALL_TOOL = PluginManifest(
    name="devops_copilot_oncall_mcp",
    version="3.0.0",
    description="On-call 联系:query / list_teams / get_primary / rotate / list_all / find_by_name / get_schedule / page。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8026",
    mcp_tool_name="query_oncall",
    permissions=["devops:read"],
    tags=["oncall", "rotation", "mcp"],
)

# ─── K8s(5 个)— :8021 ───
K8S_TOOL = PluginManifest(
    name="devops_copilot_k8s_mcp",
    version="3.0.0",
    description="K8s 操作(dry_run 默认):restart_pod / rollback_deployment / scale_deployment / get_pod_logs / cordon_node。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8021",
    mcp_tool_name="restart_pod",
    permissions=["devops:write"],
    tags=["k8s", "pod", "write", "mcp"],
)

# ─── 监控告警(6 个)— :8022 ───
ALERT_TOOL = PluginManifest(
    name="devops_copilot_alert_mcp",
    version="3.0.0",
    description="监控告警:query / list_firing / list_critical / get_service_health / silence / get_stats。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8022",
    mcp_tool_name="query_alert",
    permissions=["devops:read"],
    tags=["alert", "prometheus", "mcp"],
)

# ─── CI/CD(4 个)— :8023 ───
PIPELINE_TOOL = PluginManifest(
    name="devops_copilot_pipeline_mcp",
    version="3.0.0",
    description="CI/CD 流水线:query_pipeline / list_failed / trigger / get_stats。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8023",
    mcp_tool_name="query_pipeline",
    permissions=["devops:read"],
    tags=["cicd", "pipeline", "mcp"],
)

# ─── 日志(4 个)— :8024 ───
LOG_TOOL = PluginManifest(
    name="devops_copilot_log_mcp",
    version="3.0.0",
    description="日志源:query_log_source / list_log_sources / search_logs / get_retention_policy。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8024",
    mcp_tool_name="query_log_source",
    permissions=["devops:read"],
    tags=["logs", "elasticsearch", "mcp"],
)

# ─── Bridge(2 个)— :8027 ───
BRIDGE_HR_TOOL = PluginManifest(
    name="devops_copilot_bridge_hr_mcp",
    version="3.0.0",
    description="DevOps → HR:cross_check_hr(请假触发 oncall 备份检查)。失败静默降级。需 devops:read。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8027",
    mcp_tool_name="cross_check_hr",
    permissions=["devops:read"],
    tags=["bridge", "hr", "mcp"],
)

BRIDGE_FAQ_TOOL = PluginManifest(
    name="devops_copilot_bridge_faq_mcp",
    version="3.0.0",
    description="DevOps → FAQ 兜底:cross_query_faq(SOP 兜底补全)。失败静默降级。需 devops:read。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8028",
    mcp_tool_name="cross_query_faq",
    permissions=["devops:read"],
    tags=["bridge", "faq", "fallback", "mcp"],
)


def register(registry: PluginRegistry) -> None:
    for m in (
        AGENT_MANIFEST,
        # Incident / Oncall
        INCIDENT_TOOL, INCIDENT_CREATE_TOOL, ONCALL_TOOL,
        # K8s / 监控 / CI/CD / 日志
        K8S_TOOL, ALERT_TOOL, PIPELINE_TOOL, LOG_TOOL,
        # Bridge
        BRIDGE_HR_TOOL, BRIDGE_FAQ_TOOL,
    ):
        registry.register(m)