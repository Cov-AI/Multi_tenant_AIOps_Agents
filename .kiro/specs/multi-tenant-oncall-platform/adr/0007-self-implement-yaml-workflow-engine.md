# ADR-0007: 自实现 YAML Workflow Engine（而非使用 Temporal）

## 状态

已接受 (Accepted)

## 上下文

OnCall 平台需要支持 YAML 格式的 workflow 定义，允许 SRE 用声明式语法定义操作步骤，而不需要修改 Python 代码。

### Workflow 需求

1. **声明式定义**：使用 YAML 定义步骤序列
2. **审批门**：支持 approval 步骤，暂停执行等待人工确认
3. **断点恢复**：支持从断点恢复，不重复执行已完成步骤
4. **工具调用**：支持调用 MCP 工具和 LLM
5. **变量传递**：支持步骤间传递变量

### YAML Workflow 示例

```yaml
name: service_restart
description: 重启服务并验证恢复
steps:
  - name: fetch_logs
    type: mcp_call
    tool: loki_query
    params:
      query: '{service="{{service_name}}"} |= "error"'
      time_range: 30m
  
  - name: analyze
    type: llm_call
    prompt: |
      分析以下日志，判断是否需要重启服务：
      {{steps.fetch_logs.output}}
  
  - name: confirm_restart
    type: approval
    message: "建议重启 {{service_name}}，原因：{{steps.analyze.output}}"
  
  - name: kubectl_restart
    type: mcp_call
    tool: kubectl
    params:
      action: restart
      deployment: "{{service_name}}"
  
  - name: health_check
    type: mcp_call
    tool: health_check
    params:
      service: "{{service_name}}"
      wait_seconds: 60
```

### 技术选型

#### 选项 1：使用 Temporal Workflow

**Temporal** 是一个成熟的工作流引擎，支持：
- 长时间运行的 workflow
- 审批流程（通过 Signal）
- 断点恢复
- 强大的可观测性

#### 选项 2：自实现 YAML Workflow Engine

基于 LangGraph 和 Python，实现轻量级的 YAML workflow 解析和执行引擎。

## 决策

**自实现 YAML Workflow Engine，而非使用 Temporal。**

理由：

1. **简化架构**：避免引入独立的 Go 服务
2. **与 LangGraph 集成**：复用 LangGraph 的 Checkpoint 和 interrupt 机制
3. **需求简单**：只需要顺序执行 + 审批门，不需要 Temporal 的复杂功能
4. **学习曲线**：团队已熟悉 Python 和 LangGraph，不需要学习 Temporal

## 理由

### 自实现的优势

#### 1. 架构简单

**Temporal 的复杂性**：
```
┌─────────────────────────────────────┐
│  Temporal Server (Go)               │
│  - Frontend Service                 │
│  - History Service                  │
│  - Matching Service                 │
│  - Worker Service                   │
└─────────────────────────────────────┘
         ↓
┌─────────────────────────────────────┐
│  Temporal Worker (Python)           │
│  - Workflow 定义                    │
│  - Activity 定义                    │
└─────────────────────────────────────┘
```
- ❌ 需要独立部署 Temporal Server（Go 服务）
- ❌ 需要维护 Temporal 数据库（PostgreSQL 或 Cassandra）
- ❌ 需要学习 Temporal 的概念（Workflow、Activity、Signal、Query）
- ❌ 增加运维复杂度

**自实现的简单性**：
```
┌─────────────────────────────────────┐
│  Agent Worker (Python)              │
│  - YAML Parser                      │
│  - Workflow Executor                │
│  - LangGraph Integration            │
└─────────────────────────────────────┘
```
- ✅ 不需要独立服务
- ✅ 复用现有的 PostgreSQL（存储 Checkpoint）
- ✅ 复用 LangGraph 的 interrupt 机制
- ✅ 架构简单，易于维护

#### 2. 与 LangGraph 无缝集成

**Temporal 的集成问题**：
```python
# Temporal Workflow
@workflow.defn
class ServiceRestartWorkflow:
    @workflow.run
    async def run(self, service_name: str):
        # 步骤 1：查询日志
        logs = await workflow.execute_activity(
            fetch_logs,
            args=[service_name],
            start_to_close_timeout=timedelta(minutes=5)
        )
        
        # 步骤 2：等待审批
        await workflow.wait_condition(lambda: self.approved)
        
        # 步骤 3：重启服务
        await workflow.execute_activity(
            kubectl_restart,
            args=[service_name]
        )
```
- ❌ 需要将 LangGraph 图转换为 Temporal Workflow
- ❌ 需要将 MCP 工具调用封装为 Temporal Activity
- ❌ 两套执行引擎（LangGraph + Temporal），复杂度高

**自实现的集成优势**：
```python
# 自实现 Workflow Engine
async def execute_workflow(workflow: Workflow, context: dict):
    """执行 YAML workflow"""
    for step in workflow.steps:
        if step.type == "approval":
            # 使用 LangGraph interrupt
            raise ApprovalRequired(step.message)
        
        elif step.type == "mcp_call":
            # 直接调用 MCP 工具
            result = await mcp_client.call(step.tool, step.params)
        
        elif step.type == "llm_call":
            # 直接调用 LLM
            result = await llm.invoke(step.prompt)
        
        context[step.name] = result
    
    return context
```
- ✅ 直接使用 LangGraph 的 interrupt 机制
- ✅ 直接调用 MCP 工具和 LLM
- ✅ 单一执行引擎，架构简单

#### 3. 需求简单，不需要 Temporal 的复杂功能

**Temporal 的强大功能**：
- 分布式事务（Saga 模式）
- 子 Workflow
- 并行执行
- 定时器和延迟执行
- 版本管理
- 搜索和查询

**OnCall Workflow 的实际需求**：
- ✅ 顺序执行步骤
- ✅ 审批门（暂停和恢复）
- ✅ 断点恢复
- ❌ 不需要分布式事务
- ❌ 不需要子 Workflow
- ❌ 不需要并行执行（暂时）

**结论**：Temporal 的功能过于强大，我们只需要其中 10% 的功能。

#### 4. 学习曲线

**Temporal 的学习曲线**：
- 需要学习 Temporal 的概念（Workflow、Activity、Signal、Query）
- 需要学习 Temporal 的 Python SDK
- 需要学习 Temporal 的部署和运维
- 需要学习 Temporal 的调试工具

**自实现的学习曲线**：
- 团队已熟悉 Python 和 LangGraph
- YAML 解析使用标准库（PyYAML）
- 执行逻辑简单（顺序执行 + 审批门）

#### 5. 成本考虑

**Temporal 的成本**：
- 需要独立部署 Temporal Server（计算资源）
- 需要维护 Temporal 数据库（存储资源）
- 需要学习和培训（时间成本）

**自实现的成本**：
- 复用现有的 Agent Worker（无额外计算资源）
- 复用现有的 PostgreSQL（无额外存储资源）
- 实现成本低（约 500 行代码）

### 自实现的架构

#### YAML 解析

```python
from pydantic import BaseModel
import yaml

class WorkflowStep(BaseModel):
    name: str
    type: Literal["mcp_call", "llm_call", "approval"]
    tool: str | None = None
    params: dict | None = None
    prompt: str | None = None
    message: str | None = None

class Workflow(BaseModel):
    name: str
    description: str
    steps: list[WorkflowStep]

def parse_workflow(yaml_content: str) -> Workflow:
    """解析 YAML workflow"""
    data = yaml.safe_load(yaml_content)
    return Workflow(**data)
```

#### Workflow 执行

```python
class WorkflowEngine:
    async def execute(
        self,
        workflow: Workflow,
        context: dict,
        resume_token: str | None = None
    ) -> dict:
        """执行 workflow"""
        # 如果有 resume_token，从断点恢复
        if resume_token:
            completed_steps = await self.get_completed_steps(resume_token)
            start_index = len(completed_steps)
        else:
            completed_steps = {}
            start_index = 0
        
        results = completed_steps.copy()
        
        for i, step in enumerate(workflow.steps[start_index:], start=start_index):
            # 审批步骤：生成 resumeToken 并暂停
            if step.type == "approval":
                token = str(uuid.uuid4())
                await self.save_approval(token, workflow, results)
                raise ApprovalRequired(token, step.message)
            
            # MCP 工具调用
            elif step.type == "mcp_call":
                result = await mcp_client.call(step.tool, step.params)
                results[step.name] = result
            
            # LLM 调用
            elif step.type == "llm_call":
                result = await llm.invoke(step.prompt.format(**context, steps=results))
                results[step.name] = result
        
        return results
```

#### 断点恢复

```python
async def resume_workflow(resume_token: str) -> dict:
    """从断点恢复 workflow"""
    # 1. 从 PostgreSQL 读取审批记录
    approval = await db.get_approval(resume_token)
    
    # 2. 解析 workflow
    workflow = parse_workflow(approval.workflow_yaml)
    
    # 3. 恢复上下文
    context = approval.context
    
    # 4. 继续执行（从断点开始）
    results = await workflow_engine.execute(
        workflow,
        context,
        resume_token=resume_token
    )
    
    return results
```

### 考虑的替代方案

#### 方案 A：使用 Temporal

**优势**：
- 功能强大，久经考验
- 原生支持长时间运行和审批
- 强大的可观测性

**局限**：
- ❌ 需要独立部署 Go 服务
- ❌ 架构复杂，运维成本高
- ❌ 学习曲线陡峭
- ❌ 与 LangGraph 集成复杂
- ❌ 功能过于强大（我们只需要 10%）

#### 方案 B：使用 Airflow

**优势**：
- Python 生态，易于集成
- 强大的调度能力

**局限**：
- ❌ 主要用于批处理，不适合实时事故处理
- ❌ 审批流程支持不如 Temporal
- ❌ 需要独立部署 Airflow Server

#### 方案 C：使用 Prefect

**优势**：
- Python 生态，易于集成
- 现代化的 UI

**局限**：
- ❌ 需要独立部署 Prefect Server
- ❌ 审批流程支持有限
- ❌ 与 LangGraph 集成复杂

### 为什么选择自实现

1. **架构简单**：不需要独立服务，复用现有基础设施
2. **集成容易**：与 LangGraph 无缝集成
3. **需求匹配**：功能刚好满足需求，不过度设计
4. **学习曲线低**：团队已熟悉 Python 和 LangGraph
5. **成本低**：无额外计算和存储成本

## 后果

### 正面影响

1. **架构简单**：不需要独立部署 Temporal Server
2. **集成容易**：与 LangGraph 无缝集成
3. **维护简单**：代码量少（约 500 行），易于理解和维护
4. **成本低**：无额外计算和存储成本

### 负面影响

1. **功能有限**：不支持 Temporal 的高级功能（并行执行、子 Workflow 等）
2. **可观测性**：需要自己实现 workflow 执行追踪
3. **测试成本**：需要自己编写测试用例

### 风险缓解

1. **功能扩展**：
   - 如果未来需要并行执行，可以添加 `parallel` 步骤类型
   - 如果未来需要子 Workflow，可以添加 `sub_workflow` 步骤类型
   - 如果功能需求超过自实现的能力，可以迁移到 Temporal

2. **可观测性**：
   ```python
   # 集成 LangSmith 追踪
   @traceable(name="workflow_execution")
   async def execute_workflow(workflow: Workflow, context: dict):
       for step in workflow.steps:
           with trace_step(step.name):
               result = await execute_step(step, context)
   ```

3. **测试覆盖**：
   ```python
   @pytest.mark.asyncio
   async def test_workflow_execution():
       """测试 workflow 执行"""
       workflow = parse_workflow("""
       name: test_workflow
       steps:
         - name: step1
           type: mcp_call
           tool: test_tool
       """)
       
       result = await workflow_engine.execute(workflow, {})
       assert "step1" in result
   
   @pytest.mark.asyncio
   async def test_workflow_resume():
       """测试 workflow 断点恢复"""
       # 执行到审批步骤
       with pytest.raises(ApprovalRequired) as exc:
           await workflow_engine.execute(workflow, {})
       
       resume_token = exc.value.token
       
       # 恢复执行
       result = await resume_workflow(resume_token)
       assert result["completed"] == True
   ```

4. **迁移路径**：
   - 如果未来需要迁移到 Temporal，YAML 格式可以保持不变
   - 只需要实现 YAML → Temporal Workflow 的转换器
   - 用户的 YAML 文件不需要修改

### 实施检查清单

- [ ] 实现 YAML 解析器（使用 PyYAML + Pydantic）
- [ ] 实现 Workflow 执行引擎
- [ ] 实现审批门逻辑（生成 resumeToken）
- [ ] 实现断点恢复逻辑
- [ ] 编写单元测试（解析、执行、恢复）
- [ ] 编写集成测试（完整 workflow 流程）
- [ ] 提供预置 YAML 模板（service_restart、database_failover 等）
- [ ] 文档化 YAML 格式和步骤类型

## 相关决策

- ADR-0001: 使用 LangGraph StateGraph 替代 Plan-Execute 模式
- ADR-0006: 使用 PostgreSQL 存储 Checkpoint（而非 Redis）

## 参考资料

- [Temporal Documentation](https://docs.temporal.io/)
- [LangGraph Interrupt](https://langchain-ai.github.io/langgraph/concepts/low_level/#interrupt)
- [PyYAML Documentation](https://pyyaml.org/wiki/PyYAMLDocumentation)
- ONCALL_FINAL.md 第七章：YAML Workflow Engine 设计

## 决策日期

2026-03-22

## 决策者

项目团队
