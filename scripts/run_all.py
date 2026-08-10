"""CorpAI 一键后台启动 — 跨平台,拉起 FastAPI + 3 个 plugin + ngrok + sre_executor。

用法:
  # IDE 里(PyCharm):
  #   Run/Debug Configurations → 脚本路径 = scripts/run_all.py
  #   Working dir = 项目根
  #   点 Run → 看到 "✅ 启动完成" → 主进程 exit,服务全在后台跑
  #
  # 终端:
  PYTHONIOENCODING=utf-8 uv run python scripts/run_all.py
  #
  # Windows cmd 双击:
  scripts\run_all.bat

启动的服务(全部后台 detach,日志写 logs/):
  FastAPI (uvicorn)      8080  → logs/fastapi.log
  hr_assistant plugin    5010  → logs/hr_assistant.log
  sre_copilot plugin  5020  → logs/sre_copilot.log
  faq plugin             5030  → logs/faq.log
  ngrok (http 8080)      公开  → logs/ngrok.log
  sre_executor           异步  → logs/sre_executor.log

停:`scripts/stop_all.py` 或 `scripts/stop_all.bat`
"""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PY = PROJECT_ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)
PIDS_FILE = LOGS_DIR / ".pids"

# 必填环境变量 — **不要**模块级求值(否则 .env 加载在 COMMON_ENV 之后无效)
# 改用 _common_env() 函数,main() 里 _load_dotenv_into_env() 之后再调


def _common_env() -> dict[str, str]:
    """每次调用时从当前 os.environ 取值(此时 .env 已注入)。"""
    return {
        "AUTH_JWT_SECRET": os.getenv("AUTH_JWT_SECRET", "dev-secret"),
        "API_KEY": os.getenv("API_KEY", ""),
        "MYSQL_HOST": os.getenv("MYSQL_HOST", "localhost"),
        "MYSQL_USER": os.getenv("MYSQL_USER", "admin"),
        "MYSQL_PASSWORD": os.getenv("MYSQL_PASSWORD", "admin123456"),
        "MYSQL_DATABASE": os.getenv("MYSQL_DATABASE", "CorpAI"),
        "REDIS_URL": os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    }


def _load_dotenv_into_env(path: Path) -> int:
    """轻量 .env 解析器(不依赖 python-dotenv)。

    把 KEY=VALUE 注入 os.environ,但不覆盖已存在的(shell 设的真值优先)。
    支持 `KEY=` 空值、`# 注释`、`export ` 前缀、引号包裹。

    返回:成功加载的 key 数。
    """
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
        key = key.strip()
        value = value.strip()
        # 去引号
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        # 不覆盖已有 env(用户 shell 里真值优先)
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded

# (服务名, 启动命令, log 文件名)
SERVICES: list[tuple[str, list[str], str]] = [
    (
        "fastapi",
        [str(PY), "-m", "uvicorn",
         "CorpAI.api.app:app",
         "--host", "0.0.0.0", "--port", "8080",
         "--log-level", "info"],
        "fastapi.log",
    ),
    (
        "hr_assistant",
        [str(PY), "-m", "hr_assistant.entry"],
        "hr_assistant.log",
    ),
    (
        "sre_copilot",
        [str(PY), "-m", "sre_copilot.entry"],
        "sre_copilot.log",
    ),
    (
        "faq",
        [str(PY), "-m", "faq.entry"],
        "faq.log",
    ),
]


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _spawn_detached(cmd: list[str], log_path: Path) -> subprocess.Popen:
    """后台 detach 启动 — 父进程死了子进程继续跑。

    v3.1 行为(Windows):
      - 弹**可见** cmd 窗口(不再 CREATE_NO_WINDOW),用户能看到日志实时滚
      - 用 `tee` 同时写 log 文件,stop_all / 排错时还能 cat
      - 关窗口 = 杀进程(用户主动);stop_all 走 _kill_orphan_cmd_windows 兜底

    Windows 链路:`cmd /c start "title" cmd /k "cd /D X && python ... 2>&1 | tee log"`
      - 父进程:cmd.exe /c start → 立即返回,pid 进 .pids(几乎无意义,仅记账)
      - 子进程:新 cmd 窗口(cmd /k) → 跑 python,日志双写
      - 孙进程:python.exe 实际服务

    POSIX 仍走 start_new_session,日志只写文件。
    """
    if _is_windows():
        # 从 log_path 推 name(给窗口标题用,例:"CorpAI - sre_copilot")
        name = log_path.stem
        return _spawn_visible_windows(name, cmd, log_path)
    with open(log_path, "ab", buffering=0) as log_handle:
        return subprocess.Popen(
            cmd,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            cwd=str(PROJECT_ROOT),
            env={**os.environ, **_common_env()},
        )


def _find_tee() -> str | None:
    """找 Git for Windows 的 tee.exe 绝对路径。

    新 cmd 窗口(由 `start cmd /k` 起的)不一定继承父进程的 PATH,
    所以 `tee` 找不到 — 要用绝对路径,或先把 Git bin 加进 PATH。

    候选(按常见安装位置):
      - D:\\Git\\usr\\bin\\tee.exe(user 的 Git Bash)
      - C:\\Program Files\\Git\\usr\\bin\\tee.exe(默认安装)
      - 已 git-sdk / scoop / chocolatey 装的可能路径

    Returns:存在的绝对路径,或 None。
    """
    candidates = [
        Path("D:/Git/usr/bin/tee.exe"),
        Path("C:/Program Files/Git/usr/bin/tee.exe"),
        Path("C:/Program Files (x86)/Git/usr/bin/tee.exe"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def _spawn_visible_windows(
    name: str, cmd: list[str], log_path: Path,
) -> subprocess.Popen:
    """Windows 专属:弹可见 cmd 窗口,日志实时显示 + tee 落盘。

    v3.1.2 修法 — bat 里 `where tee` 找不到时,用绝对路径调 Git 的 tee.exe:
      - v3.1.1 假设新 cmd 窗口能从 PATH 找到 `tee`(因为父进程是 Git Bash)
      - 实际 `start cmd /k` 起的 cmd 不一定继承父 PATH,`tee` 报"找不到"
      - 解决:`_find_tee()` 探出 Git 的绝对路径,bat 里 `set TEE=...` 然后用 `%TEE%`

    链路(其他同 v3.1.1):
      - cmd.exe /c start → 立即退出
      - start "CorpAI - <name>" cmd.exe /k <bat> → 弹可见 cmd 窗口跑 bat
      - bat:cd /D → set ENV... → set TEE=... → python 2>&1 | %TEE% log
    """
    cwd = str(PROJECT_ROOT)
    env_lines = "\n".join(
        f'set "{k}={v}"' for k, v in _common_env().items()
    )
    cmdline = subprocess.list2cmdline(cmd)
    tee_abs = _find_tee() or "tee"  # 找不到就 fallback 到 PATH(赌一把)
    # .bat 文件:每行一句,不用 && 链式
    bat_content = (
        "@echo off\r\n"
        f'cd /D "{cwd}"\r\n"
        # v3.1.4 关键:强制 Python 不缓冲 stdout,tee 才能立刻刷 log 文件
        # (否则 tee 走 block buffering,等 buffer 满或 pipe 关闭才 flush,
        #  导致 _wait_healthy sleep 几秒后 log 还是空的 → 误报失败)
        f'set "PYTHONUNBUFFERED=1"\r\n'
        f"{env_lines}\r\n"
        f'set "TEE={tee_abs}"\r\n'
        f'{cmdline} 2>&1 | "%TEE%" "{log_path}"\r\n'
    )
    bat_path = LOGS_DIR / f"_spawn_{name}.bat"
    bat_path.write_text(bat_content, encoding="gbk")

    # start "title" cmd.exe /k <bat_path>
    start_args = [
        "cmd.exe", "/c", "start", f"CorpAI - {name}",
        "cmd.exe", "/k", str(bat_path),
    ]
    return subprocess.Popen(
        start_args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=0x00000008 | 0x00000200,  # DETACHED + NEW_PROCESS_GROUP
    )


def _save_pid(name: str, pid: int) -> None:
    with PIDS_FILE.open("a", encoding="utf-8") as f:
        f.write(f"{name}={pid}\n")


def _wait_healthy(proc: subprocess.Popen, log_path: Path, seconds: float = 5) -> bool:
    """等几秒看服务是否真起。

    v3.1.3 修法:不再只靠 `proc.poll() is None`,3 种情况分开判:

    A. helper 还在跑(None)→ 健康(旧式 background spawn,helper=服务)
    B. helper 已退(常见:`cmd.exe /c start` 跑完就退,但新 cmd 窗口里服务还在跑)
       → 看 log:有内容 + 没 ERROR/Traceback → 健康
    C. helper 已退 + log 没内容或显式出错 → 失败

    ngrok 这类 spawn 后立刻打印 ERROR 退出(`ERR_NGROK_334`)的 → 走 C,正确报失败。
    """
    time.sleep(seconds)
    if proc.poll() is None:
        # A:helper 进程本身==服务进程(旧模式)
        return True
    # B / C:helper 已退。看 log 内容判断实际服务健康度
    if not log_path.exists():
        return False
    try:
        content = log_path.read_text(encoding="gbk", errors="ignore")
    except OSError:
        return False
    if not content.strip():
        return False
    # 错误指示符 — 出现任一就判失败
    error_markers = ("Traceback (most recent call last)", "ERROR:", "CRITICAL:",
                     "ERR_NGROK_", "Error: ", "FATAL:", "command failed")
    for marker in error_markers:
        if marker in content:
            return False
    return True


def _read_ngrok_url(log_path: Path, timeout: float = 12.0) -> str | None:
    """从 ngrok.log 解析 https URL。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if log_path.exists():
            try:
                text = log_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                text = ""
            for line in text.splitlines():
                if "url=" in line and "https://" in line:
                    start = line.find("https://")
                    end = line.find(" ", start)
                    if end == -1:
                        end = line.find("\n", start)
                    if end == -1:
                        end = len(line)
                    return line[start:end].strip()
        time.sleep(0.5)
    return None


def _find_ngrok() -> str | None:
    """找 ngrok 二进制。

    查找顺序(任一命中即返回):
    1. PATH(shutil.which)— 含 System32 / winget / 用户 PATH
    2. 常见固定路径(System32 / Program Files / git mingw64)
    3. winget 默认路径 %LOCALAPPDATA%\\Microsoft\\WinGet\\Packages\\Ngrok.Ngrok_*\\ngrok.exe
    4. 项目目录 bin/ngrok.exe
    """
    found = shutil.which("ngrok")
    if found:
        return found
    candidates = [
        # 常见固定路径(用户手动拷的位置)
        Path("C:/Windows/System32/ngrok.exe"),
        Path("C:/Program Files/Ngrok/ngrok.exe"),
        Path("C:/Program Files (x86)/Ngrok/ngrok.exe"),
        # git bash 自带路径(可能装了老版,只是兜底)
        Path("C:/mingw64/bin/ngrok.exe"),
    ]
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        winget_root = Path(localappdata) / "Microsoft" / "WinGet" / "Packages"
        if winget_root.exists():
            for d in winget_root.iterdir():
                if d.name.startswith("Ngrok.Ngrok") and d.is_dir():
                    cand = d / "ngrok.exe"
                    if cand.exists():
                        candidates.append(cand)
    # 项目本地 bin/(推荐:放这里作为单实例权威位置)
    candidates.append(PROJECT_ROOT / "bin" / "ngrok.exe")

    for cand in candidates:
        if cand.exists():
            return str(cand)
    return None


def _start_ngrok() -> str | None:
    """起 ngrok(http 8080 → 公网 HTTPS)。

    自动从 .env 读 NGROK_AUTHTOKEN(如果有)跑一次 `ngrok config add-authtoken`,
    再启动。如果有 NGROK_DOMAIN 用固定 subdomain(ngrok paid 才生效)。
    """
    log_path = LOGS_DIR / "ngrok.log"
    ngrok_bin = _find_ngrok()
    if not ngrok_bin:
        print("  ⏭ ngrok 未安装,跳过(下载:https://ngrok.com/download)")
        print("     已查 PATH / C:\\mingw64\\bin / winget 默认路径 / 项目目录,都没找到")
        print("     解法:拷 ngrok.exe 到 C:\\Windows\\System32\\ 或加到系统 PATH")
        return None
    print(f"     ngrok:{ngrok_bin}")

    # 1) 自动配 authtoken(从 .env 读)
    authtoken = os.environ.get("NGROK_AUTHTOKEN", "").strip()
    if authtoken:
        with contextlib.suppress(Exception):
            subprocess.run(
                [ngrok_bin, "config", "add-authtoken", authtoken],
                capture_output=True, timeout=10,
            )

    # 2) 构造启动命令(可选固定 subdomain)
    cmd = [ngrok_bin, "http", "8080", "--log=stdout", "--log-format=logfmt"]
    domain = os.environ.get("NGROK_DOMAIN", "").strip()
    if domain:
        cmd[3:3] = ["--domain", domain]

    print("[5/6] 起 ngrok ...", end=" ", flush=True)
    proc = _spawn_detached(cmd, log_path)
    _save_pid("ngrok", proc.pid)
    if not _wait_healthy(proc, log_path):
        print(f"❌ 立即退出,看 {log_path}")
        return None
    url = _read_ngrok_url(log_path)
    print(f"✅ pid={proc.pid}")
    if url:
        print(f"     公网 URL:{url}")
    return url


def _start_sre_executor() -> int | None:
    """起 SRE Executor(Redis Stream consumer)。"""
    log_path = LOGS_DIR / "sre_executor.log"
    print("[6/6] 起 sre_executor ...", end=" ", flush=True)
    # v3.1:入口搬进 plugins/sre_copilot/src/sre_copilot/executor_cli.py
    candidates = [
        [str(PY), "-m", "sre_copilot.executor_cli",
         "--redis-url", _common_env()["REDIS_URL"]],
        [str(PY), "scripts/run_sre_executor.py",
         "--redis-url", _common_env()["REDIS_URL"]],
    ]
    for cmd in candidates:
        try:
            proc = _spawn_detached(cmd, log_path)
            _save_pid("sre_executor", proc.pid)
            if _wait_healthy(proc, log_path, seconds=3):
                print(f"✅ pid={proc.pid}")
                return proc.pid
            print("   退出了,试下一个入口 ...", end=" ", flush=True)
        except FileNotFoundError:
            continue
    print("⏭ 入口都不存在,跳过")
    return None


def main() -> int:
    print("=" * 60)
    print("CorpAI 一键后台启动")
    print("=" * 60)
    print(f"Python:{PY}")
    print(f"项目根:{PROJECT_ROOT}")
    print(f"日志:{LOGS_DIR}")
    print()

    # 清理上一轮 _spawn_*.bat 残留(每个 service 一个,start 用完一般保留)
    stale_bats = list(LOGS_DIR.glob("_spawn_*.bat"))
    if stale_bats:
        for b in stale_bats:
            try:
                b.unlink()
            except OSError:
                pass
        print(f"清理 {len(stale_bats)} 个 stale _spawn_*.bat")

    # 加载 .env 到当前进程(子进程 env 才会继承)
    dotenv_path = PROJECT_ROOT / ".env"
    loaded = _load_dotenv_into_env(dotenv_path)
    if loaded:
        print(f".env 已注入 {loaded} 个 env 变量")

    if not PY.exists():
        print(f"❌ Python interpreter not found:{PY}")
        print("   先跑:uv sync")
        return 1

    # 清旧 PID 文件
    if PIDS_FILE.exists():
        PIDS_FILE.unlink()

    started: list[tuple[str, int]] = []
    failed: list[str] = []

    # 启 FastAPI + plugins
    print(f"启 {len(SERVICES)} 个 Python 服务:")
    for i, (name, cmd, log_name) in enumerate(SERVICES, 1):
        log_path = LOGS_DIR / log_name
        print(f"[{i}/{len(SERVICES) + 2}] {name} ...", end=" ", flush=True)
        try:
            proc = _spawn_detached(cmd, log_path)
            _save_pid(name, proc.pid)
        except Exception as exc:
            print(f"❌ spawn 失败:{exc}")
            failed.append(name)
            continue
        if not _wait_healthy(proc, log_path, seconds=4):
            print(f"❌ 立即退出,看 {log_path}")
            failed.append(name)
            continue
        print(f"✅ pid={proc.pid}")
        started.append((name, proc.pid))
        time.sleep(1)  # plugin 端口间留时间避免冲突

    print()

    # 启 ngrok
    ngrok_url = _start_ngrok()
    print()

    # 启 sre executor
    _start_sre_executor()
    print()

    print("=" * 60)
    print(f"✅ 启动完成 — {len(started)} 成功,{len(failed)} 失败")
    if failed:
        print(f"   失败:{failed}")
    print("=" * 60)
    print()
    print("访问地址:")
    print("  前端:http://127.0.0.1:8080")
    print("  Admin UI:http://127.0.0.1:8080/admin/login.html")
    print("  hr plugin:http://127.0.0.1:5010")
    print("  sre plugin:http://127.0.0.1:5020")
    print("  faq plugin:http://127.0.0.1:5030")
    if ngrok_url:
        print()
        print(f"  公网(ngrok):{ngrok_url}")
        print(f"    飞书后台回调:{ngrok_url}/feishu/event")
        print(f"    Alertmanager webhook:{ngrok_url}/webhook/alertmanager")
    print()
    print("看实时日志:")
    print("  tail -f logs/fastapi.log")
    print("  tail -f logs/ngrok.log")
    print()
    print("停所有服务:uv run python scripts/stop_all.py")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
