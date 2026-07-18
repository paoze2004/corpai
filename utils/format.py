import json
from datetime import date, datetime, timedelta
from decimal import Decimal


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