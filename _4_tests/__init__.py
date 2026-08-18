"""
_0_CorpAI 测试包

测试目录结构：
├── conftest.py          # pytest 配置和夹具
├── test_mcp_servers.py  # MCP 服务器测试（现有）
├── test_mcp_services.py # MCP 服务集成测试（新增）
└── test_agent_services.py # Agent 服务集成测试（新增）

运行测试：

1. 运行 MCP 服务测试（需要数据库，不需要启动服务器）：
   cd _0_CorpAI
   python -m pytest _4_tests/test_mcp_services.py -v

2. 运行 Agent 服务测试（需要 MCP 和 A2A 服务器运行）：
   # 终端1: 启动 MCP 服务器
   python mcp_server/mcp_weather_server.py   # 端口 8002
   python mcp_server/mcp_ticket_server.py    # 端口 8001
   python mcp_server/mcp_trip_server.py      # 端口 8003

   # 终端2: 启动 A2A 服务器
   python a2a_server/weather_server.py  # 端口 5005
   python a2a_server/ticket_server.py    # 端口 5006
   python a2a_server/trip_server.py     # 端口 5007

   # 终端3: 运行测试
   python -m pytest _4_tests/test_agent_services.py -v

3. 运行所有测试：
   python -m pytest _4_tests/ -v

测试前置条件：
- MySQL 数据库运行中，包含 _0_CorpAI 数据库
- Milvus 向量数据库运行中（用于旅游团搜索）
- MCP 服务器运行在 8001/8002/8003 端口
- A2A 服务器运行在 5005/5006/5007 端口
"""
