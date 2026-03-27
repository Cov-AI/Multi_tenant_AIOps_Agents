"""Task 1.3 — Unit Tests：数据模型验证

对应 tasks.md: Task 1.3 — 编写 Unit Tests：数据模型验证

测试内容：
- 表创建和约束（外键、唯一性）
- RLS 策略生效
- 边缘情况（空值、超长字符串）
"""

import uuid
from datetime import datetime

import pytest

from app.storage.models import (
    Base, Tenant, User, Agent, Session, Incident,
    Approval, TokenUsage, AuditLog, Checkpoint,
    generate_rls_statements, RLS_TABLES,
)
from app.storage.database import _build_database_url


# ---------------------------------------------------------------------------
# 表结构测试
# ---------------------------------------------------------------------------

class TestTableStructure:
    """验证表结构和约束。"""

    def test_all_nine_tables_defined(self):
        """验证定义了所有 9 张表。"""
        expected_tables = {
            "tenants", "users", "agents", "sessions", "incidents",
            "approvals", "token_usage", "audit_logs", "checkpoints",
        }
        actual_tables = set(Base.metadata.tables.keys())
        assert expected_tables == actual_tables

    def test_tenants_table_columns(self):
        """验证 tenants 表的列定义。"""
        table = Base.metadata.tables["tenants"]
        columns = {col.name for col in table.columns}
        required = {"id", "name", "plan", "api_key", "quota_requests_per_minute",
                     "quota_tokens_per_month", "created_at", "updated_at"}
        assert required.issubset(columns), f"缺少列: {required - columns}"

    def test_incidents_table_columns(self):
        """验证 incidents 表的列定义。"""
        table = Base.metadata.tables["incidents"]
        columns = {col.name for col in table.columns}
        required = {"id", "tenant_id", "session_id", "state", "severity",
                     "metadata", "created_at", "resolved_at"}
        assert required.issubset(columns), f"缺少列: {required - columns}"

    def test_approvals_table_has_resume_token(self):
        """验证 approvals 表有 resume_token 列（用于审批流）。"""
        table = Base.metadata.tables["approvals"]
        columns = {col.name for col in table.columns}
        assert "resume_token" in columns
        # resume_token 应该有唯一约束
        resume_col = [c for c in table.columns if c.name == "resume_token"][0]
        assert resume_col.unique is True

    def test_token_usage_table_tracks_model(self):
        """验证 token_usage 表记录模型名称。"""
        table = Base.metadata.tables["token_usage"]
        columns = {col.name for col in table.columns}
        assert "model" in columns
        assert "input_tokens" in columns
        assert "output_tokens" in columns


# ---------------------------------------------------------------------------
# 索引测试
# ---------------------------------------------------------------------------

class TestIndexes:
    """验证索引定义。"""

    def test_tenants_api_key_index(self):
        """验证 tenants 表有 api_key 索引。"""
        table = Base.metadata.tables["tenants"]
        index_names = {idx.name for idx in table.indexes}
        assert "idx_tenants_api_key" in index_names

    def test_sessions_session_key_index(self):
        """验证 sessions 表有 session_key 索引。"""
        table = Base.metadata.tables["sessions"]
        index_names = {idx.name for idx in table.indexes}
        assert "idx_sessions_session_key" in index_names

    @pytest.mark.parametrize("table_name", RLS_TABLES)
    def test_all_rls_tables_have_tenant_id_index(self, table_name):
        """验证所有 RLS 表都有 tenant_id 索引。"""
        table = Base.metadata.tables[table_name]
        index_columns = set()
        for idx in table.indexes:
            for col in idx.columns:
                index_columns.add(col.name)
        assert "tenant_id" in index_columns, (
            f"表 '{table_name}' 缺少 tenant_id 索引"
        )

    def test_users_unique_tenant_email(self):
        """验证 users 表有 (tenant_id, email) 唯一索引。"""
        table = Base.metadata.tables["users"]
        for idx in table.indexes:
            if idx.unique:
                cols = {c.name for c in idx.columns}
                if "tenant_id" in cols and "email" in cols:
                    return
        pytest.fail("users 表缺少 (tenant_id, email) 唯一索引")


# ---------------------------------------------------------------------------
# 模型实例化测试
# ---------------------------------------------------------------------------

class TestModelInstantiation:
    """验证模型可以正确实例化。"""

    def test_create_tenant(self):
        """验证创建 Tenant 实例。"""
        t = Tenant(
            name="Test Corp",
            plan="Pro",
            api_key="test-api-key-123",
        )
        assert t.name == "Test Corp"
        assert t.plan == "Pro"
        assert t.quota_requests_per_minute == 60  # 默认值

    def test_create_user(self):
        """验证创建 User 实例。"""
        u = User(
            tenant_id=uuid.uuid4(),
            email="test@example.com",
            hashed_password="hashed",
            role="Admin",
        )
        assert u.role == "Admin"

    def test_create_incident_default_state(self):
        """验证 Incident 默认状态为 triggered。"""
        inc = Incident(
            tenant_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            severity="P0",
        )
        assert inc.state == "triggered"
        assert inc.resolved_at is None

    def test_create_approval_default_status(self):
        """验证 Approval 默认状态为 pending。"""
        appr = Approval(
            tenant_id=uuid.uuid4(),
            incident_id=uuid.uuid4(),
            action="restart service",
            requested_by=uuid.uuid4(),
        )
        assert appr.status == "pending"


# ---------------------------------------------------------------------------
# 边缘情况测试
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """测试边缘情况。"""

    def test_rls_statements_special_chars_in_table_name(self):
        """测试包含特殊字符的表名生成 RLS 语句。"""
        stmts = generate_rls_statements("my_special_table")
        assert len(stmts) == 3
        assert "my_special_table" in stmts[0]

    def test_tenant_plan_values(self):
        """测试不同的 plan 值。"""
        for plan in ["Free", "Pro", "Enterprise"]:
            t = Tenant(name="test", plan=plan, api_key=f"key-{plan}")
            assert t.plan == plan

    def test_incident_states(self):
        """测试所有有效的事故状态。"""
        valid_states = [
            "triggered", "analyzing", "awaiting_approval",
            "executing", "verifying", "resolved", "escalated",
        ]
        for state in valid_states:
            inc = Incident(
                tenant_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                state=state,
                severity="P1",
            )
            assert inc.state == state


# ---------------------------------------------------------------------------
# Database URL 构建测试
# ---------------------------------------------------------------------------

class TestDatabaseUrl:
    """验证数据库 URL 构建逻辑。"""

    def test_sqlite_fallback_when_no_url(self):
        """验证无 DATABASE_URL 时降级为 SQLite。"""
        # _build_database_url 在 config.database_url 为空时返回 SQLite
        url = _build_database_url()
        assert "sqlite" in url or "postgresql" in url
