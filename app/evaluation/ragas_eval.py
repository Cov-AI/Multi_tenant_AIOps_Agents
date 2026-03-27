"""RAGAS 评估框架

对应 design.md: Testing Strategy → RAGAS 评估 (L1512-1543)
对应 tasks.md: Task 4.1 — 创建 RAG 评估测试集和评估脚本

目标：Faithfulness >= 85%, Context Recall >= 85%

评估流程：
1. 加载 Q&A 测试集（evaluation/ragas_testset.json）
2. 对每个问题执行 RAG Pipeline（检索 + 生成）
3. 使用 RAGAS 计算 Faithfulness 和 Context Recall
4. 生成评估报告
"""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class RAGASTestItem:
    """测试集中的单条 Q&A"""
    question: str
    ground_truth: str
    context: list[str] = field(default_factory=list)  # 预期上下文来源


@dataclass
class RAGASResult:
    """单条测试的评估结果"""
    question: str
    answer: str
    contexts: list[str]
    ground_truth: str
    faithfulness: float = 0.0
    context_recall: float = 0.0


@dataclass
class RAGASReport:
    """整体评估报告"""
    total_questions: int
    avg_faithfulness: float
    avg_context_recall: float
    results: list[RAGASResult]
    duration_seconds: float
    passed: bool  # Faithfulness >= 85%


# ---------------------------------------------------------------------------
# 测试集管理
# ---------------------------------------------------------------------------

# 测试集文件路径（相对于项目根目录）
TESTSET_PATH = Path(__file__).parent / "ragas_testset.json"


def load_testset(path: Optional[str] = None) -> list[RAGASTestItem]:
    """加载 RAGAS 测试集。

    测试集格式::

        [
            {
                "question": "如何处理 payment-service OOM 错误？",
                "ground_truth": "检查内存使用趋势...",
                "context": ["runbook: payment-service-troubleshooting.md"]
            },
            ...
        ]
    """
    testset_path = Path(path) if path else TESTSET_PATH

    if not testset_path.exists():
        logger.warning(f"测试集文件不存在: {testset_path}，使用内置示例数据")
        return _get_sample_testset()

    with open(testset_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = [RAGASTestItem(**item) for item in data]
    logger.info(f"测试集加载完成: {len(items)} 条 Q&A")
    return items


def _get_sample_testset() -> list[RAGASTestItem]:
    """内置的示例测试集（10 条，开发阶段使用）。

    完整的 100 条测试集应存储在 evaluation/ragas_testset.json。
    """
    return [
        RAGASTestItem(
            question="如何处理 payment-service OOM 错误？",
            ground_truth="检查内存使用趋势，如果持续增长则增加内存限制到 2Gi 或修复内存泄漏",
            context=["payment-service-troubleshooting.md"],
        ),
        RAGASTestItem(
            question="API Gateway 出现 CrashLoopBackOff 怎么办？",
            ground_truth="检查最近的配置变更和环境变量，回滚到上一个稳定版本",
            context=["api-gateway-runbook.md"],
        ),
        RAGASTestItem(
            question="数据库连接池耗尽如何处理？",
            ground_truth="检查连接泄漏，增加 max_connections，重启慢查询的服务",
            context=["database-troubleshooting.md"],
        ),
        RAGASTestItem(
            question="Kafka consumer lag 持续增长怎么办？",
            ground_truth="增加 consumer 实例数，检查是否有慢处理逻辑，考虑分区重平衡",
            context=["kafka-operations.md"],
        ),
        RAGASTestItem(
            question="如何调查 5xx 错误率突增？",
            ground_truth="检查上游依赖健康状态，查看最近部署记录，分析错误日志中的堆栈信息",
            context=["incident-response-general.md"],
        ),
        RAGASTestItem(
            question="Redis 内存使用率超过 90% 如何处理？",
            ground_truth="分析 key 分布，清理过期数据，评估是否需要扩容或启用 eviction 策略",
            context=["redis-operations.md"],
        ),
        RAGASTestItem(
            question="Pod 启动时间过长怎么排查？",
            ground_truth="检查 image pull 时间、init container、readiness probe 配置和依赖服务连通性",
            context=["kubernetes-troubleshooting.md"],
        ),
        RAGASTestItem(
            question="SSL 证书即将过期如何处理？",
            ground_truth="使用 cert-manager 自动续期，或手动更新证书并重启相关服务",
            context=["ssl-certificate-management.md"],
        ),
        RAGASTestItem(
            question="如何处理磁盘空间不足告警？",
            ground_truth="清理日志文件和临时文件，扩容磁盘，配置日志轮转策略",
            context=["disk-space-management.md"],
        ),
        RAGASTestItem(
            question="服务间调用超时如何诊断？",
            ground_truth="检查网络延迟、目标服务负载、超时配置，使用分布式追踪定位瓶颈",
            context=["service-mesh-troubleshooting.md"],
        ),
    ]


# ---------------------------------------------------------------------------
# 评估引擎
# ---------------------------------------------------------------------------

async def run_evaluation(
    rag_search_fn=None,
    llm_generate_fn=None,
    testset: Optional[list[RAGASTestItem]] = None,
) -> RAGASReport:
    """执行 RAGAS 评估。

    design.md L1518-1543: "评估 RAG 系统质量"

    Args:
        rag_search_fn: RAG 检索函数 async (question) -> list[str]
        llm_generate_fn: LLM 生成函数 async (question, contexts) -> str
        testset: 测试集，默认从文件加载

    Returns:
        RAGASReport 评估报告

    当 rag_search_fn 或 llm_generate_fn 未提供时，使用 mock 实现（开发阶段）。
    """
    if testset is None:
        testset = load_testset()

    start_time = time.time()
    results = []

    for item in testset:
        try:
            # 执行 RAG 检索
            if rag_search_fn:
                contexts = await rag_search_fn(item.question)
            else:
                contexts = [f"Mock context for: {item.question}"]

            # 执行 LLM 生成
            if llm_generate_fn:
                answer = await llm_generate_fn(item.question, contexts)
            else:
                answer = f"Mock answer based on context about {item.question}"

            # 计算指标（简化版 RAGAS 计算）
            # 完整版需要 pip install ragas，这里先用近似实现确保可运行
            faithfulness = _compute_faithfulness(answer, contexts, item.ground_truth)
            context_recall = _compute_context_recall(contexts, item.ground_truth)

            results.append(RAGASResult(
                question=item.question,
                answer=answer,
                contexts=contexts,
                ground_truth=item.ground_truth,
                faithfulness=faithfulness,
                context_recall=context_recall,
            ))
        except Exception as e:
            logger.error(f"评估失败 [{item.question[:30]}...]: {e}")
            results.append(RAGASResult(
                question=item.question,
                answer=f"ERROR: {e}",
                contexts=[],
                ground_truth=item.ground_truth,
                faithfulness=0.0,
                context_recall=0.0,
            ))

    duration = time.time() - start_time

    # 汇总
    avg_faith = sum(r.faithfulness for r in results) / max(len(results), 1)
    avg_recall = sum(r.context_recall for r in results) / max(len(results), 1)

    report = RAGASReport(
        total_questions=len(results),
        avg_faithfulness=avg_faith,
        avg_context_recall=avg_recall,
        results=results,
        duration_seconds=duration,
        passed=avg_faith >= 0.85,
    )

    logger.info(
        f"RAGAS 评估完成: questions={report.total_questions}, "
        f"faithfulness={report.avg_faithfulness:.2%}, "
        f"context_recall={report.avg_context_recall:.2%}, "
        f"passed={'✅' if report.passed else '❌'}, "
        f"duration={report.duration_seconds:.1f}s"
    )

    return report


# ---------------------------------------------------------------------------
# 指标计算（简化版）
# ---------------------------------------------------------------------------

def _compute_faithfulness(answer: str, contexts: list[str], ground_truth: str) -> float:
    """计算 Faithfulness — 答案是否忠实于上下文。

    简化计算：答案与 ground_truth 的词重叠率。
    完整版应使用 RAGAS 框架的 NLI 模型。
    """
    if not answer or not ground_truth:
        return 0.0

    answer_words = set(answer.lower().split())
    truth_words = set(ground_truth.lower().split())

    if not truth_words:
        return 0.0

    overlap = len(answer_words & truth_words)
    return min(overlap / max(len(truth_words), 1), 1.0)


def _compute_context_recall(contexts: list[str], ground_truth: str) -> float:
    """计算 Context Recall — 上下文是否覆盖了 ground truth 信息。

    简化计算：ground_truth 中的关键词在上下文中出现的比例。
    """
    if not contexts or not ground_truth:
        return 0.0

    context_text = " ".join(contexts).lower()
    truth_words = set(ground_truth.lower().split())

    if not truth_words:
        return 0.0

    found = sum(1 for w in truth_words if w in context_text)
    return found / len(truth_words)


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------

def generate_report_markdown(report: RAGASReport) -> str:
    """生成 Markdown 格式的评估报告。"""
    status = "✅ PASSED" if report.passed else "❌ FAILED"

    lines = [
        "# RAGAS Evaluation Report",
        "",
        f"**Status**: {status}",
        f"**Total Questions**: {report.total_questions}",
        f"**Avg Faithfulness**: {report.avg_faithfulness:.2%}",
        f"**Avg Context Recall**: {report.avg_context_recall:.2%}",
        f"**Duration**: {report.duration_seconds:.1f}s",
        "",
        "## Detailed Results",
        "",
        "| # | Question | Faithfulness | Recall |",
        "|---|---------|-------------|--------|",
    ]

    for i, r in enumerate(report.results, 1):
        q_short = r.question[:40] + "..." if len(r.question) > 40 else r.question
        lines.append(
            f"| {i} | {q_short} | {r.faithfulness:.2%} | {r.context_recall:.2%} |"
        )

    return "\n".join(lines)
