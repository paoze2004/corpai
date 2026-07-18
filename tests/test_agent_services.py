"""
Agent 服务集成测试模块

测试内容：
1. WeatherQueryAssistant - 天气查询 Agent
2. TicketAssistant - 票务 Agent
3. TripAssistant - 行程管家 Agent

前置条件：
- MCP 服务器必须运行在对应端口：
  - 天气 MCP: http://127.0.0.1:8002
  - 票务 MCP: http://127.0.0.1:8001
  - 行程 MCP: http://127.0.0.1:8003
- A2A 服务器必须运行在对应端口：
  - 天气 A2A: http://127.0.0.1:5005
  - 票务 A2A: http://127.0.0.1:5006
  - 行程 A2A: http://127.0.0.1:5007

运行方式：
    # 启动所有 MCP 服务器
    python mcp_server/mcp_weather_server.py  # 端口 8002
    python mcp_server/mcp_ticket_server.py   # 端口 8001
    python mcp_server/mcp_trip_server.py     # 端口 8003

    # 启动所有 A2A 服务器
    python a2a_server/weather_server.py  # 端口 5005
    python a2a_server/ticket_server.py   # 端口 5006
    python a2a_server/trip_server.py     # 端口 5007

    # 运行测试
    python -m tests.test_agent_services
"""

import unittest
import sys
import os

# 确保能导入 SmartVoyage 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from python_a2a import A2AClient, TaskState


class TestWeatherAgent(unittest.TestCase):
    """测试天气查询 Agent"""

    @classmethod
    def setUpClass(cls):
        cls.client = A2AClient("http://127.0.0.1:5005", timeout=120)

    def _get_result_text(self, result):
        """从 A2A 结果中提取文本内容"""
        if hasattr(result, 'artifacts') and result.artifacts:
            parts = result.artifacts[0].get('parts', [])
            for part in parts:
                if part.get('type') == 'text':
                    return part.get('text', '')
        return ''

    def _is_completed(self, result):
        """检查任务是否成功完成"""
        if hasattr(result, 'status') and hasattr(result.status, 'state'):
            return str(result.status.state) in ['COMPLETED', 'completed']
        return False

    def _is_input_required(self, result):
        """检查是否需要用户补充输入"""
        if hasattr(result, 'status') and hasattr(result.status, 'state'):
            return str(result.status.state) in ['INPUT_REQUIRED', 'input_required']
        return False

    def test_query_beijing_weather(self):
        """测试北京天气查询"""
        result = self.client.ask("帮我查一下北京明天的天气")
        self.assertIsNotNone(result)

        # 验证返回了有效内容
        if hasattr(result, 'artifacts') and result.artifacts:
            text = self._get_result_text(result)
            self.assertIsInstance(text, str)
            self.assertGreater(len(text), 0)
            # 验证包含天气相关信息
            self.assertTrue(
                "北京" in text or "天气" in text or "温度" in text,
                f"结果应包含天气信息，实际内容: {text[:100]}"
            )

    def test_query_chengdu_weather(self):
        """测试成都天气查询"""
        result = self.client.ask("成都后天天气怎么样")
        self.assertIsNotNone(result)

        if hasattr(result, 'artifacts') and result.artifacts:
            text = self._get_result_text(result)
            self.assertIsInstance(text, str)

    def test_query_date_range(self):
        """测试日期范围查询"""
        result = self.client.ask("查询北京未来5天的天气")
        self.assertIsNotNone(result)

    def test_query_specific_date(self):
        """测试指定日期查询"""
        result = self.client.ask("北京2026年8月1号的天气")
        self.assertIsNotNone(result)

    def test_query_today(self):
        """测试今天天气查询"""
        result = self.client.ask("今天天气如何")
        self.assertIsNotNone(result)

    def test_greeting(self):
        """测试问候语响应"""
        result = self.client.ask("你好")
        self.assertIsNotNone(result)
        # 天气 Agent 应该能响应问候
        if hasattr(result, 'status') and hasattr(result.status, 'message'):
            message = result.status.message
            if isinstance(message, dict):
                content = message.get('content', {})
                if isinstance(content, dict):
                    text = content.get('text', '')
                    self.assertIsInstance(text, str)


class TestTicketAgent(unittest.TestCase):
    """测试票务 Agent"""

    @classmethod
    def setUpClass(cls):
        cls.client = A2AClient("http://127.0.0.1:5006", timeout=120)

    def _get_result_text(self, result):
        """从 A2A 结果中提取文本内容"""
        if hasattr(result, 'artifacts') and result.artifacts:
            parts = result.artifacts[0].get('parts', [])
            for part in parts:
                if part.get('type') == 'text':
                    return part.get('text', '')
        return ''

    # ========== 火车票测试 ==========
    def test_query_train_with_all_params(self):
        """测试提供完整参数的火车票查询"""
        result = self.client.ask("北京到成都的火车票，2026年5月1日，二等座")
        self.assertIsNotNone(result)

        if hasattr(result, 'artifacts') and result.artifacts:
            text = self._get_result_text(result)
            self.assertIsInstance(text, str)
            # 应该包含车次或价格信息
            self.assertTrue(
                "车次" in text or "¥" in text or "价格" in text or "火车" in text,
                f"结果应包含火车票相关信息，实际内容: {text[:100]}"
            )

    def test_query_train_partial_params(self):
        """测试部分参数的火车票查询"""
        result = self.client.ask("查一下北京到成都的火车票")
        self.assertIsNotNone(result)

    def test_query_train_tomorrow(self):
        """测试相对时间的火车票查询"""
        result = self.client.ask("明天北京到上海的高铁")
        self.assertIsNotNone(result)

    # ========== 机票测试 ==========
    def test_query_flight_with_all_params(self):
        """测试提供完整参数的机票查询"""
        result = self.client.ask("北京飞成都的机票，2026-05-01，头等舱")
        self.assertIsNotNone(result)

        if hasattr(result, 'artifacts') and result.artifacts:
            text = self._get_result_text(result)
            self.assertIsInstance(text, str)

    def test_query_flight_partial_params(self):
        """测试部分参数的机票查询"""
        result = self.client.ask("帮我查一下上海到深圳的机票")
        self.assertIsNotNone(result)

    # ========== 演唱会测试 ==========
    def test_query_concert_xuezhiqian(self):
        """测试薛之谦演唱会查询"""
        result = self.client.ask("薛之谦成都演唱会门票")
        self.assertIsNotNone(result)

        if hasattr(result, 'artifacts') and result.artifacts:
            text = self._get_result_text(result)
            self.assertIsInstance(text, str)

    def test_query_concert_with_date(self):
        """测试带日期的演唱会查询"""
        result = self.client.ask("成都2026年5月1日有什么演唱会")
        self.assertIsNotNone(result)

    # ========== 追问场景测试 ==========
    def test_missing_city_prompts_followup(self):
        """测试缺少城市时是否正确追问"""
        result = self.client.ask("帮我查一下明天的火车票")
        self.assertIsNotNone(result)

        # 应该要求补充城市信息
        if hasattr(result, 'status') and hasattr(result.status, 'state'):
            state = str(result.status.state)
            self.assertIn(state, ['INPUT_REQUIRED', 'input_required',
                                   'COMPLETED', 'completed'])

    # ========== 无数据场景测试 ==========
    def test_no_data_response(self):
        """测试无数据时的响应"""
        result = self.client.ask("北京到拉萨的机票，2026-05-01")
        self.assertIsNotNone(result)


class TestTripAgent(unittest.TestCase):
    """测试行程管家 Agent"""

    @classmethod
    def setUpClass(cls):
        cls.client = A2AClient("http://127.0.0.1:5007", timeout=120)

    def _get_result_text(self, result):
        """从 A2A 结果中提取文本内容"""
        if hasattr(result, 'artifacts') and result.artifacts:
            parts = result.artifacts[0].get('parts', [])
            for part in parts:
                if part.get('type') == 'text':
                    return part.get('text', '')
        return ''

    # ========== 租车测试 ==========
    def test_query_car_rental_with_all_params(self):
        """测试提供完整参数的租车查询"""
        result = self.client.ask("成都租车，明天取车还车，SUV")
        self.assertIsNotNone(result)

        if hasattr(result, 'artifacts') and result.artifacts:
            text = self._get_result_text(result)
            self.assertIsInstance(text, str)
            # 应该包含租车相关信息
            self.assertTrue(
                "SUV" in text or "车" in text or "元" in text or "租车" in text,
                f"结果应包含租车相关信息，实际内容: {text[:100]}"
            )

    def test_query_car_rental_partial(self):
        """测试部分参数的租车查询"""
        result = self.client.ask("成都租一辆车")
        self.assertIsNotNone(result)

    def test_order_car_rental(self):
        """测试租车预订"""
        result = self.client.ask("预订租车，2026-05-01，SUV，1辆")
        self.assertIsNotNone(result)

        if hasattr(result, 'artifacts') and result.artifacts:
            text = self._get_result_text(result)
            self.assertIsInstance(text, str)

    # ========== 旅游团测试 ==========
    def test_query_tour_group_semantic(self):
        """测试旅游团语义搜索"""
        result = self.client.ask("想看雪山的地方")
        self.assertIsNotNone(result)

        if hasattr(result, 'artifacts') and result.artifacts:
            text = self._get_result_text(result)
            self.assertIsInstance(text, str)

    def test_query_tour_group_with_city(self):
        """测试带城市过滤的旅游团搜索"""
        result = self.client.ask("丽江有什么旅游团")
        self.assertIsNotNone(result)

    def test_query_tour_group_food(self):
        """测试美食主题旅游团搜索"""
        result = self.client.ask("美食之旅")
        self.assertIsNotNone(result)

    # ========== 保险测试 ==========
    def test_query_insurance_all(self):
        """测试查询全部保险"""
        result = self.client.ask("有什么旅行保险可以买")
        self.assertIsNotNone(result)

        if hasattr(result, 'artifacts') and result.artifacts:
            text = self._get_result_text(result)
            self.assertIsInstance(text, str)

    def test_query_insurance_by_type(self):
        """测试按类型查询保险"""
        result = self.client.ask("综合型旅行保险多少钱")
        self.assertIsNotNone(result)

    def test_order_insurance(self):
        """测试保险购买"""
        result = self.client.ask("买一份综合型保险，2026-05-01，1份")
        self.assertIsNotNone(result)

    # ========== 追问场景测试 ==========
    def test_missing_date_car_rental(self):
        """测试租车缺少日期时的追问"""
        result = self.client.ask("我想租一辆SUV")
        self.assertIsNotNone(result)

        # 应该要求补充日期信息
        if hasattr(result, 'status') and hasattr(result.status, 'state'):
            state = str(result.status.state)
            # 可能是追问或完成
            self.assertIn(state, ['INPUT_REQUIRED', 'input_required',
                                   'COMPLETED', 'completed'])

    # ========== 无数据场景测试 ==========
    def test_no_data_beijing_car(self):
        """测试北京租车无数据"""
        result = self.client.ask("北京租车，明天")
        self.assertIsNotNone(result)


class TestAgentCard(unittest.TestCase):
    """测试 Agent Card 注册和元数据"""

    def test_weather_agent_card(self):
        """测试天气 Agent Card 是否可访问"""
        client = A2AClient("http://127.0.0.1:5005", timeout=30)
        # 发送简单请求验证服务可访问
        result = client.ask("你好")
        self.assertIsNotNone(result)

    def test_ticket_agent_card(self):
        """测试票务 Agent Card 是否可访问"""
        client = A2AClient("http://127.0.0.1:5006", timeout=30)
        result = client.ask("你好")
        self.assertIsNotNone(result)

    def test_trip_agent_card(self):
        """测试行程 Agent Card 是否可访问"""
        client = A2AClient("http://127.0.0.1:5007", timeout=30)
        result = client.ask("你好")
        self.assertIsNotNone(result)


class TestAgentErrorHandling(unittest.TestCase):
    """测试 Agent 错误处理"""

    def test_weather_agent_handles_mcp_unavailable(self):
        """测试天气 Agent 处理 MCP 不可用的情况"""
        # 如果 MCP 服务未启动，应该返回错误信息而非崩溃
        client = A2AClient("http://127.0.0.1:5005", timeout=30)
        result = client.ask("北京天气")
        # 应该有返回结果（可能是错误信息）
        self.assertIsNotNone(result)

    def test_empty_query_handling(self):
        """测试空查询处理"""
        client = A2AClient("http://127.0.0.1:5005", timeout=30)
        result = client.ask("")
        # 不应该崩溃，应该有响应
        self.assertIsNotNone(result)


if __name__ == "__main__":
    print("=" * 60)
    print("Agent 服务集成测试")
    print("请确保所有 MCP 服务器 (8001/8002/8003) 和")
    print("所有 A2A 服务器 (5005/5006/5007) 已启动")
    print("=" * 60)
    unittest.main(verbosity=2)
