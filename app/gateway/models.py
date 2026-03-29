"""
Gateway 请求/响应的数据模型
包含 统一消息封套 (MessageEnvelope) 与 Webhook/Slack 的结构体
对应 tasks.md: Task 14.1
"""

from typing import Literal, Dict, Any, Optional
from pydantic import BaseModel, Field


class MessageEnvelope(BaseModel):
    """归一化后的统一消息体，抹平不同进入渠道的差异"""
    tenant_id: str = Field(description="对应请求头的 JWT tenant_id")
    user_id: str = Field(description="对应请求头的 JWT user_id")
    agent_id: str = Field(description="调用的 Agent ID")
    session_id: str = Field(description="会话标识")
    source: Literal["webhook", "slack", "api"] = Field(description="信号来源")
    content: str = Field(description="用户纯文本或告警核心摘要")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="额外原始信息 (例如告警全部报文)")


class WebhookAlertPayload(BaseModel):
    """标准的监控系统回调数据"""
    title: str
    description: str
    severity: Literal["critical", "warning", "info"] = "warning"
    tags: Dict[str, str] = Field(default_factory=dict)
    
class SlackEventPayload(BaseModel):
    """Slack 发送来的用户聊天事件"""
    type: str # 例如 message
    user: str
    text: str
    channel: str
    ts: str
