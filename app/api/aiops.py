"""
AIOps 智能运维接口
"""

import json
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
from loguru import logger

from app.models.aiops import AIOpsRequest
from app.services.aiops_service import aiops_service
from app.agent.aiops_v2.service import aiops_service_v2
from app.workflow.approval import ApprovalManager

from pydantic import BaseModel
class ApprovalRequest(BaseModel):
    decision: str  # "approve" or "reject"
    tenant_id: str = "default_tenant"

router = APIRouter()


@router.post("/aiops")
async def diagnose_stream(request: AIOpsRequest):
    """
    AIOps 故障诊断接口（流式 SSE）

    **功能说明：**
    - 自动获取当前系统的活动告警
    - 使用 Plan-Execute-Replan 模式进行智能诊断
    - 流式返回诊断过程和结果

    **SSE 事件类型：**

    1. `status` - 状态更新
       ```json
       {
         "type": "status",
         "stage": "fetching_alerts",
         "message": "正在获取系统告警信息..."
       }
       ```

    2. `plan` - 诊断计划制定完成
       ```json
       {
         "type": "plan",
         "stage": "plan_created",
         "message": "诊断计划已制定，共 6 个步骤",
         "target_alert": {...},
         "plan": ["步骤1: ...", "步骤2: ..."]
       }
       ```

    3. `step_complete` - 步骤执行完成
       ```json
       {
         "type": "step_complete",
         "stage": "step_executed",
         "message": "步骤执行完成 (2/6)",
         "current_step": "查询系统日志",
         "result_preview": "...",
         "remaining_steps": 4
       }
       ```

    4. `report` - 最终诊断报告
       ```json
       {
         "type": "report",
         "stage": "final_report",
         "message": "最终诊断报告已生成",
         "report": "# 故障诊断报告\\n...",
         "evidence": {...}
       }
       ```

    5. `complete` - 诊断完成
       ```json
       {
         "type": "complete",
         "stage": "diagnosis_complete",
         "message": "诊断流程完成",
         "diagnosis": {...}
       }
       ```

    6. `error` - 错误信息
       ```json
       {
         "type": "error",
         "stage": "error",
         "message": "诊断过程发生错误: ..."
       }
       ```

    **使用示例：**
    ```bash
    curl -X POST "http://localhost:9900/api/aiops" \\
      -H "Content-Type: application/json" \\
      -d '{"session_id": "session-123"}' \\
      --no-buffer
    ```

    **前端使用示例：**
    ```javascript
    const eventSource = new EventSource('/api/aiops');

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === 'plan') {
        console.log('诊断计划:', data.plan);
      } else if (data.type === 'step_complete') {
        console.log('步骤完成:', data.current_step);
      } else if (data.type === 'report') {
        console.log('最终报告:', data.report);
      } else if (data.type === 'complete') {
        console.log('诊断完成');
        eventSource.close();
      }
    };
    ```

    Args:
        request: AIOps 诊断请求

    Returns:
        SSE 事件流
    """
    session_id = request.session_id or "default"
    logger.info(f"[会话 {session_id}] 收到 AIOps 诊断请求（流式）")

    async def event_generator():
        try:
            async for event in aiops_service.diagnose(session_id=session_id):
                # 发送事件
                yield {
                    "event": "message",
                    "data": json.dumps(event, ensure_ascii=False)
                }

                # 如果是完成或错误事件，结束流
                if event.get("type") in ["complete", "error"]:
                    break

            logger.info(f"[会话 {session_id}] AIOps 诊断流式响应完成")

        except Exception as e:
            logger.error(f"[会话 {session_id}] AIOps 诊断流式响应异常: {e}", exc_info=True)
            yield {
                "event": "message",
                "data": json.dumps({
                    "type": "error",
                    "stage": "exception",
                    "message": f"诊断异常: {str(e)}"
                }, ensure_ascii=False)
            }

    return EventSourceResponse(event_generator())


@router.post("/aiops/approval/{resume_token}")
async def resolve_approval(resume_token: str, request: ApprovalRequest):
    """
    处理高危操作的审批流。
    接收 approve 或 reject 并唤醒 StateGraph。
    """
    logger.info(f"收到审批请求: Token={resume_token}, 决定={request.decision}")
    
    # 1. 验证和更新 Token 记录
    approval_result = await ApprovalManager.resolve_approval(
        token=resume_token,
        tenant_id=request.tenant_id,
        decision=request.decision
    )
    
    if not approval_result:
        return {"status": "error", "message": "Failed to find or process token."}
        
    # 如果通过审批，则唤醒图
    if request.decision == "approve":
        incident_id = approval_result["incident_id"]
        # 目前将它放到后台执行，如有需要可以重构成 SSE
        import asyncio
        asyncio.create_task(
            aiops_service_v2.resume_incident(incident_id=incident_id, tenant_id=request.tenant_id)
        )
        return {"status": "success", "message": "Approval accepted. Resuming workflow."}
    else:
        return {"status": "success", "message": "Approval rejected. Workflow remains paused/aborted."}


class TriggerRequest(BaseModel):
    session_id: str = "default_session"
    tenant_id: str = "default_tenant"
    incident_content: str = "CPU usage is at 99%"

@router.post("/aiops/trigger")
async def trigger_incident(request: TriggerRequest):
    """
    新建并触发 P1 StateGraph 的全流程处理（Task 13 最小可运行 Demo）
    """
    logger.info(f"触发新突发事件: {request.incident_content}")
    # 因为 P1 还没有完整的 Incident 持久层依赖，我们传入伪造的 incident_id
    import uuid
    incident_id = str(uuid.uuid4())
    
    # 异步触发流程
    import asyncio
    asyncio.create_task(
        aiops_service_v2.execute_incident(
            incident_id=incident_id,
            tenant_id=request.tenant_id,
            session_id=request.session_id,
            content=request.incident_content
        )
    )
    return {"status": "success", "incident_id": incident_id, "message": "Incident workflow triggered in background."}
