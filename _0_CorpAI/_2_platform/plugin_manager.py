"""
Phase 3 Plugin Manager — entry_points 自动发现 + Pydantic v2 manifest。

设计依据:`docs/adr/0003-plugin-registration.md`

公开 API:
    PluginManifest — 严格 schema(`extra="forbid"`)
    PluginRegistry — register/unregister/get/list_*/find_by_intent
    discover_all() — 通过 `importlib.metadata.entry_points(group="platform.plugins")` 扫描

新增业务 plugin 的最小流程:
    1. 写 _1_plugins/<name>/plugin.py,实现 `register(registry) -> None` 函数
    2. 在 _1_plugins/<name>/pyproject.toml 的
       [project.entry-points."platform._1_plugins"] 段声明
       `name = "module.path:register"`
    3. `uv pip install -e ./_1_plugins/<name>` 即可被 `discover_all()` 找到
"""
from __future__ import annotations

import importlib
import importlib.metadata as md
import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)


class PluginManifest(BaseModel):
    """插件元数据 — 严格 schema(ADR §Manifest)。

    用 Pydantic v2 BaseModel,配置 `model_config = ConfigDict(extra="forbid")`
    拒绝未知字段,确保 schema 稳定。
    """
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64, description="唯一标识")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$", description="semver 三段")
    description: str = Field(min_length=1, max_length=512, description="给 LLM/UI 看")
    plugin_type: Literal["mcp_tool", "llm_agent"]

    # mcp_tool only — 远程端点(进程内调用可空)
    endpoint: str | None = Field(default=None, description="http://host:port")
    mcp_tool_name: str | None = Field(default=None, description="MCP 工具名,形如 query_weather")

    # llm_agent only
    llm_prompt: str | None = Field(default=None, description="系统 prompt 模板")
    summary_prompt: str | None = Field(
        default=None,
        description=("summary prompt 名(在 plugin.prompts 模块里查同名函数)。"
                     "wiring 用它 dispatch 替代原 if agent_name == '...' elif"),
    )
    # Phase 6 规约化:structured_tools 元素用 ToolDef 替代裸 dict
    # 提供 name/description/args_schema 三字段,平台 tools_gateway 校验
    structured_tools: list["ToolDef"] = Field(
        default_factory=list,
        description="Pydantic StructuredTool 列表(Phase 6 规约化)",
    )

    # common
    required_intents: list[str] = Field(default_factory=list, description="该 agent 处理的意图")
    permissions: list[str] = Field(default_factory=list, description="RBAC scopes,如 ['cs:read']")
    tags: list[str] = Field(default_factory=list, description="领域标签")

    def is_llm_agent(self) -> bool:
        return self.plugin_type == "llm_agent"

    def is_mcp_tool(self) -> bool:
        return self.plugin_type == "mcp_tool"


class ToolDef(BaseModel):
    """Phase 6 规约化:structured_tools 元素。"""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64, description="工具名")
    description: str = Field(min_length=1, max_length=512)
    args_schema: dict = Field(
        default_factory=dict,
        description="JSON Schema 风格参数 schema(可空)",
    )

    @field_validator("args_schema")
    @classmethod
    def _validate_args_schema(cls, v: dict) -> dict:
        """Phase 6:args_schema 必须是 dict,不能含可调用键,避免注入。"""
        if not isinstance(v, dict):
            raise ValueError("args_schema 必须是 dict")
        # 简化校验:key 只允许 [a-zA-Z0-9_]+
        for k in v:
            if not k.replace("_", "").isalnum():
                raise ValueError(f"args_schema key {k!r} 含非法字符")
        return v


class PluginRegistry:
    """注册表 — 内存内 dict,支持 register/unregister/get/list 查询。"""

    def __init__(self) -> None:
        self._items: dict[str, PluginManifest] = {}
        # Phase 5:wiring 通过 _plugin_modules 反查 plugin 的 prompts 模块
        # (避免 platform 直接 import 业务 plugin 私有符号)
        self._plugin_modules: dict[str, Any] = {}

    def register(self, manifest: PluginManifest) -> None:
        """校验 name 唯一 + 类型必填字段后存。"""
        if not isinstance(manifest, PluginManifest):
            raise TypeError(f"register 需要 PluginManifest,实际 {type(manifest)}")
        if manifest.name in self._items:
            raise ValueError(f"plugin name 重复: {manifest.name!r}")
        if manifest.is_llm_agent() and not manifest.llm_prompt:
            raise ValueError(f"llm_agent {manifest.name!r} 必须有 llm_prompt")
        if manifest.is_mcp_tool() and not manifest.endpoint:
            raise ValueError(f"mcp_tool {manifest.name!r} 必须有 endpoint")
        # Phase 5:permissions 必须非空(CLAUDE.md "每个插件声明至少 1 个 RBAC scope")
        if not manifest.permissions:
            raise ValueError(
                f"plugin {manifest.name!r} 必须声明 ≥1 个 RBAC scope (permissions)"
            )
        self._items[manifest.name] = manifest

    def unregister(self, name: str) -> bool:
        """返 True/False 表示是否存在。"""
        return self._items.pop(name, None) is not None

    def get(self, name: str) -> PluginManifest | None:
        return self._items.get(name)

    def list_all(self) -> list[PluginManifest]:
        return list(self._items.values())

    def list_agents(self) -> list[PluginManifest]:
        return [m for m in self._items.values() if m.is_llm_agent()]

    def list_tools(self) -> list[PluginManifest]:
        return [m for m in self._items.values() if m.is_mcp_tool()]

    def find_by_intent(self, intent: str) -> PluginManifest | None:
        """找处理该 intent 的第一个 llm_agent(register 顺序)。"""
        for m in self._items.values():
            if m.is_llm_agent() and intent in m.required_intents:
                return m
        return None

    def agents_for_intent(self, intent: str) -> PluginManifest | None:
        """Phase 5:复用 find_by_intent,只返 llm_agent 类型。"""
        return self.find_by_intent(intent)


def discover_all() -> PluginRegistry:
    """扫描 entry_points group="platform._1_plugins" 自动加载。

    每个 entry_point 必须提供 `register(registry)` 函数。
    失败 log warning 不挂 — Phase 3 平台要"软启动"。

    Returns:
        PluginRegistry 实例,含所有成功加载的插件。
    """
    r = PluginRegistry()
    eps = md.entry_points(group="platform.plugins")
    for ep in eps:
        try:
            register_fn = ep.load()
            register_fn(r)
            # Phase 5:同时存 module 句柄,wiring 用它反射 plugin.prompts。
            # entry point 形如 `<package>.plugin:register`,取 parent package。
            _mod_path = ep.module.rsplit(".", 1)[0] if "." in ep.module else ep.module
            r._plugin_modules[ep.name] = importlib.import_module(_mod_path)
            logger.info(f"plugin loaded: {ep.name} ({ep.value})")
        except Exception as e:
            logger.warning(f"plugin '{ep.name}' 加载失败: {e}")
    return r


__all__ = ["PluginManifest", "PluginRegistry", "discover_all"]
