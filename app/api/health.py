"""健康检查接口

对应 tasks.md: Task 7 — P0 Checkpoint 验证
确保改造后的代码能启动 FastAPI 服务，至少 /health 端点可访问。
"""

from typing import Any
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from loguru import logger

from app.config import config

router = APIRouter()


@router.get("/health")
async def health_check():
    """健康检查接口

    检查服务状态和外部依赖连接状态。
    即使外部依赖不可用，也返回基本健康信息（降级模式）。
    """
    health_data: dict[str, Any] = {
        "service": config.app_name,
        "version": config.app_version,
        "status": "healthy",
        "multi_tenant": config.multi_tenant_mode,
    }

    overall_healthy = True

    # 检查 Milvus 连接状态（可选依赖）
    try:
        from app.core.milvus_client import milvus_manager
        milvus_healthy = milvus_manager.health_check()
        health_data["milvus"] = {
            "status": "connected" if milvus_healthy else "disconnected",
        }
        if not milvus_healthy:
            overall_healthy = False
    except Exception as e:
        logger.debug(f"Milvus 不可用（开发模式可忽略）: {e}")
        health_data["milvus"] = {"status": "unavailable"}

    # 检查数据库连接状态（可选依赖）
    try:
        from app.storage.database import _build_database_url
        db_url = _build_database_url()
        health_data["database"] = {
            "status": "configured",
            "driver": db_url.split("://")[0] if "://" in db_url else "unknown",
        }
    except Exception as e:
        logger.debug(f"数据库配置异常: {e}")
        health_data["database"] = {"status": "unconfigured"}

    # LLM 配置检查
    health_data["llm"] = {
        "provider": "openrouter" if config.openrouter_api_key else "unconfigured",
        "model": config.default_model,
    }

    status_code = 200 if overall_healthy else 503
    health_data["status"] = "healthy" if overall_healthy else "degraded"

    return JSONResponse(
        status_code=status_code,
        content={
            "code": status_code,
            "message": "Service running" if overall_healthy else "Service degraded",
            "data": health_data,
        },
    )
