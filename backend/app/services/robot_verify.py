"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class RobotVerifyService(BaseModuleService):
    MODULE = "robot_verify"
    ENTITY = "识别记录"
    OPERATION_TERM = "调度"
    LIST_FIELDS = ["记录编号", "目标站点", "验证码类型", "识别引擎", "识别耗时", "识别结果", "置信度", "记录时间"]
    REQUIRED_FIELDS = ["记录编号", "目标站点", "验证码类型"]
    STATUS_ORDER = ["待识别", "识别成功", "识别失败", "人工干预"]
    ACTION_RULES = {"触发识别": "待识别", "人工复核": "识别成功", "误判报备": "识别失败"}
    NEGATIVE_ACTIONS = []
