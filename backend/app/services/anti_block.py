"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class AntiBlockService(BaseModuleService):
    MODULE = "anti_block"
    ENTITY = "对抗策略"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["策略编号", "目标站点", "对抗类型", "UserAgent池", "Cookie轮换", "请求间隔", "验证码识别", "策略状态"]
    REQUIRED_FIELDS = ["策略编号", "目标站点", "对抗类型"]
    STATUS_ORDER = ["待配置", "生效中", "触发封禁", "已失效"]
    ACTION_RULES = {"启效策略": "生效中", "触发轮换": "触发封禁", "标记失效": "已失效"}
    NEGATIVE_ACTIONS = []
