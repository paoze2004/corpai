"""hr_assistant plugin 工具 — insurance + policy KB。"""
from __future__ import annotations

import json
from typing import Optional


# ────────── insurance_mcp(:8010)──────────

def query_insurance(
    insurance_type: str = "全部",
    age: Optional[int] = None,
    destination: Optional[str] = None,
) -> str:
    """查询保险产品。Phase 5 stub。"""
    products = [
        {"id": "I001", "type": "综合意外", "name": "员工综合意外险",
         "price": 280.0, "coverage": "意外身故/伤残 50万 + 医疗 5万",
         "scope": "全球(战争地区除外)"},
        {"id": "I002", "type": "医疗", "name": "员工百万医疗险",
         "price": 1200.0, "coverage": "住院 200万 + 门诊 1万 + 质子重离子",
         "scope": "中国大陆二级及以上公立医院"},
        {"id": "I003", "type": "境外", "name": "商务出行境外险",
         "price": 80.0, "coverage": "意外医疗 30万 + 行李 5000 + 航班延误 600",
         "scope": "全球,7-30 天,商务/旅游"},
    ]
    if insurance_type and insurance_type != "全部":
        products = [p for p in products if insurance_type in p["type"]]
    return json.dumps({
        "status": "success" if products else "no_data",
        "data": products,
        "message": "" if products else "未找到符合的保险产品。",
    }, ensure_ascii=False)


# ────────── policy_mcp(:8011)──────────

_POLICIES = [
    {"id": "P001", "topic": "年假", "content": "员工每年享受10天带薪年假,工作满5年增加5天。"},
    {"id": "P002", "topic": "病假", "content": "员工因病请假需提供医院证明,3天以内无需证明。"},
    {"id": "P003", "topic": "缺勤", "content": "缺勤须提前1天在OA提交申请,紧急情况电话通知主管。"},
    {"id": "P004", "topic": "报销", "content": "差旅费30天内提交报销,需发票+出差审批单。"},
    {"id": "P005", "topic": "调休", "content": "周末加班可申请调休,1天加班换1天调休,30天内使用。"},
]


def query_policy(topic: str = "") -> str:
    """查 HR 政策 KB。Phase 5:固定 5 条 + 关键词过滤。"""
    if topic:
        items = [p for p in _POLICIES if topic in p["topic"]]
    else:
        items = _POLICIES
    return json.dumps({
        "status": "success" if items else "no_data",
        "data": items,
        "message": "未找到相关政策。" if not items else "",
    }, ensure_ascii=False)
