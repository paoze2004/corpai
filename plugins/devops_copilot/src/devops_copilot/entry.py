"""devops_copilot entry — Phase 5 简化版。"""
import logging

import uvicorn

from devops_copilot.server import DevopsCopilotServer

logger = logging.getLogger(__name__)


def main() -> None:
    server = DevopsCopilotServer()
    logger.info("devops_copilot A2A server 监听 http://0.0.0.0:5020")
    uvicorn.run(server, host="0.0.0.0", port=5020, log_level="info")


if __name__ == "__main__":
    main()
