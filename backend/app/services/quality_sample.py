"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class QualitySampleService(BaseModuleService):
    MODULE = "quality_sample"
    ENTITY = "抽样计划"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["计划编号", "目标批次", "抽样比例", "抽样方式", "样本数量", "检验结果", "偏差阈值", "最近采样"]
    REQUIRED_FIELDS = ["计划编号", "目标批次", "抽样比例"]
    STATUS_ORDER = ["待采样", "采样中", "已通过", "偏差告警"]
    ACTION_RULES = {"启动采样": "采样中", "确认通过": "已通过", "标记告警": "偏差告警"}
    NEGATIVE_ACTIONS = []
