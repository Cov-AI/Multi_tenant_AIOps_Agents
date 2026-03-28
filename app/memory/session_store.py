"""
三层会话存储: Redis(热数据) -> Postgres(元数据) -> S3(冷归档数据)
对应 tasks.md: Task 12.1
"""

import json
from datetime import datetime
from typing import List, Dict, Any, Tuple
from loguru import logger
from redis.asyncio import Redis, from_url

from app.config import config
from app.storage.database import tenant_session
from app.storage.models import Session

# P1阶段 Mock S3 Service
class MockS3Service:
    def __init__(self):
        self.buckets = {"oncall-sessions": {}}
        
    async def put_object(self, bucket: str, key: str, body: str) -> None:
        self.buckets[bucket][key] = body
        logger.info(f"[S3 Mock] Saved {len(body)} bytes to s3://{bucket}/{key}")
        
    async def get_object(self, bucket: str, key: str) -> str:
        if key in self.buckets[bucket]:
            logger.info(f"[S3 Mock] Fetched from s3://{bucket}/{key}")
            return self.buckets[bucket][key]
        raise ValueError("NoSuchKey")

mock_s3 = MockS3Service()


class SessionStore:
    """管理在 Redis、PostgreSQL、S3 中的多级 Session 上下文与元数据"""
    
    def __init__(self):
        self.redis_url = getattr(config, "redis_url", "redis://localhost:6379/1")
        self._redis: Redis | None = None
        
    async def get_redis(self) -> Redis:
        if self._redis is None:
            self._redis = from_url(self.redis_url, decode_responses=True)
        return self._redis

    async def append_message(self, tenant_id: str, session_key: str, message: Dict[str, Any]) -> None:
        """
        [热数据] 向 Redis 追加新消息并异步更新 DB 的使用情况与最后活跃时间 
        """
        redis = await self.get_redis()
        # 1. 写入 Redis
        redis_key = f"tenant:{tenant_id}:session:{session_key}:messages"
        await redis.rpush(redis_key, json.dumps(message, ensure_ascii=False))
        # 热数据默认保存24H的过期时间，归档任务在24小时内未活跃时触发
        await redis.expire(redis_key, 86400 * 3) # 保留3天，防止归档任务失败
        
        # 2. 异步更新 PostgreSQL (元数据)
        try:
            # 这里的 token count 应该从 message 获取，这里作为示例简单算一下
            tokens = len(str(message)) // 2 
            
            async with tenant_session(tenant_id=tenant_id) as session:
                # 若需要精确更新，可以使用 update 语句，此处简化
                import sqlalchemy as sa
                result = await session.execute(
                    sa.select(Session).where(Session.session_key == session_key)
                )
                db_sess = result.scalar_one_or_none()
                if db_sess:
                    db_sess.last_active = datetime.utcnow()
                    db_sess.token_count += tokens
                    # session 自动 commit
        except Exception as e:
            logger.warning(f"更新 Session 元数据失败 (可能无 DB): {e}")

    async def recover_session(self, tenant_id: str, session_key: str) -> Tuple[List[Dict[str, Any]], str]:
        """
        获取一个 Session 的对话历史：
        如果 Redis 没有，自动从 S3 降级恢复冷数据到 Redis
        """
        redis = await self.get_redis()
        redis_key = f"tenant:{tenant_id}:session:{session_key}:messages"
        
        # 1. 尝试从 Redis 拿
        raw_msgs = await redis.lrange(redis_key, 0, -1)
        if raw_msgs:
            logger.debug(f"[Session {session_key}] 从 Redis 热恢复 {len(raw_msgs)} 条消息")
            return [json.loads(m) for m in raw_msgs], "redis"
            
        # 2. Redis 拿不到（过期被归档），尝试从 S3 拿
        try:
            jsonl_data = await mock_s3.get_object("oncall-sessions", f"{tenant_id}/{session_key}.jsonl")
            messages = [json.loads(line) for line in jsonl_data.splitlines() if line.strip()]
            
            logger.info(f"[Session {session_key}] 从 S3 冷恢复全量记录")
            
            # 将最近的一些对话重新塞回 Redis
            if messages:
                for msg in messages[-20:]:
                    await redis.rpush(redis_key, json.dumps(msg, ensure_ascii=False))
                await redis.expire(redis_key, 86400)
                
            return messages, "s3"
        except Exception as e:
            logger.debug(f"[Session {session_key}] 冷恢复未找到记录: {e}")
            return [], "none"

    async def archive_cold_sessions(self, tenant_id: str, old_session_keys: List[str]) -> None:
        """
        定时任务的一部分：处理旧的非活跃 Session 自动写入 S3 然后清理 Redis
        """
        redis = await self.get_redis()
        for s_key in old_session_keys:
            redis_key = f"tenant:{tenant_id}:session:{s_key}:messages"
            try:
                raw_msgs = await redis.lrange(redis_key, 0, -1)
                if not raw_msgs:
                    continue
                    
                # 写入 S3
                body = "\n".join(raw_msgs)
                await mock_s3.put_object("oncall-sessions", f"{tenant_id}/{s_key}.jsonl", body)
                
                # S3写入成功后，从 Redis 中删除以释放昂贵的内存
                await redis.delete(redis_key)
                logger.info(f"会话 {s_key} 的冷数据 {len(raw_msgs)} 条已归档至 S3。")
                
            except Exception as e:
                logger.error(f"归档失败 Session {s_key}: {e}", exc_info=True)


session_store = SessionStore()
