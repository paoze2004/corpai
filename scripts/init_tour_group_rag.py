"""
需求：初始化旅游团 RAG 系统
思路：
1. 定义旅游团数据（城市、线路名称、天数、价格、行程亮点等）
2. 使用 Embedding API（OpenAI 兼容协议）将每团行程亮点生成向量
3. 在本地 Milvus 中创建 Collection 并插入数据
4. 支持后续通过语义搜索匹配用户意图的旅游团
"""

import json
import os
import sys
import requests
# 强制 stdout 使用 UTF-8，避免 Windows GBK 终端打不出中文 / ¥ 等符号
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from pymilvus import connections, Collection, CollectionSchema, FieldSchema, DataType, utility

# 脚本位于 scripts/，需把项目根加入 sys.path 才能 import CorpAI.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ==================== Embedding API（MiniMax 原生协议）====================
# MiniMax /v1/embeddings 不是 OpenAI 兼容:入参 texts + type, 返回 vectors
from CorpAI.config import Config
conf = Config()
EMBEDDING_API_KEY = conf.embedding_api_key  # 优先 EMBEDDING_API_KEY,缺省回退到 API_KEY
EMBEDDING_URL = conf.embedding_url
EMBEDDING_MODEL = conf.embedding_model_name
EMBEDDING_TYPE = conf.embedding_type_insert  # 入库用 db


def get_embedding(text: str, type: str = None) -> list:
    """
    调用 MiniMax Embedding API 生成文本向量

    参数：
        text (str): 需要生成向量的文本
        type (str, optional): embedding 类型提示。None 时用 EMBEDDING_TYPE(默认 db)

    返回值：
        list: conf.embedding_dim 维向量

    MiniMax 原生格式:
        - 入参字段 texts(不是 OpenAI 的 input)
        - 必须带 type: db(入库) / query(检索)
        - 返回字段 vectors(不是 OpenAI 的 data[].embedding)
        - 业务错误放在 base_resp.status_code(非 0 = 失败)
    """
    if not EMBEDDING_API_KEY:
        raise ValueError(
            "EMBEDDING_API_KEY 未配置，请在 .env 中设置 "
            "EMBEDDING_API_KEY=sk-xxxxx（缺省时会回退到 LLM 的 API_KEY）"
        )

    headers = {
        "Authorization": f"Bearer {EMBEDDING_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": EMBEDDING_MODEL,
        "texts": [text],          # MiniMax 原生字段
        "type": type or EMBEDDING_TYPE,
    }
    response = requests.post(EMBEDDING_URL, headers=headers, json=payload, timeout=30)
    response.raise_for_status()  # 非 200 直接抛异常,附带状态码和响应体
    result = response.json()
    # 业务错误检查
    base_resp = result.get("base_resp", {})
    if base_resp.get("status_code", 0) != 0:
        raise RuntimeError(f"Embedding API 业务错误: {base_resp.get('status_msg', result)}")
    # 提取向量(MiniMax 原生格式)
    vectors = result.get("vectors")
    if not vectors or not isinstance(vectors, list) or len(vectors) == 0:
        raise RuntimeError(f"Embedding API 响应缺少 vectors 字段: {result}")
    return vectors[0]


# ==================== 旅游团数据 ====================
TOUR_GROUPS = [
    # ========== 云南 ==========
    {
        "tour_id": "YN001",
        "tour_name": "云南丽江大理双飞6日游",
        "city": "丽江",
        "days": 6,
        "price": 3280.00,
        "total_seats": 30,
        "remaining_seats": 12,
        "agency": "云南青旅",
        "rating": 4.8,
        "departure_dates": ["2026-05-28", "2026-06-01", "2026-06-10"],
        "highlights": "含往返机票，全程四星酒店，玉龙雪山+大理古城+洱海环湖+束河古镇，纯玩无购物，赠送丽江千古情演出"
    },
    {
        "tour_id": "YN002",
        "tour_name": "香格里拉秘境5日游",
        "city": "丽江",
        "days": 5,
        "price": 2680.00,
        "total_seats": 25,
        "remaining_seats": 8,
        "agency": "携程旅游",
        "rating": 4.7,
        "departure_dates": ["2026-05-29", "2026-06-03"],
        "highlights": "虎跳峡徒步+普达措国家公园+松赞林寺+梅里雪山日照金山，藏式特色餐食，含氧气瓶和高原保险"
    },
    {
        "tour_id": "YN003",
        "tour_name": "西双版纳热带雨林4日游",
        "city": "西双版纳",
        "days": 4,
        "price": 2180.00,
        "total_seats": 35,
        "remaining_seats": 20,
        "agency": "途牛旅游",
        "rating": 4.6,
        "departure_dates": ["2026-05-31", "2026-06-05"],
        "highlights": "中科院热带植物园+野象谷+曼听公园+傣族园泼水节，住热带雨林主题酒店，含傣族特色餐"
    },
    {
        "tour_id": "YN004",
        "tour_name": "昆明石林+抚仙湖3日游",
        "city": "昆明",
        "days": 3,
        "price": 1280.00,
        "total_seats": 40,
        "remaining_seats": 25,
        "agency": "中国国旅",
        "rating": 4.5,
        "departure_dates": ["2026-05-28", "2026-06-01", "2026-06-08"],
        "highlights": "世界自然遗产石林+抚仙湖环湖+滇池喂海鸥，含昆明市区接送，品尝过桥米线"
    },

    # ========== 四川 ==========
    {
        "tour_id": "SC001",
        "tour_name": "九寨沟黄龙双飞5日游",
        "city": "成都",
        "days": 5,
        "price": 2980.00,
        "total_seats": 30,
        "remaining_seats": 10,
        "agency": "四川青旅",
        "rating": 4.9,
        "departure_dates": ["2026-05-28", "2026-06-02", "2026-06-15"],
        "highlights": "含往返机票，九寨沟全天游览+黄龙五彩池+藏羌风情晚会，全程四星酒店，赠送氧气瓶和高原保险"
    },
    {
        "tour_id": "SC002",
        "tour_name": "稻城亚丁深度7日游",
        "city": "成都",
        "days": 7,
        "price": 3880.00,
        "total_seats": 20,
        "remaining_seats": 6,
        "agency": "马蜂窝旅行",
        "rating": 4.9,
        "departure_dates": ["2026-05-31", "2026-06-10"],
        "highlights": "蓝色星球最后一片净土，稻城亚丁三神山+牛奶海+五色海+新都桥摄影天堂，越野车出行，含专业高山向导"
    },
    {
        "tour_id": "SC003",
        "tour_name": "成都美食文化3日游",
        "city": "成都",
        "days": 3,
        "price": 980.00,
        "total_seats": 45,
        "remaining_seats": 30,
        "agency": "春秋旅游",
        "rating": 4.7,
        "departure_dates": ["2026-05-28", "2026-05-29", "2026-06-01", "2026-06-02"],
        "highlights": "宽窄巷子+锦里+大熊猫基地+都江堰+青城山，全程美食打卡（火锅、串串、担担面、龙抄手），含市区接送"
    },
    {
        "tour_id": "SC004",
        "tour_name": "峨眉山乐山2日游",
        "city": "成都",
        "days": 2,
        "price": 680.00,
        "total_seats": 50,
        "remaining_seats": 35,
        "agency": "携程旅游",
        "rating": 4.6,
        "departure_dates": ["2026-05-28", "2026-05-29", "2026-06-01", "2026-06-02"],
        "highlights": "金顶云海+乐山大佛+峨眉山猴区，含索道票，住山顶酒店可看日出，品尝峨眉山素斋"
    },

    # ========== 北京 ==========
    {
        "tour_id": "BJ001",
        "tour_name": "北京经典5日游",
        "city": "北京",
        "days": 5,
        "price": 2580.00,
        "total_seats": 35,
        "remaining_seats": 15,
        "agency": "北京国旅",
        "rating": 4.8,
        "departure_dates": ["2026-05-28", "2026-06-01", "2026-06-10"],
        "highlights": "故宫+天安门+长城+颐和园+天坛+鸟巢水立方，含故宫讲解器，登长城，住三环内四星酒店，含全聚德烤鸭"
    },
    {
        "tour_id": "BJ002",
        "tour_name": "北京环球影城+故宫4日游",
        "city": "北京",
        "days": 4,
        "price": 3180.00,
        "total_seats": 25,
        "remaining_seats": 8,
        "agency": "中青旅",
        "rating": 4.9,
        "departure_dates": ["2026-05-29", "2026-06-03"],
        "highlights": "环球影城全天通票+故宫深度讲解+恭王府+什刹海，适合亲子游，含环球影城快速通行证"
    },
    {
        "tour_id": "BJ003",
        "tour_name": "北京胡同文化体验2日游",
        "city": "北京",
        "days": 2,
        "price": 780.00,
        "total_seats": 30,
        "remaining_seats": 18,
        "agency": "马蜂窝旅行",
        "rating": 4.7,
        "departure_dates": ["2026-05-28", "2026-05-29", "2026-06-01"],
        "highlights": "南锣鼓巷+胡同自行车游+老北京炸酱面制作体验+京剧欣赏+三里屯夜游，住胡同四合院客栈"
    },

    # ========== 上海 ==========
    {
        "tour_id": "SH001",
        "tour_name": "上海迪士尼+外滩3日游",
        "city": "上海",
        "days": 3,
        "price": 2280.00,
        "total_seats": 30,
        "remaining_seats": 10,
        "agency": "上海青旅",
        "rating": 4.8,
        "departure_dates": ["2026-05-28", "2026-06-01", "2026-06-05"],
        "highlights": "迪士尼全天畅玩含快速票+外滩夜景+豫园+东方明珠+田子坊，住迪士尼主题酒店一晚"
    },
    {
        "tour_id": "SH002",
        "tour_name": "上海+苏州+杭州5日游",
        "city": "上海",
        "days": 5,
        "price": 2980.00,
        "total_seats": 30,
        "remaining_seats": 12,
        "agency": "春秋旅游",
        "rating": 4.7,
        "departure_dates": ["2026-05-31", "2026-06-08"],
        "highlights": "外滩+苏州园林+拙政园+杭州西湖+灵隐寺+乌镇水乡，含高铁票，全程四星酒店，品西湖醋鱼和松鼠桂鱼"
    },

    # ========== 海南 ==========
    {
        "tour_id": "HN001",
        "tour_name": "三亚亚龙湾5日度假游",
        "city": "三亚",
        "days": 5,
        "price": 4280.00,
        "total_seats": 25,
        "remaining_seats": 8,
        "agency": "携程旅游",
        "rating": 4.9,
        "departure_dates": ["2026-05-28", "2026-06-01", "2026-06-15"],
        "highlights": "含往返机票，亚龙湾五星级海景酒店，蜈支洲岛潜水+天涯海角+南山寺+热带天堂森林公园，海鲜大餐"
    },
    {
        "tour_id": "HN002",
        "tour_name": "海口+文昌+琼海4日游",
        "city": "海口",
        "days": 4,
        "price": 1980.00,
        "total_seats": 35,
        "remaining_seats": 22,
        "agency": "海南青旅",
        "rating": 4.5,
        "departure_dates": ["2026-05-29", "2026-06-05"],
        "highlights": "骑楼老街+东郊椰林+博鳌亚洲论坛+万泉河漂流，品尝文昌鸡和海南粉，住海边民宿"
    },

    # ========== 西藏 ==========
    {
        "tour_id": "XZ001",
        "tour_name": "拉萨布达拉宫+纳木错7日游",
        "city": "拉萨",
        "days": 7,
        "price": 5280.00,
        "total_seats": 20,
        "remaining_seats": 5,
        "agency": "西藏青旅",
        "rating": 4.9,
        "departure_dates": ["2026-06-01", "2026-06-15"],
        "highlights": "含往返机票，布达拉宫+大昭寺+八廓街+纳木错+羊卓雍措，全程供氧酒店，含高原反应保险和专业导游"
    },
    {
        "tour_id": "XZ002",
        "tour_name": "珠峰大本营10日探险游",
        "city": "拉萨",
        "days": 10,
        "price": 7880.00,
        "total_seats": 15,
        "remaining_seats": 3,
        "agency": "马蜂窝旅行",
        "rating": 5.0,
        "departure_dates": ["2026-06-10"],
        "highlights": "珠峰大本营+绒布寺+珠峰日出+岗巴拉山口+扎什伦布寺，越野车全程，含氧气装备和高山向导，极限挑战"
    },

    # ========== 桂林 ==========
    {
        "tour_id": "GL001",
        "tour_name": "桂林阳朔漓江4日游",
        "city": "桂林",
        "days": 4,
        "price": 1680.00,
        "total_seats": 40,
        "remaining_seats": 25,
        "agency": "桂林国旅",
        "rating": 4.8,
        "departure_dates": ["2026-05-28", "2026-06-01", "2026-06-05"],
        "highlights": "漓江竹筏漂流+阳朔西街+十里画廊骑行+龙脊梯田+象鼻山，含阳朔啤酒鱼，住江边民宿"
    },
    {
        "tour_id": "GL002",
        "tour_name": "桂林山水精华3日游",
        "city": "桂林",
        "days": 3,
        "price": 1180.00,
        "total_seats": 45,
        "remaining_seats": 30,
        "agency": "携程旅游",
        "rating": 4.6,
        "departure_dates": ["2026-05-29", "2026-06-01", "2026-06-08"],
        "highlights": "漓江游船+银子岩溶洞+两江四湖夜游+独秀峰，含桂林米粉和啤酒鱼，适合短途出行"
    },

    # ========== 西安 ==========
    {
        "tour_id": "XA001",
        "tour_name": "西安兵马俑+华清池3日游",
        "city": "西安",
        "days": 3,
        "price": 1380.00,
        "total_seats": 40,
        "remaining_seats": 22,
        "agency": "陕西青旅",
        "rating": 4.7,
        "departure_dates": ["2026-05-28", "2026-06-01", "2026-06-08"],
        "highlights": "兵马俑+华清池+大雁塔+回民街+古城墙骑行+陕西历史博物馆，含肉夹馍和羊肉泡馍美食体验"
    },
    {
        "tour_id": "XA002",
        "tour_name": "西安+华山4日深度游",
        "city": "西安",
        "days": 4,
        "price": 1880.00,
        "total_seats": 30,
        "remaining_seats": 15,
        "agency": "中国国旅",
        "rating": 4.8,
        "departure_dates": ["2026-05-31", "2026-06-05"],
        "highlights": "兵马俑+华山长空栈道+大雁塔北广场音乐喷泉+钟鼓楼，含华山索道和门票，住古城内特色客栈"
},
]


# ==================== Milvus 初始化 ====================
# 连接信息统一从 Config 读取，避免脚本硬编码导致环境切换出问题
MILVUS_HOST = conf.milvus_host
MILVUS_PORT = conf.milvus_port
COLLECTION_NAME = conf.tour_group_collection
DIMENSION = conf.embedding_dim  # EMBEDDING_MODEL 输出维度（默认 1536）


def create_tour_group_collection():
    """
    在 Milvus 中创建旅游团 Collection

    字段设计：
    - id: 主键（自增）
    - tour_id: 团号（字符串，如 YN001）
    - tour_name: 团名
    - city: 城市
    - days: 天数
    - price: 价格
    - total_seats: 总座位
    - remaining_seats: 剩余座位
    - agency: 旅行社
    - rating: 评分
    - departure_dates: 出发日期列表（JSON 字符串）
    - highlights: 行程亮点（用于生成向量）
    - embedding: 向量（conf.embedding_dim 维，默认 1536）
    """
    # 连接 Milvus —— 失败时给出明确提示
    try:
        connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT)
        print(f"[OK] 已连接 Milvus: {MILVUS_HOST}:{MILVUS_PORT}")
    except Exception as e:
        print(f"[FAIL] 连接 Milvus 失败: {MILVUS_HOST}:{MILVUS_PORT}")
        print(f"  错误信息: {e}")
        print(f"  请检查：1) Milvus 服务是否启动  2) IP/端口是否正确  3) 防火墙是否放行")
        raise

    # 如果已存在则删除
    if utility.has_collection(COLLECTION_NAME):
        print(f"集合 {COLLECTION_NAME} 已存在，删除重建")
        utility.drop_collection(COLLECTION_NAME)

    # 定义字段
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="tour_id", dtype=DataType.VARCHAR, max_length=20),
        FieldSchema(name="tour_name", dtype=DataType.VARCHAR, max_length=200),
        FieldSchema(name="city", dtype=DataType.VARCHAR, max_length=50),
        FieldSchema(name="days", dtype=DataType.INT64),
        FieldSchema(name="price", dtype=DataType.FLOAT),
        FieldSchema(name="total_seats", dtype=DataType.INT64),
        FieldSchema(name="remaining_seats", dtype=DataType.INT64),
        FieldSchema(name="agency", dtype=DataType.VARCHAR, max_length=100),
        FieldSchema(name="rating", dtype=DataType.FLOAT),
        FieldSchema(name="departure_dates", dtype=DataType.VARCHAR, max_length=200),
        FieldSchema(name="highlights", dtype=DataType.VARCHAR, max_length=1000),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=DIMENSION),
    ]

    schema = CollectionSchema(fields, description="旅游团信息表（RAG 向量检索）")
    collection = Collection(COLLECTION_NAME, schema)
    print(f"集合 {COLLECTION_NAME} 创建成功")

    # 创建向量索引
    index_params = {
        "index_type": "IVF_FLAT",
        "metric_type": "COSINE",
        "params": {"nlist": 64}
    }
    collection.create_index(field_name="embedding", index_params=index_params)
    print("向量索引创建成功 (IVF_FLAT, COSINE)")

    return collection


def insert_tour_groups(collection):
    """
    将旅游团数据生成向量后插入 Milvus
    """
    print(f"\n开始为 {len(TOUR_GROUPS)} 个旅游团生成向量...")
    rows = []
    for i, group in enumerate(TOUR_GROUPS):
        # 使用"城市 + 团名 + 行程亮点"作为 embedding 输入文本
        # TODO 拼完以后的字段作为查询的内容
        embedding_text = f"{group['city']} {group['tour_name']} {group['highlights']}"

        if (i + 1) % 5 == 0:
            print(f"  已处理 {i + 1}/{len(TOUR_GROUPS)} 个团...")

        embedding = get_embedding(embedding_text)

        rows.append({
            "tour_id": group["tour_id"],
            "tour_name": group["tour_name"],
            "city": group["city"],
            "days": group["days"],
            "price": group["price"],
            "total_seats": group["total_seats"],
            "remaining_seats": group["remaining_seats"],
            "agency": group["agency"],
            "rating": group["rating"],
            "departure_dates": json.dumps(group["departure_dates"], ensure_ascii=False),
            "highlights": group["highlights"],
            "embedding": embedding,
        })

    # 批量插入
    collection.insert(rows)
    collection.flush()  # 刷盘
    print(f"成功插入 {len(TOUR_GROUPS)} 个旅游团数据")


def test_search(collection):
    """
    测试语义搜索：用自然语言查询旅游团
    """
    # 测试查询
    test_queries = [
        "我想去一个有雪山的地方，最好能看日出",
        "适合亲子游的短途旅行",
        "美食之旅，想吃火锅和特色小吃",
        "海边度假，潜水看珊瑚",
        "文化古迹，想看兵马俑和古城墙",
    ]

    print("\n=== 语义搜索测试 ===")
    for query in test_queries:
        print(f"\n查询: {query}")
        query_embedding = get_embedding(query)

        collection.load()
        results = collection.search(
            data=[query_embedding],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"nprobe": 10}},
            limit=2,
            output_fields=["tour_id", "tour_name", "city", "days", "price", "rating", "agency", "highlights"]
        )

        for hits in results:
            for hit in hits:
                print(f"  [{hit.entity.get('tour_id')}] {hit.entity.get('tour_name')} "
                      f"- {hit.entity.get('city')} {hit.entity.get('days')}天 "
                      f"¥{hit.entity.get('price')} 评分{hit.entity.get('rating')} "
                      f"距离: {hit.distance:.4f}")


if __name__ == '__main__':
    collection = create_tour_group_collection()
    insert_tour_groups(collection)
    test_search(collection)
