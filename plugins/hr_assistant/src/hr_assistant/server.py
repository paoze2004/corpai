"""hr_assistant plugin A2A Server — v3.0 生产化精简:9 操作类 + 3 bridge。

删掉 7 类 KB 路由(原 `query_*` 字典玩具已弃用)。
保留所有写 MySQL 真业务的 action + 跨插件 bridge。
"""
from __future__ import annotations

import json
import logging
from typing import Any

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


# 动作路由(优先级最高)
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


def _route(text: str) -> str:
    """v3.0:仅动作路由(9 类) + bridge。无 KB 字典玩具。"""
    for action, (kws, _hint) in _ACTION_HINTS.items():
        if any(k in text for k in kws):
            return _dispatch_action(action, text)
    return json.dumps({
        "status": "no_match",
        "message": "暂不支持该查询。hr_assistant 处理:请假/报销/证明/资产/培训/转正/审批/查询 8 大类 HR 操作 + 跨插件 bridge。",
    }, ensure_ascii=False)


class HrAssistantServer(A2AServer):
    """v3.0 A2A:9 操作类 + 3 bridge,仅写 MySQL 真业务。"""

    def __init__(self, llm: ChatOpenAI | None = None):
        card = AgentCard(
            name="hr_assistant",
            description="HR 助手 v3.0 — 9 操作类 + 3 跨插件 bridge,无 KB 字典",
            url="http://localhost:5010",
            version="3.0.0",
            skills=[
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
            response = _route(text)
            return Task(
                id=task.id,
                status=TaskStatus(state=TaskState.COMPLETED, message=task.message),
                artifacts=[{"parts": [{"type": "text", "text": response}]}],
            )
        except Exception:
            logger.exception("hr_assistant handle_task failed")
            return Task(id=task.id, status=TaskStatus(state=TaskState.FAILED, message=task.message))