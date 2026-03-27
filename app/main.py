"""FastAPI 应用入口

对应 tasks.md: Task 7 — P0 Checkpoint 验证
确保改造后的代码能启动 FastAPI 服务，至少 /health 端点可访问。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import os

from app.config import config
from loguru import logger
from app.api import chat, health, file, aiops


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理 — 优雅降级，不因外部依赖缺失而崩溃"""
    logger.info("=" * 60)
    logger.info(f"🚀 {config.app_name} v{config.app_version} 启动中...")
    logger.info(f"📝 环境: {'开发' if config.debug else '生产'}")
    logger.info(f"🌐 监听地址: http://{config.host}:{config.port}")
    logger.info(f"📚 API 文档: http://{config.host}:{config.port}/docs")
    logger.info(f"🏢 多租户模式: {config.multi_tenant_mode}")

    # 连接 Milvus（可选，开发环境可能没有）
    try:
        from app.core.milvus_client import milvus_manager
        logger.info("🔌 正在连接 Milvus...")
        milvus_manager.connect()
        logger.info("✅ Milvus 连接成功")
    except Exception as e:
        logger.warning(f"⚠️ Milvus 连接失败（开发模式可忽略）: {e}")

    logger.info("=" * 60)

    yield

    # 关闭时执行
    try:
        from app.core.milvus_client import milvus_manager
        milvus_manager.close()
    except Exception:
        pass
    logger.info(f"👋 {config.app_name} 关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title=config.app_name,
    version=config.app_version,
    description="Multi-tenant AIOps OnCall Agent Platform",
    lifespan=lifespan,
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(health.router, tags=["健康检查"])
app.include_router(chat.router, prefix="/api", tags=["对话"])
app.include_router(file.router, prefix="/api", tags=["文件管理"])
app.include_router(aiops.router, prefix="/api", tags=["AIOps智能运维"])

# 挂载静态文件（如果目录存在）
static_dir = "static"
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    """返回首页"""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "message": f"Welcome to {config.app_name} API",
        "version": config.app_version,
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=config.host,
        port=config.port,
        reload=config.debug,
        log_level="info",
    )
