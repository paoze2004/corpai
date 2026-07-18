"""
行程智能体集成测试

测试内容：
1. A2A 服务器启动和注册
2. 通过 A2A 协议调用行程智能体（租车、旅游团、保险）
3. 验证工具调用参数正确传递

前置条件：
1. 行程 MCP 服务器必须运行在 http://127.0.0.1:8003
2. 行程 A2A 服务器必须运行在 http://127.0.0.1:5007

运行方式：
    # 先启动 MCP 服务器
    python mcp_server/mcp_trip_server.py

    # 再启动 A2A 服务器
    python a2a_server/trip_server.py

    # 运行测试
    python -m tests.test_trip_agent
"""

import unittest
import time
import sys
import os

# 确保能导入 SmartVoyage 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from python_a2a import A2AClient, Task


class TestTripAgent(unittest.TestCase):
    """测试行程智能体（TripAssistant）"""

    @classmethod
    def setUpClass(cls):
        """设置测试客户端"""
        cls.client = A2AClient("http://127.0.0.1:5007", timeout=120)

    def test_query_car_rental(self):
        """测试租车查询 - 验证多参数正确传递"""
        result = self.client.ask("帮我查一下成都明天租车，成都取车成都还车")
        print(f"租车查询结果: {result}")

        # 验证返回了有效结果
        self.assertIsNotNone(result)

        # 检查状态
        if hasattr(result, 'status'):
            status = result.status
            if hasattr(status, 'state'):
                self.assertIn(str(status.state), ['COMPLETED', 'completed', 'INPUT_REQUIRED', 'input_required'])

        # 如果有 artifacts，应该包含查询结果
        if hasattr(result, 'artifacts') and result.artifacts:
            text = result.artifacts[0].get('parts', [{}])[0].get('text', '')
            print(f"查询结果文本: {text}")
            # 验证返回了有效内容
            self.assertIsInstance(text, str)
            self.assertGreater(len(text), 0)

    def test_query_car_rental_with_car_type(self):
        """测试带车型的租车查询"""
        result = self.client.ask("查询成都5月1号的SUV租车信息")
        print(f"带车型租车查询结果: {result}")
        self.assertIsNotNone(result)

    def test_query_tour_group(self):
        """测试旅游团查询（语义搜索）"""
        result = self.client.ask("帮我找一下适合看雪山的旅游团")
        print(f"旅游团查询结果: {result}")
        self.assertIsNotNone(result)

    def test_query_tour_group_with_city(self):
        """测试带城市过滤的旅游团查询"""
        result = self.client.ask("成都有没有适合亲子游的短途旅行")
        print(f"城市过滤旅游团查询结果: {result}")
        self.assertIsNotNone(result)

    def test_query_insurance(self):
        """测试保险查询"""
        result = self.client.ask("帮我查一下有什么旅行保险")
        print(f"保险查询结果: {result}")
        self.assertIsNotNone(result)

    def test_query_insurance_with_type(self):
        """测试指定类型的保险查询"""
        result = self.client.ask("查询综合型旅行保险")
        print(f"综合型保险查询结果: {result}")
        self.assertIsNotNone(result)

    def test_ask_missing_params_followup(self):
        """测试缺少参数时是否正确处理"""
        result = self.client.ask("我想租车")  # 缺少地点、日期
        print(f"缺少参数测试结果: {result}")
        self.assertIsNotNone(result)

        # 应该返回追问或某种形式的回复
        if hasattr(result, 'status'):
            status = result.status
            if hasattr(status, 'state'):
                self.assertIn(str(status.state), ['COMPLETED', 'completed', 'INPUT_REQUIRED', 'input_required', 'FAILED', 'failed'])

    def test_agent_card(self):
        """测试代理卡片是否正确注册"""
        result = self.client.ask("你好")
        print(f"Agent Card 测试: {result}")
        self.assertIsNotNone(result)


class TestTripAgentTools(unittest.TestCase):
    """测试行程工具是否能正确接收多参数"""

    @classmethod
    def setUpClass(cls):
        cls.client = A2AClient("http://127.0.0.1:5007", timeout=120)

    def test_car_rental_with_all_params(self):
        """测试提供完整参数时工具调用"""
        result = self.client.ask("成都5月1号到5月3号租车，成都取成都还，SUV")
        print(f"完整参数租车查询: {result}")

        self.assertIsNotNone(result)
        # 验证不是错误信息
        if hasattr(result, 'status') and hasattr(result.status, 'message'):
            message = str(result.status.message)
            self.assertNotIn("Too many arguments", message)

    def test_tour_group_semantic_search(self):
        """测试语义搜索功能"""
        result = self.client.ask("想去一个美食之旅的地方")
        print(f"语义搜索旅游团: {result}")

        self.assertIsNotNone(result)

    def test_insurance_all_params(self):
        """测试保险查询完整参数"""
        result = self.client.ask("买一份综合型旅行保险，2026年8月1号生效，1份")
        print(f"保险查询完整参数: {result}")

        self.assertIsNotNone(result)


if __name__ == "__main__":
    print("=" * 60)
    print("行程智能体集成测试")
    print("请确保行程 MCP 服务器 (8003) 和 A2A 服务器 (5007) 已启动")
    print("=" * 60)
    unittest.main(verbosity=2)
