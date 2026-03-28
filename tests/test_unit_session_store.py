"""
会话存储 - 三层存储回落逻辑与持久化测试
对应 tasks.md: Task 12.2 - Property 5: Session 三层存储一致性
"""
import asyncio
import uuid
import json
import pytest
from unittest.mock import AsyncMock, patch

from app.memory.session_store import session_store, mock_s3
@pytest.fixture(autouse=True)
def mock_redis():
    # 每次测试强制重置状态
    session_store._redis = None
    mock_s3.buckets = {"oncall-sessions": {}}
    
    with patch("app.memory.session_store.from_url") as from_url_mock:
        redis_mock = AsyncMock()
        redis_mock.lrange.return_value = []
        redis_mock.rpush = AsyncMock()
        redis_mock.expire = AsyncMock()
        redis_mock.delete = AsyncMock()
        
        from_url_mock.return_value = redis_mock
        yield redis_mock
        
        # 结束后清理
        session_store._redis = None

@pytest.mark.asyncio
async def test_session_append_and_recover_redis(mock_redis):
    """
    测试 12.2: 热数据追加和读取 (从 Redis 成功加载)
    """
    tenant_id = str(uuid.uuid4())
    session_key = str(uuid.uuid4())
    message = {"role": "user", "content": "Help me!"}
    
    # 追加
    await session_store.append_message(tenant_id, session_key, message)
    mock_redis.rpush.assert_called_once()
    mock_redis.expire.assert_called_once()
    
    # 模拟 Redis 有数据
    mock_redis.lrange.return_value = [json.dumps(message)]
    
    msgs, source = await session_store.recover_session(tenant_id, session_key)
    assert source == "redis"
    assert msgs[0]["content"] == "Help me!"


@pytest.mark.asyncio
async def test_session_recover_s3(mock_redis):
    """
    测试 12.2: 冷数据恢复 (从 S3 中恢复并且写回 Redis 预热)
    """
    tenant_id = str(uuid.uuid4())
    session_key = str(uuid.uuid4())
    
    # 模拟 Redis 无数据（过期了）
    mock_redis.lrange.return_value = []
    
    message = {"role": "assistant", "content": "Archived S3 response!"}
    
    # 手工作假数据到 Mock S3
    await mock_s3.put_object("oncall-sessions", f"{tenant_id}/{session_key}.jsonl", json.dumps(message))
    
    msgs, source = await session_store.recover_session(tenant_id, session_key)
    
    # 验证是否从 S3 获取
    assert source == "s3"
    assert len(msgs) == 1
    assert msgs[0]["content"] == "Archived S3 response!"
    
    # 应该将获取到的消息回填 Redis (rpush, expire)
    mock_redis.rpush.assert_called_once()
    mock_redis.expire.assert_called_once()


@pytest.mark.asyncio
async def test_session_archive_job(mock_redis):
    """
    测试 12.2: 旧数据归档后清除 Redis
    """
    tenant_id = str(uuid.uuid4())
    session_key = "cold-session-key"
    
    msg1 = {"role": "user", "content": "cold 1"}
    msg2 = {"role": "assistant", "content": "cold 2"}
    
    # 模拟 Redis 中存在即将过期的旧数据
    mock_redis.lrange.return_value = [json.dumps(msg1), json.dumps(msg2)]
    
    await session_store.archive_cold_sessions(tenant_id, [session_key])
    
    # 验证清理逻辑：成功写入S3后被从Redis删除释放内存
    body = await mock_s3.get_object("oncall-sessions", f"{tenant_id}/{session_key}.jsonl")
    assert "cold 1" in body
    assert "cold 2" in body
    
    mock_redis.delete.assert_called_once()
