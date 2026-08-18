"""v3.3 migration — sre_action_plans.message_id 列。"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import mysql.connector

# v3.2:统一 .env loader
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _0_CorpAI._3_utils.dotenv import load_env  # noqa: E402

load_env()

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


DB_HOST = os.environ.get("MYSQL_HOST", "localhost")
DB_USER = os.environ.get("MYSQL_USER", "admin")
DB_PASSWORD = os.environ.get("MYSQL_PASSWORD", "admin123456")
DB_NAME = os.environ.get("MYSQL_DATABASE", "_0_CorpAI")


def _column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s LIMIT 1",
        (table, column),
    )
    return cur.fetchone() is not None


def _index_exists(cur, table: str, index: str) -> bool:
    cur.execute(
        "SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND INDEX_NAME = %s LIMIT 1",
        (table, index),
    )
    return cur.fetchone() is not None


def main() -> int:
    try:
        conn = mysql.connector.connect(
            host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME,
        )
    except Exception as e:
        logger.error(f"DB 连接失败:{e}")
        return 1
    cur = conn.cursor()
    applied = []
    skipped = []
    try:
        if _column_exists(cur, "sre_action_plans", "message_id"):
            skipped.append("column message_id")
        else:
            cur.execute(
                "ALTER TABLE sre_action_plans "
                "ADD COLUMN message_id VARCHAR(64) NOT NULL DEFAULT '' "
                "COMMENT '飞书消息 ID,审批后 PATCH 替换卡片'"
            )
            applied.append("column message_id")
        if _index_exists(cur, "sre_action_plans", "idx_message_id"):
            skipped.append("index idx_message_id")
        else:
            cur.execute("ALTER TABLE sre_action_plans ADD INDEX idx_message_id (message_id)")
            applied.append("index idx_message_id")
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"迁移失败:{e}")
        cur.close()
        conn.close()
        return 1
    cur.close()
    conn.close()
    logger.info(
        f"v3.3 migration applied: applied={len(applied)} skipped={len(skipped)}"
    )
    for a in applied:
        logger.info(f"  + {a}")
    for s in skipped:
        logger.info(f"  = {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())