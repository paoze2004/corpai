"""hr_assistant MCP servers — 官方 MCP 协议实现(fastmcp 3.x)。

暴露 actions.py 里的 HR 操作类工具为标准 MCP tools。
StreamableHTTP transport, JSON-RPC 2.0 wire。

启动方式:`python -m hr_assistant.mcp_main`
"""
from __future__ import annotations

import logging
from typing import Optional

from fastmcp import FastMCP

from hr_assistant import actions as a

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════
#  :8001 ─ HR 操作全集
# ═══════════════════════════════════════════════════════════════════════

hr_server = FastMCP(
    name="hr_assistant",
    instructions=(
        "HR 助手操作类工具集:请假/报销/证明/资产/培训/转正/审批/查询 8 大类。"
        "所有写操作需 hr:write;查询需 hr:read。"
    ),
)


@hr_server.tool()
def submit_leave(
    authorization: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    days: float,
    reason: str,
) -> str:
    """提交请假申请(年假/病假/事假等)。

    Args:
        authorization: Bearer token(用户 JWT)
        leave_type: annual/sick/personal/...
        start_date: 开始日期(YYYY-MM-DD)
        end_date: 结束日期(YYYY-MM-DD)
        days: 请假天数
        reason: 原因
    """
    return a.submit_leave(
        authorization=authorization, leave_type=leave_type,
        start_date=start_date, end_date=end_date,
        days=days, reason=reason,
    )


@hr_server.tool()
def submit_reimbursement(
    authorization: str,
    category: str,
    amount: float,
    description: str,
    currency: str = "CNY",
    invoice_url: Optional[str] = None,
) -> str:
    """提交报销申请。

    Args:
        authorization: Bearer token
        category: travel/office/training/meal/other
        amount: 金额
        description: 描述
        currency: 币种,默认 CNY
        invoice_url: 发票 URL(可选)
    """
    return a.submit_reimbursement(
        authorization=authorization, category=category,
        amount=amount, description=description,
        currency=currency, invoice_url=invoice_url,
    )


@hr_server.tool()
def apply_certificate(
    authorization: str,
    cert_type: str,
    purpose: str,
    language: str = "zh",
    quantity: int = 1,
    deliver_method: str = "email",
) -> str:
    """申请证明(在职/收入/离职/工作居住证)。

    Args:
        authorization: Bearer token
        cert_type: employment/income/separation/work_permit
        purpose: 用途
        language: zh/en
        quantity: 份数
        deliver_method: email/paper
    """
    return a.apply_certificate(
        authorization=authorization, cert_type=cert_type,
        purpose=purpose, language=language,
        quantity=quantity, deliver_method=deliver_method,
    )


@hr_server.tool()
def request_asset(
    authorization: str,
    asset_type: str,
    reason: str,
    sku: Optional[str] = None,
    estimated_cost: Optional[float] = None,
) -> str:
    """申请资产(笔记本/显示器/键盘/耳机等)。

    Args:
        authorization: Bearer token
        asset_type: laptop/monitor/keyboard/headphone/...
        reason: 原因
        sku: 型号(SKU 可选)
        estimated_cost: 预估成本(可选)
    """
    return a.request_asset(
        authorization=authorization, asset_type=asset_type,
        reason=reason, sku=sku, estimated_cost=estimated_cost,
    )


@hr_server.tool()
def register_training(
    authorization: str,
    training_name: str,
    training_type: str,
    business_relevance: str,
    provider: Optional[str] = None,
    expected_cost: Optional[float] = None,
) -> str:
    """报名培训(外部/内部/认证)。

    Args:
        authorization: Bearer token
        training_name: 培训名
        training_type: external/internal/certification
        business_relevance: 业务相关性说明
        provider: 培训机构(可选)
        expected_cost: 预期费用(可选)
    """
    return a.register_training(
        authorization=authorization, training_name=training_name,
        training_type=training_type, business_relevance=business_relevance,
        provider=provider, expected_cost=expected_cost,
    )


@hr_server.tool()
def apply_regularization(
    authorization: str,
    probation_start: str,
    probation_end: str,
    achievements: str,
    self_assessment: Optional[str] = None,
) -> str:
    """申请试用期转正。

    Args:
        authorization: Bearer token
        probation_start: 试用开始日期
        probation_end: 试用结束日期
        achievements: 主要成绩
        self_assessment: 自我评估(可选)
    """
    return a.apply_regularization(
        authorization=authorization, probation_start=probation_start,
        probation_end=probation_end, achievements=achievements,
        self_assessment=self_assessment,
    )


@hr_server.tool()
def cancel_leave(authorization: str, request_id: str) -> str:
    """撤销请假申请(只能撤销 pending 状态)。

    Args:
        authorization: Bearer token
        request_id: 申请 ID(L 开头)
    """
    return a.cancel_leave(authorization=authorization, request_id=request_id)


@hr_server.tool()
def approve_request(
    authorization: str,
    request_id: str,
    target_type: str,
    action: str,
    approval_note: Optional[str] = None,
) -> str:
    """审批申请(approve/reject)。

    Args:
        authorization: Bearer token
        request_id: 申请 ID
        target_type: leave/reimbursement/certificate/asset/training/regularization
        action: approve/reject
        approval_note: 审批备注(reject 必填)
    """
    return a.approve_request(
        authorization=authorization, request_id=request_id,
        target_type=target_type, action=action,
        approval_note=approval_note,
    )


@hr_server.tool()
def query_my_requests(
    authorization: str,
    target_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 10,
) -> str:
    """查我的申请列表。

    Args:
        authorization: Bearer token
        target_type: leave/reimbursement/...(可选)
        status: pending/approved/rejected/cancelled(可选)
        limit: 返回条数
    """
    return a.query_my_requests(
        authorization=authorization, target_type=target_type,
        status=status, limit=limit,
    )


SERVER_PORTS = [
    (hr_server, 8001),
]