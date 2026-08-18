"""sre_copilot MCP 单 server 入口。

用法:`python -m sre_copilot.mcp_one <server_name> <port>`
由 `mcp_main.main()` 通过 subprocess 拉起。

符合 Anthropic MCP 官方 spec(fastmcp 3.x,StreamableHTTP transport)。
"""
from __future__ import annotations

import logging
import sys

from sre_copilot.mcp_main import _serve_one

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if len(sys.argv) != 3:
        sys.exit("usage: python -m sre_copilot.mcp_one <name> <port>")
    name, port = sys.argv[1], int(sys.argv[2])
    _serve_one(name, port)