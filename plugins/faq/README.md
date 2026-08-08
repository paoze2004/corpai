# corpai-plugin-faq

Phase 5:FAQ RAG — 跨企业文档语义检索。

## 安装 + 启动

```bash
cd D:\develop\PycharmProjects\CorpAI
uv pip install -e plugins/faq
.venv\Scripts\python.exe -m faq.entry  # 启 A2A server :5030
```

## Phase 5 vs Phase 6

- **Phase 5(当前)**: 内存 doc store + keyword overlap scoring。测试用。
- **Phase 6(未来)**: 集成 pymilvus + 真实 Embedding API + 语义检索。

## 使用示例

```python
from faq.server import add_doc_for_testing
add_doc_for_testing("员工每年 10 天年假,工作满 5 年增至 15 天。")
add_doc_for_testing("缺勤须提前 1 天在 OA 提交申请。")
# 然后通过 A2A server 查
```
