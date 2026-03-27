"""PostgreSQL 数据模型 + RLS 策略

对应 design.md: 数据模型 → PostgreSQL 核心表
对应 tasks.md: Task 1.1 — 创建 PostgreSQL 数据模型和 RLS 策略

包含所有核心表（tenants, users, agents, sessions, incidents,
approvals, token_usage, audit_logs, checkpoints），每张表启用 RLS。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """所有模型的基类"""
    pass


# ---------------------------------------------------------------------------
# RLS helper — 在迁移脚本中执行（Alembic op.execute）
# design.md: "为每张表启用 Row-Level Security（RLS）策略"
# ---------------------------------------------------------------------------

def generate_rls_statements(table_name: str) -> list[str]:
    """为给定表生成 RLS SQL 语句。

    在 Alembic 迁移中调用::

        for stmt in generate_rls_statements("incidents"):
            op.execute(stmt)
    """
    return [
        f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;",
        (
            f"CREATE POLICY tenant_isolation ON {table_name} "
            f"USING (tenant_id = current_setting('app.tenant_id')::uuid);"
        ),
    ]


# RLS 需要覆盖的表（tenants 表本身不需要 RLS）
RLS_TABLES = [
    "users",
    "agents",
    "sessions",
    "incidents",
    "approvals",
    "token_usage",
    "audit_logs",
    "checkpoints",
]


# ---------------------------------------------------------------------------
# tenants — 租户组织
# design.md L584-597
# ---------------------------------------------------------------------------

class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    plan = Column(String(50), nullable=False, default="Free")  # Free/Pro/Enterprise
    api_key = Column(String(255), unique=True, nullable=False)
    quota_requests_per_minute = Column(Integer, nullable=False, default=60)
    quota_tokens_per_month = Column(BigInteger, nullable=False, default=1_000_000)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    agents = relationship("Agent", back_populates="tenant", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_tenants_api_key", "api_key"),
    )


# ---------------------------------------------------------------------------
# users — 用户
# design.md L600-618
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    email = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="Member")  # Admin/Member/Viewer
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="users")

    __table_args__ = (
        Index("idx_users_tenant_id", "tenant_id"),
        # UNIQUE(tenant_id, email) — 同一租户内 email 唯一
        Index("uq_users_tenant_email", "tenant_id", "email", unique=True),
    )


# ---------------------------------------------------------------------------
# agents — AI Agent 实例
# design.md L624-638
# ---------------------------------------------------------------------------

class Agent(Base):
    __tablename__ = "agents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(255), nullable=False)
    # config JSONB 存 workspace：{soul, agents_md, user_md, tools}
    config = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="agents")

    __table_args__ = (
        Index("idx_agents_tenant_id", "tenant_id"),
    )


# ---------------------------------------------------------------------------
# sessions — 对话会话
# design.md L644-663
# ---------------------------------------------------------------------------

class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    agent_id = Column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # session_key 格式: tenant:{tid}:agent:{aid}:{channel}:{user_id}
    session_key = Column(String(255), unique=True, nullable=False)
    token_count = Column(BigInteger, nullable=False, default=0)
    last_active = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_sessions_tenant_id", "tenant_id"),
        Index("idx_sessions_session_key", "session_key"),
        Index("idx_sessions_last_active", "last_active"),
    )


# ---------------------------------------------------------------------------
# incidents — 事故记录
# design.md L666-687
# ---------------------------------------------------------------------------

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    session_id = Column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    # state: triggered/analyzing/awaiting_approval/executing/verifying/resolved/escalated
    state = Column(String(50), nullable=False, default="triggered")
    severity = Column(String(50), nullable=False, default="P2")  # P0/P1/P2/P3
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_incidents_tenant_id", "tenant_id"),
        Index("idx_incidents_state", "state"),
        Index("idx_incidents_created_at", "created_at"),
    )


# ---------------------------------------------------------------------------
# approvals — 审批记录
# design.md L690-715
# ---------------------------------------------------------------------------

class Approval(Base):
    __tablename__ = "approvals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    incident_id = Column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    resume_token = Column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4)
    action = Column(String(255), nullable=False)
    action_payload = Column(JSONB, nullable=False, default=dict)
    completed_steps = Column(JSONB, nullable=False, default=dict)
    # status: pending/approved/rejected/expired
    status = Column(String(50), nullable=False, default="pending")
    requested_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_approvals_tenant_id", "tenant_id"),
        Index("idx_approvals_resume_token", "resume_token"),
        Index("idx_approvals_status", "status"),
    )


# ---------------------------------------------------------------------------
# token_usage — Token 用量记录
# design.md L718-738
# ---------------------------------------------------------------------------

class TokenUsage(Base):
    __tablename__ = "token_usage"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    agent_id = Column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    session_id = Column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    model = Column(String(100), nullable=False)
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_token_usage_tenant_id", "tenant_id"),
        Index("idx_token_usage_created_at", "created_at"),
    )


# ---------------------------------------------------------------------------
# audit_logs — 审计日志
# design.md L742-760
# ---------------------------------------------------------------------------

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    action = Column(String(255), nullable=False)
    resource = Column(String(255), nullable=False)
    payload = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_audit_logs_tenant_id", "tenant_id"),
        Index("idx_audit_logs_created_at", "created_at"),
    )


# ---------------------------------------------------------------------------
# checkpoints — LangGraph Checkpoint 持久化
# design.md L762-779
# ---------------------------------------------------------------------------

class Checkpoint(Base):
    __tablename__ = "checkpoints"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    incident_id = Column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    checkpoint_data = Column(JSONB, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_checkpoints_tenant_id", "tenant_id"),
        Index("idx_checkpoints_incident_id", "incident_id"),
    )
