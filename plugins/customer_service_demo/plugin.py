"""Scaffold plugin — entry_points 接入测试用。不承载真实业务。"""
from CorpAI.platform.plugin_manager import PluginManifest, PluginRegistry


def register(registry: PluginRegistry) -> None:
    """演示用 mcp_tool:仅验证 discover_all 跑通,真实业务由 3 真 plugin 承担。"""
    registry.register(PluginManifest(
        name="customer_service_demo",
        version="0.0.1",
        description="Scaffold demo — 验证 plugin_manager.discover_all() 自动加载",
        plugin_type="mcp_tool",
        endpoint="http://localhost:9999",
        mcp_tool_name="echo_demo",
        permissions=["cs:read"],
        tags=["demo", "scaffolding"],
    ))
