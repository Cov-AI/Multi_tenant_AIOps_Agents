"""
审计日志模块单元测试与异常捕捉机制
对应 tasks.md: Task 17.2, 17.3
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.observability.audit import AuditLogger


@pytest.fixture
def mock_tenant_session():
    # 模拟 tenant_session, 注意其属于 async context manager
    with patch("app.observability.audit.tenant_session") as db_mock:
        session_mock = AsyncMock()
        session_mock.add = AsyncMock()
        session_mock.commit = AsyncMock()
        
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def make_session(*args, **kwargs):
            yield session_mock
            
        db_mock.side_effect = make_session
        yield session_mock


@pytest.mark.asyncio
async def test_17_2_audit_recording(mock_tenant_session):
    """Property 11: 验证录入所有的审计记录，并成功 Commit 落盘数据库"""
    res = await AuditLogger.log_action("t1", "userA", "APPROVE", "incident-99", {"a": 1})
    
    assert res is True
    # 确保存底的 DB 调用被激发以符合合规性
    mock_tenant_session.add.assert_called_once()
    mock_tenant_session.commit.assert_called_once()
    
    # 获取存底的对象实例进行验证
    audit_instance = mock_tenant_session.add.call_args[0][0]
    assert audit_instance.action == "APPROVE"
    assert audit_instance.user_id == "userA"
    assert audit_instance.resource == "incident-99"
    assert audit_instance.payload == {"a": 1}

@pytest.mark.asyncio
async def test_17_3_audit_log_edge_cases():
    """Unit Tests: 当因为 DB 崩溃而抛出数据库级别 Error，不会阻断系统而是被接住咽下"""
    with patch("app.observability.audit.tenant_session") as dbs:
        dbs.side_effect = Exception("DB Down")
        
        # 记录依然要返回 False，但不抛错引发系统崩溃
        res = await AuditLogger.log_action("t1", "u1", "A", "R")
        assert res is False
