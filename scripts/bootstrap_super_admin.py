"""
Phase 3 引导脚本 — 创建第一个 super_admin。

用法:`uv run python scripts/bootstrap_super_admin.py admin`
      `uv run python scripts/bootstrap_super_admin.py alice` (任意 username)
环境变量:`AUTH_JWT_SECRET` 必须设置(失败 fail-closed)。

幂等:username 已存在则更新 password_hash,否则新建。
"""
from __future__ import annotations

import getpass
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mysql.connector

from CorpAI.platform.auth.passwords import hash_password


DB_HOST = os.getenv("MYSQL_HOST", "localhost")
DB_USER = os.getenv("MYSQL_USER", "admin")
DB_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
DB_NAME = os.getenv("MYSQL_DATABASE", "CorpAI")


def main() -> int:
    username = sys.argv[1] if len(sys.argv) > 1 else "admin"
    password = getpass.getpass(f"Password for {username} (min 8 chars): ")
    if not password or len(password) < 8:
        print("❌ 密码至少 8 位")
        return 1
    password_confirm = getpass.getpass("Confirm: ")
    if password != password_confirm:
        print("❌ 两次输入不一致")
        return 1

    # 检查 / 提示用户运行 migrate-phase3
    try:
        conn = mysql.connector.connect(
            host=DB_HOST, user=DB_USER,
            password=DB_PASSWORD, database=DB_NAME,
        )
    except Exception as e:
        print(f"❌ DB 连接失败: {e}")
        print("   提示:先跑 `make migrate-phase3`")
        return 1

    cur = conn.cursor()
    # 检查 auth_users 表是否存在
    cur.execute(
        """SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'auth_users'"""
    )
    if cur.fetchone()[0] == 0:
        cur.close()
        conn.close()
        print("❌ auth_users 表不存在,请先跑 `make migrate-phase3`")
        return 1

    # 1. 默认 tenant(幂等)
    cur.execute(
        """INSERT INTO auth_tenants (tenant_id, name)
           VALUES (%s, %s)
           ON DUPLICATE KEY UPDATE name = VALUES(name)""",
        ("default", "Default Tenant"),
    )

    # 2. 找现有 user 或建新
    cur.execute(
        "SELECT user_id FROM auth_users WHERE username = %s",
        (username,),
    )
    row = cur.fetchone()
    if row:
        user_id = row[0]
        cur.execute(
            "UPDATE auth_users SET password_hash = %s WHERE user_id = %s",
            (hash_password(password), user_id),
        )
        action = "更新密码"
    else:
        user_id = str(uuid.uuid4())
        cur.execute(
            """INSERT INTO auth_users
               (user_id, username, password_hash, tenant_id, role, is_active)
               VALUES (%s, %s, %s, 'default', 'super_admin', TRUE)""",
            (user_id, username, hash_password(password)),
        )
        action = "创建"

    conn.commit()
    cur.close()
    conn.close()
    print(f"✅ super_admin {action}: username={username}, user_id={user_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
