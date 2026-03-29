"""
统一接入网关路由
处理外部的 Webhook、Slack 等集成
对应 tasks.md: Task 14.1 (实现消息路由逻辑、Webhook / Slack 接入)
"""

import uuid
from typing import Dict, Any

from fastapi import APIRouter, Request, BackgroundTasks, Header, HTTPException, Depends
from loguru import logger

from app.gateway.models import MessageEnvelope, WebhookAlertPayload, SlackEventPayload
from app.agents.supervisor import supervisor

# 如果以后会有专门的回调系统，这里负责拉起异步的实际服务
from app.agent.aiops_v2.service import aiops_service_v2
from app.api.chat import chat
from app.models.request import ChatRequest

from app.auth.jwt import get_current_tenant, TenantContext

router = APIRouter(prefix="/gateway", tags=["接入网关层"])

@router.post("/webhook/alert")
async def webhook_alert(
    payload: WebhookAlertPayload, 
    background_tasks: BackgroundTasks,
    tenant_context: TenantContext = Depends(get_current_tenant)
):
    """
    监控报警 (如 Datadog/Prometheus) 专用的触发管道
    """
    session_id = str(uuid.uuid4())
    
    # 将输入归一化为统一格式 (MessageEnvelope)
    envelope = MessageEnvelope(
        tenant_id=tenant_context.tenant_id,
        user_id=tenant_context.user_id,
        agent_id="system_webhook",
        session_id=session_id,
        source="webhook",
        content=f"监控报警: [{payload.severity}] {payload.title} - {payload.description}",
        metadata={"tags": payload.tags, "raw_alert": payload.model_dump()}
    )
    
    _process_envelope_background(envelope, background_tasks)
    return {"status": "accepted", "session_id": session_id, "message": "Webhook received, enqueued for processing"}


@router.post("/slack/events")
async def slack_events(
    payload: SlackEventPayload, 
    background_tasks: BackgroundTasks,
    tenant_context: TenantContext = Depends(get_current_tenant)
):
    """
    Slack 端机器人事件的触发管道
    """
    session_id = payload.channel
    
    # 归一化
    envelope = MessageEnvelope(
        tenant_id=tenant_context.tenant_id,
        user_id=payload.user, # Slack UID
        agent_id="system_slack",
        session_id=session_id,
        source="slack",
        content=payload.text,
        metadata={"timestamp": payload.ts}
    )
    
    _process_envelope_background(envelope, background_tasks)
    return {"status": "accepted", "session_id": session_id}


def _process_envelope_background(envelope: MessageEnvelope, background_tasks: BackgroundTasks):
    """根据主管分类进行内部背景流转分配"""
    target = supervisor.classify_intent(envelope)
    
    if target == "aiops":
        # 如果是 AIOps，我们向后台推入 故障的恢复生命周期
        # aiops_service_v2 为 generator 故此处需要封一个 wrapper
        import asyncio
        async def wrap_generator():
            try:
                # 把 AIOps V2 执行启动起来
                incident_id = str(uuid.uuid4())
                logger.info(f"==> Gateway 启用 AIOps ({incident_id}) 分发")
                async for event in aiops_service_v2.execute_incident(
                    incident_id=incident_id,
                    tenant_id=envelope.tenant_id,
                    session_id=envelope.session_id,
                    content=envelope.content
                ):
                    # 其实如果是 Slack 或 Webhook，应该有 outbound webhook 将进度回传，为了 P2 验证简化可先 logging
                    pass
            except Exception as e:
                logger.error(f"网关层 AIOps 崩溃: {e}", exc_info=True)
                
        background_tasks.add_task(wrap_generator)
    else:
        # 常规聊天推入普通对话逻辑（现存 api 的实现）
        # api/chat.py 中目前没有一个直接暴露函数签名而是一个路由器
        # 这里仅模拟打进去或用现成包。在 P2 仅负责流转结构完备。
        logger.info(f"==> Gateway 放行至 Chat 系统 (Not Implemented details for background in P1)")
