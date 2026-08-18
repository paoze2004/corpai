"""v3.1 幂等迁移脚本 — RBAC scope rename devops:* → sre:*。

读 _3_sql/migrate_devops_scope_to_sre._3_sql 执行 UPDATE,加预览 + 影响行数。

跑法:`uv run python _2_scripts/migrate_devops_scope_to_sre.py`(--或 `--dry-run` 看预览)

幂等性:WHERE scope LIKE 'devops:%' 命中 0 行后 UPDATE 是 no-op,可以重跑。
"""
import argparse
import logging
import os
import sys
from pathlib import Path

import mysql.connector

# v3.2:加载 .env(.env 是单一配置源)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _0_CorpAI._3_utils.dotenv import load_env  # noqa: E402

load_env()

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


DB_HOST = os.environ.get("MYSQL_HOST", "localhost")
DB_USER = os.environ.get("MYSQL_USER", "admin")
DB_PASSWORD = os.environ.get("MYSQL_PASSWORD", "admin123456")
DB_NAME = os.environ.get("MYSQL_DATABASE", "_0_CorpAI")


def _connect():
    return mysql.connector.connect(
        host=DB_HOST, user=DB_USER,
        password=DB_PASSWORD, database=DB_NAME,
    )


def _preview(cur) -> tuple[int, int, list[tuple[str, str]]]:
    """返 (auth_role_scopes 命中数, auth_users.scopes 命中数, 前 10 条示例)。"""
    cur.execute(
        "SELECT role, scope FROM auth_role_scopes "
        "WHERE scope LIKE 'devops:%' LIMIT 100",
    )
    rs_rows = cur.fetchall()
    cur.execute(
        "SELECT user_id, scopes FROM auth_users "
        "WHERE scopes LIKE '%devops:%' LIMIT 10",
    )
    au_rows = cur.fetchall()
    return len(rs_rows), len(au_rows), rs_rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="v3.1 RBAC scope rename devops:* → sre:*",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只打印命中行,不 UPDATE",
    )
    args = parser.parse_args()

    try:
        conn = _connect()
    except Exception as e:
        logger.error(f"DB 连接失败: {e}")
        return 1

    cur = conn.cursor()
    rs_count, au_count, sample = _preview(cur)
    logger.info(f"=== 预览 ===")
    logger.info(f"auth_role_scopes 命中 devops:* 行:{rs_count}")
    logger.info(f"auth_users.scopes 含 devops:* 行:{au_count}")
    for role, scope in sample[:10]:
        new_scope = scope.replace("devops:", "sre:")
        logger.info(f"  示例:{role} | {scope} → {new_scope}")

    if rs_count == 0 and au_count == 0:
        logger.info("无 devops:* 残留,无需迁移(幂等性 OK)")
        cur.close()
        conn.close()
        return 0

    if args.dry_run:
        logger.info("dry-run 模式,跳过 UPDATE")
        cur.close()
        conn.close()
        return 0

    ddl_path = (
        Path(__file__).resolve().parents[1]
        / "_3_sql" / "migrate_devops_scope_to_sre._3_sql"
    )
    ddl_sql = ddl_path.read_text(encoding="utf-8")

    try:
        #  文件里 2 条 UPDATE,逐条跑方便统计
        stmts = [s.strip() for s in ddl_sql.split(";") if s.strip() and not s.strip().startswith("--")]
        for stmt in stmts:
            if stmt.upper().startswith("UPDATE"):
                cur.execute(stmt)
                logger.info(f"UPDATE 影响行数:{cur.rowcount}")
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"迁移失败: {e}")
        cur.close()
        conn.close()
        return 1

    cur.close()
    conn.close()
    logger.info("✅ v3.1 scope rename 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())