"""sre_copilot MCP 入口 — 5 个 MCP server,每个一个独立子进程。

符合 Anthropic MCP 官方 spec(fastmcp 3.x + MCP SDK 2.x,
StreamableHTTP transport, JSON-RPC 2.0 wire)。

每个 server 独立进程,某个挂掉不影响其他;也避免 asyncio.run() 嵌套。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# (port, mcp_server_name) ── 跟 mcp_servers.SERVER_PORTS 对齐
PORTS = [8020, 8021, 8022, 8027, 8028]
# SERVER_NAMES 顺序跟 PORTS 一一对应
SERVER_NAMES = [
    "sre_copilot_incident",
    "sre_copilot_k8s",
    "sre_copilot_alert",
    "sre_copilot_bridge_hr",
    "sre_copilot_bridge_faq",
]


def _serve_one(name: str, port: int) -> None:
    """单个 server 进程入口:在指定端口跑一个 FastMCP server。

    通过 `python -m sre_copilot.mcp_one <server_name>` 调用,
    内部用 importlib 找对应 FastMCP 实例并启动。
    """
    from sre_copilot.mcp_servers import SERVER_PORTS

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
    """并行拉起 5 个独立子进程,每个跑一个 MCP server。"""
    python = sys.executable
    procs: list[subprocess.Popen] = []
    log_dir = Path(os.getenv("MCP_LOG_DIR", "/tmp"))
    log_dir.mkdir(parents=True, exist_ok=True)

    for name, port in zip(SERVER_NAMES, PORTS):
        log_path = log_dir / f"mcp-{name}.log"
        log_f = open(log_path, "wb")
        logger.info("起子进程:port=%d name=%s log=%s", port, name, log_path)
        p = subprocess.Popen(
            [python, "-m", "sre_copilot.mcp_one", name, str(port)],
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