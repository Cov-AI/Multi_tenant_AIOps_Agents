"""数据库连接池 + 租户上下文管理

对应 design.md: 模块架构 → storage/database.py
对应 tasks.md: Task 1.5 — 创建数据库连接池和租户上下文管理

核心职责：
- async SQLAlchemy session factory + 连接池
- set_tenant_context(tenant_id) — SET LOCAL app.tenant_id
- 连接归还时清除 app.tenant_id（连接池复用安全）

RLS 依赖此模块才能正确工作。
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from loguru import logger

from app.config import config


# ---------------------------------------------------------------------------
# Engine & Session Factory
# ---------------------------------------------------------------------------

def _build_database_url() -> str:
    """从配置构建异步数据库连接 URL。

    config.database_url 示例: postgresql://user:pass@localhost:5432/oncall
    异步驱动需要 postgresql+asyncpg://...
    """
    url = getattr(config, "database_url", "")
    if not url:
        # P0 阶段：允许没有数据库（单元测试 / 开发时使用 SQLite 或 mock）
        logger.warning("DATABASE_URL 未配置，数据库功能将不可用")
        return "sqlite+aiosqlite:///./oncall_dev.db"

    # 自动替换同步驱动为异步驱动
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """获取全局数据库引擎（懒初始化）"""
    global _engine
    if _engine is None:
        db_url = _build_database_url()
        _engine = create_async_engine(
            db_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=getattr(config, "debug", False),
        )
        logger.info(f"数据库引擎已创建: {db_url.split('@')[-1] if '@' in db_url else db_url}")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """获取全局 Session 工厂（懒初始化）"""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


# ---------------------------------------------------------------------------
# Tenant Context — RLS 上下文注入
# design.md: "JWT 中间件解析 tenant_id，注入数据库连接上下文"
# ---------------------------------------------------------------------------

@asynccontextmanager
async def tenant_session(tenant_id: str) -> AsyncGenerator[AsyncSession, None]:
    """创建带租户上下文的数据库 session。

    使用方式::

        async with tenant_session(tenant_id) as session:
            result = await session.execute(select(Incident))
            # RLS 自动过滤，只返回当前 tenant 的数据

    实现要点：
    1. SET LOCAL app.tenant_id — 仅对当前事务有效
    2. 事务结束后自动清除（SET LOCAL 的语义），连接归还安全
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            # 在事务开始时注入 tenant 上下文
            # SET LOCAL 仅对当前事务有效，事务结束自动清除
            await session.execute(
                text("SET LOCAL app.tenant_id = :tid"),
                {"tid": str(tenant_id)},
            )
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def admin_session() -> AsyncGenerator[AsyncSession, None]:
    """创建无租户过滤的管理员 session（绕过 RLS）。

    仅用于：
    - 创建新租户
    - 跨租户管理操作
    - 数据库迁移

    注意：此 session 不设置 app.tenant_id，
    需要超级用户或 RLS BYPASSRLS 权限。
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

async def init_db() -> None:
    """初始化数据库（创建表，仅开发环境使用）。

    生产环境应使用 Alembic 迁移。
    """
    from app.storage.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("数据库表已创建（开发模式）")


async def close_db() -> None:
    """关闭数据库连接池。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("数据库连接池已关闭")
