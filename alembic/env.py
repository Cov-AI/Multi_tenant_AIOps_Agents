"""Alembic env.py — 配置迁移引擎

对应 tasks.md: Task 1.1 — 使用 Alembic 创建数据库迁移脚本
"""

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# 导入所有模型以便 autogenerate 检测
from app.storage.models import Base  # noqa: E402
from app.config import config as app_config  # noqa: E402

# Alembic Config 对象
config = context.config

# 设置数据库 URL（优先使用环境变量，降级为 config.py，最终降级 SQLite）
database_url = os.getenv("DATABASE_URL", app_config.database_url)
if not database_url:
    database_url = "sqlite:///./oncall_dev.db"

# Alembic 需要同步 URL，将 async 驱动替换为同步驱动
sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
sync_url = sync_url.replace("sqlite+aiosqlite://", "sqlite://")
config.set_main_option("sqlalchemy.url", sync_url)

# 配置 Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 设置 target_metadata 供 autogenerate 使用
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — 生成 SQL 脚本。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — 直接执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
