# corpai-plugin-sre-copilot

企业 SRE 副驾 — 工单查询 + On-call 联系 + Pod 重启(dry_run)。

## 安装 + 启动

```bash
cd D:\develop\PycharmProjects\CorpAI
uv pip install -e plugins/sre_copilot
.venv\Scripts\python.exe -m sre_copilot.entry  # 启 A2A server :5020
```

## Manifest

- `sre_copilot`(llm_agent, :5020) — 处理 intent `devops`
- `sre_copilot_incident_mcp`(mcp_tool, :8020) — `query_incident` / `list_recent_incidents` / `query_oncall`
- `sre_copilot_k8s_mcp`(mcp_tool, :8021) — `restart_pod`

## 业务数据

- 8 个工单:`INC-001 ~ INC-008`(P0 ~ P3,4 个团队分派)
- 4 个 on-call 团队:`platform` / `data` / `security` / `network`

## RBAC

| Manifest | permissions | 说明 |
|----------|------------|------|
| `sre_copilot` (agent) | `[sre:read, sre:write]` | 查 + 写双重 |
| `sre_copilot_k8s_mcp` | `[sre:write]` | 只写,需 `sre:write` scope |

`restart_pod` 内部 `has_scope("sre:write", ...)` 二次校验 — RBAC 链路打通 showcase。

## Dry-Run

`K8S_DRY_RUN=true` 默认,生产设 `K8S_DRY_RUN=false` 启用真操作。