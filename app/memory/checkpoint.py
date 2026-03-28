"""
LangGraph 持久化 Checkpoint 配置
对应 tasks.md: Task 9.1 - 实现 PostgreSQL Checkpoint Saver
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from loguru import logger
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
# 注意：官方推荐在生产中使用带有 connection pooling 的 AsyncPostgresSaver
# 为防止互相依赖影响，此处根据配置的 database URL 单独创建 PostgresSaver 连接池

from app.config import config


def _get_postgres_dsn() -> str:
    """提取纯 psycopg 兼容的 PostgreSQL DSN (去除去除 asyncpg schema 等)"""
    url = getattr(config, "database_url", "")
    if not url:
        return ""
    
    # 将可能存在的 postgresql+asyncpg:// 替换为正常的 postgres(ql)://
    if "postgresql+asyncpg://" in url:
        url = url.replace("postgresql+asyncpg://", "postgresql://")
        
    return url


@asynccontextmanager
async def get_checkpointer() -> AsyncGenerator[AsyncPostgresSaver, None]:
    """
    获取全局 LangGraph Checkpointer 的 AsyncContextManager。
    由于 AsyncPostgresSaver 自己管理 db connections，我们在应用生命周期内保留。
    如果是非 PostgreSQL 环境 (比如没有配置或使用 sqlite)，返回 None 或 MemorySaver。
    """
    dsn = _get_postgres_dsn()
    
    # P0/P1 阶段过渡：如果用户还在用 SQLite mock DB，返回假的空指针让上层 fallback 到 MemorySaver
    if not dsn or "sqlite" in dsn:
        logger.warning("当前环境未使用 PostgreSQL，LangGraph Checkpointer 将降级为 MemorySaver")
        yield None
        return

    # 创建 AsyncPostgresSaver 连接池 
    # 此处自动管理表结构创建 (`checkpoints`, `checkpoint_blobs` 等)
    try:
        async with AsyncPostgresSaver.from_conn_string(dsn) as checkpointer:
            # 初始化表结构（如果表不存在）
            await checkpointer.setup()
            logger.info("LangGraph AsyncPostgresSaver (PostgreSQL Checkpointer) 初始化完成, 已成功连接")
            yield checkpointer
    except Exception as e:
        logger.error(f"初始化 AsyncPostgresSaver 失败: {e}", exc_info=True)
        # 降级
        yield None
