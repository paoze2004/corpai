"""列飞书 bot 加入的群,返 (chat_id, name) 列表。

用法:
  PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python _2_scripts/list_feishu_chats.py

输出:
  - 调用 GET /open-apis/im/v1/chats
  - 列出 bot 加入的所有群,每个群 print "oc_xxx | 群名"
  - 复制 oc_xxx 填到 .env 的 FEISHU_TEST_RECEIVE_ID

依赖:
  - .env 里的 FEISHU_APP_ID + FEISHU_APP_SECRET(同 bootstrap_feishu_test.py)
  - bot 必须加入过群(在飞书群里"添加机器人"把 _0_CorpAI 运维机器人拉进去)

为什么独立脚本而不是塞进 feishu.py:
  - 列群是一次性工具,bootstrap 是常态工具,职责不同
  - list_chats 返回数据大,单独脚本更易调试
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _get_tenant_token(app_id: str, app_secret: str) -> str | None:
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10,
    )
    if r.status_code != 200:
        print(f"❌ tenant_access_token HTTP {r.status_code}: {r.text[:200]}")
        return None
    data = r.json()
    if data.get("code", -1) != 0:
        print(f"❌ tenant_access_token API: {data.get('msg')}")
        return None
    return data.get("tenant_access_token")


def list_chats(token: str) -> list[dict]:
    """调 /open-apis/im/v1/chats 返 [{chat_id, name}, ...]。

    分页:用 page_token 翻 page 直到 has_more=false。
    """
    url = "https://open.feishu.cn/open-apis/im/v1/chats"
    headers = {"Authorization": f"Bearer {token}"}
    out: list[dict] = []
    page_token = ""
    while True:
        params = {"page_size": 50}
        if page_token:
            params["page_token"] = page_token
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.status_code != 200:
            print(f"❌ /chats HTTP {r.status_code}: {r.text[:200]}")
            return out
        data = r.json()
        if data.get("code", -1) != 0:
            print(f"❌ /chats API: {data.get('msg')}")
            return out
        items = data.get("data", {}).get("items", [])
        out.extend(items)
        if not data.get("data", {}).get("has_more", False):
            break
        page_token = data.get("data", {}).get("page_token", "")
        if not page_token:
            break
    return out


def main() -> int:
    _load_dotenv()

    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not (app_id and app_secret):
        print("❌ .env 里缺 FEISHU_APP_ID 或 FEISHU_APP_SECRET")
        return 1

    print(f"app_id: {app_id}")
    print("取 tenant_access_token ...")
    token = _get_tenant_token(app_id, app_secret)
    if not token:
        return 2

    print("列 bot 加入的群 ...")
    chats = list_chats(token)
    if not chats:
        print()
        print("⚠ bot 没加入任何群 / 接口返空。")
        print("  → 在飞书里随便建一个群,把 _0_CorpAI 运维机器人拉进去,再跑一次")
        return 3

    print()
    print(f"找到 {len(chats)} 个群:")
    print()
    for c in chats:
        chat_id = c.get("chat_id", "")
        name = c.get("name", "(无名称)")
        description = c.get("description", "")
        print(f"  chat_id: {chat_id}")
        print(f"  name:    {name}")
        if description:
            print(f"  desc:    {description}")
        print()

    print("复制上方的 chat_id 填到 .env:")
    print("  FEISHU_TEST_RECEIVE_ID=oc_xxxxxxxxxxxxx")
    print()
    print("然后跑(--send 已经是默认,不再需要):")
    print("  PYTHONIOENCODING=utf-8 PYTHONPATH=. \\")
    print("    uv run python _2_scripts/bootstrap_feishu_test.py \\")
    print("    --create-plan \\")
    print("    --receive-id oc_xxxxxxxxxxxxx \\")
    print("    --receive-id-type chat_id")
    return 0


if __name__ == "__main__":
    sys.exit(main())
