# CorpAI 项目 Makefile
# 用法：
#   make help          查看所有命令
#   make sync          装依赖
#   make test          跑测试
#   make run-weather   启动天气 MCP 服务
#   ...

.PHONY: help sync test test-unit test-mcp test-agent run-api run-weather run-ticket run-trip run-agent-weather run-agent-ticket run-agent-trip clean

help:  ## 显示帮助
	@echo "可用命令："
	@echo "  make sync              同步依赖（uv sync --group dev）"
	@echo "  make test              跑所有测试"
	@echo "  make test-unit         只跑纯单元测试（不依赖外部服务）"
	@echo "  make test-mcp          跑 MCP 服务测试（需要 MySQL）"
	@echo "  make test-agent        跑 A2A Agent 端到端测试（需要 MCP + A2A 服务都在跑）"
	@echo ""
	@echo "  make run-api           启动 FastAPI 后端（端口 8080）"
	@echo "  make run-weather       启动天气 MCP 服务（端口 8002）"
	@echo "  make run-ticket        启动票务 MCP 服务（端口 8001）"
	@echo "  make run-trip          启动行程 MCP 服务（端口 8003）"
	@echo "  make run-agent-weather 启动天气 A2A 代理（端口 5005）"
	@echo "  make run-agent-ticket  启动票务 A2A 代理（端口 5006）"
	@echo "  make run-agent-trip    启动行程 A2A 代理（端口 5007）"
	@echo ""
	@echo "  make clean             清理 __pycache__ 和 pytest 缓存"

# ==================== 依赖管理 ====================
sync:  ## 装运行时 + 开发依赖
	uv sync --group dev

# ==================== 测试 ====================
test:  ## 跑全部测试
	uv run pytest tests/

test-unit:  ## 只跑纯单元测试（不需要 MySQL / A2A 服务）
	uv run pytest tests/test_mcp_servers.py::TestFormatEncoder

test-mcp:  ## 跑 MCP 服务测试（需要 MySQL）
	uv run pytest tests/test_mcp_servers.py tests/test_mcp_services.py

test-agent:  ## 跑 Agent 端到端测试（需要 MCP + A2A 服务都启动）
	uv run pytest tests/test_agent_services.py

# ==================== 服务启动 ====================
run-api:  ## 启动 FastAPI 后端
	uv run python -m CorpAI.api.app

run-weather:  ## 启动天气 MCP 服务
	uv run python -m CorpAI.tools.weather

run-ticket:  ## 启动票务 MCP 服务
	uv run python -m CorpAI.tools.ticket

run-trip:  ## 启动行程 MCP 服务
	uv run python -m CorpAI.tools.trip

run-agent-weather:  ## 启动天气 A2A 代理
	uv run python -m CorpAI.agents.weather

run-agent-ticket:  ## 启动票务 A2A 代理
	uv run python -m CorpAI.agents.ticket

run-agent-trip:  ## 启动行程 A2A 代理
	uv run python -m CorpAI.agents.trip

# ==================== 清理 ====================
clean:  ## 清理 Python 缓存
	find . -type d -name "__pycache__" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	@echo "清理完成"
