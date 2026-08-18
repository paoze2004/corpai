"""Phase 2 Layer 3 测试 — 实体历史(进程内 list,per user_id 跨 session)。"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import unittest

from _0_CorpAI._2_platform.orchestrator.memory_gateway import MemoryPool


class TestEntity(unittest.TestCase):
    """extract_entities / entity_history 是 duck-type 测试,不依赖 DB。"""

    def test_extract_entities_appends(self):
        pool = MemoryPool(user_id='alice', session_id='s1', db_conn=None)
        pool.extract_entities('weather', '北京天气')
        pool.extract_entities('flight', '北京到上海机票')
        self.assertEqual(len(pool.entity_history), 2)
        self.assertEqual(pool.entity_history[0]['type'], 'weather')
        self.assertEqual(pool.entity_history[1]['type'], 'flight')

    def test_entity_history_limit_50(self):
        """50 条上限 — 写入 60 条应保留最后 50 条。"""
        pool = MemoryPool(user_id='alice', session_id='s1', db_conn=None)
        for i in range(60):
            pool.extract_entities('weather', f'q-{i}')
        self.assertEqual(len(pool.entity_history), 50)
        # 最早 10 条被裁掉
        self.assertEqual(pool.entity_history[0]['query'], 'q-10')


if __name__ == "__main__":
    unittest.main()
