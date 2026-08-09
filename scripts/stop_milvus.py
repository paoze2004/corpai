"""CorpAI Milvus 停止脚本。

用法:
    uv run python scripts/stop_milvus.py
    uv run python scripts/stop_milvus.py --purge   # 删命名卷,数据全清

行为:
    - 默认 `down` 保留命名卷(etcd/minio/milvus 数据下次启动仍在)
    - `--purge` 走 `down --volumes`,Milvus 数据全清,等同首次启动

对应 docker compose:
    docker compose -f corpai-milvus.yml down [--volumes]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = PROJECT_ROOT / "corpai-milvus.yml"


def main() -> int:
    parser = argparse.ArgumentParser(description="Stop CorpAI Milvus cluster")
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Delete named volumes (corpai_etcd / corpai_minio / corpai_milvus)",
    )
    args = parser.parse_args()

    if not COMPOSE_FILE.exists():
        sys.exit(f"[FATAL] 缺 compose 文件: {COMPOSE_FILE}")

    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), "down"]
    if args.purge:
        cmd.append("--volumes")
        print("[WARN] --purge: 数据卷 corpai_{etcd,minio,milvus} 将被删除")

    print(f"[CMD] {' '.join(cmd)}")
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    if p.stdout:
        print(p.stdout.rstrip())
    if p.returncode != 0:
        print(f"[ERROR] 停止失败 rc={p.returncode}", file=sys.stderr)
        if p.stderr:
            print(p.stderr.rstrip(), file=sys.stderr)
        return 1

    print("[OK] Milvus 集群已停止")
    if not args.purge:
        print("[INFO] 数据卷保留,下次 start_milvus.py 数据仍在")
    return 0


if __name__ == "__main__":
    sys.exit(main())