# CorpAI Plugin 开发指南

Phase 5 落地后,所有业务都通过 plugin 实现。本文档解释如何编写/发布/调试自定义 plugin。

## 1. 概述

- 每个 plugin 是独立 Python 包,根目录在 `plugins/<your-plugin>/`
- 通过 **entry_points** 自动加载(无需手动注册)
- 必须声明至少 1 个 **RBAC scope**(`permissions=[]` 在 `register()` 时抛 ValueError)
- 平台 `platform/plugin_manager.py` 用 `importlib.metadata.entry_points(group="platform.plugins")` 扫描
- 加载失败 plugin 自动 warning 不挂,其他 plugin 照常工作(软启动)

## 2. 最小可行 plugin(5 步)

### Step 1: 创建目录
```bash
mkdir -p plugins/my_plugin/src/my_plugin
```

### Step 2: `pyproject.toml`
```toml
[project]
name = "corpai-plugin-my-plugin"
version = "0.1.0"
description = "My new plugin"
requires-python = ">=3.11"
dependencies = []   # 平台已装的 langchain / fastapi / uvicorn 等不需重复声明

[project.entry-points."platform.plugins"]
my_plugin = "my_plugin.plugin:register"
```

### Step 3: `src/my_plugin/__init__.py`
```python
from my_plugin.plugin import register
__all__ = ["register"]
```

### Step 4: `src/my_plugin/plugin.py`
```python
from CorpAI.platform.plugin_manager import PluginManifest, PluginRegistry

MANIFEST = PluginManifest(
    name="my_plugin",
    version="0.1.0",
    description="My new plugin",
    plugin_type="llm_agent",  # 或 "mcp_tool"
    endpoint="http://localhost:5050",
    llm_prompt="You are a helpful assistant.",  # 仅 llm_agent 必填
    summary_prompt="summarize",  # 可选:在 plugin.prompts 找同名函数
    required_intents=["my_intent"],
    permissions=["my_plugin:read"],
    tags=["my-domain"],
)

def register(registry: PluginRegistry) -> None:
    registry.register(MANIFEST)
```

### Step 5: 安装 + 验证
```bash
cd D:\develop\PycharmProjects\CorpAI
uv pip install -e plugins/my_plugin
.venv\Scripts\python.exe -c "
from CorpAI.platform.plugin_manager import discover_all
r = discover_all()
print([m.name for m in r.list_all()])
# 期望:['hr_assistant', 'sre_copilot', 'faq', 'my_plugin']
"
```

## 3. PluginManifest 字段

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| `name` | str | ✓ | 唯一标识,1-64 字符 |
| `version` | str | ✓ | semver,正则 `^\d+\.\d+\.\d+$` |
| `description` | str | ✓ | 1-512 字符 |
| `plugin_type` | `Literal["mcp_tool", "llm_agent"]` | ✓ | 形态 |
| `endpoint` | str \| None | mcp_tool 必填 | `http://host:port` |
| `mcp_tool_name` | str \| None | - | MCP 工具名,UI 展示 |
| `llm_prompt` | str \| None | llm_agent 必填 | 系统 prompt 模板 |
| `summary_prompt` | str \| None | - | 在 plugin.prompts 找同名函数 |
| `required_intents` | list[str] | - | 路由匹配 |
| `permissions` | list[str] | ✓(非空) | RBAC scopes |
| `tags` | list[str] | - | 领域标签 |
| `structured_tools` | list[dict] | - | LangChain 工具定义(Phase 6 规约化) |

## 4. register() 模式

### 单 manifest
```python
def register(registry: PluginRegistry) -> None:
    registry.register(MANIFEST)
```

### 多 manifest(同一 plugin 同时提供 A2A + MCP)
```python
def register(registry: PluginRegistry) -> None:
    for m in (AGENT_MANIFEST, MCP_TOOL_1, MCP_TOOL_2):
        registry.register(m)
```

## 5. RBAC scope 强制机制(Phase 5)

- `permissions=[]` → `register()` 抛 `ValueError`
- `/api/chat` 接受可选 `Authorization: Bearer <token>`(Phase 5 加)
- 解析 token → 取 `claims["scopes"]` → `wiring.set_user_scopes(scopes)`
- `wiring._call_a2a_and_summarize` 调 `has_scope(manifest.permissions[0], _get_current_user_scopes())`
- 失败 → `raise PermissionError` → `OrchestratorService.chat` 顶层 try/except 捕获 → 返 error_message

**RBAC 设计模式**:
| 角色 | 期望 scope | 用例 |
|------|------------|------|
| super_admin | `["*"]` | 可调所有 plugin |
| admin | `["hr:read", "sre:read", "faq:read"]` | 跨 plugin 读 |
| employee | `["chat:write"]` | 普通聊天(无 plugin 直接权限) |
| agent_author | `["chat:write", "plugin:write"]` | 注册/管理 plugin |

**sre_copilot 双 scope 示范**:`permissions: ["sre:read", "sre:write"]` — 同一 plugin 多个 scope。`restart_pod` 单独要 `sre:write`(由 plugin 内部 `has_scope` 校验)。

## 6. summary_prompt dispatch 机制

`manifest.summary_prompt = "summarize_x"` 时,wiring 通过反射从 `plugin.prompts` 模块查同名函数并调,得到 `ChatPromptTemplate`。

### 范例:`hr_assistant` plugin
```python
# plugins/hr_assistant/src/hr_assistant/prompts.py
from langchain_core.prompts import ChatPromptTemplate

def summarize_benefits() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_template("...")
```

`AGENT_MANIFEST.summary_prompt = "summarize_benefits"` 即可。`wiring._resolve_summary_prompt`:
```python
mod = plugin_manager._plugin_modules[manifest.name]  # "hr_assistant"
prompts_pkg = getattr(mod, "prompts", None)
fn = getattr(prompts_pkg, "summarize_benefits", None)
return fn() if fn else None
```

**找不到 → fallback 返 `agent_result`**(Phase 4 行为)。

## 7. 测试 plugin

每个 plugin 自带 `tests/` 目录,模式:
```python
# plugins/my_plugin/tests/test_plugin.py
import sys
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT))  # 让 `import CorpAI` 找到

import unittest
from CorpAI.platform.plugin_manager import PluginRegistry
from my_plugin.plugin import register, MANIFEST

class TestRegister(unittest.TestCase):
    def test_register(self):
        r = PluginRegistry()
        register(r)
        self.assertEqual(r.get("my_plugin").name, "my_plugin")
```

**conftest.py** 必须设项目根:
```python
import sys
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
```

跑:`cd plugins/my_plugin && uv run pytest`

## 8. e2e 流程

1. 启 A2A server:`cd plugins/my_plugin && uv run python -m my_plugin.entry`
2. curl 测试:`curl -X POST http://localhost:5050 -d '{...}'`
3. 启 FastAPI:`make run-api`
4. chat 测试:`curl -X POST http://127.0.0.1:8080/api/chat -H "Authorization: Bearer $TOKEN" -d '{"message":"..."}'`

## 9. FAQ

### 9.1 manifest 字段不识别?
Pydantic v2 `model_config = ConfigDict(extra="forbid")` — 任何拼错的字段会立即 raise。检查 `name` 长度、`version` semver 格式、`permissions` 非空。

### 9.2 entry_points 缓存?
`uv pip install -e` 后需重启 Python 进程(entry_points 元数据在 import 时读)。`uv pip cache purge` 清缓存。

### 9.3 plugin 私有依赖隔离?
- **Phase 5 决策**:0 新 platform dep;plugin 可在 `pyproject.toml:dependencies` 声明自己私有依赖,platform 不受影响。
- 不允许修改平台代码来适配 plugin;反过来平台升级也不能改 plugin。

### 9.4 插件测试 / 脚手架
- 3 个真 plugin(`hr_assistant` / `sre_copilot` / `faq`)各自 `tests/test_plugin.py`,走 `unittest` + `pytest` 风格混用
- entry_points 机制验证见 `docs/adr/0003-plugin-registration.md`;无需单独脚手架(写自己的 plugin 时照 §3-§6 模板即可)

### 9.5 性能 / trace / 监控?
- `manifest.name` 落到 `corpai_app_info` 的 `version=phase4` 元数据(Phase 4)
- 每次 `wiring._call_a2a_and_summarize` 自动写 `call_records` 一行(trace_id / span_id / duration_ms)
- `_call_a2a_and_summarize` 自动 inc `A2A_CALL_TOTAL` Counter
- summary LLM 自动 inc `LLM_CALL_TOTAL` + 计时

### 9.6 Milvus + Embedding 集成示范(faq plugin)

`plugins/faq` 是首个 RAG plugin,集成 Milvus + MiniMax embo-01 embedding。3 文件分层:

| 文件 | 职责 |
|------|------|
| `embedding.py` | MiniMax /v1/embeddings HTTP 客户端,1536 维 + 模块级 cache + batch 接口 |
| `milvus_store.py` | lazy connect + schema bootstrap + upsert/search + 2 Counter |
| `retriever.py` | `query_faq` (Milvus 优先) + `query_faq_inmemory_fallback` (关键词兜底) |

**契约**(JSON envelope 不变,`summarize_faq` prompt 依赖):
```json
{"status": "success|no_data", "data": [{"id","text","score"}], "message": "..."}
```

**失败策略**(用户决策,见 CLAUDE.md "不 silent-fail"):
- `query_faq`:Milvus 不可达 → `raise MilvusUnreachable`,FaqServer 返 `TaskState.FAILED`
- `seed_default_kb`:Milvus upsert 失败 → `logger.warning` + `RAG_QUERY_ERRORS_TOTAL{kind="seed_failed"}` inc,plugin 继续启动

**2 个 Counter**(`prometheus_client.Counter.labels(...).inc()`):
- `rag_query_total{backend="milvus|inmemory"}`
- `rag_query_errors_total{kind="milvus_unreachable|seed_failed|embedding_failed"}`

**测试**(`tests/test_plugin.py`):
- `TestRetriever` — 走 `query_faq_inmemory_fallback`,**不依赖 Milvus / embedding API**,CI 必过
- `TestEmbedding` — 用 `mock_embedding_response` fixture(monkeypatch `_post_embed`),返回 deterministic 1536 维向量
- `TestMilvusStore` — `@pytest.mark.skipif(not os.getenv("FAQ_MILVUS_HOST"))`,只在 Milvus 在跑时启用

**新 plugin 复用模式**:
1. 抄 `embedding.py` 改名(如 `my_plugin_embedding.py`),改 `_post_embed` 端点
2. 抄 `milvus_store.py` 改 Collection 名 / Schema(可加 metadata 字段)
3. 抄 `retriever.py` 改 `query_xxx` 函数名,保留同 JSON envelope
4. seed 时同步调 `upsert()`,失败容忍策略可按业务调整

## 10. 已交付的 3 个真 plugin(v2.1/v3.0 升级版)

| Plugin | A2A 端口 | MCP 端口 | 业务 | RBAC scopes |
|--------|----------|----------|------|------------|
| `hr_assistant` | 5010 | 8010-8026 (17 个 mcp) | **82 条 KB**(福利 18+ 政策 30+ 流程 12+ 招聘 6+ 薪酬 6+ 培训 6+ 关怀 4)+ **8 个操作类**(写 MySQL 真业务:请假/报销/证明/资产/培训/转正/审批/查询)+ **3 个跨插件 bridge**(faq 兜底 / devops 去重 / 查 oncall) | `hr:read, hr:write` |
| `sre_copilot` | 5020 | 8020-8028 (8 个 mcp) | **35 工具**(incident 10+ oncall 8+ k8s 5+ 告警 6+ CI/CD 4+ 日志 4)+ **2 个跨插件 bridge**(hr 检查 / faq SOP 兜底) | `sre:read, sre:write` |
| `faq` | 5030 | 8030 | 企业 KB RAG(**71 条 Milvus faq_docs_v2**:IT/HR/Security/Finance/Procurement/Admin/Engineering 7 大业务域) | `faq:read` |

### 10.1 hr_assistant 操作类工具详解

8 个真写 MySQL 的操作类工具(端口 :8017-8024):

| manifest | mcp_tool | 端口 | 写表 | scope |
|---|---|---|---|---|
| hr_assistant_leave_mcp | submit_leave / cancel_leave | :8017 | hr_leave_requests | hr:write |
| hr_assistant_reim_mcp | submit_reimbursement | :8018 | hr_reimbursements | hr:write |
| hr_assistant_cert_mcp | apply_certificate | :8019 | hr_certificates | hr:write |
| hr_assistant_asset_mcp | request_asset | :8020 | hr_asset_requests | hr:write |
| hr_assistant_train_mcp | register_training | :8021 | hr_training_registrations | hr:write |
| hr_assistant_reg_mcp | apply_regularization | :8022 | hr_regularization | hr:write |
| hr_assistant_approve_mcp | approve_request | :8023 | 6 表通用入口 | hr:write |
| hr_assistant_my_mcp | query_my_requests | :8024 | 读 6 表 | chat:write |

**架构要点**:
- 入口必校验 scope + 从 token 强制拿 user_id(防越权)
- 状态机:`pending → approved / rejected / cancelled`(4 态流转)
- 每次操作写 `hr_audit_log`,含 `trace_id`(`current_trace_id()`)
- DB 错误不吞,`logger.warning` + 抛错 + `HR_ACTION_TOTAL{status=error}` Counter

### 10.2 跨插件联动矩阵

```
                    hr_assistant    sre_copilot    faq
hr_assistant            -               ✓(bridge)     ✓(bridge)
sre_copilot       ✓(bridge)            -           ✓(bridge)
faq                     -             ✓(bridge)          -
```

bridge 工具通过 `requests.post({url}/mcp/tools/{tool_name}, timeout=2s)` 跨插件调用,失败静默降级 + `HR_BRIDGE_ERRORS_TOTAL{target,kind}` Counter。

**典型场景**:
1. **HR KB 未命中兜底**:`cross_query_faq` 调 faq 补全
2. **资产申请去重**:`cross_check_sre` 查 devops 工单去重
3. **请假触发 oncall 备份**:devops `cross_check_hr` 查 hr 申请
4. **SOP 兜底**:devops 用户问故障 → `cross_query_faq` 查 SOP
5. **审批后查 oncall**:`cross_notify_sre` 拿 oncall 联系方式

### 10.3 关键 metrics

| Metric | 类型 | Labels | 用途 |
|--------|------|--------|------|
| `hr_action_total` | Counter | action,status | HR 操作类工具调用 |
| `hr_bridge_errors_total` | Counter | target,kind | HR bridge 失败(target=faq/devops;kind=timeout/unreachable/http5xx) |

### 10.4 测试覆盖

| plugin | 单元测试 | e2e 集成 |
|--------|---------|---------|
| hr_assistant | 21 case | 6 case(`test_e2e.py`,需 MySQL,自动 skip if 不可用) |
| sre_copilot | 20 case | — (Phase 6 接真 SDK 时加) |
| 平台核心 | 152 case | 1 skipped |

```bash
cd plugins/hr_assistant && pytest -v
cd plugins/sre_copilot && pytest -v
cd plugins/hr_assistant && pytest tests/test_e2e.py -v
pytest tests/ -m "not integration"
```

## 11. 引用

- `CorpAI/platform/plugin_manager.py` — 公开 API
- `CorpAI/platform/wiring.py` — `_resolve_summary_prompt` / `set_user_scopes`
- `CorpAI/api/app.py` — `/api/chat` 可选 JWT
- `CorpAI/api/admin_router.py` — `/admin/api/plugins` 展示
- `docs/adr/0003-plugin-registration.md` — entry_points 设计
- `docs/REFACTOR_PLAN.md:200-207` — 4 个示范插件映射表

## 12. Milvus 部署(vector store for faq RAG)

faq plugin 的 KB 检索后端是 Milvus。本地开发用 docker compose 一键起。

### 12.1 启动

```bash
uv run python scripts/start_milvus.py
# 拉镜像(milvus v2.5.15 + etcd v3.5.25 + minio + attu v2.5.7)
# → 启 4 容器(corpai-milvus / corpai-etcd / corpai-minio / corpai-attu)
# → poll :19530 直到通(最多 120s)
# → 打印 URL 表
```

### 12.2 访问

| 服务 | 地址 | 说明 |
|------|------|------|
| Milvus gRPC | `localhost:19530` | PyMilvus 连这个 |
| Milvus HTTP | `http://localhost:9091/healthz` | 健康检查 + Prometheus 指标 |
| MinIO Console | `http://localhost:9001` | `minioadmin` / `minioadmin` |
| Attu UI | `http://localhost:8012` | Web 管理界面(避开 hr insurance_mcp :8010) |

### 12.3 停止

```bash
uv run python scripts/stop_milvus.py             # 保留数据
uv run python scripts/stop_milvus.py --purge     # 删命名卷,数据全清
```

### 12.4 compose 文件

| 文件 | 状态 | 用途 |
|------|------|------|
| `corpai-milvus.yml` | **active** | Milvus + etcd + minio + Attu |
| `corpai-redis.yml` | 占位(DO-NOT-RUN-YET) | 未来会话缓存 |
| `corpai-mysql.yml` | 占位(DO-NOT-RUN-YET) | 未来容器化 MySQL |
| `corpai-platform.yml` | 占位(DO-NOT-RUN-YET) | 未来全栈编排入口 |

### 12.5 镜像版本选择

- 锁 `milvusdb/milvus:v2.5.15` 而非 `v3.0-beta` — 稳定版,与本地 PyMilvus 3.0.0 客户端完全兼容
- `MQ_TYPE=rocksmq` — Milvus 2.5 standalone 唯一支持的内置 MQ(`woodpecker` 不识别,会 panic);**不依赖**外部 Redis
- 命名卷(`corpai_etcd` / `corpai_minio` / `corpai_milvus`)代替 bind-mount,避开 Windows + WSL2 的 UID/GID 坑
- Attu 锁 `8012`(原 8010 与 hr insurance_mcp 冲突)

### 12.6 故障排查

| 现象 | 检查 |
|------|------|
| `start_milvus.py` poll 超时 | `docker logs corpai-milvus --tail=50` |
| 端口已占 | `netstat -ano | findstr "19530 9091 9000 9001 8012"` |
| 数据丢失 | `docker volume inspect corpai_corpai_milvus` 看挂载路径 |
| 旧 `edu_agent_*` 残留 | `docker ps -a --filter name=edu_agent` + `docker rm -f` 清 |

### 12.7 不在本 plan 范围

- faq plugin 真接 Milvus(embedding.py + milvus_store.py)— **已完成(106 条数据 + delete-by-doc_id 去重 + MilvusClient API)**
- 生产 TLS / 鉴权 — Milvus standalone 默认无鉴权,仅开发用
- 集群模式 — 106 FAQ 文档 standalone 足够
