"""
需求：管理SmartVoyage项目的配置信息，包括大模型、数据库、日志等配置
思路步骤：
1. 定义项目根目录路径
2. 设置环境变量（生产/测试/开发/预生产）
3. 创建Config类管理所有配置项
4. 配置大模型参数（API地址、密钥、模型名称）
5. 配置数据库参数（主机、用户名、密码、数据库名）
6. 配置日志文件路径
7. 配置票务查询接口地址
8. 配置意图映射字典
9. 实现根据环境获取不同数据库配置的方法
"""

import os
from dotenv import load_dotenv
load_dotenv()

# 项目根目录
project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)))

# 生产环境
# env = "prod"
# 测试环境
env = "test"
# 开发环境
# env = "dev"
# 预生产环境
# env = "pre_prod"



#定义配置文件
class Config:

    def __init__(self):
        # 大模型配置
        self.base_url = os.getenv("BASE_URL")
        self.api_key = os.getenv("API_KEY")
        self.model_name = os.getenv("MODEL")

        # 数据库配置
        self.host = 'localhost'
        # TODO 实际工作中，一般一个业务创建一个账号。不要使用root，风险太大
        # 当前环境直接用 root:root 跑通（root/123456 不存在，root/root 可用）
        self.user = 'root'
        self.password = 'root'
        self.database = 'travel_rag'

        # 数据库连接池配置
        self.pool_name = "smart_voyage_pool"  # 连接池名称
        self.pool_size = 5  # 连接池大小（最大连接数）

        # 日志配置
        self.log_file = os.path.join(project_root, 'logs', 'app.log')

        # # 票务查询的12306接口地址
        # self.url_123 = ""

        # 路由：意图和对应的Agent的对应关系
        self.intent = {
            "weather": "WeatherQueryAssistant",
            "flight": "TicketAssistant",
            "train": "TicketAssistant",
            "concert": "TicketAssistant",
            "order": "TicketAssistant",
            "car_rental": "TripAssistant",
            "tour_group": "TripAssistant",
            "insurance": "TripAssistant",
            "trip_order": "TripAssistant",
        }

        self.temperature = 0.1

        # 天气数据源配置
        # 默认："database"
        # 可选值："database"（从数据库获取） / "api"（直接从和风API获取）
        self.weather_source = "database"

        # 和风天气 API 配置
        self.weather_api_key = os.getenv("WEATHER_API_KEY")
        self.weather_base_url = os.getenv("WEATHER_BASE_URL")
        self.weather_api_host = os.getenv("WEATHER_API_HOST")
        self.weather_timezone = os.getenv("WEATHER_TIMEZONE")

        # 天气监控城市列表（城市名 -> 城市代码）
        self.weather_city_codes = {
            "北京": "101010100",
            "成都": "101270101"
        }

        # 天气定时更新调度时间（北京时间）
        self.weather_schedule_time = "01:00"

        # Milvus 向量数据库配置
        self.milvus_host = "localhost"
        self.milvus_port = 19530
        self.tour_group_collection = "tour_groups"

        # Qwen Embedding API 配置
        self.embedding_url = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
        self.embedding_dim = 1024

    #
    # def get_mysql_config(self,env):
    #     """
    #     通过不同的环境获取不同的数据库配置
    #     :return:
    #     """
    #     if env == 'prod':
    #         # 数据库配置 生产
    #         self.host = 'localhost'
    #         self.user = 'root'
    #         self.password = 'root'
    #         self.database = 'travel_rag'
    #     elif env == 'dev':
    #         # 数据库配置 开发
    #         self.host = 'localhost1'
    #         self.user = 'root1'
    #         self.password = 'root1'
    #         self.database = 'travel_rag'
    #     elif env == 'test':
    #         # 数据库配置 测试
    #         self.host = 'localhost2'
    #         self.user = 'root2'
    #         self.password = 'root2'
    #         self.database = 'travel_rag'
    #     else:
    #         # 数据库配置 预生产
    #         self.host = 'localhost3'
    #         self.user = 'root3'
    #         self.password = 'root3'
    #         self.database = 'travel_rag'
    #
    #     return self.host, self.user, self.password, self.database


if __name__ == '__main__':
    print(Config().log_file)
    print(Config().database)
    # ('localhost', 'root', 'root', 'travel_rag')
    # ('localhost', 'root2', 'root2', 'travel_rag')