"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class TemplateLibService(BaseModuleService):
    MODULE = "template_lib"
    ENTITY = "采集模板"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["模板编号", "站点类型", "模板名称", "字段列表", "抽取规则集", "版本号", "兼容站点数", "最近更新"]
    REQUIRED_FIELDS = ["模板编号", "站点类型", "模板名称"]
    STATUS_ORDER = ["草稿", "已发布", "有更新", "已废弃"]
    ACTION_RULES = {"发布模板": "已发布", "标记更新": "有更新", "废弃模板": "已废弃"}
    NEGATIVE_ACTIONS = []
