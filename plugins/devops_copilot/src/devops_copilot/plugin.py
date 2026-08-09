"""devops_copilot plugin v3.0 — 生产化精简到 4 个真工具 + 2 bridge。

删掉:
- incident_create(6 个 create/assign/resolve/escalate 等写操作玩具)
- pipeline(4 个查询玩具)
- log(4 个查询玩具)

保留 4 个真工具(都接真 SDK,Phase 1 接入):
- query_incident → Jira
- query_oncall   → PagerDuty
- query_alert    → Prometheus Alertmanager
- get_pod_logs   → kubernetes-python

+ 2 个跨插件 bridge(显式失败):
- cross_check_hr
- cross_query_faq
"""
from CorpAI.platform.plugin_manager import PluginManifest, PluginRegistry

from devops_copilot.prompts import DEVOPS_LLM_PROMPT

AGENT_MANIFEST = PluginManifest(
    name="devops_copilot",
    version="3.0.0",
    description="DevOps 副驾 v3.0(生产化):4 个真工具(query_incident/query_oncall/query_alert/get_pod_logs)+ 2 跨插件 bridge。无 in-memory 玩具。",
    plugin_type="llm_agent",
    endpoint="http://localhost:5020",
    llm_prompt=DEVOPS_LLM_PROMPT,
    summary_prompt="summarize_incident",
    required_intents=["devops", "incident", "oncall", "alert", "pod"],
    permissions=["devops:read", "devops:write"],
    tags=["devops", "incident", "oncall", "alert", "k8s"],
)

# ─── Incident(1)— :8020 ───
INCIDENT_TOOL = PluginManifest(
    name="devops_copilot_incident_mcp",
    version="3.0.0",
    description="工单查询:query_incident(Jira REST API)。Phase 1 接入。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8020",
    mcp_tool_name="query_incident",
    permissions=["devops:read"],
    tags=["incident", "jira", "mcp"],
)

# ─── Oncall(1)— :8020 ───
ONCALL_TOOL = PluginManifest(
    name="devops_copilot_oncall_mcp",
    version="3.0.0",
    description="On-call 联系:query_oncall(PagerDuty API)。Phase 1 接入。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8020",
    mcp_tool_name="query_oncall",
    permissions=["devops:read"],
    tags=["oncall", "pagerduty", "mcp"],
)

# ─── Alert(1)— :8022 ───
ALERT_TOOL = PluginManifest(
    name="devops_copilot_alert_mcp",
    version="3.0.0",
    description="监控告警:query_alert(Prometheus Alertmanager)。Phase 1 接入。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8022",
    mcp_tool_name="query_alert",
    permissions=["devops:read"],
    tags=["alert", "prometheus", "mcp"],
)

# ─── K8s(1)— :8021, get_pod_logs 是 devops:read ───
K8S_TOOL = PluginManifest(
    name="devops_copilot_k8s_mcp",
    version="3.0.0",
    description="K8s: get_pod_logs(kubernetes-python)。DRY_RUN 默认。需 devops:read。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8021",
    mcp_tool_name="get_pod_logs",
    permissions=["devops:read"],
    tags=["k8s", "pod", "logs", "mcp"],
)

# ─── Bridge(2)— :8027-8028 ───
BRIDGE_HR_TOOL = PluginManifest(
    name="devops_copilot_bridge_hr_mcp",
    version="3.0.0",
    description="DevOps → HR:cross_check_hr(请假触发 oncall 备份检查)。失败显式告知 + Counter。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8027",
    mcp_tool_name="cross_check_hr",
    permissions=["devops:read"],
    tags=["bridge", "hr", "mcp"],
)

BRIDGE_FAQ_TOOL = PluginManifest(
    name="devops_copilot_bridge_faq_mcp",
    version="3.0.0",
    description="DevOps → FAQ 兜底:cross_query_faq(SOP 兜底)。失败显式告知 + Counter。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8028",
    mcp_tool_name="cross_query_faq",
    permissions=["devops:read"],
    tags=["bridge", "faq", "fallback", "mcp"],
)


def register(registry: PluginRegistry) -> None:
    """v3.0:7 manifest = 1 agent + 4 真工具 + 2 bridge。"""
    for m in (
        AGENT_MANIFEST,
        INCIDENT_TOOL, ONCALL_TOOL, ALERT_TOOL, K8S_TOOL,
        BRIDGE_HR_TOOL, BRIDGE_FAQ_TOOL,
    ):
        registry.register(m)