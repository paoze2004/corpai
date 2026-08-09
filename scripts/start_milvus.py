"""CorpAI Milvus 启动脚本。

用法:
    uv run python scripts/start_milvus.py
    .venv\Scripts\python.exe scripts\start_milvus.py

流程:
    1. 检查 docker 可用
    2. docker compose pull(拉镜像)
    3. docker compose up -d(后台启动)
    4. poll 19530 端口直到通(最多 120s)
    5. 打印 URL 速查表

失败处理:
    - docker 不可用 → 立即退出,打印 docker info 排查提示
    - 镜像拉失败 → 退出非 0,不打日志详情(用户自行 docker pull)
    - 19530 未通 → 打 `compose logs --tail=50` 帮诊断,退出 1
"""
from __future__ import annotations

import subprocess
import sys
import time
import socket
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = PROJECT_ROOT / "corpai-milvus.yml"


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """执行 shell 命令并打印输出。失败时根据 check 决定是否 sys.exit。"""
    print(f"[CMD] {' '.join(cmd)}")
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    if p.stdout:
        print(p.stdout.rstrip())
    if p.stderr:
        print(p.stderr.rstrip(), file=sys.stderr)
    if check and p.returncode != 0:
        sys.exit(f"[FATAL] 命令失败: {' '.join(cmd)} (rc={p.returncode})")
    return p


def _wait_port(host: str, port: int, timeout: int = 120) -> bool:
    """TCP 探活。失败时不抛,仅返 False。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                print(f"[OK] {host}:{port} 已通")
                return True
        except OSError:
            time.sleep(3)
    print(f"[FATAL] {host}:{port} 在 {timeout}s 内未通")
    return False


def _check_docker() -> None:
    """docker info 能跑即视为可用;非零则提示用户启 Docker Desktop。"""
    p = subprocess.run(
        ["docker", "info"], capture_output=True, text=True, timeout=10
    )
    if p.returncode != 0:
        print("[FATAL] docker info 失败 — Docker Desktop 是否启动?")
        if p.stderr:
            print(p.stderr.rstrip(), file=sys.stderr)
        sys.exit(1)
    print("[OK] Docker 已就绪")


def main() -> int:
    if not COMPOSE_FILE.exists():
        sys.exit(f"[FATAL] 缺 compose 文件: {COMPOSE_FILE}")
    _check_docker()

    print("[INFO] 拉取 Milvus 等镜像(可能几分钟)...")
    _run(["docker", "compose", "-f", str(COMPOSE_FILE), "pull"])

    print("[INFO] 启动 Milvus 集群...")
    _run(["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d"])

    print("[INFO] 等 etcd / minio 健康检查通过...")
    time.sleep(15)

    print("[INFO] poll Milvus gRPC :19530(最多 120s)...")
    if not _wait_port("127.0.0.1", 19530, timeout=120):
        print("[INFO] 拉最近 50 行日志帮诊断:")
        _run(["docker", "compose", "-f", str(COMPOSE_FILE), "logs", "--tail=50"],
             check=False)
        return 1

    print()
    print("=" * 64)
    print("CorpAI Milvus 集群就绪:")
    print("  gRPC      : localhost:19530")
    print("  HTTP      : http://localhost:9091/healthz")
    print("  MinIO     : http://localhost:9001  (minioadmin/minioadmin)")
    print("  Attu UI   : http://localhost:8012")
    print()
    print("停:  uv run python scripts/stop_milvus.py")
    print("清:  docker compose -f corpai-milvus.yml down --volumes")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())