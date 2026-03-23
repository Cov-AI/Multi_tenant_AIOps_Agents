# ADR-0003: 使用 PostgreSQL RLS 作为数据隔离的最后防线

## 状态
已接受 (Accepted)

## 上下文

多租户 SaaS 系统的核心安全需求是确保租户数据完全隔离。应用层的过滤逻辑可能因为代码 bug、SQL 注入、权限配置错误等原因被绕过，导致数据泄露。

### 常见的租户隔离方案

1. **应用层过滤**：在 ORM 查询中添加 `WHERE tenant_id = ?`
2. **数据库视图**：为每个租户创建视图
3. **Row-Level Security (RLS)**：数据库层强制过滤
4. **独立数据库**：每个租户一个数据库

### 安全事件案例

- **Slack (2022)**：应用层过滤 bug 导致跨租户数据泄露
- **GitHub (2020)**：权限配置错误导致私有仓库泄露
- **Salesforce (2019)**：SQL 注入绕过应用层过滤

**教训**：应用层过滤不可靠，需要数据库层的强制隔离。

## 决策

**在所有核心业务表上启用 PostgreSQL Row-Level Security (RLS)，作为租户隔离的最后防线。**

具体实施：
1. 所有核心表（sessions、incidents、approvals、token_usage、audit_logs）启用 RLS
2. 创建 RLS 策略：`USING (tenant_id = current_setting('app.tenant_id')::uuid)`
3. JWT 中间件解析 tenant_id，注入到数据库连接上下文
4. 应用层继续添加 `WHERE tenant_id = ?`（性能优化 + 防御深度）

## 理由

### RLS 的优势

#### 1. 数据库层强制隔离
```sql
-- 即使应用层漏写 WHERE 条件，数据库也会自动过滤
SELECT * FROM incidents;  -- 应用层忘记加 WHERE tenant_id = ?

-- PostgreSQL 自动改写为：
SELECT * FROM incidents WHERE tenant_id = current_setting('app.tenant_id')::uuid;
```
- ✅ 防止应用层 bug 导致的数据泄露
- ✅ 防止 SQL 注入绕过应用层过滤
- ✅ 防止权限配置错误

#### 2. 防御深度（Defense in Depth）
```
第一层：应用层过滤（WHERE tenant_id = ?）
第二层：ORM 自动过滤（SQLAlchemy filter）
第三层：数据库 RLS（强制过滤）
```
- ✅ 多层防护，降低单点失败风险
- ✅ 即使前两层失效，第三层仍然有效

#### 3. 审计和合规
- ✅ 满足 SOC2、ISO27001 等合规要求
- ✅ 数据库层的隔离可以通过审计
- ✅ 证明"技术上不可能"跨租户访问

#### 4. 简化应用逻辑
```python
# 应用层不需要在每个查询都加 tenant_id
# 只需在连接建立时设置上下文
await db.execute("SET app.tenant_id = %s", [tenant_id])

# 后续所有查询自动过滤
incidents = await db.query(Incident).all()  # 自动只返回当前租户的数据
```
- ✅ 减少应用层代码重复
- ✅ 降低遗漏过滤的风险

### RLS 的实现

#### 1. 启用 RLS
```sql
-- 为每张核心表启用 RLS
ALTER TABLE incidents ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE token_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
```

#### 2. 创建 RLS 策略
```sql
-- 创建租户隔离策略
CREATE POLICY tenant_isolation ON incidents
    USING (tenant_id = current_setting('app.tenant_id')::uuid);

CREATE POLICY tenant_isolation ON sessions
    USING (tenant_id = current_setting('app.tenant_id')::uuid);

-- 其他表类似
```

#### 3. 应用层注入 tenant_id
```python
# FastAPI 中间件
@app.middleware("http")
async def inject_tenant_context(request: Request, call_next):
    # 解析 JWT，获取 tenant_id
    tenant_id = parse_jwt(request.headers.get("Authorization"))
    
    # 注入到数据库连接上下文
    async with db.begin():
        await db.execute(
            text("SET LOCAL app.tenant_id = :tenant_id"),
            {"tenant_id": str(tenant_id)}
        )
        
        response = await call_next(request)
    
    return response
```

#### 4. 连接池注意事项
```python
# 连接复用时必须清除上下文
async def reset_connection(conn):
    await conn.execute("RESET app.tenant_id")

# 在连接池配置中注册清理函数
engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    # 连接归还到池时清理上下文
    poolclass=AsyncAdaptedQueuePool,
    pool_reset_on_return="rollback"  # 回滚会自动清除 SET LOCAL
)
```

### 考虑的替代方案

#### 方案 A：仅应用层过滤
```python
# 在每个查询都加 WHERE tenant_id = ?
incidents = await db.query(Incident).filter(
    Incident.tenant_id == tenant_id
).all()
```

**优势**：
- 实现简单
- 性能好（可以使用索引）

**局限**：
- ❌ 容易遗漏过滤条件
- ❌ 无法防止 SQL 注入
- ❌ 无法防止权限配置错误
- ❌ 不满足合规要求

#### 方案 B：数据库视图
```sql
-- 为每个租户创建视图
CREATE VIEW tenant_123_incidents AS
SELECT * FROM incidents WHERE tenant_id = '123';
```

**优势**：
- 数据库层隔离

**局限**：
- ❌ 需要为每个租户创建视图（管理成本高）
- ❌ 租户数量增加时视图数量爆炸
- ❌ 不如 RLS 灵活

#### 方案 C：独立数据库
```
tenant_123_db
tenant_456_db
tenant_789_db
```

**优势**：
- 隔离强度最高
- 可以独立备份和恢复

**局限**：
- ❌ 管理成本极高
- ❌ 资源浪费严重
- ❌ 跨租户查询困难（如平台级统计）
- ❌ 只适合极高合规要求的场景

### 为什么选择 RLS

1. **安全性**：数据库层强制隔离，防止应用层 bug
2. **合规性**：满足 SOC2、ISO27001 要求
3. **可维护性**：不需要为每个租户创建视图或数据库
4. **性能**：RLS 策略可以使用索引，性能损失小
5. **灵活性**：支持复杂的隔离策略（如基于角色的访问控制）

## 后果

### 正面影响

1. **安全保障**：即使应用层有 bug，数据库层也能防止数据泄露
2. **合规认证**：满足 SOC2、ISO27001 等合规要求
3. **简化代码**：应用层不需要在每个查询都加 tenant_id 过滤
4. **防御深度**：多层防护，降低单点失败风险

### 负面影响

1. **性能开销**：RLS 策略会增加查询开销（但可以通过索引优化）
2. **调试复杂**：RLS 策略可能导致"查询返回空结果"，需要检查上下文设置
3. **连接池管理**：需要正确清除连接上下文，避免上下文泄露

### 风险缓解

1. **性能优化**：
   - 在 tenant_id 列上创建索引
   - 应用层继续添加 `WHERE tenant_id = ?`（帮助查询优化器）
   - 监控查询性能，发现慢查询

2. **调试工具**：
   ```sql
   -- 查看当前上下文
   SELECT current_setting('app.tenant_id', true);
   
   -- 临时禁用 RLS（仅用于调试，生产环境禁止）
   SET SESSION AUTHORIZATION postgres;
   ALTER TABLE incidents DISABLE ROW LEVEL SECURITY;
   ```

3. **连接池测试**：
   ```python
   # 测试连接复用时上下文是否正确清除
   async def test_connection_isolation():
       # 连接 1：设置 tenant_id = 'A'
       async with db.begin():
           await db.execute("SET LOCAL app.tenant_id = 'A'")
           result_a = await db.query(Incident).all()
       
       # 连接 2：设置 tenant_id = 'B'（可能复用连接 1）
       async with db.begin():
           await db.execute("SET LOCAL app.tenant_id = 'B'")
           result_b = await db.query(Incident).all()
       
       # 验证结果不重叠
       assert not set(result_a) & set(result_b)
   ```

4. **监控告警**：
   - 监控 RLS 策略是否生效
   - 监控是否有查询绕过 RLS（通过审计日志）
   - 定期进行渗透测试

### 实施检查清单

- [ ] 所有核心表启用 RLS
- [ ] 创建 tenant_isolation 策略
- [ ] JWT 中间件注入 tenant_id
- [ ] 连接池正确清除上下文
- [ ] 在 tenant_id 列上创建索引
- [ ] 编写 RLS 测试用例
- [ ] 文档化 RLS 策略
- [ ] 培训团队成员

## 相关决策

- ADR-0002: Milvus 使用 Partition 进行租户隔离
- ADR-0004: Session 三层存储（Redis + PostgreSQL + S3）

## 参考资料

- [PostgreSQL Row Security Policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [Multi-tenant Data Isolation with PostgreSQL RLS](https://aws.amazon.com/blogs/database/multi-tenant-data-isolation-with-postgresql-row-level-security/)
- [Citus Multi-tenant Database Design](https://docs.citusdata.com/en/stable/sharding/multi_tenant.html)
- ONCALL_FINAL.md 第四章：多租户设计 - 数据隔离三层

## 决策日期
2026-03-22

## 决策者
项目团队
