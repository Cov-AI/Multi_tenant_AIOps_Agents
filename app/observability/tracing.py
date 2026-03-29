"""
LangSmith 可观测性与追踪层
对应 tasks.md: Task 20.1 
确保多租户背景下所有的 LLM 触发带着 TenantID 和 IncidentID 方便追踪
"""

import os
from typing import Dict, Any
from loguru import logger

class TracingManager:
    
    @staticmethod
    def get_langgraph_config(tenant_id: str, incident_id: str) -> Dict[str, Any]:
        """
        生成带有标准 metadata 和 tags 的 LangGraph 配置字典对象。
        LangSmith 会自动吸附 configurable、metadata 和 tags 字段，进而体现在云端看板上。
        """
        # 预设的基础 configurable 参数
        config = {
            "configurable": {
                "thread_id": incident_id,
                "tenant_id": tenant_id
            },
            "metadata": {
                "tenant_id": tenant_id,
                "incident_id": incident_id,
                "environment": os.getenv("ENVIRONMENT", "development")
            },
            "tags": [
                f"tenant:{tenant_id}",
                f"incident:{incident_id}"
            ]
        }
        
        # 辅助检查 LangSmith 联通性，提醒开发者
        if not os.getenv("LANGCHAIN_API_KEY"):
            logger.debug("未检测到 LANGCHAIN_API_KEY，追踪只会发生在本地内存而无法上报至 LangSmith 云端。")
            
        return config
