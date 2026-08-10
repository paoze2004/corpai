"""CorpAI 一键后台启动 — 跨平台。

设计原则(v3.2):
  - 不再用 cmd.exe 包装 + bat 文件 + tee(v3.1 反复踩坑:cmd /c quoting bug / tee buffer /
    GBK 解码 / 子进程 detach 等问题)
  - 直接 python.exe + CREATE_NEW_CONSOLE:python 拿到独立可见 console,
    日志直接进 console,无需 tee,无需 bat,无需 cmd /c 那一层
  - 健康检查不看 log 内容(避免误判 buffer / encoding),直接探端口是否 LISTENING
  - .pids 存**真 python.exe pid**(CREATE_NEW_CONSOLE 返回的 Popen.pid 就是)

启动的服务(后台 detach,每个一个可见 console):
  FastAPI             8080  → logs/fastapi.log
  sre_copilot plugin  5020  → logs/sre_copilot.log
  ngrok               -     → logs/ngrok.log(只 1 个,Console)
  sre_executor        -     → logs/sre_executor.log

停:`scripts/stop_all.py` 或 `scripts/stop_all.bat`
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PY = PROJECT_ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)
PIDS_FILE = LOGS_DIR / ".pids"

# Windows CREATE_NEW_CONSOLE = 0x00000010,父进程死了不影响子进程
CREATE_NEW_CONSOLE = 0x00000010
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def _load_dotenv_into_env(path: Path) -> int:
    """轻量 .env 解析。"""
    if not path.exists():
        return 0
    loaded = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


def _common_env() -> dict[str, str]:
    return {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",  # 强制 line-buffer,console 立即显示
        "AUTH_JWT_SECRET": os.getenv("AUTH_JWT_SECRET", "dev-secret"),
        "MYSQL_HOST": os.getenv("MYSQL_HOST", "localhost"),
        "MYSQL_USER": os.getenv("MYSQL_USER", "admin"),
        "MYSQL_PASSWORD": os.getenv("MYSQL_PASSWORD", "admin123456"),
        "MYSQL_DATABASE": os.getenv("MYSQL_DATABASE", "CorpAI"),
        "REDIS_URL": os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        "NGROK_AUTHTOKEN": os.getenv("NGROK_AUTHTOKEN", ""),
        "NGROK_DOMAIN": os.getenv("NGROK_DOMAIN", ""),
    }


# 启动计划:(name, port_for_health_check, cmd, log_name)
# port=None 表示不探活(比如 ngrok / sre_executor 没有 HTTP 端口)
SERVICES: list[tuple[str, int | None, list[str], str]] = [
    (
        "fastapi", 8080,
        [str(PY), "-m", "uvicorn", "CorpAI.api.app:app",
         "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"],
        "fastapi.log",
    ),
    (
        "sre_copilot", 5020,
        [str(PY), "-m", "sre_copilot.entry"],
        "sre_copilot.log",
    ),
    # ngrok 和 sre_executor 在 main() 里单独处理(命令格式不同)
]

# hr_assistant / faq 不在自动启动里:
# 当前阶段专注运维闭环。手动起命令:
#   PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python -m hr_assistant.entry
#   PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python -m faq.entry


def _save_pid(name: str, pid: int) -> None:
    with PIDS_FILE.open("a", encoding="utf-8") as f:
        f.write(f"{name}={pid}\n")


def _spawn_visible(name: str, cmd: list[str]) -> subprocess.Popen:
    """Windows: CREATE_NEW_CONSOLE 给 python 独立 console,无 cmd 包装。
    返回的 Popen.pid == 真 python.exe pid(直接 Popen 启动的进程)。

    注意 CREATE_NEW_CONSOLE 不能与 DETACHED_PROCESS 同用(互斥)。
    父进程死了不影响子进程 = 用 CREATE_NEW_PROCESS_GROUP(子进程自成组)。
    """
    creationflags = CREATE_NEW_PROCESS_GROUP | CREATE_NEW_CONSOLE
    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=None,  # python stdout 去 console(子进程会写到 inherited console)
        stderr=subprocess.STDOUT,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, **_common_env()},
        creationflags=creationflags,
    )


def _spawn_background(name: str, cmd: list[str]) -> subprocess.Popen:
    """POSIX 或 Windows 无 console:文件收 stdout/stderr。"""
    log_path = LOGS_DIR / f"{name}.log"
    with open(log_path, "ab", buffering=0) as fh:
        creationflags = CREATE_NEW_PROCESS_GROUP if sys.platform.startswith("win") else 0
        return subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=fh,
            stderr=subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
            env={**os.environ, **_common_env()},
            start_new_session=(not sys.platform.startswith("win")),
            creationflags=creationflags,
        )


def _port_listening(port: int, timeout: float = 8.0) -> bool:
    """PowerShell 探端口 LISTENING。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-NetTCPConnection -State Listen -LocalPort {port} -EA SilentlyContinue | "
             "Select-Object -First 1"],
            capture_output=True, text=True, timeout=5,
        )
        if "LocalAddress" in r.stdout or f":{port}" in r.stdout:
            return True
        time.sleep(0.5)
    return False


def _find_ngrok() -> str | None:
    candidates = [
        Path(r"C:\Windows\System32\ngrok.exe"),
        Path(r"C:\Windows\ngrok.exe"),
        Path(r"D:\Git\usr\bin\ngrok.exe"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    # 试 where 命令
    try:
        r = subprocess.run(["where", "ngrok"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().splitlines()[0]
    except Exception:
        pass
    return None


def _start_ngrok() -> int | None:
    ngrok = _find_ngrok()
    if not ngrok:
        print("  ⏭ ngrok 没找到,跳过")
        return None
    # 先 kill 已有 ngrok 进程,避免 ERR_NGROK_334(endpoint already online)
    subprocess.run(
        ["taskkill", "/IM", "ngrok", "/F", "/T"],
        capture_output=True, text=True, timeout=10,
    )
    time.sleep(1)
    cmd = [ngrok, "http", "8080", "--log=stdout", "--log-format=logfmt"]
    domain = os.getenv("NGROK_DOMAIN", "").strip()
    if domain:
        cmd[3:3] = ["--domain", domain]
    print("  起 ngrok ...", end=" ", flush=True)
    proc = _spawn_visible("ngrok", cmd)
    _save_pid("ngrok", proc.pid)
    # 等URL出现(从 stdout 不可见 — ngrok log 写到 stderr 我们已合并)
    log_path = LOGS_DIR / "ngrok.log"
    # ngrok 默认写本地 log file C:\...\AppData\Local\ngrok\ngrok.log,不写 stdout;
    # 我们的 ngrok.log 是空文件(因为 ngrok 自己有日志路径)。简化:直接给 3s 等待
    time.sleep(4)
    # 检查 ngrok 进程是否还活着
    if proc.poll() is None:
        print(f"✅ pid={proc.pid}")
        print(f"     公网 URL:https://{domain}.ngrok-free.dev (domain 来自 NGROK_DOMAIN env)")
        return proc.pid
    print(f"❌ ngrok 退出(看 logs/ngrok.log 或 C:\\Users\\...\\AppData\\Local\\ngrok\\ngrok.log)")
    return None


def _start_sre_executor() -> int | None:
    log_path = LOGS_DIR / "sre_executor.log"
    # 探测 Redis 是否在跑(避免之前那种连不上崩掉的误导)
    if not _port_listening(6379, timeout=2):
        print(f"  ⏭ Redis 6379 没起,sre_executor 跳过(先 docker start corpai-redis)")
        return None
    cmd = [
        str(PY), "-m", "sre_copilot.executor_cli",
        "--redis-url", _common_env()["REDIS_URL"],
    ]
    print("  起 sre_executor ...", end=" ", flush=True)
    proc = _spawn_visible("sre_executor", cmd)
    _save_pid("sre_executor", proc.pid)
    # sre_executor 没 HTTP 端口,等 3s 看进程是否还活着
    time.sleep(3)
    if proc.poll() is None:
        print(f"✅ pid={proc.pid}")
        return proc.pid
    print(f"❌ sre_executor 退出,看 {log_path}")
    return None


def main() -> int:
    print("=" * 60)
    print("CorpAI 一键后台启动")
    print("=" * 60)
    print(f"Python:{PY}")
    print(f"项目根:{PROJECT_ROOT}")
    print()

    # 清旧 PID
    if PIDS_FILE.exists():
        PIDS_FILE.unlink()

    # 加载 .env
    loaded = _load_dotenv_into_env(PROJECT_ROOT / ".env")
    if loaded:
        print(f".env 已注入 {loaded} 个 env 变量")

    started: list[tuple[str, int]] = []
    failed: list[str] = []

    print(f"\n启 {len(SERVICES)} 个 Python 服务(每个独立 console 窗口):")
    for i, (name, port, cmd, log_name) in enumerate(SERVICES, 1):
        print(f"[{i}/{len(SERVICES) + 2}] {name} ...", end=" ", flush=True)
        try:
            proc = _spawn_visible(name, cmd)
            _save_pid(name, proc.pid)
        except Exception as exc:
            print(f"❌ spawn 失败:{exc}")
            failed.append(name)
            continue
        # 健康检查:端口 LISTENING
        if port is None:
            time.sleep(3)
            ok = proc.poll() is None
        else:
            ok = _port_listening(port, timeout=8)
        if ok:
            print(f"✅ pid={proc.pid} port={port} LISTENING")
            started.append((name, proc.pid))
        else:
            print(f"❌ 没起来(进程退出或端口未 LISTENING)")
            failed.append(name)

    print()
    ngrok_pid = _start_ngrok()
    if ngrok_pid:
        started.append(("ngrok", ngrok_pid))

    sre_pid = _start_sre_executor()
    if sre_pid:
        started.append(("sre_executor", sre_pid))

    print()
    print("=" * 60)
    if failed:
        print(f"⚠ 启动完成 — {len(started)} 成功,{len(failed)} 失败")
        print(f"   失败:{failed}")
    else:
        print(f"✅ 全部启动 — {len(started)} 个服务")
    print("=" * 60)
    print()
    print("访问地址:")
    print("  前端:http://127.0.0.1:8080")
    print("  Admin UI:http://127.0.0.1:8080/admin/login.html")
    print("  sre plugin:http://127.0.0.1:5020")
    print()
    print("停所有服务:uv run python scripts/stop_all.py")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())