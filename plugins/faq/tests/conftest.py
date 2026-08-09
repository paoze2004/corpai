"""faq conftest — sys.path + mock_embedding fixture + Milvus 可用性 gate。"""
import os
import socket
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def milvus_available() -> bool:
    """查 env FAQ_MILVUS_HOST + 端口可达性 — 仅 Milvus 集成测试使用。"""
    host = os.getenv("FAQ_MILVUS_HOST")
    if not host:
        return False
    try:
        port = int(os.getenv("FAQ_MILVUS_PORT", "19530"))
        with socket.create_connection((host, port), timeout=1):
            return True
    except Exception:
        return False