"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class ContentExtractService(BaseModuleService):
    MODULE = "content_extract"
    ENTITY = "抽取规则"
    OPERATION_TERM = "清洗"
    LIST_FIELDS = ["规则编号", "目标站点", "XPath选择器", "字段映射", "数据类型", "清洗正则", "抽取顺序", "规则状态"]
    REQUIRED_FIELDS = ["规则编号", "目标站点", "XPath选择器"]
    STATUS_ORDER = ["草稿", "生效中", "抽取异常", "已废弃"]
    ACTION_RULES = {"启效规则": "生效中", "标记异常": "抽取异常", "废弃规则": "已废弃"}
    NEGATIVE_ACTIONS = []
