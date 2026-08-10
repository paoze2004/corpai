"""SRE Action Executor CLI 入口 — `python -m sre_copilot.executor_cli`。

启动 Redis Stream consumer 异步执行 AI 批的修复方案。

用法:
    python -m sre_copilot.executor_cli                # 用 REDIS_URL env
    python -m sre_copilot.executor_cli --redis-url redis://x:6379/0
    python -m sre_copilot.executor_cli --once          # 拉完一轮就退出(测试)

退出:
    Ctrl-C / SIGTERM → stop() 设标志 → 下次 XREADGROUP block 超时后退出
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from CorpAI.utils.dotenv import load_env

# v3.2:加载 .env,REDIS_URL 等自动从 .env 读
load_env()

from sre_copilot.action_executor import ActionExecutor


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


async def _main_async(args: argparse.Namespace) -> int:
    executor = ActionExecutor(
        redis_url=args.redis_url,
        consumer_name=args.consumer,
        max_retries=args.max_retries,
    )

    # 信号优雅退出(Windows: add_signal_handler 在 Python 3.10+ 仅 Unix 支持;
    # 这里靠 XREADGROUP block 5s 超时自然退出)
    loop = asyncio.get_running_loop()

    def _request_stop(*_: object) -> None:
        logging.getLogger(__name__).info("收到停止信号,准备退出")
        executor.stop()

    with contextlib_ignore_errors():
        loop.add_signal_handler(signal.SIGTERM, _request_stop)
        loop.add_signal_handler(signal.SIGINT, _request_stop)

    if args.once:
        # 一次性模式:只跑一次 XREADGROUP(测试用)
        await executor._handle_message("test-once", {"plan_id": "0"})
        return 0

    await executor.run()
    return 0


class contextlib_ignore_errors:
    """add_signal_handler 在 Windows ProactorEventLoop 上不支持,失败就吞。

    用 ctx manager 让 except 后不抛。
    """

    def __enter__(self) -> None:
        pass

    def __exit__(self, *_exc: object) -> bool:
        return True


def main() -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(
        description="SRE Action Executor(消费 Redis Stream 执行 AI 批的修复方案)",
    )
    parser.add_argument(
        "--redis-url", default=None,
        help="Redis URL(默认从 REDIS_URL env 读,再回退 redis://localhost:6379/0)",
    )
    parser.add_argument(
        "--consumer", default=None,
        help="consumer name(默认 worker-<random8>)",
    )
    parser.add_argument(
        "--max-retries", type=int, default=3,
        help="单 plan 最大重试次数(默认 3)",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="只拉一轮就退出(测试用)",
    )
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    sys.exit(main())