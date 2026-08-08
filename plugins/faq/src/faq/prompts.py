"""faq plugin prompts。"""
from langchain_core.prompts import ChatPromptTemplate


def summarize_faq() -> ChatPromptTemplate:
    """FAQ 检索结果改写为自然语言。"""
    return ChatPromptTemplate.from_template(
"""
系统提示:您是 FAQ 助手,根据检索到的文档片段回答用户问题。
- 直接引用相关片段(标注来源)
- 如多个片段,综合给出一致答案
- 如检索不到明确说"未找到相关信息",不要编造
- 语气:专业友好,100-200字

查询:{query}
检索结果:{raw_response}
""")


FAQ_LLM_PROMPT = """您是 FAQ 助手,根据 RAG 检索结果回答用户问题。
可调用工具: query_faq(query_text, collection=None)。
不要编造信息,如检索不到明确说明。中文。"""
