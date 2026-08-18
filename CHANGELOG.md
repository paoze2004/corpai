# CHANGELOG

CorpAI 项目的改动日志。格式参照 [Keep a Changelog](https://keepachangelog.com/),日期用 `YYYY-MM-DD`。

---

## [Unreleased]

### Breaking
- 顶层目录重命名 + 加 `_0_`–`_5_` 编号前缀(见 `LAYERS.md`)
- MCP 协议升级:从 python-a2a 私有 FastMCP → **Anthropic 官方 spec**(fastmcp 3.x + MCP SDK 2.x,JSON-RPC 2.0 over StreamableHTTP)
- Plugin 测试目录改名 `tests/` → `<plugin>_tests/`,打破 pytest ImportPathMismatchError
- 3 个 plugin 加 `[build-system] hatchling` + wheel target,distribution name 必须 `corpai-plugin-*`

### Added
- 顶层 README.md(完全重写,反映所有改动)
- `LAYERS.md`(分层编号约定)
- `ARCHITECTURE.md`(详细架构:Composition Root、MCP 真协议、Memory 模型、Plugin 协议、RBAC 链路)
- `CLAUDE.md`(Claude Code 项目指南)
- `CONTRIBUTING.md`(开发指南:跑测试 / 加 plugin / commit 规范 / Code Review checklist)
- `CHANGELOG.md`(本文件)
- `docs/adr/0001-clean-architecture.md`(Clean Architecture 分层 ADR)
- 3 个 plugin 的 `mcp_servers.py` / `mcp_main.py` / `mcp_one.py`(官方 MCP 实现)
- plugin manifest endpoint 统一 hr_assistant → `:8001`(单端口 9 tools)
- `make run-mcp-*` target(3 个 plugin 各 1 个)
- hr_assistant v3.2:8 个 action + 1 个 query + 2 个 bridge → MCP server 单端口 9 tools

### Changed
- `_0_CorpAI/_2_platform/wiring.py` 加注释说明 Composition Root 唯一性
- `bridges.py`:从 `asyncio.new_event_loop().run_until_complete()` hack → `asyncio.run()` + `BridgeAsyncioConflictError` 明确错误信息;暴露 `*_async` 版本供 ReAct loop 直接 await
- Makefile:`test-plugins` / `test-phase5` 加注释说明 `make install-plugins` 前置
- `.env.example`:`FAQ_URL` 标 deprecated,加 `KNOWLEDGE_URL`
- `corpai-milvus.yml`:删除过时的 `insurance_mcp :8010` 注释
- 3 个 plugin README.md:重写,反映实际 manifest / 端口 / 测试

### Fixed
- `bridges.py` sync wrapper 在 async 上下文抛模糊 `RuntimeError` → 抛明确 `BridgeAsyncioConflictError`
- `sre_copilot/tests/test_incident_flow.py::test_metrics_agent_runs`:硬编码 `"data"` 键导致无 PROMETHEUS_URL 时挂 → 适配 not_configured 状态,断言改为 `status` 键必现

### Removed
- 旧 `README.md`(被替换为重写版)
- 旧 `tests/conftest.py` in hr_assistant + knowledge(冲突源)

### Migration notes

从老版本升级:

1. `git pull` 后跑 `make install-plugins` 重新装 3 个 plugin
2. **Python 包导入**全部从 `CorpAI.x.y` → `_0_CorpAI._N_x._M_y`
   - `from CorpAI.api.app import app` → `from _0_CorpAI._0_api.app import app`
   - `from CorpAI.platform.wiring` → `from _0_CorpAI._2_platform.wiring`
3. **Plugin manifest endpoint** hr_assistant 全部改成 `:8001`(单端口)
4. **MCP 客户端**如有自定义代码:从 `requests.post("/mcp/tools/{name}")` → `fastmcp.Client(url).call_tool(name, args)`
5. **Plugin 测试目录**名变了,IDE import 路径可能要更新

---

## 历史快照(仅保留要点)

### v3.4.12(2026-08)build_approved_card flatten 成 v1 格式
### v3.4.11(2026-08)回退 v1 卡片格式(GET 显示飞书 sandbox 拒绝 v2)
### v3.4.7(2026-08)安全硬化与异步化收敛(见 `AUDIT_REPORT.md`)
### v3.4.0(2026-08)Phase 0-7 完整重构
### v3.2(2026-08)删 70% 玩具,保留 14 个真工具 + bridge 显式失败 + ADR 0011
### v3.1(2026-08)rename `devops_copilot` → `sre_copilot`,absorb `platform/sre/` into plugin
### v3.0(2026-07)Phase 0:稳定基线 + ChatService 拆分 + 改名 CorpAI