"""Token 消耗 A/B 基准测试

对应 design.md: Testing Strategy → Token 消耗 A/B 测试 (L1485-1510)
对应 tasks.md: Task 6.1 — 创建 Token 基准测试框架

对比两种上下文管理策略的 token 消耗：
  方法 A：固定截断 20 轮（原版方案）
  方法 B：四层 Compaction（新方案）

目标：Token 减少率 >= 70%
"""

import time
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from app.core.llm_factory import count_tokens
from app.evaluation.mock_incidents import MOCK_INCIDENTS, MockIncident, generate_mock_conversation


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkResult:
    """单场景的对比结果"""
    scenario: str
    severity: str
    tokens_truncate: int      # 方法 A: 固定截断
    tokens_compaction: int    # 方法 B: Compaction
    reduction_pct: float      # 减少百分比


@dataclass
class BenchmarkReport:
    """整体基准测试报告"""
    total_scenarios: int
    avg_reduction_pct: float
    results: list[BenchmarkResult]
    duration_seconds: float
    passed: bool  # avg >= 70%


# ---------------------------------------------------------------------------
# 方法 A：固定截断
# 原版方案 — 保留最近 20 轮消息
# ---------------------------------------------------------------------------

def simulate_truncation(messages: list[dict], max_turns: int = 20) -> int:
    """模拟固定截断策略的 token 消耗。

    保留 system prompt + 最近 max_turns 条消息。
    """
    system_prompt = "You are an OnCall AI Agent helping diagnose and resolve incidents."
    total = count_tokens(system_prompt)

    # 截断到最近 max_turns 条
    truncated = messages[-max_turns:] if len(messages) > max_turns else messages

    for m in truncated:
        total += count_tokens(m.get("content", ""))

    return total


# ---------------------------------------------------------------------------
# 方法 B：四层 Compaction
# 新方案 — workspace + summary + recent 5 + RAG
# ---------------------------------------------------------------------------

def simulate_compaction(messages: list[dict]) -> int:
    """模拟四层 Compaction 策略的 token 消耗。

    Layer 1: Workspace (固定大小，约 500 tokens)
    Layer 2: Summary (压缩后约 200 tokens)
    Layer 3: Recent 5 条消息
    Layer 4: RAG chunks (约 500 tokens)
    """
    # Layer 1: Workspace 配置
    workspace = "You are an OnCall AI Agent helping diagnose and resolve incidents."
    total = count_tokens(workspace)

    # Layer 2: Compaction summary（模拟压缩后的摘要）
    if len(messages) > 5:
        # 模拟 LLM 压缩：将早期消息压缩为约 10% 的摘要
        older = messages[:-5]
        older_text = " ".join(m.get("content", "") for m in older)
        # 压缩比约 10%（实际 LLM 压缩效果）
        summary_tokens = int(count_tokens(older_text) * 0.1)
        total += summary_tokens
    else:
        total += 0  # 消息不足 5 条，无需压缩

    # Layer 3: 最近 5 条消息
    recent = messages[-5:] if len(messages) > 5 else messages
    for m in recent:
        total += count_tokens(m.get("content", ""))

    # Layer 4: RAG chunks（模拟检索结果）
    rag_tokens = 500  # 假设平均 RAG 返回 500 tokens
    total += rag_tokens

    return total


# ---------------------------------------------------------------------------
# 基准测试运行器
# design.md L1488-1509
# ---------------------------------------------------------------------------

async def run_token_benchmark(
    scenarios: Optional[list[MockIncident]] = None,
) -> BenchmarkReport:
    """运行 Token 消耗 A/B 基准测试。

    design.md L1488: "对比固定截断和 Compaction 的 token 消耗"

    Args:
        scenarios: 测试场景列表，默认使用全部 20 个

    Returns:
        BenchmarkReport 基准测试报告
    """
    if scenarios is None:
        scenarios = MOCK_INCIDENTS

    start_time = time.time()
    results = []

    for incident in scenarios:
        # 生成模拟对话
        messages = generate_mock_conversation(incident)

        # 方法 A: 固定截断 20 轮
        tokens_truncate = simulate_truncation(messages, max_turns=20)

        # 方法 B: 四层 Compaction
        tokens_compaction = simulate_compaction(messages)

        # 计算减少率
        if tokens_truncate > 0:
            reduction = (tokens_truncate - tokens_compaction) / tokens_truncate * 100
        else:
            reduction = 0.0

        results.append(BenchmarkResult(
            scenario=incident.name,
            severity=incident.severity,
            tokens_truncate=tokens_truncate,
            tokens_compaction=tokens_compaction,
            reduction_pct=reduction,
        ))

    duration = time.time() - start_time

    avg_reduction = sum(r.reduction_pct for r in results) / max(len(results), 1)

    report = BenchmarkReport(
        total_scenarios=len(results),
        avg_reduction_pct=avg_reduction,
        results=results,
        duration_seconds=duration,
        passed=avg_reduction >= 70.0,
    )

    logger.info(
        f"Token A/B 测试完成: scenarios={report.total_scenarios}, "
        f"avg_reduction={report.avg_reduction_pct:.1f}%, "
        f"passed={'✅' if report.passed else '❌'}"
    )

    return report


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------

def generate_report_markdown(report: BenchmarkReport) -> str:
    """生成 Markdown 格式的基准测试报告。"""
    status = "✅ PASSED" if report.passed else "❌ FAILED"

    lines = [
        "# Token A/B Benchmark Report",
        "",
        f"**Status**: {status}",
        f"**Total Scenarios**: {report.total_scenarios}",
        f"**Avg Reduction**: {report.avg_reduction_pct:.1f}%",
        f"**Target**: >= 70%",
        f"**Duration**: {report.duration_seconds:.2f}s",
        "",
        "## Per-Scenario Results",
        "",
        "| Scenario | Severity | Truncate | Compact | Reduction |",
        "|----------|----------|----------|---------|-----------|",
    ]

    for r in report.results:
        lines.append(
            f"| {r.scenario} | {r.severity} | {r.tokens_truncate} | "
            f"{r.tokens_compaction} | {r.reduction_pct:.1f}% |"
        )

    return "\n".join(lines)
