"""
安全审计日志收集
对应 tasks.md: Task 17.1 (记录所有高危操作及其 payload)
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.storage.database import tenant_session
from app.storage.models import AuditLog


class AuditLogger:
    """提供通用的方式来录入高危和重要系统的状态变更日志至物理表以备查"""
    
    @staticmethod
    async def log_action(
        tenant_id: str,
        user_id: str,
        action: str,
        resource: str,
        payload: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        录入一行审计日志
        :param tenant_id: 租户标识
        :param user_id: 做出改动的实体, 如 Admin-ID 或 Webhook
        :param action: "APPROVE", "TRIGGER", "RESTART"
        :param resource: 作用于的资源标志，如 IncidentID, Server-IP
        :param payload: 操作附带的具体元数据 JSON
        """
        payload = payload or {}
        try:
            async with tenant_session(tenant_id) as session:
                audit = AuditLog(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    action=action,
                    resource=resource,
                    payload=payload
                )
                session.add(audit)
                await session.commit()
            
            # 同时将关键审计操作打印出以便 Loki/EFK 即时抓取
            logger.info(f"[AUDIT] Tenant:{tenant_id} User:{user_id} Action:{action} Resource:{resource} Payload:{payload}")
            return True
        except Exception as e:
            # 审计如果失败，取决于业务逻辑。这里我们吞咽错误防止阻塞主干，但记录大号严重异常
            logger.critical(f"[AUDIT FAIL] 无法记录审计日志! {e}")
            return False
