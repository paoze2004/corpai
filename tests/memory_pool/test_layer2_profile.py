"""Phase 2 Layer 2 测试 — 用户偏好(per user_id 跨 session)。"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import unittest

from CorpAI.platform.orchestrator.memory_gateway import MemoryPool


class TestProfile(unittest.TestCase):
    """update_profile / get_profile_text 是 duck-type 测试,不依赖 DB。"""

    def test_update_profile_merges_dict(self):
        """update_profile 是 merge(update 不删已有),不是替换。"""
        pool = MemoryPool(user_id='alice', session_id='s1', db_conn=None)
        pool.update_profile({'seat_type': '二等座'})
        pool.update_profile({'cabin_type': '经济舱'})
        self.assertEqual(pool.user_profile['seat_type'], '二等座')
        self.assertEqual(pool.user_profile['cabin_type'], '经济舱')

    def test_get_profile_text_empty_vs_set(self):
        """无偏好时返回 '无已知的用户偏好' 占位字符串(IntentRecognizer 假设)。"""
        pool_empty = MemoryPool(user_id='alice', session_id='s1', db_conn=None)
        self.assertEqual(pool_empty.get_profile_text(), '无已知的用户偏好')

        pool_set = MemoryPool(user_id='alice', session_id='s1', db_conn=None)
        pool_set.update_profile({'seat_type': '二等座', 'language': 'zh-CN'})
        text = pool_set.get_profile_text()
        self.assertIn('seat_type', text)
        self.assertIn('二等座', text)
        self.assertIn('zh-CN', text)


if __name__ == "__main__":
    unittest.main()
