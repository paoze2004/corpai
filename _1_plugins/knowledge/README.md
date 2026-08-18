# corpai-plugin-knowledge v1.1

企业知识中心 — Milvus 语义检索 RAG(原 faq plugin,已改名)。

> 重命名:`faq` → `knowledge`(v1.1)。意图名 `faq` 保留(RBAC scope `knowledge:read`,intent 字符串向后兼容)。

---

## 安装 + 启动

```bash
cd D:\develop\PycharmProjects\CorpAI
uv pip install -e _1_plugins/knowledge

# A2A server(LLM agent 入口)
.venv\Scripts\python.exe -m knowledge.entry  # :5030

# MCP server(工具入口,Anthropic 官方 spec)
.venv\Scripts\python.exe -m knowledge.mcp_main  # :8030
# 或 make run-mcp-knowledge
```

---

## Manifest 清单(2 个)

| Manifest name | Type | Endpoint | MCP tool | RBAC scope | 用途 |
|---|---|---|---|---|---|
| `knowledge` | llm_agent | :5030 | — | knowledge:read | LLM agent 入口 |
| `knowledge_query_mcp` | mcp_tool | :8030 | `query_knowledge` | knowledge:read | 语义检索 |

---

## MCP tools(2 个,跑在 :8030)

| Tool | 必填参数 | 可选参数 | 说明 |
|---|---|---|---|
| `query_knowledge` | query_text | collection, limit | Milvus 语义检索(不可达时返错误 envelope) |
| `add_document` | text | collection, doc_id | 注入 1 条 doc 到 in-memory store(Milvus upsert 走 seed.py) |

---

## 内置 KB(12 条)

启动时由 `seed.py` 自动注入(`FAQ001 ~ FAQ012`,collection 默认 `knowledge_docs`):

| ID | 主题 |
|----|------|
| FAQ001 | VPN 申请流程 |
| FAQ002 | 远程办公设备申请 |
| FAQ003 | 安全事件上报 |
| FAQ004 | 差旅预订流程 |
| FAQ005 | 加班调休规则 |
| FAQ006 | 员工证办理 |
| FAQ007 | 工位调整 |
| FAQ008 | 公司 WiFi 接入 |
| FAQ009 | 团队建设申请 |
| FAQ010 | 代码保密规范 |
| FAQ011 | IT 采购流程 |
| FAQ012 | 培训申请 |

---

## 检索方式

**Milvus**(IVF_FLAT + COSINE, dim=1536)语义检索 — MiniMax `embo-01` embedding。

- `query_knowledge(text)` → 走 Milvus 语义搜索;**Milvus 不可达硬失败 raise**(CLAUDE.md 不 silent-fail)
- 启动时 `seed.py` 同步灌入 12 条 FAQ 到 Milvus;upsert 失败仅 warn + counter,plugin 继续启动
- 指标:`rag_query_total{backend}` + `rag_query_errors_total{kind}`(Prometheus)
- Milvus 部署:`corpai-milvus.yml`(docker compose)

详见 `docs/PLUGINS.md §12` Milvus 部署。

---

## 被谁调(跨 plugin)

- `hr_assistant.cross_query_knowledge(:8001)` — HR KB 未命中时调本 plugin 兜底
- `sre_copilot.cross_query_knowledge(:8028)` — SRE SOP 兜底

---

## 测试

```bash
cd _1_plugins/knowledge
uv run pytest -m "not integration"
```

`test_plugin.py` 覆盖 retriever / embedding / register / manifest。

---

## 相关文件

- `_1_plugins/knowledge/src/knowledge/retriever.py` — `query_knowledge` 实现
- `_1_plugins/knowledge/src/knowledge/embedding.py` — MiniMax `embo-01` embedding
- `_1_plugins/knowledge/src/knowledge/seed.py` — 启动时灌 KB
- `_1_plugins/knowledge/src/knowledge/mcp_servers.py` — FastMCP server 定义
- `_1_plugins/knowledge/src/knowledge/mcp_main.py` — 启动入口
- `_1_plugins/knowledge/src/knowledge/plugin.py` — manifest 注册