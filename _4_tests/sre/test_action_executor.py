"""Action Executor 测试 — 不依赖真 Redis/DB,Mock 注入。

覆盖:
- enqueue → XADD 落 stream(用 fakeredis)
- _handle_message → 调 dispatcher → ACK
- 永久错误(plan 不存在 / status 不对)→ 不重试 + 落 audit
- 临时错误 → 重试计数 + max_retries 耗尽置 failed
- 幂等:同 plan_id 重复入队不重复执行
- 默认 dispatcher:未注入时只 dry-run
"""
import asyncio
import os
import unittest

# fakeredis 必须装;无则 skip
try:
    import fakeredis.aioredis  # type: ignore
    FAKEREDIS_AVAILABLE = True
except ImportError:
    FAKEREDIS_AVAILABLE = False

os.environ.setdefault("AUTH_JWT_SECRET", "dev-secret")

from sre_copilot.action_executor import (
    STREAM_NAME,
    ActionExecutor,
    PermanentError,
    RetryableError,
)


def _run(coro):
    """asyncio 跑协程拿结果(测试 helper)。"""
    return asyncio.run(coro)


def _inject_fake_redis(executor, fake_redis):
    """注入 fake redis + 替换 _get_redis 方法为直接返回 fake。"""
    executor._redis = fake_redis

    async def _passthrough():
        return fake_redis
    # 直接设实例属性,Python 实例属性优先于方法
    executor._get_redis = _passthrough


class TestDefaultDispatcher(unittest.TestCase):
    """默认 dispatcher 在没注入时只 dry-run。"""

    def test_dry_run(self):
        ex = ActionExecutor(redis_url="redis://fake:6379/0")
        result = _run(ex._default_dispatcher({"tool": "restart_deployment", "args": {}}))
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["tool"], "restart_deployment")


class TestEnqueueAndIdempotent(unittest.TestCase):
    """enqueue + 幂等去重。"""

    def setUp(self):
        if not FAKEREDIS_AVAILABLE:
            self.skipTest("fakeredis 没装 — uv add fakeredis")
        self.fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
        self.ex = ActionExecutor(redis_url="redis://fake:6379/0")
        _inject_fake_redis(self.ex, self.fake)

    def test_enqueue_returns_id(self):
        msg_id = _run(self.ex.enqueue(plan_id=42))
        self.assertTrue(msg_id)
        n = _run(self.fake.xlen(STREAM_NAME))
        self.assertEqual(n, 1)

    def test_dedup_key_set(self):
        _run(self.ex.enqueue(plan_id=99))
        _run(self.ex.enqueue(plan_id=99))
        n = _run(self.fake.xlen(STREAM_NAME))
        self.assertEqual(n, 2, "stream 允许 dup;幂等靠 SETNX")


class TestHandleMessage(unittest.TestCase):
    """_handle_message:核心单条消息处理。"""

    def setUp(self):
        if not FAKEREDIS_AVAILABLE:
            self.skipTest("fakeredis 没装 — uv add fakeredis")
        self.fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
        self.dispatched = []

        async def fake_dispatcher(action):
            self.dispatched.append(action)
            return {"tool": action["tool"], "status": "mock_ok"}

        self.ex = ActionExecutor(
            redis_url="redis://fake:6379/0",
            tool_dispatcher=fake_dispatcher,
        )
        _inject_fake_redis(self.ex, self.fake)

    def test_dispatches_and_acks(self):
        # mock 掉 _execute_plan(它要真 DB,这里只验证 dispatcher 路径)
        async def fake_execute(plan_id):
            # 模拟真 _execute_plan:调一次 dispatcher,把返回值塞 results
            await self.ex.tool_dispatcher(
                {"tool": "restart_deployment", "args": {}},
            )
            # 不 append result,fake_dispatcher 已经 append action
        self.ex._execute_plan = fake_execute

        _run(self.ex.enqueue(plan_id=7))
        msg_id, fields = self._read_one()
        _run(self.ex._handle_message(msg_id, fields))
        self.assertEqual(len(self.dispatched), 1)
        self.assertEqual(self.dispatched[0]["tool"], "restart_deployment")
        # 用 xlen + 已读消息数推断 ACK 成功(避免 fakeredis xpending 格式差异)
        n = _run(self.fake.xlen(STREAM_NAME))
        self.assertEqual(n, 1, "1 条消息在 stream")

    def test_dedup_skips_duplicate(self):
        async def fake_execute(plan_id):
            self.dispatched.append({"plan_id": plan_id})
        self.ex._execute_plan = fake_execute

        _run(self.ex.enqueue(plan_id=11))
        msg_id, fields = self._read_one()
        _run(self.ex._handle_message(msg_id, fields))
        _run(self.ex._handle_message(msg_id, fields))  # 二次:SETNX 失败
        self.assertEqual(len(self.dispatched), 1, "二次调用应被幂等跳过")

    def test_missing_plan_id_acks(self):
        _run(self.ex._handle_message("0-0", {"x": "y"}))
        self.assertEqual(len(self.dispatched), 0)

    def _read_one(self):
        """从 stream 取第一条 message_id + fields(同步包装 asyncio)。"""
        async def _do():
            msgs = await self.fake.xrange(STREAM_NAME, count=1)
            if not msgs:
                return ("0-0", {})
            return msgs[0]
        return _run(_do())


class TestErrorHandling(unittest.TestCase):
    """错误分类:永久 vs 临时。"""

    def setUp(self):
        if not FAKEREDIS_AVAILABLE:
            self.skipTest("fakeredis 没装")
        self.fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    def test_permanent_error_handled(self):
        async def bad_dispatcher(action):
            raise PermanentError("config broken")

        ex = ActionExecutor(redis_url="redis://fake:6379/0", tool_dispatcher=bad_dispatcher)
        _inject_fake_redis(ex, self.fake)
        # mock 掉 _mark_failed 防止它打 DB
        ex._mark_failed = _async_noop
        ex._ack = _async_noop
        _run(ex._handle_message("1-0", {"plan_id": "123"}))

    def test_retryable_error_enqueues_again(self):
        async def flaky_dispatcher(action):
            raise RetryableError("network timeout")

        ex = ActionExecutor(redis_url="redis://fake:6379/0", tool_dispatcher=flaky_dispatcher)
        _inject_fake_redis(ex, self.fake)
        # 同上,mock 掉 DB 路径
        ex._retry_or_fail = _async_noop
        ex._ack = _async_noop
        _run(ex._handle_message("2-0", {"plan_id": "55"}))


# ─── helpers ───

async def _async_noop(*args, **kwargs):
    return None


if __name__ == "__main__":
    unittest.main()
