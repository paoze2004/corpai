"""sre_copilot entry — Phase 5 简化版。

注意:python_a2a.A2AServer 是 Flask WSGI app,不能用 uvicorn(ASGI),
必须用 python_a2a.run_server()(底层 Flask dev server,dev 够用)。
"""
import logging

from python_a2a import run_server

from _0_CorpAI._3_utils.dotenv import load_env

# v3.2:所有 entry 第一件事 = 加载 .env(.env 是单一配置源)
load_env()

from sre_copilot.server import SreCopilotServer

logger = logging.getLogger(__name__)


def main() -> None:
    server = SreCopilotServer()
    logger.info("sre_copilot A2A server 监听 http://0.0.0.0:5020")
    run_server(server, host="0.0.0.0", port=5020, debug=False)


if __name__ == "__main__":
    main()
