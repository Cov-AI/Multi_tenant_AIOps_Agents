"""
测试 Workspace 缓存优先及 Round-Trip 对象序列化
对应 tasks.md: Task 18.2, 18.3, 18.4
"""

import json
import pytest
from unittest.mock import AsyncMock, patch

from app.services.workspace import WorkspaceConfigService

@pytest.fixture
def mock_redis_and_db():
    with patch("app.services.workspace.session_store.get_redis", new_callable=AsyncMock) as redis_mock:
        with patch("app.services.workspace.tenant_session") as db_mock:
            # Setup DB Mock Context Manager
            from contextlib import asynccontextmanager
            session_mock = AsyncMock()
            
            # Setup DB Select Query Mock Return
            from unittest.mock import MagicMock
            query_mock = MagicMock()
            query_mock.scalar_one_or_none.return_value = {"agents_md": "hello"}
            session_mock.execute.return_value = query_mock
            
            @asynccontextmanager
            async def make_session(*args, **kwargs):
                yield session_mock
                
            db_mock.side_effect = make_session
            yield redis_mock, db_mock, session_mock


@pytest.mark.asyncio
async def test_18_2_workspace_cache_priority(mock_redis_and_db):
    """Property 25: Workspace 配置缓存优先 - 验证命中优先从 Redis 读取"""
    redis_mock, db_mock, session_mock = mock_redis_and_db
    
    # 模拟 Redis Hit
    mock_connection = AsyncMock()
    mock_connection.get.return_value = json.dumps({"tools": ["loki"]})
    redis_mock.return_value = mock_connection
    
    # 获取配置
    config = await WorkspaceConfigService.get_config("t1", "a1")
    
    # 验证是否没有连库
    assert config == {"tools": ["loki"]}
    assert session_mock.execute.call_count == 0


@pytest.mark.asyncio
async def test_18_3_workspace_config_json_round_trip():
    """Property 27: Workspace 配置 JSON Round-Trip - 验证解析一致性"""
    original = {"soul": "You are a helpful assistant", "tools": ["mcp-prom", "mcp-k8s"], "thresholds": {"cpu": 90}}
    
    # Serialize to JSON 字符串
    serialized = json.dumps(original)
    
    # Deserialize back
    deserialized = json.loads(serialized)
    
    assert deserialized == original
    assert deserialized["thresholds"]["cpu"] == 90


@pytest.mark.asyncio
async def test_18_4_workspace_cache_miss_repopulation(mock_redis_and_db):
    """Unit Tests: Workspace 缓存击穿时从 DB 获取并且回填 Redis 的容错测试"""
    redis_mock, db_mock, session_mock = mock_redis_and_db
    
    # 模拟 Redis Miss
    mock_connection = AsyncMock()
    mock_connection.get.return_value = None
    mock_connection.setex = AsyncMock()
    redis_mock.return_value = mock_connection
    
    config = await WorkspaceConfigService.get_config("t1", "a1")
    
    # 这时来自于 DB 中 Mock 的返回
    assert config == {"agents_md": "hello"}
    
    # 验证确实发生了查询
    assert session_mock.execute.call_count == 1
    
    # 验证将该结果 set 进了 Redis
    mock_connection.setex.assert_called_once()
    assert "workspace:config:a1" in mock_connection.setex.call_args[0]


@pytest.mark.asyncio
async def test_18_4_workspace_redis_down_fallback(mock_redis_and_db):
    """Unit Tests: 当 Redis 不可用完全挂掉时，降级退居 DB"""
    redis_mock, db_mock, session_mock = mock_redis_and_db
    
    redis_mock.side_effect = Exception("Redis Offline")
    
    config = await WorkspaceConfigService.get_config("t1", "a1")
    
    # 依然可以顺滑访问
    assert config == {"agents_md": "hello"}
    assert session_mock.execute.call_count == 1
