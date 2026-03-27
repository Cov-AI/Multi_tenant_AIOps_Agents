"""Task 4.2 — Unit Tests: 评估框架测试

对应 tasks.md: Task 4.2 — 编写 Unit Tests：评估框架测试
"""

import pytest

from app.evaluation.ragas_eval import (
    load_testset, _get_sample_testset, RAGASTestItem,
    _compute_faithfulness, _compute_context_recall, generate_report_markdown,
    RAGASReport, RAGASResult,
)


class TestRAGASTestset:
    """测试测试集加载和验证。"""

    def test_sample_testset_has_items(self):
        """验证内置示例测试集非空。"""
        items = _get_sample_testset()
        assert len(items) >= 10

    def test_testset_items_have_required_fields(self):
        """验证每条测试数据有必要字段。"""
        for item in _get_sample_testset():
            assert isinstance(item, RAGASTestItem)
            assert len(item.question) > 0
            assert len(item.ground_truth) > 0

    def test_load_testset_fallback(self):
        """验证文件不存在时使用内置数据。"""
        items = load_testset("/nonexistent/path.json")
        assert len(items) >= 10


class TestRAGASMetrics:
    """测试评估指标计算。"""

    def test_faithfulness_perfect_match(self):
        """验证完全匹配时 faithfulness 为 1.0。"""
        score = _compute_faithfulness("hello world", ["context"], "hello world")
        assert score == 1.0

    def test_faithfulness_no_overlap(self):
        """验证无重叠时 faithfulness 为 0.0。"""
        score = _compute_faithfulness("alpha beta", ["ctx"], "gamma delta")
        assert score == 0.0

    def test_faithfulness_empty_answer(self):
        """验证空答案时返回 0.0。"""
        assert _compute_faithfulness("", ["ctx"], "truth") == 0.0

    def test_context_recall_perfect(self):
        """验证上下文完全覆盖 ground_truth。"""
        score = _compute_context_recall(
            ["hello world is great"], "hello world"
        )
        assert score == 1.0

    def test_context_recall_empty(self):
        """验证空上下文返回 0.0。"""
        assert _compute_context_recall([], "truth") == 0.0


class TestRAGASReport:
    """测试报告生成。"""

    def test_report_markdown_format(self):
        """验证报告 Markdown 格式正确。"""
        report = RAGASReport(
            total_questions=2,
            avg_faithfulness=0.90,
            avg_context_recall=0.85,
            results=[
                RAGASResult(question="Q1", answer="A1", contexts=["C1"],
                           ground_truth="G1", faithfulness=0.9, context_recall=0.8),
                RAGASResult(question="Q2", answer="A2", contexts=["C2"],
                           ground_truth="G2", faithfulness=0.9, context_recall=0.9),
            ],
            duration_seconds=1.5,
            passed=True,
        )
        md = generate_report_markdown(report)
        assert "RAGAS" in md
        assert "PASSED" in md
        assert "90.00%" in md
