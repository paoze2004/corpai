"""Phase 2 Layer 4 测试 — 任务上下文(进程内 dict + TTL 30min,per user_id)。"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import unittest
from datetime import datetime, timedelta

from _0_CorpAI._2_platform.orchestrator.memory_gateway import MemoryPool


class TestTaskContext(unittest.TestCase):
    """Layer 4 完全在内存,不需要 DB。"""

    def test_set_get_round_trip(self):
        pool = MemoryPool(user_id='alice', session_id='s1', db_conn=None)
        pool.set_task_context('t1', {'departure': '北京'}, ttl_min=30)
        self.assertEqual(pool.get_task_context('t1'), {'departure': '北京'})

    def test_per_user_isolation(self):
        """不同 user_id 的 MemoryPool 互看不到对方的 task_context。"""
        p1 = MemoryPool(user_id='alice', session_id='s1', db_conn=None)
        p2 = MemoryPool(user_id='bob', session_id='s1', db_conn=None)

        p1.set_task_context('t1', {'k': 'v1'}, ttl_min=30)
        # bob 看不见 alice 的
        self.assertIsNone(p2.get_task_context('t1'))
        # alice 仍能读
        self.assertEqual(p1.get_task_context('t1'), {'k': 'v1'})

    def test_ttl_expiration(self):
        """TTL 到期后 get_task_context 返回 None。"""
        pool = MemoryPool(user_id='alice', session_id='s1', db_conn=None)
        pool.set_task_context('t1', {'k': 'v'}, ttl_min=30)
        # 手动把过期时间调成过去式,模拟 TTL 过期
        pool._task_ctx['t1']['expires_at'] = datetime.utcnow() - timedelta(seconds=1)
        self.assertIsNone(pool.get_task_context('t1'))


if __name__ == "__main__":
    unittest.main()
