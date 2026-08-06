# ============================================================
# MCP 行程服务模块
# 功能：提供行程相关的 MCP（Model Context Protocol）工具接口
# 支持三种业务：租车查询/预订、旅游团查询/报名、保险查询/购买
# 启动命令：python mcp_server/mcp_trip_server.py
# 访问地址：http://127.0.0.1:8003/mcp
#
# 调用流程图：
#
#   AI 智能体（如 Claude）
#        │
#        ▼
#   ┌─────────────────────────────┐
#   │  MCP Server (端口 8003)      │
#   │  create_trip_mcp_server()   │
#   │  FastMCP("TripTools")       │
#   └──────────────┬──────────────┘
#                  │
#        ┌─────────┴─────────┐
#        │                   │
#   查询类工具            预订类工具
#        │                   │
#   ┌────┴────┐         ┌────┴────┐
#   │         │         │         │
#   ▼         ▼         ▼         ▼
# 租车查询  旅游团查询  租车预订  旅游团报名
#   │         │                   │
#   ▼         ▼                   ▼
# MySQL    Milvus              返回预订成功信息
# 查询      语义检索            (模拟返回)
#   │         │
#   │         ▼
#   │    ┌─────────────┐
#   │    │ Qwen API    │
#   │    │ 生成向量     │
#   │    └──────┬──────┘
#   │           ▼
#   │    Milvus 向量相似度搜索
#   │    返回最相似的旅游团
#   │           │
#   └─────┬─────┘
#         ▼
#   JSON 字符串返回给 AI 智能体
#
# 数据源说明：
#   - 租车/保险：从 MySQL 数据库查询（car_rentals / insurances 表）
#   - 旅游团：从 Milvus 向量数据库语义检索（RAG 架构）
#
# 返回格式示例（旅游团查询）：
#   {
#     "status": "success",
#     "data": [
#       {
#         "tour_id": "YN001",
#         "tour_name": "云南丽江大理双飞6日游",
#         "city": "丽江",
#         "days": 6,
#         "price": 3280.0,
#         "similarity": 0.8923
#       }
#     ]
#   }
# ============================================================

from CorpAI.config import Config  # 项目配置
import json  # JSON 处理
from datetime import date, datetime, timedelta  # 时间处理
from decimal import Decimal  # 高精度小数类型
import requests  # HTTP 请求，用于调用 Embedding API（OpenAI 兼容协议）

import mysql.connector  # MySQL 数据库驱动
from pymilvus import connections, Collection  # Milvus 向量数据库客户端

from python_a2a import FastMCP, create_fastapi_app  # MCP 框架：FastMCP 用于定义工具，create_fastapi_app 转为 FastAPI 服务
import uvicorn  # ASGI 服务器，用于运行 FastAPI 应用

from CorpAI.logging import logger  # 日志模块
from CorpAI.utils.format import DateEncoder, default_encoder  # 日期格式化工具

# 加载全局配置对象
conf = Config()

# ============================================================
# Milvus 延迟连接（Lazy Init）
# 真实工程做法：模块加载时不连 Milvus，而是等到第一次调用旅游团查询时才连接。
# 这样即使 Milvus 没启动，服务也能正常起来，租车 / 保险 / 预订工具照常工作；
# 只有旅游团语义搜索会返回"Milvus 暂不可用"的友好提示。
# ============================================================
_milvus_collection = None      # 缓存已加载的 Collection，避免重复 load
_milvus_connect_attempted = False  # 标记是否已尝试连接过（避免每次查询都重试）


def _ensure_milvus_collection():
    """
    确保 Milvus 已连接且旅游团 Collection 已加载到内存。

    返回值：
        Collection 对象（成功）或 None（连接失败）

    工作流程：
        1. 若已缓存，直接返回
        2. 若已尝试过且失败过，直接返回 None
        3. 否则尝试连接 Milvus，加载 Collection，缓存并返回
    """
    global _milvus_collection, _milvus_connect_attempted

    # 命中缓存
    if _milvus_collection is not None:
        return _milvus_collection
    # 已尝试过且失败，不再重试（防止每次查询都耗时阻塞）
    if _milvus_connect_attempted and _milvus_collection is None:
        return None

    _milvus_connect_attempted = True
    try:
        connections.connect(alias="default", host=conf.milvus_host, port=conf.milvus_port)
        coll = Collection(conf.tour_group_collection)
        coll.load()
        _milvus_collection = coll
        logger.info(f"Milvus 已连接，collection='{conf.tour_group_collection}' 已加载")
        return coll
    except Exception as e:
        logger.error(
            f"Milvus 连接失败（host={conf.milvus_host}:{conf.milvus_port}）: {e}。"
            f"旅游团语义搜索将不可用，其他工具不受影响。"
        )
        return None


# ==================== 向量检索辅助函数 ====================

def get_embedding(text: str, type: str = None) -> list:
    """
    调用 MiniMax Embedding API 将文本转换为向量

    用途：将用户的自然语言查询转换为 conf.embedding_dim 维向量，用于 Milvus 语义搜索
    MiniMax 的 /v1/embeddings 不是 OpenAI 兼容格式:
      - 入参字段是 texts（不是 input）
      - 必须带 type: query(检索时) / db(入库时)
      - 返回字段是 vectors（不是 data[].embedding）

    参数：
        text (str): 待向量化的文本，如 "想看雪山的地方"
        type (str, optional): embedding 类型提示。None 时用 conf.embedding_type_query(默认 query)

    返回值：
        list: conf.embedding_dim 维浮点数向量

    异常：
        ValueError: 入参为空或 API Key 未配置时抛出
        RuntimeError: 重试 3 次后仍请求失败时抛出
    """
    import requests

    # ---- 入参校验 ----
    if not text or not text.strip():
        raise ValueError("get_embedding 入参 text 不能为空")

    if not conf.embedding_api_key:
        raise ValueError(
            "EMBEDDING_API_KEY 未配置，请在 .env 中设置 "
            "EMBEDDING_API_KEY=sk-xxxxx（或配置 API_KEY 作为 fallback）"
        )

    # MiniMax 的 type 参数影响语义检索质量
    embed_type = type or conf.embedding_type_query

    # ---- 构造请求 ----
    headers = {
        "Authorization": f"Bearer {conf.embedding_api_key}",  # Bearer Token 认证
        "Content-Type": "application/json"
    }
    payload = {
        "model": conf.embedding_model_name,   # 默认 embo-01
        "texts": [text.strip()],              # MiniMax 原生字段: texts
        "type": embed_type,                   # MiniMax 原生字段: db / query
    }

    # ---- 重试机制：最多尝试 3 次，间隔递增（1s, 2s, 3s） ----
    max_retries = 3
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"调用 Embedding API（第 {attempt}/{max_retries} 次）: text='{text[:50]}...'")
            response = requests.post(conf.embedding_url, headers=headers, json=payload, timeout=30)

            # HTTP 状态码校验：非 200 主动抛异常，触发重试
            if response.status_code != 200:
                raise RuntimeError(f"Embedding API 返回 HTTP {response.status_code}: {response.text[:200]}")

            # ---- 响应结构校验 ----
            result = response.json()
            # MiniMax 业务错误放在 base_resp.status_code != 0
            base_resp = result.get("base_resp", {})
            if base_resp.get("status_code", 0) != 0:
                raise RuntimeError(
                    f"Embedding API 业务错误: {base_resp.get('status_msg', result)}"
                )

            # MiniMax 原生格式: 返回 vectors 字段(不是 OpenAI 的 data[].embedding)
            vectors = result.get("vectors")
            if not vectors or not isinstance(vectors, list) or len(vectors) == 0:
                raise RuntimeError(f"Embedding API 响应缺少 vectors 字段: {result}")

            embedding = vectors[0]
            if not isinstance(embedding, list) or len(embedding) == 0:
                raise RuntimeError(f"Embedding API 返回的向量格式异常: {result}")

            logger.info(f"Embedding API 调用成功，向量维度: {len(embedding)}")
            return embedding

        except requests.exceptions.Timeout:
            last_error = "请求超时（30s）"
            logger.warning(f"Embedding API 第 {attempt} 次超时")
        except requests.exceptions.ConnectionError as e:
            last_error = f"网络连接失败: {e}"
            logger.warning(f"Embedding API 第 {attempt} 次连接失败")
        except (RuntimeError, KeyError, ValueError) as e:
            # 响应解析失败或业务错误，不需要重试（API 侧不会自动恢复）
            raise RuntimeError(f"Embedding API 调用失败: {e}") from e
        except Exception as e:
            last_error = f"未知异常: {e}"
            logger.warning(f"Embedding API 第 {attempt} 次未知异常: {e}")

        # 重试间隔递增，避免频繁请求
        if attempt < max_retries:
            import time
            time.sleep(attempt)

    # 全部重试耗尽，抛出最终错误
    raise RuntimeError(f"Embedding API 调用失败（重试 {max_retries} 次后）: {last_error}")


def search_tour_groups_in_milvus(query_text: str, city: str = None, limit: int = 5) -> list:
    """
    在 Milvus 向量数据库中进行语义搜索，找到最匹配的旅游团

    参数：
        query_text (str): 用户查询描述，如 "想看雪山的地方"、"适合亲子游的短途旅行"
        city (str, optional): 城市过滤条件，如 "成都"、"丽江"；None 表示不过滤
        limit (int): 返回结果数量上限，默认 5

    返回值：
        list: 旅游团信息列表，每个元素包含 tour_id, tour_name, city, days, price, similarity

    工作流程：
        1. 懒加载：检查/建立 Milvus 连接和 Collection
        2. 将查询文本转换为向量（调用 get_embedding）
        3. 执行向量相似度搜索（COSINE 距离）
        4. 提取并返回匹配的旅游团信息

    异常：
        RuntimeError: 当 Milvus 服务不可用时抛出，由上层 query_tour_group 转为友好 JSON 错误
    """
    # 步骤 1：懒加载 Milvus 连接与 Collection
    coll = _ensure_milvus_collection()
    if coll is None:
        raise RuntimeError(
            "Milvus 向量数据库未运行或无法连接，旅游团语义搜索暂不可用。"
            f"请检查服务 {conf.milvus_host}:{conf.milvus_port} 是否启动。"
        )

    # 步骤 2-3：将查询文本转为向量，执行相似度搜索
    results = coll.search(
        data=[get_embedding(query_text)],  # 查询向量
        anns_field="embedding",             # 向量字段名
        param={"metric_type": "COSINE", "params": {"nprobe": 10}},  # 相似度度量：余弦相似度
        limit=limit,                         # 返回前 N 个最相似结果
        output_fields=["tour_id", "tour_name", "city", "days", "price",
                       "total_seats", "remaining_seats", "agency", "rating",
                       "departure_dates", "highlights"],  # 需要返回的标量字段
        expr=f'city == "{city}"' if city else None  # 城市过滤条件（可选）
    )

    # 步骤 4：提取搜索结果，组装为字典列表
    tour_list = []
    for hits in results:
        for hit in hits:
            tour_list.append({
                "tour_id": hit.entity.get("tour_id"),       # 团号
                "tour_name": hit.entity.get("tour_name"),   # 团名
                "city": hit.entity.get("city"),             # 城市
                "days": hit.entity.get("days"),             # 天数
                "price": hit.entity.get("price"),           # 价格
                "similarity": round(hit.distance, 4),       # 相似度分数（0~1，越接近 1 越相似）
            })
    return tour_list


# ==================== 行程服务类 ====================
class TripService:
    """
    行程查询与预订服务类

    混合数据源架构：
    ┌─────────────────────────────────────────────────┐
    │              TripService                         │
    │                                                  │
    │  查询类方法                  预订类方法            │
    │  ├─ query_car_rental()      ├─ order_car_rental()│
    │  ├─ query_tour_group()      ├─ order_tour_group()│
    │  └─ query_insurance()       └─ order_insurance() │
    │        │                        │                │
    │        ▼                        ▼                │
    │   ┌─────────┐  ┌─────────┐   返回预订成功信息     │
    │   │ MySQL   │  │ Milvus  │   (模拟返回，未写库)   │
    │   │ 租车表   │  │ 旅游团   │                      │
    │   │ 保险表   │  │ 向量检索 │                      │
    │   └─────────┘  └─────────┘                      │
    └─────────────────────────────────────────────────┘

    数据源说明：
    - 租车/保险：从 MySQL 数据库查询（car_rentals / insurances 表）
    - 旅游团：从 Milvus 向量数据库语义检索（RAG 架构，基于 OpenAI 兼容 Embedding）
    """

    def __init__(self):
        """
        初始化方法：建立 MySQL 数据库连接

        连接配置从 config.py 的 Config 类读取：
        - host: 数据库主机地址
        - user: 数据库用户名
        - password: 数据库密码
        - database: 数据库名称
        """
        # 建立 MySQL 数据库连接（单连接模式，非连接池）
        self.conn = mysql.connector.connect(
            host=conf.host,
            user=conf.user,
            password=conf.password,
            database=conf.database
        )

    def _execute_query(self, sql: str, params: list = None) -> str:
        """
        执行 SQL 查询的通用方法，返回 JSON 格式的结果

        参数：
            sql (str): SQL 查询语句，使用 %s 占位符（参数化查询，防止 SQL 注入）
            params (list): SQL 参数列表，按顺序填充 %s 占位符

        返回值：
            str: JSON 字符串，包含三种可能的结构：
                - {"status": "success", "data": [...]}       查询到数据
                - {"status": "no_data", "message": "..."}    无匹配数据
                - {"status": "error", "message": "..."}      SQL 执行异常

        工作流程：
            1. 创建游标（dictionary=True 使结果以字典形式返回）
            2. 执行参数化查询
            3. 获取所有结果
            4. 转换特殊类型（date/datetime/Decimal）为可序列化格式
            5. 序列化为 JSON 字符串并返回
        """
        try:
            # 每次执行前 ping 一下 MySQL，断线自动重连
            # 解决 trip MCP 服务长期运行后空闲连接被服务端 wait_timeout 关掉的问题
            try:
                self.conn.ping(reconnect=True, attempts=3, delay=1)
            except Exception as ping_err:
                logger.warning(f"MySQL ping 失败，尝试重建连接: {ping_err}")
                self.conn = mysql.connector.connect(
                    host=conf.host, user=conf.user,
                    password=conf.password, database=conf.database
                )

            # 创建游标，dictionary=True 使结果以字典列表形式返回（而非元组）
            cursor = self.conn.cursor(dictionary=True)
            # 执行参数化查询 —— params 中的值会自动转义，防止 SQL 注入
            cursor.execute(sql, params or [])
            results = cursor.fetchall()
            cursor.close()

            # 处理特殊类型（日期、Decimal 等）—— 这些类型无法直接 JSON 序列化
            for result in results:
                for key, value in result.items():
                    if isinstance(value, (date, datetime, timedelta, Decimal)):
                        result[key] = default_encoder(value)  # 转为字符串

            # 根据是否有数据返回不同的 JSON 结构
            if results:
                response = {"status": "success", "data": results}
            else:
                response = {"status": "no_data", "message": "未找到行程数据，请确认查询条件。"}

            # ensure_ascii=False 保证中文正常显示而非 Unicode 转义
            return json.dumps(response, cls=DateEncoder, ensure_ascii=False)

        except Exception as e:
            # 记录错误日志并返回错误 JSON
            logger.error(f"行程查询错误: {str(e)}")
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

    # ========== 租车查询（MySQL） ==========

    def query_car_rental(self, pickup_city: str, return_city: str, date: str, car_type: str = None) -> str:
        """
        查询租车信息（从 MySQL car_rentals 表查询）

        参数：
            pickup_city (str): 取车城市，如 "成都"
            return_city (str): 还车城市，如 "成都"（支持异地还车）
            date (str): 取车日期，格式 "YYYY-MM-DD"
            car_type (str, optional): 车型过滤，如 "经济型"、"SUV"、"豪华型"、"MPV"

        返回值：
            str: JSON 字符串，包含租车公司信息、车型、价格、可用数量等

        SQL 说明：
            - 基础条件：取车城市 + 还车城市 + 取车日期
            - 可选条件：车型类型
            - 返回字段：公司、车型、价格/天、可用数量、变速箱、座位数、押金
        """
        logger.info(f"查询租车: {pickup_city} -> {return_city}, {date}, {car_type}")
        # 基础 SQL：按取车城市、还车城市、取车日期查询
        sql = ("SELECT id, company, pickup_city, return_city, pickup_date, car_type, "
               "car_model, price_per_day, total_available, transmission, seats, deposit "
               "FROM car_rentals "
               "WHERE pickup_city = %s AND return_city = %s AND pickup_date = %s")
        params = [pickup_city, return_city, date]
        # 如果指定了车型，追加过滤条件
        if car_type:
            sql += " AND car_type = %s"
            params.append(car_type)
        return self._execute_query(sql, params)

    # ========== 旅游团查询（Milvus RAG） ==========

    def query_tour_group(self, query_text: str, city: str = None) -> str:
        """
        查询旅游团信息（从 Milvus 向量数据库进行语义检索）

        这是 RAG（Retrieval-Augmented Generation）架构的核心方法：
        用户的自然语言查询 → Embedding API（OpenAI 兼容）→ 向量 → Milvus 相似度搜索 → 返回最相似的旅游团

        参数：
            query_text (str): 用户查询描述，如 "想看雪山的地方"、"适合亲子游的短途旅行"
            city (str, optional): 城市过滤条件，如 "成都"、"丽江"；None 表示不过滤

        返回值：
            str: JSON 字符串，包含匹配的旅游团列表（最多 5 个），每个旅游团包含：
                - tour_id: 团号
                - tour_name: 团名
                - city: 城市
                - days: 天数
                - price: 价格
                - similarity: 相似度分数（0~1）

        工作流程：
            1. 记录日志
            2. 调用 search_tour_groups_in_milvus() 执行向量搜索
            3. 根据结果返回 success / no_data / error 状态
        """
        logger.info(f"查询旅游团: query='{query_text}', city='{city}'")
        try:
            # 调用 Milvus 语义搜索函数，返回最相似的前 5 个旅游团
            tour_list = search_tour_groups_in_milvus(query_text, city, limit=5)

            if tour_list:
                # 查询成功，返回匹配的旅游团列表
                return json.dumps({"status": "success", "data": tour_list}, ensure_ascii=False)
            else:
                # 无匹配结果，给出友好提示
                return json.dumps({
                    "status": "no_data",
                    "message": f"未找到匹配的旅游团。{'请确认城市名称，' if city else ''}或尝试其他搜索条件。"
                }, ensure_ascii=False)

        except Exception as e:
            # 异常处理：记录日志并返回错误信息
            logger.error(f"旅游团 RAG 查询错误: {str(e)}")
            return json.dumps({"status": "error", "message": f"旅游团查询出错：{str(e)}"}, ensure_ascii=False)

    # ========== 保险查询（MySQL） ==========

    def query_insurance(self, insurance_type: str = None) -> str:
        """
        查询旅行保险产品信息（从 MySQL insurances 表查询）

        参数：
            insurance_type (str, optional): 保险类型过滤，可选值：
                - "综合型"：综合保障，覆盖多种风险
                - "意外型"：专注意外伤害保障
                - "医疗型"：专注医疗保障
                - "境外型"：专为境外旅行设计
                None 表示查询所有类型

        返回值：
            str: JSON 字符串，包含保险产品信息列表，每个产品包含：
                - insurance_type: 保险类型
                - name: 产品名称
                - company: 保险公司
                - coverage: 保障范围说明
                - price: 价格（元/份）
                - duration_days: 保障天数
                - max_coverage: 最高赔付金额
                - medical_coverage: 医疗保障额度
                - baggage_coverage: 行李保障额度
                - flight_delay: 是否包含航班延误
        """
        logger.info(f"查询保险: {insurance_type}")
        # 基础 SQL：查询所有保险产品
        sql = ("SELECT id, insurance_type, name, company, coverage, price, "
               "duration_days, max_coverage, medical_coverage, baggage_coverage, flight_delay "
               "FROM insurances")
        params = []
        # 如果指定了保险类型，追加 WHERE 条件
        if insurance_type:
            sql += " WHERE insurance_type = %s"
            params.append(insurance_type)
        return self._execute_query(sql, params)

    # ========== 预订方法（演示环境：仅模拟返回，未实际写入数据库） ==========

    def order_car_rental(self, date: str, car_type: str, number: int) -> str:
        """
        预订租车（模拟方法）

        参数：
            date (str): 租车日期，格式 "YYYY-MM-DD"
            car_type (str): 车型，如 "经济型"、"SUV"
            number (int): 租车数量

        返回值：
            str: 预订成功的提示文本

        注意：当前为演示环境，仅返回成功提示，未实际写入数据库
        """
        logger.info(f"预订租车: {date}, {car_type}, {number}辆")
        return f"恭喜，租车预订成功！日期：{date}，车型：{car_type}，数量：{number}辆。"

    def order_tour_group(self, date: str, tour_name: str, number: int) -> str:
        """
        报名旅游团（模拟方法）

        参数：
            date (str): 出发日期，格式 "YYYY-MM-DD"
            tour_name (str): 旅游团名称（需与查询结果中的团名一致）
            number (int): 报名人数

        返回值：
            str: 报名成功的提示文本

        注意：当前为演示环境，仅返回成功提示，未实际写入数据库
        """
        logger.info(f"报名旅游团: {date}, {tour_name}, {number}人")
        return f"恭喜，旅游团报名成功！团名：{tour_name}，日期：{date}，人数：{number}人。"

    def order_insurance(self, insurance_type: str, date: str, number: int) -> str:
        """
        购买旅行保险（模拟方法）

        参数：
            insurance_type (str): 保险类型，如 "综合型"、"意外型"
            date (str): 生效日期，格式 "YYYY-MM-DD"
            number (int): 购买份数

        返回值：
            str: 购买成功的提示文本

        注意：当前为演示环境，仅返回成功提示，未实际写入数据库
        """
        logger.info(f"购买保险: {insurance_type}, {date}, {number}份")
        return f"恭喜，旅行保险购买成功！类型：{insurance_type}，日期：{date}，份数：{number}份。"


 # ========== MCP 服务器创建与启动 ==========

def create_trip_mcp_server():
    """
    创建并启动行程管家 MCP 服务器

    工作流程：
        1. 创建 FastMCP 实例（工具容器）
        2. 实例化 TripService（业务逻辑层）
        3. 注册查询类工具（租车、旅游团、保险）
        4. 注册预订类工具（租车预订、旅游团报名、保险购买）
        5. 将 FastMCP 转为 FastAPI 应用
        6. 使用 uvicorn 启动 HTTP 服务

    注册的工具列表：
        查询类：
            - query_car_rental: 查询租车信息
            - query_tour_group: 查询旅游团（语义搜索）
            - query_insurance: 查询旅行保险
        预订类：
            - order_car_rental: 预订租车
            - order_tour_group: 报名旅游团
            - order_insurance: 购买旅行保险
    """
    # 步骤 1：创建 FastMCP 实例，相当于定义一个工具服务
    trip_mcp = FastMCP(name="TripTools")  # 工具服务名称，AI 调用时会看到这个名称

    # 步骤 2：实例化业务逻辑服务类
    service = TripService()

    # ========== 注册查询类工具 ==========
    # 使用 @tool 装饰器将函数注册为 MCP 工具
    # name: 工具的唯一标识，AI 通过这个名字调用
    # description: 工具说明，AI 会阅读这段描述来判断是否使用该工具

    @trip_mcp.tool(
        name="query_car_rental",
        description="查询租车信息，参数：pickup_city(取车城市), return_city(还车城市), date(日期，格式YYYY-MM-DD), car_type(车型类型，可选：经济型/SUV/豪华型/MPV)"
    )
    def query_car_rental(pickup_city: str, return_city: str, date: str, car_type: str = None) -> str:
        """MCP 工具入口：查询租车信息"""
        return service.query_car_rental(pickup_city, return_city, date, car_type)

    @trip_mcp.tool(
        name="query_tour_group",
        description="查询旅游团信息（语义搜索），参数：query_text(查询描述，如'想看雪山的地方')，city(城市过滤，可选)"
    )
    def query_tour_group(query_text: str, city: str = None) -> str:
        """MCP 工具入口：查询旅游团（基于 Milvus 向量语义搜索）"""
        return service.query_tour_group(query_text, city)

    @trip_mcp.tool(
        name="query_insurance",
        description="查询旅行保险产品，参数：insurance_type(保险类型，可选：综合型/意外型/医疗型/境外型)"
    )
    def query_insurance(insurance_type: str = None) -> str:
        """MCP 工具入口：查询旅行保险"""
        return service.query_insurance(insurance_type)

    # ========== 注册预订类工具 ==========

    @trip_mcp.tool(
        name="order_car_rental",
        description="根据日期、车型和数量预订租车服务。参数：date(租车日期，格式YYYY-MM-DD), car_type(车型，如经济型/SUV/豪华型/MPV), number(租车数量)"
    )
    def order_car_rental(date: str, car_type: str, number: int) -> str:
        """MCP 工具入口：预订租车"""
        logger.info(f"正在预订租车: {date}, {car_type}, {number}辆")
        return service.order_car_rental(date, car_type, number)

    @trip_mcp.tool(
        name="order_tour_group",
        description="根据出发日期、旅游团名称和人数报名旅游团。参数：date(出发日期，格式YYYY-MM-DD), tour_name(旅游团名称，需与查询结果中的团名一致), number(报名人数)"
    )
    def order_tour_group(date: str, tour_name: str, number: int) -> str:
        """MCP 工具入口：报名旅游团"""
        logger.info(f"正在报名旅游团: {date}, {tour_name}, {number}人")
        return service.order_tour_group(date, tour_name, number)

    @trip_mcp.tool(
        name="order_insurance",
        description="根据保险类型、生效日期和份数购买旅行保险。参数：insurance_type(保险类型，如综合型/意外型/医疗型/境外型), date(生效日期，格式YYYY-MM-DD), number(购买份数)"
    )
    def order_insurance(insurance_type: str, date: str, number: int) -> str:
        """MCP 工具入口：购买旅行保险"""
        logger.info(f"正在购买保险: {insurance_type}, {date}, {number}份")
        return service.order_insurance(insurance_type, date, number)

    # 步骤 5-6：将 FastMCP 转为 FastAPI 应用，并使用 uvicorn 启动 HTTP 服务
    app = create_fastapi_app(mcp_server=trip_mcp)
    uvicorn.run(app, host="0.0.0.0", port=8003)  # 端口 8003，允许外部访问


# 入口点：直接运行此文件时启动 MCP 服务器
if __name__ == '__main__':
    create_trip_mcp_server()