# ADR-0001: 使用 LangGraph StateGraph 替代 Plan-Execute 模式

## 状态
已接受 (Accepted)

## 上下文

我们需要为多租户 OnCall AIOps Agent 选择执行引擎架构。现有原型使用 Plan-Execute-Replan 模式，但在评估企业级需求和业界最佳实践后，需要重新审视这个选择。

### 现有实现
- 已有 Plan-Execute-Replan 模式的原型实现
- 使用 LangGraph 构建工作流
- 集成了 MCP 工具和 RAG pipeline
- 使用 MemorySaver 作为 Checkpoint

### 企业级 OnCall 系统的核心需求
1. **可审计性**：每个操作必须可追溯，合规要求（SOC2、ISO27001）需要完整的审计链路
2. **可恢复性**：服务重启、网络中断后能否精确恢复，审批可能等待几小时
3. **人机协作**：高危操作必须人工审批，审批流程可能跨越多个系统
4. **可观测性**：SRE 需要实时看到"事故处理进展"，管理层需要看到处理时长和审批等待时间
5. **扩展性**：未来可能添加新的处理阶段，不同类型事故可能有不同流程

### 业界参考
- **PagerDuty**：使用显式状态机（Triggered → Acknowledged → Investigating → Resolved）
- **Rootly**：使用显式状态机（Declared → Investigating → Identified → Monitoring → Resolved）
- **Temporal Workflow**：使用显式状态机（Activities + Signals），不使用 Plan-Execute
- **Kubernetes Operator**：使用显式状态机（通过 Status 字段）

业界共识：企业级事件驱动系统倾向于使用显式状态机而非动态规划。

## 决策

采用 LangGraph StateGraph 实现六状态事故处理流程：

```
TRIGGERED → ANALYZING → AWAITING_APPROVAL → EXECUTING → VERIFYING → RESOLVED
                              ↓ 拒绝/超时              ↓ 失败
                          ESCALATED                ESCALATED
```

通过并行开发和 A/B 测试的方式，逐步从 Plan-Execute 迁移到 StateGraph。

## 理由

### StateGraph 的优势

#### 1. 可审计性
**StateGraph**：
```python
# 审计日志记录显式状态
{
  "incident_id": "inc-123",
  "state": "AWAITING_APPROVAL",  # 显式状态
  "entered_at": "2024-01-15T10:30:00Z",
  "previous_state": "ANALYZING"
}
```
- ✅ 显式的业务状态，直接可查询
- ✅ 可以直接查询 `SELECT COUNT(*) WHERE state = 'AWAITING_APPROVAL'`
- ✅ 符合合规审计要求

**Plan-Execute**：
```python
# 审计日志记录步骤列表
{
  "plan": ["步骤1", "步骤2", "步骤3"],
  "past_steps": [("步骤1", "结果1")],
  "current_step": 1
}
```
- ❌ 没有显式的业务状态
- ❌ 难以回答"有多少事故在等待审批？"
- ❌ 需要遍历所有 plan 判断

#### 2. 人机协作（审批流程）
**StateGraph**：
```python
# 审批是显式的状态节点
graph.add_node("wait_for_approval", wait_for_approval_node)
graph.compile(interrupt_before=["wait_for_approval"])
```
- ✅ 审批是"一等公民"，有独立的节点
- ✅ LangGraph 原生支持 interrupt + Checkpoint
- ✅ 审批状态显式可查询

**Plan-Execute**：
```python
# 审批是步骤内的逻辑
async def executor(state):
    if requires_approval(result):
        # 需要自己实现暂停和恢复机制
        pass
```
- ❌ 审批是"步骤内的逻辑"，不是流程的一部分
- ❌ 暂停和恢复需要自己实现
- ❌ 审批状态不显式

#### 3. 可恢复性
**StateGraph**：
```python
# Checkpoint 保存当前节点
{
  "current_node": "wait_for_approval",
  "state": {"incident_id": "inc-123", "analysis_result": {...}}
}
```
- ✅ 恢复点明确（从特定节点继续）
- ✅ 图结构静态，恢复逻辑简单
- ✅ 状态数据完整保存

**Plan-Execute**：
```python
# Checkpoint 保存动态 plan
{
  "plan": ["步骤3", "步骤4"],
  "past_steps": [("步骤1", "结果1")]
}
```
- ⚠️ Plan 是动态生成的，可能不稳定
- ⚠️ 恢复点不明确（在哪个步骤的哪个位置？）
- ⚠️ Replanner 可能修改 plan，恢复逻辑复杂

#### 4. 可观测性
**StateGraph**：
```python
# Prometheus 指标
incident_by_state{tenant_id="t1", state="AWAITING_APPROVAL"} = 5
incident_duration_seconds{tenant_id="t1", state="ANALYZING"} = 120
```
- ✅ 直接查询每个状态的事故数量
- ✅ 可以计算每个状态的平均时长
- ✅ 指标语义清晰，符合业务语言

**Plan-Execute**：
```python
# Prometheus 指标
incident_step_count{tenant_id="t1"}  # 当前第几步？
```
- ❌ 无法直接查询"有多少事故在审批阶段"
- ❌ 需要遍历 Checkpoint 解析 plan
- ❌ 指标语义不清晰

#### 5. 扩展性
**StateGraph**：
```python
# 添加新阶段：添加新节点
graph.add_node("pre_check", pre_check_node)
graph.add_edge("triggered", "pre_check")
```
- ✅ 图结构清晰，一目了然
- ✅ 每个节点独立测试
- ✅ 易于版本演进

**Plan-Execute**：
```python
# 添加新阶段：修改 planner 或 executor
plan = ["新步骤", "步骤1", "步骤2"]
```
- ❌ 逻辑分散在 planner 和 executor
- ❌ 难以保证一致性
- ❌ 测试复杂

### 考虑的替代方案

#### 方案 A：保留 Plan-Execute，叠加多租户
- 在现有 Plan-Execute 基础上添加 tenant_id
- 在 executor 中判断是否需要审批
- 替换 MemorySaver 为 PostgreSQL Checkpoint

**优势**：
- 改造工作量小
- 风险低，现有逻辑已验证

**局限**：
- 不符合企业级可审计性要求（状态不显式）
- 审批流程不是一等公民
- 可观测性差（指标语义不清晰）
- 不符合业界最佳实践

#### 方案 B：使用 Temporal Workflow
- 使用 Temporal 作为工作流引擎
- 实现显式状态机

**优势**：
- 功能强大，久经考验
- 原生支持长时间运行和审批

**局限**：
- 需要独立部署 Go 服务，增加运维复杂度
- 与 LangGraph 生态不兼容
- 学习曲线陡峭

#### 方案 C：自己实现状态机
- 不使用 LangGraph，自己实现状态机引擎

**局限**：
- 重复造轮子
- 需要自己实现 Checkpoint、恢复、追踪等机制
- 维护成本高

### 为什么选择 StateGraph

1. **符合企业级需求**：可审计、可恢复、可观测
2. **符合业界最佳实践**：PagerDuty、Rootly、Temporal 都用显式状态机
3. **LangGraph 原生支持**：interrupt、Checkpoint、追踪
4. **技术债务考虑**：现有 Plan-Execute 是原型，现在重构比未来重构成本低
5. **生态兼容**：与 LangChain、LangSmith 无缝集成

## 后果

### 正面影响

1. **清晰的审计链路**：每个状态转换都有明确记录，满足合规要求
2. **可靠的恢复机制**：Checkpoint 恢复点明确，长时间运行的审批流程可靠
3. **有意义的监控指标**：可以直接查询每个状态的事故数量和处理时长
4. **易于扩展**：添加新的处理阶段只需添加新节点
5. **符合业界标准**：与 PagerDuty、Rootly 等成熟产品的设计一致

### 负面影响

1. **需要重构现有代码**：从 Plan-Execute 迁移到 StateGraph 需要重写执行引擎
2. **短期开发成本**：并行开发和 A/B 测试需要额外时间
3. **学习曲线**：团队需要学习 StateGraph 的概念（但 LangGraph 文档完善）

### 风险缓解

1. **并行开发**：保留现有 Plan-Execute，新建 `aiops_v2/` 目录开发 StateGraph
2. **A/B 测试**：10% 流量走 StateGraph，90% 流量走 Plan-Execute，对比指标
3. **复用现有逻辑**：业务逻辑（MCP 调用、RAG 检索）保持不变，只是换个编排方式
4. **逐步迁移**：StateGraph 稳定后，逐步提高流量比例，最终下线 Plan-Execute
5. **回滚机制**：如果 StateGraph 出现问题，可以快速切回 Plan-Execute

### 实施路径

```
阶段 1：并行开发（2-3 周）
app/agent/
├── aiops/              # 现有 Plan-Execute（保留）
└── aiops_v2/           # 新的 StateGraph（并行开发）

阶段 2：A/B 测试（1-2 周）
- 10% 流量走 StateGraph
- 对比指标：成功率、处理时长、错误率

阶段 3：逐步迁移（1-2 周）
- StateGraph 稳定后，逐步提高流量比例
- 最终下线 Plan-Execute

阶段 4：清理代码（1 周）
- 删除 aiops/ 目录
- 将 aiops_v2/ 重命名为 aiops/
```

## 相关决策

- ADR-0006: 使用 PostgreSQL 存储 Checkpoint（而非 Redis）
- ADR-0007: 自实现 YAML Workflow Engine（而非使用 Temporal）

## 参考资料

- [LangGraph 官方文档](https://langchain-ai.github.io/langgraph/)
- [LangGraph StateGraph 概念](https://langchain-ai.github.io/langgraph/concepts/low_level/)
- [LangGraph Checkpoint 机制](https://langchain-ai.github.io/langgraph/concepts/persistence/)
- [PagerDuty Incident Workflow](https://support.pagerduty.com/docs/incidents)
- [Rootly Incident Management](https://rootly.com/blog/incident-management-workflow)
- [Temporal Workflow Patterns](https://docs.temporal.io/workflows)
- ONCALL_FINAL.md 第六章：事故状态机

## 决策日期
2026-03-22

## 决策者
项目团队
