# corpai-plugin-hr-assistant

Phase 5:HR 助手 — 保险方案比较 + 假期政策 + 缺勤申报。

## 安装 + 启动

```bash
cd D:\develop\PycharmProjects\CorpAI
uv pip install -e plugins/hr_assistant
.venv\Scripts\python.exe -m hr_assistant.entry  # 启 A2A server :5010
```

## Manifest

- `hr_assistant`(llm_agent, :5010)
- `hr_assistant_insurance_mcp`(mcp_tool, :8010)
- `hr_assistant_policy_mcp`(mcp_tool, :8011)

## RBAC

`permissions: [hr:read, hr:write]`
