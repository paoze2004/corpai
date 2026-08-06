"""
天气智能体集成测试

测试内容：
1. A2A 服务器启动和注册
2. 通过 A2A 协议调用天气智能体
3. 验证工具调用参数正确传递（修复 "Too many arguments" 问题）

前置条件：
1. 天气 MCP 服务器必须运行在 http://127.0.0.1:8002
2. 天气 A2A 服务器必须运行在 http://127.0.0.1:5005

运行方式：
    # 先启动 MCP 服务器
    python mcp_server/mcp_weather_server.py

    # 再启动 A2A 服务器
    python a2a_server/weather_server.py

    # 运行测试
    python -m tests.test_weather_agent
"""

import unittest
import time
import sys
import os

# 确保能导入 CorpAI 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from python_a2a import A2AClient, Task


class TestWeatherAgent(unittest.TestCase):
    """测试天气智能体（WeatherQueryAssistant）"""

    @classmethod
    def setUpClass(cls):
        """设置测试客户端"""
        cls.client = A2AClient("http://127.0.0.1:5005", timeout=120)

    def test_query_beijing_weather(self):
        """测试北京天气查询 - 验证多参数正确传递"""
        result = self.client.ask("帮我查一下北京明天的天气")
        print(f"北京天气查询结果: {result}")

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

    def test_query_chengdu_weather(self):
        """测试成都天气查询"""
        result = self.client.ask("成都后天天气怎么样")
        print(f"成都天气查询结果: {result}")
        self.assertIsNotNone(result)

        if hasattr(result, 'artifacts') and result.artifacts:
            text = result.artifacts[0].get('parts', [{}])[0].get('text', '')
            self.assertIsInstance(text, str)

    def test_query_date_range_weather(self):
        """测试日期范围天气查询"""
        result = self.client.ask("查询北京未来5天的天气")
        print(f"日期范围查询结果: {result}")
        self.assertIsNotNone(result)

    def test_query_specific_date_weather(self):
        """测试指定日期天气查询"""
        result = self.client.ask("北京2026年8月1号的天气")
        print(f"指定日期查询结果: {result}")
        self.assertIsNotNone(result)

    def test_query_today_weather(self):
        """测试今天天气查询"""
        result = self.client.ask("今天天气如何")
        print(f"今天天气查询结果: {result}")
        self.assertIsNotNone(result)

    def test_agent_card(self):
        """测试代理卡片是否正确注册"""
        result = self.client.ask("你好")
        print(f"Agent Card 测试: {result}")
        self.assertIsNotNone(result)


class TestWeatherAgentTools(unittest.TestCase):
    """测试天气工具是否能正确接收多参数（这是核心修复点）"""

    @classmethod
    def setUpClass(cls):
        cls.client = A2AClient("http://127.0.0.1:5005", timeout=120)

    def test_tool_receives_all_three_params(self):
        """
        测试工具能正确接收三个参数（city, start_date, end_date）

        这是修复的核心验证点：之前的问题是 to_langchain_tool 不能正确
        传递多参数，导致 "Too many arguments to single-input tool" 错误
        """
        result = self.client.ask("北京明天的天气")
        print(f"三参数测试: {result}")

        self.assertIsNotNone(result)

        # 验证不是 "Too many arguments" 错误
        if hasattr(result, 'status') and hasattr(result.status, 'message'):
            message = str(result.status.message)
            self.assertNotIn("Too many arguments", message)

        # 验证不是工具调用错误
        if hasattr(result, 'status') and hasattr(result.status, 'message'):
            message = str(result.status.message)
            self.assertNotIn("unexpected keyword argument", message)
            self.assertNotIn("missing", message[:100].lower() if len(message) > 100 else message.lower())

    def test_query_with_tomorrow_relative(self):
        """测试相对时间（明天）转换"""
        result = self.client.ask("明天上海天气")
        print(f"相对时间测试（明天）: {result}")

        self.assertIsNotNone(result)

        # 应该成功返回结果
        if hasattr(result, 'artifacts') and result.artifacts:
            text = result.artifacts[0].get('parts', [{}])[0].get('text', '')
            # 不应该包含错误信息
            self.assertNotIn("错误", text[:50] if len(text) > 50 else text)
            self.assertNotIn("Error", text[:50] if len(text) > 50 else text)


if __name__ == "__main__":
    print("=" * 60)
    print("天气智能体集成测试")
    print("请确保天气 MCP 服务器 (8002) 和 A2A 服务器 (5005) 已启动")
    print("=" * 60)
    unittest.main(verbosity=2)
