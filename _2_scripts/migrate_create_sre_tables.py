"""跑 _3_sql/create_sre_tables._3_sql。

用法:
    uv run python _2_scripts/migrate_create_sre_tables.py
    uv run python _2_scripts/migrate_create_sre_tables.py --dry-run   # 只看 SQL,不执行

读 .env 拿 MYSQL_HOST/PORT/USER/PASSWORD,执行 SQL 文件。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# v3.2:加载 .env(.env 是单一配置源)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _0_CorpAI._3_utils.dotenv import load_env  # noqa: E402

load_env()

# 项目根 = _2_scripts 的父目录
ROOT = Path(__file__).resolve().parent.parent
SQL_FILE = ROOT / "_3_sql" / "create_sre_tables._3_sql"

# 加载 .env(必须,不要 from .env.example)
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        import os
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _split_sql(sql: str) -> list[str]:
    """按 `;` 拆语句(忽略注释行)。"""
    out: list[str] = []
    buf: list[str] = []
    for raw in sql.splitlines():
        line = raw.strip()
        if not line or line.startswith("--"):
            continue
        buf.append(raw)
        if line.endswith(";"):
            stmt = "\n".join(buf).rstrip(";").strip()
            if stmt:
                out.append(stmt)
            buf = []
    if buf:
        tail = "\n".join(buf).strip().rstrip(";")
        if tail:
            out.append(tail)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="只看 SQL,不连接 MySQL")
    args = parser.parse_args()

    if not SQL_FILE.exists():
        print(f"❌ {SQL_FILE} 不存在")
        return 1

    sql_text = SQL_FILE.read_text(encoding="utf-8")
    statements = _split_sql(sql_text)
    print(f"📜 {SQL_FILE.name}:共 {len(statements)} 条 DDL")

    if args.dry_run:
        for i, stmt in enumerate(statements, 1):
            first_line = stmt.splitlines()[0][:80]
            print(f"  [{i}] {first_line}...")
        return 0

    # 真接 MySQL
    try:
        import pymysql
    except ImportError:
        print("❌ 缺 pymysql — uv add pymysql")
        return 1

    host = __import__("os").environ.get("MYSQL_HOST", "localhost")
    port = int(__import__("os").environ.get("MYSQL_PORT", "3306"))
    user = __import__("os").environ.get("MYSQL_USER", "admin")
    password = __import__("os").environ.get("MYSQL_PASSWORD", "admin123456")
    database = __import__("os").environ.get("MYSQL_DATABASE", "_0_CorpAI")

    print(f"🔌 连接 MySQL {host}:{port} user={user} db={database}")
    try:
        conn = pymysql.connect(
            host=host, port=port, user=user, password=password,
            database=database, charset="utf8mb4",
            autocommit=True,
        )
    except Exception as exc:
        print(f"❌ 连接失败:{exc}")
        return 1

    cursor = conn.cursor()
    ok = 0
    for i, stmt in enumerate(statements, 1):
        first_line = stmt.splitlines()[0][:80]
        try:
            cursor.execute(stmt)
            print(f"  ✅ [{i}] {first_line}")
            ok += 1
        except Exception as exc:
            print(f"  ❌ [{i}] {first_line}\n     {exc}")
            return 1

    cursor.close()
    conn.close()
    print(f"\n🎉 DDL 应用完成 {ok}/{len(statements)}")
    print("📋 验证:")
    for tbl in ("sre_incidents", "sre_action_plans", "sre_audit_log"):
        print(f"  - SELECT COUNT(*) FROM {tbl};")
    return 0


if __name__ == "__main__":
    sys.exit(main())
