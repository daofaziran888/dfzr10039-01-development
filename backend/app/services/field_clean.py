"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class FieldCleanService(BaseModuleService):
    MODULE = "field_clean"
    ENTITY = "清洗规则"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["规则编号", "目标字段", "清洗类型", "处理表达式", "空值策略", "校验范围", "清洗顺序", "规则状态"]
    REQUIRED_FIELDS = ["规则编号", "目标字段", "清洗类型"]
    STATUS_ORDER = ["草稿", "生效中", "清洗失败", "已停用"]
    ACTION_RULES = {"启效规则": "生效中", "标记失败": "清洗失败", "停用规则": "已停用"}
    NEGATIVE_ACTIONS = ["停用规则"]
