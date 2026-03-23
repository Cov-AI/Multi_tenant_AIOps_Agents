# ADR-0006: 使用 PostgreSQL 存储 Checkpoint（而非 Redis）

## 状态

已接受 (Accepted)

## 上下文

LangGraph 需要持久化 Checkpoint 以支持图执行的暂停和恢复。OnCall 平台的审批流程可能等待几小时甚至几天，Checkpoint 必须可靠持久化。

### Checkpoint 的作用

1. **审批流程暂停**：高危操作需要人工审批，图执行暂停在 `interrupt()` 节点
2. **服务重启恢复**：Agent Worker 重启后能从断点继续执行
3. **错误恢复**：执行失败后能从最近的 Checkpoint 重试
4. **审计追溯**：记录图执行的完整状态变化

### Checkpoint 数据特征

- **大小**：通常 1-10KB（包含图状态、已完成节点、变量值）
- **访问频率**：低频（只在暂停/恢复时访问）
- **持久化要求**：强持久化（不能丢失）
- **查询需求**：需要按 incident_id、tenant_id 查询

### 存储选项对比

| 存储 | 持久化 | 查询能力 | 成本 | 事务支持 |
|------|--------|----------|------|----------|
| Redis | 可选（AOF） | 简单 K-V | 高 | 无 |
| PostgreSQL | 强 | 强大 SQL | 中 | 强 |
| S3 | 强 | 需要下载 | 低 | 无 |

## 决策

**使用 PostgreSQL 存储 LangGraph Checkpoint，而非 Redis。**

具体实施：

1. 创建 `checkpoints` 表存储 Checkpoint 数据
2. 使用 PostgreSQL 的 JSONB 类型存储图状态
3. 启用 RLS 确保租户隔离
4. 创建索引支持快速查询

## 理由

### PostgreSQL 的优势

#### 1. 强持久化保证

**Redis 的问题**：
```python
# Redis AOF 持久化有延迟
await redis.set(f"checkpoint:{incident_id}", checkpoint_data)
# 如果此时 Redis 崩溃，数据可能丢失（AOF 默认每秒 fsync）
```
- ❌ AOF 持久化有延迟（默认每秒 fsync）
- ❌ RDB 快照可能丢失最近的数据
- ❌ 不适合关键业务数据

**PostgreSQL 的优势**：
```python
# PostgreSQL 事务保证
async with db.begin():
    checkpoint = Checkpoint(
        incident_id=incident_id,
        checkpoint_data=checkpoint_data
    )
    await db.add(checkpoint)
    await db.commit()
# 提交成功后，数据已持久化到磁盘
```
- ✅ 事务保证（ACID）
- ✅ WAL（Write-Ahead Logging）确保数据不丢失
- ✅ 适合关键业务数据

#### 2. 强大的查询能力

**Redis 的局限**：
```python
# Redis 只能通过 key 查询
checkpoint = await redis.get(f"checkpoint:{incident_id}")

# 无法查询"租户 A 的所有未完成 Checkpoint"
# 需要遍历所有 key（性能差）
```
- ❌ 只支持 K-V 查询
- ❌ 无法按条件过滤
- ❌ 无法关联查询

**PostgreSQL 的优势**：
```python
# PostgreSQL 支持复杂查询
# 查询租户 A 的所有未完成 Checkpoint
checkpoints = await db.query(Checkpoint).filter(
    Checkpoint.tenant_id == tenant_id,
    Checkpoint.completed == False
).all()

# 查询最近 24 小时的 Checkpoint
checkpoints = await db.query(Checkpoint).filter(
    Checkpoint.created_at > now() - timedelta(hours=24)
).all()

# 关联查询（Checkpoint + Incident）
results = await db.query(Checkpoint, Incident).join(
    Incident, Checkpoint.incident_id == Incident.id
).filter(
    Incident.state == "AWAITING_APPROVAL"
).all()
```
- ✅ 支持复杂查询
- ✅ 支持关联查询
- ✅ 支持索引优化

#### 3. 租户隔离

**PostgreSQL RLS**：
```sql
-- 启用 RLS
ALTER TABLE checkpoints ENABLE ROW LEVEL SECURITY;

-- 创建租户隔离策略
CREATE POLICY tenant_isolation ON checkpoints
    USING (tenant_id = current_setting('app.tenant_id')::uuid);
```
- ✅ 数据库层强制隔离
- ✅ 防止应用层 bug 导致的数据泄露
- ✅ 符合合规要求

**Redis 的局限**：
- ❌ 只能通过应用层过滤
- ❌ 容易遗漏 tenant_id 前缀
- ❌ 无法防止应用层 bug

#### 4. 审计和合规

**PostgreSQL 的优势**：
```sql
-- 查询审计日志
SELECT 
    c.id,
    c.incident_id,
    c.created_at,
    i.state,
    a.action
FROM checkpoints c
JOIN incidents i ON c.incident_id = i.id
JOIN audit_logs a ON a.resource = 'checkpoint:' || c.id
WHERE c.tenant_id = '...'
ORDER BY c.created_at DESC;
```
- ✅ 支持关联查询（Checkpoint + Incident + Audit Log）
- ✅ 支持时间范围查询
- ✅ 满足合规审计要求

**Redis 的局限**：
- ❌ 无法关联查询
- ❌ 无法按时间范围查询
- ❌ 不适合审计场景

#### 5. 成本考虑

**Checkpoint 访问频率低**：
- 只在暂停时写入（低频）
- 只在恢复时读取（低频）
- 不需要毫秒级延迟（10ms 可接受）

**成本对比**：
- Redis：高成本（内存贵），但提供毫秒级延迟（不需要）
- PostgreSQL：中等成本，提供 10ms 延迟（足够）

**结论**：PostgreSQL 性价比更高。

### Checkpoint 表设计

```sql
CREATE TABLE checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    checkpoint_data JSONB NOT NULL,  -- LangGraph 图状态
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 索引
CREATE INDEX idx_checkpoints_tenant_id ON checkpoints(tenant_id);
CREATE INDEX idx_checkpoints_incident_id ON checkpoints(incident_id);
CREATE INDEX idx_checkpoints_completed ON checkpoints(completed);
CREATE INDEX idx_checkpoints_created_at ON checkpoints(created_at);

-- 启用 RLS
ALTER TABLE checkpoints ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON checkpoints
    USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

### LangGraph 集成

```python
from langgraph.checkpoint.postgres import PostgresSaver

# 创建 PostgreSQL Checkpoint Saver
checkpointer = PostgresSaver(
    conn=db_connection,
    table_name="checkpoints"
)

# 编译图时指定 checkpointer
graph = StateGraph(...)
graph.add_node(...)
graph.add_edge(...)

compiled_graph = graph.compile(
    checkpointer=checkpointer,
    interrupt_before=["wait_for_approval"]
)

# 执行图（自动保存 Checkpoint）
result = await compiled_graph.ainvoke(
    input_data,
    config={"configurable": {"thread_id": incident_id}}
)

# 恢复图执行
result = await compiled_graph.ainvoke(
    None,  # 从 Checkpoint 恢复，不需要新输入
    config={"configurable": {"thread_id": incident_id}}
)
```

### 考虑的替代方案

#### 方案 A：使用 Redis 存储 Checkpoint

**优势**：
- 性能好（毫秒级延迟）
- 实现简单

**局限**：
- ❌ 持久化可靠性不如 PostgreSQL
- ❌ 查询能力弱（只能 K-V 查询）
- ❌ 无法关联查询
- ❌ 租户隔离只能靠应用层
- ❌ 不适合审计场景

#### 方案 B：使用 S3 存储 Checkpoint

**优势**：
- 成本低
- 持久化可靠

**局限**：
- ❌ 延迟高（50-200ms）
- ❌ 查询能力弱（需要下载）
- ❌ 无法关联查询
- ❌ 不适合频繁访问

#### 方案 C：Redis + PostgreSQL 双写

**优势**：
- Redis 提供快速访问
- PostgreSQL 提供持久化保证

**局限**：
- ❌ 架构复杂（需要保证一致性）
- ❌ 成本高（两个存储）
- ❌ Checkpoint 访问频率低，不需要 Redis 的性能

### 为什么选择 PostgreSQL

1. **持久化可靠**：事务保证，数据不丢失
2. **查询能力强**：支持复杂查询和关联查询
3. **租户隔离**：RLS 提供数据库层强制隔离
4. **审计友好**：支持时间范围查询和关联查询
5. **性价比高**：Checkpoint 访问频率低，不需要 Redis 的性能
6. **LangGraph 支持**：官方提供 PostgresSaver

## 后果

### 正面影响

1. **可靠性保证**：Checkpoint 不会因为 Redis 崩溃而丢失
2. **查询能力强**：支持复杂查询和审计
3. **租户隔离**：RLS 提供数据库层强制隔离
4. **成本优化**：不需要为 Checkpoint 单独维护 Redis

### 负面影响

1. **延迟略高**：10ms vs Redis 的 <1ms（但可接受）
2. **数据库压力**：增加 PostgreSQL 的写入负载（但 Checkpoint 频率低）

### 风险缓解

1. **性能优化**：
   ```python
   # 创建索引
   CREATE INDEX idx_checkpoints_incident_id ON checkpoints(incident_id);
   
   # 使用连接池
   engine = create_async_engine(
       DATABASE_URL,
       pool_size=20,
       max_overflow=10
   )
   ```

2. **监控告警**：
   ```python
   # Prometheus 指标
   checkpoint_save_duration = Histogram(
       "checkpoint_save_duration_seconds",
       "Time to save a checkpoint"
   )
   
   checkpoint_save_failures = Counter(
       "checkpoint_save_failures_total",
       "Number of failed checkpoint saves"
   )
   ```

3. **定期清理**：
   ```python
   # 定时任务：清理 30 天前的已完成 Checkpoint
   async def cleanup_old_checkpoints():
       await db.execute(
           delete(Checkpoint).where(
               Checkpoint.completed == True,
               Checkpoint.created_at < now() - timedelta(days=30)
           )
       )
   ```

4. **备份策略**：
   ```bash
   # PostgreSQL 定期备份
   pg_dump oncall_db > backup_$(date +%Y%m%d).sql
   ```

### 实施检查清单

- [ ] 创建 checkpoints 表
- [ ] 创建索引（tenant_id、incident_id、completed、created_at）
- [ ] 启用 RLS
- [ ] 集成 LangGraph PostgresSaver
- [ ] 编写 Checkpoint 保存和恢复测试
- [ ] 配置监控指标（保存时长、失败次数）
- [ ] 实现定期清理任务
- [ ] 配置数据库备份策略

## 相关决策

- ADR-0001: 使用 LangGraph StateGraph 替代 Plan-Execute 模式
- ADR-0003: 使用 PostgreSQL RLS 作为数据隔离的最后防线
- ADR-0004: Session 三层存储（Redis + PostgreSQL + S3）

## 参考资料

- [LangGraph Persistence](https://langchain-ai.github.io/langgraph/concepts/persistence/)
- [LangGraph PostgresSaver](https://langchain-ai.github.io/langgraph/reference/checkpoints/#langgraph.checkpoint.postgres.PostgresSaver)
- [PostgreSQL JSONB](https://www.postgresql.org/docs/current/datatype-json.html)
- ONCALL_FINAL.md 第六章：Checkpoint 持久化策略

## 决策日期

2026-03-22

## 决策者

项目团队
