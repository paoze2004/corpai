"""
需求：管理CorpAI项目的配置信息,所有配置项 Phase 6 走 os.getenv 读 .env。

思路步骤：
1. 加载 .env(python-dotenv 自动)
2. 创建 Config 类,所有字段优先读 env,缺省值兜底(开发/测试便利)
3. 配置大模型参数(BASE_URL/API_KEY/MODEL)
4. 配置数据库参数(host/user/password/database,env override)
5. 配置日志文件路径(从项目根算)
6. 配置意图映射(保留,Phase 6 不动)
7. 配置天气/Embedding/Milvus(全部 env override)
"""
import os

from dotenv import load_dotenv

load_dotenv()

# 项目根目录:config.py 在 CorpAI/ 包内,向上两层回到项目根
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _env(name: str, default: str | None = None) -> str | None:
    """优先 .env,缺省 None。空字符串视为 None(避免 '' 走流程)。"""
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    return val


def _env_int(name: str, default: int) -> int:
    val = _env(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError as exc:
        raise ValueError(f"环境变量 {name}={val!r} 不是合法整数") from exc


def _env_float(name: str, default: float) -> float:
    val = _env(name)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError as exc:
        raise ValueError(f"环境变量 {name}={val!r} 不是合法浮点数") from exc


class Config:
    """Phase 6:全部 hardcoded 改 os.getenv 读 .env(.env.example 已列出所有 env 名)。

    必填项:`API_KEY`、`AUTH_JWT_SECRET`(Phase 3+);其余有合理 dev 缺省。
    """

    def __init__(self) -> None:
        # ── LLM ──
        self.base_url = _env("BASE_URL", "https://api.minimaxi.com/v1")
        self.api_key = _env("API_KEY")  # Phase 6:dev 也必须从 .env 读(无 default)
        self.model_name = _env("MODEL", "MiniMax-Text-01")
        self.temperature = _env_float("TEMPERATURE", 0.1)

        # ── MySQL ──
        self.host = _env("MYSQL_HOST", "localhost")
        self.user = _env("MYSQL_USER", "admin")
        self.password = _env("MYSQL_PASSWORD", "admin123456")
        self.database = _env("MYSQL_DATABASE", "CorpAI")

        # 连接池(Phase 6:env override)
        self.pool_name = _env("MYSQL_POOL_NAME", "corp_ai_pool")
        self.pool_size = _env_int("MYSQL_POOL_SIZE", 5)

        # ── 日志 ──
        self.log_file = os.path.join(_project_root, "logs", "app.log")

        # ── 意图路由 ──
        # 优先走 plugin_manager.agents_for_intent(intent)(entry_points 自动发现);
        # 此 dict 仅在 plugin 未命中时兜底,Phase 7 旅行 plugin 已删,
        # 不再列任何旅行 intent(weather/flight/train/...)映射 — 那些 A2A URL 不存在。
        # 企业插件(hr/devops/faq)统一由 plugin manifest 注册,不在此处硬编码。
        self.intent: dict[str, str] = {}

        # ── 天气数据源(可选 "database" | "api")──
        self.weather_source = _env("WEATHER_SOURCE", "database")
        if self.weather_source not in ("database", "api"):
            raise ValueError(
                f"WEATHER_SOURCE={self.weather_source!r} 必须是 'database' 或 'api'"
            )

        # 和风天气 API
        self.weather_api_key = _env("WEATHER_API_KEY")
        self.weather_base_url = _env("WEATHER_BASE_URL")
        self.weather_api_host = _env("WEATHER_API_HOST")
        self.weather_timezone = _env("WEATHER_TIMEZONE", "Asia/Shanghai")
        self.weather_city_codes = {
            "北京": "101010100",
            "成都": "101270101",
        }
        self.weather_schedule_time = _env("WEATHER_SCHEDULE_TIME", "01:00")

        # ── Milvus ──
        self.milvus_host = _env("MILVUS_HOST", "192.168.88.100")
        self.milvus_port = _env_int("MILVUS_PORT", 19530)
        # Phase 7:删除 tour_group_collection(旅行 plugin 已删,无业务使用)
        self.faq_collection = _env("FAQ_COLLECTION", "faq_docs")  # Phase 5 faq plugin 加

        # ── Embedding(独立于 LLM,Phase 6 env override)──
        # Phase 6:与 LLM 同源 fallback(单 key 部署便利)
        self.embedding_base_url = _env("EMBEDDING_BASE_URL") or self.base_url
        self.embedding_api_key = _env("EMBEDDING_API_KEY") or self.api_key
        self.embedding_model_name = _env("EMBEDDING_MODEL", "embo-01")
        self.embedding_url = f"{self.embedding_base_url.rstrip('/')}/embeddings"
        self.embedding_type_insert = _env("EMBEDDING_TYPE_INSERT", "db")
        self.embedding_type_query = _env("EMBEDDING_TYPE_QUERY", "query")
        self.embedding_dim = _env_int("EMBEDDING_DIM", 1536)

        # ── Phase 3+ RBAC ──
        # AUTH_JWT_SECRET 由 dependencies.get_jwt_secret() 直接读 os.getenv,
        # 此处不存,保持单一 source-of-truth。

    def __repr__(self) -> str:
        # 隐藏密码 + api_key,避免 .env 调试时泄露
        return (
            f"Config(host={self.host!r}, user={self.user!r}, password={'***' if self.password else None}, "
            f"database={self.database!r}, base_url={self.base_url!r}, "
            f"api_key={'***' if self.api_key else None}, model={self.model_name!r})"
        )


if __name__ == "__main__":
    c = Config()
    print(repr(c))
