"""
需求：实现基于A2A的统一票务服务器，处理用户的火车票、机票和演唱会票查询及预订请求

架构说明：
    本服务器是 CorpAI 系统中的另一个子代理（Sub-Agent），负责处理所有票务相关任务。
    它运行在独立的进程中（localhost:5006），通过 A2A（Agent2Agent）协议与主助手通信。

    与 weather_server 的区别：
    - weather_server 使用 LLM 生成 SQL，再通过 MCP 执行（Text-to-SQL 模式）
    - ticket_server 使用 LangChain Agent + MCP Tools 模式（工具调用模式）
      LLM 直接决定调用哪个 MCP 工具（火车票查询/机票查询/演唱会查询/预定），
      然后由 LangChain 的 AgentExecutor 自动完成工具调用和结果处理

    工作流程：
    1. 主助手通过 A2A 协议向本服务器发送任务（Task）
    2. 本服务器收到任务后，提取用户的自然语言查询
    3. 使用 LangChain Agent（基于工具调用的 Agent）处理查询：
       a. LLM 分析用户输入，决定调用哪个 MCP 工具
       b. LangChain 自动调用 MCP Server 的工具（端口 8001）
       c. 工具返回结果后，LLM 将结果格式化为友好的中文回复
    4. 将结果返回给主助手

    涉及的关键技术：
    - LangChain Agent: 一种让 LLM 自主选择和使用工具的框架
    - Tool Calling Agent: 一种 Agent 类型，LLM 以结构化格式调用工具
    - MCP Tools: MCP Server 提供的工具，本系统中包括火车票查询、机票查询等
    - AgentExecutor: LangChain 的执行器，负责运行 Agent 循环（思考→调用工具→处理结果→继续）

    MCP Server（端口 8001）提供的工具包括：
    - 火车票查询工具
    - 机票查询工具
    - 演唱会门票查询工具
    - 火车票预定工具
    - 机票预定工具
    - 演唱会门票预定工具
"""

# ==================== 逻辑流程图 ====================
#
#  ┌─────────────────────────────────────────────────────────────────┐
#  │                        主程序入口 (__main__)                      │
#  │  1. 创建 TicketServer 实例                                        │
#  │    │
#  │  2. run_server(ticket_server, host, port=5006)                   │
#  └──────────────────────────────┬──────────────────────────────────┘
#                                 ▼
#  ┌─────────────────────────────────────────────────────────────────┐
#  │                     模块加载 & 全局初始化                            │
#  │  ┌─────────────────────┐    ┌──────────────────────────────┐    │
#  │  │ 1. 初始化 LLM        │    │ 2. 定义 AgentCard             │    │
#  │  │    ChatOpenAI(...)   │    │    - name: TicketAssistant    │    │
#  │  │    (model/base_url/  │    │    - 6 个 AgentSkill:         │    │
#  │  │     api_key/temp)    │    │      查询: 火车/机票/演唱会      │    │
#  │  └─────────────────────┘    │      预定: 火车/机票/演唱会      │    │
#  │                              └──────────────┬───────────────┘    │
#  └─────────────────────────────────────────────┼───────────────────┘
#                                                ▼
#  ┌─────────────────────────────────────────────────────────────────┐
#  │                    TicketServer.__init__()                        │
#  │    super().__init__(agent_card=agent_card)                       │
#  └──────────────────────────────┬──────────────────────────────────┘
#                                 ▼  (主助手通过 A2A 发送 Task)
#  ┌─────────────────────────────────────────────────────────────────┐
#  │                    TicketServer.handle_task(task)                 │
#  │                                                                 │
#  │  5.1 提取用户查询: query = task.message["content"]                │
#  │        │                                                        │
#  │        ▼                                                        │
#  │  5.2 获取 MCP 工具集: tools = to_langchain_tool(MCP_URL:8001)    │
#  │        │                                                        │
#  │        ▼                                                        │
#  │  5.3 构建 Prompt: ChatPromptTemplate                              │
#  │        │  system: 角色说明 + 参数校验要求 + 当前日期                  │
#  │        │  human:  {input}                                        │
#  │        │  placeholder: {agent_scratchpad}                        │
#  │        ▼                                                        │
#  │  5.4 构建 Agent:                                                  │
#  │        create_tool_calling_agent(llm, tools, prompt)              │
#  │        AgentExecutor(agent, tools, verbose=True)                  │
#  │        │                                                        │
#  │        ▼                                                        │
#  │  5.5 执行 Agent 循环: agent_executor.invoke()                      │
#  │        ┌──────────────────────────────────────┐                  │
#  │        │  LLM 分析输入 → 选择 MCP 工具           │                  │
#  │        │  → 调用工具(端口 8001) → 获取结果        │                  │
#  │        │  → 格式化为中文回复                     │                  │
#  │        └──────────────────────────────────────┘                  │
#  │        │                                                        │
#  │        ▼                                                        │
#  │  5.6 结果分支处理:                                                  │
#  │        │                                                        │
#  │        ├─ "缺少" in output                                        │
#  │        │   → TaskState.INPUT_REQUIRED                             │
#  │        │   → 返回追问信息                                          │
#  │        │                                                        │
#  │        ├─ 正常输出                                                │
#  │        │   → TaskState.COMPLETED                                  │
#  │        │   → artifacts = [格式化结果]                              │
#  │        │                                                        │
#  │        └─ Exception                                             │
#  │            → TaskState.FAILED                                     │
#  │            → 错误信息                                             │
#  │                                                                 │
#  └──────────────────────────────┬──────────────────────────────────┘
#                                 ▼
#                          返回 task 给主助手
#
# ==================== 导入依赖 ====================
import asyncio  # 异步IO库
import json  # 用于 query_concert 缺参时返回 JSON 提示

from python_a2a import A2AServer, run_server, AgentCard, AgentSkill, TaskStatus, TaskState
# A2AServer: A2A 服务器基类
# run_server: 启动服务器的函数
# AgentCard: 代理卡片
# AgentSkill: 代理技能
# TaskStatus: 任务状态对象
# TaskState: 任务状态枚举（COMPLETED / FAILED / INPUT_REQUIRED）

from langchain_openai import ChatOpenAI  # LangChain 的大模型接口
from langchain_core.prompts import ChatPromptTemplate  # 提示模板
from langchain_core.tools import StructuredTool  # 结构化 LangChain 工具
from langchain.agents import create_tool_calling_agent, AgentExecutor
from pydantic import BaseModel, Field  # StructuredTool 的参数 schema
import requests  # 直接调 MCP HTTP API,绕开 to_langchain_tool 的桥接 bug
from typing import Optional  # 可选类型标注

from datetime import datetime  # 时间处理
import pytz  # 时区库

from CorpAI.config import Config  # 项目配置
from CorpAI.logging import logger  # 日志模块
from CorpAI.utils.format import strip_think  # 剥掉 LLM 回复里的 <think> 块

# 1. 初始化大模型

conf = Config()

# 初始化LLM
llm = ChatOpenAI(
    model=conf.model_name,
    base_url=conf.base_url,
    api_key=conf.api_key,
    temperature=conf.temperature
)
# 2. 定义AgentCard，6个skill

# ==================== Agent Card（代理卡片） ====================
# 描述票务代理的能力、技能等信息
# 主助手通过这个卡片决定是否将票务相关任务路由到这个代理
# TODO 这里的6个skill作用：是给主路由在选择子Agent的时候作为参考使用的，和MCP层的工具没有对应的关系。可以将6个skill合成2个，
# 1. 查询票务（火车票、机票、演唱会） 2. 预定票（火车票、机票、演唱会）
agent_card = AgentCard(
    name="TicketAssistant",  # 代理名称
    description="基于 LangChain 提供票务查询和预订服务的统一助手",  # 代理描述
    url="http://localhost:5006",  # 代理的访问地址
    version="2.0.0",  # 版本号
    capabilities={"streaming": True, "memory": True},  # 支持的能力
    skills=[
        # 技能1：火车票查询
        AgentSkill(
            name="query train tickets",
            description="查询火车票/火车票，支持指定出发城市、到达城市、日期和座位类型",
            examples=["火车票 北京 上海 2025-07-31", "北京到广州的高铁 明天 二等座"]
        ),
        # 技能2：机票查询
        AgentSkill(
            name="query flight tickets",
            description="查询机票/航班，支持指定出发城市、到达城市、日期和舱位类型",
            examples=["机票 北京 上海 2025-07-31", "北京到深圳的机票 后天 经济舱"]
        ),
        # 技能3：演唱会门票查询
        AgentSkill(
            name="query concert tickets",
            description="查询演唱会门票，支持指定城市、艺人、日期和票档类型",
            examples=["演唱会 北京 刀郎 2025-08-23", "周杰伦演唱会门票 上海"]
        ),
        # 技能4：火车票预定
        AgentSkill(
            name="order train tickets",
            description="根据车次、座位类型和数量预定火车票",
            examples=["预定G1次列车 2025-11-15 北京到上海 二等座 1张"]
        ),
        # 技能5：机票预定
        AgentSkill(
            name="order flight tickets",
            description="根据航班号、舱位类型和数量预定机票",
            examples=["预定MU5101 2025-12-11 上海到北京 公务舱 2张"]
        ),
        # 技能6：演唱会门票预定
        AgentSkill(
            name="order concert tickets",
            description="根据艺人、场地、日期、票档和数量预定演唱会门票",
            examples=["预定刀郎演唱会 2025-08-23 北京 看台票 2张"]
        )
    ]
)

MCP_URL = 'http://127.0.0.1:8001'


# 3. 定义类，继承A2AServer
class TicketServer(A2AServer):
    # 4. 实现初始化
    def __init__(self):
        super().__init__(agent_card=agent_card)

    # 5. 实现handle_task
    # 接收用户的请求，使用langchain-agent自动去调用对应的工具集
    def handle_task(self, task):
        # 5.1 从task里面获取message
        content = (task.message or {}).get("content", {})
        query = content.get("text", "") if isinstance(content, dict) else ""
        logger.info(f"用户票务查询: {query}")
        # 5.2 获取MCP Server所有的工具集（tools）
        # ========== 手动定义 StructuredTool 包装,绕开 to_langchain_tool 的桥接 bug ==========
        # 原因:to_langchain_tool 把多参数工具折叠成单 input,LLM 不知道传几个 named 参数
        # 解决:直接 HTTP 调 /tools/{name},用 Pydantic schema 暴露真实参数

        def _call_mcp_tool(tool_name: str, **kwargs) -> str:
            """直接 HTTP POST 调 MCP 工具"""
            try:
                resp = requests.post(
                    f"{MCP_URL}/tools/{tool_name}",
                    json=kwargs,
                    timeout=30
                )
                resp.raise_for_status()
                result = resp.json()
                if "error" in result:
                    return f"工具调用失败:{result['error']}"
                content = result.get("content", [])
                if content and isinstance(content, list) and "text" in content[0]:
                    return content[0]["text"]
                return str(result)
            except Exception as e:
                logger.error(f"MCP 工具 {tool_name} 调用异常: {e}")
                return f"MCP 工具调用异常:{str(e)}"

        # ---- 1. query_train ----
        class QueryTrainInput(BaseModel):
            departure_city: str = Field(..., description="出发城市,如'北京'")
            arrival_city: str = Field(..., description="到达城市,如'上海'")
            date: str = Field(..., description="出发日期,格式 YYYY-MM-DD")
            seat_type: Optional[str] = Field(None, description="座位类型,可选:二等座/一等座/商务座")

        def query_train(departure_city: str, arrival_city: str, date: str, seat_type: Optional[str] = None) -> str:
            return _call_mcp_tool("query_train", departure_city=departure_city,
                                  arrival_city=arrival_city, date=date, seat_type=seat_type)

        # ---- 2. order_train ----
        class OrderTrainInput(BaseModel):
            departure_date: str = Field(..., description="出发日期,格式 YYYY-MM-DD")
            train_number: str = Field(..., description="车次号,如 G123")
            seat_type: str = Field(..., description="座位类型,如 二等座/一等座/商务座")
            number: int = Field(..., description="订票数量")

        def order_train(departure_date: str, train_number: str, seat_type: str, number: int) -> str:
            return _call_mcp_tool("order_train", departure_date=departure_date,
                                  train_number=train_number, seat_type=seat_type, number=number)

        # ---- 3. query_flight ----
        class QueryFlightInput(BaseModel):
            departure_city: str = Field(..., description="出发城市,如'北京'")
            arrival_city: str = Field(..., description="到达城市,如'成都'")
            date: str = Field(..., description="出发日期,格式 YYYY-MM-DD")
            cabin_type: Optional[str] = Field(None, description="舱位类型,可选:经济舱/商务舱/头等舱")

        def query_flight(departure_city: str, arrival_city: str, date: str, cabin_type: Optional[str] = None) -> str:
            return _call_mcp_tool("query_flight", departure_city=departure_city,
                                  arrival_city=arrival_city, date=date, cabin_type=cabin_type)

        # ---- 4. order_flight ----
        class OrderFlightInput(BaseModel):
            departure_date: str = Field(..., description="出发日期,格式 YYYY-MM-DD")
            flight_number: str = Field(..., description="航班号,如 CA4101")
            cabin_type: str = Field(..., description="舱位类型,如 经济舱/商务舱/头等舱")
            number: int = Field(..., description="订票数量")

        def order_flight(departure_date: str, flight_number: str, cabin_type: str, number: int) -> str:
            return _call_mcp_tool("order_flight", departure_date=departure_date,
                                  flight_number=flight_number, cabin_type=cabin_type, number=number)

        # ---- 5. query_concert ----
        # city/artist/date 业务上必传,但 Pydantic 也标成 Optional + 提示 LLM 追问,
        # 函数内部判 None 返回友好提示
        class QueryConcertInput(BaseModel):
            city: Optional[str] = Field(None, description="演出城市,如'上海'")
            artist: Optional[str] = Field(None, description="艺人/乐队名,如'周杰伦',**必填**")
            date: Optional[str] = Field(None, description="演出日期,格式 YYYY-MM-DD,**必填**")
            ticket_type: Optional[str] = Field(None, description="票类型,可选:VIP/普通票")

        def query_concert(city: Optional[str] = None, artist: Optional[str] = None,
                          date: Optional[str] = None, ticket_type: Optional[str] = None) -> str:
            if not artist or not date:
                return json.dumps(
                    {"status": "missing_params", "message": "查询演唱会需要提供艺人名称和演出日期,请追问用户。"},
                    ensure_ascii=False
                )
            return _call_mcp_tool("query_concert", city=city, artist=artist,
                                  date=date, ticket_type=ticket_type)

        # ---- 6. order_concert ----
        class OrderConcertInput(BaseModel):
            artist: str = Field(..., description="艺人/乐队名")
            start_date: str = Field(..., description="演出日期,格式 YYYY-MM-DD")
            venue: str = Field(..., description="演出场馆名")
            ticket_type: str = Field(..., description="票类型,如 VIP/普通票")
            number: int = Field(..., description="订票数量")

        def order_concert(artist: str, start_date: str, venue: str, ticket_type: str, number: int) -> str:
            return _call_mcp_tool("order_concert", artist=artist, start_date=start_date,
                                  venue=venue, ticket_type=ticket_type, number=number)

        tools = [
            StructuredTool.from_function(func=query_train, name="query_train",
                description="查询火车票,参数:departure_city(出发城市),arrival_city(到达城市),date(出发日期YYYY-MM-DD),seat_type(座位类型,可选)",
                args_schema=QueryTrainInput),
            StructuredTool.from_function(func=order_train, name="order_train",
                description="预定火车票,参数:departure_date(出发日期YYYY-MM-DD),train_number(车次号),seat_type(座位类型),number(数量)",
                args_schema=OrderTrainInput),
            StructuredTool.from_function(func=query_flight, name="query_flight",
                description="查询机票,参数:departure_city(出发城市),arrival_city(到达城市),date(出发日期YYYY-MM-DD),cabin_type(舱位类型,可选)",
                args_schema=QueryFlightInput),
            StructuredTool.from_function(func=order_flight, name="order_flight",
                description="预定机票,参数:departure_date(出发日期YYYY-MM-DD),flight_number(航班号),cabin_type(舱位类型),number(数量)",
                args_schema=OrderFlightInput),
            StructuredTool.from_function(func=query_concert, name="query_concert",
                description="查询演唱会票,参数:city(城市),artist(艺人,**必填**),date(演出日期YYYY-MM-DD,**必填**),ticket_type(票类型,可选)",
                args_schema=QueryConcertInput),
            StructuredTool.from_function(func=order_concert, name="order_concert",
                description="预定演唱会票,参数:artist(艺人),start_date(演出日期YYYY-MM-DD),venue(场馆),ticket_type(票类型),number(数量)",
                args_schema=OrderConcertInput),
        ]
        # 5.3 构建提示词模板(prompt)
        prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一个票务预定和查询助手，能够调用工具来完成火车票、飞机票或演出票的预定和查询。
你需要仔细分析工具需要的参数，然后从用户提供的信息中提取参数值，再调用对应的查询或预定工具。
如果用户提供的信息不足以提取到调用工具的所有必要参数，则向用户追问，以获取该信息。不能自己编撰参数。
注意：
- 用户可能使用相对时间，如"明天"、"后天"、"今天"、"下周六"等，请根据当前日期转换为具体日期（YYYY-MM-DD格式）。
- 查询火车票时，需要出发城市、到达城市、日期；如果缺少任一参数，需要追问。
- 查询机票时，需要出发城市、到达城市、日期；如果缺少任一参数，需要追问。
- 查询演唱会门票时，需要城市和艺人名称；如果缺少任一参数，需要追问。
- 预定票务时，需要具体的车次/航班/演出信息、座位/票档类型和数量；如果缺少任一参数，需要追问。
- 【重要】当你需要向用户追问时，回复必须以"[追问]"开头，例如："[追问]请问您想查询哪一天的火车票？"
查询到结果后，请用清晰的中文格式化输出票务信息，包括车次/航班/演出、日期、出发到达城市、座位/票档类型、价格等。
如果未查到数据，请回复"未找到相关票务数据，请确认或修改查询条件。"
当前日期是{current_date}。"""),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ])
        # 5.4 构建Agent(tools + prompt + llm)
        agent = create_tool_calling_agent(llm, tools, prompt)
        agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)
        # 5.5 执行请求Agent的invoke
        try:
            current_date = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')
            result = agent_executor.invoke({'input': query,
                                            'current_date': current_date
                                            })
            output = strip_think(result['output'])
            # 5.6 根据返回结果封装Task.Status和artifacts
            # 检查是否是追问消息（LLM 发现信息不足时会追问）
            # 判断优先级：[追问] 前缀（Prompt 约定）> 关键词兜底
            # 注意：LLM 格式化输出中可能包含"请告诉我"等礼貌用语，不能仅凭关键词判断
            # 如果输出中包含实际数据（价格、车次、航班等），说明是查询结果而非追问
            has_data = (
                "¥" in output or "￥" in output
                or "余票" in output
                or "车次" in output
                or "航班" in output
                or "场馆" in output
                or "演出" in output
            )
            is_followup = (
                output.strip().startswith("[追问]")  # Prompt 约定的追问标记（最高优先级）
                or (not has_data and (
                    "请提供" in output
                    or "请告诉我" in output
                    or "请问您" in output
                    or "缺少" in output
                    or "哪一天" in output
                    or "哪个城市" in output
                    or "哪个车次" in output
                    or "哪个航班" in output
                    or "哪种座位" in output
                    or "哪种票档" in output
                ))
            )
            # ① 缺少参数，需要追问
            if is_followup:
                clean_text = output.replace("[追问]", "").strip()
                task.status = TaskStatus(
                    state=TaskState.INPUT_REQUIRED,
                    message={"role": "agent", "content": {"text": clean_text}}
                )
            else:
                # ② 运行成功
                task.status = TaskStatus(
                    state=TaskState.COMPLETED,
                    message={"role": "agent", "content": {"text": "运行成功"}}
                )
                task.artifacts = [{"parts": [{"type": "text", "text": output}]}]
            return task
        except Exception as e:
            # ③ 运行失败
            task.status = TaskStatus(TaskState.FAILED,

                                     message={"role": "agent", "content": {"text": f"agent执行失败：{e}"}}
                                     )
            return task
if __name__ == "__main__":
    # 创建票务查询服务器实例
    ticket_server = TicketServer()

    # 打印服务器信息，方便确认启动状态
    print("\n=== 服务器信息 ===")
    print(f"名称: {ticket_server.agent_card.name}")
    print(f"描述: {ticket_server.agent_card.description}")
    print("\n技能:")
    for skill in ticket_server.agent_card.skills:
        print(f"- {skill.name}: {skill.description}")

    # 启动 A2A 服务器，监听 5006 端口
    # 主助手会通过 http://localhost:5006 连接本服务器
    run_server(ticket_server, host="127.0.0.1", port=5006)
