"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class IncrCrawlService(BaseModuleService):
    MODULE = "incr_crawl"
    ENTITY = "增量标记"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["标记编号", "目标站点", "增量字段", "上次游标", "当前游标", "新增数量", "更新数量", "最后同步"]
    REQUIRED_FIELDS = ["标记编号", "目标站点", "增量字段"]
    STATUS_ORDER = ["待初始化", "追踪中", "已追上", "追踪异常"]
    ACTION_RULES = {"初始化游标": "追踪中", "启动追踪": "已追上", "标记异常": "追踪异常"}
    NEGATIVE_ACTIONS = []
