"""CorpAI 一键停所有后台服务 — 简化版(v3.2)。

设计原则:
  - 不依赖 .pids(可能丢、可能不准、helper cmd PID 永远是死的)
  - 按**端口** + **进程名** + **cmd 标题** 三路并行,任何一路命中就 kill
  - 用 PowerShell 做端口/进程查询(GBK 解码无忧)

用法:
  uv run python scripts/stop_all.py
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
PIDS_FILE = LOGS_DIR / ".pids"

# CorpAI 服务的目标端口
TARGET_PORTS = [8080, 5010, 5020, 5030]


def _ps(query: str, timeout: int = 15) -> str:
    """跑 PowerShell 命令,返 stdout。"""
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", query],
        capture_output=True, text=True, timeout=timeout,
    )
    return r.stdout or ""


def _kill_pid(pid: int, label: str) -> bool:
    """taskkill /F /T /PID,返是否真杀了。"""
    r = subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode == 0:
        print(f"  ✅ {label} (pid={pid}) killed")
        return True
    err = (r.stderr or r.stdout or "").strip()
    if "没有找到" in err or "not found" in err.lower():
        # 已不在
        return False
    print(f"  ⚠ {label} (pid={pid}): {err[:80]}")
    return False


def _kill_by_port(port: int) -> int:
    """用 Get-NetTCPConnection 找监听 port 的进程,kill 整树。"""
    out = _ps(
        f"Get-NetTCPConnection -State Listen -LocalPort {port} "
        f"-EA SilentlyContinue | Select-Object -ExpandProperty OwningProcess"
    )
    killed = 0
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            if _kill_pid(int(line), f":{port} 占用进程"):
                killed += 1
    if killed == 0:
        print(f"  · :{port} 无监听")
    return killed


def _kill_by_name(name: str) -> int:
    """taskkill /IM /F 杀所有同名进程。返回杀掉的 PID 列表长度。"""
    r = subprocess.run(
        ["taskkill", "/IM", name, "/F", "/T"],
        capture_output=True, text=True, timeout=15,
    )
    output = (r.stdout or "") + "\n" + (r.stderr or "")
    killed = sum(
        1 for line in output.splitlines()
        if "SUCCESS:" in line and "terminated" in line
    )
    return killed


def _kill_corpai_cmd_windows() -> int:
    """杀标题 'CorpAI - *' 的 cmd 窗口(连带子树)。"""
    out = _ps(
        "Get-Process cmd -EA SilentlyContinue | "
        "Where-Object { $_.MainWindowTitle -like 'CorpAI - *' } | "
        "Select-Object -ExpandProperty Id"
    )
    killed = 0
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            if _kill_pid(int(line), "CorpAI cmd 窗口"):
                killed += 1
    return killed


def _kill_pids_file() -> int:
    """读 .pids,kill 每个 pid(如果还在)。"""
    if not PIDS_FILE.exists():
        return 0
    killed = 0
    for line in PIDS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        name, pid_str = line.split("=", 1)
        try:
            pid = int(pid_str.strip())
        except ValueError:
            continue
        if _kill_pid(pid, f"{name} (.pids)"):
            killed += 1
    return killed


def main() -> int:
    print("CorpAI 停所有后台服务")
    print("=" * 40)

    total = 0

    # 1. .pids(真 python PID — v3.2 之后 Popen.pid 是真 python PID)
    print("\n[1/4] 读 .pids 杀进程 ...")
    total += _kill_pids_file()

    # 2. 按端口杀
    print("\n[2/4] 按端口杀(8080/5010/5020/5030)...")
    for port in TARGET_PORTS:
        total += _kill_by_port(port)

    # 3. CorpAI cmd 窗口(可见 console)
    print("\n[3/4] 杀 CorpAI cmd 窗口(标题 'CorpAI - *')...")
    n = _kill_corpai_cmd_windows()
    print(f"  杀掉 {n} 个 CorpAI cmd 窗口")

    # 4. ngrok(管手动起的)
    print("\n[4/4] 按名杀 ngrok ...")
    n = _kill_by_name("ngrok")
    if n > 0:
        print(f"  ✅ {n} 个 ngrok killed")
    else:
        print(f"  · 无 ngrok 进程")

    # 删 .pids
    if PIDS_FILE.exists():
        try:
            PIDS_FILE.unlink()
        except OSError:
            pass

    print()
    print("=" * 40)
    print(f"总计 kill {total} 个进程")
    return 0


if __name__ == "__main__":
    sys.exit(main())