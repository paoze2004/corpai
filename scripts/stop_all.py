"""
CorpAI 一键停止 — 跨平台,按端口找 PID + kill。

用法:`.venv/Scripts/python.exe scripts/stop_all.py`
"""
from __future__ import annotations

import sys

PORTS = [
    8080,  # FastAPI
    5010, 8010, 8011,  # hr_assistant A2A + MCP
    5020, 8020, 8021,  # devops_copilot A2A + MCP
    5030, 8030,  # faq A2A + MCP
]


def main() -> int:
    if sys.platform == "win32":
        import subprocess
        killed = 0
        for port in PORTS:
            cmd = f'netstat -aon ^| findstr ":{port}" ^| findstr LISTENING'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            for line in result.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 5:
                    pid = parts[-1]
                    if pid.isdigit():
                        subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
                        print(f"  ✓ killed PID {pid} (port {port})")
                        killed += 1
        print(f"\n共 kill {killed} 个进程")
    else:
        # POSIX:用 lsof 或 fuser
        import subprocess
        killed = 0
        for port in PORTS:
            try:
                result = subprocess.run(
                    ["fuser", "-k", f"{port}/tcp"],
                    capture_output=True, text=True,
                )
                if result.returncode == 0:
                    print(f"  ✓ killed port {port}")
                    killed += 1
            except FileNotFoundError:
                print("需要 lsof 或 fuser 安装")
                return 1
        print(f"\n共清理 {killed} 个端口")
    return 0


if __name__ == "__main__":
    sys.exit(main())