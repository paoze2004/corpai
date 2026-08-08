"""hr_assistant plugin — 3 manifest + register。"""
from CorpAI.platform.plugin_manager import PluginManifest, PluginRegistry

from hr_assistant.prompts import HR_ASSISTANT_LLM_PROMPT

AGENT_MANIFEST = PluginManifest(
    name="hr_assistant",
    version="1.0.0",
    description="HR 助手:员工福利(社保/体检/团建/培训/设备) + 人事政策(假期/缺勤/报销/考勤)。",
    plugin_type="llm_agent",
    endpoint="http://localhost:5010",
    llm_prompt=HR_ASSISTANT_LLM_PROMPT,
    summary_prompt="summarize_benefits",
    required_intents=["hr", "benefits"],
    permissions=["hr:read", "hr:write"],
    tags=["hr", "benefits", "policy"],
)

BENEFITS_TOOL = PluginManifest(
    name="hr_assistant_benefits_mcp",
    version="1.0.0",
    description="员工福利查询(社保/补充医疗/体检/团建/设备/培训/餐饮/通讯)。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8010",
    mcp_tool_name="query_benefits",
    permissions=["hr:read"],
    tags=["benefits", "welfare", "mcp"],
)

POLICY_TOOL = PluginManifest(
    name="hr_assistant_policy_mcp",
    version="1.0.0",
    description="HR 政策 KB 检索(年假/病假/婚产/缺勤/报销/调休/离职/考勤)。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8011",
    mcp_tool_name="query_policy",
    permissions=["hr:read"],
    tags=["policy", "kb"],
)


def register(registry: PluginRegistry) -> None:
    for m in (AGENT_MANIFEST, BENEFITS_TOOL, POLICY_TOOL):
        registry.register(m)
