# ADR-0002: Milvus 使用 Partition 而非 Collection 进行租户隔离（MVP 阶段）

## 状态
已接受 (Accepted)

## 上下文

多租户 OnCall 平台需要在 Milvus 向量数据库中隔离不同租户的 runbook 数据。OnCall 场景的数据特别敏感（内部架构、故障复盘、数据库表结构、恢复脚本），串租户不只是"搜错了"，是直接泄露企业内部运维知识。

### Milvus 四层隔离强度

根据 Milvus 官方文档，隔离强度从高到低：

```
Database > Collection > Partition > Partition Key
```

### 租户规模预估

- MVP 阶段：10-50 家企业客户
- 成长期：50-200 家企业客户
- 成熟期：200+ 家企业客户

### 技术约束

- 单个 Collection 最多支持 1024 个 Partition
- Partition 是"同一大池子里的分仓"，不是物理边界
- Collection 管理成本高（独立建索引、独立删库、独立配置）

## 决策

**MVP 阶段使用 Partition 隔离，预留迁移到 Collection 的能力。**

具体策略：
1. 每个租户创建独立 Partition（命名格式：`tenant_{tenant_id}`）
2. 查询时同时指定 `partition_names` 和 `metadata filter`（双重防护）
3. 返回结果后验证 `tenant_id` 一致性（三重防护）
4. 为大客户或高敏感客户预留迁移到独立 Collection 的能力

## 理由

### Partition 的优势（MVP 阶段）

1. **管理成本低**
   - 所有租户共享同一个 Collection schema
   - 统一索引配置，维护简单
   - 创建和删除 Partition 操作轻量

2. **快速上线**
   - 不需要为每个租户单独建索引
   - 不需要管理大量 Collection
   - 适合快速验证产品

3. **资源利用率高**
   - 共享索引结构，节省内存
   - 小租户不会浪费独立 Collection 的资源

4. **扩展性足够**
   - 1024 个 Partition 上限足够支持 MVP 和成长期
   - 几十到一两百家企业规模完全够用

### Partition 的真实局限

1. **隔离强度低于 Collection**
   - 是"同一大池子里的分仓"，不是物理边界
   - 安全不能只靠"传 partition_names"这种软约束

2. **规模上限**
   - 单 Collection 最多 1024 个 Partition
   - 租户规模增长会撞上限

3. **性能考虑**
   - 大量 Partition 可能影响查询性能
   - 需要监控和优化

### 应用层强制过滤（Invariant）

**无论使用哪种隔离方式，应用层 tenant_id 强制过滤是不变的原则**：

```python
# 三重防护
# 1. Partition 隔离（物理层）
results = await milvus.search(
    collection_name="runbooks",
    partition_names=[f"tenant_{tenant_id}"],  # 第一重
    
    # 2. Metadata filter（逻辑层）
    filter=f"tenant_id == '{tenant_id}'",      # 第二重
    
    data=[embedding],
    limit=top_k
)

# 3. 返回结果验证（应用层）
for result in results:
    assert result["tenant_id"] == tenant_id, "Tenant isolation violated!"  # 第三重
```

### 演进路径

```
阶段 1：MVP（0-50 租户）
- 所有租户使用 Partition 隔离
- 监控 Partition 数量和查询性能

阶段 2：成长期（50-200 租户）
- 普通客户继续使用 Partition
- 大客户（数据量大、查询频繁）迁移到独立 Collection

阶段 3：成熟期（200+ 租户）
- 新租户默认使用独立 Collection
- 小租户可选择共享 Collection + Partition

阶段 4：高合规场景
- 金融、医疗等高敏感行业使用独立 Database
```

### 考虑的替代方案

#### 方案 A：每个租户一个 Collection
**优势**：
- 隔离强度最高（物理隔离）
- 独立建索引、独立删库、独立合规审计

**局限**：
- 管理成本高（需要管理大量 Collection）
- 小租户浪费资源（每个 Collection 都有固定开销）
- 创建和删除 Collection 操作重
- MVP 阶段过度设计

#### 方案 B：使用 Partition Key
**优势**：
- Milvus 2.2+ 支持
- 自动分区，管理更简单

**局限**：
- 隔离强度最低
- 不支持独立删除某个租户的数据
- 查询性能可能不如显式 Partition

#### 方案 C：每个租户一个 Database
**优势**：
- 隔离强度最高
- 完全独立的命名空间

**局限**：
- 管理成本极高
- 资源浪费严重
- 只适合极高合规要求的场景

### 为什么选择 Partition（MVP）+ 演进路径

1. **务实选择**：MVP 阶段租户数量可控，Partition 足够
2. **成本优化**：避免过度设计，节省资源
3. **灵活演进**：预留迁移路径，根据实际需求调整
4. **安全保障**：三重防护确保隔离，不只依赖 Partition

## 后果

### 正面影响

1. **快速上线**：不需要复杂的 Collection 管理逻辑
2. **成本可控**：共享索引，节省资源
3. **维护简单**：统一 schema 和索引配置
4. **扩展性足够**：支持 MVP 和成长期的租户规模

### 负面影响

1. **隔离强度有限**：不如独立 Collection
2. **规模上限**：1024 个 Partition 上限
3. **性能风险**：大量 Partition 可能影响查询性能

### 风险缓解

1. **三重防护**：Partition + metadata filter + 结果验证
2. **监控告警**：监控 Partition 数量和查询性能
3. **演进路径**：提前规划迁移到 Collection 的方案
4. **大客户优先**：数据量大或高敏感客户优先迁移到独立 Collection
5. **定期审计**：定期检查租户隔离是否有漏洞

### 迁移策略

当需要将租户从 Partition 迁移到独立 Collection 时：

```python
# 1. 创建新的 Collection
new_collection = f"runbooks_tenant_{tenant_id}"
milvus.create_collection(new_collection, schema)

# 2. 复制数据
data = milvus.query(
    collection_name="runbooks",
    partition_names=[f"tenant_{tenant_id}"],
    filter=f"tenant_id == '{tenant_id}'"
)
milvus.insert(new_collection, data)

# 3. 更新租户配置
tenant.milvus_collection = new_collection
tenant.isolation_level = "collection"

# 4. 验证数据完整性
assert milvus.count(new_collection) == len(data)

# 5. 删除旧 Partition
milvus.drop_partition("runbooks", f"tenant_{tenant_id}")
```

## 相关决策

- ADR-0003: 使用 PostgreSQL RLS 作为数据隔离的最后防线
- ADR-0009: Runbook 摄入时的租户隔离策略

## 参考资料

- [Milvus Multi-tenancy 官方文档](https://milvus.io/docs/multi_tenancy.md)
- [Milvus Partition 管理](https://milvus.io/docs/manage-partitions.md)
- [Milvus Collection 管理](https://milvus.io/docs/manage-collections.md)
- ONCALL_FINAL.md 第八章：RAG Pipeline - Milvus 多租户隔离策略

## 决策日期
2026-03-22

## 决策者
项目团队
