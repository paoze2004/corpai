"""
Composition Root — Phase 1.7 把 ChatService.__init__ 接线逻辑搬到此处。

平台唯一允许导入 A2A / LangChain / mysql.connector 的位置:
- platform/orchestrator/* 保持纯(不依赖具体基础设施)
- platform/wiring.py 组装 A2A / ChatOpenAI / ConversationMemory / DB / 闭包为 OrchestratorService

行为契约:与原 ChatService() 构造等价 — 同样的 A2A URL、ChatOpenAI 参数、
memory limit、DB 加载顺序;公开方法与 ChatService 一一对应。
"""
import asyncio
import json
import uuid
from typing import Any, Awaitable, Callable

import mysql.connector
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from python_a2a import AgentNetwork, Message, MessageRole, Task, TextContent
from python_a2a.client import A2AClient

from CorpAI.config import Config
from CorpAI.core.memory import ConversationMemory
# Phase 5:CorpAIPrompts.summarize_*_prompt 迁到各 plugin.prompts 模块;
# wiring 用 _resolve_summary_prompt 通过 plugin_manager 拿模板。
from CorpAI.logging import logger
from CorpAI.platform.observability.metrics import (
    A2A_CALL_TOTAL,
    LLM_CALL_DURATION,
    LLM_CALL_TOTAL,
)
from CorpAI.platform.observability.trace import start_span, to_thread_propagating
from CorpAI.platform.plugin_manager import PluginRegistry
from CorpAI.platform.orchestrator import OrchestratorService
from CorpAI.platform.orchestrator.intent import IntentRecognizer
from CorpAI.platform.orchestrator.planner import TaskPlanner
from CorpAI.platform.orchestrator.react_loop import ReActRunner
from CorpAI.utils.format import strip_think
import contextvars


# ════════════════════════════════════════════════════════════════
# Phase 5:thread-local user scopes + summary prompt dispatch
# ════════════════════════════════════════════════════════════════
_user_scopes_var: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "wiring_user_scopes", default=None,
)


def set_user_scopes(scopes: list[str]) -> None:
    """api/app.py 解析 JWT 后调用,把 scopes 喂给 wiring。"""
    _user_scopes_var.set(list(scopes))


def _get_current_user_scopes() -> list[str]:
    """wiring 内部 helper — 缺省返 ['*'](向后兼容 Phase 1.7/2/3/4 无 token)。"""
    return _user_scopes_var.get() or ["*"]


def _resolve_summary_prompt(plugin_manager: PluginRegistry | None, manifest, name: str):
    """从 plugin.prompts 模块反射取 name 函数的返回值(ChatPromptTemplate)。

    wiring 不直接 import plugin 私有符号 — 走 plugin_manager._plugin_modules 反查。
    找不到 → 返 None → caller 走 fallback(原样返回 agent_result)。
    """
    if plugin_manager is None or manifest is None:
        return None
    mod = plugin_manager._plugin_modules.get(manifest.name)
    if mod is None:
        return None
    prompts_pkg = getattr(mod, "prompts", None)
    if prompts_pkg is None:
        return None
    fn = getattr(prompts_pkg, name, None)
    if fn is None or not callable(fn):
        return None
    return fn()  # ChatPromptTemplate 实例


def _make_a2a_network(plugin_manager: PluginRegistry | None = None) -> tuple[dict[str, str], AgentNetwork]:
    """注册 A2A 子代理。

    Phase 3 扩展:plugin_manager 不为空时,从 llm_agent 类型插件取 endpoint;
    否则用 hardcoded fallback 3 个 A2A(向后兼容 Phase 1.7/2 行为)。
    """
    if plugin_manager is not None and plugin_manager.list_agents():
        agent_urls = {
            m.name: m.endpoint for m in plugin_manager.list_agents() if m.endpoint
        }
        if not agent_urls:
            agent_urls = _LEGACY_AGENT_URLS
    else:
        agent_urls = _LEGACY_AGENT_URLS
    network = AgentNetwork(name="旅行助手网络")
    for name, url in agent_urls.items():
        network.add(name, A2AClient(url, timeout=120))
    return agent_urls, network


# Phase 3 fallback hardcoded dict(便于 _make_a2a_network 复用)
_LEGACY_AGENT_URLS: dict[str, str] = {
    "WeatherQueryAssistant": "http://localhost:5005",
    "TicketAssistant": "http://localhost:5006",
    "TripAssistant": "http://localhost:5007",
}


def _make_llm(conf: Config) -> ChatOpenAI:
    """原 ChatService.llm(chat.py:225-230)。"""
    return ChatOpenAI(
        model=conf.model_name,
        api_key=conf.api_key,
        base_url=conf.base_url,
        temperature=conf.temperature,
    )


def _make_memory() -> ConversationMemory:
    """Phase 2:已被 MemoryPool 取代,保留对老 wiring 调用栈的兼容占位。"""
    return ConversationMemory(short_term_limit=20)


def _make_memory_pool(user_id: str = "legacy", session_id: str = "legacy"):
    """Phase 2:DatabasePool 单例 + MemoryPool(替代 ConversationMemory)。

    user_id / session_id 占位 'legacy'(Phase 3 RBAC 才能注入真实值)。
    DB 连不上时降级 — MemoryPool 仅短内存模式,所有 save 抛 RuntimeError。
    """
    from CorpAI.platform.db import DatabasePool
    from CorpAI.platform.orchestrator.memory_gateway import MemoryPool

    try:
        conn = DatabasePool.get().get_conn()
    except Exception as e:
        logger.warning(f"DB 连接失败,MemoryPool 退化到无 conn 模式: {e}")
        conn = None
    pool = MemoryPool(user_id=user_id, session_id=session_id, db_conn=conn)
    if conn is not None:
        try:
            pool._conv.load_profile_from_db()
            pool._conv.load_entities_from_db()
            pool._conv.load_messages_from_db()
            logger.info(
                f"记忆加载完成: 偏好={len(pool.user_profile)}项, "
                f"历史={len(pool.entity_history)}条, "
                f"对话={len(pool.short_term_messages)}条"
            )
        except Exception as e:
            logger.warning(f"DB 数据加载失败: {e}")
    return pool


def _load_memory_from_db(memory: ConversationMemory, conf: Config) -> None:
    """向后兼容 stub — Phase 2 已迁到 _make_memory_pool。调用方应改用 _make_memory_pool。"""
    logger.warning("_load_memory_from_db 已废弃,改用 _make_memory_pool")
    try:
        db_conn = mysql.connector.connect(
            host=conf.host, user=conf.user,
            password=conf.password, database=conf.database,
        )
        memory.set_db_connection(db_conn)
        memory.load_profile_from_db()
        memory.load_entities_from_db()
        memory.load_messages_from_db()
    except Exception as e:
        logger.warning(f"_load_memory_from_db legacy path failed: {e}")
        memory.set_db_connection(None)


def _make_agent_card_provider(
    agent_network: AgentNetwork, agent_urls: dict[str, str],
) -> Callable[[], list[dict]]:
    """[{name, skills, description, url, status}] closure(原 chat.py:803-832)。"""

    def provide_cards() -> list[dict]:
        cards: list[dict] = []
        for agent_name in agent_network.agents.keys():
            card = agent_network.get_agent_card(agent_name)
            cards.append({
                "name": agent_name,
                "skills": [s.name + ": " + s.description for s in card.skills],
                "description": card.description,
                "url": agent_urls.get(agent_name, "未知地址"),
                "status": "在线",
            })
        return cards

    return provide_cards


def _make_attraction_executor(
    agent_network: AgentNetwork, llm: ChatOpenAI, memory: ConversationMemory,
) -> Callable[[str], Awaitable[str]]:
    """city_extract → A2A 查天气 → attraction_prompt | llm.astream(原 chat.py:294-302 + 375-418)。"""
    city_extract_prompt = ChatPromptTemplate.from_template(
"""从以下用户查询和对话历史中提取目的地城市(用于天气查询)。规则:
- 只输出城市名称,不要输出其他内容。
- 如果查询中没有明确城市,尝试从对话历史中推断。
- 如果无法确定城市,输出"未知"。

对话历史:{conversation_history}
用户查询:{query}
""")

    async def fetch_weather(query_str: str) -> str:
        try:
            chain = city_extract_prompt | llm
            city = chain.invoke({
                "conversation_history": memory.get_short_term_text(),
                "query": query_str,
            }).content.strip()
            city = strip_think(city)
            if city == "未知" or not city:
                logger.info(f"无法从查询中提取目的地城市: {query_str}")
                return ""
            logger.info(f"从景点查询中提取到城市: {city}")
            agent = agent_network.get_agent("WeatherQueryAssistant")
            if agent is None:
                return ""
            weather_query = f"{city}明天天气"
            msg = Message(content=TextContent(text=weather_query), role=MessageRole.USER)
            task = Task(id="task-" + str(uuid.uuid4()), message=msg.to_dict())
            # Phase 4:包 span + to_thread_propagating 传播 ContextVar
            with start_span(
                "a2a_call.WeatherQueryAssistant",
                {"agent": "WeatherQueryAssistant", "purpose": "attraction_weather"},
            ) as span:
                try:
                    raw = await agent.send_task_async(task)  # Phase 6:直接 await(在 async 上下文,无需 thread+asyncio.run)
                    span.set_attr("a2a_status", str(raw.status.state))
                    A2A_CALL_TOTAL.labels(
                        agent="WeatherQueryAssistant", status=str(raw.status.state),
                    ).inc()
                    if raw.status.state == "completed" and raw.artifacts:
                        return raw.artifacts[0]["parts"][0]["text"]
                    return ""
                except Exception as exc:
                    span.end_err(str(exc))
                    A2A_CALL_TOTAL.labels(
                        agent="WeatherQueryAssistant", status="error",
                    ).inc()
                    raise
        except Exception as e:
            logger.warning(f"查询景点天气失败: {e}")
            return ""

    async def attraction_executor(query_str: str) -> str:
        weather_info = await fetch_weather(query_str)
        chain = CorpAIPrompts.attraction_prompt() | llm
        chunks: list[str] = []
        async for chunk in chain.astream({"query": query_str, "weather_info": weather_info}):
            text = strip_think(chunk.content) if hasattr(chunk, "content") else str(chunk)
            chunks.append(text)
        return "".join(chunks)

    return attraction_executor


def _make_simple_step_executor(
    agent_network: AgentNetwork, llm: ChatOpenAI, memory: ConversationMemory,
    conf: Config, attraction_executor: Callable[[str], Awaitable[str]],
    plugin_manager: PluginRegistry | None = None,
) -> Callable[[str, str], Awaitable[str]]:
    """Phase 5:plugin_manager 不为 None 时优先用 agents_for_intent 拿 manifest.name + summary_prompt;
    否则用 conf.intent 老 dict(向后兼容 Phase 1.7/2/3/4 无 plugin 场景)。"""

    async def _call_a2a_and_summarize(agent_name: str, query_str: str, intent: str) -> str:
        agent = agent_network.get_agent(agent_name)
        if agent is None:
            logger.warning(f"未找到代理:{agent_name}")
            return f"抱歉,{agent_name} 暂时不可用,请稍后重试。"
        agent_input = json.dumps({
            "history": memory.get_short_term_text(),
            "query": query_str,
        }, ensure_ascii=False)
        msg = Message(content=TextContent(text=agent_input), role=MessageRole.USER)
        task = Task(id="task-" + str(uuid.uuid4()), message=msg.to_dict())

        # Phase 5:RBAC scope 校验 — manifest 取 permissions[0]
        _manifest = (
            plugin_manager.agents_for_intent(intent) if plugin_manager else None
        ) if intent is not None else None
        if _manifest is None and plugin_manager is not None:
            _manifest = plugin_manager.get(agent_name)
        if plugin_manager is not None and _manifest is not None and _manifest.permissions:
            from CorpAI.platform.auth.scopes import has_scope
            needed_scope = _manifest.permissions[0]
            if not has_scope(needed_scope, _get_current_user_scopes()):
                logger.warning(
                    f"RBAC deny: scopes={_get_current_user_scopes()} 缺 {needed_scope} "
                    f"for plugin={_manifest.name}",
                )
                raise PermissionError(
                    f"plugin {_manifest.name} 需要 scope {needed_scope}",
                )

        # Phase 4:A2A 调用包 span + to_thread_propagating(传播 ContextVar)
        a2a_status = "error"
        with start_span(
            f"a2a_call.{agent_name}",
            {"agent": agent_name, "query_len": len(query_str)},
        ) as a2a_span:
            try:
                logger.info(f"调用 {agent_name}...")
                raw = await agent.send_task_async(task)  # Phase 6:直接 await(在 async 上下文)
                a2a_status = str(raw.status.state)
                logger.info(f"{agent_name} 收到响应: {raw.status.state}")
                a2a_span.set_attr("a2a_status", a2a_status)
                if raw.status.state == "completed" and raw.artifacts:
                    agent_result = raw.artifacts[0]["parts"][0]["text"]
                elif raw.status.message:
                    agent_result = raw.status.message.get("content", {}).get(
                        "text", str(raw.status.message)
                    )
                else:
                    agent_result = f"查询失败:{raw.status.message or '未知错误'}"
            except Exception as e:
                logger.error(f"{agent_name} 调用异常: {str(e)}")
                A2A_CALL_TOTAL.labels(agent=agent_name, status=a2a_status).inc()
                return f"{agent_name} 服务暂时不可用:{str(e)}"
        # span 退出 → 自动 end_ok + write_call_record
        A2A_CALL_TOTAL.labels(agent=agent_name, status=a2a_status).inc()

        # Phase 5:从 manifest 取 summary_prompt 名字,反射拿模板;fallback 直接返原结果
        _summary_name = _manifest.summary_prompt if _manifest else None
        if _summary_name is None:
            return agent_result  # 未映射代理 → 原 chat.py:664-666
        _prompt = _resolve_summary_prompt(plugin_manager, _manifest, _summary_name)
        if _prompt is None:
            return agent_result
        chain = _prompt | llm
        # Phase 4:summary LLM 也包 span + timer metric
        with start_span(
            "llm_summarize",
            {"agent": agent_name, "model": conf.model_name, "intent": "summary"},
        ):
            LLM_CALL_TOTAL.labels(model=conf.model_name, intent="summary").inc()
            with LLM_CALL_DURATION.labels(model=conf.model_name).time():
                summarized = chain.invoke(
                    {"query": query_str, "raw_response": agent_result},
                ).content.strip()
        return strip_think(summarized)

    async def simple_step_executor(intent: str, query_str: str) -> str:
        # attraction 委托(ReAct 路径也走它,统一 astream 行为)
        if intent == "attraction":
            return await attraction_executor(query_str)
        # Phase 5:plugin_manager 优先拿 manifest.name,fallback 走 conf.intent 老 dict
        agent_name: str | None = None
        if plugin_manager is not None:
            _m = plugin_manager.agents_for_intent(intent)
            if _m is not None:
                agent_name = _m.name
        if agent_name is None:
            agent_name = conf.intent.get(intent)  # 向后兼容 Phase 1.7/2/3/4
        if not agent_name:
            return "暂不支持此意图。"
        # 票务类意图:提取实体 + 更新 task_context(原 chat.py:613-615)
        if intent in ["flight", "train", "concert", "car_rental", "tour_group", "insurance"]:
            memory.extract_entities(intent, query_str)
            memory.update_task_context({"type": intent, "query": query_str})
        return await _call_a2a_and_summarize(agent_name, query_str, intent)

    return simple_step_executor


def build_default_service(
    user_id: str = "legacy",
    session_id: str = "legacy",
    plugin_manager: PluginRegistry | None = None,
) -> OrchestratorService:
    """Phase 3:装配 OrchestratorService。plugin_manager 可选注入,None 走 fallback。"""
    conf = Config()
    agent_urls, agent_network = _make_a2a_network(plugin_manager)
    llm = _make_llm(conf)
    memory = _make_memory_pool(user_id=user_id, session_id=session_id)

    # planner/ReAct 读"当前轮 user"的 hook —— OrchestratorService.chat() 先写
    # user 到 memory,short_term_messages[-1] 就是当前输入
    messages_provider: Callable[[], list] = lambda: memory.short_term_messages

    attraction_executor = _make_attraction_executor(agent_network, llm, memory)
    simple_step_executor = _make_simple_step_executor(
        agent_network, llm, memory, conf, attraction_executor, plugin_manager,
    )

    return OrchestratorService(
        intent=IntentRecognizer(llm=llm, memory=memory),
        planner=TaskPlanner(
            llm=llm, memory=memory, messages_provider=messages_provider,
        ),
        react_runner=ReActRunner(
            llm=llm,
            step_executor=simple_step_executor,
            messages_provider=messages_provider,
        ),
        simple_step_executor=simple_step_executor,
        attraction_executor=attraction_executor,
        memory=memory,
        agent_card_provider=_make_agent_card_provider(agent_network, agent_urls),
    )


__all__ = ["build_default_service"]
