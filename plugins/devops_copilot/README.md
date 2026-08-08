# corpai-plugin-devops-copilot

企业 DevOps 副驾 — 工单查询 + On-call 联系 + Pod 重启(dry_run)。

## 安装 + 启动

```bash
cd D:\develop\PycharmProjects\CorpAI
uv pip install -e plugins/devops_copilot
.venv\Scripts\python.exe -m devops_copilot.entry  # 启 A2A server :5020
```

## Manifest

- `devops_copilot`(llm_agent, :5020) — 处理 intent `devops`
- `devops_copilot_incident_mcp`(mcp_tool, :8020) — `query_incident` / `list_recent_incidents` / `query_oncall`
- `devops_copilot_k8s_mcp`(mcp_tool, :8021) — `restart_pod`

## 业务数据

- 8 个工单:`INC-001 ~ INC-008`(P0 ~ P3,4 个团队分派)
- 4 个 on-call 团队:`platform` / `data` / `security` / `network`

## RBAC

| Manifest | permissions | 说明 |
|----------|------------|------|
| `devops_copilot` (agent) | `[devops:read, devops:write]` | 查 + 写双重 |
| `devops_copilot_k8s_mcp` | `[devops:write]` | 只写,需 `devops:write` scope |

`restart_pod` 内部 `has_scope("devops:write", ...)` 二次校验 — RBAC 链路打通 showcase。

## Dry-Run

`K8S_DRY_RUN=true` 默认,生产设 `K8S_DRY_RUN=false` 启用真操作。