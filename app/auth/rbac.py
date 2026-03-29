"""
RBAC 角色鉴权模块
对应 tasks.md: Task 16.1 
定义了 Admin/Member/Viewer 体系并提供了 FastAPI Depends。
"""

from typing import Callable, List
from fastapi import HTTPException, status, Depends
from loguru import logger

from app.auth.jwt import get_current_tenant, TenantContext


class RoleDefinition:
    """定义系统中默认角色的等级"""
    ADMIN = "Admin"
    MEMBER = "Member"
    VIEWER = "Viewer"


# 角色的向下兼容等级
ROLE_HIERARCHY = {
    RoleDefinition.ADMIN: [RoleDefinition.ADMIN, RoleDefinition.MEMBER, RoleDefinition.VIEWER],
    RoleDefinition.MEMBER: [RoleDefinition.MEMBER, RoleDefinition.VIEWER],
    RoleDefinition.VIEWER: [RoleDefinition.VIEWER],
}


def require_role(allowed_roles: List[str]) -> Callable:
    """
    FastAPI Depends: 用于验证当前租户上下文中的 role。
    
    使用方法：
    @router.post("/critical/action")
    async def critical_action(tenant: TenantContext = Depends(require_role(["Admin"]))):
        ...
    """
    async def role_checker(
        tenant_context: TenantContext = Depends(get_current_tenant)
    ) -> TenantContext:
        user_role = tenant_context.role
        
        # 找到用户扮演角色所有拥有的权限列表包容项
        inherited_roles = ROLE_HIERARCHY.get(user_role, [])
        
        # 检查是否满足
        has_access = any(required in inherited_roles for required in allowed_roles)
        
        if not has_access:
            logger.warning(
                f"[RBAC Deny] 租户 {tenant_context.tenant_id} 的用户 {tenant_context.user_id} "
                f"因为角色 ({user_role}) 不足, 被拦截访问需 ({allowed_roles}) 的资源."
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"没有足够的权限。该操作需要角色: {', '.join(allowed_roles)}。你的实际角色: {user_role}",
            )
            
        return tenant_context
        
    return role_checker
