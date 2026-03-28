"""
Property Tests & Unit Tests for AIOps V2 StateGraph
对应 tasks.md: Task 8.2 (Property 10) & Task 8.3
"""

import pytest
import uuid
import json
from unittest.mock import patch, MagicMock

from app.agent.aiops_v2.service import aiops_service_v2
from app.agent.aiops_v2.state import SystemState


@pytest.fixture
def mock_llm_low_risk():
    """Mock LLM to always return low risk execution plan"""
    with patch("app.agent.aiops_v2.nodes.get_chat_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps({"plan": "清理无用日志 (低风险)", "risk": "low"})
        
        async def ainvoke_mock(*args, **kwargs):
            return mock_response
            
        mock_llm.ainvoke = ainvoke_mock
        mock_get_llm.return_value = mock_llm
        yield mock_get_llm


@pytest.fixture
def mock_llm_high_risk():
    """Mock LLM to always return high risk execution plan"""
    with patch("app.agent.aiops_v2.nodes.get_chat_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps({"plan": "重启主数据库引擎 (高风险)", "risk": "high"})
        
        async def ainvoke_mock(*args, **kwargs):
            return mock_response
            
        mock_llm.ainvoke = ainvoke_mock
        mock_get_llm.return_value = mock_llm
        yield mock_get_llm


@pytest.mark.asyncio
async def test_low_risk_flow_completes_property_10(mock_llm_low_risk):
    """
    测试点 8.2 (Property 10: 六状态流转完整性)
    验证：对于低危操作，状态图应该顺畅地经历:
    TRIGGERED -> analyze -> plan -> execute -> verify -> RESOLVED
    """
    incident_id = str(uuid.uuid4())
    tenant_id = "tenant_prop_10"
    
    events = []
    
    # 运行图流转
    async for event in aiops_service_v2.execute_incident(
        incident_id=incident_id,
        user_input="磁盘空间即将耗尽，请诊断。",
        tenant_id=tenant_id
    ):
        events.append(event)
        
    # 由于使用 MemorySaver，且没触发高风险阻断，工作流应该顺利跑完
    nodes_executed = [e["node"] for e in events if e.get("type") == "workflow_update"]
    
    assert "analyze" in nodes_executed
    assert "plan" in nodes_executed
    assert "execute" in nodes_executed
    assert "verify" in nodes_executed
    assert "resolve" in nodes_executed
    
    # 获取图的最终状态
    final_snapshot = await aiops_service_v2.get_state(incident_id, tenant_id)
    
    assert final_snapshot.values["state"] == SystemState.RESOLVED
    assert final_snapshot.values["risk_level"] == "low"
    assert final_snapshot.values["verified"] is True
    
    # 验证行为日志的记录顺序
    action_logs = [log["action"] for log in final_snapshot.values["action_logs"]]
    assert action_logs == ["analyze", "plan", "execute", "verify"]


@pytest.mark.asyncio
async def test_high_risk_flow_interrupts(mock_llm_high_risk):
    """
    测试点 8.3: 状态机边缘情况 (高危操作中断)
    验证：遇到高危操作，状态图必须挂起（AWAITING_APPROVAL）并在人工干预后继续
    """
    incident_id = str(uuid.uuid4())
    tenant_id = "tenant_high_risk"
    
    events = []
    
    # 第一次运行：应该停在 wait_for_approval，因为高风险
    async for event in aiops_service_v2.execute_incident(
        incident_id=incident_id,
        user_input="数据库无响应，请重启",
        tenant_id=tenant_id
    ):
        events.append(event)
        
    # 检查最后的事件是不是 interrupt
    last_event = events[-1]
    assert last_event.get("type") == "interrupt"
    assert last_event.get("next_node") == "wait_for_approval"
    
    # 状态机停滞在当前状态，等待下一次唤醒
    snapshot = await aiops_service_v2.get_state(incident_id, tenant_id)
    assert snapshot.next == ("wait_for_approval",)
    # (注意: 在真正执行 wait_for_approval 这个节点之前就中断了)
    # 此处 state.values 内的 state 还没有进入 AWAITING_APPROVAL 节点代码，
    # 但根据图设计，当前卡在了 wait_for_approval 前面。
    assert snapshot.next == ("wait_for_approval",)
    assert snapshot.values["risk_level"] == "high"
    
    # 模拟人工批准后唤醒
    await aiops_service_v2.resume_incident(incident_id, tenant_id)
            
    final_snapshot = await aiops_service_v2.get_state(incident_id, tenant_id)
    assert final_snapshot.values["state"] == SystemState.RESOLVED


@pytest.mark.asyncio
async def test_resume_idempotency_property_13(mock_llm_high_risk):
    """
    测试点 9.2: 恢复幂等性 (Property 13)
    验证：使用 Checkpointer 挂起后恢复，不会使得之前的节点被重复执行
    """
    incident_id = str(uuid.uuid4())
    tenant_id = "tenant_idempotency"
    
    # 获取初次中断
    events1 = []
    async for event in aiops_service_v2.execute_incident(
        incident_id=incident_id,
        user_input="高危测试",
        tenant_id=tenant_id
    ):
        events1.append(event)
        
    nodes_executed_1 = [e["node"] for e in events1 if e.get("type") == "workflow_update"]
    assert "analyze" in nodes_executed_1
    assert "plan" in nodes_executed_1
    
    # 模拟断点恢复
    await aiops_service_v2.resume_incident(incident_id, tenant_id)
    
    # 验证最终数据中，action_logs 没有重复的 analyze 和 plan
    final_snapshot = await aiops_service_v2.get_state(incident_id, tenant_id)
    actions = [log["action"] for log in final_snapshot.values["action_logs"]]
    
    # analyze 和 plan 只能出现一次
    assert actions.count("analyze") == 1
    assert actions.count("plan") == 1
    
    # 后续的节点应该出现
    assert "execute" in actions
    assert "verify" in actions


@pytest.mark.asyncio
async def test_checkpointer_fallback():
    """测试点 9.3: 获取 checkpointer 的降级处理"""
    from app.memory.checkpoint import get_checkpointer
    import app.config
    
    # 模拟错误的数据库链接
    original_url = getattr(app.config.config, "database_url", "")
    app.config.config.database_url = "postgresql://fakeuser:fakepass@localhost:1234/fakedb"
    
    try:
        # 当连接无效时，应当被我们的 try-except 包裹并 yield None 进行妥善降级
        async with get_checkpointer() as checkpointer:
            assert checkpointer is None
    finally:
        app.config.config.database_url = original_url
