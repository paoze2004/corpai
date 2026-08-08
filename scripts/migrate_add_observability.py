"""
Phase 4 幂等迁移脚本 — call_records 表。

通过 INFORMATION_SCHEMA.TABLES 守卫 — 跑 1 次和 N 次结果一致。

跑法:`uv run python scripts/migrate_add_observability.py`(或 `make migrate-phase4`)
"""
import logging
import sys
from pathlib import Path

import mysql.connector

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = "root"
DB_NAME = "CorpAI"


def _table_exists(cur, table: str) -> bool:
    cur.execute(
        """SELECT 1 FROM INFORMATION_SCHEMA.TABLES
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = %s LIMIT 1""",
        (table,),
    )
    return cur.fetchone() is not None


def main() -> int:
    try:
        conn = mysql.connector.connect(
            host=DB_HOST, user=DB_USER,
            password=DB_PASSWORD, database=DB_NAME,
        )
    except Exception as e:
        logger.error(f"DB 连接失败: {e}")
        return 1

    cur = conn.cursor()
    applied: list[str] = []
    skipped: list[str] = []

    # 读 SQL 文件(避免在 Python 和 SQL 各维护一份 DDL)
    ddl_path = Path(__file__).resolve().parents[1] / "sql" / "migrate_add_observability.sql"
    ddl_sql = ddl_path.read_text(encoding="utf-8")

    try:
        if _table_exists(cur, "call_records"):
            skipped.append("table call_records")
        else:
            cur.execute(ddl_sql)
            applied.append("table call_records")
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"迁移失败: {e}")
        cur.close()
        conn.close()
        return 1

    cur.close()
    conn.close()

    logger.info(
        f"Phase 4 migration applied: applied={len(applied)} skipped={len(skipped)}"
    )
    for item in applied:
        logger.info(f"  + {item}")
    for item in skipped:
        logger.info(f"  = {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())