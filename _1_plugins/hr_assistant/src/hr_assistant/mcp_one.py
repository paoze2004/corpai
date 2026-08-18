"""hr_assistant MCP 单 server 入口(由 mcp_main 通过 subprocess 拉起)。"""
from __future__ import annotations

import logging
import sys

from hr_assistant.mcp_main import _serve_one

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if len(sys.argv) != 3:
        sys.exit("usage: python -m hr_assistant.mcp_one <name> <port>")
    name, port = sys.argv[1], int(sys.argv[2])
    _serve_one(name, port)