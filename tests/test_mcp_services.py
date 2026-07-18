"""
MCP 服务集成测试模块

测试内容：
1. WeatherService - 天气查询服务
2. TicketService - 票务服务（火车票、机票、演唱会）
3. TripService - 行程服务（租车、旅游团、保险）

前置条件：
- MySQL 数据库服务运行中，包含 weather_data, train_tickets, flight_tickets,
  concert_tickets, car_rentals, insurances 表
- Milvus 向量数据库运行中（用于旅游团查询）

注意：数据库中的测试数据日期为 2026-08-01

运行方式：
    cd SmartVoyage
    python -m tests.test_mcp_services
"""

import unittest
import json
import sys
import os
from datetime import date, datetime, timedelta
from decimal import Decimal

# 确保能导入 SmartVoyage 模块（项目根目录在 ..）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestWeatherService(unittest.TestCase):
    """测试天气查询服务"""

    @classmethod
    def setUpClass(cls):
        from SmartVoyage.mcp_server.mcp_weather_server import WeatherService
        cls.service = WeatherService()

    def test_query_weather_single_day(self):
        """测试单天天气查询"""
        result = self.service.query_weather("北京", "2026-07-10", "2026-07-10")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        first = parsed["data"][0]
        self.assertEqual(first["city"], "北京")
        self.assertEqual(first["fx_date"], "2026-07-10")

    def test_query_weather_date_range(self):
        """测试日期范围天气查询"""
        result = self.service.query_weather("北京", "2026-07-10", "2026-07-14")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(len(parsed["data"]), 5)

    def test_query_weather_chengdu(self):
        """测试成都天气查询"""
        result = self.service.query_weather("成都", "2026-07-15", "2026-07-15")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        self.assertEqual(parsed["data"][0]["city"], "成都")

    def test_query_weather_no_data(self):
        """测试无数据情况"""
        result = self.service.query_weather("火星", "2026-07-15", "2026-07-15")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "no_data")

    def test_weather_result_fields(self):
        """验证天气结果包含所有必要字段"""
        result = self.service.query_weather("北京", "2026-07-10", "2026-07-10")
        parsed = json.loads(result)
        first = parsed["data"][0]
        required_fields = ["city", "fx_date", "temp_max", "temp_min",
                          "text_day", "text_night", "humidity",
                          "wind_dir_day", "wind_scale_day", "precip"]
        for field in required_fields:
            self.assertIn(field, first, f"缺少必要字段: {field}")


class TestTicketService(unittest.TestCase):
    """测试票务服务"""

    @classmethod
    def setUpClass(cls):
        from SmartVoyage.mcp_server.mcp_ticket_server import TicketService
        cls.service = TicketService()

    # ========== 火车票测试 ==========
    def test_query_train_basic(self):
        """测试火车票基本查询"""
        result = self.service.query_train("北京", "成都", "2026-08-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        first = parsed["data"][0]
        self.assertEqual(first["departure_city"], "北京")
        self.assertEqual(first["arrival_city"], "成都")

    def test_query_train_with_seat_type(self):
        """测试按座位类型筛选火车票"""
        result = self.service.query_train("北京", "成都", "2026-08-01", "二等座")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        for item in parsed["data"]:
            self.assertEqual(item["seat_type"], "二等座")

    def test_query_train_no_data(self):
        """测试无火车票数据"""
        result = self.service.query_train("北京", "上海", "2026-08-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "no_data")

    def test_train_result_fields(self):
        """验证火车票结果包含所有必要字段"""
        result = self.service.query_train("北京", "成都", "2026-08-01")
        parsed = json.loads(result)
        if parsed["data"]:
            first = parsed["data"][0]
            required_fields = ["departure_city", "arrival_city", "train_number",
                              "seat_type", "price", "remaining_seats"]
            for field in required_fields:
                self.assertIn(field, first, f"缺少必要字段: {field}")

    # ========== 机票测试 ==========
    def test_query_flight_basic(self):
        """测试机票基本查询"""
        result = self.service.query_flight("北京", "成都", "2026-08-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        first = parsed["data"][0]
        self.assertEqual(first["departure_city"], "北京")
        self.assertEqual(first["arrival_city"], "成都")

    def test_query_flight_with_cabin_type(self):
        """测试按舱位类型筛选机票"""
        result = self.service.query_flight("北京", "成都", "2026-08-01", "头等舱")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        for item in parsed["data"]:
            self.assertEqual(item["cabin_type"], "头等舱")

    def test_query_flight_no_data(self):
        """测试无机票数据"""
        result = self.service.query_flight("拉萨", "三亚", "2026-08-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "no_data")

    def test_flight_result_fields(self):
        """验证机票结果包含所有必要字段"""
        result = self.service.query_flight("北京", "成都", "2026-08-01")
        parsed = json.loads(result)
        if parsed["data"]:
            first = parsed["data"][0]
            required_fields = ["departure_city", "arrival_city", "flight_number",
                              "cabin_type", "price", "remaining_seats"]
            for field in required_fields:
                self.assertIn(field, first, f"缺少必要字段: {field}")

    # ========== 演唱会票测试 ==========
    def test_query_concert_xuezhiqian(self):
        """测试薛之谦演唱会查询"""
        result = self.service.query_concert("成都", "薛之谦", "2026-08-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        first = parsed["data"][0]
        self.assertEqual(first["artist"], "薛之谦")
        self.assertEqual(first["city"], "成都")

    def test_query_concert_dengziqi(self):
        """测试邓紫棋演唱会查询"""
        result = self.service.query_concert("成都", "邓紫棋", "2026-08-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        self.assertEqual(parsed["data"][0]["venue"], "凤凰山体育公园综合体育馆")

    def test_query_concert_no_data(self):
        """测试无演唱会数据"""
        result = self.service.query_concert("成都", "周杰伦", "2026-08-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "no_data")

    def test_concert_result_fields(self):
        """验证演唱会结果包含所有必要字段"""
        result = self.service.query_concert("成都", "薛之谦", "2026-08-01")
        parsed = json.loads(result)
        if parsed["data"]:
            first = parsed["data"][0]
            required_fields = ["artist", "city", "venue", "ticket_type",
                              "price", "remaining_seats"]
            for field in required_fields:
                self.assertIn(field, first, f"缺少必要字段: {field}")

    # ========== 订单模拟测试 ==========
    def test_order_train_mock(self):
        """测试火车票订单（模拟）"""
        result = self.service.order_train("2026-08-01", "G1234", "二等座", 1)
        self.assertIn("预定成功", result)

    def test_order_flight_mock(self):
        """测试机票订单（模拟）"""
        result = self.service.order_flight("2026-08-01", "CA1234", "经济舱", 1)
        self.assertIn("预定成功", result)

    def test_order_concert_mock(self):
        """测试演唱会订单（模拟）"""
        result = self.service.order_concert("2026-08-01", "薛之谦", "成都体育中心", "VIP", 2)
        self.assertIn("预定成功", result)


class TestTripService(unittest.TestCase):
    """测试行程服务"""

    @classmethod
    def setUpClass(cls):
        from SmartVoyage.mcp_server.mcp_trip_server import TripService
        cls.service = TripService()

    # ========== 租车测试 ==========
    def test_query_car_rental_basic(self):
        """测试租车基本查询"""
        result = self.service.query_car_rental("成都", "成都", "2026-08-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        first = parsed["data"][0]
        self.assertEqual(first["pickup_city"], "成都")
        self.assertEqual(first["return_city"], "成都")

    def test_query_car_rental_with_type(self):
        """测试按车型筛选租车"""
        result = self.service.query_car_rental("成都", "成都", "2026-08-01", "SUV")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        for item in parsed["data"]:
            self.assertEqual(item["car_type"], "SUV")

    def test_query_car_rental_no_data(self):
        """测试无租车数据"""
        result = self.service.query_car_rental("北京", "北京", "2026-08-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "no_data")

    def test_car_rental_result_fields(self):
        """验证租车结果包含所有必要字段"""
        result = self.service.query_car_rental("成都", "成都", "2026-08-01")
        parsed = json.loads(result)
        if parsed["data"]:
            first = parsed["data"][0]
            required_fields = ["company", "car_type", "car_model",
                              "price_per_day", "total_available"]
            for field in required_fields:
                self.assertIn(field, first, f"缺少必要字段: {field}")

    # ========== 旅游团测试（Milvus RAG - 需要 Embedding API） ==========
    def test_query_tour_group_semantic(self):
        """测试旅游团语义搜索"""
        result = self.service.query_tour_group("想看雪山的地方")
        parsed = json.loads(result)
        # Milvus RAG 需要有效的 DashScope API Key
        # 如果返回 error 说明 API Key 无效，跳过此测试
        if parsed.get("status") == "error" and "API key" in parsed.get("message", ""):
            self.skipTest("Embedding API Key 无效，跳过 Milvus RAG 测试")
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)

    def test_query_tour_group_with_city(self):
        """测试带城市过滤的旅游团搜索"""
        result = self.service.query_tour_group("美食之旅", city="丽江")
        parsed = json.loads(result)
        if parsed.get("status") == "error" and "API key" in parsed.get("message", ""):
            self.skipTest("Embedding API Key 无效，跳过 Milvus RAG 测试")
        self.assertEqual(parsed["status"], "success")
        for item in parsed["data"]:
            self.assertEqual(item["city"], "丽江")

    def test_tour_group_result_fields(self):
        """验证旅游团结果包含所有必要字段"""
        result = self.service.query_tour_group("亲子游")
        parsed = json.loads(result)
        if parsed.get("status") == "error" and "API key" in parsed.get("message", ""):
            self.skipTest("Embedding API Key 无效，跳过 Milvus RAG 测试")
        if parsed["data"]:
            first = parsed["data"][0]
            required_fields = ["tour_id", "tour_name", "city", "days", "price", "similarity"]
            for field in required_fields:
                self.assertIn(field, first, f"缺少必要字段: {field}")

    # ========== 保险测试 ==========
    def test_query_insurance_all(self):
        """测试查询全部保险"""
        result = self.service.query_insurance()
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)

    def test_query_insurance_by_type(self):
        """测试按类型筛选保险"""
        result = self.service.query_insurance("综合型")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        for item in parsed["data"]:
            self.assertEqual(item["insurance_type"], "综合型")

    def test_query_insurance_jingwai(self):
        """测试境外型保险"""
        result = self.service.query_insurance("境外型")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        for item in parsed["data"]:
            self.assertEqual(item["insurance_type"], "境外型")

    def test_insurance_result_fields(self):
        """验证保险结果包含所有必要字段"""
        result = self.service.query_insurance()
        parsed = json.loads(result)
        if parsed["data"]:
            first = parsed["data"][0]
            required_fields = ["insurance_type", "name", "company",
                              "price", "duration_days", "max_coverage"]
            for field in required_fields:
                self.assertIn(field, first, f"缺少必要字段: {field}")

    # ========== 订单模拟测试 ==========
    def test_order_car_rental_mock(self):
        """测试租车订单（模拟）"""
        result = self.service.order_car_rental("2026-08-01", "SUV", 1)
        self.assertIn("预订成功", result)

    def test_order_tour_group_mock(self):
        """测试旅游团报名（模拟）"""
        result = self.service.order_tour_group("2026-08-01", "丽江三日游", 2)
        self.assertIn("报名成功", result)

    def test_order_insurance_mock(self):
        """测试保险购买（模拟）"""
        result = self.service.order_insurance("综合型", "2026-08-01", 1)
        self.assertIn("购买成功", result)


class TestMCPIntegration(unittest.TestCase):
    """MCP 服务集成测试 - 测试跨服务协作"""

    def test_all_services_return_valid_json(self):
        """验证所有服务返回有效的 JSON 格式"""
        from SmartVoyage.mcp_server.mcp_weather_server import WeatherService
        from SmartVoyage.mcp_server.mcp_ticket_server import TicketService
        from SmartVoyage.mcp_server.mcp_trip_server import TripService

        services = [
            ("WeatherService", WeatherService(), lambda s: s.query_weather("北京", "2026-07-10", "2026-07-10")),
            ("TicketService-Train", TicketService(), lambda s: s.query_train("北京", "成都", "2026-08-01")),
            ("TripService-Car", TripService(), lambda s: s.query_car_rental("成都", "成都", "2026-08-01")),
        ]

        for name, service, query_func in services:
            result = query_func(service)
            # 验证返回的是有效 JSON
            try:
                parsed = json.loads(result)
                self.assertIn("status", parsed, f"{name}: 返回结果缺少 status 字段")
                print(f"✓ {name} 返回有效 JSON: status={parsed['status']}")
            except json.JSONDecodeError as e:
                self.fail(f"{name}: 返回结果不是有效 JSON: {e}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
