# 需求文档：多租户 OnCall Agent 平台

## 简介

本文档定义了将现有单用户 OnCall AI Agent 系统改造为多租户 SaaS 产品的需求。系统基于 LangGraph + Milvus RAG + MCP 工具集成，参考 OpenClaw 架构思想，实现企业级多租户 OnCall 自动化平台。核心价值链：告警触发 → Agent 自动分析 → 检索 runbook → 生成修复方案 → 人工审批 → 执行修复 → 验证恢复。

## 术语表

- **Platform**：多租户 OnCall Agent 平台（本系统）
- **Tenant**：租户，使用平台的工程组织（企业客户）
- **User**：用户，属于某个租户的工程师
- **Agent**：AI Agent 实例，执行事故分析和修复任务
- **Session**：对话会话，记录 Agent 与用户的交互历史
- **Incident**：事故，需要处理的告警或故障
- **Runbook**：运维手册，记录故障处理步骤的文档
- **MCP_Server**：Model Context Protocol 服务器，部署在用户内网的工具执行代理
- **Gateway**：网关层，负责消息接收和路由
- **Workspace**：工作空间配置，包含 Agent 人格定义和操作规范
- **Compaction**：上下文压缩，通过摘要和分层减少 token 消耗
- **Checkpoint**：检查点，LangGraph 图执行状态的持久化快照
- **ResumeToken**：恢复令牌，用于审批流程中断后的恢复标识
- **RLS**：Row-Level Security，PostgreSQL 行级安全策略
- **Partition**：Milvus 分区，用于租户数据隔离
- **RAG**：Retrieval-Augmented Generation，检索增强生成
- **RAGAS**：RAG Assessment，RAG 系统评估框架

## 开发原则与约束

### SOLID 原则

在整个开发过程中，所有代码实现必须遵守 SOLID 原则：

1. **单一职责原则（Single Responsibility Principle）**
   - 每个类/模块只负责一个明确的功能
   - 例如：SessionStore 只负责 Session 存储，不处理业务逻辑
   - 例如：TenantIsolationMiddleware 只负责租户上下文注入，不处理认证

2. **开闭原则（Open/Closed Principle）**
   - 对扩展开放，对修改关闭
   - 使用抽象接口和依赖注入，便于替换实现
   - 例如：MessageQueue 接口可以有 InMemoryQueue、RedisQueue、KafkaQueue 多种实现

3. **里氏替换原则（Liskov Substitution Principle）**
   - 子类必须能够替换父类而不影响程序正确性
   - 例如：所有 StorageBackend 实现必须遵守相同的契约

4. **接口隔离原则（Interface Segregation Principle）**
   - 客户端不应依赖它不需要的接口
   - 例如：ReadOnlySessionStore 和 WritableSessionStore 分离

5. **依赖倒置原则（Dependency Inversion Principle）**
   - 高层模块不应依赖低层模块，都应依赖抽象
   - 使用依赖注入容器管理依赖关系
   - 例如：Agent 依赖 ISessionStore 接口，而不是具体的 RedisSessionStore

### 避免重复造轮子

在实现任何功能前，必须优先考虑使用业界成熟的工具、库和最佳实践：

#### 认证与授权
- **JWT 处理**：使用 `PyJWT` 或 `python-jose`，不自己实现 JWT 编解码
- **密码哈希**：使用 `passlib` 或 `bcrypt`，不自己实现哈希算法
- **RBAC**：参考 Casbin 或 Flask-Security 的权限模型

#### 数据库与 ORM
- **ORM**：使用 SQLAlchemy，不自己实现 SQL 构建器
- **数据库迁移**：使用 Alembic，不手写 SQL 迁移脚本
- **连接池**：使用 SQLAlchemy 内置连接池或 psycopg2 连接池

#### 缓存与消息队列
- **Redis 客户端**：使用 `redis-py`，考虑 `redis-om-python` 用于对象映射
- **消息队列**：当前使用 FastAPI BackgroundTasks，扩展时使用 `aiokafka` 或 `celery`

#### API 开发
- **参数验证**：使用 Pydantic，不手写验证逻辑
- **API 文档**：使用 FastAPI 自动生成的 OpenAPI 文档
- **限流**：使用 `slowapi` 或 `fastapi-limiter`

#### 向量数据库
- **Milvus 客户端**：使用官方 `pymilvus` SDK
- **Embedding**：使用 LangChain 的 Embeddings 抽象，支持多种模型切换

#### LLM 集成
- **LangGraph**：使用官方 LangGraph 框架，不自己实现状态图引擎
- **LangSmith**：使用官方 SDK 集成追踪
- **Prompt 管理**：考虑使用 LangChain Hub 或 Promptfoo

#### 配置管理
- **环境变量**：使用 `pydantic-settings`，不手写配置加载
- **配置验证**：使用 Pydantic 模型验证配置完整性

#### 测试
- **单元测试**：使用 `pytest`
- **Mock**：使用 `pytest-mock` 或 `unittest.mock`
- **异步测试**：使用 `pytest-asyncio`
- **覆盖率**：使用 `pytest-cov`

#### 日志与监控
- **结构化日志**：使用 `structlog` 或 Python 标准库 logging
- **Prometheus 指标**：使用 `prometheus-client`
- **分布式追踪**：LangSmith（Agent 追踪）+ OpenTelemetry（可选，用于服务追踪）

#### YAML 处理
- **YAML 解析**：使用 `PyYAML` 或 `ruamel.yaml`（支持保留注释和格式）
- **Schema 验证**：使用 `pydantic` 或 `jsonschema` 验证 YAML 结构

#### 安全
- **SQL 注入防护**：使用 SQLAlchemy 参数化查询
- **XSS 防护**：使用 FastAPI 自动转义
- **CORS**：使用 `fastapi.middleware.cors`
- **Rate Limiting**：使用 `slowapi`

#### 代码质量
- **代码格式化**：使用 `black` 和 `isort`
- **类型检查**：使用 `mypy`
- **Linting**：使用 `ruff` 或 `flake8`
- **Pre-commit hooks**：使用 `pre-commit` 框架

### 架构模式参考

- **Gateway 模式**：参考 OpenClaw 的消息归一化设计
- **Repository 模式**：数据访问层使用 Repository 模式封装
- **Factory 模式**：LLM、Embedding、Storage 使用 Factory 创建实例
- **Strategy 模式**：不同的 Compaction 策略、路由策略使用 Strategy 模式
- **Observer 模式**：事故状态变更通知使用 Observer 模式

### 性能优化参考

- **连接池**：数据库、Redis、Milvus 都使用连接池
- **批量操作**：向量写入、日志写入使用批量 API
- **异步 I/O**：所有 I/O 操作使用 async/await
- **缓存策略**：参考 Cache-Aside 模式（Workspace 配置缓存）

### 实现检查清单

在实现每个功能时，开发者（AI）必须：

1. **调研阶段**：搜索是否有成熟的库或工具可以直接使用
2. **评估阶段**：评估库的维护状态、社区活跃度、文档质量
3. **决策阶段**：只有在以下情况才考虑自己实现：
   - 找不到合适的库
   - 现有库不满足核心需求且无法扩展
   - 引入库的复杂度超过自己实现的复杂度
4. **实现阶段**：遵守 SOLID 原则，编写清晰的接口和文档
5. **测试阶段**：编写单元测试，覆盖核心逻辑

### 技术债务管理

- **TODO 注释**：标记临时实现和需要优化的地方
- **技术债务文档**：在 docs/tech-debt.md 记录已知的技术债务
- **重构计划**：定期评估是否需要重构以保持代码质量

## 需求

### 需求 1：多租户身份与认证

**用户故事**：作为平台管理员，我希望支持多个租户组织独立使用平台，以便将系统商业化为 SaaS 产品。

#### 验收标准

1. THE Platform SHALL 支持租户（Tenant）、用户（User）、Agent 三层身份模型
2. WHEN 用户注册时，THE Platform SHALL 要求提供租户标识和用户角色（Admin/Member/Viewer）
3. THE Platform SHALL 使用 JWT 令牌进行身份认证，令牌中包含 tenant_id 和 user_id
4. WHEN API 请求到达时，THE Gateway SHALL 解析 JWT 并将 tenant_id 注入请求上下文
5. THE Platform SHALL 为每个租户生成独立的 API Key 用于 Webhook 接入

### 需求 2：数据隔离

**用户故事**：作为租户管理员，我希望确保我的数据不会被其他租户访问，以便保护企业内部运维知识的安全。

#### 验收标准

1. THE Platform SHALL 在 PostgreSQL 所有核心业务表（sessions、incidents、approvals、token_usage、audit_logs）上启用行级安全策略（RLS）
2. WHEN 数据库查询执行时，THE PostgreSQL SHALL 自动过滤当前 tenant_id 之外的数据行
3. THE Platform SHALL 为每个租户在 Milvus 中创建独立 Partition（命名格式：tenant_{tenant_id}）
4. WHEN 执行向量检索时，THE Platform SHALL 指定当前租户的 partition_names 参数
5. THE Platform SHALL 在 Redis 中使用带租户前缀的 key（格式：session:tenant:{tid}:agent:{aid}:...）
6. WHEN 向量检索返回结果时，THE Platform SHALL 验证每条结果的 tenant_id 与当前请求者一致

### 需求 3：混合部署架构

**用户故事**：作为企业客户，我希望生产环境凭证不离开内网，以便满足安全合规要求。

#### 验收标准

1. THE Platform SHALL 部署控制面（Gateway、Agent Worker、数据库）在云端
2. THE Platform SHALL 支持用户在内网部署 MCP_Server
3. WHEN Agent 需要执行工具调用时，THE Platform SHALL 通过 MCP 协议与用户内网的 MCP_Server 通信
4. THE MCP_Server SHALL 控制暴露给 Agent 的工具范围和权限
5. THE Platform SHALL 不存储用户生产环境的凭证（kubectl token、数据库密码等）

### 需求 4：Session 持久化

**用户故事**：作为 SRE，我希望对话历史在服务重启后仍然可用，以便继续处理中断的事故。

#### 验收标准

1. THE Platform SHALL 使用 Redis 存储热 Session 消息列表（最近对话）
2. THE Platform SHALL 使用 PostgreSQL 存储 Session 元数据（session_key、token_count、last_active）
3. THE Platform SHALL 使用 S3 存储对话 JSONL 归档（冷数据）
4. WHEN Session 超过 24 小时未活跃时，THE Platform SHALL 将消息从 Redis 归档到 S3
5. WHEN 服务重启时，THE Platform SHALL 能够从 PostgreSQL 和 Redis 恢复活跃 Session

### 需求 5：四层上下文 Compaction

**用户故事**：作为平台运营者，我希望减少 token 消耗，以便降低 LLM API 成本。

#### 验收标准

1. THE Platform SHALL 组装四层上下文结构：永久层（Workspace 配置）、摘要层（branch_summary）、近期层（最近 3-5 轮完整对话）、RAG 层（动态检索的 runbook）
2. WHEN 上下文 token 数超过 context_window - 20000 时，THE Platform SHALL 触发 Compaction
3. WHEN Compaction 触发时，THE Platform SHALL 使用 LLM 提炼历史对话的关键信息生成 branch_summary
4. THE Platform SHALL 将 branch_summary 存入 Redis（key: session:{session_key}:summary）
5. THE Platform SHALL 保留最近 3-5 轮完整消息，丢弃更早的消息
6. THE Platform SHALL 在每次 Agent 调用时重新执行 RAG 检索（不缓存检索结果）

### 需求 6：六状态事故处理流程

**用户故事**：作为 SRE，我希望清晰追踪事故处理进展，以便了解当前处于哪个阶段。

#### 验收标准

1. THE Platform SHALL 使用 LangGraph StateGraph 实现六状态流转：TRIGGERED → ANALYZING → AWAITING_APPROVAL → EXECUTING → VERIFYING → RESOLVED
2. WHEN 事故无法自动解决或审批被拒绝时，THE Platform SHALL 转换状态为 ESCALATED
3. THE Platform SHALL 在 PostgreSQL incidents 表记录每次状态转换和时间戳
4. WHEN 状态转换发生时，THE Platform SHALL 通过 Slack 或 Webhook 通知相关人员
5. THE Platform SHALL 在 Dashboard 中实时展示事故当前状态

### 需求 7：高危操作审批

**用户故事**：作为 SRE，我希望高危操作（如重启服务、数据库 failover）需要人工确认，以便避免自动化误操作。

#### 验收标准

1. WHEN Agent 生成的修复方案包含高危操作时，THE Platform SHALL 使用 LangGraph interrupt() 暂停图执行
2. THE Platform SHALL 将图状态序列化写入 PostgreSQL Checkpoint 表
3. THE Platform SHALL 生成 resumeToken（UUID）并写入 PostgreSQL approvals 表和 Redis
4. THE Platform SHALL 向 Slack 发送审批请求消息，包含操作描述和 resumeToken
5. WHEN SRE 确认审批时，THE Platform SHALL 从 Checkpoint 恢复图状态并继续执行
6. THE Platform SHALL 不重新执行已完成的步骤（从 approvals.completed_steps 读取）

### 需求 8：YAML Workflow Engine

**用户故事**：作为 SRE，我希望用 YAML 文件定义操作步骤，以便在不修改 Python 代码的情况下调整修复流程。

#### 验收标准

1. THE Platform SHALL 实现 YAML workflow 解析引擎，支持顺序执行步骤
2. THE Workflow_Engine SHALL 支持 approval gate 步骤类型，触发人工审批
3. WHEN approval 步骤执行时，THE Workflow_Engine SHALL 生成 resumeToken 并暂停执行
4. THE Workflow_Engine SHALL 支持从断点恢复，读取 completed_steps 跳过已完成步骤
5. THE Platform SHALL 提供预置 YAML 模板（service_restart.yaml、database_failover.yaml 等）
6. THE Platform SHALL 支持 LLM 辅助生成 YAML workflow（SRE 提供自然语言描述）

### 需求 9：RAG 多租户隔离

**用户故事**：作为租户管理员，我希望上传的 runbook 只能被本组织的 Agent 检索，以便保护内部运维知识。

#### 验收标准

1. WHEN 租户上传 runbook 时，THE Platform SHALL 将文档切片并写入 Milvus 的租户专属 Partition
2. THE Platform SHALL 在每个 chunk 的 metadata 中记录 tenant_id
3. WHEN 执行向量检索时，THE Platform SHALL 同时指定 partition_names 和 metadata filter（tenant_id = current_tenant）
4. THE Platform SHALL 使用 Hybrid 检索（70% vector + 30% BM25）并通过 RRF 融合排序
5. WHEN 检索结果返回时，THE Platform SHALL 验证所有 chunk 的 tenant_id 与当前请求者一致

### 需求 10：RAG 评估

**用户故事**：作为 AI 工程师，我希望量化评估 RAG 系统质量，以便验证改进效果。

#### 验收标准

1. THE Platform SHALL 使用 RAGAS 框架评估 RAG 系统
2. THE Platform SHALL 维护 100 条 OnCall Q&A 测试集（历史事故问题 + 对应 runbook 答案）
3. THE Platform SHALL 计算 Faithfulness 指标（答案是否基于检索内容，不捏造）
4. THE Platform SHALL 计算 Context Recall 指标（相关内容被召回的比例）
5. THE Platform SHALL 达到 85% 以上的 Faithfulness 分数

### 需求 11：Token 消耗优化

**用户故事**：作为平台运营者，我希望验证 Compaction 相比固定截断的 token 节省效果，以便证明优化价值。

#### 验收标准

1. THE Platform SHALL 实现 A/B 测试框架，对比固定截断 20 轮和四层 Compaction 的 token 消耗
2. THE Platform SHALL 使用 20 个模拟事故对话场景进行测试
3. THE Platform SHALL 记录每次 LLM 调用的 input_tokens 和 output_tokens
4. THE Platform SHALL 计算 Compaction 相比固定截断的 token 减少百分比
5. THE Platform SHALL 达到 70% 以上的 token 减少率

### 需求 12：事故响应时间优化

**用户故事**：作为产品经理，我希望量化 AI Agent 相比人工处理的时间节省，以便证明产品价值。

#### 验收标准

1. THE Platform SHALL 记录每个事故从 TRIGGERED 到 RESOLVED 的完整时长
2. THE Platform SHALL 维护人工处理相同事故类型的基线时间（通过历史数据或专家估算）
3. THE Platform SHALL 计算 AI 处理时间相比人工基线的减少百分比
4. THE Platform SHALL 在 20 个模拟事故场景中达到 80% 以上的时间减少率
5. THE Platform SHALL 在 Grafana Dashboard 展示 per-tenant 的平均事故处理时长

### 需求 13：可观测性 - LangSmith 追踪

**用户故事**：作为 AI 工程师，我希望追踪 Agent 执行链路，以便调试 Agent 行为和优化 prompt。

#### 验收标准

1. THE Platform SHALL 集成 LangSmith，自动上报 LangGraph 图执行 trace
2. THE Platform SHALL 在每个 trace 中注入 tenant_id 和 incident_id 作为 metadata 标签
3. THE Platform SHALL 记录每次 LLM 调用的 prompt 内容、completion 内容、token 消耗和耗时
4. THE Platform SHALL 记录每次 MCP 工具调用的名称、输入参数、返回结果和耗时
5. THE Platform SHALL 记录 Compaction 触发时 branch_summary 的生成过程

### 需求 14：可观测性 - Prometheus 指标

**用户故事**：作为平台管理员，我希望监控系统运行状态和 per-tenant 资源消耗，以便进行计费和容量规划。

#### 验收标准

1. THE Platform SHALL 暴露 /metrics 端点供 Prometheus 抓取
2. THE Platform SHALL 采集以下指标（带 tenant_id 标签）：incident_total（事故总数）、incident_duration_seconds（处理时长）、token_usage_total（token 消耗）、approval_wait_seconds（审批等待时长）、agent_invocations_total（Agent 调用次数）
3. THE Platform SHALL 在 Grafana 中展示 per-tenant 的 token 消耗趋势
4. WHEN 租户 token 消耗超过配额阈值时，THE Platform SHALL 触发告警
5. THE Platform SHALL 不将 session_id 或 incident_id 作为 Prometheus label（避免高基数问题）

### 需求 15：消息路由

**用户故事**：作为系统架构师，我希望根据消息来源和意图路由到不同的 Agent，以便优化处理流程。

#### 验收标准

1. WHEN Webhook 告警到达时，THE Gateway SHALL 直接路由到 AIOps Agent（不经过意图分类）
2. WHEN Slack 对话消息到达时，THE Gateway SHALL 使用 LLM 进行意图分类
3. IF 意图为普通问答，THEN THE Gateway SHALL 路由到 Chat Agent（只读工具集）
4. IF 意图为事故处理请求，THEN THE Gateway SHALL 路由到 AIOps Agent（完整工具集）
5. THE Gateway SHALL 归一化不同来源的消息格式为统一 envelope（sender/content/channel/thread）

### 需求 16：限流与配额

**用户故事**：作为平台管理员，我希望防止单个租户耗尽平台资源，以便保证多租户公平使用。

#### 验收标准

1. THE Platform SHALL 在 Redis 中维护 per-tenant 请求计数器（key: quota:tenant:{tid}:requests:{minute}）
2. WHEN 租户请求到达时，THE Gateway SHALL 检查当前分钟的请求数是否超过配额
3. IF 请求数超过配额，THEN THE Gateway SHALL 返回 429 Too Many Requests 错误
4. THE Platform SHALL 在 PostgreSQL tenants 表记录每个租户的 plan（Free/Pro/Enterprise）和对应配额
5. THE Platform SHALL 支持动态调整租户配额（通过管理后台）

### 需求 17：审计日志

**用户故事**：作为合规审计员，我希望追踪所有高危操作的完整链路，以便满足企业合规要求。

#### 验收标准

1. THE Platform SHALL 在 PostgreSQL audit_logs 表记录所有高危操作（kubectl restart、database failover、配置变更等）
2. WHEN 高危操作执行时，THE Platform SHALL 记录 tenant_id、user_id、action、resource、payload、timestamp
3. THE Platform SHALL 记录审批流程（谁请求、谁审批、审批时间）
4. THE Platform SHALL 提供审计日志查询 API（支持按 tenant、user、时间范围过滤）
5. THE Platform SHALL 保留审计日志至少 1 年

### 需求 18：Workspace 配置管理

**用户故事**：作为租户管理员，我希望自定义 Agent 的人格定义和操作规范，以便适配团队的工作流程。

#### 验收标准

1. THE Platform SHALL 在 PostgreSQL agents.config JSONB 字段存储 Workspace 配置
2. THE Workspace SHALL 包含以下内容：soul（Agent 人格定义）、agents_md（操作规范）、user_md（用户偏好）、tools（可用工具列表）
3. THE Platform SHALL 在 Redis 中缓存 Workspace 配置（key: workspace:{tenant_id}:{agent_id}，TTL 1 小时）
4. WHEN Agent 调用时，THE Platform SHALL 优先从 Redis 读取 Workspace，未命中则从 PostgreSQL 读取
5. THE Platform SHALL 提供 API 允许租户管理员更新 Workspace 配置

### 需求 19：MCP 工具集成

**用户故事**：作为 Agent 开发者，我希望通过标准化协议集成运维工具，以便支持可插拔的工具生态。

#### 验收标准

1. THE Platform SHALL 通过 MCP 协议调用用户内网的 MCP_Server
2. THE MCP_Server SHALL 暴露以下工具：Loki 日志查询、Prometheus 指标查询、kubectl 操作、数据库查询
3. WHEN MCP 工具返回数据时，THE MCP_Server SHALL 返回结构化 JSON 摘要（不返回原始数据流）
4. THE Platform SHALL 支持开发阶段使用 Mock MCP_Server（返回预定义测试数据）
5. THE Platform SHALL 在生产环境支持切换到真实 MCP_Server（通过租户配置）

### 需求 20：Parser 和 Serializer 的 Round-Trip 测试

**用户故事**：作为质量保证工程师，我希望确保所有数据格式的解析和序列化正确无误，以便避免数据损坏。

#### 验收标准

1. WHEN Platform 解析 YAML workflow 文件时，THE YAML_Parser SHALL 将其转换为内部 Workflow 对象
2. WHEN Platform 序列化 Workflow 对象时，THE YAML_Serializer SHALL 将其格式化为有效的 YAML 文件
3. FOR ALL 有效的 Workflow 对象，THE Platform SHALL 满足 round-trip 属性：parse(serialize(obj)) == obj
4. WHEN 解析无效 YAML 文件时，THE YAML_Parser SHALL 返回描述性错误信息
5. THE Platform SHALL 对 JSON 格式的 Workspace 配置实现相同的 round-trip 测试

### 需求 21：扩展性预留

**用户故事**：作为系统架构师，我希望在不重构核心逻辑的情况下支持未来扩展，以便应对规模增长。

#### 验收标准

1. THE Gateway SHALL 支持通过环境变量切换消息传输层（当前：BackgroundTasks，未来：Kafka）
2. THE Platform SHALL 在代码中预留消息队列接口（enqueue/dequeue），当前实现为内存队列
3. WHEN 切换到 Kafka 时，THE Platform SHALL 只需替换传输层实现，不修改 Agent 逻辑
4. THE Platform SHALL 支持 Agent Worker 横向扩展（多实例消费同一队列）
5. THE Platform SHALL 在 Milvus 中预留从 Partition 迁移到独立 Collection 的能力（大客户隔离）

### 需求 22：开发环境 Mock 支持

**用户故事**：作为开发者，我希望在本地环境测试完整流程，以便不依赖真实生产环境。

#### 验收标准

1. THE Platform SHALL 提供 Docker Compose 配置，一键启动 PostgreSQL、Redis、Milvus、Mock MCP_Server
2. THE Mock_MCP_Server SHALL 返回预定义的测试数据（OOM 错误日志、高 error_rate 指标等）
3. THE Platform SHALL 提供 20 个模拟事故对话场景（用于 token A/B 测试）
4. THE Platform SHALL 提供 100 条 Q&A 测试集（用于 RAGAS 评估）
5. THE Platform SHALL 支持通过环境变量 MULTI_TENANT_MODE=false 降级为单租户模式（便于调试）
