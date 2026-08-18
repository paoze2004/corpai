"""
Phase 2 数据库连接池单例。

所有模块从此取连接,不再自建 MySQLConnectionPool。
失败 loud-fail(get_conn 抛 ConnectionError 给调用方决策)。

替代:`tools/weather.py:128-136`、`tools/ticket.py:40-49`、`tools/trip.py:317-333`、
`utils/weather_crawler.py:39-40` 各自持有的连接/池(详见 ADR-006)。

Phase 6 路线图(本文件未启用,留作 foundation):
  SQLAlchemy 2.0 async + asyncmy 异步池(参见 git stash 或 #corpai-tech-stack-upgrade-roadmap),
  迁移需要把 memory.py / action_executor.py 全部改 async + 所有调用方加 await,
  以及 _4_tests/conftest.py 同步 mock 改 async mock。本次 session 网络受限,
  仅完成依赖基线评估 + AsyncDatabasePool 雏形(见 git history),完整迁移下一 session 继续。
"""
import logging

import mysql.connector
from mysql.connector.pooling import MySQLConnectionPool, PoolError

from _0_CorpAI.config import Config
from _0_CorpAI.logging import logger

# Phase 4 Observability — DB pool metrics(包内 import 防循环:metrics 不依赖 db)
from _0_CorpAI._2_platform.observability.metrics import (
    DB_POOL_ACQUIRE_SECONDS,
    DB_POOL_EXHAUSTED_TOTAL,
)


class DatabasePool:
    """单例数据库连接池。Phase 2 集中所有 MySQL 连接。"""

    _instance: "DatabasePool | None" = None
    _pool: MySQLConnectionPool | None = None

    @classmethod
    def get(cls) -> "DatabasePool":
        """单例入口。第一次调用时 lazy 创建 pool。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _ensure_pool(self) -> MySQLConnectionPool:
        if self._pool is None:
            cfg = Config()
            try:
                self._pool = MySQLConnectionPool(
                    pool_name=cfg.pool_name,
                    pool_size=cfg.pool_size,
                    host=cfg.host,
                    user=cfg.user,
                    password=cfg.password,
                    database=cfg.database,
                )
                logger.info(
                    f"DatabasePool 初始化成功: {cfg.host}/{cfg.database} "
                    f"pool_size={cfg.pool_size}"
                )
            except Exception as e:
                logger.error(f"DatabasePool 初始化失败: {e}")
                raise
        return self._pool

    def get_conn(self):
        """从池借一个连接。失败 raise(Phase 2 loud-fail 要求)。

        Phase 4:histogram 计时 + 池耗尽 counter。
        """
        try:
            with DB_POOL_ACQUIRE_SECONDS.time():
                return self._ensure_pool().get_connection()
        except PoolError as exc:
            DB_POOL_EXHAUSTED_TOTAL.inc()
            raise ConnectionError(f"DB pool exhausted: {exc}") from exc

    def get_pool(self) -> MySQLConnectionPool:
        """暴露底层 pool,给 tools/* 等用 pool.get_connection() 旧语法的模块。"""
        return self._ensure_pool()

    def healthcheck(self) -> bool:
        """探活 + ping;用于 conftest fixture / readiness check。"""
        try:
            conn = self.get_conn()
            conn.ping(reconnect=True)
            conn.close()
            return True
        except Exception as e:
            logger.debug(f"DB healthcheck failed: {e}")
            return False

    def close(self) -> None:
        """测试 reset 用 — 把 pool 标记为 None,下次 get() 时重建。"""
        # 池内连接由 MySQLConnectionPool 内部管理;此处仅清引用。
        self._pool = None


__all__ = ["DatabasePool"]