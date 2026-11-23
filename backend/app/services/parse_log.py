"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class ParseLogService(BaseModuleService):
    MODULE = "parse_log"
    ENTITY = "解析记录"
    OPERATION_TERM = "解析"
    LIST_FIELDS = ["记录编号", "来源URL", "解析规则", "解析结果", "异常类型", "重试次数", "错误详情", "记录时间", "所属作业"]
    REQUIRED_FIELDS = ["记录编号", "来源URL", "解析规则"]
    STATUS_ORDER = ["成功", "格式异常", "内容缺失", "重试中"]
    ACTION_RULES = {"标记重试": "格式异常", "标记审计": "内容缺失"}
    NEGATIVE_ACTIONS = []
