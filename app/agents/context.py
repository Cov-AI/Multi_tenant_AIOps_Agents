"""四层上下文组装器

对应 design.md: Agent Worker 层 → 上下文组装接口 (L298-334)
对应 tasks.md: Task 5.1 — 实现 agents/context.py 中的 ContextAssembler 类

四层上下文结构（design.md: ContextLayers）：
  Layer 1 — 永久层（Workspace 配置：soul/agents_md/user_md）
  Layer 2 — 摘要层（branch_summary，由 Compaction 生成）
  Layer 3 — 近期层（最近 3-5 轮完整消息）
  Layer 4 — RAG 层（实时检索的 runbook chunks）

每次 Agent 调用都完整组装四层，RAG 层不缓存（design.md Property 9）。
"""

from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from app.config import config


# ---------------------------------------------------------------------------
# 上下文数据模型
# design.md L301-306: ContextLayers
# ---------------------------------------------------------------------------

@dataclass
class ContextLayers:
    """四层上下文结构"""
    layer1_permanent: str = ""          # Workspace 配置（soul/agents_md/user_md）
    layer2_summary: str = ""            # branch_summary（历史摘要）
    layer3_recent: list[dict] = field(default_factory=list)   # 最近 3-5 轮完整消息
    layer4_rag: list[str] = field(default_factory=list)       # RAG 检索的 runbook chunks


# ---------------------------------------------------------------------------
# ContextAssembler
# design.md L308-334
# ---------------------------------------------------------------------------

class ContextAssembler:
    """四层上下文组装器。

    design.md::

        async def assemble(tenant_id, agent_id, session_key, query) -> ContextLayers:
            # Layer 1: Workspace
            # Layer 2: branch_summary from Redis
            # Layer 3: recent messages from Redis
            # Layer 4: RAG from Milvus
    """

    async def assemble(
        self,
        tenant_id: str,
        agent_id: str,
        session_key: str,
        query: str,
        workspace_config: Optional[dict] = None,
        recent_messages: Optional[list[dict]] = None,
        summary: Optional[str] = None,
    ) -> ContextLayers:
        """组装四层上下文。

        design.md L309-334: 完整的上下文组装流程

        Args:
            tenant_id: 租户 ID
            agent_id: Agent ID
            session_key: Session key
            query: 当前用户查询
            workspace_config: Workspace 配置（Layer 1），None 则尝试从 Redis/DB 读取
            recent_messages: 最近消息（Layer 3），None 则尝试从 Redis 读取
            summary: 历史摘要（Layer 2），None 则尝试从 Redis 读取

        Returns:
            ContextLayers 四层上下文
        """
        layers = ContextLayers()

        # Layer 1: 永久层 — Workspace 配置
        # design.md: "从 Redis 缓存或 PostgreSQL 读取 Workspace"
        layers.layer1_permanent = await self._get_workspace(
            tenant_id, agent_id, workspace_config
        )

        # Layer 2: 摘要层 — branch_summary
        # design.md: "从 Redis 读取 branch_summary"
        layers.layer2_summary = await self._get_summary(session_key, summary)

        # Layer 3: 近期层 — 最近 3-5 轮消息
        # design.md: "从 Redis 读取最近消息"
        layers.layer3_recent = await self._get_recent_messages(
            session_key, recent_messages
        )

        # Layer 4: RAG 层 — 实时检索（不缓存！）
        # design.md Property 9: "RAG 检索应重新执行，不使用缓存"
        layers.layer4_rag = await self._search_rag(tenant_id, query)

        logger.debug(
            f"上下文组装完成: tenant={tenant_id}, "
            f"workspace={len(layers.layer1_permanent)}chars, "
            f"summary={len(layers.layer2_summary)}chars, "
            f"recent={len(layers.layer3_recent)}msgs, "
            f"rag={len(layers.layer4_rag)}chunks"
        )

        return layers

    async def _get_workspace(
        self,
        tenant_id: str,
        agent_id: str,
        provided: Optional[dict] = None,
    ) -> str:
        """获取 Workspace 配置。"""
        if provided:
            return self._format_workspace(provided)

        # 尝试从 Redis 缓存读取
        # design.md: "优先从 Redis 读取 Workspace 配置"
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(config.redis_url)
            cached = await r.get(f"workspace:{tenant_id}:{agent_id}")
            await r.aclose()
            if cached:
                import json
                return self._format_workspace(json.loads(cached))
        except Exception as e:
            logger.debug(f"Redis 读取 workspace 失败（降级到默认）: {e}")

        # 返回默认 workspace
        return "You are an OnCall AI Agent. You help SREs diagnose and resolve incidents."

    def _format_workspace(self, ws: dict) -> str:
        """将 workspace 配置格式化为 system prompt。"""
        parts = []
        if ws.get("soul"):
            parts.append(ws["soul"])
        if ws.get("agents_md"):
            parts.append(ws["agents_md"])
        if ws.get("user_md"):
            parts.append(ws["user_md"])
        return "\n\n".join(parts) if parts else str(ws)

    async def _get_summary(
        self,
        session_key: str,
        provided: Optional[str] = None,
    ) -> str:
        """获取历史摘要（branch_summary）。"""
        if provided is not None:
            return provided

        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(config.redis_url)
            summary = await r.get(f"session:{session_key}:summary")
            await r.aclose()
            return summary.decode("utf-8") if summary else ""
        except Exception as e:
            logger.debug(f"Redis 读取 summary 失败: {e}")
            return ""

    async def _get_recent_messages(
        self,
        session_key: str,
        provided: Optional[list[dict]] = None,
    ) -> list[dict]:
        """获取最近 3-5 轮消息。"""
        if provided is not None:
            return provided[-5:]  # 保留最近 5 条

        try:
            import json
            import redis.asyncio as aioredis
            r = aioredis.from_url(config.redis_url)
            messages = await r.lrange(f"session:{session_key}:messages", -5, -1)
            await r.aclose()
            return [json.loads(m) for m in messages] if messages else []
        except Exception as e:
            logger.debug(f"Redis 读取 recent messages 失败: {e}")
            return []

    async def _search_rag(self, tenant_id: str, query: str) -> list[str]:
        """RAG 检索 — 每次重新执行，不缓存。"""
        try:
            from app.memory.vector_store import vector_store
            results = await vector_store.search(tenant_id, query, top_k=config.rag_top_k)
            return [r["text"] for r in results]
        except Exception as e:
            logger.warning(f"RAG 检索失败（跳过 Layer 4）: {e}")
            return []


# ---------------------------------------------------------------------------
# 全局实例
# ---------------------------------------------------------------------------

context_assembler = ContextAssembler()
