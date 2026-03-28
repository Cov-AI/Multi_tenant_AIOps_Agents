"""
StateGraph 状态定义 - P1 六状态架构
对应 tasks.md: Task 8.1 - 重构 AIOps Agent 为六状态 StateGraph
"""

from typing import TypedDict, Annotated, List, Any, Optional
from enum import Enum
import operator


class SystemState(str, Enum):
    """系统状态枚举，对应 Incident 模型中的状态"""
    TRIGGERED = "TRIGGERED"           # 初始化触发
    ANALYZING = "ANALYZING"           # 正在分析（调用 RAG/Loki）
    AWAITING_APPROVAL = "AWAITING_APPROVAL" # 等待人工审批
    EXECUTING = "EXECUTING"           # 正在执行修复方案
    VERIFYING = "VERIFYING"           # 正在验证恢复情况
    RESOLVED = "RESOLVED"             # 已解决
    ESCALATED = "ESCALATED"           # 升级（失败或拒绝时）


class IncidentState(TypedDict):
    """
    AIOps StateGraph 核心状态
    """
    
    # 基础信息
    incident_id: str
    tenant_id: str             # 多租户环境标识
    state: SystemState         # 当前流转状态 (显式记录状态，利于被读取和监控)
    
    # 上下文输入
    user_input: str            # 最早触发的提问、告警描述等
    
    # 分析结果 (analyze_node 填充)
    # 使用 operator.add 可以将多种工具产生的诊断证据累加
    analysis_evidence: Annotated[List[str], operator.add]
    analysis_report: Optional[str]
    
    # 执行方案 (plan_node 填充)
    risk_level: Optional[str]        # 风险定级 (low / high)
    execution_plan: Optional[str]    # 修复计划或待执行的指令 (Mock YAML 或步骤)
    
    # 验证与历史行为
    action_logs: Annotated[List[Any], operator.add]
    verified: Optional[bool]
