"""
天气 Agent 测试脚本
访问地址：http://127.0.0.1:5005/
测试方式：通过 A2A 协议向 WeatherQueryAssistant 发送任务，打印返回结果
"""

import requests
import json

AGENT_URL = "http://127.0.0.1:5005/tasks/send"

# ==================== 测试用例 ====================
TEST_CASES = [
    {
        "name": "用例1：精确城市 + 精确日期",
        "input": "帮我查一下北京2026年5月28日的天气",
        "desc": "测试基础查询：城市+日期完整参数"
    },
    {
        "name": "用例2：精确城市 + 日期范围",
        "input": "成都6月1日到6月5日的天气怎么样",
        "desc": "测试日期范围查询"
    },
    {
        "name": "用例3：相对时间（今天）",
        "input": "北京今天天气如何",
        "desc": "测试相对时间识别（需 LLM 将'今天'转为具体日期）"
    },
    {
        "name": "用例4：只有城市，没有日期",
        "input": "三亚天气怎么样",
        "desc": "测试信息不足时 LLM 是否追问日期"
    },
    {
        "name": "用例5：不存在的城市",
        "input": "帮我查一下瓦坎达2026年6月1日的天气",
        "desc": "测试无效城市时的兜底提示"
    },
]


def send_task(user_input: str) -> dict:
    """向 Agent 发送 A2A 任务"""
    payload = {
        "message": {
            "content": {
                "text": user_input
            }
        }
    }
    try:
        resp = requests.post(AGENT_URL, json=payload, timeout=60)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    print("=" * 60)
    print("天气 Agent 测试（共 {} 个用例）".format(len(TEST_CASES)))
    print("Agent 地址：http://127.0.0.1:5005/")
    print("=" * 60)

    results = []
    for i, case in enumerate(TEST_CASES, 1):
        print(f"\n{'─' * 60}")
        print(f"[{case['name']}]")
        print(f"测试目的：{case['desc']}")
        print(f"用户输入：{case['input']}")
        print(f"{'─' * 60}")

        resp = send_task(case["input"])
        # 提取任务状态和返回内容
        status = resp.get("status", {})
        state = status.get("state", "UNKNOWN") if isinstance(status, dict) else "UNKNOWN"
        message = status.get("message", {}) if isinstance(status, dict) else {}
        text = (message.get("content", {}).get("text", "") if isinstance(message, dict) else "")
        artifacts = resp.get("artifacts", [])
        artifact_text = ""
        if artifacts and isinstance(artifacts, list) and len(artifacts) > 0:
            parts = artifacts[0].get("parts", [])
            if parts:
                artifact_text = parts[0].get("text", "")

        print(f"任务状态：{state}")
        if artifact_text:
            print(f"返回结果：{artifact_text[:500]}")
        elif text:
            print(f"Agent 回复：{text[:500]}")
        elif "error" in resp:
            print(f"错误信息：{resp['error']}")
        else:
            print(f"原始响应：{json.dumps(resp, ensure_ascii=False)[:300]}")

        results.append({
            "case": case["name"],
            "state": state,
            "has_result": bool(artifact_text or text)
        })

    # ==================== 汇总 ====================
    print(f"\n{'=' * 60}")
    print("测试结果汇总")
    print(f"{'=' * 60}")
    print(f"{'用例':<30} {'状态':<15} {'有返回'}")
    print("-" * 60)
    for r in results:
        mark = "✓" if r["has_result"] else "✗"
        print(f"{r['case']:<30} {r['state']:<15} {mark}")
