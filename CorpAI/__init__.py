"""
CorpAI —— 智能旅游助手核心包

包内模块：
    config           配置管理（环境变量、数据库、API 等）
    create_logger    日志记录器
    memory           对话记忆（短期/用户偏好/任务上下文）
    main_prompts     提示模板管理
    chat_service     核心对话服务（意图识别 + ReAct 编排）
    api_server       FastAPI 后端入口
    utils            工具集（日期格式化、天气爬虫等）
    mcp_server       MCP 工具服务端（天气/票务/行程）
    a2a_server       A2A 智能体服务端（天气/票务/行程）
"""

__version__ = "0.1.0"
