"""
监督与分类器 - 判断用户或监控系统的意图以正确路由
对应 tasks.md: Task 14.1 (实现 agents/supervisor.py 意图分类)
"""

from loguru import logger
from app.gateway.models import MessageEnvelope


class AgentSupervisor:
    """
    接收归一化的 MessageEnvelope 数据结构。
    对意图进行分类判别，返回路由的 Agent 目标: 'chat' or 'aiops'
    """
    
    @staticmethod
    def classify_intent(envelope: MessageEnvelope) -> str:
        """简单的意图判决边界"""
        source = envelope.source
        
        # Webhook 过来的报警固定走 AIOps Agent 流程图去分析与修复
        if source == "webhook":
            logger.debug(f"[Supervisor] Webhook事件直接分配给 AIOps Agent: {envelope.content[:20]}")
            return "aiops"
            
        # 来源于 Slack 或者 API 的纯文字如果带有运维意向，或者携带 alert 告警字典元数据
        text_lower = envelope.content.lower()
        if source in ["slack", "api"]:
            # 当存在以下触发动词或名词时，我们启动复杂的流程引擎，其余进入常规 Chat
            aiops_triggers = ["告警", "重启", "宕机", "恢复", "alert", "restart", "failover", "down", "error 500"]
            
            if any(t in text_lower for t in aiops_triggers):
                logger.info(f"[Supervisor] 语义检测为高危/异常运维意图，路由到 aiops: {text_lower[:30]}")
                return "aiops"
                
            logger.info("[Supervisor] 语义检测为只读交互意图，路由到 chat agent")
            return "chat"
            
        return "chat"


supervisor = AgentSupervisor()
