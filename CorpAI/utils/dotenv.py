"""加载 .env 进 os.environ,所有 entry / cli 入口统一调用。

设计原则:.env 是单一配置源,任何 Python 入口启动时第一件事 = 加载 .env,
不要让用户在 shell 里手动 export 各 key。

用法(在 entry.py / executor_cli.py / app.py 顶部):

    from CorpAI.utils.dotenv import load_env
    load_env()  # 自动找项目根的 .env

依赖:python-dotenv(已经在 .venv 里)。

为什么不用我们自己写的 _load_dotenv_into_env(在 run_all.py 里):
  - 跑 entry.py 时不会经过 run_all.py,自己实现重复一份
  - python-dotenv 是业界标准,parse 边界情况更全(引号 / 转义 / 多行)
  - 我们只 wrap 一层,加个项目根搜索逻辑
"""
from __future__ import annotations

import os
from pathlib import Path


def _find_dotenv(start: Path | None = None) -> Path | None:
    """从 start 向上找 .env,直到 git root 或 filesystem root。

    项目布局假设:
      <project_root>/
        .env
        CorpAI/        ← 我们
        plugins/       ← 兄弟
        scripts/       ← 兄弟
    任何子目录的 entry.py(executor_cli / sre_copilot.entry / app)都该找到这个 .env。
    """
    start = (start or Path(__file__).resolve()).parent
    for candidate in [start, *start.parents]:
        env_path = candidate / ".env"
        if env_path.is_file():
            return env_path
    return None


def load_env(dotenv_path: Path | None = None, override: bool = False) -> Path | None:
    """加载 .env 到 os.environ。返实际加载的路径(找不到返 None)。

    Args:
        dotenv_path: 显式给路径(测试用)。None = 自动找。
        override: True = .env 覆盖已有 env(shell 真值优先 = False)。
    """
    try:
        from dotenv import load_dotenv as _load
    except ImportError:
        # python-dotenv 没装 — 静默跳过,让 .env 默认值通过 os.environ.get('KEY', default) 兜底
        return None
    path = dotenv_path or _find_dotenv()
    if path is None:
        return None
    _load(path, override=override)
    return path


__all__ = ["load_env"]