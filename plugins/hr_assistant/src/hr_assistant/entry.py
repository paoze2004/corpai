"""hr_assistant entry — Phase 5 简化版:启 A2A server 单一进程。"""
import logging

import uvicorn

from hr_assistant.server import HrAssistantServer

logger = logging.getLogger(__name__)


def main() -> None:
    server = HrAssistantServer()
    logger.info("hr_assistant A2A server 监听 http://0.0.0.0:5010")
    uvicorn.run(server, host="0.0.0.0", port=5010, log_level="info")


if __name__ == "__main__":
    main()
