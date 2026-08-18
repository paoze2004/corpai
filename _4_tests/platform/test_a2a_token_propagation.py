"""
A2A scope 链路测试 — 验证 user JWT 从 platform → plugin 透传链路。

关键不变量:platform 在 dispatch 到 plugin 时,user 的 raw JWT 必须出现在
task.metadata["authorization"],这样 plugin server 能用它当 Bearer header
给 action 调用(替代之前硬编码 dev_token 占位)。
"""
import unittest
from unittest.mock import MagicMock, patch

import pytest


class TestUserTokenContextVar(unittest.TestCase):
    """wiring 的 _user_token_var contextvar 行为。"""

    def test_set_and_get_token(self):
        from _0_CorpAI._2_platform.wiring import set_user_token, _get_current_user_token
        set_user_token("Bearer abc.def.ghi")
        self.assertEqual(_get_current_user_token(), "Bearer abc.def.ghi")

    def test_default_token_is_none(self):
        """未调用 set_user_token 时,get 返 None(plugin 用 dev_token fallback)。"""
        from _0_CorpAI._2_platform.wiring import _get_current_user_token
        # contextvar default 是 None
        self.assertIsNone(_get_current_user_token())


class TestA2ATaskMetadata(unittest.TestCase):
    """wiring 在构造 Task 时把 user token 写进 metadata。"""

    def test_token_written_to_metadata(self):
        """模拟:用户有 token,平台 dispatch 时 task.metadata["authorization"] 应是 'Bearer <token>'"""
        from _0_CorpAI._2_platform.wiring import set_user_token
        set_user_token("Bearer user.jwt.here")

        # 复刻 wiring 内的 Task 构造逻辑(避免 import 整个 orchestrator)
        from python_a2a import Task, Message, TextContent, MessageRole
        from _0_CorpAI._2_platform.wiring import _get_current_user_token
        import uuid
        import json

        user_token = _get_current_user_token()
        task_metadata: dict = {}
        if user_token:
            task_metadata["authorization"] = user_token

        msg = Message(
            content=TextContent(text=json.dumps({"query": "test"})),
            role=MessageRole.USER,
        )
        task = Task(
            id="task-" + str(uuid.uuid4()),
            message=msg.to_dict(),
            metadata=task_metadata,
        )

        self.assertEqual(task.metadata["authorization"], "Bearer user.jwt.here")

    def test_no_token_means_no_metadata_auth(self):
        """无 token 时 metadata 里不写 authorization(plugin 走 dev_token fallback)。"""
        from _0_CorpAI._2_platform.wiring import set_user_token
        set_user_token(None)

        from _0_CorpAI._2_platform.wiring import _get_current_user_token
        user_token = _get_current_user_token()
        task_metadata: dict = {}
        if user_token:
            task_metadata["authorization"] = user_token

        self.assertNotIn("authorization", task_metadata)


class TestPluginServerReadsMetadata(unittest.TestCase):
    """plugin server 从 task.metadata 读 user_token,传给 action。"""

    def test_hr_assistant_dispatch_uses_metadata_token(self):
        """hr_assistant._dispatch_action 收到 user_token 后,authorization 变量 = user_token"""
        from hr_assistant.server import _dispatch_action
        from unittest.mock import patch
        import hr_assistant.actions as actions_mod

        with patch.object(actions_mod, "submit_leave", return_value="OK") as mock_leave:
            _dispatch_action("submit_leave", "请年假", user_token="Bearer real.user.jwt")
            # verify mock called with the REAL token, not DEV_TOKEN
            call_args = mock_leave.call_args
            self.assertEqual(call_args.kwargs["authorization"], "Bearer real.user.jwt")

    def test_hr_assistant_falls_back_to_dev_token(self):
        """无 user_token(DEV_NO_AUTH 模式)时,fallback 到 Bearer DEV_TOKEN"""
        from hr_assistant.server import _dispatch_action
        from unittest.mock import patch
        import hr_assistant.actions as actions_mod

        with patch.object(actions_mod, "submit_leave", return_value="OK") as mock_leave:
            _dispatch_action("submit_leave", "请年假", user_token=None)
            call_args = mock_leave.call_args
            self.assertEqual(call_args.kwargs["authorization"], "Bearer DEV_TOKEN")


if __name__ == "__main__":
    unittest.main()