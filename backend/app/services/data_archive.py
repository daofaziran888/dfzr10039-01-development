"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class DataArchiveService(BaseModuleService):
    MODULE = "data_archive"
    ENTITY = "归档策略"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["策略编号", "数据范围", "归档周期", "归档格式", "保留时长", "存储位置", "压缩方式", "最后归档"]
    REQUIRED_FIELDS = ["策略编号", "数据范围", "归档周期"]
    STATUS_ORDER = ["待触发", "归档中", "已完成", "归档异常"]
    ACTION_RULES = {"触发归档": "归档中", "暂停归档": "已完成", "标记异常": "归档异常"}
    NEGATIVE_ACTIONS = []
