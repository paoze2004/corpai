# corpai-plugin-hr-assistant v3.2

企业 HR 助手 — **8 个操作类工具**(写 MySQL 真业务)+ **2 个跨插件 bridge**(knowledge/sre)。

v3.2 改动(2026-08):
- MCP 端口统一到 `:8001`(1 个 FastMCP server,9 tools);废弃老的 8 端口架构(8017-8026)
- 删掉 v3.0 之前的 KB 字典玩具(`query_benefits` / `query_policy` 走死字典 82 条)
- 全部工具走 Anthropic 官方 MCP spec(fastmcp 3.x + MCP SDK 2.x,JSON-RPC 2.0 over StreamableHTTP)

---

## 安装 + 启动

```bash
cd D:\develop\PycharmProjects\CorpAI
uv pip install -e _1_plugins/hr_assistant

# A2A server(LLM agent 入口)
.venv\Scripts\python.exe -m hr_assistant.entry  # :5010

# MCP server(工具入口,Anthropic 官方 spec)
.venv\Scripts\python.exe -m hr_assistant.mcp_main  # :8001
# 或 make run-mcp-hr-assistant
```

---

## Manifest 清单(11 个,全注册到 platform)

| Manifest name | Type | Endpoint | MCP tool | RBAC scope | 用途 |
|---|---|---|---|---|---|
| `hr_assistant` | llm_agent | :5010 | — | hr:read · hr:write | LLM agent 入口 |
| `hr_assistant_leave_mcp` | mcp_tool | :8001 | `submit_leave` | hr:write | 请假申请 |
| `hr_assistant_reim_mcp` | mcp_tool | :8001 | `submit_reimbursement` | hr:write | 报销申请 |
| `hr_assistant_cert_mcp` | mcp_tool | :8001 | `apply_certificate` | hr:write | 证明申请 |
| `hr_assistant_asset_mcp` | mcp_tool | :8001 | `request_asset` | hr:write | 资产申请 |
| `hr_assistant_train_mcp` | mcp_tool | :8001 | `register_training` | hr:write | 培训报名 |
| `hr_assistant_reg_mcp` | mcp_tool | :8001 | `apply_regularization` | hr:write | 转正申请 |
| `hr_assistant_approve_mcp` | mcp_tool | :8001 | `approve_request` | hr:write | 审批(approve/reject) |
| `hr_assistant_my_mcp` | mcp_tool | :8001 | `query_my_requests` | chat:write | 我的申请列表 |
| `hr_assistant_bridge_knowledge_mcp` | mcp_tool | :8001 | `cross_query_knowledge` | chat:write | 跨插件:HR → knowledge 兜底 |
| `hr_assistant_bridge_sre_mcp` | mcp_tool | :8001 | `cross_check_sre` | hr:write | 跨插件:HR → SRE 资产去重 / oncall 通知 |

> 所有 mcp_tool manifest 的 endpoint 都指向 **同一个** `:8001` server。`mcp_tool_name` 字段告诉 platform 调哪个 tool 函数。

---

## MCP tools(9 个,跑在 :8001)

### 写操作(7,需 hr:write)

| Tool | 必填参数 | 说明 |
|---|---|---|
| `submit_leave` | leave_type, start_date, end_date, days, reason | 请假(annual/sick/personal) |
| `submit_reimbursement` | category, amount, description | 报销(travel/office/training/meal/other) |
| `apply_certificate` | cert_type, purpose | 证明(employment/income/separation/work_permit) |
| `request_asset` | asset_type, reason | 资产(laptop/monitor/keyboard/...) |
| `register_training` | training_name, training_type, business_relevance | 培训(external/internal/certification) |
| `apply_regularization` | probation_start, probation_end, achievements | 转正申请 |
| `approve_request` | request_id, target_type, action | 审批(approve/reject,reject 必填 approval_note) |

### 读 / 撤销(2)

| Tool | 必填参数 | 说明 |
|---|---|---|
| `cancel_leave` | request_id | 撤销请假(仅 pending) |
| `query_my_requests` | (无,可选 target_type/status/limit) | 我的申请列表 |

### 跨插件 bridge(2)

| Tool | 目标 plugin | 用途 |
|---|---|---|
| `cross_query_knowledge` | knowledge(:8030) | HR KB 未命中时兜底 |
| `cross_check_sre` | sre_copilot(:8020/:8021) | 资产去重 + oncall 通知 |

---

## RBAC scope 链路

| 角色 | scopes | 可访问 tools |
|---|---|---|
| employee + hr | `hr:read`, `hr:write` | 全部 9 个 |
| employee(无 hr scope) | — | 不能调 hr plugin 任何 tool |
| hr + 跨 plugin 演示用户 | + `knowledge:read`, `sre:read` | 跨 plugin bridge 可调 |

`has_scope(needed, scopes)` 在 `_0_CorpAI/_2_platform/auth/scopes.py:has_scope` 校验。

---

## 状态机(写操作)

```
pending ──┬──→ approved
          ├──→ rejected
          └──→ cancelled (仅 cancel_leave 触发,且仅 pending 状态)
```

`hr_leave_requests` / `hr_reimbursements` 等表存状态,每次 transition 写 `hr_audit_log`(含 trace_id)。

---

## 测试

```bash
cd _1_plugins/hr_assistant
uv run pytest -m "not integration"
```

`test_plugin.py` 覆盖 register / manifest / prompt 校验。`test_e2e.py` 覆盖端到端流程(集成,默认 skip,需 MySQL)。

---

## 业务数据(真实写入 MySQL)

`hr_leave_requests` / `hr_reimbursements` / `hr_certificates` / `hr_asset_requests` / `hr_training_requests` / `hr_regularization_requests` —— 6 张业务表 + `hr_audit_log` 审计表。

DDL 见 `_3_sql/create_all_tables.sql`,Phase 3+ 增量见 `_2_scripts/migrate_*.py`。

---

## 相关文件

- `_1_plugins/hr_assistant/src/hr_assistant/mcp_servers.py` — FastMCP server 定义 + tool 函数
- `_1_plugins/hr_assistant/src/hr_assistant/mcp_main.py` — 启动入口(子进程拉起 server)
- `_1_plugins/hr_assistant/src/hr_assistant/mcp_one.py` — 单 server 子进程入口
- `_1_plugins/hr_assistant/src/hr_assistant/actions.py` — 业务逻辑(写 MySQL)
- `_1_plugins/hr_assistant/src/hr_assistant/server.py` — A2A server(LLM agent 入口)
- `_1_plugins/hr_assistant/src/hr_assistant/plugin.py` — manifest 注册