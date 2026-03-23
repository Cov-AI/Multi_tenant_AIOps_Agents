# Architecture Decision Records (ADR)

本目录包含多租户 OnCall Agent 平台的所有架构决策记录。

## 什么是 ADR？

Architecture Decision Record (ADR) 是一种记录重要架构决策的文档格式。每个 ADR 描述：

- **上下文**：为什么需要做这个决策
- **决策**：我们选择了什么方案
- **理由**：为什么选择这个方案（对比其他方案）
- **后果**：这个决策的正面和负面影响

## ADR 列表

### 核心架构

- [ADR-0001: 使用 LangGraph StateGraph 替代 Plan-Execute 模式](./0001-use-stategraph-over-plan-execute.md)
  - **状态**: 已接受
  - **关键点**: 企业级可审计性、可恢复性、可观测性
  - **影响**: 需要重构执行引擎，但符合业界最佳实践

- [ADR-0008: 混合部署架构（云端控制面 + 用户内网 MCP Server）](./0008-hybrid-deployment-architecture.md)
  - **状态**: 已接受
  - **关键点**: 凭证不离开内网，满足合规要求
  - **影响**: 用户需要部署轻量级 MCP Server

### 数据隔离

- [ADR-0002: Milvus 使用 Partition 而非 Collection 进行租户隔离（MVP 阶段）](./0002-milvus-partition-over-collection.md)
  - **状态**: 已接受
  - **关键点**: MVP 阶段使用 Partition，预留迁移到 Collection 的能力
  - **影响**: 支持 10-200 家企业客户，大客户可迁移到独立 Collection

- [ADR-0003: 使用 PostgreSQL RLS 作为数据隔离的最后防线](./0003-postgresql-rls-for-tenant-isolation.md)
  - **状态**: 已接受
  - **关键点**: 数据库层强制隔离，防御深度
  - **影响**: 即使应用层有 bug，数据库层也能防止数据泄露

### 存储策略

- [ADR-0004: Session 三层存储（Redis + PostgreSQL + S3）](./0004-session-three-layer-storage.md)
  - **状态**: 已接受
  - **关键点**: 热数据用 Redis，元数据用 PostgreSQL，冷数据用 S3
  - **影响**: 性能优化 + 成本优化，冷数据存储成本降低 99%

- [ADR-0006: 使用 PostgreSQL 存储 Checkpoint（而非 Redis）](./0006-postgresql-checkpoint-storage.md)
  - **状态**: 已接受
  - **关键点**: 强持久化保证，支持复杂查询
  - **影响**: Checkpoint 不会因为 Redis 崩溃而丢失

### 上下文管理

- [ADR-0005: 四层上下文 Compaction vs 固定截断](./0005-four-layer-compaction-vs-fixed-truncation.md)
  - **状态**: 已接受
  - **关键点**: 减少 70% token 消耗，保留关键信息
  - **影响**: 降低 LLM API 成本，提升长对话质量

### 工作流引擎

- [ADR-0007: 自实现 YAML Workflow Engine（而非使用 Temporal）](./0007-self-implement-yaml-workflow-engine.md)
  - **状态**: 已接受
  - **关键点**: 架构简单，与 LangGraph 无缝集成
  - **影响**: 不需要独立部署 Temporal Server，但功能有限

## ADR 状态

- **已提议 (Proposed)**: 正在讨论中
- **已接受 (Accepted)**: 已决定采用
- **已废弃 (Deprecated)**: 已被新的 ADR 替代
- **已拒绝 (Rejected)**: 决定不采用

## 如何使用 ADR

### 创建新的 ADR

1. 复制 `template.md` 到新文件（如 `0009-new-decision.md`）
2. 填写上下文、决策、理由、后果
3. 提交 Pull Request 进行讨论
4. 团队达成共识后，更新状态为"已接受"

### 更新现有 ADR

- 如果决策发生变化，创建新的 ADR 并将旧 ADR 标记为"已废弃"
- 在新 ADR 中引用旧 ADR，说明为什么需要改变

### 引用 ADR

在代码、文档、PR 中引用 ADR：

```python
# 实现基于 ADR-0001 的 StateGraph 架构
graph = StateGraph(...)
```

```markdown
根据 [ADR-0003](./adr/0003-postgresql-rls-for-tenant-isolation.md)，
我们使用 PostgreSQL RLS 作为数据隔离的最后防线。
```

## 决策原则

在做架构决策时，我们遵循以下原则：

1. **安全第一**：优先考虑安全性和合规性
2. **务实选择**：选择适合当前阶段的方案，避免过度设计
3. **业界实践**：参考成熟产品的设计（PagerDuty、Rootly、Temporal）
4. **可演进性**：预留演进路径，支持未来扩展
5. **成本意识**：在满足需求的前提下，优化成本

## 相关资源

- [需求文档](../requirements.md)
- [设计文档](../design.md)
- [任务列表](../tasks.md)
- [ONCALL_FINAL.md](../../../ONCALL_FINAL.md)

## 贡献指南

欢迎团队成员提出新的 ADR 或对现有 ADR 提出改进建议。请遵循以下流程：

1. 创建新的 ADR 文件
2. 提交 Pull Request
3. 在团队会议中讨论
4. 达成共识后合并

## 联系方式

如有疑问，请联系项目团队。
