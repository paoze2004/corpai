"""faq entry — Phase 5 简化版:启 A2A server + 注入默认 KB。

注意:python_a2a.A2AServer 是 Flask WSGI app,不能用 uvicorn(ASGI),
必须用 python_a2a.run_server()(底层 Flask dev server,dev 够用)。
"""
import logging

from python_a2a import run_server

from _0_CorpAI._3_utils.dotenv import load_env

# v3.2:加载 .env(单一配置源)
load_env()

from knowledge.seed import seed_default_kb
from knowledge.server import KnowledgeServer

logger = logging.getLogger(__name__)


def main() -> None:
    # 启动时注入默认企业 FAQ KB(幂等)
    n = seed_default_kb()
    logger.info(f"faq KB 已注入 {n} 条默认文档")
    server = KnowledgeServer()
    logger.info("faq A2A server 监听 http://0.0.0.0:5030")
    run_server(server, host="0.0.0.0", port=5030, debug=False)


if __name__ == "__main__":
    main()
