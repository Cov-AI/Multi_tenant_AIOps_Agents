"""
网关入口相关功能单元测试及属性测试
对应 tasks.md: Task 14.2, 14.3, 14.4
"""

import pytest
from fastapi.testclient import TestClient

from app.gateway.server import app
from app.gateway.models import MessageEnvelope, WebhookAlertPayload, SlackEventPayload
from app.agents.supervisor import supervisor
from app.auth.jwt import jwt_encode

client = TestClient(app)

# 构造合法的测试 JWT
def get_auth_headers(tenant_id="test_tenant", user_id="test_user", role="Admin"):
    token = jwt_encode({"tenant_id": tenant_id, "user_id": user_id, "role": role})
    return {"Authorization": f"Bearer {token}"}

def test_14_3_message_normalization():
    """Property 23: Message Normalization"""
    # 验证不同的源都能被映射到 MessageEnvelope
    env1 = MessageEnvelope(
        tenant_id="t1",
        user_id="u1",
        agent_id="system",
        session_id="s1",
        source="webhook",
        content="something bad",
        metadata={"a": 1}
    )
    assert env1.source == "webhook"
    
    # 无效 Source 则 Pydantic 会抛错
    with pytest.raises(ValueError):
        MessageEnvelope(
            tenant_id="t1",
            user_id="u1",
            agent_id="system",
            session_id="s1",
            source="unknown", # type: ignore
            content="something bad",
        )

def test_14_2_message_routing():
    """Property 22: Message routing (Supervisor intent tracking)"""
    
    # Webhook 总是走 AIOps
    env_webhook = MessageEnvelope(
        tenant_id="1", user_id="1", agent_id="1", session_id="1",
        source="webhook", content="just info"
    )
    assert supervisor.classify_intent(env_webhook) == "aiops"

    # Slack 普通对话走 chat
    env_chat = MessageEnvelope(
        tenant_id="1", user_id="1", agent_id="1", session_id="1",
        source="slack", content="hi, how are you?"
    )
    assert supervisor.classify_intent(env_chat) == "chat"
    
    # Slack 触发告警关键字走 AIOps
    env_trigger = MessageEnvelope(
        tenant_id="1", user_id="1", agent_id="1", session_id="1",
        source="slack", content="请帮忙重启发生 error 500 的服务器"
    )
    assert supervisor.classify_intent(env_trigger) == "aiops"

def test_14_4_gateway_webhook_endpoint():
    """Unit Tests: Gateway 集成测试"""
    headers = get_auth_headers()
    
    payload = {
        "title": "CPU Spike",
        "description": "Server 1 is at 99%",
        "severity": "critical"
    }
    
    response = client.post("/gateway/webhook/alert", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    
def test_14_4_gateway_slack_endpoint():
    """Unit Tests: Gateway Slack 解析集成了 JWT 测试"""
    headers = get_auth_headers("tenant-c", "user-d")
    
    payload = {
        "type": "message",
        "user": "U123456",
        "text": "help me with my alert",
        "channel": "C123456",
        "ts": "123456789.00"
    }
    
    response = client.post("/gateway/slack/events", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"

def test_14_4_gateway_no_auth():
    """测试当缺少 JWT 时候中间件被阻拦"""
    payload = {
        "title": "CPU Spike",
        "description": "Server 1 is at 99%",
        "severity": "critical"
    }
    # 不带有 Auth
    response = client.post("/gateway/webhook/alert", json=payload)
    assert response.status_code == 401
