"""
RBAC 单元测试与越权保护机制测试
对应 tasks.md: Task 16.2
"""

import pytest
from fastapi import FastAPI, Depends, APIRouter
from fastapi.testclient import TestClient

from app.auth.jwt import jwt_encode
from app.auth.rbac import require_role

# 1. 设置一个微型应用使用 RBAC 测试
mock_app = FastAPI()
rbac_router = APIRouter()

@rbac_router.get("/admin-only")
async def only_admin(tenant=Depends(require_role(["Admin"]))):
    return {"message": "success_admin"}
    
@rbac_router.get("/member-only")
async def only_member(tenant=Depends(require_role(["Member"]))):
    return {"message": "success_member"}
    
@rbac_router.get("/viewer-only")
async def only_viewer(tenant=Depends(require_role(["Viewer"]))):
    return {"message": "success_viewer"}

mock_app.include_router(rbac_router)

client = TestClient(mock_app)

def get_auth_headers(role: str):
    token = jwt_encode({"tenant_id": "T1", "user_id": "U1", "role": role})
    return {"Authorization": f"Bearer {token}"}

def test_16_2_rbac_strict_boundaries():
    """Unit Tests: RBAC 角色越权限制测试"""
    # 模拟客户端身份分别为 Admin, Member, Viewer
    headers_admin = get_auth_headers("Admin")
    headers_member = get_auth_headers("Member")
    headers_viewer = get_auth_headers("Viewer")
    
    # 1. Admin 可以访问所有的资源
    res = client.get("/admin-only", headers=headers_admin)
    assert res.status_code == 200
    res = client.get("/member-only", headers=headers_admin)
    assert res.status_code == 200
    res = client.get("/viewer-only", headers=headers_admin)
    assert res.status_code == 200
    
    # 2. Member 可以访问 Member 和 Viewer, 但禁止 Admin
    res = client.get("/admin-only", headers=headers_member)
    assert res.status_code == 403
    assert "没有足够的权限" in res.json()["detail"]
    
    res = client.get("/member-only", headers=headers_member)
    assert res.status_code == 200
    
    # 3. Viewer 只能查看看权限
    res = client.get("/admin-only", headers=headers_viewer)
    assert res.status_code == 403
    res = client.get("/member-only", headers=headers_viewer)
    assert res.status_code == 403
    res = client.get("/viewer-only", headers=headers_viewer)
    assert res.status_code == 200
