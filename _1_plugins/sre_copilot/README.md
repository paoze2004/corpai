# corpai-plugin-sre-copilot v3.1

企业 SRE 副驾 — 工单查询 + On-call 联系 + 告警响应 + Pod 日志(dry_run)+ **2 个跨插件 bridge**。

> 重命名:`devops_copilot` → `sre_copilot`(v3.0)。RBAC scope `devops:*` → `sre:*`。

---

## 安装 + 启动

```bash
cd D:\develop\PycharmProjects\CorpAI
uv pip install -e _1_plugins/sre_copilot

# A2A server(LLM agent 入口)
.venv\Scripts\python.exe -m sre_copilot.entry  # :5020

# MCP servers(工具入口,Anthropic 官方 spec)
.venv\Scripts\python.exe -m sre_copilot.mcp_main  # 5 个 server 子进程
# 或 make run-mcp-sre-copilot
# 端口:8020(incident+oncall)/ 8021(k8s)/ 8022(alert)/ 8027(bridge-hr)/ 8028(bridge-knowledge)
```

---

## Manifest 清单(7 个)

| Manifest name | Type | Endpoint | MCP tool | RBAC scope | 用途 |
|---|---|---|---|---|---|
| `sre_copilot` | llm_agent | :5020 | — | sre:read · sre:write | LLM agent 入口 |
| `sre_copilot_incident_mcp` | mcp_tool | :8020 | `query_incident` | sre:read | Jira 工单查询 |
| `sre_copilot_oncall_mcp` | mcp_tool | :8020 | `query_oncall` | sre:read | PagerDuty on-call |
| `sre_copilot_alert_mcp` | mcp_tool | :8022 | `query_alert` | sre:read | Prometheus Alertmanager |
| `sre_copilot_k8s_mcp` | mcp_tool | :8021 | `get_pod_logs` | sre:read | K8s Pod 日志(dry_run) |
| `sre_copilot_bridge_hr_mcp` | mcp_tool | :8027 | `cross_check_hr` | sre:read | 跨插件:SRE → HR |
| `sre_copilot_bridge_knowledge_mcp` | mcp_tool | :8028 | `cross_query_knowledge` | sre:read | 跨插件:SRE → knowledge |

> 注意:`incident_mcp` 和 `oncall_mcp` **共享同一 server**:8020(2 tools 1 server)。其余 server 各 1 tool。

---

## MCP tools(6 个,跑在 5 个 server)

| Tool | 端口 | 必填参数 | 后端 SDK |
|---|---|---|---|
| `query_incident` | :8020 | incident_id?/status?/priority?/limit? | Jira REST API v3(JIRA_URL/EMAIL/TOKEN) |
| `query_oncall` | :8020 | team(默认 platform) | PagerDuty REST API |
| `query_alert` | :8022 | alert_id?/severity?/service?/state? | Prometheus Alertmanager v2 |
| `get_pod_logs` | :8021 | pod_name, namespace, tail_lines | kubernetes-python(KUBECONFIG) |
| `cross_check_hr` | :8027 | authorization, request_id | MCP bridge → hr_assistant(:8001) |
| `cross_query_knowledge` | :8028 | query, top_k | MCP bridge → knowledge(:8030) |

---

## 跨插件 bridge(2)

| Bridge | 调谁 | 用途 |
|---|---|---|
| `cross_check_hr(:8027)` | `hr_assistant.query_my_requests(:8001)` | 请假触发 oncall 备份检查 |
| `cross_query_knowledge(:8028)` | `knowledge.query_knowledge(:8030)` | SOP 兜底补全 |

bridge 走 fastmcp `Client` async 调用,**显式失败 + Counter**(HR_BRIDGE_ERRORS_TOTAL{kind=timeout/unreachable/error/...})。

---

## 错误模型(显式,不 silent)

- 401 retry 一次,仍失败 → `http401` + Counter
- 超时 → `timeout` + Counter
- 不可达 → `unreachable` + Counter
- 4xx/5xx → `http4xx`/`http5xx` + Counter
- JSON 解析失败 → `json_decode` + Counter
- 业务错误 → 显式 `status`(not_found / invalid)
- 配置缺失 → `not_configured` + `required_env` 列表

---

## Dry-Run

`K8S_DRY_RUN=true`(默认)→ `get_pod_logs` 返 stub 日志,生产设 `K8S_DRY_RUN=false` 启用真 K8s API。`SRE_DRY_RUN=true` 控制 async executor(Redis Stream consumer)。

---

## 测试

```bash
cd _1_plugins/sre_copilot
uv run pytest -m "not integration"
```

`test_plugin.py` 覆盖 7 manifest / RBAC / SDK 错误分类 / Kafka pipeline。
`test_incident_flow.py` 端到端 6 agent 流水线(部分需要 PROMETHEUS_URL,JIRA_TOKEN 等真实配置,默认 skip)。

---

## 相关文件

- `_1_plugins/sre_copilot/src/sre_copilot/tools.py` — 4 个真工具实现(Jira/PagerDuty/Prometheus/K8s)
- `_1_plugins/sre_copilot/src/sre_copilot/bridges.py` — 2 个 bridge(用 fastmcp Client)
- `_1_plugins/sre_copilot/src/sre_copilot/mcp_servers.py` — FastMCP server 定义
- `_1_plugins/sre_copilot/src/sre_copilot/mcp_main.py` — 启动入口(子进程拉起 5 个 server)
- `_1_plugins/sre_copilot/src/sre_copilot/mcp_one.py` — 单 server 子进程入口
- `_1_plugins/sre_copilot/src/sre_copilot/server.py` — A2A server(LLM agent 入口)
- `_1_plugins/sre_copilot/src/sre_copilot/plugin.py` — manifest 注册