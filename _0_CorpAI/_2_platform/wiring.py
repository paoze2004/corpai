"""
Composition Root — Phase 1.7 把 ChatService.__init__ 接线逻辑搬到此处。

平台唯一允许导入 A2A / LangChain / mysql.connector 的位置:
- platform/orchestrator/* 保持纯(不依赖具体基础设施)
- platform/wiring.py 组装 A2A / ChatOpenAI / ConversationMemory / DB / 闭包为 OrchestratorService

行为契约:与原 ChatService() 构造等价 — 同样的 A2A URL、ChatOpenAI 参数、
memory limit、DB 加载顺序;公开方法与 ChatService 一一对应。
"""
import contextvars
import json
import uuid
from typing import Awaitable, Callable

import mysql.connector
from langchain_openai import ChatOpenAI
from python_a2a import AgentNetwork, Message, MessageRole, Task, TextContent
from python_a2a.client import A2AClient

from _0_CorpAI.config import Config
from _0_CorpAI._1_core.memory import ConversationMemory
# Phase 5:各 plugin 自己的 summarize_*_prompt 在 plugin.prompts 模块里;
# wiring 用 _resolve_summary_prompt 通过 plugin_manager 反射拿模板。
from _0_CorpAI.logging import logger
from _0_CorpAI._2_platform.observability.metrics import (
    A2A_CALL_TOTAL,
    LLM_CALL_DURATION,
    LLM_CALL_TOTAL,
)
from _0_CorpAI._2_platform.observability.trace import start_span
from _0_CorpAI._2_platform.orchestrator import OrchestratorService
from _0_CorpAI._2_platform.orchestrator.intent import IntentRecognizer
from _0_CorpAI._2_platform.orchestrator.planner import TaskPlanner
from _0_CorpAI._2_platform.orchestrator.react_loop import ReActRunner
from _0_CorpAI._2_platform.plugin_manager import PluginRegistry
from _0_CorpAI._3_utils.format import strip_think

# ════════════════════════════════════════════════════════════════
# Phase 5:thread-local user scopes + summary prompt dispatch
# ════════════════════════════════════════════════════════════════
_user_scopes_var: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "wiring_user_scopes", default=None,
)
# Phase 6+ A2A scope 透传:平台 → plugin → plugin(bridge) 全程带原用户 token
_user_token_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "wiring_user_token", default=None,
)


def set_user_scopes(scopes: list[str]) -> None:
    """api/app.py 解析 JWT 后调用,把 scopes 喂给 wiring。"""
    _user_scopes_var.set(list(scopes))


def set_user_token(token: str | None) -> None:
    """api/app.py 解析 JWT 后调用,把 raw token 喂给 wiring。

    用于 A2A 透传:平台 → plugin 时把 user JWT 写进 task.metadata["authorization"],
    plugin server 读出来当 Bearer header 给自己的 action 调用。
    """
    _user_token_var.set(token)


def _get_current_user_token() -> str | None:
    """wiring 内部 helper — 拿当前用户 raw JWT(没设返 None,plugin 用 dev_token fallback)。"""
    return _user_token_var.get()


def _get_current_user_scopes() -> list[str]:
    """wiring 内部 helper — 无 token 时返空列表(fail-closed,拒绝所有权限)。

    安全修复:原实现返回 ["*"](super_admin),导致未认证请求完全绕过 RBAC。
    现改为返回空列表,未认证请求不获得任何权限。
    若需要向后兼容无 token 的开发环境,请在 api/app.py 中显式注入默认 scopes。
    """
    return _user_scopes_var.get() or []


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
    """注册 A2A 子代理 — Phase 7 起完全走 plugin_manager(无 legacy fallback)。

    plugin_manager 不为 None 且至少 1 个 llm_agent 时,从 manifest 取 endpoint;
    否则返空 dict(平台退化为只跑 LLM 直答)。
    """
    agent_urls: dict[str, str] = {}
    if plugin_manager is not None:
        agent_urls = {
            m.name: m.endpoint for m in plugin_manager.list_agents() if m.endpoint
        }
    network = AgentNetwork(name="CorpAI企业助手网络")
    for name, url in agent_urls.items():
        network.add(name, A2AClient(url, timeout=120))
    return agent_urls, network


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
    from _0_CorpAI._2_platform.db import DatabasePool
    from _0_CorpAI._2_platform.orchestrator.memory_gateway import MemoryPool

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


def _make_simple_step_executor(
        agent_network: AgentNetwork, llm: ChatOpenAI, memory: ConversationMemory,
        conf: Config,
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

        # Phase 6:A2A scope 透传 — 把用户 token 写进 task.metadata,
        # plugin server 读出来当 Bearer header 给 action 调用
        # (替代之前硬编码 dev_token 占位,这样 plugin 端 RBAC 检查的是真用户 scope)
        user_token = _get_current_user_token()
        task_metadata: dict = {}
        if user_token:
            task_metadata["authorization"] = f"Bearer {user_token}"
        task = Task(
            id="task-" + str(uuid.uuid4()),
            message=msg.to_dict(),
            metadata=task_metadata,
        )

        # Phase 5:RBAC scope 校验 — manifest 取 permissions[0]
        _manifest = (
            plugin_manager.agents_for_intent(intent) if plugin_manager else None
        ) if intent is not None else None
        if _manifest is None and plugin_manager is not None:
            _manifest = plugin_manager.get(agent_name)
        if plugin_manager is not None and _manifest is not None and _manifest.permissions:
            from _0_CorpAI._2_platform.auth.scopes import has_scope
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
                summarized = (await chain.ainvoke(
                    {"query": query_str, "raw_response": agent_result},
                )).content.strip()
        return strip_think(summarized)

    async def simple_step_executor(intent: str, query_str: str) -> str:
        # Phase 5:plugin_manager 优先拿 manifest.name,fallback 走 conf.intent 老 dict
        agent_name: str | None = None
        if plugin_manager is not None:
            _m = plugin_manager.agents_for_intent(intent)
            if _m is not None:
                agent_name = _m.name
        if agent_name is None:
            agent_name = conf.intent.get(intent)  # 兼容 Phase 1.7/2/3/4,Phase 7 后基本为空
        if not agent_name:
            return f"暂不支持意图:{intent}。当前支持:hr / devops / faq。"
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

    simple_step_executor = _make_simple_step_executor(
        agent_network, llm, memory, conf, plugin_manager,
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
        memory=memory,
        agent_card_provider=_make_agent_card_provider(agent_network, agent_urls),
    )


__all__ = ["build_default_service"]
