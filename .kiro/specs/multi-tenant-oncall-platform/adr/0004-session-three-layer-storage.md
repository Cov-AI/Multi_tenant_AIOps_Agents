# ADR-0004: Session 三层存储（Redis + PostgreSQL + S3）

## 状态

已接受 (Accepted)

## 上下文

多租户 OnCall 平台需要持久化对话历史，以支持以下场景：

1. **服务重启恢复**：Agent Worker 重启后能继续处理中断的事故
2. **长时间审批**：审批流程可能等待几小时，Session 不能丢失
3. **历史回溯**：SRE 需要查看历史对话，分析事故处理过程
4. **成本优化**：热数据快速访问，冷数据低成本存储

### 数据访问模式

- **热数据**（最近 24 小时）：高频读写，需要毫秒级延迟
- **温数据**（24 小时 - 30 天）：偶尔查询，秒级延迟可接受
- **冷数据**（30 天以上）：很少访问，主要用于审计和分析

### 存储选项对比

| 存储 | 读延迟 | 写延迟 | 成本 | 持久化 | 查询能力 |
|------|--------|--------|------|--------|----------|
| Redis | <1ms | <1ms | 高 | 可选 | 简单 K-V |
| PostgreSQL | 1-10ms | 1-10ms | 中 | 强 | 强大 SQL |
| S3 | 50-200ms | 50-200ms | 低 | 强 | 需要下载 |

## 决策

**采用三层存储架构：Redis（热数据）+ PostgreSQL（元数据）+ S3（归档）**

具体策略：

1. **Redis**：存储最近 24 小时的 Session 消息列表
2. **PostgreSQL**：存储 Session 元数据（session_key、token_count、last_active）
3. **S3**：存储超过 24 小时未活跃的对话 JSONL 归档

## 理由

### 三层架构的优势

#### 1. 性能优化

**热路径（Redis）**：
```python
# Agent 调用时读取最近消息（<1ms）
messages = await redis.lrange(f"session:{session_key}:messages", -5, -1)
```
- ✅ 毫秒级延迟，满足实时对话需求
- ✅ 支持高并发读写
- ✅ 减少数据库压力

**元数据查询（PostgreSQL）**：
```python
# 查询活跃 Session（1-10ms）
sessions = await db.query(Session).filter(
    Session.last_active > now() - timedelta(hours=24)
).all()
```
- ✅ 支持复杂查询（按租户、时间范围、token 消耗等）
- ✅ 事务保证，确保元数据一致性

**归档访问（S3）**：
```python
# 查看历史对话（50-200ms）
jsonl = await s3.get_object(
    Bucket="oncall-sessions",
    Key=f"{session_key}.jsonl"
)
```
- ✅ 低成本存储大量历史数据
- ✅ 支持生命周期策略（自动删除过期数据）

#### 2. 成本优化

**存储成本对比**（假设 1GB 数据）：

| 存储 | 月成本 | 年成本 |
|------|--------|--------|
| Redis | $50-100 | $600-1200 |
| PostgreSQL | $10-20 | $120-240 |
| S3 Standard | $0.023 | $0.28 |
| S3 Glacier | $0.004 | $0.05 |

- ✅ 热数据用 Redis（快但贵）
- ✅ 元数据用 PostgreSQL（中等成本）
- ✅ 冷数据用 S3（便宜）
- ✅ 总成本远低于全部用 Redis

#### 3. 可靠性保证

**数据持久化**：
```
Redis（可选 AOF）→ PostgreSQL（强持久化）→ S3（11 个 9 的可靠性）
```
- ✅ Redis 宕机：从 PostgreSQL 恢复元数据，从 S3 恢复历史消息
- ✅ PostgreSQL 宕机：Redis 仍可服务热数据
- ✅ S3 作为最终归档，确保数据不丢失

**服务重启恢复**：
```python
async def recover_session(session_key: str):
    # 1. 从 PostgreSQL 读取元数据
    session = await db.get_session(session_key)
    
    # 2. 尝试从 Redis 读取消息
    messages = await redis.lrange(f"session:{session_key}:messages", 0, -1)
    
    # 3. 如果 Redis 没有，从 S3 恢复
    if not messages:
        jsonl = await s3.get_object(Key=f"{session_key}.jsonl")
        messages = [json.loads(line) for line in jsonl.splitlines()]
        
        # 重新加载到 Redis
        for msg in messages[-10:]:  # 只加载最近 10 条
            await redis.rpush(f"session:{session_key}:messages", json.dumps(msg))
    
    return session, messages
```

#### 4. 扩展性

**水平扩展**：
- Redis：使用 Redis Cluster 分片
- PostgreSQL：使用读写分离 + 分区表
- S3：天然支持无限扩展

**数据生命周期管理**：
```python
# 定时任务：归档冷数据
async def archive_cold_sessions():
    # 查询 24 小时未活跃的 Session
    cold_sessions = await db.query(Session).filter(
        Session.last_active < now() - timedelta(hours=24)
    ).all()
    
    for session in cold_sessions:
        # 从 Redis 读取消息
        messages = await redis.lrange(f"session:{session.session_key}:messages", 0, -1)
        
        # 写入 S3
        jsonl = "\n".join(messages)
        await s3.put_object(
            Bucket="oncall-sessions",
            Key=f"{session.session_key}.jsonl",
            Body=jsonl
        )
        
        # 从 Redis 删除
        await redis.delete(f"session:{session.session_key}:messages")
        
        # 更新 PostgreSQL 状态
        session.archived = True
        await db.commit()
```

### 考虑的替代方案

#### 方案 A：全部用 PostgreSQL

**优势**：
- 架构简单，只需维护一个存储
- 强大的查询能力

**局限**：
- ❌ 性能不足（10ms 延迟 vs Redis 的 <1ms）
- ❌ 高并发下数据库压力大
- ❌ 存储成本高（相比 S3）

#### 方案 B：全部用 Redis

**优势**：
- 性能最好
- 架构简单

**局限**：
- ❌ 成本极高（Redis 内存贵）
- ❌ 持久化可靠性不如 PostgreSQL
- ❌ 查询能力弱（只能 K-V 查询）
- ❌ 不适合长期存储

#### 方案 C：Redis + PostgreSQL（无 S3）

**优势**：
- 性能好
- 查询能力强

**局限**：
- ❌ 长期存储成本高
- ❌ 历史数据占用数据库空间
- ❌ 不符合冷热分离最佳实践

#### 方案 D：PostgreSQL + S3（无 Redis）

**优势**：
- 成本低
- 持久化可靠

**局限**：
- ❌ 性能不足（无热数据缓存）
- ❌ 高并发下数据库压力大

### 为什么选择三层架构

1. **性能**：Redis 提供毫秒级热数据访问
2. **成本**：S3 大幅降低冷数据存储成本
3. **可靠性**：PostgreSQL 提供强持久化保证
4. **扩展性**：每层独立扩展，互不影响
5. **业界实践**：符合冷热分离的最佳实践

## 后果

### 正面影响

1. **性能优化**：热数据毫秒级访问，满足实时对话需求
2. **成本优化**：冷数据存储成本降低 99%（S3 vs Redis）
3. **可靠性保证**：多层备份，数据不丢失
4. **扩展性强**：每层独立扩展，支持大规模部署

### 负面影响

1. **架构复杂**：需要维护三个存储系统
2. **数据一致性**：需要确保三层数据同步
3. **归档延迟**：冷数据访问需要从 S3 下载（50-200ms）

### 风险缓解

1. **数据一致性保证**：
   ```python
   async def append_message(session_key: str, message: dict):
       # 1. 写入 Redis（热数据）
       await redis.rpush(f"session:{session_key}:messages", json.dumps(message))
       
       # 2. 更新 PostgreSQL 元数据（事务保证）
       async with db.begin():
           session = await db.get_session(session_key)
           session.token_count += count_tokens(message)
           session.last_active = now()
           await db.commit()
       
       # 3. S3 归档由定时任务异步处理（不阻塞主流程）
   ```

2. **归档失败处理**：
   ```python
   async def archive_with_retry(session_key: str):
       for attempt in range(3):
           try:
               await archive_session(session_key)
               break
           except Exception as e:
               logger.error("archive_failed", session_key=session_key, attempt=attempt)
               if attempt == 2:
                   # 归档失败，保留在 Redis（不删除）
                   await redis.expire(f"session:{session_key}:messages", 86400 * 7)  # 延长 7 天
   ```

3. **恢复测试**：
   ```python
   @pytest.mark.integration
   async def test_session_recovery_from_s3():
       """验证从 S3 恢复 Session"""
       # 1. 创建 Session 并归档
       session_key = create_test_session()
       await archive_session(session_key)
       
       # 2. 清空 Redis
       await redis.delete(f"session:{session_key}:messages")
       
       # 3. 恢复 Session
       session, messages = await recover_session(session_key)
       
       # 4. 验证数据完整性
       assert len(messages) > 0
       assert session.session_key == session_key
   ```

4. **监控告警**：
   ```python
   # Prometheus 指标
   session_archive_duration = Histogram(
       "session_archive_duration_seconds",
       "Time to archive a session"
   )
   
   session_archive_failures = Counter(
       "session_archive_failures_total",
       "Number of failed session archives"
   )
   ```

### 实施检查清单

- [ ] Redis 配置 AOF 持久化
- [ ] PostgreSQL sessions 表创建索引（session_key、last_active）
- [ ] S3 Bucket 配置生命周期策略（90 天后转 Glacier）
- [ ] 实现归档定时任务（每小时运行）
- [ ] 实现恢复逻辑（从 S3 恢复到 Redis）
- [ ] 编写集成测试（归档 + 恢复）
- [ ] 配置监控告警（归档失败、恢复失败）
- [ ] 文档化数据生命周期策略

## 相关决策

- ADR-0003: 使用 PostgreSQL RLS 作为数据隔离的最后防线
- ADR-0005: 四层上下文 Compaction vs 固定截断

## 参考资料

- [Redis Persistence](https://redis.io/docs/management/persistence/)
- [PostgreSQL Partitioning](https://www.postgresql.org/docs/current/ddl-partitioning.html)
- [AWS S3 Lifecycle Policies](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html)
- ONCALL_FINAL.md 第五章：Session 持久化 - 三层存储策略

## 决策日期

2026-03-22

## 决策者

项目团队
