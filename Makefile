# CorpAI 项目 Makefile
# 用法:
#   make help           查看所有命令
#   make sync           装依赖
#   make test           跑全部测试
#   make run-api        启 FastAPI 后端
#   ...

.PHONY: help sync test test-unit test-platform test-auth test-observability test-plugins test-phase3 test-phase4 test-phase5 install-plugins migrate-phase2 migrate-phase3 migrate-phase4 bootstrap-superadmin run-api run-hr-assistant run-sre-copilot run-faq clean

help:  ## 显示帮助
	@echo "可用命令:"
	@echo "  make sync                 同步依赖(uv sync --group dev)"
	@echo "  make test                 跑全部测试"
	@echo "  make test-unit            只跑纯单元测试(不依赖外部服务)"
	@echo "  make test-platform        Phase 1.7 + Phase 2 orchestrator/memory_pool"
	@echo "  make test-auth            Phase 3 RBAC + JWT 单元测试"
	@echo "  make test-observability   Phase 4 Observability 单元测试(trace/log/metrics/call_record)"
	@echo "  make test-plugins         Phase 5 3 个真插件单元测试"
	@echo "  make test-phase3          Phase 1+2+3 全部单元测试"
	@echo "  make test-phase4          Phase 1+2+3+4 全部单元测试"
	@echo "  make test-phase5          Phase 1+2+3+4+5 全部单元测试"
	@echo "  make install-plugins      装 3 个真插件(本地 editable)"
	@echo "  make migrate-phase2       跑 Phase 2 MySQL 迁移(user_id + task_context + cross_agent_context)"
	@echo "  make migrate-phase3       跑 Phase 3 RBAC 迁移(auth_* 4 张表)"
	@echo "  make migrate-phase4       跑 Phase 4 Observability 迁移(call_records 表)"
	@echo "  make bootstrap-superadmin 引导创建第一个 super_admin(要求 AUTH_JWT_SECRET 已设)"
	@echo ""
	@echo "  make run-api              启动 FastAPI 后端(端口 8080)"
	@echo "  make run-hr-assistant     启 hr_assistant A2A server(端口 5010)"
	@echo "  make run-sre-copilot   启 sre_copilot A2A server(端口 5020)"
	@echo "  make run-faq              启 faq A2A server(端口 5030)"
	@echo ""
	@echo "  make clean                清理 __pycache__ 和 pytest 缓存"
	@echo ""
	@echo "  Milvus 启停见 scripts/start_milvus.py / stop_milvus.py"

# ==================== 依赖管理 ====================
sync:  ## 装运行时 + 开发依赖
	uv sync --group dev

# ==================== 测试 ====================
test:  ## 跑全部测试
	uv run pytest tests/

test-unit:  ## 只跑纯单元测试(不依赖外部服务)
	uv run pytest tests/platform tests/memory_pool tests/auth tests/observability -m "not integration"

test-platform:  ## Phase 1.7 + Phase 2 orchestrator + memory_pool 单元测试
	uv run pytest tests/platform tests/memory_pool -m "not integration"

test-auth:  ## Phase 3 RBAC + JWT 单元测试
	AUTH_JWT_SECRET=dev-secret uv run pytest tests/auth -m "not integration"

test-observability:  ## Phase 4 Observability 单元测试
	uv run pytest tests/observability -m "not integration"

test-plugins:  ## 3 个真插件单元测试
	cd plugins/hr_assistant && uv run pytest -m "not integration"
	cd ../sre_copilot && uv run pytest -m "not integration"
	cd ../faq && uv run pytest -m "not integration"

test-phase3:  ## Phase 1+2+3 全部单元测试
	AUTH_JWT_SECRET=dev-secret uv run pytest tests/platform tests/memory_pool tests/auth -m "not integration"

test-phase4:  ## Phase 1+2+3+4 全部单元测试
	AUTH_JWT_SECRET=dev-secret uv run pytest tests/platform tests/memory_pool tests/auth tests/observability -m "not integration"

test-phase5:  ## Phase 1+2+3+4+5 全部单元测试
	AUTH_JWT_SECRET=dev-secret uv run pytest tests/platform tests/memory_pool tests/auth tests/observability -m "not integration"
	cd plugins/hr_assistant && uv run pytest -m "not integration"
	cd ../sre_copilot && uv run pytest -m "not integration"
	cd ../faq && uv run pytest -m "not integration"

# ==================== 迁移 ====================
migrate-phase2:  ## Phase 2 MySQL DDL 迁移(user_id + task_context + cross_agent_context)
	uv run python scripts/migrate_add_user_id.py

migrate-phase3:  ## Phase 3 MySQL DDL 迁移(auth_* 4 张表)
	uv run python scripts/migrate_add_auth.py

migrate-phase4:  ## Phase 4 MySQL DDL 迁移(call_records 表)
	uv run python scripts/migrate_add_observability.py

bootstrap-superadmin:  ## 引导第一个 super_admin
	AUTH_JWT_SECRET=dev-secret uv run python scripts/bootstrap_super_admin.py admin

# ==================== 服务启动 ====================
install-plugins:  ## 装 3 个真插件(本地 editable)
	uv pip install -e plugins/hr_assistant
	uv pip install -e plugins/sre_copilot
	uv pip install -e plugins/faq

run-api:  ## 启动 FastAPI 后端
	uv run python -m CorpAI.api.app

run-hr-assistant:  ## 启 hr_assistant A2A server(端口 5010)
	cd plugins/hr_assistant && uv run python -m hr_assistant.entry

run-sre-copilot:  ## 启 sre_copilot A2A server(端口 5020)
	cd plugins/sre_copilot && uv run python -m sre_copilot.entry

run-faq:  ## 启 faq A2A server(端口 5030)
	cd plugins/faq && uv run python -m faq.entry

# ==================== 清理 ====================
clean:  ## 清理 Python 缓存
	find . -type d -name "__pycache__" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	@echo "清理完成"