"""
架构 P2 后独立的 API 网关端点
对应 tasks.md: Task 14.1
"""

import sys
import os

# 将根目录注入保证直接运行
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from fastapi import Depends
from app.main import app as core_app
from app.gateway.router import router as gateway_router
from app.gateway.limiter import rate_limit_dependency

# 这里我们可以注入网关级的全量依赖中间件，例如 API Rate limiting 中间件，Auth JWT 拦截
core_app.include_router(
    gateway_router,
    dependencies=[Depends(rate_limit_dependency)]
)

# 对外暴露统一 app 入口 (或者使用 uvicorn app.gateway.server:app启动)
app = core_app

if __name__ == "__main__":
    import uvicorn
    from app.config import config
    
    uvicorn.run(
        "app.gateway.server:app",
        host=config.host,
        port=config.port,
        reload=config.debug,
    )
