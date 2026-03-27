"""事故响应时间评估

对应 tasks.md: Task 6.5 — 实现事故响应时间评估
对应 ONCALL_FINAL.md: "80%+ incident response time reduction"

评估流程：
1. 使用 20 个模拟事故场景
2. 模拟 AI Agent 处理时间（基于对话轮次和 LLM 延迟）
3. 对比人工处理基线时间
4. 计算减少百分比

目标：AI 处理时间相比人工基线减少 >= 80%
"""

import time
from dataclasses import dataclass
from typing import Optional

from loguru import logger

from app.evaluation.mock_incidents import MOCK_INCIDENTS, MockIncident


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class ResponseTimeResult:
    """单场景的响应时间对比"""
    scenario: str
    severity: str
    human_minutes: float          # 人工处理基线时间（分钟）
    ai_minutes: float             # AI 处理时间（分钟）
    reduction_pct: float          # 减少百分比
    conversation_turns: int       # 对话轮次


@dataclass
class ResponseTimeReport:
    """整体响应时间评估报告"""
    total_scenarios: int
    avg_human_minutes: float
    avg_ai_minutes: float
    avg_reduction_pct: float
    results: list[ResponseTimeResult]
    duration_seconds: float
    passed: bool  # avg >= 80%


# ---------------------------------------------------------------------------
# AI 处理时间估算
# ---------------------------------------------------------------------------

# 每轮对话的平均时间（秒）— LLM 推理 + 工具调用
AVG_TURN_SECONDS = 15.0  # LLM 约 5s + MCP 工具调用约 10s

# 审批等待时间（分钟）— 人工审批通常需要几分钟
AVG_APPROVAL_MINUTES = 2.0


def estimate_ai_processing_time(incident: MockIncident) -> float:
    """估算 AI Agent 处理事故的时间（分钟）。

    基于：
    - 每轮对话约 15 秒（LLM 推理 + 工具调用）
    - 高危操作需要人工审批（约 2 分钟等待）
    - P0/P1 通常需要审批
    """
    # 基础处理时间
    base_minutes = (incident.conversation_turns * AVG_TURN_SECONDS) / 60.0

    # 高危操作需要审批
    if incident.severity in ("P0", "P1"):
        base_minutes += AVG_APPROVAL_MINUTES

    return round(base_minutes, 1)


# ---------------------------------------------------------------------------
# 评估运行器
# ---------------------------------------------------------------------------

async def run_response_time_evaluation(
    scenarios: Optional[list[MockIncident]] = None,
) -> ResponseTimeReport:
    """运行事故响应时间评估。

    Args:
        scenarios: 测试场景列表，默认使用全部 20 个

    Returns:
        ResponseTimeReport 评估报告
    """
    if scenarios is None:
        scenarios = MOCK_INCIDENTS

    start_time = time.time()
    results = []

    for incident in scenarios:
        ai_minutes = estimate_ai_processing_time(incident)
        human_minutes = incident.human_baseline_minutes

        # 计算减少率
        if human_minutes > 0:
            reduction = (human_minutes - ai_minutes) / human_minutes * 100
        else:
            reduction = 0.0

        results.append(ResponseTimeResult(
            scenario=incident.name,
            severity=incident.severity,
            human_minutes=human_minutes,
            ai_minutes=ai_minutes,
            reduction_pct=reduction,
            conversation_turns=incident.conversation_turns,
        ))

    duration = time.time() - start_time

    avg_human = sum(r.human_minutes for r in results) / max(len(results), 1)
    avg_ai = sum(r.ai_minutes for r in results) / max(len(results), 1)
    avg_reduction = sum(r.reduction_pct for r in results) / max(len(results), 1)

    report = ResponseTimeReport(
        total_scenarios=len(results),
        avg_human_minutes=avg_human,
        avg_ai_minutes=avg_ai,
        avg_reduction_pct=avg_reduction,
        results=results,
        duration_seconds=duration,
        passed=avg_reduction >= 80.0,
    )

    logger.info(
        f"响应时间评估完成: scenarios={report.total_scenarios}, "
        f"human_avg={report.avg_human_minutes:.1f}min, "
        f"ai_avg={report.avg_ai_minutes:.1f}min, "
        f"reduction={report.avg_reduction_pct:.1f}%, "
        f"passed={'✅' if report.passed else '❌'}"
    )

    return report


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------

def generate_report_markdown(report: ResponseTimeReport) -> str:
    """生成 Markdown 格式的响应时间评估报告。"""
    status = "✅ PASSED" if report.passed else "❌ FAILED"

    lines = [
        "# Incident Response Time Evaluation Report",
        "",
        f"**Status**: {status}",
        f"**Total Scenarios**: {report.total_scenarios}",
        f"**Avg Human Time**: {report.avg_human_minutes:.1f} min",
        f"**Avg AI Time**: {report.avg_ai_minutes:.1f} min",
        f"**Avg Reduction**: {report.avg_reduction_pct:.1f}%",
        f"**Target**: >= 80%",
        f"**Duration**: {report.duration_seconds:.3f}s",
        "",
        "## Per-Scenario Results",
        "",
        "| Scenario | Severity | Human (min) | AI (min) | Reduction | Turns |",
        "|----------|----------|-------------|----------|-----------|-------|",
    ]

    for r in report.results:
        lines.append(
            f"| {r.scenario} | {r.severity} | {r.human_minutes:.1f} | "
            f"{r.ai_minutes:.1f} | {r.reduction_pct:.1f}% | {r.conversation_turns} |"
        )

    return "\n".join(lines)
