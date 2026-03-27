"""JWT 认证 + FastAPI 中间件

对应 design.md: 模块架构 → auth/jwt.py, gateway/middleware.py
对应 tasks.md: Task 2.1 — 实现 JWT 编解码和中间件

职责：
- JWT 编码 / 解码（PyJWT）
- FastAPI 中间件：解析 JWT → 注入 tenant_id 到请求上下文
- API Key 验证（用于 Webhook 接入）
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from pydantic import BaseModel

from app.config import config


# ---------------------------------------------------------------------------
# Token Payload 模型
# ---------------------------------------------------------------------------

class TokenPayload(BaseModel):
    """JWT token 中携带的身份信息"""
    tenant_id: str
    user_id: str
    role: str = "Member"  # Admin / Member / Viewer
    exp: Optional[float] = None


# ---------------------------------------------------------------------------
# JWT 编解码
# design.md: "JWT 令牌中包含 tenant_id 和 user_id"
# ---------------------------------------------------------------------------

def jwt_encode(payload: dict) -> str:
    """将 payload 编码为 JWT token。

    Args:
        payload: 必须包含 tenant_id, user_id；可选 role

    Returns:
        JWT token 字符串
    """
    to_encode = payload.copy()
    if "exp" not in to_encode:
        expire = datetime.now(timezone.utc) + timedelta(minutes=config.jwt_expire_minutes)
        to_encode["exp"] = expire.timestamp()
    return pyjwt.encode(to_encode, config.jwt_secret, algorithm=config.jwt_algorithm)


def jwt_decode(token: str) -> TokenPayload:
    """解码并验证 JWT token。

    Raises:
        HTTPException(401): token 无效、过期或缺少必要字段
    """
    try:
        payload = pyjwt.decode(
            token,
            config.jwt_secret,
            algorithms=[config.jwt_algorithm],
        )
        return TokenPayload(
            tenant_id=payload["tenant_id"],
            user_id=payload["user_id"],
            role=payload.get("role", "Member"),
            exp=payload.get("exp"),
        )
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 已过期",
        )
    except (pyjwt.InvalidTokenError, KeyError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token 无效: {str(e)}",
        )


# ---------------------------------------------------------------------------
# API Key 验证
# design.md: "为每个租户生成独立的 API Key 用于 Webhook 接入"
# ---------------------------------------------------------------------------

async def verify_api_key(api_key: str) -> Optional[str]:
    """验证 API Key，返回对应的 tenant_id。

    Args:
        api_key: 从 Webhook 请求头中获取的 API Key

    Returns:
        tenant_id（如果 API Key 有效），否则 None

    注意：当前实现需要数据库查询，P0 阶段先提供接口，
    实际查询在 Gateway 层集成时补充。
    """
    # TODO: P2 阶段集成数据库查询 tenants.api_key
    # 目前返回 None，由调用方决定如何处理
    from app.storage.database import admin_session
    from app.storage.models import Tenant
    from sqlalchemy import select

    try:
        async with admin_session() as session:
            result = await session.execute(
                select(Tenant.id).where(Tenant.api_key == api_key)
            )
            row = result.scalar_one_or_none()
            if row:
                return str(row)
    except Exception as e:
        logger.warning(f"API Key 验证失败: {e}")
    return None


# ---------------------------------------------------------------------------
# FastAPI 依赖项
# design.md: "Gateway → JWT 解析 + tenant 上下文注入"
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)


class TenantContext(BaseModel):
    """注入到每个请求的租户上下文"""
    tenant_id: str
    user_id: str
    role: str


async def get_current_tenant(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> TenantContext:
    """FastAPI 依赖：从 JWT 或 API Key 中解析租户上下文。

    优先级：
    1. Authorization: Bearer <JWT>
    2. X-API-Key: <api_key>（Webhook 场景）

    使用方式::

        @router.get("/api/something")
        async def handler(tenant: TenantContext = Depends(get_current_tenant)):
            print(tenant.tenant_id)
    """
    # 如果多租户模式关闭，返回默认上下文
    if not config.multi_tenant_mode:
        return TenantContext(
            tenant_id="default",
            user_id="default",
            role="Admin",
        )

    # 方式 1: JWT Bearer token
    if credentials:
        payload = jwt_decode(credentials.credentials)
        return TenantContext(
            tenant_id=payload.tenant_id,
            user_id=payload.user_id,
            role=payload.role,
        )

    # 方式 2: API Key（Webhook 接入）
    api_key = request.headers.get("X-API-Key")
    if api_key:
        tenant_id = await verify_api_key(api_key)
        if tenant_id:
            return TenantContext(
                tenant_id=tenant_id,
                user_id="webhook",
                role="Member",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key 无效",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="缺少认证信息（Bearer token 或 X-API-Key）",
    )
