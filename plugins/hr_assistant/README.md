# corpai-plugin-hr-assistant

企业 HR 助手 — 员工福利查询 + 人事政策问答。

## 安装 + 启动

```bash
cd D:\develop\PycharmProjects\CorpAI
uv pip install -e plugins/hr_assistant
.venv\Scripts\python.exe -m hr_assistant.entry  # 启 A2A server :5010
```

## Manifest

- `hr_assistant`(llm_agent, :5010) — 处理 intent `hr` / `benefits`
- `hr_assistant_benefits_mcp`(mcp_tool, :8010) — `query_benefits`
- `hr_assistant_policy_mcp`(mcp_tool, :8011) — `query_policy`

## 业务数据

| ID 范围 | 数量 | 类别 |
|--------|------|------|
| B001-B008 | 8 | 福利项目(社保/补充医疗/体检/团建/设备/培训/餐饮/通讯) |
| P001-P010 | 10 | 人事政策(年假/病假/缺勤/报销/调休/婚假/产假/丧假/离职/考勤) |

## RBAC

`permissions: [hr:read, hr:write]`