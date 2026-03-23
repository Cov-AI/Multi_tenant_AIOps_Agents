# 实现计划：多租户 OnCall Agent 平台

## 概述

本实现计划将现有单用户 OnCall AI Agent 系统改造为多租户 SaaS 产品。按照 P0（产生简历数字）→ P1（架构深度）→ P2（完整度）的优先级组织任务，确保每个阶段都能产出可量化的成果。

实现语言：Python
核心技术栈：FastAPI + SQLAlchemy + LangGraph + Milvus + Redis

## 任务列表

### P0 阶段：核心多租户能力 + 可量化指标

- [ ] 1. 建立数据模型和多租户隔离基础
  - [ ] 1.1 创建 PostgreSQL 数据模型和 RLS 策略
    - 使用 SQLAlchemy 定义所有核心表（tenants、users、agents、sessions、incidents、approvals、token_usage、audit_logs、checkpoints）
    - 为每张表启用 Row-Level Security（RLS）策略
    - 创建索引优化查询性能
    - 使用 Alembic 创建数据库迁移脚本
    - _需求：2.1, 2.2_
  
  - [ ]* 1.2 编写 Property Test：租户数据完全隔离
    - **Property 2: 租户数据完全隔离**
    - **验证需求：2.2, 2.4, 2.6**
    - 使用 hypothesis 生成随机租户 ID 和测试数据
    - 验证租户 A 查询不会返回租户 B 的数据（PostgreSQL、Milvus、Redis）
  
  - [ ]* 1.3 编写 Unit Tests：数据模型验证
    - 测试表创建和约束（外键、唯一性）
    - 测试 RLS 策略生效
    - 测试边缘情况（空值、超长字符串）

- [ ] 2. 实现 JWT 认证和租户上下文注入
  - [ ] 2.1 实现 JWT 编解码和中间件
    - 使用 PyJWT 实现 JWT 编码和解码
    - 创建 FastAPI 中间件解析 JWT 并注入 tenant_id 到请求上下文
    - 实现 API Key 验证（用于 Webhook 接入）
    - 设置数据库连接的 app.tenant_id 上下文变量
    - _需求：1.3, 1.4, 1.5_
  
  - [ ]* 2.2 编写 Property Test：JWT Round-Trip 保持身份信息
    - **Property 1: JWT Round-Trip 保持身份信息**
    - **验证需求：1.3, 1.4**
    - 验证任意有效的 tenant_id 和 user_id 编码后解码保持一致
  
  - [ ]* 2.3 编写 Unit Tests：认证错误处理
    - 测试无效 JWT（过期、签名错误、缺少字段）
    - 测试 API Key 不存在或已撤销
    - 测试权限不足场景（403 错误）


- [ ] 3. 实现 Milvus 多租户隔离
  - [ ] 3.1 修改向量存储以支持租户 Partition
    - 在 memory/vector_store.py 中为每个租户创建独立 Partition（tenant_{tenant_id}）
    - 修改 ingest_runbook 方法，写入时指定租户 Partition
    - 修改 search 方法，查询时同时指定 partition_names 和 metadata filter（tenant_id）
    - 实现返回结果的 tenant_id 一致性验证
    - _需求：2.3, 2.4, 9.1, 9.2, 9.3, 9.5_
  
  - [ ]* 3.2 编写 Property Test：Partition 命名一致性
    - **Property 3: Partition 命名一致性**
    - **验证需求：2.3, 2.4**
    - 验证 Partition 名称遵循 tenant_{tenant_id} 格式
  
  - [ ]* 3.3 编写 Property Test：RAG 检索双重过滤
    - **Property 17: RAG 检索双重过滤**
    - **验证需求：9.3, 9.5**
    - 验证检索同时使用 partition_names 和 metadata filter
    - 验证返回结果的 tenant_id 与请求者一致
  
  - [ ]* 3.4 编写 Unit Tests：Milvus 集成测试
    - 测试 Partition 创建和删除
    - 测试跨租户检索隔离
    - 测试 Milvus 服务不可用时的降级处理

- [ ] 4. 实现 RAGAS 评估框架
  - [ ] 4.1 创建 RAG 评估测试集和评估脚本
    - 在 evaluation/ragas_eval.py 中实现 RAGAS 评估
    - 创建 100 条 OnCall Q&A 测试集（evaluation/ragas_testset.json）
    - 使用 RAGAS 框架计算 Faithfulness 和 Context Recall 指标
    - 生成评估报告，目标：Faithfulness >= 85%
    - _需求：10.1, 10.2, 10.3, 10.4, 10.5_
  
  - [ ]* 4.2 编写 Unit Tests：评估框架测试
    - 测试测试集加载和验证
    - 测试评估指标计算
    - 测试报告生成

- [ ] 5. 实现四层上下文 Compaction
  - [ ] 5.1 实现上下文组装和 Compaction 逻辑
    - 在 memory/compaction.py 中实现四层上下文组装（Workspace + Summary + Recent + RAG）
    - 实现 token 计数和 Compaction 触发判断（超过 context_window - 20000）
    - 使用 LLM 生成 branch_summary 并存入 Redis
    - 保留最近 3-5 轮完整消息，丢弃更早消息
    - 更新 Redis 压缩计数器
    - _需求：5.1, 5.2, 5.3, 5.4, 5.5_
  
  - [ ]* 5.2 编写 Property Test：四层上下文结构完整性
    - **Property 7: 四层上下文结构完整性**
    - **验证需求：5.1**
    - 验证组装的上下文包含所有四层
  
  - [ ]* 5.3 编写 Property Test：Compaction 触发和执行
    - **Property 8: Compaction 触发和执行**
    - **验证需求：5.2, 5.3, 5.4, 5.5**
    - 验证超过阈值时触发 Compaction
    - 验证生成 branch_summary 并正确存储
  
  - [ ]* 5.4 编写 Unit Tests：Compaction 边缘情况
    - 测试空历史消息
    - 测试 LLM 生成 summary 失败的降级处理
    - 测试 Redis 写入失败的错误处理

- [ ] 6. 实现 Token 消耗 A/B 测试
  - [ ] 6.1 创建 Token 基准测试框架
    - 在 evaluation/token_benchmark.py 中实现 A/B 测试
    - 创建 20 个模拟事故对话场景（evaluation/mock_incidents.py）
    - 对比固定截断 20 轮和四层 Compaction 的 token 消耗
    - 计算 token 减少百分比，目标：>= 70%
    - 生成对比报告
    - _需求：11.1, 11.2, 11.3, 11.4, 11.5_
  
  - [ ]* 6.2 编写 Property Test：Token 消耗记录完整性
    - **Property 18: Token 消耗记录完整性**
    - **验证需求：11.3**
    - 验证每次 LLM 调用都记录 token 使用
  
  - [ ]* 6.3 编写 Unit Tests：基准测试验证
    - 测试模拟场景加载
    - 测试 token 计数准确性
    - 测试报告生成

- [ ] 7. Checkpoint：P0 阶段验证
  - 运行所有 P0 阶段的单元测试和属性测试
  - 验证 RAGAS Faithfulness >= 85%
  - 验证 Token 减少率 >= 70%
  - 确认所有测试通过，询问用户是否继续 P1 阶段


### P1 阶段：架构深度 - 状态机、工作流、Session 持久化

- [ ] 8. 实现六状态 AIOps Agent
  - [ ] 8.1 重构 AIOps Agent 为六状态 StateGraph
    - 在 agents/aiops_agent.py 中实现六状态流转（TRIGGERED → ANALYZING → AWAITING_APPROVAL → EXECUTING → VERIFYING → RESOLVED）
    - 实现 analyze_node（并行调用 MCP 工具：Loki、Prometheus、RAG 检索）
    - 实现 plan_node（LLM 生成修复方案，判断操作风险等级）
    - 实现 wait_for_approval_node（高危操作触发 interrupt()）
    - 实现 execute_node（执行修复操作）
    - 实现 verify_node（验证服务恢复）
    - 添加 ESCALATED 状态处理（失败或审批拒绝）
    - _需求：6.1, 6.2, 6.3_
  
  - [ ]* 8.2 编写 Property Test：六状态流转完整性
    - **Property 10: 六状态流转完整性**
    - **验证需求：6.1, 6.2**
    - 验证状态按正确顺序流转或转为 ESCALATED
  
  - [ ]* 8.3 编写 Unit Tests：状态机边缘情况
    - 测试每个节点的错误处理
    - 测试状态转换记录到数据库
    - 测试 LLM API 失败时的降级

- [ ] 9. 实现 LangGraph Checkpoint 持久化
  - [ ] 9.1 实现 PostgreSQL Checkpoint 存储
    - 在 memory/checkpoint.py 中实现 Checkpoint 管理
    - 配置 LangGraph 使用 PostgreSQL 作为 Checkpoint 存储
    - 实现 interrupt() 触发时的图状态序列化
    - 实现从 Checkpoint 恢复图状态
    - 确保 Checkpoint 写入使用事务（原子性）
    - _需求：7.1, 7.2, 7.5, 7.6_
  
  - [ ]* 9.2 编写 Property Test：Checkpoint 恢复幂等性
    - **Property 13: Checkpoint 恢复幂等性**
    - **验证需求：7.5, 7.6**
    - 验证从 Checkpoint 恢复不重新执行已完成步骤
  
  - [ ]* 9.3 编写 Unit Tests：Checkpoint 错误处理
    - 测试 Checkpoint 数据损坏时的处理
    - 测试数据库连接失败时的重试
    - 测试服务重启后的恢复

- [ ] 10. 实现 YAML Workflow Engine
  - [ ] 10.1 创建 YAML workflow 解析和执行引擎
    - 在 workflow/engine.py 中实现 YAML 解析器（使用 PyYAML）
    - 定义 Workflow 和 WorkflowStep Pydantic 模型
    - 实现步骤类型：mcp_call、llm_call、approval
    - 实现 approval gate：生成 resumeToken，暂停执行
    - 实现从断点恢复：读取 completed_steps，跳过已完成步骤
    - 创建预置 YAML 模板（service_restart.yaml、database_failover.yaml）
    - _需求：8.1, 8.2, 8.3, 8.4, 8.5_
  
  - [ ]* 10.2 编写 Property Test：YAML Workflow Round-Trip
    - **Property 14: YAML Workflow Round-Trip**
    - **验证需求：8.1, 20.3**
    - 验证 parse(serialize(workflow)) ≈ workflow
  
  - [ ]* 10.3 编写 Property Test：Approval Gate 暂停执行
    - **Property 15: Approval Gate 暂停执行**
    - **验证需求：8.2, 8.3, 8.4**
    - 验证 approval 步骤生成 resumeToken 并暂停
    - 验证支持从断点恢复
  
  - [ ]* 10.4 编写 Property Test：无效输入错误处理
    - **Property 28: 无效输入错误处理**
    - **验证需求：20.4**
    - 验证无效 YAML 返回描述性错误信息
  
  - [ ]* 10.5 编写 Unit Tests：Workflow 执行测试
    - 测试各种步骤类型的执行
    - 测试变量替换（{{variable}}）
    - 测试步骤依赖和结果传递

- [ ] 11. 实现审批流程
  - [ ] 11.1 实现 resumeToken 生成和审批管理
    - 在 workflow/approval.py 中实现审批逻辑
    - 生成 resumeToken（UUID）并写入 PostgreSQL approvals 表和 Redis
    - 实现审批请求发送（Slack 通知）
    - 实现审批确认 API（验证 resumeToken，恢复执行）
    - 实现审批超时处理（24 小时自动过期）
    - _需求：7.3, 7.4, 7.5, 7.6_
  
  - [ ]* 11.2 编写 Property Test：高危操作触发 Interrupt
    - **Property 12: 高危操作触发 Interrupt**
    - **验证需求：7.1, 7.2, 7.3**
    - 验证高危操作触发 interrupt() 并生成 resumeToken
  
  - [ ]* 11.3 编写 Unit Tests：审批流程测试
    - 测试审批请求创建
    - 测试审批确认和拒绝
    - 测试审批超时自动过期

- [ ] 12. 实现 Session 三层存储
  - [ ] 12.1 实现 Redis + PostgreSQL + S3 三层 Session 存储
    - 在 memory/session_store.py 中实现 SessionStore 接口
    - 实现 Redis 存储热 Session 消息列表（TTL 24 小时）
    - 实现 PostgreSQL 存储 Session 元数据（session_key、token_count、last_active）
    - 实现 S3 归档冷数据（JSONL 格式）
    - 实现归档触发逻辑（24 小时未活跃）
    - 实现从归档恢复 Session
    - _需求：4.1, 4.2, 4.3, 4.4, 4.5_
  
  - [ ]* 12.2 编写 Property Test：Session 三层存储一致性
    - **Property 5: Session 三层存储一致性**
    - **验证需求：4.1, 4.2, 4.3, 4.5**
    - 验证消息写入 Redis 时元数据同步写入 PostgreSQL
    - 验证归档到 S3 后能完整恢复
  
  - [ ]* 12.3 编写 Property Test：Session 归档触发条件
    - **Property 6: Session 归档触发条件**
    - **验证需求：4.4**
    - 验证 last_active 超过 24 小时触发归档
  
  - [ ]* 12.4 编写 Unit Tests：Session 存储测试
    - 测试 Redis 写入失败的降级处理
    - 测试 S3 归档和恢复
    - 测试并发访问 Session

- [ ] 13. Checkpoint：P1 阶段验证
  - 运行所有 P1 阶段的单元测试和属性测试
  - 手动测试完整事故处理流程（触发 → 分析 → 审批 → 执行 → 验证）
  - 验证服务重启后能从 Checkpoint 恢复
  - 确认所有测试通过，询问用户是否继续 P2 阶段


### P2 阶段：完整度 - Gateway、RBAC、可观测性、接入

- [ ] 14. 实现 Gateway 层
  - [ ] 14.1 创建 FastAPI Gateway 和消息路由
    - 在 gateway/server.py 中创建 FastAPI 应用入口
    - 在 gateway/router.py 中实现消息路由逻辑
    - 实现 Webhook 接入（/webhook/alert）
    - 实现 Slack 接入（/slack/events）
    - 实现消息归一化为 MessageEnvelope 格式
    - 实现意图分类（Chat Agent vs AIOps Agent）
    - 集成 JWT 中间件
    - _需求：15.1, 15.2, 15.3, 15.4, 15.5_
  
  - [ ]* 14.2 编写 Property Test：消息路由正确性
    - **Property 22: 消息路由正确性**
    - **验证需求：15.1, 15.2, 15.3, 15.4**
    - 验证 Webhook 告警路由到 AIOps Agent
    - 验证 Slack 消息根据意图正确路由
  
  - [ ]* 14.3 编写 Property Test：消息格式归一化
    - **Property 23: 消息格式归一化**
    - **验证需求：15.5**
    - 验证不同来源消息转换为统一 MessageEnvelope
  
  - [ ]* 14.4 编写 Unit Tests：Gateway 集成测试
    - 测试 Webhook 请求处理
    - 测试 Slack 事件处理
    - 测试无效请求拒绝

- [ ] 15. 实现限流和配额管理
  - [ ] 15.1 实现 Redis 限流器
    - 在 gateway/limiter.py 中实现 RateLimiter 接口
    - 使用 Redis 维护 per-tenant 请求计数器（quota:tenant:{tid}:requests:{minute}）
    - 实现限流检查逻辑（超过配额返回 429）
    - 从 PostgreSQL tenants 表读取租户配额
    - 支持动态调整配额
    - _需求：16.1, 16.2, 16.3, 16.4, 16.5_
  
  - [ ]* 15.2 编写 Property Test：限流配额检查
    - **Property 24: 限流配额检查**
    - **验证需求：16.2, 16.3**
    - 验证超过配额时返回 429 错误
  
  - [ ]* 15.3 编写 Unit Tests：限流测试
    - 测试配额边界情况
    - 测试 Redis 不可用时的降级
    - 测试配额重置逻辑

- [ ] 16. 实现 RBAC 权限控制
  - [ ] 16.1 实现基于角色的访问控制
    - 在 auth/rbac.py 中实现 RBAC 逻辑
    - 定义角色权限（Admin/Member/Viewer）
    - 实现权限检查装饰器
    - 集成到 API 路由
    - _需求：1.2_
  
  - [ ]* 16.2 编写 Unit Tests：RBAC 测试
    - 测试各角色权限边界
    - 测试权限不足返回 403
    - 测试权限继承

- [ ] 17. 实现审计日志
  - [ ] 17.1 实现完整审计日志记录
    - 在所有高危操作点记录审计日志
    - 记录 tenant_id、user_id、action、resource、payload、timestamp
    - 实现审计日志查询 API（支持按租户、用户、时间范围过滤）
    - 配置审计日志保留策略（至少 1 年）
    - _需求：17.1, 17.2, 17.3, 17.4, 17.5_
  
  - [ ]* 17.2 编写 Property Test：状态转换审计记录
    - **Property 11: 状态转换审计记录**
    - **验证需求：6.3, 17.1, 17.2**
    - 验证所有状态转换都记录审计日志
  
  - [ ]* 17.3 编写 Unit Tests：审计日志测试
    - 测试审计日志写入
    - 测试审计日志查询和过滤
    - 测试审计日志保留策略

- [ ] 18. 实现 Workspace 配置管理
  - [ ] 18.1 实现 Workspace 配置存储和缓存
    - 在 PostgreSQL agents.config JSONB 字段存储 Workspace 配置
    - 在 Redis 中缓存 Workspace 配置（TTL 1 小时）
    - 实现 Workspace 配置读取（优先 Redis，未命中读 PostgreSQL）
    - 实现 Workspace 配置更新 API
    - _需求：18.1, 18.2, 18.3, 18.4, 18.5_
  
  - [ ]* 18.2 编写 Property Test：Workspace 配置缓存优先
    - **Property 25: Workspace 配置缓存优先**
    - **验证需求：18.3, 18.4**
    - 验证优先从 Redis 读取，未命中读 PostgreSQL
  
  - [ ]* 18.3 编写 Property Test：Workspace 配置 JSON Round-Trip
    - **Property 27: Workspace 配置 JSON Round-Trip**
    - **验证需求：20.5**
    - 验证 parse(serialize(config)) == config
  
  - [ ]* 18.4 编写 Unit Tests：Workspace 配置测试
    - 测试配置读取和更新
    - 测试缓存失效和刷新
    - 测试无效配置拒绝

- [ ] 19. 实现 MCP 工具集成
  - [ ] 19.1 实现 MCP 协议客户端
    - 在 tools/mcp_client.py 中实现 MCP 协议调用
    - 支持调用 Loki、Prometheus、kubectl、数据库查询工具
    - 实现结构化 JSON 响应解析
    - 实现超时和重试逻辑
    - 支持开发环境使用 Mock MCP Server
    - _需求：3.2, 19.1, 19.2, 19.3, 19.4, 19.5_
  
  - [ ]* 19.2 编写 Property Test：MCP 协议调用返回结构化数据
    - **Property 26: MCP 协议调用返回结构化数据**
    - **验证需求：19.3**
    - 验证 MCP 工具返回 JSON 格式而非原始数据流
  
  - [ ]* 19.3 编写 Unit Tests：MCP 集成测试
    - 测试各种 MCP 工具调用
    - 测试 MCP Server 超时处理
    - 测试 Mock MCP Server 切换

- [ ] 20. 实现 LangSmith 追踪集成
  - [ ] 20.1 集成 LangSmith 追踪
    - 配置 LangSmith 环境变量（LANGCHAIN_API_KEY、LANGCHAIN_TRACING_V2）
    - 在每个 Agent 调用注入 tenant_id 和 incident_id 作为 metadata
    - 验证 trace 正确上报到 LangSmith
    - _需求：13.1, 13.2, 13.3, 13.4, 13.5_
  
  - [ ]* 20.2 编写 Property Test：LangSmith Trace Metadata 注入
    - **Property 20: LangSmith Trace Metadata 注入**
    - **验证需求：13.2**
    - 验证每个 trace 包含 tenant_id 和 incident_id
  
  - [ ]* 20.3 编写 Unit Tests：LangSmith 集成测试
    - 测试 trace 上报
    - 测试 metadata 注入
    - 测试 LangSmith 不可用时的降级

- [ ] 21. 实现 Prometheus 指标采集
  - [ ] 21.1 实现 Prometheus 指标暴露
    - 在 observability/metrics.py 中使用 prometheus-client 定义指标
    - 实现 per-tenant 指标：incident_total、incident_duration_seconds、token_usage_total、approval_wait_seconds、agent_invocations_total
    - 暴露 /metrics 端点供 Prometheus 抓取
    - 配置 Grafana Dashboard 展示指标
    - 配置告警规则（token 超过配额、高错误率）
    - _需求：14.1, 14.2, 14.3, 14.4, 14.5_
  
  - [ ]* 21.2 编写 Property Test：Prometheus 指标租户标签
    - **Property 21: Prometheus 指标租户标签**
    - **验证需求：14.2, 14.5**
    - 验证指标包含 tenant_id 标签
    - 验证不包含高基数字段（session_id、incident_id）
  
  - [ ]* 21.3 编写 Unit Tests：Prometheus 指标测试
    - 测试指标采集和暴露
    - 测试 /metrics 端点格式
    - 测试告警规则触发

- [ ] 22. 实现事故响应时间评估
  - [ ] 22.1 创建响应时间基准测试
    - 在 evaluation/response_time.py 中实现响应时间评估
    - 记录事故从 created_at 到 resolved_at 的时长
    - 维护人工处理基线时间
    - 计算 AI 处理时间相比基线的减少百分比
    - 目标：>= 80% 时间减少率
    - 在 Grafana Dashboard 展示 per-tenant 平均处理时长
    - _需求：12.1, 12.2, 12.3, 12.4, 12.5_
  
  - [ ]* 22.2 编写 Property Test：事故处理时长记录
    - **Property 19: 事故处理时长记录**
    - **验证需求：12.1, 12.3**
    - 验证记录完整时长并计算对比百分比
  
  - [ ]* 22.3 编写 Unit Tests：响应时间评估测试
    - 测试时长计算准确性
    - 测试基线数据加载
    - 测试报告生成

- [ ] 23. 实现 Slack 接入
  - [ ] 23.1 实现 Slack Bot 集成
    - 实现 Slack 事件订阅（/slack/events）
    - 实现 Slack 消息发送（通知、审批请求）
    - 实现 Slack 交互组件（审批按钮）
    - 配置 Slack App 权限和 OAuth
    - _需求：6.4, 7.4_
  
  - [ ]* 23.2 编写 Unit Tests：Slack 集成测试
    - 测试 Slack 事件处理
    - 测试 Slack 消息发送
    - 测试 Slack 交互响应

- [ ] 24. 实现开发环境 Mock 支持
  - [ ] 24.1 创建开发环境配置
    - 创建 Docker Compose 配置（PostgreSQL、Redis、Milvus、Mock MCP Server）
    - 实现 Mock MCP Server（返回预定义测试数据）
    - 创建 20 个模拟事故对话场景
    - 创建 100 条 Q&A 测试集
    - 支持 MULTI_TENANT_MODE=false 单租户模式
    - _需求：22.1, 22.2, 22.3, 22.4, 22.5_
  
  - [ ]* 24.2 编写 Unit Tests：Mock 环境测试
    - 测试 Mock MCP Server 响应
    - 测试模拟场景加载
    - 测试单租户模式降级

- [ ] 25. 实现扩展性预留
  - [ ] 25.1 预留消息队列接口
    - 定义 MessageQueue 抽象接口（enqueue/dequeue）
    - 实现 BackgroundTasksQueue（当前实现）
    - 预留 KafkaQueue 实现（注释代码）
    - 支持通过环境变量切换传输层
    - _需求：21.1, 21.2, 21.3, 21.4, 21.5_
  
  - [ ]* 25.2 编写 Unit Tests：消息队列接口测试
    - 测试 BackgroundTasksQueue 实现
    - 测试接口切换逻辑
    - 测试消息序列化和反序列化

- [ ] 26. 实现 REST API 路由
  - [ ] 26.1 创建完整 REST API
    - 在 api/incidents.py 中实现事故管理 API
    - 在 api/approvals.py 中实现审批 API
    - 在 api/workspaces.py 中实现 Workspace 配置 API
    - 在 api/webhooks.py 中实现 Webhook 接入 API
    - 使用 Pydantic 模型验证请求和响应
    - 实现统一错误响应格式
    - 生成 OpenAPI 文档
  
  - [ ]* 26.2 编写 Unit Tests：API 集成测试
    - 测试所有 API 端点
    - 测试参数验证
    - 测试错误响应格式

- [ ] 27. 实现错误处理和监控
  - [ ] 27.1 实现统一错误处理
    - 实现错误分类（4xx 客户端错误、5xx 服务端错误、业务逻辑错误）
    - 实现统一 ErrorResponse 格式
    - 实现结构化日志记录（structlog）
    - 实现错误监控和告警（Prometheus）
    - 实现降级策略（Redis 失败、Milvus 失败、LLM API 失败）
  
  - [ ]* 27.2 编写 Unit Tests：错误处理测试
    - 测试各类错误响应格式
    - 测试降级策略
    - 测试错误日志记录

- [ ] 28. 实现 Redis Key 命名规范
  - [ ] 28.1 统一 Redis Key 命名
    - 实现 Redis Key 生成工具函数
    - 确保所有 key 包含 tenant_id 前缀
    - 实现 key 过期策略（TTL）
    - _需求：2.5_
  
  - [ ]* 28.2 编写 Property Test：Redis Key 租户前缀
    - **Property 4: Redis Key 租户前缀**
    - **验证需求：2.5**
    - 验证所有 Redis key 包含 tenant_id 前缀
  
  - [ ]* 28.3 编写 Unit Tests：Redis Key 测试
    - 测试 key 生成格式
    - 测试 key 过期策略
    - 测试 key 冲突检测

- [ ] 29. 实现 Runbook 摄入
  - [ ] 29.1 实现 Runbook 上传和摄入
    - 实现 Runbook 上传 API
    - 实现文档切片（使用 LangChain TextSplitter）
    - 实现 embedding 生成
    - 写入 Milvus 租户 Partition
    - 原文存储到 S3
    - _需求：9.1, 9.2_
  
  - [ ]* 29.2 编写 Property Test：Runbook 摄入租户隔离
    - **Property 16: Runbook 摄入租户隔离**
    - **验证需求：9.1, 9.2**
    - 验证所有 chunk 写入正确 Partition
    - 验证 metadata 包含正确 tenant_id
  
  - [ ]* 29.3 编写 Unit Tests：Runbook 摄入测试
    - 测试文档切片
    - 测试 embedding 生成
    - 测试 Milvus 写入

- [ ] 30. 实现 RAG 检索不缓存
  - [ ] 30.1 确保 RAG 检索每次重新执行
    - 验证 RAG 检索不使用缓存
    - 每次 Agent 调用重新执行检索
    - _需求：5.6_
  
  - [ ]* 30.2 编写 Property Test：RAG 检索不缓存
    - **Property 9: RAG 检索不缓存**
    - **验证需求：5.6**
    - 验证每次调用重新执行检索
  
  - [ ]* 30.3 编写 Unit Tests：RAG 检索测试
    - 测试检索结果不缓存
    - 测试检索参数变化时结果更新

- [ ] 31. Checkpoint：P2 阶段验证
  - 运行所有 P2 阶段的单元测试和属性测试
  - 手动测试完整端到端流程（Webhook → Gateway → Agent → MCP → 审批 → 执行 → 通知）
  - 验证所有 API 端点正常工作
  - 验证 Prometheus 指标和 Grafana Dashboard
  - 验证 LangSmith 追踪正常上报
  - 确认所有测试通过，系统达到生产就绪状态


### 集成测试和端到端测试

- [ ] 32. 端到端集成测试
  - [ ]* 32.1 编写端到端测试：完整事故处理流程
    - 测试从 Webhook 告警到事故解决的完整流程
    - 测试审批流程（触发 → 暂停 → 审批 → 恢复 → 执行）
    - 测试服务重启后从 Checkpoint 恢复
    - 测试多租户隔离（并发处理不同租户的事故）
  
  - [ ]* 32.2 编写集成测试：RAG Pipeline
    - 测试 Runbook 上传 → 切片 → embedding → 写入 Milvus
    - 测试 RAG 检索 → 排序 → 返回结果
    - 测试租户隔离（租户 A 检索不到租户 B 的 runbook）
  
  - [ ]* 32.3 编写集成测试：Session 生命周期
    - 测试 Session 创建 → 消息追加 → Compaction → 归档 → 恢复
    - 测试三层存储一致性（Redis、PostgreSQL、S3）
  
  - [ ]* 32.4 编写集成测试：可观测性
    - 测试 LangSmith trace 上报
    - 测试 Prometheus 指标采集
    - 测试审计日志记录

## 注意事项

### 任务执行原则

1. **按优先级顺序执行**：严格按照 P0 → P1 → P2 顺序执行，每个阶段完成后进行 Checkpoint 验证
2. **测试驱动开发**：每个核心功能实现后立即编写对应的属性测试和单元测试
3. **增量验证**：每完成一个任务，运行相关测试确保功能正确
4. **保留原有逻辑**：改造时不删除原有 Agent 逻辑，只在外层叠加多租户能力
5. **使用成熟工具**：优先使用业界成熟的库和工具，避免重复造轮子

### 可选任务说明

- 标记为 `*` 的任务为可选任务（主要是测试任务）
- 可选任务可以跳过以加快 MVP 开发速度
- 但强烈建议实现所有属性测试，以确保系统正确性

### 属性测试要求

- 每个属性测试必须运行至少 100 次迭代
- 使用 hypothesis 库生成随机测试数据
- 每个测试必须引用设计文档中的属性编号
- 使用注释标签格式：`# Feature: multi-tenant-oncall-platform, Property {N}: {property_text}`

### Checkpoint 验证标准

**P0 Checkpoint**：
- 所有 P0 单元测试和属性测试通过
- RAGAS Faithfulness >= 85%
- Token 减少率 >= 70%
- 数据库 RLS 策略生效
- Milvus 租户隔离验证通过

**P1 Checkpoint**：
- 所有 P1 单元测试和属性测试通过
- 完整事故处理流程（6 状态）正常工作
- Checkpoint 恢复功能验证通过
- YAML Workflow 执行正常
- Session 三层存储一致性验证通过

**P2 Checkpoint**：
- 所有 P2 单元测试和属性测试通过
- 所有 API 端点正常工作
- Prometheus 指标和 Grafana Dashboard 正常
- LangSmith 追踪正常上报
- 端到端集成测试通过
- 系统达到生产就绪状态

### 开发环境配置

**必需服务**：
- PostgreSQL 15+
- Redis 7+
- Milvus 2.3+
- Mock MCP Server（开发阶段）

**环境变量**：
```bash
# 数据库
DATABASE_URL=postgresql://user:pass@localhost:5432/oncall
REDIS_URL=redis://localhost:6379
MILVUS_HOST=localhost
MILVUS_PORT=19530

# 认证
JWT_SECRET=your-secret-key

# LLM
ANTHROPIC_API_KEY=your-api-key

# 可观测性
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your-langsmith-key

# 开发模式
MULTI_TENANT_MODE=true
MCP_SERVER_URL=http://localhost:8001
```

**启动开发环境**：
```bash
# 启动依赖服务
docker-compose -f docker-compose.test.yml up -d

# 运行数据库迁移
alembic upgrade head

# 运行测试
pytest

# 启动开发服务器
uvicorn gateway.server:app --reload
```

### 技术栈参考

**核心框架**：
- FastAPI（API 框架）
- SQLAlchemy（ORM）
- Alembic（数据库迁移）
- Pydantic（数据验证）

**认证授权**：
- PyJWT（JWT 处理）
- passlib（密码哈希）

**存储**：
- redis-py（Redis 客户端）
- pymilvus（Milvus 客户端）
- boto3（S3 客户端）

**LLM 集成**：
- LangGraph（状态图引擎）
- LangChain（LLM 抽象）
- LangSmith（追踪）

**监控**：
- prometheus-client（指标采集）
- structlog（结构化日志）

**测试**：
- pytest（测试框架）
- hypothesis（属性测试）
- pytest-asyncio（异步测试）
- pytest-mock（Mock）
- pytest-cov（覆盖率）

**代码质量**：
- black（格式化）
- isort（导入排序）
- mypy（类型检查）
- ruff（Linting）

### 实现建议

1. **从数据模型开始**：先建立数据库表和 RLS 策略，确保多租户隔离基础
2. **早期集成测试**：尽早实现端到端测试，确保各模块正确集成
3. **Mock 外部依赖**：开发阶段使用 Mock MCP Server 和 Mock LLM，避免依赖外部服务
4. **增量部署**：每个阶段完成后可以部署到测试环境，收集反馈
5. **文档同步更新**：实现过程中更新 API 文档和部署文档

### 常见问题

**Q: 为什么属性测试标记为可选？**
A: 属性测试需要较长时间运行（每个测试 100+ 次迭代），可以在 MVP 阶段跳过以加快开发速度。但强烈建议在生产前实现所有属性测试。

**Q: 如何处理 LLM API 成本？**
A: 开发阶段使用 Mock LLM 或小模型（如 claude-3-haiku），只在集成测试和评估时使用真实 LLM。

**Q: 如何验证多租户隔离？**
A: 运行属性测试 Property 2（租户数据完全隔离），使用 hypothesis 生成随机租户 ID 和数据，验证查询结果不跨租户。

**Q: Checkpoint 恢复如何测试？**
A: 在测试中模拟服务重启（保存 Checkpoint 后重新创建 Agent 实例），验证能从断点继续执行。

**Q: 如何处理 Redis 不可用？**
A: 实现降级策略：缓存读取失败时直接从 PostgreSQL 读取，缓存写入失败时记录警告但继续执行。

## 总结

本实现计划共 32 个顶层任务，按 P0/P1/P2 三个阶段组织：

- **P0 阶段（7 个任务）**：建立多租户基础，产生可量化指标（RAGAS 85%+、Token 减少 70%+）
- **P1 阶段（6 个任务）**：实现架构深度（6 状态机、Checkpoint、YAML Workflow、Session 持久化）
- **P2 阶段（18 个任务）**：完善系统（Gateway、RBAC、可观测性、Slack 接入、完整 API）
- **集成测试（1 个任务）**：端到端验证

每个阶段都有明确的 Checkpoint 验证标准，确保增量交付和质量保证。所有核心功能都配有属性测试和单元测试，确保系统正确性和可维护性。

