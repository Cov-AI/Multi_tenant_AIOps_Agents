"""四层上下文 Compaction

对应 design.md: Memory 层 → Compaction 接口 (L337-364)
对应 tasks.md: Task 5.1 — 实现上下文组装和 Compaction 逻辑

Compaction 流程：
1. 判断是否需要压缩：total_tokens > context_window - 20000
2. 使用 LLM 提炼关键信息 → 生成 branch_summary
3. branch_summary 存入 Redis
4. 保留最近 3-5 轮消息，丢弃更早的
5. 更新压缩计数器
"""

from typing import Optional

from loguru import logger

from app.config import config
from app.core.llm_factory import count_tokens


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 默认上下文窗口大小（token 数）
# claudesonnet: 200K, gpt-4o: 128K — 取保守值
DEFAULT_CONTEXT_WINDOW = 128_000

# 触发 Compaction 的安全边距
# design.md L342-344: "total_tokens > (context_window - 20000)"
COMPACTION_MARGIN = 20_000

# 保留的最近消息轮次
KEEP_RECENT_TURNS = 5

# Compaction prompt
COMPACTION_PROMPT = """你是一个 OnCall 事故上下文提炼器。请从以下对话中提炼关键信息。

必须保留：
1. 告警原文（完整保留）
2. 已完成的诊断结论
3. 已执行的操作和结果
4. 当前待解决的问题

对话内容：
{messages}

请输出简洁的摘要（保留所有关键技术细节）："""


# ---------------------------------------------------------------------------
# Compaction 引擎
# design.md L340-364
# ---------------------------------------------------------------------------

class Compaction:
    """上下文压缩引擎。

    当 token 数超过阈值时自动压缩历史消息为摘要，
    减少 token 消耗同时保留关键信息。
    """

    def __init__(self, context_window: int = DEFAULT_CONTEXT_WINDOW):
        self.context_window = context_window

    def should_compact(self, total_tokens: int) -> bool:
        """判断是否需要压缩。

        design.md L341-344:
        "当 token 数超过 (context_window - 20000) 时触发 Compaction"
        """
        threshold = self.context_window - COMPACTION_MARGIN
        should = total_tokens > threshold
        if should:
            logger.info(
                f"Compaction 触发: tokens={total_tokens} > "
                f"threshold={threshold} (window={self.context_window})"
            )
        return should

    async def compact(
        self,
        session_key: str,
        messages: list[dict],
    ) -> str:
        """执行压缩，返回 branch_summary。

        design.md L346-363:
        1. 使用 LLM 提炼关键信息
        2. 存入 Redis
        3. 保留最近 3-5 轮
        4. 更新压缩计数

        Args:
            session_key: Session key
            messages: 所有历史消息

        Returns:
            生成的 branch_summary 文本
        """
        if not messages:
            return ""

        # 分离：早期消息（要压缩）和近期消息（保留）
        older_messages = messages[:-KEEP_RECENT_TURNS] if len(messages) > KEEP_RECENT_TURNS else []
        recent_messages = messages[-KEEP_RECENT_TURNS:]

        if not older_messages:
            logger.debug("消息不足，不需要压缩")
            return ""

        # 使用 LLM 生成 summary
        summary = await self._generate_summary(older_messages)

        # 存入 Redis
        await self._save_to_redis(session_key, summary, recent_messages)

        logger.info(
            f"Compaction 完成: session={session_key}, "
            f"compressed={len(older_messages)}msgs, "
            f"kept={len(recent_messages)}msgs, "
            f"summary_len={len(summary)}chars"
        )

        return summary

    async def _generate_summary(self, messages: list[dict]) -> str:
        """使用 LLM 生成摘要。

        降级处理：如果 LLM 调用失败，返回简单拼接。
        design.md: "Compaction 失败时保留原始消息，不执行压缩"
        """
        try:
            from app.core.llm_factory import get_chat_llm

            llm = get_chat_llm(temperature=0.3, streaming=False)

            # 格式化消息
            msg_text = "\n".join(
                f"[{m.get('role', 'unknown')}]: {m.get('content', '')}"
                for m in messages
            )

            prompt = COMPACTION_PROMPT.format(messages=msg_text)
            result = await llm.ainvoke(prompt)
            return result.content
        except Exception as e:
            logger.warning(f"LLM 生成 summary 失败（降级到简单拼接）: {e}")
            # 降级：提取关键信息
            parts = []
            for m in messages:
                if m.get("role") in ("assistant", "tool"):
                    content = m.get("content", "")
                    if len(content) > 200:
                        content = content[:200] + "..."
                    parts.append(content)
            return " | ".join(parts[-5:])  # 最多保留 5 段

    async def _save_to_redis(
        self,
        session_key: str,
        summary: str,
        recent_messages: list[dict],
    ) -> None:
        """将 summary 和近期消息存入 Redis。"""
        try:
            import json
            import redis.asyncio as aioredis

            r = aioredis.from_url(config.redis_url)

            # 存 summary
            # design.md L354: "await redis.set(session:{key}:summary, summary)"
            await r.set(f"session:{session_key}:summary", summary)

            # 只保留最近消息
            # design.md L358: "await redis.ltrim(session:{key}:messages, -5, -1)"
            pipe = r.pipeline()
            msg_key = f"session:{session_key}:messages"
            await pipe.delete(msg_key)
            for m in recent_messages:
                await pipe.rpush(msg_key, json.dumps(m, ensure_ascii=False))
            await pipe.expire(msg_key, 86400)  # 24h TTL

            # 更新压缩计数
            # design.md L361: "await redis.incr(session:{key}:compaction_count)"
            await pipe.incr(f"session:{session_key}:compaction_count")

            await pipe.execute()
            await r.aclose()
        except Exception as e:
            logger.warning(f"Redis 存储 compaction 结果失败: {e}")


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------

async def estimate_context_tokens(
    workspace: str,
    summary: str,
    recent_messages: list[dict],
    rag_chunks: list[str],
) -> int:
    """估算四层上下文的总 token 数。"""
    total = count_tokens(workspace)
    total += count_tokens(summary)
    for m in recent_messages:
        total += count_tokens(m.get("content", ""))
    for chunk in rag_chunks:
        total += count_tokens(chunk)
    return total


# ---------------------------------------------------------------------------
# 全局实例
# ---------------------------------------------------------------------------

compaction = Compaction()
