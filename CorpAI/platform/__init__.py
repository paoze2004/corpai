"""
Platform 核心包 — 企业 AI Copilot 平台的写死部分。

包含:
- orchestrator/: 调度核心(意图/规划/ReAct/流式/网关)
- plugin_manager.py: 插件注册表(Phase 3)
- auth/: RBAC(Phase 3)
- observability/: 日志/指标/追踪(Phase 4)
- db.py: DatabasePool(Phase 2)

业务插件在 plugins/ 目录(独立,Phase 5)。

注:`platform` 与 Python 标准库同名,所有引用必须用 `CorpAI.platform.*` 全路径。
"""
