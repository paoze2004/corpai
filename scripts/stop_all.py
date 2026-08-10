"""CorpAI 一键停所有后台服务 — 读 logs/.pids 杀干净。

用法:
  PYTHONIOENCODING=utf-8 uv run python scripts/stop_all.py

行为:
  1. 读 logs/.pids(由 start_all.py 写)
  2. 按名字杀(uvicorn / ngrok / sre_executor)
  3. Windows 用 taskkill /F /T(杀进程树),POSIX 用 SIGTERM
  4. 已死的进程跳过
  5. 删 .pids 文件
  6. 兜底:按端口 8080 杀残余进程
"""
from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
PIDS_FILE = LOGS_DIR / ".pids"


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _kill(pid: int, name: str) -> bool:
    """杀 PID。Windows 用 taskkill /F /T(树),POSIX 用 SIGTERM。返 True=杀成功。"""
    if _is_windows():
        try:
            result = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                print(f"  ✅ {name} (pid={pid}) killed")
                return True
            err = (result.stderr or result.stdout or "").strip()
            if "not found" in err.lower() or "找不到" in err:
                print(f"  ⏭ {name} (pid={pid}) 已不在")
                return True
            print(f"  ⚠ {name} (pid={pid}) taskkill 返 {result.returncode}:{err[:100]}")
            return False
        except subprocess.TimeoutExpired:
            print(f"  ❌ {name} (pid={pid}) taskkill 超时")
            return False
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            print(f"  ✅ {name} (pid={pid}) SIGTERM")
            return True
        except ProcessLookupError:
            print(f"  ⏭ {name} (pid={pid}) 已不在")
            return True
        except PermissionError:
            print(f"  ❌ {name} (pid={pid}) 没权限杀")
            return False


def _read_pids() -> dict[str, int]:
    """读 .pids 文件 → {name: pid}。"""
    if not PIDS_FILE.exists():
        return {}
    out = {}
    for line in PIDS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        name, pid_str = line.split("=", 1)
        with contextlib.suppress(ValueError):
            out[name.strip()] = int(pid_str.strip())
    return out


def _kill_by_port(port: int) -> None:
    """兜底:按端口杀 — 防 .pids 丢了还有孤儿进程。"""
    if _is_windows():
        with contextlib.suppress(Exception):
            r = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True, text=True, timeout=10,
            )
            for line in r.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts and parts[-1].isdigit():
                        pid = int(parts[-1])
                        _kill(pid, f":{port} 占用进程")
                        return
    else:
        with contextlib.suppress(Exception):
            subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, timeout=10,
            )


def _kill_by_name(process_name: str) -> int:
    """按进程名 kill(Windows 用 taskkill /IM,POSIX 用 pkill)。

    主要场景:ngrok — 用户经常手动起 ngrok 占 subdomain,
    stop_all 只杀 .pids + cmd 窗口,抓不到手动起的。
    taskkill /IM ngrok /F 不带 .exe 通配匹配 → 更可靠。

    Returns:杀掉的进程数。
    """
    if _is_windows():
        # taskkill /IM 默认通配匹配,不需要 .exe 后缀
        with contextlib.suppress(Exception):
            r = subprocess.run(
                ["taskkill", "/IM", process_name, "/F", "/T"],
                capture_output=True, text=True, timeout=15,
            )
            # taskkill 把 SUCCESS 行打到 stdout,INFO/ERROR 打 stderr
            output = (r.stdout or "") + "\n" + (r.stderr or "")
            killed = sum(
                1 for line in output.splitlines()
                if "SUCCESS:" in line and "terminated" in line
            )
            if killed > 0:
                print(f"  ✅ {killed} 个 {process_name} 已 kill(按名)")
            return killed
    else:
        with contextlib.suppress(Exception):
            r = subprocess.run(
                ["pkill", "-9", "-x", process_name],
                capture_output=True, timeout=10,
            )
            return 0 if r.returncode == 1 else 1
    return 0


def _kill_orphan_cmd_windows() -> int:
    """清理 v3.1+ 弹的 cmd 窗口(标题 'CorpAI - <service>')。

    v3.1 之前 .pids 里是服务进程本身,helper=服务 → taskkill 直接杀。
    v3.1+ 用 `start cmd /k <bat>` 弹可见窗口:
      - .pids 里是 helper cmd.exe(pid 已退出),taskkill 啥也干不了
      - 真要杀的是新 cmd 窗口(标题 'CorpAI - <name>')
    按 MainWindowTitle 前缀 'CorpAI - ' 杀,避开用户自己开的 cmd。

    返回杀掉的窗口数。
    """
    if not _is_windows():
        return 0
    killed = 0
    with contextlib.suppress(Exception):
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process cmd -ErrorAction SilentlyContinue | "
             "Where-Object { $_.MainWindowTitle -like 'CorpAI - *' -and "
             "  $_.MainWindowHandle -ne 0 } | "
             "ForEach-Object { '{0}|{1}' -f $_.Id, $_.MainWindowTitle }"],
            capture_output=True, text=True, timeout=15,
        )
        for line in r.stdout.splitlines():
            line = line.strip()
            if "|" not in line:
                continue
            pid_str, title = line.split("|", 1)
            try:
                pid = int(pid_str.strip())
            except ValueError:
                continue
            # 标题里取 service 名(如 'CorpAI - fastapi' → 'fastapi')
            svc_name = title.split("CorpAI -", 1)[-1].strip()
            if _kill(pid, f"cmd:{svc_name}"):
                killed += 1
    return killed


def main() -> int:
    print("CorpAI 停所有后台服务")
    print("=" * 40)

    pids = _read_pids()
    if not pids:
        print("⚠ 没找到 PID 文件(可能没跑 start_all.py)")
        print("  兜底:按端口杀 8080 占用进程")
        _kill_by_port(8080)
        return 0

    killed = 0
    for name, pid in pids.items():
        if _kill(pid, name):
            killed += 1

    if PIDS_FILE.exists():
        PIDS_FILE.unlink()
        print()
        print("已删 PID 文件")

    print()
    print(f"杀 {killed}/{len(pids)} 个进程")
    print()
    print("兜底:按端口 8080 杀残余")
    _kill_by_port(8080)
    print()
    print("清理孤儿 cmd 窗口")
    orphans = _kill_orphan_cmd_windows()
    print(f"  清掉 {orphans} 个孤儿 cmd 窗口")
    print()
    print("兜底:按名杀 ngrok(管手动起的)")
    killed_ngrok = _kill_by_name("ngrok")
    print(f"  清掉 {killed_ngrok} 个 ngrok 进程")
    return 0


if __name__ == "__main__":
    sys.exit(main())
