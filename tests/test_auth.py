"""Task 2.2 — Property Test: JWT Round-Trip + Task 2.3 — Unit Tests: 认证错误处理

对应 design.md: Correctness Properties → Property 1
对应 tasks.md: Task 2.2, 2.3

Property 1: JWT Round-Trip 保持身份信息
  For any 有效的 tenant_id 和 user_id，编码为 JWT 后再解码，
  应得到相同的身份信息。
"""

import uuid
import time

import pytest
from fastapi import HTTPException

from app.auth.jwt import jwt_encode, jwt_decode, TenantContext, TokenPayload
from app.config import config


# ---------------------------------------------------------------------------
# Task 2.2 — Property Test: JWT Round-Trip
# Feature: multi-tenant-oncall-platform, Property 1: JWT Round-Trip 保持身份信息
# ---------------------------------------------------------------------------

class TestJWTRoundTripProperty:
    """Property 1: JWT 编码解码保持身份信息。"""

    @pytest.mark.parametrize("_", range(20))
    def test_jwt_roundtrip_random_ids(self, _):
        """验证随机 tenant_id 和 user_id 编码后解码保持一致。"""
        tenant_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())

        token = jwt_encode({
            "tenant_id": tenant_id,
            "user_id": user_id,
            "role": "Admin",
        })
        decoded = jwt_decode(token)

        assert decoded.tenant_id == tenant_id
        assert decoded.user_id == user_id
        assert decoded.role == "Admin"

    @pytest.mark.parametrize("role", ["Admin", "Member", "Viewer"])
    def test_jwt_roundtrip_all_roles(self, role):
        """验证所有角色都能正确编解码。"""
        payload = {
            "tenant_id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
            "role": role,
        }
        token = jwt_encode(payload)
        decoded = jwt_decode(token)
        assert decoded.role == role

    def test_jwt_default_role(self):
        """验证缺少 role 时默认为 Member。"""
        payload = {
            "tenant_id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
        }
        token = jwt_encode(payload)
        decoded = jwt_decode(token)
        assert decoded.role == "Member"

    def test_jwt_token_is_string(self):
        """验证 JWT token 是字符串格式。"""
        token = jwt_encode({
            "tenant_id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
        })
        assert isinstance(token, str)
        assert len(token) > 0
        # JWT 有三段（header.payload.signature）
        assert token.count(".") == 2


# ---------------------------------------------------------------------------
# Task 2.3 — Unit Tests: 认证错误处理
# ---------------------------------------------------------------------------

class TestJWTErrorHandling:
    """测试 JWT 认证的错误处理。"""

    def test_invalid_token_raises_401(self):
        """测试无效 JWT（随机字符串）。"""
        with pytest.raises(HTTPException) as exc_info:
            jwt_decode("invalid.token.string")
        assert exc_info.value.status_code == 401

    def test_empty_token_raises_401(self):
        """测试空 token。"""
        with pytest.raises(HTTPException) as exc_info:
            jwt_decode("")
        assert exc_info.value.status_code == 401

    def test_missing_tenant_id_raises_401(self):
        """测试缺少 tenant_id 字段。"""
        import jwt as pyjwt
        # 手动编码一个缺少 tenant_id 的 token
        token = pyjwt.encode(
            {"user_id": "test", "exp": time.time() + 3600},
            config.jwt_secret,
            algorithm=config.jwt_algorithm,
        )
        with pytest.raises(HTTPException) as exc_info:
            jwt_decode(token)
        assert exc_info.value.status_code == 401

    def test_missing_user_id_raises_401(self):
        """测试缺少 user_id 字段。"""
        import jwt as pyjwt
        token = pyjwt.encode(
            {"tenant_id": "test", "exp": time.time() + 3600},
            config.jwt_secret,
            algorithm=config.jwt_algorithm,
        )
        with pytest.raises(HTTPException) as exc_info:
            jwt_decode(token)
        assert exc_info.value.status_code == 401

    def test_expired_token_raises_401(self):
        """测试过期 token。"""
        import jwt as pyjwt
        token = pyjwt.encode(
            {
                "tenant_id": "test",
                "user_id": "test",
                "exp": time.time() - 3600,  # 已过期
            },
            config.jwt_secret,
            algorithm=config.jwt_algorithm,
        )
        with pytest.raises(HTTPException) as exc_info:
            jwt_decode(token)
        assert exc_info.value.status_code == 401
        assert "过期" in exc_info.value.detail

    def test_wrong_secret_raises_401(self):
        """测试用错误密钥签名的 token。"""
        import jwt as pyjwt
        token = pyjwt.encode(
            {
                "tenant_id": "test",
                "user_id": "test",
                "exp": time.time() + 3600,
            },
            "wrong-secret-key",
            algorithm=config.jwt_algorithm,
        )
        with pytest.raises(HTTPException) as exc_info:
            jwt_decode(token)
        assert exc_info.value.status_code == 401

    def test_valid_token_returns_payload(self):
        """测试有效 token 返回正确信息。"""
        tenant_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        token = jwt_encode({
            "tenant_id": tenant_id,
            "user_id": user_id,
            "role": "Viewer",
        })
        result = jwt_decode(token)
        assert isinstance(result, TokenPayload)
        assert result.tenant_id == tenant_id
        assert result.user_id == user_id
        assert result.role == "Viewer"
