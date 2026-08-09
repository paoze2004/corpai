"""hr_assistant plugin — v3.0 生产化精简:1 agent + 8 ops + 2 bridge = 11 manifest。

删掉 7 个 KB 类工具(`query_benefits` / `query_policy` 等写死 82 条 dict 的玩具)。
保留 8 个写 MySQL 真业务的操作类工具 + 3 个跨插件 bridge。
"""
from CorpAI.platform.plugin_manager import PluginManifest, PluginRegistry

from hr_assistant.prompts import HR_ASSISTANT_LLM_PROMPT

AGENT_MANIFEST = PluginManifest(
    name="hr_assistant",
    version="3.0.0",
    description="HR 助手 v3.0(生产化):8 个操作类工具(请假/报销/证明/资产/培训/转正/审批/查询)+ 3 个跨插件 bridge(faq/devops)。无 KB 字典玩具。",
    plugin_type="llm_agent",
    endpoint="http://localhost:5010",
    llm_prompt=HR_ASSISTANT_LLM_PROMPT,
    summary_prompt="summarize_action",
    required_intents=["hr", "leave", "reimbursement"],
    permissions=["hr:read", "hr:write"],
    tags=["hr", "action", "approval", "leave", "reimbursement"],
)


# ─── 操作类工具(写 MySQL 真业务)───

LEAVE_TOOL = PluginManifest(
    name="hr_assistant_leave_mcp",
    version="3.0.0",
    description="请假申请:submit_leave(提交)/cancel_leave(撤销)。写 hr_leave_requests;状态机 pending→approved/rejected/cancelled。需 hr:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8017",
    mcp_tool_name="submit_leave",
    permissions=["hr:write"],
    tags=["leave", "action", "approval", "mcp"],
)

REIM_TOOL = PluginManifest(
    name="hr_assistant_reim_mcp",
    version="3.0.0",
    description="报销申请:submit_reimbursement。写 hr_reimbursements;支持 travel/office/training/meal/other。需 hr:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8018",
    mcp_tool_name="submit_reimbursement",
    permissions=["hr:write"],
    tags=["reimbursement", "expense", "action", "mcp"],
)

CERT_TOOL = PluginManifest(
    name="hr_assistant_cert_mcp",
    version="3.0.0",
    description="证明申请:apply_certificate。在职/收入/离职/工作居住证;支持中英;支持 email/pickup/mail。需 hr:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8019",
    mcp_tool_name="apply_certificate",
    permissions=["hr:write"],
    tags=["certificate", "action", "mcp"],
)

ASSET_TOOL = PluginManifest(
    name="hr_assistant_asset_mcp",
    version="3.0.0",
    description="资产申请:request_asset。笔记本/显示器/键盘/鼠标/耳机/手机。需 hr:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8020",
    mcp_tool_name="request_asset",
    permissions=["hr:write"],
    tags=["asset", "it", "action", "mcp"],
)

TRAIN_TOOL = PluginManifest(
    name="hr_assistant_train_mcp",
    version="3.0.0",
    description="培训报名:register_training。external/internal/certification。需 hr:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8021",
    mcp_tool_name="register_training",
    permissions=["hr:write"],
    tags=["training", "action", "mcp"],
)

REG_TOOL = PluginManifest(
    name="hr_assistant_reg_mcp",
    version="3.0.0",
    description="转正申请:apply_regularization。需 achievements + 试用期区间。需 hr:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8022",
    mcp_tool_name="apply_regularization",
    permissions=["hr:write"],
    tags=["regularization", "probation", "action", "mcp"],
)

APPROVE_TOOL = PluginManifest(
    name="hr_assistant_approve_mcp",
    version="3.0.0",
    description="通用审批:approve_request(approve/reject)。HR 视角,审批任意用户的 request;reject 必须填 approval_note。需 hr:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8023",
    mcp_tool_name="approve_request",
    permissions=["hr:write"],
    tags=["approval", "action", "mcp"],
)

MY_REQUESTS_TOOL = PluginManifest(
    name="hr_assistant_my_mcp",
    version="3.0.0",
    description="我的申请:query_my_requests。按 target_type/status 过滤。需 chat:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8024",
    mcp_tool_name="query_my_requests",
    permissions=["chat:write"],
    tags=["query", "self", "mcp"],
)


# ─── 跨插件 bridge(显式失败 + Counter)───

BRIDGE_FAQ_TOOL = PluginManifest(
    name="hr_assistant_bridge_faq_mcp",
    version="3.0.0",
    description="HR → FAQ 兜底:cross_query_faq。HR KB 未命中时调 faq 兜底补全。失败显式告知 + Counter。需 chat:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8025",
    mcp_tool_name="cross_query_faq",
    permissions=["chat:write"],
    tags=["bridge", "faq", "fallback", "mcp"],
)

BRIDGE_DEVOPS_TOOL = PluginManifest(
    name="hr_assistant_bridge_devops_mcp",
    version="3.0.0",
    description="HR → DevOps:cross_check_devops(资产去重)+ cross_notify_devops(查 oncall)。失败显式告知 + Counter。需 hr:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8026",
    mcp_tool_name="cross_check_devops",
    permissions=["hr:write"],
    tags=["bridge", "devops", "incident", "oncall", "mcp"],
)


def register(registry: PluginRegistry) -> None:
    """v3.0 注册 11 manifest:1 agent + 8 ops + 2 bridge(共 11 manifest,3 个 bridge 函数共用 2 manifest)。"""
    for m in (
        AGENT_MANIFEST,
        # 操作类(8)
        LEAVE_TOOL, REIM_TOOL, CERT_TOOL, ASSET_TOOL,
        TRAIN_TOOL, REG_TOOL, APPROVE_TOOL, MY_REQUESTS_TOOL,
        # 跨插件 bridge(2 — 3 个函数共用 1 个 manifest 路由)
        BRIDGE_FAQ_TOOL, BRIDGE_DEVOPS_TOOL,
    ):
        registry.register(m)