# Demo Plugin — Scaffold for plugin_manager discovery test

## Purpose

这个插件包仅作 `platform/plugin_manager.py:discover_all()` 的 entry_points 接入验证,
**不承载真实业务**。真实业务由 3 个真 plugin 承担:

- `hr_assistant` — 员工福利 + 人事政策
- `devops_copilot` — 工单 + On-call + Pod 重启
- `faq` — 企业 KB RAG

## Install (本地开发)

```bash
cd CorpAI
uv pip install -e plugins/customer_service_demo
```

## Manifest

- name: `customer_service_demo`
- plugin_type: `mcp_tool`
- endpoint: `http://localhost:9999` (占位,实际未启动)
- permissions: `["cs:read"]`

## Discover Test

```bash
uv run python -c "
from CorpAI.platform.plugin_manager import discover_all
r = discover_all()
print([m.name for m in r.list_all()])
# 期望: ['customer_service_demo', 'hr_assistant', 'devops_copilot', 'faq', ...]
"
```
