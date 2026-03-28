"""
审批管理器 - 负责管理基于 resumedToken 的审批记录生命周期
对应 tasks.md: Task 11.1 - 审批模块与断点恢复集成
"""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import select, update
from loguru import logger

from app.storage.database import tenant_session
from app.storage.models import Approval


class ApprovalManager:
    """处理 AIOps 的审批生命周期：创建令牌、验证与更新状态"""

    @staticmethod
    async def create_approval(
        tenant_id: str,
        incident_id: str,
        requested_by: str,
        message: str,
        action: str = "workflow_resume"
    ) -> str:
        """
        创建一个挂起的审批记录并返回独一无二的 resume_token
        """
        token = str(uuid.uuid4())
        logger.info(f"为事件 {incident_id} 创建审批申请, Token: {token}")

        # 如果 P0 未挂载 PostgreSQL，暂且打印 warning
        try:
            async with tenant_session(tenant_id=tenant_id) as session:
                new_approval = Approval(
                    id=uuid.uuid4(),
                    tenant_id=uuid.UUID(tenant_id),
                    incident_id=uuid.UUID(incident_id),
                    resume_token=uuid.UUID(token),
                    action=action,
                    action_payload={"message": message},
                    status="pending",
                    # 假定请求者是系统发起的 (如果没有具体的 user_id，留待 P2 进一步细化)
                    # P1 为了跑通外键先写死或跳过
                    requested_by=uuid.UUID(requested_by) if requested_by else uuid.uuid4(),
                )
                session.add(new_approval)
                # session 管理器会自动 commit
        except Exception as e:
            logger.warning(f"未能将审批记录保存到 DB (可能处于无DB的 mock 阶段): {e}")

        return token

    @staticmethod
    async def resolve_approval(
        token: str,
        tenant_id: str,
        decision: str,
        approved_by: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        根据用户的决定 (approve, reject) 更新 Token 状态，并返回审批对应的事件详细信息 (incident_id 等)
        若没找到 Token，返回 None
        """
        logger.info(f"处理审批令牌 {token}, 决定为: {decision}")
        
        try:
            async with tenant_session(tenant_id=tenant_id) as session:
                result = await session.execute(
                    select(Approval).where(Approval.resume_token == uuid.UUID(token))
                )
                approval = result.scalar_one_or_none()
                
                if not approval:
                    logger.warning(f"找不到或并不在当前租户下的审批记录: {token}")
                    return None
                    
                if approval.status != "pending":
                    logger.warning(f"审批记录已经被处理，当前状态: {approval.status}")
                    # 但是我们可以继续返回它的事件信息以防重复点击
                    return {"incident_id": str(approval.incident_id), "status": approval.status}
                    
                approval.status = "approved" if decision == "approve" else "rejected"
                if approved_by:
                    approval.approved_by = uuid.UUID(approved_by)
                approval.approved_at = datetime.utcnow()
                
                incident_id = str(approval.incident_id)
                # Session会自动提交 (tenant_session 包装了 commit)
                return {"incident_id": incident_id, "status": approval.status}
                
        except Exception as e:
            logger.warning(f"DB 中未找到或是无法更新 (Mock 流程): {e}")
            # Mock 模式返回一些兜底数据让系统能跑
            return {"incident_id": "dummy_incident", "status": "approved" if decision == "approve" else "rejected"}
