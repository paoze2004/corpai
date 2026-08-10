"""sre_copilot plugin v3.1 — 重组完成。

重组(v3.1):
- plugin 包名 devops_copilot → sre_copilot
- CorpAI/platform/sre/ 里 action_executor / action_tools / incident_manager / feishu / executor_cli 5 个文件搬进本 plugin
- RBAC scope devops:* → sre:*
- 跨插件 bridge 名 cross_check_devops → cross_check_sre(在 hr_assistant 那边同步)

v3.0 保留 4 个真工具(都接真 SDK,Phase 1 接入):
- query_incident → Jira
- query_oncall   → PagerDuty
- query_alert    → Prometheus Alertmanager
- get_pod_logs   → kubernetes-python

+ 2 个跨插件 bridge(显式失败):
- cross_check_hr
- cross_query_faq
"""
from CorpAI.platform.plugin_manager import PluginManifest, PluginRegistry
from sre_copilot.prompts import SRE_LLM_PROMPT

AGENT_MANIFEST = PluginManifest(
    name="sre_copilot",
    version="3.1.0",
    description="SRE Copilot v3.1:4 个真工具(query_incident/query_oncall/query_alert/get_pod_logs)+ 2 跨插件 bridge。无 in-memory 玩具。Action 引擎 + 飞书审批已并入 plugin。",
    plugin_type="llm_agent",
    endpoint="http://localhost:5020",
    llm_prompt=SRE_LLM_PROMPT,
    summary_prompt="summarize_incident",
    required_intents=["sre", "incident", "oncall", "alert", "pod"],
    permissions=["sre:read", "sre:write"],
    tags=["sre", "incident", "oncall", "alert", "k8s"],
)

# ─── Incident(1)— :8020 ───
INCIDENT_TOOL = PluginManifest(
    name="sre_copilot_incident_mcp",
    version="3.1.0",
    description="工单查询:query_incident(Jira REST API)。Phase 1 接入。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8020",
    mcp_tool_name="query_incident",
    permissions=["sre:read"],
    tags=["incident", "jira", "mcp"],
)

# ─── Oncall(1)— :8020 ───
ONCALL_TOOL = PluginManifest(
    name="sre_copilot_oncall_mcp",
    version="3.1.0",
    description="On-call 联系:query_oncall(PagerDuty API)。Phase 1 接入。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8020",
    mcp_tool_name="query_oncall",
    permissions=["sre:read"],
    tags=["oncall", "pagerduty", "mcp"],
)

# ─── Alert(1)— :8022 ───
ALERT_TOOL = PluginManifest(
    name="sre_copilot_alert_mcp",
    version="3.1.0",
    description="监控告警:query_alert(Prometheus Alertmanager)。Phase 1 接入。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8022",
    mcp_tool_name="query_alert",
    permissions=["sre:read"],
    tags=["alert", "prometheus", "mcp"],
)

# ─── K8s(1)— :8021, get_pod_logs 是 sre:read ───
K8S_TOOL = PluginManifest(
    name="sre_copilot_k8s_mcp",
    version="3.1.0",
    description="K8s: get_pod_logs(kubernetes-python)。DRY_RUN 默认。需 sre:read。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8021",
    mcp_tool_name="get_pod_logs",
    permissions=["sre:read"],
    tags=["k8s", "pod", "logs", "mcp"],
)

# ─── Bridge(2)— :8027-8028 ───
BRIDGE_HR_TOOL = PluginManifest(
    name="sre_copilot_bridge_hr_mcp",
    version="3.1.0",
    description="SRE → HR:cross_check_hr(请假触发 oncall 备份检查)。失败显式告知 + Counter。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8027",
    mcp_tool_name="cross_check_hr",
    permissions=["sre:read"],
    tags=["bridge", "hr", "mcp"],
)

BRIDGE_FAQ_TOOL = PluginManifest(
    name="sre_copilot_bridge_faq_mcp",
    version="3.1.0",
    description="SRE → FAQ 兜底:cross_query_faq(SOP 兜底)。失败显式告知 + Counter。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8028",
    mcp_tool_name="cross_query_faq",
    permissions=["sre:read"],
    tags=["bridge", "faq", "fallback", "mcp"],
)


def register(registry: PluginRegistry) -> None:
    """v3.1:7 manifest = 1 agent + 4 真工具 + 2 bridge。"""
    for m in (
        AGENT_MANIFEST,
        INCIDENT_TOOL, ONCALL_TOOL, ALERT_TOOL, K8S_TOOL,
        BRIDGE_HR_TOOL, BRIDGE_FAQ_TOOL,
    ):
        registry.register(m)