"""
并发配额限流器 (Rate Limiter)
基于 Redis 和 Token Bucket 或 Fixed Window
对应 tasks.md: Task 15.1
"""

import time
from fastapi import Request, HTTPException, status
from loguru import logger

from app.auth.jwt import jwt_decode, verify_api_key
from app.config import config
from app.memory.session_store import session_store  # 复用其 get_redis()
from app.storage.database import tenant_session
from app.storage.models import Tenant

class RateLimiter:
    """
    负责维护每个租户的分钟级并发请求上限。
    如果配额满，抛出 429 Too Many Requests。
    如果 Redis 挂掉，则降级为放行，不阻断主链路。
    """
    
    @staticmethod
    async def get_tenant_quota(tenant_id: str) -> int:
        """从 DB 里获取租户特定的限额，支持动态更新配额。如果异常，fallback 60"""
        try:
            # Note: 为 P2 演示简化, 直接开个 session 拿 quota。生产环境应该缓存在本地或 Redis。
            import sqlalchemy as sa
            async with tenant_session(tenant_id=tenant_id) as session:
                res = await session.execute(sa.select(Tenant.quota_requests_per_minute).where(Tenant.id == tenant_id))
                quota = res.scalar_one_or_none()
                return quota if quota is not None else 60
        except Exception as e:
            logger.warning(f"获取租户 {tenant_id} 的动态配额失败，降级为 60: {e}")
            return 60

    @staticmethod
    async def check_rate_limit(tenant_id: str) -> None:
        """
        验证当前请求是否超过了分钟级滑窗限制。
        由于任务要求简化为 `quota:tenant:{tid}:requests:{minute}` 格式，我们采用 Fixed Window(固定窗口)。
        这虽然会有突刺边界，但易于理解、占用少且极稳定。
        """
        # 防止完全没有配置模式或者本地开发卡死
        if config.multi_tenant_mode is False:
            return
            
        try:
            redis = await session_store.get_redis()
        except Exception as e:
            logger.error(f"Redis 连接失败，限流器自动放行: {e}")
            return
            
        current_minute = int(time.time() / 60)
        redis_key = f"quota:tenant:{tenant_id}:requests:{current_minute}"
        
        try:
            # 1. Pipeline 封装 INCR 与 EXPIRE 以保证原子性
            async with redis.pipeline(transaction=True) as pipe:
                pipe.incr(redis_key)
                pipe.expire(redis_key, 120)  # 过期稍大于 1 分钟即可
                result = await pipe.execute()
            
            # 拿到计数
            current_requests = result[0]
            
            # 2. 从 DB 获取当前租户的最高容忍数
            quota = await RateLimiter.get_tenant_quota(tenant_id)
            
            if current_requests > quota:
                logger.warning(f"[RateLimit] 租户 {tenant_id} 触发限流 ({current_requests}/{quota})")
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"请求频次过多。当前租户配额为 {quota}/分钟",
                    headers={"Retry-After": "60"}
                )
                
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"RateLimiter 发生未知错误，降级放行: {e}")
            return


# 包装为 FastAPI 依赖
async def rate_limit_dependency(request: Request):
    """提取 tenant_id 并且打给 RateLimiter"""
    tenant_id = None
    
    # 尝试各种形式拿出 tenant_id
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        try:
            payload = jwt_decode(auth_header.split(" ")[1])
            tenant_id = payload.tenant_id
        except Exception:
            pass
            
    if not tenant_id:
        api_key = request.headers.get("X-API-Key")
        if api_key:
            tenant_id = await verify_api_key(api_key)
            
    # 如果没拿到，让 auth middleware 接下来去处理 401
    if tenant_id:
        await RateLimiter.check_rate_limit(tenant_id)
