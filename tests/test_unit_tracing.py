"""
LangSmith Telemetry (追踪配置) 测试组件
对应 tasks.md: Task 20.2, 20.3
"""

import os
from unittest.mock import patch

from app.observability.tracing import TracingManager

def test_20_2_langsmith_metadata_injection():
    """Property 28: 验证配置注入结构符合 Langsmith API Requirements"""
    
    tenant_id = "tenant-007"
    incident_id = "inc-404"
    
    # 手动设定一个环境常量看它能不能顺利吸附过去
    with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
        config = TracingManager.get_langgraph_config(tenant_id, incident_id)
        
        # 必须含有三件套：configurable, metadata, tags
        assert "configurable" in config
        assert "metadata" in config
        assert "tags" in config
        
        # 验证 configurable 防止 checkpoint 撞车串联
        assert config["configurable"]["thread_id"] == incident_id
        assert config["configurable"]["tenant_id"] == tenant_id
        
        # 验证 metadata 用于 langsmith 可视化查询
        assert config["metadata"]["incident_id"] == incident_id
        assert config["metadata"]["environment"] == "production"
        
        # 验证 tags
        assert f"tenant:{tenant_id}" in config["tags"]


def test_20_3_langsmith_api_key_absence_fallback():
    """Unit Tests: 当 LangChain_API_KEY 无效或没有配置时不能影响系统主权"""
    
    with patch.dict(os.environ, {}, clear=True):  # 清空环境以去掉 KEY
        with patch("app.observability.tracing.logger.debug") as mock_debug:
            config = TracingManager.get_langgraph_config("t", "i")
            
            # 它必须能够平安出来
            assert "configurable" in config
            
            # 应该有一条 debug 日志提醒管理员
            mock_debug.assert_called_once()
            assert "未检测到 LANGCHAIN_API_KEY" in mock_debug.call_args[0][0]
