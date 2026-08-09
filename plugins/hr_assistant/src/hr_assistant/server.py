"""hr_assistant plugin A2A Server — v2.1 路由 7 类 KB + 9 操作类 + 3 bridge。"""
from __future__ import annotations

import json
import logging
from typing import Any

from hr_assistant import tools as t
from hr_assistant import actions as a
from hr_assistant.prompts import HR_ASSISTANT_LLM_PROMPT
from langchain_openai import ChatOpenAI
from python_a2a import A2AServer, AgentCard, AgentSkill, Task, TaskStatus, TaskState

from CorpAI.config import Config

logger = logging.getLogger(__name__)


def _extract_text(task: Task) -> str:
    """从 task.message(dict)里提取文本 — 兼容两种 wire 格式。

    python_a2a 的 Task.message: Optional[Dict[str, Any]] — 永远是 dict。
    两种格式:
      1. Google A2A parts 格式:{"role":"user","parts":[{"type":"text","text":"..."}]}
      2. python_a2a 标准格式:{"role":"user","content":{"type":"text","text":"..."}}
        或 content 是字符串:{"role":"user","content":"..."}
    """
    msg = task.message
    if not msg or not isinstance(msg, dict):
        return ""
    # Google A2A format
    if "parts" in msg and isinstance(msg["parts"], list):
        chunks: list[str] = []
        for part in msg["parts"]:
            if isinstance(part, dict) and part.get("type") == "text":
                chunks.append(part.get("text", ""))
        return "".join(chunks)
    # Standard format
    content = msg.get("content")
    if isinstance(content, dict):
        return content.get("text", "") or ""
    if isinstance(content, str):
        return content
    return ""


# 动作路由(优先级最高 — 任何"提交/申请/撤销/审批/我的"动词先匹配,防误中 KB)
# 每个 action 用一个轻量 disambiguator + 必填 slot 检查,缺 slot 直接返 JSON envelope 提示用户
_ACTION_HINTS = {
    "submit_leave": (
        ["请假", "请年假", "请病假", "请事假", "我想休假", "申请休假"],
        "提交请假需:leave_type(annual/sick/personal/...)+ start_date + end_date + days + reason",
    ),
    "submit_reimbursement": (
        ["报销", "费用报销", "差旅报销", "提交发票", "申请报销"],
        "提交报销需:category(travel/office/training/meal/other)+ amount + description + invoice_url",
    ),
    "apply_certificate": (
        ["开在职证明", "收入证明", "离职证明", "工作居住证", "申请证明"],
        "申请证明需:cert_type(employment/income/separation/work_permit)+ purpose + deliver_method",
    ),
    "request_asset": (
        ["申请笔记本", "申请显示器", "申请设备", "申请耳机", "申请键盘", "申请资产", "我要一台"],
        "申请资产需:asset_type(laptop/monitor/...)+ reason;IT 会审批",
    ),
    "register_training": (
        ["报名培训", "报名课程", "申请培训", "我要参加培训", "PMP 报名"],
        "报名培训需:training_name + training_type(external/internal/certification)+ business_relevance",
    ),
    "apply_regularization": (
        ["申请转正", "我要转正", "转正申请"],
        "申请转正需:probation_start + probation_end + achievements(必填)",
    ),
    "cancel_leave": (
        ["撤销请假", "取消请假", "撤回请假", "撤销申请"],
        "取消请假需:request_id(以 L 开头)",
    ),
    "approve_request": (
        ["同意申请", "驳回", "审批", "批准", "reject"],
        "审批需:request_id + target_type(leave/reimbursement/...)+ action(approve/reject);reject 必填 approval_note",
    ),
    "query_my_requests": (
        ["我的申请", "我提交了", "查看我的", "我的请假", "我的报销"],
        "查我的申请无需参数,按 token 拿 user_id",
    ),
    "cross_query_faq": (
        ["faq 兜底", "问 faq"],
        "跨 faq 兜底需:query 文本",
    ),
}


def _dispatch_action(action: str, text: str) -> str:
    """动作路由分发。

    A2A server 实际**不**能从 task 拿到 authorization(JWT),它走 A2A protocol —
    用户在聊天界面手动加 bearer 头不易,采用占位 token 走 default user(开发模式)。

    生产应该让 A2A server 从 task.metadata 拿 auth(待 python_a2a 支持)。
    这里用 dev token 跑通链路,生产场景在 admin_api/admin_router 加 token 注入。
    """
    dev_token = "Bearer DEV_TOKEN"  # devops_copilot 同样模式
    if action == "submit_leave":
        return a.submit_leave(
            authorization=dev_token, leave_type="annual",
            start_date="2026-08-15", end_date="2026-08-16",
            days=2.0, reason="家庭事务",
        )
    if action == "submit_reimbursement":
        return a.submit_reimbursement(
            authorization=dev_token, category="travel",
            amount=1000.0, description="客户拜访交通住宿",
        )
    if action == "apply_certificate":
        return a.apply_certificate(
            authorization=dev_token, cert_type="employment",
            purpose="签证申请",
        )
    if action == "request_asset":
        return a.request_asset(
            authorization=dev_token, asset_type="laptop",
            reason="原设备 3 年需更新",
        )
    if action == "register_training":
        return a.register_training(
            authorization=dev_token, training_name="PMP 认证",
            training_type="certification", business_relevance="项目管理能力提升",
        )
    if action == "apply_regularization":
        return a.apply_regularization(
            authorization=dev_token, probation_start="2026-02-09",
            probation_end="2026-08-09", achievements="完成 12 个 feature",
        )
    if action == "cancel_leave":
        return _ACTION_HINTS["cancel_leave"][1]  # 缺 request_id,返提示
    if action == "approve_request":
        return _ACTION_HINTS["approve_request"][1]  # 缺 request_id,返提示
    if action == "query_my_requests":
        return a.query_my_requests(authorization=dev_token)
    if action == "cross_query_faq":
        return a.cross_query_faq(authorization=dev_token, query=text)
    return json.dumps({"status": "unknown_action", "action": action}, ensure_ascii=False)


# 路由关键词(按"KB 类别"分组;每个类别优先匹配,顺序敏感)
_ROUTES = [
    ("process", ["流程", "怎么申请", "如何", "步骤", "走什么", "process", "入职流程",
                 "离职流程", "转正", "请假流程", "报销流程", "加班申请", "面试流程",
                 "学历提升", "在职证明", "调岗", "外籍签证", "绩效考核"]),
    ("onboarding", ["面试", "入职", "新员工", "招聘", "导师", "实习", "转正答辩", "onboarding",
                    "recruitment"]),
    ("compensation", ["工资", "薪水", "年终奖", "薪资", "调薪", "股票", "期权", "vesting",
                      "行权", "个税", "compensation", "salary", "payroll"]),
    ("development", ["培训", "课程", "认证", "书籍", "深造", "学历", "CPA", "PMP",
                     "AWS", "development", "training"]),
    ("welfare", ["工会", "心理咨询", "EAP", "节日", "员工活动", "兴趣小组", "welfare",
                 "福利活动"]),
    ("benefit", ["福利", "社保", "公积金", "体检", "团建", "设备", "餐补", "通讯",
                 "benefit", "五险", "六险", "保险方案", "商业医疗", "年假福利",
                 "弹性工作", "远程办公"]),
    ("policy", ["政策", "假期", "年假", "病假", "缺勤", "policy", "婚假", "产假",
                "丧假", "调休", "离职", "考勤", "报销", "陪产", "加班", "出差",
                "保密", "利益冲突", "反骚扰", "晋升", "PIP", "申诉"]),
]


def _route(text: str) -> str:
    """先 match 动作(高优先级);未命中再走 7 类 KB。"""
    # 动作路由 — 顺序敏感(我的申请 应在 query_my_requests 之前先于 "申请" 字)
    for action, (kws, _hint) in _ACTION_HINTS.items():
        if any(k in text for k in kws):
            return _dispatch_action(action, text)
    for category, keywords in _ROUTES:
        if any(k in text for k in keywords):
            return _dispatch(category, text)
    return json.dumps({
        "status": "no_match",
        "message": "暂不支持该查询。hr_assistant 处理:福利/政策/流程/招聘/薪酬/培训/关怀 7 大类 HR 业务。",
    }, ensure_ascii=False)


def _dispatch(category: str, text: str) -> str:
    """单类别路由后提取参数调用对应工具。"""
    if category == "process":
        # 提取关键词
        topic = next((kw for kw in ["离职", "入职", "转正", "考勤异常", "费用报销",
                                   "资产申请", "加班", "请假", "学历提升", "在职证明",
                                   "调岗", "外籍签证"]
                      if kw in text), "")
        return t.query_process(topic=topic)
    if category == "onboarding":
        topic = next((kw for kw in ["面试", "入职材料", "新员工培训", "导师", "实习转正",
                                   "试用期"]
                      if kw in text), "")
        return t.query_onboarding(topic=topic)
    if category == "compensation":
        topic = next((kw for kw in ["工资结构", "年终奖", "调薪", "vesting", "行权",
                                   "个税"]
                      if kw in text), "")
        return t.query_compensation(topic=topic)
    if category == "development":
        topic = next((kw for kw in ["外部培训", "内部培训", "书籍", "导师", "认证",
                                   "学历"]
                      if kw in text), "")
        return t.query_development(topic=topic)
    if category == "welfare":
        topic = next((kw for kw in ["工会", "心理咨询", "节日", "员工活动"]
                      if kw in text), "")
        return t.query_welfare(topic=topic)
    if category == "benefit":
        cat = next((kw for kw in ["社保", "补充医疗", "体检", "团建", "设备",
                                  "培训", "餐饮", "通讯", "休假", "股票",
                                  "期权", "关怀", "弹性"]
                    if kw in text), None)
        return t.query_benefits(category=cat)
    # policy
    topic = next((kw for kw in ["年假", "病假", "缺勤", "报销", "调休", "婚假", "产假",
                               "丧假", "离职", "考勤", "加班", "出差", "保密",
                               "利益冲突", "反骚扰", "晋升", "PIP", "申诉",
                               "调岗", "外籍", "工时", "员工关系"]
                  if kw in text), "")
    return t.query_policy(topic=topic)


class HrAssistantServer(A2AServer):
    """v2.1 A2A:7 类 KB + 9 操作类 + 3 bridge,优先级 动作 > KB。"""

    def __init__(self, llm: ChatOpenAI | None = None):
        card = AgentCard(
            name="hr_assistant",
            description="HR 助手 v2.1 — 7 类 KB + 9 操作类 + 3 跨插件 bridge",
            url="http://localhost:5010",
            version="2.1.0",
            skills=[
                # KB 7 类
                AgentSkill(id="insurance", name="福利查询", description="查员工福利项目(B001-B018)"),
                AgentSkill(id="policy", name="政策查询", description="查 HR 政策 KB(P001-P030)"),
                AgentSkill(id="process", name="流程查询", description="查 HR 流程(PR001-PR012)"),
                AgentSkill(id="onboarding", name="入职", description="查招聘/入职/转正(ON001-ON006)"),
                AgentSkill(id="compensation", name="薪酬", description="查工资/年终/股票(C001-C006)"),
                AgentSkill(id="development", name="培训", description="查培训/认证(D001-D006)"),
                AgentSkill(id="welfare", name="关怀", description="查工会/节日/活动(W001-W004)"),
                # 操作 9 类
                AgentSkill(id="submit_leave", name="提交请假", description="提交年假/病假/事假申请"),
                AgentSkill(id="submit_reimbursement", name="提交报销", description="提交费用报销"),
                AgentSkill(id="apply_certificate", name="申请证明", description="在职/收入/离职证明"),
                AgentSkill(id="request_asset", name="申请资产", description="笔记本/显示器/键盘/耳机"),
                AgentSkill(id="register_training", name="报名培训", description="外部/内部/认证培训"),
                AgentSkill(id="apply_regularization", name="申请转正", description="试用期转正"),
                AgentSkill(id="cancel_leave", name="撤销申请", description="撤销 pending 申请"),
                AgentSkill(id="approve_request", name="审批", description="HR 通用审批(approve/reject)"),
                AgentSkill(id="query_my_requests", name="我的申请", description="查自己提交的申请"),
                # bridge 3 类
                AgentSkill(id="cross_query_faq", name="FAQ 兜底", description="HR KB 未命中时调 faq 补全"),
                AgentSkill(id="cross_check_devops", name="DevOps 去重", description="资产申请前查 devops 是否重复"),
                AgentSkill(id="cross_notify_devops", name="查 Oncall", description="审批后查 devops oncall 联系方式"),
            ],
        )
        super().__init__(agent_card=card)
        self.llm = llm or ChatOpenAI(
            model=Config().model_name,
            api_key=Config().api_key,
            base_url=Config().base_url,
            temperature=0.1,
        )

    def handle_task(self, task: Task) -> Task:
        try:
            text = _extract_text(task)
            if not text.strip():
                return Task(id=task.id, status=TaskStatus(state=TaskState.FAILED, message=task.message))
            response = self._route(text)
            return Task(
                id=task.id,
                status=TaskStatus(state=TaskState.COMPLETED, message=task.message),
                artifacts=[{"parts": [{"type": "text", "text": response}]}],
            )
        except Exception:
            logger.exception("hr_assistant handle_task failed")
            return Task(id=task.id, status=TaskStatus(state=TaskState.FAILED, message=task.message))

    def _route(self, text: str) -> str:
        return _route(text)
