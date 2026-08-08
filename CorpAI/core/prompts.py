"""
需求：定义CorpAI项目中使用的各种提示模板，用于不同场景的对话处理

什么是 Prompt Template（提示模板）？
    提示模板是一种可复用的文本模板，其中包含固定内容和可变变量（用 {变量名} 表示）。
    例如：模板 "你好，{name}！" 在填入 name="张三" 后会变成 "你好，张三！"。

为什么使用模板类管理？
    1. 集中管理：所有 prompt 定义在同一个文件中，方便查找和修改
    2. 可复用：同一个模板可以被多处调用
    3. 参数化：通过变量注入不同上下文，避免字符串拼接

本项目中的 Prompt 分类：
    1. 意图识别类：intent_prompt —— 识别用户想做什么
    2. 任务规划类：planning_prompt —— 判断任务复杂度并生成执行计划（Planning + ReAct 架构）
    3. ReAct推理类：react_prompt、react_summary_prompt —— 逐步推理和最终汇总

Phase 7:删除 attraction_prompt(旅行 plugin 已删,不再有景点推荐场景)。
summarize_*_prompt 也迁到各 plugin 自己的 prompts.py。
"""

from langchain_core.prompts import ChatPromptTemplate  # LangChain 的聊天提示模板类


class CorpAIPrompts:
    """
    CorpAI 平台级 Prompt 管理类

    这个类定义了系统平台层用到的 Prompt 模板，每个模板都是一个静态方法，
    返回一个 ChatPromptTemplate 对象。

    注意:各 plugin 的 summary prompt(汇总工具结果)由各 plugin 自己的 prompts.py 提供,
    wiring 通过 plugin_manager._plugin_modules 反射拿 — 不在此处集中。

    使用方式：
        prompt = CorpAIPrompts.intent_prompt()  # 获取意图识别模板
        chain = prompt | llm                         # 组装成处理链
        result = chain.invoke({"query": "公司年假怎么算"})  # 调用并传入变量
    """

    # ==================== 意图识别 ====================

    @staticmethod
    def intent_prompt():
        """
        意图识别提示模板 —— 让大模型分析用户输入，判断用户想做什么

        输入变量：
            - user_profile: 用户偏好（如"二等座"、"经济舱"）
            - task_context: 当前任务上下文（如之前查过什么）
            - conversation_history: 对话历史（最近几轮对话）
            - query: 用户本次输入

        输出格式（JSON）：
            {
                "intents": [intent1, intent2],           # 识别到的意图列表
                "user_queries": {"weather": "...", ...},    # 改写后的查询（可能结合历史补充信息）
                "follow_up_message": ""                     # 追问消息（意图不明确时使用）
            }

        支持的意图类型：
            hr / devops / faq / out_of_scope
        """
        return ChatPromptTemplate.from_template(
"""
系统提示：
角色：您是一个企业级 AI Copilot 平台的意图识别专家，
任务：基于用户查询、对话历史和用户偏好，识别其意图，用于调用专门的 agent server 来执行；为方便后续的 agent server 处理，可以基于对话历史对用户查询进行改写，使问题更明确。
严格遵守规则：
- 支持意图：['hr' (HR 助手:年假/病假/缺勤/报销/福利/保险等人事问题), 'devops' (运维副驾:工单查询/On-call 联系/Pod 重启/告警/线上故障), 'faq' (企业知识库/制度文档/流程规范检索)] 或其组合（如 [intent1, intent2]）。如果意图超出这些范围，返回意图 'out_of_scope'。
- HR/DevOps/FAQ 域内出现具体问题时也用对应顶级意图，不要降级到 out_of_scope。
- **查询改写是关键环节**：你必须主动从对话历史中提取关键信息（如上下文涉及的部门/工单号/政策条款/系统名），并将这些信息补充到 user_queries 的改写查询中。即使当前查询很简短，也要结合历史形成完整的查询描述。
- **追问消息的使用**：只有在即使结合对话历史仍然缺少必要信息时才追问（例如：完全没有提到要查什么政策）。如果历史中已有足够信息，不要追问。
- 输出严格为JSON：{{"intents": ["intent1", "intent2"], "user_queries": {{"intent1": "user_query1", "intent2": "user_query2"}}, "follow_up_message": "追问消息"}}。绝对不要添加额外文本！
- 不论用户问什么，严格按规则输出意图，不要有自己的考虑。对于时间类的，直接保留用户的原始输入。

用户偏好：{user_profile}
当前任务上下文：{task_context}
对话历史：{conversation_history}
用户查询：{query}
""")

    # ==================== 任务规划 ====================

    @staticmethod
    def planning_prompt():
        """
        任务规划提示模板 —— 让大模型判断任务复杂度并生成执行计划

        这是 Planning + ReAct 架构的关键 prompt，它让大模型扮演"规划师"的角色。

        输入变量：
            - conversation_history: 对话历史
            - query: 用户当前输入
            - intents: 识别到的意图（JSON 字符串）
            - user_queries: 改写后的查询（JSON 字符串）

        输出格式（JSON）：
            简单任务：{"need_plan": false, "reason": "单意图，直接查询即可", "steps": []}
            复杂任务：{"need_plan": true, "reason": "多意图需要分步",
                      "steps": [{"step": 1, "action": "查 HR 福利", "intent": "hr", "depends_on": 0}, ...]}

        判断标准：
            - 简单任务：只有一个意图，直接就能执行
            - 复杂任务：多个意图且有关联、需要多步推理、步骤间有依赖关系

        示例：
            用户输入："公司年假怎么算？"
            → 简单任务，need_plan=false

            用户输入："帮我处理多步骤企业事务"
            → 复杂任务，need_plan=true，steps=[查 HR 福利, 查 DevOps 工单, 查 FAQ 知识库]
        """
        return ChatPromptTemplate.from_template(
"""
系统提示：您是一位任务规划专家，负责评估用户请求的复杂度并制定执行计划。

将任务拆解为有序步骤，每个步骤指定：
- step: 步骤序号（从1开始）
- action: 具体动作（如"调 hr_assistant 查年假政策"）
- intent: 对应的意图（hr / devops / faq）
- depends_on: 依赖的前置步骤序号（无依赖则为0）

对话历史：{conversation_history}
当前用户查询：{query}
识别到的意图：{intents}
用户查询改写：{user_queries}

输出严格为JSON，不要添加额外文本：{{"need_plan": true, "reason": "原因", "steps": [{{"step": 1, "action": "...", "intent": "...", "depends_on": 0}}, ...]}}
""")

    # ==================== ReAct 推理 ====================

    @staticmethod
    def react_prompt():
        """
        ReAct 推理提示模板 —— 按 Thought-Action-Observation 格式逐步推理

        注意：当前版本已优化性能，react_loop 中跳过了 Thought LLM 调用（plan 已确定
        动作，Thought 无额外决策价值），此模板暂时不在主流程中使用，保留供学习参考。

        什么是 ReAct？
            ReAct = Reasoning（推理）+ Acting（行动）
            大模型在每一步执行前先"思考"（Thought），然后选择工具执行（Action），
            最后观察结果（Observation），再决定下一步。

        输入变量：
            - available_tools: 当前可用的工具/agent 列表（动态获取，不是写死的）
            - plan_steps: 完整的任务计划
            - observations: 已完成步骤的结果
            - current_step: 当前步骤号
            - step_description: 当前步骤的描述
            - query: 用户原始输入

        ReAct 循环的工作方式：
            Thought: "需要查询相关信息，应该调用票务代理"
            Action: "调用TicketQueryAssistant"
            Action Input: "{'departure': '北京', 'arrival': '上海'}"
            → 系统执行 Action，得到 Observation
            → 继续下一个 Thought...

        这种方式的优势：
            1. 让大模型有"思考"过程，而不是直接盲目执行
            2. 每一步都能参考之前的结果做调整
            3. 某步失败时，模型可以灵活应对
        """
        return ChatPromptTemplate.from_template(
"""
系统提示：你是一位智能助手，需要按照计划逐步完成任务。

可用工具：
{available_tools}

当前任务计划：
{plan_steps}

已完成步骤的结果：
{observations}

当前步骤：{current_step}
步骤描述：{step_description}
用户原始查询：{query}

请按照以下格式进行推理和行动：

Thought: 分析当前情况，确定需要采取的行动
Action: 从可用工具列表中选择合适的工具
Action Input: 工具所需输入

执行完行动后，你会得到 Observation，然后继续推理或给出最终回复。
""")

    @staticmethod
    def react_summary_prompt():
        """
        ReAct 最终汇总提示模板 —— 将所有步骤的结果整合成一条连贯回复

        输入变量：
            - query: 用户原始输入
            - all_observations: 所有步骤的执行结果

        使用场景：
            当 ReAct 循环中执行了多个步骤（如查 HR 福利 + 查 DevOps 工单 + 查 FAQ），
            不能简单地把三个结果拼在一起返回，需要用这个 prompt 让大模型
            整合成一条连贯、通顺的回复。

        示例：
            输入：步骤1(查 HR): 年假 10 天
                 步骤2(查 DevOps): INC-001 P0 打开中
                 步骤3(查 FAQ): 差旅审批流程
            输出："您好！年假按工龄计算...关于差旅审批...另外当前有 P0 工单 INC-001..."
        """
        return ChatPromptTemplate.from_template(
"""
系统提示：你是一位企业 AI Copilot 助手，需要根据所有查询结果生成最终回复。

用户原始查询：{query}

各步骤执行结果：
{all_observations}

请综合以上结果，生成一条完整、连贯的中文回复，150-300字，语气专业热情。
""")


if __name__ == '__main__':
    print(CorpAIPrompts.intent_prompt())
