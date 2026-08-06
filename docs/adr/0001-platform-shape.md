# ADR-001: 从 CorpAI 到企业 AI Copilot 平台

## 状态
**Accepted** — 2026-08-06

## 背景

CorpAI 当前是一个面向旅游场景的中文聊天助手,代码结构(`core/chat.py:185-1063` 880 行 god class)+ 业务范围(天气/票务/旅游团)+ 工程标准(无认证/无 CORS/零测试)都不再匹配企业用户需求。

### 当前痛点
1. **业务写死**:新增业务 = 编辑 4 个文件(agent/tool/prompts/config)+ 启 2 个新进程
2. **零测试覆盖**:ChatService 完全没单测,任何重构都心里没底
3. **零认证**:FastAPI 裸跑,任何能访问 8080 的人都能调聊天/记忆
4. **配置硬编码**:DB/Milvus/intent mapping 写在 `config.py:45-99`,部署/迁移痛苦
5. **记忆无 per-user**:全局单例 `ConversationMemory`,alice 能看 bob 的聊天记录

### 用户决策
- **业务方向**:旅游助手 → 企业 AI Copilot 平台(2026-08-06 确认)
- **形态**:平台型(1 Orchestrator + N 业务 Agent + N×M MCP 工具),非单一业务深耕
- **工程标准**:必须达到"企业工程项目"级,含 RBAC + 可观测性 + CI/CD + 管理后台

## 决策

将 CorpAI 改造为**企业 AI Copilot 平台**:

### 形态
- **Orchestrator**:核心调度器,意图识别 + Planning + ReAct + 流式
- **业务 Agent**:N 个可注册插件,每个服务一个业务域(客服/HR/研发...)
- **MCP 工具**:N×M 个可注册工具,对接真实系统(CRM/工单/K8s/知识库)
- **MemoryPool**:6 层记忆(3 现有 + 3 新增),per-user 化
- **RBAC**:4 角色(`super_admin`/`admin`/`agent_author`/`employee`)+ 多租户
- **Observability**:结构化日志 + trace_id + Prometheus 指标 + call_records 表
- **2 个 UI**:聊天窗口沿用 + 新增管理后台

### 关键约束
- **零行为变化先行**:每个 Phase 必须保证现有 demo 不挂
- **配置 .env 化**:DB/Milvus/intent-mapping 全进环境变量
- **保留技术栈**:LangChain + FastMCP + Milvus + A2A 不换
- **复用 > 重写**:现有 3 个 agent 改造为 3 个示范插件

## 后果

### 正面
1. **可扩展性**:新增业务 = 写一个 plugin 包 + 注册,**不动平台核心**
2. **可上生产**:RBAC/可观测性/CI/管理后台齐备,符合企业工程标准
3. **可演示**:既有聊天 demo(沿用),又有管理后台(新),展示完整产品形态
4. **代码可维护**:Orchestrator 880 行 god class 拆为 7 个 ≤300 行模块

### 负面
1. **重构工作量大**:12 周(单人),约 6300 LOC 新增/重写
2. **测试补齐工作**:ChatService 零覆盖 → 70%+,需要先写特性测试
3. **API 演进**:旧 `POST /api/chat` 保持,但 `/api/chat/stream` payload 微调(stream/non-stream 不一致已修复)
4. **管理后台开发**:新增 5 个页面 vanilla JS 页面

### 中性
1. **插件作者门槛**:需要写一个 `register(registry)` 函数 + pyproject.toml entry_points
2. **学习成本**:平台核心模块拆分后,新开发者需要熟悉 7 个模块的边界

## 权衡

| 备选方案 | 取舍 |
|---------|------|
| **深耕单一业务**(如:智能客服) | � 拒绝 — 单一业务天花板低,且无法体现"平台"价值 |
| **用 LangGraph 重写** | ❌ 拒绝 — 当前 ReAct 逻辑能保留,引入新框架学习成本不值 |
| **微服务化**(K8s + Service Mesh) | ❌ 拒绝 — 单体 FastAPI + 进程内 plugin 足够覆盖;分布式引入额外复杂度 |
| **不引入 CI/CD** | ❌ 拒绝 — 无 CI 的演示时崩溃是已知风险 |
| **管理后台用 React + Vite** | ❌ 拒绝 — 当前团队能 ship vanilla SPA;React 增加构建步骤与依赖 |

## 验证

- **Phase 1 验收**:Orchestrator 7 模块拆分,每个 ≤300 行;特性测试覆盖每个模块
- **Phase 3 验收**:4 个示范插件注册到 Orchestrator,行为与原 agent 一致
- **Phase 5 验收**:聊天窗口 + 管理后台都跑通 e2e
- **Phase 6 验收**:所有 .env 注入,Pydantic 边界验证生效
