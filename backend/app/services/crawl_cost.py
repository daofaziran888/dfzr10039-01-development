"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class CrawlCostService(BaseModuleService):
    MODULE = "crawl_cost"
    ENTITY = "用量记录"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["记录编号", "采集站点", "计费周期", "请求次数", "数据流量", "代理用量", "费用预估", "账单状态"]
    REQUIRED_FIELDS = ["记录编号", "采集站点", "计费周期"]
    STATUS_ORDER = ["统计中", "已核算", "超额告警", "已确认"]
    ACTION_RULES = {"启动核算": "已核算", "确认账单": "超额告警", "标记超额": "已确认"}
    NEGATIVE_ACTIONS = []
