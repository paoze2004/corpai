"""
_0_CorpAI —— 企业 AI Copilot 平台核心包

包内模块：
    config           配置管理（环境变量、数据库、API 等）
    logging          结构化日志
    core/memory      对话记忆（6 层 MemoryPool,per-user）
    core/prompts     提示模板(intent / planning / react / system)
    platform/orchestrator  编排服务(IntentRecognizer / TaskPlanner / ReActRunner)
    platform/auth    JWT / RBAC / scopes
    platform/observability trace / log / metrics / call_record
    platform/db      MySQL 连接池单例
    platform/plugin_manager  entry_points 自动发现 + 注册表
    api/app          FastAPI 后端入口(用户 SPA + admin/ + /api/chat)
    api/admin_router 管理后台 5 页 API
    utils/format     JSON encoder + strip_think
"""

__version__ = "0.1.0"
