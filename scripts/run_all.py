"""
CorpAI 一键启动 — 跨平台,同时拉起 FastAPI + 3 个 plugin。

用法:`.venv/Scripts/python.exe scripts/run_all.py`
PyCharm:Run/Debug Config — 脚本路径填这个,Working dir = 项目根。
停:每个子进程独立 stdout,你 Ctrl-C 这个脚本时不会关子进程;
   要关子进程:`scripts/stop_all.py` 或手动 taskkill。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PY = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"

# 必填环境变量
COMMON_ENV = {
    "AUTH_JWT_SECRET": "dev-secret",
    "MYSQL_HOST": "localhost",
    "MYSQL_USER": "admin",
    "MYSQL_PASSWORD": os.getenv("MYSQL_PASSWORD", "admin123456"),
    "MYSQL_DATABASE": "CorpAI",
}

SERVICES = [
    ("FastAPI", "CorpAI.api.app", []),
    ("hr_assistant", "hr_assistant.entry", []),
    ("devops_copilot", "devops_copilot.entry", []),
    ("faq", "faq.entry", []),
]


def main() -> int:
    if not PY.exists():
        print(f"❌ Python interpreter not found: {PY}")
        return 1

    procs: list[tuple[str, subprocess.Popen]] = []
    for name, module, extra_args in SERVICES:
        env = os.environ.copy()
        env.update(COMMON_ENV)
        # 跨平台:Windows 弹新窗口显示 stdout;POSIX 直接 inherit
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_CONSOLE

        print(f"[start] {name} ({module}) ...")
        p = subprocess.Popen(
            [str(PY), "-m", module, *extra_args],
            cwd=str(PROJECT_ROOT),
            env=env,
            creationflags=creationflags,
        )
        procs.append((name, p))

    print()
    print("=" * 50)
    print(f"已启 {len(procs)} 个服务:")
    for name, p in procs:
        print(f"  {name:20s} PID={p.pid}")
    print()
    print("FastAPI:    http://127.0.0.1:8080")
    print("Admin UI:   http://127.0.0.1:8080/admin/login.html")
    print()
    print("停止:`python scripts/stop_all.py`")
    print("=" * 50)

    # 主进程挂起,等任意子进程退出就通知
    try:
        for name, p in procs:
            rc = p.wait()
            print(f"⚠ {name} (PID={p.pid}) 退出 rc={rc}")
    except KeyboardInterrupt:
        print("\n收到 Ctrl-C,主进程退出(子进程继续跑,用 stop_all.py 关)")
    return 0


if __name__ == "__main__":
    sys.exit(main())