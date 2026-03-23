# OnCall Agent Platform — 完整设计文档
> 给 Claude Code 的上下文文档：理解项目全貌、设计决策、改造逻辑、编码指南
> 基于已有简历项目源码进行改造，参考 OpenClaw 架构，实现多租户产品化
> **持续迭代中**

---

## 一、项目定位

### 我们做的是什么

基于一个已有的 OnCall AI Agent 项目进行架构改造，两个目标：
- **简历层**：做出有技术深度的项目，具备真实可量化指标
- **产品层**：从单团队内部工具改造成多租户 SaaS 产品，面向真实用户

核心价值链：
```
告警触发 → Agent 自动分析日志和监控 → 检索相关 runbook
        → 生成修复方案 → SRE 确认 → 执行修复 → 验证恢复
```

### 原有项目是什么

已有一个 Python 实现的 OnCall AI Agent 系统：
- LangGraph 实现的 ReAct Chat Agent + Plan-Execute AIOps Agent
- Milvus 向量数据库 + hybrid BM25+vector 检索的 RAG pipeline
- MCP 协议集成 Prometheus、Loki、PostgreSQL 等运维工具
- SSE 流式输出，保留最近20轮对话历史（内存列表）
- LangSmith 可观测性追踪

**原版根本问题**：这是一个单用户脚本，不是产品。没有用户概念、没有租户概念、没有权限体系、session 存在内存里重启即丢失、RAG 无租户隔离。

### 改造原则

**叠加而非替换**：原有 LangGraph Agent 逻辑、RAG pipeline、MCP 工具集成全部保留，在外层叠加新的架构层。每一层改造都有明确的问题要解决。

### 参考来源：OpenClaw

改造思想主要参考 OpenClaw（开源个人 AI Agent 平台，310k+ GitHub Stars，Node.js 实现）。我们不直接使用，而是理解其设计原理，用 Python 重新实现工业级版本。

**为什么不直接用 OpenClaw**：Node.js 单用户系统，无多租户，无 Python 生态支持，创始人已加入 OpenAI 后项目治理不确定。

| OpenClaw 原版 | 我们的实现 | 改进点 |
|-------------|---------|-------|
| Gateway 消息归一化路由 | FastAPI Gateway + Slack/Webhook 接入 | 加 tenant_id 识别，解耦接收和处理 |
| Session 两层存储（sessions.json + JSONL） | Redis（热）+ PostgreSQL（索引）+ S3（归档） | 多实例共享，持久化可靠 |
| Compaction + branch_summary | 4层上下文组装 | 加 RAG 动态注入层，tenant 隔离 |
| Workspace 文件（SOUL.md/AGENTS.md） | PostgreSQL JSONB + Redis 缓存 | 结构化存储，多租户隔离 |
| Lobster YAML workflow + resumeToken | Python 重实现的 YAML workflow engine | 支持 Python async 函数，接入 PG approvals 表，LLM 辅助生成 |

---

## 二、系统架构

### 部署模式：混合架构

```
┌─────────────────────────────────────────┐
│           我们的平台（云端）              │
│                                         │
│  Slack Bot / Webhook 接入               │
│  FastAPI Gateway（无状态，可横向扩展）    │
│  Agent Worker Pool                      │
│  PostgreSQL / Redis / Milvus / S3       │
│  LangSmith + Prometheus Dashboard       │
└──────────────┬──────────────────────────┘
               │ MCP 协议
               │ （标准化工具调用接口）
┌──────────────▼──────────────────────────┐
│           用户内网（用户自己部署）         │
│                                         │
│  MCP Server（用户控制工具暴露范围）        │
│     ├── Prometheus / Loki              │
│     ├── kubectl                        │
│     └── 内部数据库 / 告警系统            │
│                                         │
│  生产环境服务器                          │
└─────────────────────────────────────────┘
```

**为什么混合部署**：企业不会把 kubectl 权限交给第三方 SaaS。用户通过 MCP Server 自己控制工具授权范围，生产环境凭证永远不离开用户内网。

### 各模块运行位置

| 模块 | 位置 | 原因 |
|------|------|------|
| FastAPI Gateway | 我们的云端 | 无状态，可横向扩展 |
| Agent Worker | 我们的云端 | 消费队列，处理 LangGraph 图 |
| PostgreSQL | 我们的云端 | session 元数据、审批记录、token 用量 |
| Redis | 我们的云端 | 热 session 缓存、限流计数器 |
| Milvus | 我们的云端 | 向量检索，per-tenant Partition 隔离 |
| S3 | 我们的云端 | 对话 JSONL 归档、runbook 原文 |
| MCP Server | 用户内网 | 工具执行必须在内网，保护生产环境凭证 |
| LangSmith | Anthropic 云端 | Agent 追踪，外部 SaaS |
| Prometheus + Grafana | 我们的云端 | per-tenant 指标监控 |

### 目录结构

```
oncall-platform/
├── gateway/                    # OpenClaw-inspired Gateway 层
│   ├── server.py              # FastAPI 入口
│   ├── router.py              # 消息路由（tenant+agent+user 解析）
│   ├── session.py             # Session 生命周期管理
│   └── middleware.py          # JWT 解析 + tenant 上下文注入
│
├── agents/                     # LangGraph Agent 层（保留原有，加 tenant 参数）
│   ├── chat_agent.py          # ReAct Chat Agent（保留原有逻辑）
│   ├── aiops_agent.py         # Plan-Execute AIOps StateGraph（重构为6状态）
│   └── supervisor.py          # 路由判断（Chat vs AIOps）
│
├── memory/                     # 记忆层
│   ├── session_store.py       # Redis + PostgreSQL Session 存储
│   ├── vector_store.py        # Milvus（tenant Partition 隔离）
│   └── compaction.py          # 4层上下文 Compaction
│
├── workflow/                   # Lobster-lite 工作流引擎
│   ├── engine.py              # YAML pipeline 执行引擎
│   ├── approval.py            # resumeToken 审批门
│   └── runbooks/              # *.yaml 工作流定义
│
├── tools/                      # MCP 工具集成（保留原有）
│   └── mcp_client.py          # MCP 协议调用封装
│
├── auth/                       # 认证层
│   ├── jwt.py
│   └── rbac.py
│
├── storage/                    # 存储层
│   ├── models.py              # SQLAlchemy 数据模型
│   └── migrations/
│
├── evaluation/                 # 指标采集（产生简历数字）
│   ├── ragas_eval.py          # RAGAS 评估
│   ├── token_benchmark.py     # Compaction A/B 测试
│   └── mock_incidents.py      # 测试用模拟事故数据
│
└── api/                        # 对外 REST API
    └── routes/
```

---

## 三、完整数据流

### 一次 P0 事故从触发到解决

```
步骤1：告警触发
PagerDuty / Alertmanager / Slack 告警
      │ Webhook POST（携带 tenant API Key）
      ▼

步骤2：Gateway 接收（毫秒级，轻操作）
FastAPI /webhook/alert
- 解析 JWT，识别 tenant_id
- 归一化消息格式（统一 envelope：sender/content/channel/thread）
- 限流检查（Redis：quota:tenant:{tid}:requests:{minute}）
- PostgreSQL incidents 表创建记录，state = TRIGGERED
- 推入 BackgroundTasks（当前实现）/ Redis Stream（扩展时替换）
      │
      ▼

步骤3：路由判断（轻量，毫秒级）
- Webhook 告警 → 直接触发 AIOps Agent（不经过 Chat Agent）
- Slack 对话 → 意图分类
  ├── 普通问答 → Chat Agent（只读工具集）
  └── 事故处理请求 → AIOps Agent（完整工具集）
      │
      ▼

步骤4：Agent Worker 消费
- 从队列取出消息
- 查 Redis 缓存获取 workspace 配置（TTL 1小时）
  └── 未命中 → 从 PostgreSQL agents.config JSONB 读取
- 创建 LangGraph 图实例（传入 tenant_id + incident_id）
      │
      ▼

步骤5：4层上下文组装（Compaction）
Layer 1 永久层：workspace 配置（SOUL/AGENTS/USER）
Layer 2 摘要层：Redis branch_summary（上次压缩的历史摘要）
Layer 3 近期层：Redis 最近3-5轮完整消息
Layer 4 RAG层：Milvus 检索相关 runbook（partition: tenant_{tid}）
      │
      ▼

步骤6：LangGraph StateGraph 执行
state: TRIGGERED → ANALYZING

analyze_node（并行执行）：
├── MCP 调用 Loki：拉取最近30分钟错误日志 → 结构化 JSON 摘要
├── MCP 调用 Prometheus：查询 error_rate 等指标
└── Milvus 检索：搜索相关 runbook chunk

plan_node：
- LLM 综合以上信息，生成修复方案
- 判断操作风险等级
  ├── 低风险（只读、查询）→ 直接进入 execute_node
  └── 高风险（kubectl restart / rollback / db failover）→ 进入审批流
      │
      ▼

步骤7：人工审批（高危操作）
state: ANALYZING → AWAITING_APPROVAL

- LangGraph interrupt_before=["wait_for_approval"] 硬停止
- 图状态序列化写入 PostgreSQL Checkpoint（事务保证原子性）
- YAML workflow engine 创建 approval 记录，生成 resumeToken（UUID）
- 写入 PostgreSQL approvals 表（tenant_id + incident_id + token + completed_steps）
- 同时写入 Redis（快速查询）
- 向 Slack 发送审批请求："建议重启 payment-service，原因：OOM，请确认"
      │
      │  SRE 在 Slack 或 Dashboard 点击确认（可能10分钟后）
      ▼

步骤8：审批恢复
- API 收到 approve 请求，验证 resumeToken
- 从 PostgreSQL approvals 表取 completed_steps（已完成步骤结果）
- 从 PostgreSQL Checkpoint 恢复 LangGraph 图状态
- 继续执行（不重跑已完成步骤）
state: AWAITING_APPROVAL → EXECUTING
      │
      ▼

步骤9：YAML Workflow 执行（用户内网）
workflow: service_restart.yaml 步骤顺序执行：
  step 1: fetch_logs   → MCP Loki（已完成，从 checkpoint 取）
  step 2: analyze      → LLM（已完成）
  step 3: confirm      → approval gate（已通过）
  step 4: kubectl_restart → MCP Server（用户内网执行）
  step 5: health_check → 等待60秒，验证服务恢复
      │
      ▼

步骤10：验证与关闭
state: EXECUTING → VERIFYING → RESOLVED

- 验证服务健康检查通过
- incidents 表 state = RESOLVED，记录 resolved_at
- 写入 audit_log：完整操作链路记录
- Slack 发送结果："payment-service 已恢复，耗时 8 分钟"
- LangSmith 记录完整 trace
- Prometheus 更新 per-tenant 指标（incident_duration、token_usage）
```

### 上下文超限时的 Compaction 触发

```
每轮对话结束后检查：
context_tokens > context_window - 20000（RESERVE_TOKENS）？
      │ 是
      ▼
Memory Flush（静默执行，不发消息给用户）：
- LLM 提炼当前历史中的关键信息（告警原文、诊断结论、已执行操作）
- 写入 Milvus 长期记忆（tenant Partition）
- 生成 branch_summary 文本
- 存入 Redis：session:{session_key}:summary
- 保留最近3-5轮完整消息
- 更新 Redis：session:{session_key}:compaction_count + 1
```

---

## 四、多租户设计

### 身份模型

```
Tenant（工程组织）
  └── User（工程师）role: Admin / Member / Viewer
       └── Agent（AI Agent 实例，有独立 workspace 配置）
```

所有核心业务表（sessions、incidents、approvals、token_usage、audit_logs）都有 tenant_id 外键。

### 数据隔离三层

**PostgreSQL RLS（Row-Level Security）**

每张核心表开启行级安全策略：
```sql
CREATE POLICY tenant_isolation ON incidents
    USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

JWT 中间件解析 tenant_id，注入数据库连接上下文。数据库自动在所有查询加过滤，应用层即使漏写 WHERE 条件，数据库层也不会泄漏。

**连接池注意点**：连接复用时必须正确清除 `app.tenant_id` 上下文，在 ORM 层统一处理，这是实现细节不是放弃 RLS 的理由。

**Milvus Partition**

每个租户一个 Partition（`tenant_{tid}`），查询时指定 `partition_names`，物理隔离。选 Partition 不选 Collection：Collection 管理成本高，Partition 更轻量，索引统一维护。

**Redis Key 前缀**

所有 key 带 tenant 前缀：`session:tenant:{tid}:agent:{aid}:...`

### PostgreSQL 核心数据模型

```
tenants (id, name, plan, created_at)
users (id, tenant_id, email, role, hashed_password)
agents (id, tenant_id, name, config JSONB)
  └── config 存 workspace：{soul, agents_md, user_md, tools}

sessions (id, tenant_id, agent_id, user_id, session_key, token_count, last_active)
  session_key 格式：tenant:{tid}:agent:{aid}:{channel}:{user_id}

incidents (id, tenant_id, session_id, state, severity, metadata JSONB, created_at, resolved_at)
  state: triggered/analyzing/awaiting_approval/executing/verifying/resolved/escalated

approvals (id, tenant_id, incident_id, resume_token, action, action_payload JSONB,
           completed_steps JSONB, status, requested_by, approved_by, created_at)

token_usage (id, tenant_id, agent_id, session_id, model, input_tokens, output_tokens, created_at)

audit_logs (id, tenant_id, user_id, action, resource, payload JSONB, created_at)
```

---

## 五、记忆系统

### 存储分层

| 存储 | 存什么 | 不存什么 |
|------|-------|---------|
| PostgreSQL | session 元数据、token 用量、审批记录、audit log | 消息内容本身 |
| Redis | 热 session 消息列表、branch_summary、workspace 缓存、限流计数 | 永久数据 |
| S3 | 对话 JSONL 归档（大文件）、runbook 原文 | workspace 配置（几KB，存 PG） |
| Milvus | runbook embedding，per-tenant Partition | 原始文档 |

**Workspace 文件存 PostgreSQL JSONB，不存 S3**：几KB配置文件不需要对象存储，JSONB 查询更直接，事务保证原子性。

### 4层上下文组装

```
Layer 1 — 永久层（每次都在）
  来源：PostgreSQL agents.config JSONB
  缓存：Redis workspace:{tenant_id}:{agent_id}（TTL 1小时）
  内容：Agent 人格定义 / 操作规范 / 用户偏好

Layer 2 — 摘要层（历史压缩后的精华）
  来源：Redis session:{session_key}:summary
  内容：LLM 生成的 branch_summary，保留关键事故信息

Layer 3 — 近期层（最近3-5轮完整对话）
  来源：Redis session:{session_key}:messages（LIST）
  不压缩，保留完整细节

Layer 4 — RAG 层（动态注入，每次重新检索）
  来源：Milvus 按当前 query 检索（指定 tenant partition）
  不缓存，每次请求重新检索
```

**为什么比固定截断20轮好**：截断无差别丢弃早期内容，早期记录的告警原文、初始诊断可能被截掉，导致 Agent 后续决策错误。Compaction 压缩前先提炼摘要，关键信息保留在 Layer 2，不丢失。

---

## 六、事故状态机

### 6状态 StateGraph

```
TRIGGERED → ANALYZING → AWAITING_APPROVAL → EXECUTING → VERIFYING → RESOLVED
                              ↓ 拒绝/超时              ↓ 失败
                          ESCALATED                ESCALATED
```

每个状态转换写入 PostgreSQL incidents 表，SRE 可实时查看事故进展。

### LangGraph Checkpoint

选 PostgreSQL 不选 Redis：Redis 持久化有窗口期，极端情况可能丢数据。PostgreSQL WAL 每次事务写盘，Checkpoint 数据丢了需要重来，必须用更可靠的存储。

**服务 down 了怎么恢复**：
1. incidents 表记录当前 state（粗粒度业务状态）
2. LangGraph Checkpoint 记录图执行位置（细粒度技术状态）
3. 重启后查未完成事故，用 Checkpoint 恢复图，从断点继续
4. Checkpoint 用事务写入，要么完整要么回滚，不存在中间状态

---

## 七、YAML Workflow Engine

### 使用者分层是核心理由

- **AI 工程师**：写 LangGraph Python 代码，维护 Agent 逻辑
- **SRE / 运维**：定义操作步骤，审核修复方案，不写 Python

SRE 修改"重启前先检查数据库连接"这个步骤，不应该改 Python 代码，应该改 YAML 文件。YAML 可读、可审核、可用 git 版本控制、可让 LLM 辅助生成。

**LLM 辅助生成 YAML**：SRE 描述需求（自然语言），LLM 生成 YAML pipeline，SRE 审核确认后使用。不需要手写。

### Lobster-lite vs LangGraph interrupt() 分工

**不是重复，是不同层次**：

| | LangGraph interrupt() | Lobster-lite approval gate |
|--|----------------------|--------------------------|
| 层次 | 图执行层（宏观） | 步骤执行层（微观） |
| 使用者 | 开发者 / 系统 | SRE |
| 问题 | "要不要执行这个修复方案" | "确认重启 payment-service" |
| 暂停粒度 | 整个 Agent 图 | 单个操作步骤 |

### resumeToken 持久化

```
approval 步骤触发
      ↓
生成 resumeToken（UUID）
同时写入：
  - Redis（快速查询，TTL 24小时）
  - PostgreSQL approvals 表（持久化，含 completed_steps）
      ↓
SRE 审批
      ↓
从 PostgreSQL 取 completed_steps
从断点继续，不重跑已完成步骤
```

### 为什么不用 Temporal / Airflow

- **Temporal**：需独立部署 Go 服务，LangGraph Checkpoint 已解决持久化，引入是两套机制重叠
- **Airflow**：批处理工具，不适合实时事件驱动场景
- **自实现**：200-300行 Python，刚好够用，每行可解释，原版 Lobster 是 shell 命令，我们需要 Python async 函数

---

## 八、RAG Pipeline

### 改造重点

原版问题：单 Collection 无隔离（安全漏洞）+ 无评估指标。

### Milvus 多租户隔离策略

**Milvus 四层隔离强度**（官方文档明确）：
```
Database > Collection > Partition > Partition Key
隔离强度递减，扩展性递增
```

**我们的选择：Partition 起步，大客户迁 Collection**

当前实现：每个租户一个 Partition（`tenant_{tid}`），查询时指定 `partition_names`。

选 Partition 而不是 Collection 的理由（MVP 阶段）：
- 所有租户 schema 一致，统一索引配置
- 管理成本低，适合快速上线
- 几十到一两百家企业规模完全够用

**Partition 的真实局限（需要知道）**：
- 单 Collection 最多 1024 个 Partition，租户规模增长会撞上限
- 隔离强度低于 Collection，是"同一大池子里的分仓"，不是物理边界
- 安全不能只靠"传 partition_names"这种软约束

**因此无论用哪种隔离，应用层 tenant_id 强制过滤是 invariant**：
- ingest 时写入 tenant_id 字段
- 查询时强制 `tenant_id = current_tenant`（元数据过滤）
- Partition 只是额外防线，不是唯一防线
- 返回结果后做 tenant consistency check

**演进路径**：
- 普通客户：共享 Collection + Partition 隔离
- 大客户 / 高敏感客户：独立 Collection（独立建索引、独立删库、独立合规审计）
- 极高合规要求（金融/医疗）：独立 Database

OnCall 场景数据特别敏感（内部架构、故障复盘、数据库表结构、恢复脚本），串租户不只是"搜错了"，是直接泄露企业内部运维知识，所以隔离策略需要 hard isolation mindset。

### Hybrid 检索

- Vector（70%）：cosine 相似度，语义匹配
- BM25（30%）：精确关键词，适合服务名/错误码
- RRF Fusion 合并排序

**MCP 工具返回结构化 JSON，不返回原始数据**：参考 OpenClaw 语义快照原则，日志查询返回结构化摘要而不是原始日志流，降低 Token 消耗。

### RAGAS 评估

100条 OnCall Q&A 测试集（历史事故→问题，对应 runbook→答案），评估：
- Faithfulness：答案是否基于检索内容，不捏造
- Context Recall：相关内容被召回的比例

---

## 九、可扩展性

### 当前规模判断

OnCall 是低并发高可靠性场景，平台上100家公司同时处理的事故通常个位数。FastAPI + PostgreSQL + Redis 完全够用。

### 扩展路径（预留接口，按需实现）

**Gateway 层解耦**（当前：BackgroundTasks，扩展：Kafka）：
```
当前：FastAPI → BackgroundTasks → Agent Worker（同进程）
扩展：FastAPI → Kafka topic → Agent Worker Pool（独立进程，可横向扩）
```

接口层不动，只替换传输层。极端故障（AWS down）时 Kafka 做削峰，避免 LLM API rate limit 被打爆。

---

---

## 九点五、可观测性设计

> 可观测性分两层，解决两个不同的问题：
> - **LangSmith**：Agent 行为调试——"Agent 为什么这么做"
> - **Prometheus**：系统运行监控——"系统整体运行得怎么样"
>
> 两者不重叠，必须同时存在。

---

### LangSmith

**是什么**：Anthropic 官方提供的 LLM 应用追踪平台（云端 SaaS），专门用于记录和分析 LangChain/LangGraph 应用的完整调用链路。

**部署方式**：无需自己部署，直接使用 Anthropic 云端服务。在环境变量里配置 `LANGCHAIN_API_KEY` 和 `LANGCHAIN_TRACING_V2=true`，LangGraph 会自动上报 trace。我们不需要在代码里显式调用 LangSmith SDK，框架层面自动集成。

**负责哪块**：Agent 执行链路的完整追踪，面向开发者调试。

**接什么数据**：
- 每次 LangGraph 图执行的完整 trace（从收到消息到返回结果）
- 每个 StateGraph 节点的输入输出（analyze_node / plan_node / execute_node 等）
- 每次 LLM 调用：prompt 内容、completion 内容、token 消耗、耗时
- 每次工具调用：MCP 工具名称、输入参数、返回结果、耗时
- Compaction 触发时 branch_summary 的生成过程
- 每个 trace 打上 `tenant_id` 和 `incident_id` 的 metadata 标签

**per-tenant 的挑战**：LangSmith 默认没有 tenant 维度。需要在每次 Agent 调用时手动注入 tenant_id 作为 metadata，确保 trace 可以按租户过滤查询。这是需要在 Agent Worker 层统一处理的地方，不能依赖各个节点自己去加。

**使用场景**：
- 调试"Agent 为什么跳过了某个步骤"
- 分析某次事故处理中 LLM 的推理过程
- 排查 Compaction 后上下文是否正确保留了关键信息
- 对比不同 prompt 版本的效果

---

### Prometheus + Grafana

**是什么**：开源的指标采集和可视化系统。Prometheus 负责存储时序指标数据，Grafana 负责可视化展示。

**部署方式**：部署在我们自己的云端，和 FastAPI Gateway、Agent Worker 同一个基础设施环境。

数据流向：
```
FastAPI / Agent Worker
    │ 暴露 /metrics 端点（prometheus_client 库）
    ▼
Prometheus Server（定时 scrape /metrics 端点，默认15秒一次）
    ▼
Grafana Dashboard（查询 Prometheus，可视化展示）
```

Prometheus 是**拉取模式**（pull-based）——不是应用主动推数据给 Prometheus，而是 Prometheus 定期来拉取。应用只需要暴露一个 `/metrics` HTTP 端点，格式符合 Prometheus 规范即可。

**负责哪块**：业务层面的聚合指标，面向运营监控和 per-tenant 计费。

**接什么数据（核心指标）**：

| 指标名 | 类型 | 标签 | 含义 |
|--------|------|------|------|
| `incident_total` | Counter | tenant_id, severity | 各租户事故总数 |
| `incident_duration_seconds` | Histogram | tenant_id, state | 事故各阶段处理时长 |
| `token_usage_total` | Counter | tenant_id, model, agent_type | 各租户 token 消耗（计费依据） |
| `approval_wait_seconds` | Histogram | tenant_id | 审批等待时长 |
| `agent_invocations_total` | Counter | tenant_id, agent_type, status | Agent 调用次数和成功率 |
| `rag_retrieval_latency_seconds` | Histogram | tenant_id | RAG 检索延迟 |
| `compaction_triggered_total` | Counter | tenant_id | Compaction 触发次数 |
| `session_active` | Gauge | tenant_id | 当前活跃 session 数 |

**高基数注意点**：每个指标都带 tenant_id 标签。租户数量增多时，label 组合数量（cardinality）会增加，需要注意不要把 session_id、incident_id 这类高基数字段直接放进 label——这会让 Prometheus 存储爆炸。tenant_id 是可控的（几十到几百），放进 label 没问题。

**使用场景**：
- 查看各租户本月 token 消耗，作为计费依据
- 监控事故平均处理时长，检测系统性能退化
- 设置告警：某租户 token 消耗超过配额阈值时触发通知
- Grafana Dashboard 展示平台整体健康状态

---

### 两层对比

| | LangSmith | Prometheus + Grafana |
|--|-----------|---------------------|
| 部署位置 | Anthropic 云端 SaaS | 我们自己的云端 |
| 数据接入方式 | 框架自动上报（环境变量配置） | 应用暴露 /metrics 端点，Prometheus 定时拉取 |
| 数据粒度 | 单次调用级别（每个 trace） | 聚合指标（计数、分布、总量） |
| 主要使用者 | AI 工程师（调试） | 运营 / 平台管理员（监控） |
| 回答的问题 | Agent 为什么这么做 | 系统整体运行得怎么样 |
| per-tenant 支持 | 手动注入 metadata 标签 | 指标 label 自带 tenant_id |
| 数据保留 | LangSmith 平台管理 | Prometheus 自配（默认15天） |

---

### 面试深问应对

**"你们的可观测性怎么做的？"**
> 分两层。LangSmith 追踪 Agent 执行链路——每次 LLM 调用的 prompt 和输出、工具调用参数、每个节点耗时，主要用于调试，每个 trace 打 tenant_id 标签可以按租户过滤。Prometheus 采集业务层聚合指标——各租户事故数量、处理时长、token 消耗，用于运营监控和计费。两层解决的问题不同：LangSmith 回答"Agent 为什么这么做"，Prometheus 回答"系统整体运行得怎么样"。

**"per-tenant 可观测性有什么挑战？"**
> LangSmith 默认没有 tenant 维度，需要在 Agent Worker 层统一注入 tenant_id 作为 metadata，不能依赖各节点自己加。Prometheus 这边要注意高基数问题——tenant_id 放进 label 没问题（数量可控），但 session_id、incident_id 这类无限增长的字段不能放进 label，否则 Prometheus 存储会爆炸。

**"LangSmith 和直接看日志有什么区别？"**
> 日志是平铺的文本，LangSmith 是结构化的调用树。一次事故处理可能涉及10次 LLM 调用、5次工具调用，LangSmith 把它们组织成有层级的 trace，可以直接看到哪一步耗时最长、哪次 LLM 输出导致了后续的错误决策。调试 Agent 行为比翻日志效率高得多。

**"Prometheus 是推模式还是拉模式？"**
> 拉模式。应用暴露 /metrics 端点，Prometheus 定时 scrape（默认15秒）。好处是应用不需要知道 Prometheus 在哪里，部署解耦；缺点是采集有延迟，不适合需要实时推送的场景。我们的监控场景对15秒延迟完全可以接受。

## 十、改造对比清单（给 CC 编码用）

### 原版状态 → 改造方向

| 模块 | 原版代码状态 | 改造方向 | 关键文件 |
|------|------------|---------|---------|
| 入口 | 单 FastAPI 端点，同步调用 Agent | 加 JWT 中间件，tenant_id 注入，异步路由 | gateway/middleware.py, gateway/router.py |
| Session | `chat_history = []` 内存列表 | Redis LIST + PostgreSQL session 索引 | memory/session_store.py |
| 上下文 | `history[-20:]` 固定截断 | 4层 Compaction，branch_summary | memory/compaction.py |
| RAG | `collection.search(data=[embedding])` | 加 `partition_names=[tenant_partition]` | memory/vector_store.py |
| Agent | 无 tenant 参数 | 所有函数签名加 `tenant_id: str` | agents/chat_agent.py, agents/aiops_agent.py |
| 状态机 | plan → execute 两步 | 6状态 StateGraph + interrupt() + PG Checkpoint | agents/aiops_agent.py |
| 工具 | LangChain Tool wrapper | MCP Server 包装，可插拔 | tools/mcp_client.py |
| 工作流 | 无 | YAML pipeline engine + resumeToken | workflow/engine.py |
| 数据模型 | 无 tenant 概念 | PostgreSQL 建表 + RLS 策略 | storage/models.py, storage/migrations/ |
| 评估 | 无 | RAGAS + A/B token benchmark | evaluation/ |

### 改造优先级

**P0（先做，产生简历数字）**
1. `storage/models.py` — 数据模型 + RLS
2. `gateway/middleware.py` — JWT + tenant 注入
3. `memory/vector_store.py` — Milvus 加 partition_names（一行关键改动）
4. `evaluation/ragas_eval.py` — 跑出 85%+ 数字
5. `memory/compaction.py` — 跑出 70% token 对比数字

**P1（架构深度）**
6. `agents/aiops_agent.py` — 6状态机 + interrupt() + PG Checkpoint
7. `workflow/engine.py` — YAML engine + resumeToken
8. `memory/session_store.py` — Redis Session

**P2（完整度）**
9. `auth/rbac.py` — 权限控制
10. `api/routes/approvals.py` — 审批接口
11. `api/routes/metrics.py` — Prometheus per-tenant 指标
12. Slack 接入
13. `evaluation/token_benchmark.py` + `evaluation/response_time.py`

### 改造注意事项

- **不删除原有 Agent 逻辑**，只在外层包装 tenant_id
- 通过环境变量 `MULTI_TENANT_MODE=false` 可降级为单租户模式，便于开发调试
- 原有 MCP 工具集成保留，在调用层加 tenant 上下文
- LangSmith 追踪保留，在每个 Agent 调用加 tenant 标签

---

## 十一、本地开发环境

### Mock MCP Server（开发阶段替代真实工具）

开发时不需要真实的 k8s 集群和监控系统，本机起一个 Mock MCP Server：

```
本机 Docker Compose 服务：
├── PostgreSQL（port 5432）
├── Redis（port 6379）
├── Milvus（port 19530）
└── Mock MCP Server（port 8001）
    ├── GET /loki/query    → 返回写死的错误日志 JSON
    ├── GET /prometheus    → 返回写死的 error_rate 数据
    └── POST /kubectl      → 返回 "操作成功"（不真实执行）
```

**Mock 数据设计原则**：
- Loki 返回：包含 OOM 错误、stack trace 的结构化 JSON
- Prometheus 返回：error_rate 高于阈值的指标数据
- kubectl 返回：操作成功的确认信息

这样可以：
- 构造任意事故场景测试 Agent 行为
- 跑 RAGAS 评估（不需要真实数据）
- 跑 Compaction A/B 测试
- 测试 interrupt() 审批流程

**MCP 的价值在这里体现**：开发用 Mock Server，生产换真实 Server，Agent 代码不动。

### 测试数据构造

```
evaluation/mock_incidents.py 提供：
- 20个模拟事故对话（用于 token A/B 测试）
- 100条 Q&A 测试集（用于 RAGAS 评估）
- 标准事故场景：OOM / CrashLoopBackOff / 数据库连接失败 / 网络超时
```

### 环境变量配置

```
# 必须配置
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
MILVUS_HOST=localhost
JWT_SECRET=your-secret
ANTHROPIC_API_KEY=...

# 开发模式
MULTI_TENANT_MODE=true
MCP_SERVER_URL=http://localhost:8001  # 开发时指向 Mock Server
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=...

# 生产时 MCP_SERVER_URL 由每个租户配置，不是全局变量
```

---

## 十二、量化指标产生方法

| 指标 | 测量方法 | 产出文件 |
|------|---------|---------|
| 85%+ answer faithfulness | RAGAS 评估：100条 Q&A 测试集，跑 faithfulness + context_recall | evaluation/ragas_eval.py |
| 70% token reduction | A/B benchmark：20个对话，固定截断 vs 4层 Compaction，记录 token 差值 | evaluation/token_benchmark.py |
| 80%+ incident response reduction | 基准测试：20个模拟事故场景，AI 处理时间 vs 人工估算基线 | evaluation/response_time.py |

**所有数字来自代码运行，不是估算**。面试被追问方法论时能完整回答。

---

## 十三、面试深问应对

**"租户是什么，你们系统里租户是谁？"**
> 租户是需要 OnCall Agent 的工程组织。他们上传自己的内部 runbook，接入告警系统，有自己的 SRE 团队审批高危操作。不同租户数据完全隔离，共用同一套平台基础设施。

**"怎么保证 A 公司看不到 B 公司数据？"**
> 三层隔离：PostgreSQL RLS 数据库层强制过滤，Milvus Partition 向量检索物理隔离，Redis key 前缀缓存逻辑隔离。即使应用层漏写过滤条件，数据库层也不会泄漏。

**"Compaction 和截断20轮有什么区别？"**
> 截断无差别丢弃早期内容，告警原文和初始诊断可能丢失，导致 Agent 后续决策错误。Compaction 压缩前先让 LLM 提炼摘要，4层结构让关键配置、历史摘要、最新对话、相关文档各司其职，节省约70% token 同时不丢关键信息。

**"interrupt() 和普通 human-in-the-loop 有什么区别？"**
> 普通实现返回响应、下次重新调用，已执行的工具结果丢失。LangGraph interrupt() + PostgreSQL Checkpoint 把图状态序列化写库，服务重启后从精确断点继续，已完成步骤不重跑。

**"服务 down 了进行中的事故怎么办？"**
> 两层保障：incidents 表记录粗粒度业务状态，LangGraph Checkpoint 记录细粒度图执行位置。重启后查未完成事故，用 Checkpoint 恢复，不需要重新触发告警。Checkpoint 用 PostgreSQL 事务写入，不存在中间状态。

**"为什么要 YAML workflow engine，LangGraph interrupt() 不够吗？"**
> 两者不同层次：interrupt() 是图层面的宏观决策（要不要执行方案），YAML workflow 是操作层面的确定性执行（具体步骤顺序）。更重要的是使用者分层——SRE 不应该改 Python 代码来修改操作步骤，他们需要能读懂、能修改、能让 LLM 生成的 YAML 文件。

**"为什么不用 Temporal？"**
> Temporal 需要独立部署 Go 服务，LangGraph Checkpoint 已解决持久化，引入是两套机制解决同一问题。Airflow 是批处理工具不适合实时场景。自实现200-300行 Python 刚好够用。

**"用户怎么授权你们访问生产环境？"**
> 混合部署：平台提供控制面，用户在自己内网部署 MCP Server，暴露有限工具接口。生产凭证不离开内网，我们通过 MCP 协议调用工具，用户自己控制授权范围。

**"能扛住大规模使用吗？"**
> OnCall 天生低并发，当前架构够用。Gateway 层接收和处理解耦，需要时把 BackgroundTasks 换成 Kafka，Worker 横向扩展，接口层不动。极端故障时 Kafka 削峰，避免 LLM API rate limit 被打爆。

**"Multi-Agent 路由会不会增加延迟？"**
> 路由轻量——Webhook 告警直接触发 AIOps Agent，不经过 Chat Agent。Slack 对话意图分类是毫秒级操作。P0 告警进来直接走 AIOps，无冗余路由。

**"MCP 在你们系统里具体怎么工作的？"**
> 我们把 Prometheus、Loki、kubectl 包装成 MCP Server 部署在用户内网，Agent 通过 MCP 协议调用。价值是可插拔——用户换监控系统只需替换 MCP Server 实现，Agent 代码不改。开发阶段用 Mock MCP Server，生产时换真实实现，这就是接口标准化的价值。

**"OpenClaw 有 Device Node 可以直接让 Agent 执行命令，你们为什么用 MCP 而不是这种方式？"**
> 两种设计解决的是不同场景的问题。OpenClaw 的 Device Node 是"Agent 控制用户的个人设备"——Mac、手机通过 WebSocket 注册到 Gateway，Agent 可以直接发指令执行 shell 命令，适合个人用户信任自己 Agent 的场景。我们的场景是企业生产环境，"Agent 直接执行 shell 命令"在这里是安全噩梦——没有审批、没有审计、没有权限边界。MCP 的价值正好在于：用户内网的 MCP Server 决定暴露哪些工具、每个工具有什么参数约束，Agent 调用的是"有明确接口的工具"而不是"任意命令"。配合我们的 interrupt() 审批和 audit_log，每个操作都有迹可查。

**"你们 Milvus 为什么用 Partition 而不是每个租户一个 Collection？"**
> Milvus 官方明确了四层隔离强度：Database > Collection > Partition > Partition Key。我们用 Partition 是 MVP 阶段的务实选择——租户数不多、schema 一致、管理成本低。但 Partition 有 1024 个的上限，隔离强度也低于 Collection，所以我们的架构设计了演进路径：普通客户用 Partition，大客户或高敏感客户迁到独立 Collection。无论哪种隔离方式，应用层 tenant_id 强制过滤是 invariant——查询时必须加 metadata filter，不能只靠传 partition_names 这种软约束。

**"如果 A 公司的 runbook 被 B 公司检索到了怎么办，你们怎么防止？"**
> 三道防线：第一，Milvus Partition 在向量库层隔离，查询只扫当前租户 Partition；第二，应用层强制 tenant_id metadata filter，即使 Partition 配置有误，metadata filter 仍会过滤；第三，返回结果后做 tenant consistency check，确认每条 chunk 的 tenant_id 和当前请求者一致。OnCall 场景数据特别敏感——内部架构、故障复盘、恢复脚本——串租户是直接泄露企业内部运维知识，不只是搜错了。

**"你说参考了 OpenClaw，具体参考了什么？"**
> 五个地方：Gateway 的消息归一化路由、Session 的两层存储、Compaction 的 branch_summary 机制、Workspace 文件的 Agent 配置模型、Lobster 的 YAML workflow + resumeToken。没直接用因为它是 Node.js 单用户系统，我们用 Python 重实现加入多租户和企业级存储。

**"这个产品真的能商业化吗？"**
> 可以，目标客户是中大型技术公司。混合部署解决企业安全顾虑，MCP 标准化工具集成，常见工具提供预置模板。竞品（PagerDuty、Rootly）停在辅助诊断阶段，我们的差异是把 AI 推进到自动执行修复。

---

## 十四、设计审查结论

判断是否过度设计的标准：**这个设计解决的问题，在多租户 OnCall 平台场景里真实存在吗？**

| 设计 | 结论 | 理由 |
|------|------|------|
| PostgreSQL RLS | ✅ 保留 | 多组织共用平台，数据隔离是安全底线 |
| Milvus Partition | ✅ 保留 | 跨租户检索是真实安全漏洞 |
| 6状态机 + PG Checkpoint | ✅ 保留 | 事故处理跨时间、跨重启 |
| LangGraph interrupt() | ✅ 保留 | 高危操作必须人工确认，不可绕过 |
| Lobster-lite YAML | ✅ 保留 | SRE 和开发者是不同人，操作步骤不应耦合进代码 |
| RAGAS 评估 | ✅ 保留 | 没有评估无法验证 RAG 改动好坏 |
| Redis Session | ✅ 保留 | 多实例部署下进程内存无法共享 |
| 4层 Compaction | ✅ 保留 | 关键事故信息被截断导致决策错误 |
| S3 存 Workspace 文件 | ❌ 调整 | 几KB配置存 PG JSONB 即可，S3 只存大文件 |
| BackgroundTasks → Kafka | ⏳ 预留 | OnCall 低并发，当前够用，接口预留 |
| Temporal | ❌ 不引入 | LangGraph Checkpoint 已覆盖，引入是重叠 |

---

## 十五、OpenClaw 原版边界（理解为什么这么改）

**Lane Queue 不用 Redis**：Local-First 哲学，单进程不需要外部依赖。我们打破这个哲学因为多租户需要多实例。

**Markdown 记忆的边界**：个人场景优雅，企业级几十万条时文件读写和 SQLite 并发写入会成瓶颈。

**两层 Sub-Agent 限制**：刻意约束防止递归失控。我们保留，Gateway 层加配额控制防止单租户耗尽平台资源。

**MCP 工具返回结构化数据**：OpenClaw 浏览器工具用 ARIA 语义快照替代截图，5MB → 50KB，Token 降低98%。我们的 MCP 工具同样返回结构化 JSON 摘要而不是原始数据流。

---

## 十六、商业模式与产品定位

**目标客户**：中大型技术公司（有专职 SRE、有复杂内网、有 OnCall 流程）

**竞品**：PagerDuty / Rootly / FireHydrant——都停在"辅助诊断"阶段，我们差异是"自动执行修复"

**护城河**：混合部署解决安全顾虑 + MCP 标准化工具集成 + 多租户平台而非内部工具

**企业落地障碍与我们的解法**：

| 障碍 | 解决方案 |
|------|---------|
| 数据不出域 | 混合部署，生产凭证留内网 |
| 合规审计 | audit_logs 全链路记录 |
| 成本失控 | per-tenant Token 配额 + Compaction |
| 模型锁定 | LLM 抽象层，配置切换支持国产模型 |
| OpenClaw 治理风险 | Python 自主实现，不依赖上游 |
