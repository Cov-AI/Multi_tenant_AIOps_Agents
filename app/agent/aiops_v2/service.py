"""
StateGraph 服务包装 - P1 六状态架构
对应 tasks.md: Task 8.1 - 重构 AIOps Agent 构造 StateGraph
"""

from typing import Dict, AsyncGenerator, Any
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from loguru import logger

from app.memory.checkpoint import get_checkpointer
from app.workflow.approval import ApprovalManager
from app.observability.tracing import TracingManager

from app.agent.aiops_v2.state import IncidentState, SystemState
from app.agent.aiops_v2.nodes import (
    analyze_node,
    plan_node,
    wait_for_approval_node,
    execute_node,
    verify_node,
    resolve_node,
    escalate_node,
)


class AIOpsServiceV2:
    """基于 StateGraph 的六状态 AIOps Agent 服务"""

    def __init__(self):
        self.raw_graph = self._build_graph()
        self._fallback_memory_saver = MemorySaver()
        logger.info("AIOps Workflow StateGraph 初始化完成 (版本 V2)")

    def _build_graph(self):
        """构建六状态工作流图"""
        logger.info("构建六状态工作流图 (TRIGGERED -> RESOLVED)...")

        workflow = StateGraph(IncidentState)

        # 添加所有节点
        workflow.add_node("analyze", analyze_node)
        workflow.add_node("plan", plan_node)
        workflow.add_node("wait_for_approval", wait_for_approval_node)
        workflow.add_node("execute", execute_node)
        workflow.add_node("verify", verify_node)
        workflow.add_node("resolve", resolve_node)
        workflow.add_node("escalate", escalate_node)

        # 1. 触发后第一步：分析
        workflow.add_edge(START, "analyze")
        workflow.add_edge("analyze", "plan")

        # 2. 计划生成后：通过条件路由判断是否需要审批
        def route_after_plan(state: IncidentState) -> str:
            risk = state.get("risk_level", "high")
            if risk == "high":
                logger.info(f"[{state.get('incident_id')}] 规划路由: high risk, 转向 await_approval")
                return "wait_for_approval"
            logger.info(f"[{state.get('incident_id')}] 规划路由: low risk, 直接 execute")
            return "execute"

        workflow.add_conditional_edges(
            "plan",
            route_after_plan,
            {"wait_for_approval": "wait_for_approval", "execute": "execute"}
        )

        # 3. 审批后 -> 执行
        # Note: 审批被拒绝的逻辑会在 Task 11 补全 (加入 approval 结果读取条件)
        workflow.add_edge("wait_for_approval", "execute")

        # 4. 执行后 -> 验证
        workflow.add_edge("execute", "verify")

        # 5. 验证后条件路由：成功还是升级
        def route_after_verify(state: IncidentState) -> str:
            if state.get("verified", False):
                return "resolve"
            return "escalate"

        workflow.add_conditional_edges(
            "verify",
            route_after_verify,
            {"resolve": "resolve", "escalate": "escalate"}
        )

        # 6. 终点
        workflow.add_edge("resolve", END)
        workflow.add_edge("escalate", END)

        return workflow

    async def execute_incident(
        self,
        incident_id: str,
        user_input: str,
        tenant_id: str = "default_tenant"
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        发起告警处理流程 (替代原来的 execute)
        """
        logger.info(f"[事件 {incident_id}] 启动 AIOps 流水线...")

        initial_state: IncidentState = {
            "incident_id": incident_id,
            "tenant_id": tenant_id,
            "state": SystemState.TRIGGERED,
            "user_input": user_input,
            "analysis_evidence": [],
            "action_logs": []
        }
        logger.info(f"[事件 {incident_id}] 新流程启动")
        
        # 通过 TracingManager 生成带有 Observability Telemetry Metadata 的请求配置
        config_dict = TracingManager.get_langgraph_config(tenant_id, incident_id)

        try:
            async with get_checkpointer() as checkpointer:
                # 若无法连接 Postgres，降级为应用级单例 MemorySaver
                saver = checkpointer if checkpointer is not None else self._fallback_memory_saver
                
                compiled_graph = self.raw_graph.compile(
                    checkpointer=saver,
                    interrupt_before=["wait_for_approval"]
                )
                
                async for event in compiled_graph.astream(
                    input=initial_state,
                    config=config_dict,
                    stream_mode="updates"
                ):
                    for node_name, node_output in event.items():
                        log_msg = f"节点 '{node_name}' 执行完成"
                        logger.debug(log_msg)
                        
                        if not isinstance(node_output, dict):
                            continue
                            
                        # 将事件向外推送
                        yield {
                            "type": "workflow_update",
                            "node": node_name,
                            "state_snapshot": node_output.get("state", "UNKNOWN")
                        }

                # 判断是否中断 (因为 interrupt_before="wait_for_approval")
                snapshot = compiled_graph.get_state(config_dict)
                if snapshot.next and "wait_for_approval" in snapshot.next:
                    # 记录并生成审批 Token
                    token = await ApprovalManager.create_approval(
                        tenant_id=tenant_id,
                        incident_id=incident_id,
                        requested_by="", # System
                        message=f"事件 [{incident_id}] 需要进行高危操作执行审批。"
                    )
                    
                    logger.info(f"[事件 {incident_id}] 流程已暂停，等待权限审批 (AWAITING_APPROVAL)")
                    yield {
                        "type": "interrupt",
                        "message": "流程已暂停，等待审批",
                        "next_node": "wait_for_approval",
                        "resume_token": token
                    }
                else:
                    logger.info(f"[事件 {incident_id}] 流程完全结束")

        except Exception as e:
            logger.error(f"[事件 {incident_id}] AIOps 执行异常: {e}", exc_info=True)
            yield {
                "type": "error",
                "message": f"执行错误: {str(e)}"
            }

    async def resume_incident(self, incident_id: str, tenant_id: str) -> None:
        """从断点恢复流转"""
        config_dict = TracingManager.get_langgraph_config(tenant_id, incident_id)
        logger.info(f"[事件 {incident_id}] 收到恢复信号，继续执行图流转")
        
        async with get_checkpointer() as checkpointer:
            saver = checkpointer if checkpointer is not None else self._fallback_memory_saver
            compiled_graph = self.raw_graph.compile(
                checkpointer=saver,
                interrupt_before=["wait_for_approval"]
            )
            
            # 将空请求发给图，即可唤醒继续执行
            async for event in compiled_graph.astream(None, config=config_dict, stream_mode="updates"):
                for node_name, node_output in event.items():
                    logger.info(f"恢复执行节点: {node_name}")
                    
    async def get_state(self, incident_id: str, tenant_id: str):
        """测试/外部获取当前图状态的便捷方法"""
        config_dict = TracingManager.get_langgraph_config(tenant_id, incident_id)
        async with get_checkpointer() as checkpointer:
            saver = checkpointer if checkpointer is not None else self._fallback_memory_saver
            compiled_graph = self.raw_graph.compile(
                checkpointer=saver,
                interrupt_before=["wait_for_approval"]
            )
            return compiled_graph.get_state(config_dict)


# 全局单例
aiops_service_v2 = AIOpsServiceV2()
