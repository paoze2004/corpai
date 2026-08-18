"""
Phase 3 幂等迁移脚本 — auth_ 4 张表 + 角色→scope 种子。

通过 INFORMATION_SCHEMA.TABLES 守卫,每个 DDL 步骤前先查存在性 —
已存在则 skip。跑 1 次和 N 次结果一致。

跑法:`uv run python _2_scripts/migrate_add_auth.py`(或 `make migrate-phase3`)
"""
import logging
import sys
from pathlib import Path

import mysql.connector

# v3.2:加载 .env(.env 是单一配置源)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _0_CorpAI._3_utils.dotenv import load_env  # noqa: E402

load_env()

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


# ──────────────────────── DB config(本地默认走 .env 加载后的 os.environ)────────────────────────
import os

DB_HOST = os.environ.get("MYSQL_HOST", "localhost")
DB_USER = os.environ.get("MYSQL_USER", "admin")
DB_PASSWORD = os.environ.get("MYSQL_PASSWORD", "admin123456")
DB_NAME = os.environ.get("MYSQL_DATABASE", "_0_CorpAI")


# ──────────────────────── INFORMATION_SCHEMA 守卫 helpers ────────────────────────
def _table_exists(cur, table: str) -> bool:
    cur.execute(
        """SELECT 1 FROM INFORMATION_SCHEMA.TABLES
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""",
        (table,),
    )
    return cur.fetchone() is not None


# ──────────────────────── 4 张 auth 表 DDL(从 _3_sql/migrate_add_auth._3_sql 复制,这里是 IN-DDL )────────────────────────
_DDL_AUTH_TENANTS = """CREATE TABLE auth_tenants (
    tenant_id   VARCHAR(64)  PRIMARY KEY,
    name        VARCHAR(128) NOT NULL,
    is_active   BOOLEAN      DEFAULT TRUE,
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

_DDL_AUTH_USERS = """CREATE TABLE auth_users (
    user_id        VARCHAR(64)  PRIMARY KEY,
    username       VARCHAR(64)  UNIQUE NOT NULL,
    password_hash  VARCHAR(256) NOT NULL,
    tenant_id      VARCHAR(64)  NOT NULL,
    role           VARCHAR(32)  NOT NULL,
    scopes         TEXT,
    is_active      BOOLEAN      DEFAULT TRUE,
    created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
    last_login_at  DATETIME     NULL,
    INDEX idx_tenant (tenant_id),
    INDEX idx_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

_DDL_AUTH_ROLE_SCOPES = """CREATE TABLE auth_role_scopes (
    role   VARCHAR(32) NOT NULL,
    scope  VARCHAR(64) NOT NULL,
    PRIMARY KEY (role, scope)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

_DDL_AUTH_AUDIT_LOG = """CREATE TABLE auth_audit_log (
    id         BIGINT       AUTO_INCREMENT PRIMARY KEY,
    ts         DATETIME(3)  DEFAULT CURRENT_TIMESTAMP(3),
    user_id    VARCHAR(64)  NOT NULL,
    tenant_id  VARCHAR(64)  NOT NULL,
    action     VARCHAR(64)  NOT NULL,
    target     VARCHAR(256),
    ip         VARCHAR(64),
    user_agent TEXT,
    result     VARCHAR(32)  NOT NULL,
    reason     TEXT,
    INDEX idx_user_ts   (user_id, ts),
    INDEX idx_tenant_ts (tenant_id, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

_DDL_INDEX_AUTH_ROLE = (
    "CREATE INDEX idx_short_user ON short_term_messages(user_id, session_id, message_order)"
    if False else None  # 占位;实际 index 在 Phase 2 migrate
)


# ──────────────────────── Migration steps ────────────────────────
def _step_create_auth_tenants(cur, applied, skipped):
    if _table_exists(cur, "auth_tenants"):
        skipped.append("table auth_tenants")
    else:
        cur.execute(_DDL_AUTH_TENANTS)
        applied.append("table auth_tenants")


def _step_create_auth_users(cur, applied, skipped):
    if _table_exists(cur, "auth_users"):
        skipped.append("table auth_users")
    else:
        cur.execute(_DDL_AUTH_USERS)
        applied.append("table auth_users")


def _step_create_auth_role_scopes(cur, applied, skipped):
    if _table_exists(cur, "auth_role_scopes"):
        skipped.append("table auth_role_scopes")
    else:
        cur.execute(_DDL_AUTH_ROLE_SCOPES)
        applied.append("table auth_role_scopes")


def _step_create_auth_audit_log(cur, applied, skipped):
    if _table_exists(cur, "auth_audit_log"):
        skipped.append("table auth_audit_log")
    else:
        cur.execute(_DDL_AUTH_AUDIT_LOG)
        applied.append("table auth_audit_log")


def _step_seed_role_scopes(cur, applied, skipped):
    """seed 4 角色 × 8 scope 映射;INSERT IGNORE 幂等。"""
    if not _table_exists(cur, "auth_role_scopes"):
        # 上面 _step_create_auth_role_scopes 会建
        skipped.append("seed auth_role_scopes (table missing)")
        return
    seed = [
        ("employee",     "chat:write"),
        ("agent_author", "chat:write"),
        ("agent_author", "plugin:write"),
        ("admin",        "chat:write"),
        ("admin",        "plugin:read"),
        ("admin",        "plugin:write"),
        ("admin",        "user:read"),
        ("admin",        "log:read"),
        ("super_admin",  "*"),
    ]
    cur.executemany(
        "INSERT IGNORE INTO auth_role_scopes (role, scope) VALUES (%s, %s)",
        seed,
    )
    applied.append(f"seed auth_role_scopes ({len(seed)} rows)")


# ──────────────────────── Main ────────────────────────
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

    try:
        _step_create_auth_tenants(cur, applied, skipped)
        _step_create_auth_users(cur, applied, skipped)
        _step_create_auth_role_scopes(cur, applied, skipped)
        _step_create_auth_audit_log(cur, applied, skipped)
        _step_seed_role_scopes(cur, applied, skipped)
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
        f"Phase 3 migration applied: applied={len(applied)} skipped={len(skipped)}"
    )
    for item in applied:
        logger.info(f"  + {item}")
    for item in skipped:
        logger.info(f"  = {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
