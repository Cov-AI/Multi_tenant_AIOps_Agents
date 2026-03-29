"""
MCP(Machine-to-Machine 通信客户端) 单元与结构化返回测试
对应 tasks.md: Task 19.2, 19.3
"""

import json
import pytest
from unittest.mock import AsyncMock, patch

from mcp.types import CallToolResult, TextContent
from app.agent.mcp_client import get_mcp_client, retry_interceptor

@pytest.mark.asyncio
async def test_19_3_mcp_integration_mocked():
    """Unit Tests: 测试 MCP 聚合客户端可以正常聚合 mock 的多个 endpoints"""
    
    servers_config = {
        "loki": {"transport": "mock", "url": "http://loki"},
        "prom": {"transport": "mock", "url": "http://prom"}
    }
    
    with patch("app.agent.mcp_client.MultiServerMCPClient") as mock_client:
        mock_instance = AsyncMock()
        mock_client.return_value = mock_instance
        
        client = await get_mcp_client(servers=servers_config, force_new=True)
        assert client == mock_instance
        mock_client.assert_called_once()
        

@pytest.mark.asyncio
async def test_19_2_property_mcp_structured_response():
    """Property 26: MCP 返回结构化数据 - 确保 RetryInterceptor 可以返回统一稳定的结构不会产生崩溃乱码"""
    
    # 构造原始请求结构体
    class MockRequest:
        name = "run_query"
        server_name = "prom"
        
    async def failing_handler(req):
        raise ValueError("Prometheus is unreachable")
        
    # 我们调用拦截器并且看它如何结构化包裹错误返回 (而不是抛出 stacktrace 中断业务流)
    result = await retry_interceptor(MockRequest(), failing_handler, max_retries=1, delay=0.01)
    
    # 验证它是 CallToolResult (因为要兼容 langchain) 并且 isError=True 结构稳定
    assert isinstance(result, CallToolResult)
    assert result.isError is True
    assert "Prometheus is unreachable" in result.content[0].text
