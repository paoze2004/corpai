"""
pytest 配置文件

提供测试夹具（fixtures）和配置选项
"""

import pytest
import sys
import os

# 确保 _0_CorpAI 模块可以导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


@pytest.fixture(scope="session")
def mcp_services_available():
    """检查 MCP 服务是否可用"""
    import socket

    def is_port_open(host, port):
        """检查端口是否开放"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        try:
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception:
            return False

    services = {
        "weather_mcp": ("127.0.0.1", 8002),
        "ticket_mcp": ("127.0.0.1", 8001),
        "trip_mcp": ("127.0.0.1", 8003),
        "weather_a2a": ("127.0.0.1", 5005),
        "ticket_a2a": ("127.0.0.1", 5006),
        "trip_a2a": ("127.0.0.1", 5007),
    }

    status = {}
    for name, (host, port) in services.items():
        status[name] = is_port_open(host, port)

    return status


@pytest.fixture(scope="session")
def database_pool_available():
    """Phase 2:DatabasePool 单例健康检查 — 区别 database_available 的 raw ping."""
    try:
        from _0_CorpAI._2_platform.db import DatabasePool
        return DatabasePool.get().healthcheck()
    except Exception:
        return False


@pytest.fixture(scope="session")
def database_available():
    """检查数据库是否可用"""
    try:
        import mysql.connector
        from _0_CorpAI.config import Config
        conf = Config()
        conn = mysql.connector.connect(
            host=conf.host,
            user=conf.user,
            password=conf.password,
            database=conf.database
        )
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def milvus_available():
    """检查 Milvus 是否可用"""
    try:
        from pymilvus import connections
        from _0_CorpAI.config import Config
        conf = Config()
        connections.connect(alias="default",
                          host=conf.milvus_host,
                          port=conf.milvus_port)
        return True
    except Exception:
        return False


def pytest_configure(config):
    """pytest 启动时的配置"""
    config.addinivalue_line(
        "markers", "mcp: 测试需要 MCP 服务运行"
    )
    config.addinivalue_line(
        "markers", "a2a: 测试需要 A2A 服务运行"
    )
    config.addinivalue_line(
        "markers", "database: 测试需要数据库连接"
    )
    config.addinivalue_line(
        "markers", "milvus: 测试需要 Milvus 连接"
    )
    config.addinivalue_line(
        "markers", "integration: 集成测试"
    )
