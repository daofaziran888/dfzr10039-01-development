"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class ProxyPoolService(BaseModuleService):
    MODULE = "proxy_pool"
    ENTITY = "代理节点"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["节点编号", "代理地址", "代理类型", "地域标签", "运营商", "响应延迟", "成功率", "最后校验"]
    REQUIRED_FIELDS = ["节点编号", "代理地址", "代理类型"]
    STATUS_ORDER = ["待校验", "可用", "延迟告警", "已下线"]
    ACTION_RULES = {"校验节点": "可用", "标记告警": "延迟告警", "下线节点": "已下线"}
    NEGATIVE_ACTIONS = ["下线节点"]
