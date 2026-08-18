"""knowledge MCP 入口 — 子进程模式。

符合 Anthropic MCP 官方 spec(fastmcp 3.x,StreamableHTTP transport)。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

PORTS = [8030]
SERVER_NAMES = ["knowledge"]


def _serve_one(name: str, port: int) -> None:
    from knowledge.mcp_servers import SERVER_PORTS

    target = None
    for server, p in SERVER_PORTS:
        if server.name == name and p == port:
            target = server
            break
    if target is None:
        raise RuntimeError(f"找不到 server:{name} on port {port}")

    logger.info(
        "MCP server '%s' 启动 transport=streamable-http on http://0.0.0.0:%d/mcp",
        name, port,
    )
    target.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=port,
        log_level="INFO",
    )


def main() -> None:
    python = sys.executable
    procs: list[subprocess.Popen] = []
    log_dir = Path(os.getenv("MCP_LOG_DIR", "/tmp"))
    log_dir.mkdir(parents=True, exist_ok=True)

    for name, port in zip(SERVER_NAMES, PORTS):
        log_path = log_dir / f"mcp-{name}.log"
        log_f = open(log_path, "wb")
        logger.info("起子进程:port=%d name=%s log=%s", port, name, log_path)
        p = subprocess.Popen(
            [python, "-m", "knowledge.mcp_one", name, str(port)],
            stdout=log_f, stderr=subprocess.STDOUT,
        )
        procs.append(p)

    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    main()