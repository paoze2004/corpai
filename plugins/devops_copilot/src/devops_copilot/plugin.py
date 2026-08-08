"""devops_copilot plugin — 3 manifest + register(RBAC showcase)。"""
from CorpAI.platform.plugin_manager import PluginManifest, PluginRegistry

from devops_copilot.prompts import DEVOPS_LLM_PROMPT

AGENT_MANIFEST = PluginManifest(
    name="devops_copilot",
    version="1.0.0",
    description="DevOps 副驾:工单查询 + On-call 联系 + Pod 重启(dry_run 默认)。",
    plugin_type="llm_agent",
    endpoint="http://localhost:5020",
    llm_prompt=DEVOPS_LLM_PROMPT,
    summary_prompt="summarize_incident",
    required_intents=["incident", "oncall", "pod_restart"],
    permissions=["devops:read", "devops:write"],  # 双 scope 演示 read/write
    tags=["devops", "k8s", "incident", "oncall"],
)

INCIDENT_TOOL = PluginManifest(
    name="devops_copilot_incident_mcp",
    version="1.0.0",
    description="工单查询 mock(查询 INC-001 状态)。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8020",
    mcp_tool_name="query_incident",
    permissions=["devops:read"],
    tags=["incident", "jira"],
)

K8S_TOOL = PluginManifest(
    name="devops_copilot_k8s_mcp",
    version="1.0.0",
    description="K8s Pod 重启(mock,dry_run 默认;restart_pod 内部 has_scope devops:write 二次校验)。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8021",
    mcp_tool_name="restart_pod",
    permissions=["devops:write"],   # 单独 write scope,写操作更严
    tags=["k8s", "pod", "write"],
)


def register(registry: PluginRegistry) -> None:
    for m in (AGENT_MANIFEST, INCIDENT_TOOL, K8S_TOOL):
        registry.register(m)
