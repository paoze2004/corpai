"""faq entry — Phase 5 简化版:启 A2A server。"""
import logging

import uvicorn

from faq.server import FaqServer

logger = logging.getLogger(__name__)


def main() -> None:
    server = FaqServer()
    logger.info("faq A2A server 监听 http://0.0.0.0:5030")
    uvicorn.run(server, host="0.0.0.0", port=5030, log_level="info")


if __name__ == "__main__":
    main()
