"""Task 6.2/6.3 — Token 基准测试验证 + 响应时间测试

对应 tasks.md: Task 6.2 (Property: Token记录完整性), 6.3 (Unit: 基准测试验证)
"""

import pytest

from app.evaluation.mock_incidents import (
    MOCK_INCIDENTS, MockIncident, generate_mock_conversation,
)
from app.evaluation.token_benchmark import (
    simulate_truncation, simulate_compaction,
    BenchmarkResult, BenchmarkReport, generate_report_markdown,
)
from app.evaluation.response_time import (
    estimate_ai_processing_time, ResponseTimeResult,
    generate_report_markdown as rt_report_markdown,
)


# ---------------------------------------------------------------------------
# Task 6.2 — Property Test: Token 消耗记录完整性
# Feature: multi-tenant-oncall-platform, Property 18: Token 消耗记录完整性
# ---------------------------------------------------------------------------

class TestTokenRecordingProperty:
    """Property 18: Token 消耗记录完整性。"""

    def test_token_usage_table_exists(self):
        """验证 token_usage 表定义了所有必要字段。"""
        from app.storage.models import Base
        table = Base.metadata.tables["token_usage"]
        columns = {col.name for col in table.columns}
        assert "tenant_id" in columns
        assert "model" in columns
        assert "input_tokens" in columns
        assert "output_tokens" in columns
        assert "created_at" in columns


# ---------------------------------------------------------------------------
# Task 6.3 — Unit Tests: 基准测试验证
# ---------------------------------------------------------------------------

class TestMockIncidents:
    """测试模拟场景加载。"""

    def test_has_20_scenarios(self):
        """验证有 20 个模拟事故场景。"""
        assert len(MOCK_INCIDENTS) == 20

    def test_scenarios_have_required_fields(self):
        """验证每个场景有必要字段。"""
        for inc in MOCK_INCIDENTS:
            assert isinstance(inc, MockIncident)
            assert len(inc.name) > 0
            assert inc.severity in ("P0", "P1", "P2", "P3")
            assert len(inc.alert_content) > 0
            assert inc.human_baseline_minutes > 0

    def test_severity_distribution(self):
        """验证严重级别分布合理。"""
        severities = [inc.severity for inc in MOCK_INCIDENTS]
        assert "P0" in severities
        assert "P1" in severities
        assert "P2" in severities

    def test_generate_conversation_non_empty(self):
        """验证生成的对话非空。"""
        for inc in MOCK_INCIDENTS[:3]:
            msgs = generate_mock_conversation(inc)
            assert len(msgs) >= 4  # 至少有 4 条初始消息


class TestTokenBenchmark:
    """测试 token 基准测试逻辑。"""

    def test_truncation_returns_positive(self):
        """验证截断策略返回正数 token 数。"""
        msgs = generate_mock_conversation(MOCK_INCIDENTS[0])
        tokens = simulate_truncation(msgs)
        assert tokens > 0

    def test_compaction_returns_positive(self):
        """验证 Compaction 策略返回正数 token 数。"""
        msgs = generate_mock_conversation(MOCK_INCIDENTS[0])
        tokens = simulate_compaction(msgs)
        assert tokens > 0

    def test_compaction_less_than_truncation(self):
        """验证 Compaction 比截断消耗更少 token。"""
        for inc in MOCK_INCIDENTS:
            msgs = generate_mock_conversation(inc)
            t_trunc = simulate_truncation(msgs)
            t_compact = simulate_compaction(msgs)
            assert t_compact <= t_trunc, (
                f"场景 {inc.name}: compact={t_compact} > truncate={t_trunc}"
            )

    def test_all_scenarios_reduction_positive(self):
        """验证所有场景的 token 减少率为正。"""
        for inc in MOCK_INCIDENTS:
            msgs = generate_mock_conversation(inc)
            t_trunc = simulate_truncation(msgs)
            t_compact = simulate_compaction(msgs)
            reduction = (t_trunc - t_compact) / t_trunc * 100
            assert reduction > 0, f"场景 {inc.name} 减少率为负"

    def test_report_markdown(self):
        """测试报告生成。"""
        report = BenchmarkReport(
            total_scenarios=1,
            avg_reduction_pct=75.0,
            results=[BenchmarkResult(
                scenario="test", severity="P0",
                tokens_truncate=1000, tokens_compaction=250,
                reduction_pct=75.0,
            )],
            duration_seconds=0.1,
            passed=True,
        )
        md = generate_report_markdown(report)
        assert "PASSED" in md
        assert "75.0%" in md


class TestResponseTime:
    """测试响应时间评估。"""

    def test_ai_time_less_than_human(self):
        """验证 AI 处理时间 < 人工基线时间。"""
        for inc in MOCK_INCIDENTS:
            ai_time = estimate_ai_processing_time(inc)
            assert ai_time < inc.human_baseline_minutes, (
                f"场景 {inc.name}: AI={ai_time} >= human={inc.human_baseline_minutes}"
            )

    def test_reduction_above_target(self):
        """验证所有场景的响应时间减少率 > 50%。"""
        for inc in MOCK_INCIDENTS:
            ai = estimate_ai_processing_time(inc)
            h = inc.human_baseline_minutes
            reduction = (h - ai) / h * 100
            assert reduction > 50, (
                f"场景 {inc.name}: reduction={reduction:.1f}% < 50%"
            )

    def test_response_time_report(self):
        """测试报告 Markdown 生成。"""
        from app.evaluation.response_time import ResponseTimeReport
        report = ResponseTimeReport(
            total_scenarios=1,
            avg_human_minutes=30.0,
            avg_ai_minutes=4.0,
            avg_reduction_pct=86.7,
            results=[],
            duration_seconds=0.01,
            passed=True,
        )
        md = rt_report_markdown(report)
        assert "PASSED" in md
        assert "86.7%" in md
