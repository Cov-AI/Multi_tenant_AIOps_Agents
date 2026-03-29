"""
限流器测试
对应 tasks.md: Task 15.2, 15.3
"""

import time
import pytest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from app.gateway.limiter import RateLimiter

from contextlib import asynccontextmanager

@pytest.fixture
def mock_redis_pipeline():
    with patch("app.memory.session_store.SessionStore.get_redis") as get_redis_mock:
        redis_mock = AsyncMock()
        
        pipeline_mock = AsyncMock()
        pipeline_mock.incr = AsyncMock()
        pipeline_mock.expire = AsyncMock()
        pipeline_mock.execute = AsyncMock()
        
        @asynccontextmanager
        async def mock_ctx(*args, **kwargs):
            yield pipeline_mock
            
        redis_mock.pipeline = mock_ctx
        get_redis_mock.return_value = redis_mock
        
        yield get_redis_mock, pipeline_mock

@pytest.mark.asyncio
async def test_15_2_rate_limiter_within_quota(mock_redis_pipeline):
    """Property 24: 限流配额检查 - 在限额内应当被放行"""
    get_redis_mock, pipeline_mock = mock_redis_pipeline
    
    # Mock current token usages = 30, below default quota 60
    pipeline_mock.execute.return_value = [30, True]
    
    # 模拟 DB 查询
    with patch("app.gateway.limiter.RateLimiter.get_tenant_quota", new_callable=AsyncMock) as mock_quota:
        mock_quota.return_value = 60
        # 正常验证应抛出什么也没有 (不进入 except HTTPExc)
        await RateLimiter.check_rate_limit("t1")
        pipeline_mock.execute.assert_called_once()


@pytest.mark.asyncio
async def test_15_2_rate_limiter_exceeded_quota(mock_redis_pipeline):
    """Property 24: 限流配额检查 - 超出限额应当被抛出 HTTPException 429"""
    get_redis_mock, pipeline_mock = mock_redis_pipeline
    
    # Mock current token usages = 61!
    pipeline_mock.execute.return_value = [61, True]
    
    with patch("app.gateway.limiter.RateLimiter.get_tenant_quota", new_callable=AsyncMock) as mock_quota:
        mock_quota.return_value = 60
        
        with pytest.raises(HTTPException) as exc:
            await RateLimiter.check_rate_limit("t1")
            
        assert exc.value.status_code == 429
        assert "配额为 60/分" in exc.value.detail

@pytest.mark.asyncio
async def test_15_3_limiter_edge_cases_redis_fallback():
    """Unit Tests: Redis 崩盘等边缘触发 发生时不可阻断链路"""
    with patch("app.memory.session_store.SessionStore.get_redis") as get_redis_mock:
        get_redis_mock.side_effect = ConnectionError("Redis down")
        
        # 此执行不应抛出任何错误，必须平滑处理
        await RateLimiter.check_rate_limit("t1")
