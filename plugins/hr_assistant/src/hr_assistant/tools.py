"""hr_assistant plugin 工具 — 员工福利 + 政策 KB。

注意:不再保留任何旅行保险/出行险产品。福利数据是企业内部的:
五险一金 / 补充医疗 / 年度体检 / 团建经费 / 设备申请 / 培训报销。
"""
from __future__ import annotations

import json
from typing import Optional


# ────────── benefits_mcp(:8010)──────────

_BENEFITS = [
    {
        "id": "B001", "category": "社保",
        "name": "五险一金",
        "details": "养老/医疗/失业/工伤/生育保险 + 住房公积金;缴费基数与比例按当地社保政策执行,公司与个人各承担法定部分",
        "eligibility": "全员(入职次月起)",
        "contact": "HR 薪酬组",
    },
    {
        "id": "B002", "category": "补充医疗",
        "name": "员工商业医疗险",
        "details": "住院 100 万 + 门诊 2 万额度,二级及以上公立医院直付;含重疾绿色通道",
        "eligibility": "全员(入职即享)",
        "contact": "HR 福利组",
    },
    {
        "id": "B003", "category": "体检",
        "name": "年度体检",
        "details": "3000 元基础套餐 + 2000 元可选升级;每年 4-6 月统一预约,美年大健康/爱康国宾可选",
        "eligibility": "在职满 1 年",
        "contact": "HR 健康组",
    },
    {
        "id": "B004", "category": "团建",
        "name": "部门团建经费",
        "details": "人均 200 元/季度,部门负责人审批后由 HR 财务组打款;可跨季度累计",
        "eligibility": "全员",
        "contact": "直属上级 + HR",
    },
    {
        "id": "B005", "category": "设备",
        "name": "MacBook Pro 申请",
        "details": "研发岗标配 16 寸 M3 Pro;非研发岗需 CTO 特批;每 3 年可申请更新",
        "eligibility": "研发岗全员,其他岗特批",
        "contact": "IT 设备组",
    },
    {
        "id": "B006", "category": "培训",
        "name": "外部培训报销",
        "details": "上限 8000 元/年/人;需直属上级 + HR 双批;考试/认证类可放宽至 12000",
        "eligibility": "全员",
        "contact": "HR 培训组",
    },
    {
        "id": "B007", "category": "餐饮",
        "name": "加班餐补",
        "details": "工作日晚 8 点后下班可申请 50 元餐补;周末加班可申请 100 元/天",
        "eligibility": "全员",
        "contact": "直属上级",
    },
    {
        "id": "B008", "category": "通讯",
        "name": "通讯补贴",
        "details": "管理岗 300 元/月,技术骨干 200 元/月;按月打入工资",
        "eligibility": "M3 及以上 / 特殊技术岗",
        "contact": "HR 薪酬组",
    },
]


def query_benefits(
    category: Optional[str] = None,
    benefit_id: Optional[str] = None,
) -> str:
    """查询员工福利项目。

    Args:
        category: 福利类别(社保/补充医疗/体检/团建/设备/培训/餐饮/通讯)
        benefit_id: 直接查 B001-B008
    """
    items = _BENEFITS
    if benefit_id:
        items = [b for b in items if b["id"].upper() == benefit_id.upper()]
    elif category and category != "全部":
        items = [b for b in items if category in b["category"]]
    return json.dumps({
        "status": "success" if items else "no_data",
        "data": items,
        "message": "未找到符合条件的福利项目。" if not items else "",
    }, ensure_ascii=False)


# ────────── policy_mcp(:8011)──────────

_POLICIES = [
    {"id": "P001", "topic": "年假",
     "content": "员工每年享受 5 天带薪年假;工作满 10 年增加至 10 天;满 20 年增加至 15 天(依《职工带薪年休假条例》)。新员工按当年剩余日历天数折算。"},
    {"id": "P002", "topic": "病假",
     "content": "3 天以内病假无需医院证明;超过 3 天需提供二级以上医院诊断证明;连续病假最长 6 个月,医疗期工资按《企业职工患病或非因工负伤医疗期规定》执行。"},
    {"id": "P003", "topic": "缺勤",
     "content": "缺勤须提前 1 个工作日在 OA 提交申请;紧急情况先电话通知主管,24 小时内补单;未请假且未出勤按旷工处理。"},
    {"id": "P004", "topic": "报销",
     "content": "差旅/办公费用 30 天内提交报销;附原始发票(抬头公司全称)+ 事项说明;单笔 ≥ 5000 元需部门负责人 + 财务双批。"},
    {"id": "P005", "topic": "调休",
     "content": "周末加班 1:1 兑换调休;工作日延时加班按 4 小时起算可换 0.5 天调休;调休须 90 天内使用,过期作废。"},
    {"id": "P006", "topic": "婚假",
     "content": "依法登记结婚员工享受 10 天婚假(含周末);需提供结婚证复印件;须在登记后 12 个月内使用。"},
    {"id": "P007", "topic": "产假",
     "content": "女员工基础产假 158 天(难产+15 天,多胞胎每多一胎+15 天);男员工陪产假 15 天;依各地人口与计划生育条例调整。"},
    {"id": "P008", "topic": "丧假",
     "content": "直系亲属(父母/配偶/子女)去世 3 天;岳父母/公婆 3 天;需提供死亡证明或讣告。"},
    {"id": "P009", "topic": "离职",
     "content": "试用期内提前 3 天通知;转正后提前 30 天书面通知;交接清单由 HR 提供模板;最后一个工作日办结工资 + 社保转移。"},
    {"id": "P010", "topic": "考勤",
     "content": "弹性工作制:核心时间 10:00-16:00,其余时段 8 小时工作制即可;迟到 30 分钟内不扣款,超 30 分钟按事假 0.5 天计。"},
]


def query_policy(topic: str = "") -> str:
    """查 HR 政策 KB。topic 为空返回全部;否则按关键词过滤(子串匹配)。"""
    if topic:
        items = [p for p in _POLICIES if topic in p["topic"]]
    else:
        items = _POLICIES
    return json.dumps({
        "status": "success" if items else "no_data",
        "data": items,
        "message": "未找到相关政策。" if not items else "",
    }, ensure_ascii=False)