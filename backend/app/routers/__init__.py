"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import recrawl, resource

# 缺页复采的固定路径必须排在通用 /api/{module} 资源路由之前，
# 否则 /api/recrawl/... 会被动态路径抢先匹配。
ROUTERS = [recrawl, resource]
