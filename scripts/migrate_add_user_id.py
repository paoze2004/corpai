"""
Phase 2 幂等迁移脚本。

通过 INFORMATION_SCHEMA.COLUMNS / STATISTICS / TABLES 守卫,每个 DDL 步骤
前先查存在性 — 已存在则 skip — 跑 1 次和 N 次结果一致。

跑法:`uv run python scripts/migrate_add_user_id.py`(或 `make migrate-phase2`)
"""
import logging
import os
import sys
from pathlib import Path

import mysql.connector

# v3.2:加载 .env(.env 是单一配置源)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from CorpAI.utils.dotenv import load_env  # noqa: E402

load_env()

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


# ──────────────────────── DB config ────────────────────────
DB_HOST = os.environ.get("MYSQL_HOST", "localhost")
DB_USER = os.environ.get("MYSQL_USER", "admin")
DB_PASSWORD = os.environ.get("MYSQL_PASSWORD", "admin123456")
DB_NAME = os.environ.get("MYSQL_DATABASE", "CorpAI")


# ──────────────────────── INFORMATION_SCHEMA 守卫 helpers ────────────────────────
def _column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        """SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = %s
             AND COLUMN_NAME = %s
           LIMIT 1""",
        (table, column),
    )
    return cur.fetchone() is not None


def _index_exists(cur, table: str, index: str) -> bool:
    cur.execute(
        """SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = %s
             AND INDEX_NAME = %s
           LIMIT 1""",
        (table, index),
    )
    return cur.fetchone() is not None


def _table_exists(cur, table: str) -> bool:
    cur.execute(
        """SELECT 1 FROM INFORMATION_SCHEMA.TABLES
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = %s""",
        (table,),
    )
    return cur.fetchone() is not None


def _has_pk_duplicate(cur) -> bool:
    """user_profiles PK 重构前,查 profile_key 是否跨 user_id 已有重复。
    新 PK 是 (user_id, profile_key),要求无重复。
    """
    cur.execute(
        """SELECT profile_key, COUNT(*) AS c
           FROM user_profiles
           GROUP BY profile_key
           HAVING c > 1
           LIMIT 1"""
    )
    return cur.fetchone() is not None


# ──────────────────────── Migration steps ────────────────────────
def _step_add_columns(cur, applied: list, skipped: list) -> None:
    """Step 1:加 user_id / session_id 列。"""
    columns_to_add = [
        ("short_term_messages", "user_id"),
        ("short_term_messages", "session_id"),
        ("user_profiles", "user_id"),
        ("query_history", "user_id"),
    ]
    for table, column in columns_to_add:
        if _column_exists(cur, table, column):
            skipped.append(f"column {table}.{column}")
        else:
            cur.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} VARCHAR(64) "
                f"NOT NULL DEFAULT 'legacy'"
            )
            applied.append(f"column {table}.{column}")


def _step_rebuild_profile_pk(cur, applied: list, skipped: list) -> None:
    """Step 2:重构 user_profiles PK 为 (user_id, profile_key)。
    有重复 profile_key 时 SKIP — 人工迁移数据。
    """
    if _has_pk_duplicate(cur):
        skipped.append("user_profiles PK rebuild (duplicate profile_key)")
        logger.warning("user_profiles PK 重构 SKIP: 存在跨 user 重复 profile_key")
        return

    # 先查 PK 是不是已经是 (user_id, profile_key) 复合键
    cur.execute(
        """SELECT COUNT(*) AS c FROM INFORMATION_SCHEMA.STATISTICS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'user_profiles'
             AND INDEX_NAME = 'PRIMARY'"""
    )
    pk_col_count = cur.fetchone()[0]
    if pk_col_count == 2:
        skipped.append("user_profiles PK rebuild (already composite)")
        return

    cur.execute("ALTER TABLE user_profiles DROP PRIMARY KEY")
    cur.execute(
        "ALTER TABLE user_profiles ADD PRIMARY KEY (user_id, profile_key)"
    )
    applied.append("user_profiles PK rebuild")


def _step_create_indexes(cur, applied: list, skipped: list) -> None:
    """Step 3:per-user 查询索引。"""
    indexes = [
        ("short_term_messages", "idx_short_user",
         "(user_id, session_id, message_order)"),
        ("query_history", "idx_entity_user", "(user_id, query_time)"),
        ("user_profiles", "idx_profile_user", "(user_id)"),
    ]
    for table, name, cols in indexes:
        if _index_exists(cur, table, name):
            skipped.append(f"index {table}.{name}")
        else:
            cur.execute(f"CREATE INDEX {name} ON {table}{cols}")
            applied.append(f"index {table}.{name}")


def _step_create_tables(cur, applied: list, skipped: list) -> None:
    """Step 4+5:task_context 和 cross_agent_context 新表。
    用 DDL 拼字符串(逻辑内嵌 SQL 已读,N+1 防注入:SQL 是写死字面量)。"""
    new_tables = [
        # task_context (Layer 4)
        ("task_context", """CREATE TABLE task_context (
    task_id      VARCHAR(64)  PRIMARY KEY,
    user_id      VARCHAR(64)  NOT NULL,
    session_id   VARCHAR(64)  NOT NULL,
    context_json JSON         NOT NULL,
    created_at   DATETIME     DEFAULT CURRENT_TIMESTAMP,
    expires_at   DATETIME     NOT NULL,
    INDEX idx_ttl  (expires_at),
    INDEX idx_user (user_id, session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Layer 4: 跨 Agent 共享任务上下文 (TTL 30min)'"""),
        # cross_agent_context (Layer 5)
        ("cross_agent_context", """CREATE TABLE cross_agent_context (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id      VARCHAR(64)  NOT NULL,
    session_id   VARCHAR(64)  NOT NULL,
    agent_id     VARCHAR(64)  NOT NULL,
    context_json JSON         NOT NULL,
    updated_at   DATETIME     DEFAULT CURRENT_TIMESTAMP
                             ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_user_agent (user_id, session_id, agent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Layer 5: 单 Agent 私有上下文(upsert 模式)'"""),
    ]
    for table_name, ddl in new_tables:
        if _table_exists(cur, table_name):
            skipped.append(f"table {table_name}")
        else:
            cur.execute(ddl)
            applied.append(f"table {table_name}")


# ──────────────────────── Main ────────────────────────
def main() -> int:
    """迁移入口。返回 0=成功,1=error。
    输出 'Phase 2 migration applied: applied=N skipped=M'"""
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
        )
    except Exception as e:
        logger.error(f"DB 连接失败: {e}")
        return 1

    cur = conn.cursor()
    applied: list[str] = []
    skipped: list[str] = []

    try:
        _step_add_columns(cur, applied, skipped)
        _step_rebuild_profile_pk(cur, applied, skipped)
        _step_create_indexes(cur, applied, skipped)
        _step_create_tables(cur, applied, skipped)
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
        f"Phase 2 migration applied: applied={len(applied)} skipped={len(skipped)}"
    )
    for item in applied:
        logger.info(f"  + {item}")
    for item in skipped:
        logger.info(f"  = {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
