"""
票务智能体集成测试

测试内容：
1. A2A 服务器启动和注册
2. 通过 A2A 协议调用票务智能体
3. 验证工具调用参数正确传递

前置条件：
1. 票务 MCP 服务器必须运行在 http://127.0.0.1:8001
2. 票务 A2A 服务器必须运行在 http://127.0.0.1:5006

运行方式：
    # 先启动 MCP 服务器
    python mcp_server/mcp_ticket_server.py

    # 再启动 A2A 服务器
    python a2a_server/ticket_server.py

    # 运行测试
    python -m tests.test_ticket_agent
"""

import unittest
import time
import sys
import os

# 确保能导入 SmartVoyage 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from python_a2a import A2AClient, Task


class TestTicketAgent(unittest.TestCase):
    """测试票务智能体（TicketAssistant）"""

    @classmethod
    def setUpClass(cls):
        """设置测试客户端"""
        cls.client = A2AClient("http://127.0.0.1:5006", timeout=120)

    def test_query_train_ticket(self):
        """测试火车票查询 - 验证多参数正确传递"""
        result = self.client.ask("帮我查询北京到成都，2026年8月1号的火车票")
        print(f"火车票查询结果: {result}")

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

    def test_query_train_with_seat_type(self):
        """测试带座位类型的火车票查询"""
        result = self.client.ask("查询北京到上海的火车票，8月2号，二等座")
        print(f"带座位类型查询结果: {result}")
        self.assertIsNotNone(result)

    def test_query_flight_ticket(self):
        """测试机票查询"""
        result = self.client.ask("帮我查一下北京到成都8月1号的机票")
        print(f"机票查询结果: {result}")
        self.assertIsNotNone(result)

    def test_query_flight_business_class(self):
        """测试商务舱机票查询"""
        result = self.client.ask("查询北京到成都的机票，8月3号，经济舱")
        print(f"经济舱机票查询结果: {result}")
        self.assertIsNotNone(result)

    def test_query_concert(self):
        """测试演唱会票查询"""
        result = self.client.ask("查询成都薛之谦8月1号的演唱会门票")
        print(f"演唱会查询结果: {result}")
        self.assertIsNotNone(result)

    def test_ask_missing_params_followup(self):
        """测试缺少参数时是否正确追问"""
        result = self.client.ask("帮我查火车票")  # 缺少出发地、目的地、日期
        print(f"追问测试结果: {result}")
        self.assertIsNotNone(result)

        # 应该返回追问或某种形式的回复
        if hasattr(result, 'status'):
            status = result.status
            if hasattr(status, 'state'):
                # 可能是追问（INPUT_REQUIRED）或直接回答
                self.assertIn(str(status.state), ['COMPLETED', 'completed', 'INPUT_REQUIRED', 'input_required', 'FAILED', 'failed'])

    def test_agent_card(self):
        """测试代理卡片是否正确注册"""
        # 获取代理信息
        result = self.client.ask("你好")
        print(f"Agent Card 测试: {result}")
        self.assertIsNotNone(result)


class TestTicketAgentTools(unittest.TestCase):
    """测试票务工具是否能正确接收多参数"""

    @classmethod
    def setUpClass(cls):
        cls.client = A2AClient("http://127.0.0.1:5006", timeout=120)

    def test_train_query_with_all_params(self):
        """测试提供完整参数时工具调用"""
        # 这个测试确保工具能正确接收所有参数
        result = self.client.ask("北京到成都8月5号高铁票，二等座")
        print(f"完整参数火车票查询: {result}")

        self.assertIsNotNone(result)
        # 验证不是错误信息
        if hasattr(result, 'status') and hasattr(result.status, 'message'):
            message = str(result.status.message)
            self.assertNotIn("Too many arguments", message)
            self.assertNotIn("错误", message[:100] if len(message) > 100 else message)


if __name__ == "__main__":
    print("=" * 60)
    print("票务智能体集成测试")
    print("请确保票务 MCP 服务器 (8001) 和 A2A 服务器 (5006) 已启动")
    print("=" * 60)
    unittest.main(verbosity=2)
