"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class CrawlLimitService(BaseModuleService):
    MODULE = "crawl_limit"
    ENTITY = "限速策略"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["策略编号", "目标站点", "请求间隔", "并发上限", "日请求量", "时段窗口", "限速类型", "策略状态"]
    REQUIRED_FIELDS = ["策略编号", "目标站点", "请求间隔"]
    STATUS_ORDER = ["草稿", "生效中", "触发限速", "已停用"]
    ACTION_RULES = {"启效策略": "生效中", "临时放开": "触发限速", "停用策略": "已停用"}
    NEGATIVE_ACTIONS = ["停用策略"]
