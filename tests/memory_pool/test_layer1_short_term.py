"""Phase 2 Layer 1 测试 — 短期对话(per user_id × session_id)。"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import unittest

from CorpAI.platform.orchestrator.memory_gateway import MemoryPool


class TestShortTerm(unittest.TestCase):
    """add_message / limit-trim 不依赖 DB(走 _conv 内存)。"""

    def test_add_message_increments_list(self):
        pool = MemoryPool(user_id='alice', session_id='s1', db_conn=None)
        pool.add_message('user', 'hi')
        pool.add_message('assistant', '你好')
        self.assertEqual(len(pool.short_term_messages), 2)

    def test_limit_trims_to_20(self):
        """short_term_limit=20 — 超过 20 时保留最后 20 条。"""
        pool = MemoryPool(user_id='alice', session_id='s1', db_conn=None)
        for i in range(25):
            pool.add_message('user', f'msg-{i}')
        self.assertEqual(len(pool.short_term_messages), 20)
        # 最早 5 条被裁掉
        self.assertEqual(pool.short_term_messages[0]['content'], 'msg-5')
        self.assertEqual(pool.short_term_messages[-1]['content'], 'msg-24')

    def test_get_short_term_text_round_trip(self):
        pool = MemoryPool(user_id='alice', session_id='s1', db_conn=None)
        pool.add_message('user', '北京')
        pool.add_message('assistant', '上海')
        text = pool.get_short_term_text()
        self.assertIn('User: 北京', text)
        self.assertIn('Assistant: 上海', text)


if __name__ == "__main__":
    unittest.main()
