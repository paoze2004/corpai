"""Bootstrap Feishu Test — 真发飞书卡 + 验证集成是否配通。

不依赖任何外部 worker,纯单次脚本:
  1. 读 .env 中的 FEISHU_APP_ID / FEISHU_APP_SECRET
  2. 校验配置齐全 + 取 tenant_access_token(走飞书 API)
  3. 默认真发:构造 incident 卡片 → 打印 JSON → POST 飞书
  4. 加 --dry-run 才只打印不发(用来离线调试卡片结构)
  5. 加 --create-plan 才在 DB 写真 pending plan(点 ✅ 真能 approve)

用法:

    # 默认行为:真发到 .env 里的 FEISHU_TEST_RECEIVE_ID
    uv run python scripts/bootstrap_feishu_test.py --create-plan

    # 真发到指定 chat(覆盖 .env 默认)
    uv run python scripts/bootstrap_feishu_test.py --create-plan \\
        --receive-id oc_xxxxxxxxxxxxx \\
        --receive-id-type chat_id

    # 只看卡片 JSON,不真发
    uv run python scripts/bootstrap_feishu_test.py --dry-run

    # 不写 DB(只测发卡通道,按钮回调进来 plan 不存在会 404)
    uv run python scripts/bootstrap_feishu_test.py \\
        --receive-id oc_xxx --receive-id-type chat_id

输出:
  配置缺失 → 列出缺哪几项,跳过发卡
  配置齐全 + 默认 → 打印卡片 JSON + 调飞书 API + 打印 message_id
  --dry-run → 只打印卡片 JSON,不发
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import logging

logger = logging.getLogger(__name__)

# v3.2:统一从 CorpAI.utils.dotenv 加载 .env(单一配置源)
# 顺便把项目根加进 sys.path(允许 `from CorpAI.xxx import yyy`)
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
# 也加 plugins/sre_copilot/src 让 sre_copilot.feishu 能 import(没装 pip 包时)
sre_plugin_src = project_root / "plugins" / "sre_copilot" / "src"
if sre_plugin_src.exists() and str(sre_plugin_src) not in sys.path:
    sys.path.insert(0, str(sre_plugin_src))
from CorpAI.utils.dotenv import load_env  # noqa: E402

load_env()


def _check_config() -> tuple[bool, list[str]]:
    """返 (是否齐, 缺哪几项)。

    必填只查 APP_ID + APP_SECRET(发卡 token 所需)。
    VERIFY_TOKEN / ENCRYPT_KEY 是加密场景的可选项,新版事件订阅 url_verification 不强制。
    """
    required = ["FEISHU_APP_ID", "FEISHU_APP_SECRET"]
    missing = [k for k in required if not os.environ.get(k)]
    return (len(missing) == 0, missing)


def _create_pending_plan(
    incident_id: str, plan_json: str, risk_level: str,
    service: str, severity: str,
) -> tuple[int, str]:
    """写真 plan 到 DB,返 (plan_id, approval_token)。

    1. 先 INSERT IGNORE 占位 incident(sre_action_plans 有外键到 sre_incidents)
    2. 再调 ApprovalService.store_pending_plan
    """
    from CorpAI.platform.db import DatabasePool
    from CorpAI.platform.sre.approval import ApprovalService

    # 1) 占位 incident(外键依赖)
    pool = DatabasePool.get()
    conn = pool.get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT IGNORE INTO sre_incidents "
            "(incident_id, fingerprint, service, severity, status, "
            " plan_id, first_alert_at, last_alert_at) "
            "VALUES (%s, LEFT(MD5(%s), 16), %s, %s, 'open', 0, NOW(), NOW())",
            (incident_id, incident_id, service, severity),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()

    # 2) 写真 plan(ApprovalService 保证 token 规则一致)
    svc = ApprovalService()
    return svc.store_pending_plan(
        incident_id=incident_id,
        plan_json=plan_json,
        risk_level=risk_level,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap Feishu test — 验证飞书集成配置",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只打印卡片 JSON,不真发飞书(默认是真发)",
    )
    parser.add_argument(
        "--no-create-plan", dest="create_plan", action="store_false",
        help="**不写真 plan(只测发卡通道)** —— 默认写真,approve 按钮能真生效",
    )
    parser.set_defaults(create_plan=True)
    parser.add_argument(
        "--receive-id", default=os.environ.get("FEISHU_TEST_RECEIVE_ID", ""),
        help="飞书 receive_id(open_id / chat_id / email)",
    )
    parser.add_argument(
        "--receive-id-type", default="chat_id",
        choices=["open_id", "chat_id", "email", "union_id"],
        help="receive_id 类型(默认 chat_id)",
    )
    parser.add_argument(
        "--incident-id", default="INC-BOOTSTRAP-001",
        help="Incident ID(用于卡片展示)",
    )
    parser.add_argument(
        "--service", default="payment-api",
        help="受影响 service",
    )
    parser.add_argument(
        "--severity", default="critical",
        choices=["critical", "error", "warning", "info"],
    )
    parser.add_argument(
        "--risk-level", default="high",
        choices=["low", "medium", "high"],
    )
    parser.add_argument(
        "--plan-summary",
        default="AI 建议:重启 payment-api deployment,先切走 10% 流量观察 60s 后观察 latency",
    )
    args = parser.parse_args()

    # .env 在模块顶部已加载(load_env())。此处不再需要。

    print("=" * 60)
    print("Feishu Bootstrap Test")
    print("=" * 60)

    # 1) 配置检查
    ok, missing = _check_config()
    print(f"配置检查:{'OK' if ok else 'FAIL'}")
    if not ok:
        print(f"  缺:{missing}")
        print("  → 在 .env 填这 3 个值:")
        print("     FEISHU_APP_ID=cli_xxxxxxxxxxxxx")
        print("     FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        print("     FEISHU_VERIFY_TOKEN=your_verify_token")
        if args.dry_run:
            print()
            print("  dry-run 模式继续(只构造卡片不发)")
        else:
            print()
            print("  真发必须凭证齐才有效,加 --dry-run 调试")
    print()

    # 2) 准备 plan_id + token
    plan_id = 1
    token = "dry_run_token_only"
    if args.create_plan:
        if args.dry_run:
            print("⚠ --no-create-plan 没加(默认写真)+ --dry-run 在:写真 DB 但不发飞书,plan 没人收")
        plan_json = json.dumps({
            "actions": [
                {"tool": "restart_deployment", "args": {
                    "deployment": args.service, "namespace": "default",
                }},
            ],
        }, ensure_ascii=False)
        try:
            plan_id, token = _create_pending_plan(
                incident_id=args.incident_id,
                plan_json=plan_json,
                risk_level=args.risk_level,
                service=args.service,
                severity=args.severity,
            )
            print(f"✅ plan 已写入 DB:plan_id={plan_id} token={token[:8]}...")
        except Exception as exc:
            print(f"❌ plan 写入失败:{exc}")
            print("   检查 .env 里 MYSQL_* 是否对 + corp_ai_pool 是否能连")
            return 2
        print()

    print("按钮回调方式:飞书事件订阅 → POST /feishu/event")
    print(f"  plan_id={plan_id} token={token[:8]}... 会塞进按钮 value")
    print()

    # 4) 构造卡片
    from sre_copilot.feishu import build_incident_card
    card = build_incident_card(
        incident_id=args.incident_id,
        service=args.service,
        severity=args.severity,
        plan_summary=args.plan_summary,
        risk_level=args.risk_level,
        plan_id=plan_id,
        approval_token=token,
    )
    print("卡片 JSON:")
    print(json.dumps(card, ensure_ascii=False, indent=2))
    print()

    # 5) 发卡(dry-run 模式不发,直接返回)
    if args.dry_run:
        print("ℹ dry-run 模式,没真发飞书。")
        print("  默认行为就是真发,把 --dry-run 去掉即可")
        if not args.create_plan:
            print("  想要 approve 真生效:再加 --create-plan")
        return 0

    if not ok:
        print("❌ 真发需要 FEISHU_* 全齐,见上方缺失列表")
        return 1

    if not args.receive_id:
        print("❌ 真发必须给 --receive-id(否则不知道发给谁)")
        print("   建议:在 .env 写 FEISHU_TEST_RECEIVE_ID=oc_xxx 全局复用")
        return 1

    from sre_copilot.feishu import send_approval_card
    result = send_approval_card(
        receive_id=args.receive_id,
        receive_id_type=args.receive_id_type,
        incident_id=args.incident_id,
        service=args.service,
        severity=args.severity,
        plan_summary=args.plan_summary,
        risk_level=args.risk_level,
        plan_id=plan_id,
        approval_token=token,
    )
    print("发送结果:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("status") == "sent":
        # v3.3:把 message_id 写真到 plan(供 callback 后 PATCH 卡片用)
        msg_id = result.get("message_id", "")
        logger.info(f"[BOOT-SAVE] send result status={result.get('status')} msg_id={msg_id!r} plan_id={plan_id}")
        if msg_id and plan_id and token != "dry_run_token_only":
            try:
                from CorpAI.platform.db import DatabasePool
                pool = DatabasePool.get()
                conn = pool.get_conn()
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE sre_action_plans SET message_id=%s WHERE id=%s",
                        (msg_id, plan_id),
                    )
                    affected = cur.rowcount
                    conn.commit()
                    cur.close()
                finally:
                    conn.close()
                logger.info(
                    f"[BOOT-SAVE] UPDATE message_id={msg_id} WHERE id={plan_id}"
                    f" → rowcount={affected}"
                )
                print(f"   message_id={msg_id} 已写入 plan_id={plan_id} (rowcount={affected})")
            except Exception as exc:
                logger.warning(f"写真 message_id 失败(不影响发卡):{exc}")
        else:
            logger.warning(
                f"[BOOT-SAVE] 跳过写真: msg_id={msg_id!r} plan_id={plan_id} token={token[:8]}"
            )
        print()
        print("✅ 飞书卡片已发出 — 检查手机/PC 飞书是否收到。")
        print("   点 ✅/❌ 按钮测试回调 → sre_action_plans 表 status 改变,")
        print("   飞书卡片按钮会被 PATCH 替换成锁定状态(不再可点)。")
        return 0
    print()
    print("❌ 发送失败 — 看上面 result['kind'] 排查")
    return 3


if __name__ == "__main__":
    sys.exit(main())
