"""
Orchestrator 包 — 调度核心。

包含:
- service.py: OrchestratorService(唯一协调器)— Phase 1.6 ✅
- intent.py: IntentRecognizer(意图识别)— Phase 1.2 ✅
- planner.py: TaskPlanner(规划 + skip heuristic)— Phase 1.3 ✅
- react_loop.py: ReActRunner(ReAct 执行)— Phase 1.4 ✅
- streaming.py: StreamMux(流式 + ThinkBlockFilter)— Phase 1.5 ✅
- tools_gateway.py: ToolsGateway(插件调用网关)— Phase 3 待引入
- memory_gateway.py: MemoryGateway(记忆网关)— Phase 2 待引入

每个模块 ≤300 LOC,严格边界(由 import-linter 强制)。

注:`platform` 与 Python 标准库同名,所有引用必须用 `_0_CorpAI._2_platform.*` 全路径。
"""

from _0_CorpAI._2_platform.orchestrator.service import OrchestratorService

__all__ = ["OrchestratorService"]


