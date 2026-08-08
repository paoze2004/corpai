"""Phase 2 duck-type 兼容性测试 — 不依赖 DB。

MemoryPool 暴露给现有 8 个调用方
(IntentRecognizer / TaskPlanner / OrchestratorService.get_memory_state /
wiring._make_*_executor / messages_provider 等)的 4 属性 + 7 方法
必须全部满足现有契约。

任何一项失败表示 wiring.py 或下游使用方代码会崩。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import unittest

from CorpAI.platform.orchestrator.memory_gateway import MemoryPool


class TestDuckType(unittest.TestCase):
    """MemoryPool 对外 4 属性 + 7 方法与 ConversationMemory 行为等价。"""

    def test_duck_type_attributes(self):
        """OrchestratorService.get_memory_state 用的 4 个属性。"""
        pool = MemoryPool(user_id='alice', session_id='s1', db_conn=None)
        # 4 个 list/dict 属性
        self.assertEqual(pool.short_term_messages, [])
        self.assertEqual(pool.user_profile, {})
        self.assertEqual(pool.current_task, {})
        self.assertEqual(pool.entity_history, [])

    def test_duck_type_methods(self):
        """wiring / planner / intent / service.py 内部全部 duck-type 调用方。"""
        pool = MemoryPool(user_id='alice', session_id='s1', db_conn=None)

        # 7 个 set/update 方法
        pool.add_message('user', '公司有什么福利')
        self.assertEqual(len(pool.short_term_messages), 1)
        self.assertEqual(pool.short_term_messages[0]['content'], '公司有什么福利')

        pool.add_message('assistant', '五险一金 + 体检 + 培训等')
        self.assertEqual(len(pool.short_term_messages), 2)

        # 文本格式 — IntentRecognizer/TaskPlanner/simple_step_executor 用
        text = pool.get_short_term_text()
        self.assertIn('User: 公司有什么福利', text)
        self.assertIn('Assistant: 五险一金 + 体检 + 培训等', text)

        # 偏好路径
        pool.update_profile({'department': '研发'})
        self.assertEqual(pool.user_profile['department'], '研发')
        self.assertIn('研发', pool.get_profile_text())

        # 任务上下文
        pool.update_task_context({'type': 'hr'})
        self.assertEqual(pool.current_task['type'], 'hr')

        # 实体提取(进程内)
        pool.extract_entities('hr', '公司有什么福利')
        self.assertEqual(len(pool.entity_history), 1)
        self.assertEqual(pool.entity_history[0]['query'], '公司有什么福利')

        # clear — 全部清空
        pool.clear()
        self.assertEqual(pool.short_term_messages, [])
        self.assertEqual(pool.user_profile, {})
        self.assertEqual(pool.entity_history, [])


class TestIdentity(unittest.TestCase):
    """MemoryPool 自身的 user_id / session_id 标识必须可读。"""

    def test_identity_attributes(self):
        pool = MemoryPool(user_id='alice', session_id='session-001', db_conn=None)
        self.assertEqual(pool.user_id, 'alice')
        self.assertEqual(pool.session_id, 'session-001')


if __name__ == "__main__":
    unittest.main()
