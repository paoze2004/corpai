# corpai-plugin-faq

企业 FAQ 助手 — 跨企业 KB 文档语义检索(VPN / 远程办公 / 差旅 / 工位 / WiFi / 培训等)。

## 安装 + 启动

```bash
cd D:\develop\PycharmProjects\CorpAI
uv pip install -e plugins/faq
.venv\Scripts\python.exe -m faq.entry  # 启 A2A server :5030
```

## Manifest

- `faq`(llm_agent, :5030) — 处理 intent `faq`
- `faq_query_mcp`(mcp_tool, :8030) — `query_faq`

## 内置 KB(12 条)

启动时由 `seed.py` 自动注入(`FAQ001 ~ FAQ012`):

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

## 检索方式

**Milvus**(IVF_FLAT + COSINE, dim=1536)语义检索 — MiniMax `embo-01` embedding。

- `query_faq(text)` → 走 Milvus 语义搜索;**Milvus 不可达硬失败 raise**(CLAUDE.md 不 silent-fail)
- `query_faq_inmemory_fallback(text)` → 测试 / 运维兜底,关键词打分,不依赖 Milvus
- 启动时 `seed.py` 同步灌入 12 条 FAQ 到 Milvus;upsert 失败仅 warn + counter,plugin 继续启动
- 指标:`rag_query_total{backend}` + `rag_query_errors_total{kind}`(Prometheus)

详见 `docs/PLUGINS.md §12` Milvus 部署。