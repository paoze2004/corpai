"""hr_assistant plugin — 16 manifest + register。v2.1 加 9 个操作类工具 + 2 个 bridge。"""
from CorpAI.platform.plugin_manager import PluginManifest, PluginRegistry

from hr_assistant.prompts import HR_ASSISTANT_LLM_PROMPT

AGENT_MANIFEST = PluginManifest(
    name="hr_assistant",
    version="2.1.0",
    description="HR 助手 v2.1:7 大业务域 KB(82 条只读)+ 9 个操作类工具(请假/报销/证明/资产/培训/转正/审批)+ 3 个跨插件 bridge(faq/devops)。",
    plugin_type="llm_agent",
    endpoint="http://localhost:5010",
    llm_prompt=HR_ASSISTANT_LLM_PROMPT,
    summary_prompt="summarize_benefits",
    required_intents=["hr", "benefits"],
    permissions=["hr:read", "hr:write"],
    tags=["hr", "benefits", "policy", "process", "onboarding", "compensation",
          "development", "welfare", "action", "approval"],
)

BENEFITS_TOOL = PluginManifest(
    name="hr_assistant_benefits_mcp",
    version="2.0.0",
    description="员工福利查询(B001-B018,18 条):五险一金/补充医疗/体检/团建/设备/培训/餐饮/通讯/休假/股票/期权/关怀/弹性。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8010",
    mcp_tool_name="query_benefits",
    permissions=["hr:read"],
    tags=["benefits", "welfare", "mcp"],
)

POLICY_TOOL = PluginManifest(
    name="hr_assistant_policy_mcp",
    version="2.0.0",
    description="HR 政策 KB(P001-P030,30 条):年假/病假/婚产/缺勤/报销/调休/离职/考勤/加班/出差/保密/利益冲突/反骚扰/招聘纪律/知识产权/工作居住证/户口/晋升/绩效/PIP/申诉/培训/调岗/外籍/实习/工时/出差补贴/员工关系。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8011",
    mcp_tool_name="query_policy",
    permissions=["hr:read"],
    tags=["policy", "kb"],
)

PROCESS_TOOL = PluginManifest(
    name="hr_assistant_process_mcp",
    version="2.0.0",
    description="HR 流程查询(PR001-PR012,12 条):离职/入职/转正/考勤异常/费用报销/资产申请/加班/请假/学历提升/在职证明/内部调岗/外籍签证。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8012",
    mcp_tool_name="query_process",
    permissions=["hr:read"],
    tags=["process", "workflow"],
)

ONBOARDING_TOOL = PluginManifest(
    name="hr_assistant_onboarding_mcp",
    version="2.0.0",
    description="招聘/入职(ON001-ON006,6 条):面试流程/入职材料/新员工培训/导师制/实习转正/试用期管理。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8013",
    mcp_tool_name="query_onboarding",
    permissions=["hr:read"],
    tags=["onboarding", "recruitment"],
)

COMPENSATION_TOOL = PluginManifest(
    name="hr_assistant_compensation_mcp",
    version="2.0.0",
    description="薪酬模块(C001-C006,6 条):工资结构/年终奖/调薪/股票 vesting/期权行权/个税申报。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8014",
    mcp_tool_name="query_compensation",
    permissions=["hr:read"],
    tags=["compensation", "salary"],
)

DEVELOPMENT_TOOL = PluginManifest(
    name="hr_assistant_development_mcp",
    version="2.0.0",
    description="培训/发展(D001-D006,6 条):外部培训/内部培训/书籍报销/导师制/专业认证/学历提升。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8015",
    mcp_tool_name="query_development",
    permissions=["hr:read"],
    tags=["development", "training"],
)

WELFARE_TOOL = PluginManifest(
    name="hr_assistant_welfare_mcp",
    version="2.0.0",
    description="员工关怀/工会(W001-W004,4 条):工会福利/节日福利/心理咨询/员工活动。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8016",
    mcp_tool_name="query_welfare",
    permissions=["hr:read"],
    tags=["welfare", "union"],
)

# ─── 操作类工具(写 MySQL 真业务)— v2.1 ───

LEAVE_TOOL = PluginManifest(
    name="hr_assistant_leave_mcp",
    version="2.1.0",
    description="请假申请:submit_leave(提交)/cancel_leave(撤销)。写 hr_leave_requests;状态机 pending→approved/rejected/cancelled。需 hr:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8017",
    mcp_tool_name="submit_leave",
    permissions=["hr:write"],
    tags=["leave", "action", "approval", "mcp"],
)

REIM_TOOL = PluginManifest(
    name="hr_assistant_reim_mcp",
    version="2.1.0",
    description="报销申请:submit_reimbursement。写 hr_reimbursements;支持 travel/office/training/meal/other。需 hr:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8018",
    mcp_tool_name="submit_reimbursement",
    permissions=["hr:write"],
    tags=["reimbursement", "expense", "action", "mcp"],
)

CERT_TOOL = PluginManifest(
    name="hr_assistant_cert_mcp",
    version="2.1.0",
    description="证明申请:apply_certificate。在职/收入/离职/工作居住证;支持中英;支持 email/pickup/mail。需 hr:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8019",
    mcp_tool_name="apply_certificate",
    permissions=["hr:write"],
    tags=["certificate", "action", "mcp"],
)

ASSET_TOOL = PluginManifest(
    name="hr_assistant_asset_mcp",
    version="2.1.0",
    description="资产申请:request_asset。笔记本/显示器/键盘/鼠标/耳机/手机。需 hr:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8020",
    mcp_tool_name="request_asset",
    permissions=["hr:write"],
    tags=["asset", "it", "action", "mcp"],
)

TRAIN_TOOL = PluginManifest(
    name="hr_assistant_train_mcp",
    version="2.1.0",
    description="培训报名:register_training。external/internal/certification。需 hr:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8021",
    mcp_tool_name="register_training",
    permissions=["hr:write"],
    tags=["training", "action", "mcp"],
)

REG_TOOL = PluginManifest(
    name="hr_assistant_reg_mcp",
    version="2.1.0",
    description="转正申请:apply_regularization。需 achievements + 试用期区间。需 hr:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8022",
    mcp_tool_name="apply_regularization",
    permissions=["hr:write"],
    tags=["regularization", "probation", "action", "mcp"],
)

APPROVE_TOOL = PluginManifest(
    name="hr_assistant_approve_mcp",
    version="2.1.0",
    description="通用审批:approve_request(approve/reject)。HR 视角,审批任意用户的 request;reject 必须填 approval_note。需 hr:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8023",
    mcp_tool_name="approve_request",
    permissions=["hr:write"],
    tags=["approval", "action", "mcp"],
)

MY_REQUESTS_TOOL = PluginManifest(
    name="hr_assistant_my_mcp",
    version="2.1.0",
    description="我的申请:query_my_requests。按 target_type/status 过滤。需 chat:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8024",
    mcp_tool_name="query_my_requests",
    permissions=["chat:write"],
    tags=["query", "self", "mcp"],
)

# ─── 跨插件 bridge(去重/兜底/联动)— v2.1 ───

BRIDGE_FAQ_TOOL = PluginManifest(
    name="hr_assistant_bridge_faq_mcp",
    version="2.1.0",
    description="HR → FAQ 兜底:cross_query_faq。HR KB 未命中时调 faq 兜底补全。失败静默降级。需 chat:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8025",
    mcp_tool_name="cross_query_faq",
    permissions=["chat:write"],
    tags=["bridge", "faq", "fallback", "mcp"],
)

BRIDGE_DEVOPS_TOOL = PluginManifest(
    name="hr_assistant_bridge_devops_mcp",
    version="2.1.0",
    description="HR → DevOps:cross_check_devops(资产去重)+ cross_notify_devops(查 oncall)。失败静默降级。需 hr:write。",
    plugin_type="mcp_tool",
    endpoint="http://localhost:8026",
    mcp_tool_name="cross_check_devops",
    permissions=["hr:write"],
    tags=["bridge", "devops", "incident", "oncall", "mcp"],
)


def register(registry: PluginRegistry) -> None:
    for m in (
        AGENT_MANIFEST,
        # KB 查询(7)
        BENEFITS_TOOL, POLICY_TOOL, PROCESS_TOOL, ONBOARDING_TOOL,
        COMPENSATION_TOOL, DEVELOPMENT_TOOL, WELFARE_TOOL,
        # 操作类(8)
        LEAVE_TOOL, REIM_TOOL, CERT_TOOL, ASSET_TOOL,
        TRAIN_TOOL, REG_TOOL, APPROVE_TOOL, MY_REQUESTS_TOOL,
        # 跨插件 bridge(2 — 3 个函数共用 1 个 manifest 路由)
        BRIDGE_FAQ_TOOL, BRIDGE_DEVOPS_TOOL,
    ):
        registry.register(m)
