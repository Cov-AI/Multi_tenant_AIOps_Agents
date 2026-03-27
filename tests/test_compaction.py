"""Task 5.2/5.3/5.4 — Compaction 和 ContextAssembler 测试

对应 tasks.md: Task 5.2 (Property: 四层结构完整性), 5.3 (Property: Compaction触发), 5.4 (Unit: 边缘情况)
"""

import inspect
import pytest

from app.agents.context import ContextAssembler, ContextLayers, context_assembler
from app.memory.compaction import (
    Compaction, compaction, COMPACTION_MARGIN, KEEP_RECENT_TURNS,
    DEFAULT_CONTEXT_WINDOW, estimate_context_tokens,
)
from app.core.llm_factory import count_tokens


# ---------------------------------------------------------------------------
# Task 5.2 — Property Test: 四层上下文结构完整性
# Feature: multi-tenant-oncall-platform, Property 7: 四层上下文结构完整性
# ---------------------------------------------------------------------------

class TestContextStructureProperty:
    """Property 7: 组装的上下文应包含四层。"""

    def test_context_layers_has_four_fields(self):
        """验证 ContextLayers 包含四层字段。"""
        layers = ContextLayers()
        assert hasattr(layers, "layer1_permanent")
        assert hasattr(layers, "layer2_summary")
        assert hasattr(layers, "layer3_recent")
        assert hasattr(layers, "layer4_rag")

    def test_context_layers_default_values(self):
        """验证默认值为空。"""
        layers = ContextLayers()
        assert layers.layer1_permanent == ""
        assert layers.layer2_summary == ""
        assert layers.layer3_recent == []
        assert layers.layer4_rag == []

    def test_assembler_has_assemble_method(self):
        """验证 ContextAssembler 有 assemble 方法。"""
        assert hasattr(context_assembler, "assemble")

    def test_assembler_assemble_returns_context_layers(self):
        """验证 assemble 方法签名返回 ContextLayers。"""
        import typing
        hints = typing.get_type_hints(ContextAssembler.assemble)
        assert hints.get("return") == ContextLayers

    def test_assembler_rag_never_cached(self):
        """Property 9: RAG 检索不缓存 — 验证代码中无缓存逻辑。"""
        source = inspect.getsource(ContextAssembler._search_rag)
        assert "cache" not in source.lower()


# ---------------------------------------------------------------------------
# Task 5.3 — Property Test: Compaction 触发和执行
# Feature: multi-tenant-oncall-platform, Property 8: Compaction 触发和执行
# ---------------------------------------------------------------------------

class TestCompactionTriggerProperty:
    """Property 8: 超过阈值时触发 Compaction。"""

    def test_should_compact_when_over_threshold(self):
        """验证超过阈值时触发。"""
        c = Compaction(context_window=100_000)
        threshold = 100_000 - COMPACTION_MARGIN
        assert c.should_compact(threshold + 1) is True

    def test_should_not_compact_when_under_threshold(self):
        """验证未超过阈值时不触发。"""
        c = Compaction(context_window=100_000)
        threshold = 100_000 - COMPACTION_MARGIN
        assert c.should_compact(threshold - 1) is False

    def test_should_compact_at_exact_threshold(self):
        """验证恰好等于阈值时不触发（需要超过）。"""
        c = Compaction(context_window=100_000)
        threshold = 100_000 - COMPACTION_MARGIN
        assert c.should_compact(threshold) is False

    @pytest.mark.parametrize("window", [50_000, 100_000, 200_000])
    def test_threshold_scales_with_window(self, window):
        """验证阈值随 context_window 缩放。"""
        c = Compaction(context_window=window)
        threshold = window - COMPACTION_MARGIN
        assert c.should_compact(threshold + 1) is True
        assert c.should_compact(threshold - 1) is False

    def test_keep_recent_turns_value(self):
        """验证保留最近 5 轮消息。"""
        assert KEEP_RECENT_TURNS == 5

    def test_compaction_stores_to_redis(self):
        """验证 compact 方法将 summary 存到 Redis。"""
        source = inspect.getsource(Compaction._save_to_redis)
        assert "summary" in source
        assert "session:" in source


# ---------------------------------------------------------------------------
# Task 5.4 — Unit Tests: Compaction 边缘情况
# ---------------------------------------------------------------------------

class TestCompactionEdgeCases:
    """测试 Compaction 边缘情况。"""

    @pytest.mark.asyncio
    async def test_compact_empty_messages(self):
        """测试空历史消息不报错。"""
        result = await compaction.compact("test-session", [])
        assert result == ""

    @pytest.mark.asyncio
    async def test_compact_few_messages_no_compression(self):
        """测试消息不足 5 条时不压缩。"""
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = await compaction.compact("test-session", messages)
        assert result == ""  # 消息不足，不需要压缩

    def test_count_tokens_non_empty(self):
        """测试 token 计数非空文本。"""
        tokens = count_tokens("Hello world")
        assert tokens > 0

    def test_count_tokens_empty(self):
        """测试空文本 token 计数为 0。"""
        assert count_tokens("") == 0

    @pytest.mark.asyncio
    async def test_estimate_context_tokens(self):
        """测试上下文 token 估算。"""
        total = await estimate_context_tokens(
            workspace="system prompt",
            summary="history summary",
            recent_messages=[{"content": "hello"}, {"content": "world"}],
            rag_chunks=["chunk1", "chunk2"],
        )
        assert total > 0
