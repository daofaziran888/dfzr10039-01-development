"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class UrlDedupService(BaseModuleService):
    MODULE = "url_dedup"
    ENTITY = "去重指纹"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["指纹编号", "源URL", "指纹算法", "指纹哈希", "发现渠道", "首次发现", "重复次数", "去重状态"]
    REQUIRED_FIELDS = ["指纹编号", "源URL", "指纹算法"]
    STATUS_ORDER = ["已记录", "已去重", "允许重采", "永久排除"]
    ACTION_RULES = {"标记重采": "已去重", "永久排除": "永久排除"}
    NEGATIVE_ACTIONS = []
