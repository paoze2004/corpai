"""
Bootstrap 3 个 plugin demo 用户 — 每个对应一个业务 plugin 的 RBAC 作用域。

用法:
    uv run python _2_scripts/bootstrap_plugin_users.py
    (用默认密码 CorpAI2026)
    或:
    uv run python _2_scripts/bootstrap_plugin_users.py --password mypass

为什么需要这个:平台设计有 super_admin / admin / agent_author / employee 4 个
内置角色,默认 scopes 列表里没有 plugin 专属 scope(hr:read、sre:read 等),
所以普通 admin 登录后调 HR plugin 会被 RBAC deny。演示"不同用户登录不同
业务系统"必须创建带正确 scopes 的用户。

3 个用户(scope 链完整演示):

  hr_alice  → employee + [hr:read, hr:write, knowledge:read]
              能用 HR plugin + 跨调 FAQ plugin
  sre_bob   → employee + [sre:read, sre:write, sre:approve, knowledge:read]
              能用 SRE plugin(含飞书审批) + 跨调 FAQ
  faq_carol → employee + [knowledge:read]
              只能用 FAQ plugin(只读)

幂等:用户名已存在则更新 password + scopes,否则新建。
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mysql.connector

from _0_CorpAI._2_platform.auth.passwords import hash_password


DB_HOST = os.getenv("MYSQL_HOST", "localhost")
DB_USER = os.getenv("MYSQL_USER", "admin")
DB_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
DB_NAME = os.getenv("MYSQL_DATABASE", "_0_CorpAI")


# 演示用户定义 — (username, password_default, role, extra_scopes_csv)
PLUGIN_USERS: list[tuple[str, str, str, str, str]] = [
    # username, default_pw, role, scopes_csv, description
    (
        "hr_alice", "CorpAI2026", "employee",
        "hr:read,hr:write,knowledge:read",
        "HR 助理用户:能用 HR plugin,跨调 FAQ 查规章制度",
    ),
    (
        "sre_bob", "CorpAI2026", "employee",
        "sre:read,sre:write,sre:approve,knowledge:read",
        "SRE Copilot 用户:含审批权限(飞书回调),可跨调 FAQ",
    ),
    (
        "faq_carol", "CorpAI2026", "employee",
        "knowledge:read",
        "FAQ 用户:只读权限,只能查企业 KB,不能调 HR/SRE",
    ),
]


def _connect() -> "mysql.connector.MySQLConnection":
    return mysql.connector.connect(
        host=DB_HOST, user=DB_USER,
        password=DB_PASSWORD, database=DB_NAME,
    )


def _ensure_schema(cur) -> None:
    """检查 auth_users + auth_tenants 表是否存在(同 bootstrap_super_admin 守卫)。"""
    cur.execute(
        """SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'auth_users'"""
    )
    if cur.fetchone()[0] == 0:
        raise SystemExit("❌ auth_users 表不存在,请先跑 `make migrate-phase3`")


def _ensure_default_tenant(cur, conn) -> None:
    cur.execute(
        """INSERT INTO auth_tenants (tenant_id, name)
           VALUES (%s, %s) ON DUPLICATE KEY UPDATE name = VALUES(name)""",
        ("default", "Default Tenant"),
    )
    conn.commit()


def _upsert_user(cur, username: str, password: str, role: str, scopes: str) -> str:
    """新建或更新 user,返 user_id。"""
    cur.execute("SELECT user_id FROM auth_users WHERE username = %s", (username,))
    row = cur.fetchone()
    pwhash = hash_password(password)
    if row:
        user_id = row[0]
        cur.execute(
            """UPDATE auth_users
               SET password_hash = %s, role = %s, scopes = %s, is_active = TRUE
               WHERE user_id = %s""",
            (pwhash, role, scopes, user_id),
        )
        action = "更新"
    else:
        user_id = str(uuid.uuid4())
        cur.execute(
            """INSERT INTO auth_users
               (user_id, username, password_hash, tenant_id, role, scopes, is_active)
               VALUES (%s, %s, %s, 'default', %s, %s, TRUE)""",
            (user_id, username, pwhash, role, scopes),
        )
        action = "创建"
    return user_id, action


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--password", default=None,
        help="统一密码(默认 CorpAI2026;生产必改)",
    )
    args = parser.parse_args()

    pw = args.password or "CorpAI2026"
    if len(pw) < 8:
        print("❌ 密码至少 8 位")
        return 1

    conn = _connect()
    cur = conn.cursor()
    try:
        _ensure_schema(cur)
        _ensure_default_tenant(cur, conn)

        print(f"🔧 引导 3 个 plugin demo 用户(密码={pw!r}):\n")
        for username, default_pw, role, scopes, desc in PLUGIN_USERS:
            user_id, action = _upsert_user(cur, username, pw, role, scopes)
            print(f"  ✅ {action} {username} (role={role}, scopes={scopes})")
            print(f"     {desc}")
            print(f"     user_id={user_id}\n")
        conn.commit()
    finally:
        cur.close()
        conn.close()

    print("💡 演示用法:")
    print("   1. 用 hr_alice 登录 chat → 问'请年假' → HR plugin 响应")
    print("   2. 用 sre_bob 登录 → 问'CPU 飙高怎么办' → SRE plugin 响应(可发飞书审批)")
    print("   3. 用 faq_carol 登录 → 问'年假怎么算' → FAQ plugin 响应")
    print("   4. 演示 RBAC deny:用 faq_carol 问'请年假' → 401(只有 knowledge:read 缺 hr:write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())