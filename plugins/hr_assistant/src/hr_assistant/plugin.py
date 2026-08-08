"""hr_assistant plugin — 3 manifest + register。"""
from CorpAI.platform.plugin_manager import PluginManifest, PluginRegistry

from hr_assistant.prompts import HR_ASSISTANT_LLM_PROMPT

AGENT_MANIFEST = PluginManifest(
    name="hr_assistant",
    version="1.0.0",
    description="HR 助手:保险方案比较 + 假期政策 + 缺勤申报。",
    plugin_type="llm_agent",
    endpoint="http://localhost:5010",
    llm_prompt=HR_ASSISTANT_LLM_PROMPT,
    summary_prompt="summarize_insurance",
    required_intents=["insurance"],
    permissions=["hr:read", "hr:write"],
    tags=["hr", "benefits", "policy"],
)

INSURANCE_TOOL = PluginManifest(
    name="hr_assistant_insurance_mcp",
    version="1.0.0",
    description="保险产品查询(综合/意外/医疗/境外)。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8010",
    mcp_tool_name="query_insurance",
    permissions=["hr:read"],
    tags=["insurance", "mcp"],
)

POLICY_TOOL = PluginManifest(
    name="hr_assistant_policy_mcp",
    version="1.0.0",
    description="HR 政策 KB 检索(假期/缺勤/报销)。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8011",
    mcp_tool_name="query_policy",
    permissions=["hr:read"],
    tags=["policy", "kb"],
)


def register(registry: PluginRegistry) -> None:
    for m in (AGENT_MANIFEST, INSURANCE_TOOL, POLICY_TOOL):
        registry.register(m)
