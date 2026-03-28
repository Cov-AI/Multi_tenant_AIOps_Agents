"""
StateGraph 节点实现 - P1 六状态架构
对应 tasks.md: Task 8.1 - 实现 analyze_node, plan_node, wait_for_approval_node, execute_node, verify_node

注意：开源版本，MCP 调用先以 Mock 进行功能打通验证，后续接入真实的 MCP 模块。
不硬编码敏感 Token/URL。
"""

import json
from loguru import logger
from typing import Dict, Any
from app.agent.aiops_v2.state import IncidentState, SystemState
from app.core.llm_factory import get_chat_llm
from langchain_core.messages import SystemMessage, HumanMessage


async def analyze_node(state: IncidentState) -> Dict:
    """
    ANALYZING 节点
    并行调用 MCP 工具：Loki、Prometheus、RAG 检索 (目前 Mock)。
    """
    logger.info(f"[{state.get('incident_id')}] 进入 analyze_node (ANALYZING)")
    
    # Mock 并行请求 MCP 和 RAG (TODO: 这里未来由具体的 MCP Tool Client 替换)
    logger.debug("Mocking 告警查询 (Prometheus), 日志分析 (Loki) 与历史诊断 (RAG)...")
    
    user_input = state.get("user_input", "")
    
    mock_evidence = [
        f"Prometheus 指标异常: CPU 利用率突增至 98% (来源: {user_input})",
        "Loki 错误日志: OOM Killed, Java 进程崩溃",
        "RAG 历史经验: 上次同样现象是因为内存泄露，建议清空缓存并重启容器"
    ]
    
    return {
        "state": SystemState.ANALYZING,
        "analysis_evidence": mock_evidence,
        "analysis_report": "\n".join(mock_evidence),
        "action_logs": [{"action": "analyze", "status": "success"}]
    }


async def plan_node(state: IncidentState) -> Dict:
    """
    计算/决策节点
    调用 LLM 基于 Context 决定修复策略及定级 (高危 / 低危)。
    """
    logger.info(f"[{state.get('incident_id')}] 进入 plan_node")
    
    evidence = state.get("analysis_report", "")
    input_text = state.get("user_input", "")
    
    llm = get_chat_llm(temperature=0.1, streaming=False)
    
    sys_prompt = (
        "你是一个架构师诊断 Agent。我们遇到了以下状况:\n"
        f"用户输入: {input_text}\n"
        f"证据调查结果:\n{evidence}\n\n"
        "请返回纯 JSON 格式：\n"
        "{\n"
        '  "plan": "重启容器",\n'
        '  "risk": "high" 或者 "low"\n'
        "}\n"
        "规则：任何修改配置、重启、重启集群等带有直接写操作的动作为 high，只读或轻微操作为 low。"
    )
    
    try:
        response = await llm.ainvoke([HumanMessage(content=sys_prompt)])
        content = response.content.strip()
        
        # 去掉 markdown pre-block 
        if content.startswith("```json"):
            content = content[7:-3]
        elif content.startswith("```"):
            content = content[3:-3]
            
        decision = json.loads(content)
        risk = decision.get("risk", "low").lower()
        plan = decision.get("plan", "No structural plan generated")
    except Exception as e:
        logger.error(f"Plan_node LLM 失败, 默认降级为 high 风险: {e}")
        risk = "high"
        plan = "Fallback plan: Requires manual intervention due to LLM error"
        
    return {
        "risk_level": risk,
        "execution_plan": plan,
        "action_logs": [{"action": "plan", "risk": risk, "plan": plan}]
    }


def wait_for_approval_node(state: IncidentState) -> Dict:
    """
    挂起点节点 (AWAITING_APPROVAL)。
    LangGraph 会在使用 interrupt() 或配置 interrupt_before 时，将图在此暂停。
    这里仅做状态标记。
    """
    logger.info(f"[{state.get('incident_id')}] 进入 wait_for_approval_node (AWAITING_APPROVAL)")
    return {
        "state": SystemState.AWAITING_APPROVAL,
        "action_logs": [{"action": "wait_approval", "status": "pending"}]
    }


async def execute_node(state: IncidentState) -> Dict:
    """
    EXECUTING 节点
    执行 `execution_plan` (Task 10 YAML 工作流引擎预留处，目前 Mock 执行)
    """
    logger.info(f"[{state.get('incident_id')}] 进入 execute_node (EXECUTING)")
    
    plan_to_exec = state.get("execution_plan", "")
    # TODO: 接入 YAML workflow engine (workflow/engine.py)
    logger.debug(f"Mock 执行方案: {plan_to_exec}")
    
    return {
        "state": SystemState.EXECUTING,
        "action_logs": [{"action": "execute", "status": "success", "plan": plan_to_exec}]
    }


async def verify_node(state: IncidentState) -> Dict:
    """
    VERIFYING 节点
    验证操作是否修复了告警/指标。
    """
    logger.info(f"[{state.get('incident_id')}] 进入 verify_node (VERIFYING)")
    
    # TODO: 调用 Prometheus 查询修复后的指标，验证是否真正恢复
    # Mock：假设执行后一切恢复正常
    verified = True
    logger.debug(f"Mock 验证结果: {verified}")
    
    return {
        "state": SystemState.VERIFYING,
        "verified": verified,
        "action_logs": [{"action": "verify", "result": verified}]
    }


def resolve_node(state: IncidentState) -> Dict:
    """
    已解决节点
    """
    logger.info(f"[{state.get('incident_id')}] 事故已解决 (RESOLVED)")
    return {"state": SystemState.RESOLVED}

def escalate_node(state: IncidentState) -> Dict:
    """
    升级节点 (失败或拒绝审批时)
    """
    logger.warning(f"[{state.get('incident_id')}] 事故已升级 (ESCALATED)")
    return {"state": SystemState.ESCALATED}
