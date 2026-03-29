"""
Workspace (Agent 配置) 缓存与存储层服务
对应 tasks.md: Task 18.1
"""

import json
from typing import Dict, Any, Optional
from loguru import logger

from app.memory.session_store import session_store
from app.storage.database import tenant_session
from app.storage.models import Agent

class WorkspaceConfigService:
    """提供通过 AgentID 或 TenantID 抓取其专属 workspace config 的能力，提供 Redis 二级缓存优化"""
    
    CACHE_TTL = 3600  # Redis 缓存寿命设为 1 小时
    
    @staticmethod
    def _cache_key(agent_id: str) -> str:
        return f"workspace:config:{agent_id}"
        
    @staticmethod
    async def get_config(tenant_id: str, agent_id: str) -> Dict[str, Any]:
        """优先从缓存拿。如果没有则查库并反向填回 Redis"""
        
        redis = None
        try:
            redis = await session_store.get_redis()
            cached = await redis.get(WorkspaceConfigService._cache_key(agent_id))
            if cached:
                # Cache Hit!
                try:
                    return json.loads(cached)
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            logger.warning(f"从 Redis 读取 Workspace Config 时出现异常, 降级直查 DB: {e}")
            
        # Cache Miss or Redis Offline: Query Database
        config_data = {}
        try:
            import sqlalchemy as sa
            async with tenant_session(tenant_id=tenant_id) as session:
                res = await session.execute(
                    sa.select(Agent.config).where(Agent.id == agent_id, Agent.tenant_id == tenant_id)
                )
                config_data = res.scalar_one_or_none() or {}
        except Exception as e:
            logger.error(f"从 PostgreSQL 读取 Workspace 配置失败: {e}", exc_info=True)
            return config_data # 返回空壳防止崩溃
            
        # Re-warm Cache if Redis is okay
        if redis:
            try:
                # 防止无用内容被持久化导致无限空转
                await redis.setex(
                    WorkspaceConfigService._cache_key(agent_id),
                    WorkspaceConfigService.CACHE_TTL,
                    json.dumps(config_data, ensure_ascii=False)
                )
            except Exception as e:
                logger.debug(f"回填 Workspace 配置至缓存失败 (不影响链路): {e}")

        return config_data

    @staticmethod
    async def update_config(tenant_id: str, agent_id: str, updates: Dict[str, Any]) -> bool:
        """更新工作区配置：双写模式（写库 + 清除/更新缓存）"""
        try:
            import sqlalchemy as sa
            async with tenant_session(tenant_id=tenant_id) as session:
                result = await session.execute(
                    sa.select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id)
                )
                agent = result.scalar_one_or_none()
                if not agent:
                    logger.warning(f"[Workspace Service] Update 失败: 查无此 Agent({agent_id})")
                    return False
                    
                # 累加合并字典对象
                current_conf = agent.config or {}
                current_conf.update(updates)
                agent.config = current_conf
                
                await session.commit()
                
            # 删缓存迫使其下一次 get 的时候 reload
            try:
                redis = await session_store.get_redis()
                await redis.delete(WorkspaceConfigService._cache_key(agent_id))
            except Exception:
                pass 
                
            return True
        except Exception as e:
            logger.error(f"Workspace 配置 Update 异常: {e}", exc_info=True)
            return False
