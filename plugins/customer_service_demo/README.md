# Phase 3 Demo Plugin — Customer Service Scaffolding

## Purpose

这个插件包只是 Phase 3 脚手架,验证 `platform/plugin_manager.py:discover_all()` 能通过
`importlib.metadata.entry_points(group="platform.plugins")` 自动加载。

## Install (本地开发)

```bash
cd CorpAI
uv pip install -e plugins/customer_service_demo
```

Phase 5 会替换为真实业务插件(customer_service / hr_assistant / devops_copilot / faq)。

## Manifest

- name: `customer_service_demo`
- plugin_type: `mcp_tool`
- endpoint: `http://localhost:9999` (占位,实际未启动)
- permissions: `["customer_service:read"]`

## Discover Test

```bash
uv run python -c "
from CorpAI.platform.plugin_manager import discover_all
r = discover_all()
print([m.name for m in r.list_all()])
# 期望: ['customer_service_demo']
"
```
