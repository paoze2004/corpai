import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal


# MiniMax-M3 等推理模型会在 content 里塞 <think>...</think> 思考过程,
# 前端/JSON 解析必须剥掉,否则用户会看到半截思考文本混入正式回复。
# 见 memory: minimax-m3-think-blocks
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def strip_think(text: str) -> str:
    """
    剥掉 LLM 回复中的 <think>...</think> 思考块(以及块后的空白)。

    用法: agent / chat service 拿到 LLM content 后过一遍再返回。
    """
    if not text:
        return text
    return _THINK_BLOCK_RE.sub("", text).strip()


def default_encoder(obj):
    """格式化单个对象，将非标准类型转换为JSON兼容格式"""
    if isinstance(obj, datetime):
        return obj.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(obj, date):
        return obj.strftime('%Y-%m-%d')
    if isinstance(obj, timedelta):
        return str(obj)
    if isinstance(obj, Decimal):
        return float(obj)
    return obj

# 自定义JSON编码器类，处理非标准类型序列化
class DateEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.strftime('%Y-%m-%d %H:%M:%S') if isinstance(obj, datetime) else obj.strftime('%Y-%m-%d')
        if isinstance(obj, timedelta):
            return str(obj)
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)