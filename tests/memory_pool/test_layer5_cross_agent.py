"""Phase 2 Layer 5 测试 — 跨 Agent 上下文(持久化到 cross_agent_context 表)。

要求 MySQL 可达,DatabasePool healthcheck=True。conftest 通过
unittest.SkipTest 在无 DB 时跳过整个类。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import unittest

from CorpAI.platform.db import DatabasePool
from CorpAI.platform.orchestrator.memory_gateway import MemoryPool


def _require_db_pool():
    if not DatabasePool.get().healthcheck():
        raise unittest.SkipTest("DatabasePool unavailable — MySQL 不可达")


class TestCrossAgent(unittest.TestCase):
    """Layer 5 走 MySQL cross_agent_context 表,upsert 模式。"""

    @classmethod
    def setUpClass(cls):
        _require_db_pool()

    def test_set_get_round_trip(self):
        """set 后立即 get,数据应一致。"""
        pool = MemoryPool(user_id='alice', session_id='s1', db_conn=DatabasePool.get().get_conn())
        try:
            pool.set_cross_agent_context('cs_agent', {'last_query': '查账'})
            ctx = pool.get_cross_agent_context('cs_agent')
            self.assertEqual(ctx, {'last_query': '查账'})
        finally:
            pool.clear()

    def test_upsert_overwrites(self):
        """同 (user_id, session_id, agent_id) 二次写入覆盖。"""
        pool = MemoryPool(user_id='alice', session_id='s2', db_conn=DatabasePool.get().get_conn())
        try:
            pool.set_cross_agent_context('hr_agent', {'v': 1})
            pool.set_cross_agent_context('hr_agent', {'v': 2})
            ctx = pool.get_cross_agent_context('hr_agent')
            self.assertEqual(ctx, {'v': 2})
        finally:
            pool.clear()


if __name__ == "__main__":
    unittest.main()
