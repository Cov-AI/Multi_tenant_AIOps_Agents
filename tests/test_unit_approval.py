"""
审批流程相关的接口与服务测试
对应 tasks.md: Task 11.2 / 11.3
"""
import pytest
import uuid
import app.config
from app.workflow.approval import ApprovalManager

@pytest.mark.asyncio
async def test_approval_manager_mock():
    """由于我们暂时还没有在测试集配置测试数据库，我们测试 Mock 层级的 fallback。"""
    
    tenant_id = str(uuid.uuid4())
    incident_id = str(uuid.uuid4())
    
    # 模拟错误的数据库链接以触发 fallback
    original_url = getattr(app.config.config, "database_url", "")
    app.config.config.database_url = "postgresql://fakeuser:fakepass@localhost:1234/fakedb"
    
    try:
        # 获取 token（ fallback 不出错）
        token = await ApprovalManager.create_approval(
            tenant_id=tenant_id,
            incident_id=incident_id,
            requested_by=None,
            message="Test fallback"
        )
        assert token is not None
        
        # 尝试审批（fallback 应该默认能 resolve 以防止阻塞死循环）
        result = await ApprovalManager.resolve_approval(
            token=token,
            tenant_id=tenant_id,
            decision="approve"
        )
        
        # Mock 逻辑返回
        assert result is not None
        assert result.get("status") == "approved"
        
    finally:
        app.config.config.database_url = original_url
