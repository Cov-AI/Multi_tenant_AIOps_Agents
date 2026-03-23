# ADR-0008: 混合部署架构（云端控制面 + 用户内网 MCP Server）

## 状态

已接受 (Accepted)

## 上下文

OnCall 平台需要访问用户的生产环境（Kubernetes、数据库、监控系统）来执行故障诊断和修复操作。这涉及到敏感的生产凭证（kubectl token、数据库密码、API Key）。

### 安全合规要求

企业客户（尤其是金融、医疗、政府行业）通常有严格的安全合规要求：

1. **凭证不出内网**：生产环境凭证不能存储在云端
2. **最小权限原则**：第三方服务只能访问必要的资源
3. **审计追溯**：所有操作必须可追溯
4. **数据主权**：敏感数据不能离开特定地理区域

### 部署模式对比

#### 模式 1：全云端部署

```
┌─────────────────────────────────────┐
│  云端平台                            │
│  - Agent Worker                     │
│  - 存储生产凭证                     │
│  - 直接访问用户生产环境             │
└─────────────────────────────────────┘
         ↓ 直接访问
┌─────────────────────────────────────┐
│  用户生产环境                        │
│  - Kubernetes                       │
│  - 数据库                           │
│  - 监控系统                         │
└─────────────────────────────────────┘
```

**问题**：
- ❌ 凭证存储在云端，安全风险高
- ❌ 需要开放生产环境到公网，增加攻击面
- ❌ 不满足合规要求

#### 模式 2：全本地部署

```
┌─────────────────────────────────────┐
│  用户内网                            │
│  - Agent Worker                     │
│  - PostgreSQL                       │
│  - Redis                            │
│  - Milvus                           │
│  - 生产环境                         │
└─────────────────────────────────────┘
```

**问题**：
- ❌ 用户需要自己部署和维护整个平台
- ❌ 无法享受 SaaS 的便利性（自动更新、统一运维）
- ❌ 不适合中小企业（运维成本高）

#### 模式 3：混合部署（推荐）

```
┌─────────────────────────────────────┐
│  云端平台（我们部署）                │
│  - Gateway                          │
│  - Agent Worker                     │
│  - PostgreSQL                       │
│  - Redis                            │
│  - Milvus                           │
└──────────────┬──────────────────────┘
               │ MCP 协议（HTTPS）
               │ 只传输操作指令和结果
               │ 不传输凭证
┌──────────────▼──────────────────────┐
│  用户内网（用户部署）                │
│  - MCP Server                       │
│  - 生产凭证（不离开内网）           │
│  - 生产环境                         │
└─────────────────────────────────────┘
```

**优势**：
- ✅ 凭证不离开内网
- ✅ 用户只需部署轻量级 MCP Server
- ✅ 平台享受 SaaS 的便利性
- ✅ 满足合规要求

## 决策

**采用混合部署架构：云端控制面 + 用户内网 MCP Server。**

具体策略：

1. **云端部署**：Gateway、Agent Worker、数据库、向量数据库
2. **用户内网部署**：MCP Server（轻量级 Python 服务）
3. **通信协议**：MCP over HTTPS（只传输操作指令和结果，不传输凭证）
4. **权限控制**：MCP Server 控制暴露给 Agent 的工具范围和权限

## 理由

### 混合部署的优势

#### 1. 凭证不离开内网

**全云端部署的问题**：
```python
# 云端存储凭证（不安全）
tenant_config = {
    "kubectl_token": "eyJhbGciOiJSUzI1NiIsImtpZCI6Ii...",  # 敏感凭证
    "db_password": "prod_db_password_123",                # 敏感凭证
    "prometheus_api_key": "prom_key_456"                  # 敏感凭证
}
```
- ❌ 凭证存储在云端数据库，泄露风险高
- ❌ 平台被攻击时，所有租户凭证泄露
- ❌ 不满足合规要求

**混合部署的优势**：
```python
# 云端只存储 MCP Server 地址
tenant_config = {
    "mcp_server_url": "https://mcp.customer.internal",  # 只存储地址
    "mcp_api_key": "mcp_key_789"                        # MCP Server 的 API Key（非生产凭证）
}

# 生产凭证存储在用户内网的 MCP Server
# 云端 Agent 无法直接访问
```
- ✅ 生产凭证不离开内网
- ✅ 平台被攻击时，生产凭证不泄露
- ✅ 满足合规要求

#### 2. 最小权限原则

**MCP Server 控制工具暴露**：
```python
# MCP Server 配置（用户内网）
mcp_config = {
    "tools": [
        {
            "name": "loki_query",
            "allowed": True,
            "params": {
                "max_time_range": "1h"  # 限制查询时间范围
            }
        },
        {
            "name": "kubectl_delete",
            "allowed": False  # 禁止删除操作
        },
        {
            "name": "db_query",
            "allowed": True,
            "params": {
                "allowed_databases": ["monitoring"],  # 只允许查询监控数据库
                "read_only": True  # 只读
            }
        }
    ]
}
```
- ✅ 用户控制 Agent 可以访问的工具
- ✅ 用户控制工具的权限范围
- ✅ 云端 Agent 无法绕过限制

#### 3. 审计追溯

**MCP Server 记录所有操作**：
```python
# MCP Server 审计日志（用户内网）
{
    "timestamp": "2024-01-15T10:30:00Z",
    "tool": "kubectl_restart",
    "params": {"deployment": "payment-service"},
    "result": "success",
    "agent_id": "agent-123",
    "tenant_id": "tenant-456",
    "user_id": "user-789"
}
```
- ✅ 用户可以查看所有 Agent 执行的操作
- ✅ 满足审计要求
- ✅ 用户可以随时撤销 MCP Server 的访问权限

#### 4. 数据主权

**敏感数据不离开内网**：
```python
# Agent 调用 MCP 工具
request = {
    "tool": "loki_query",
    "params": {
        "query": '{service="payment"} |= "error"',
        "time_range": "30m"
    }
}

# MCP Server 返回摘要（不返回原始日志）
response = {
    "summary": "发现 15 条错误日志，主要错误：OOMKilled",
    "error_count": 15,
    "top_errors": [
        {"message": "OOMKilled", "count": 10},
        {"message": "Connection timeout", "count": 5}
    ]
}
# 原始日志不离开内网
```
- ✅ 原始日志、指标、数据库数据不离开内网
- ✅ 只传输摘要和结构化数据
- ✅ 满足数据主权要求

#### 5. SaaS 便利性

**用户只需部署轻量级 MCP Server**：
```bash
# 用户内网部署（Docker Compose）
docker-compose up -d

# 或使用 Kubernetes
kubectl apply -f mcp-server.yaml
```
- ✅ 部署简单（单个 Docker 容器）
- ✅ 无需维护数据库、向量数据库
- ✅ 平台自动更新（云端部分）
- ✅ 享受 SaaS 的便利性

### MCP 协议

**Model Context Protocol (MCP)** 是 Anthropic 提出的标准化协议，用于 LLM 与外部工具的通信。

#### MCP Server 接口

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class ToolRequest(BaseModel):
    tool: str
    params: dict

class ToolResponse(BaseModel):
    result: dict
    error: str | None = None

@app.post("/tools/call")
async def call_tool(request: ToolRequest) -> ToolResponse:
    """调用工具"""
    # 验证 API Key
    if not verify_api_key(request.headers["Authorization"]):
        return ToolResponse(error="Unauthorized")
    
    # 检查工具是否允许
    if not is_tool_allowed(request.tool):
        return ToolResponse(error=f"Tool {request.tool} not allowed")
    
    # 执行工具
    if request.tool == "loki_query":
        result = await query_loki(request.params)
    elif request.tool == "kubectl_restart":
        result = await kubectl_restart(request.params)
    else:
        return ToolResponse(error=f"Unknown tool {request.tool}")
    
    return ToolResponse(result=result)

@app.get("/tools/list")
async def list_tools() -> list[str]:
    """列出可用工具"""
    return ["loki_query", "prometheus_query", "kubectl_restart", "health_check"]
```

#### Agent 调用 MCP Server

```python
class MCPClient:
    def __init__(self, server_url: str, api_key: str):
        self.server_url = server_url
        self.api_key = api_key
    
    async def call(self, tool: str, params: dict) -> dict:
        """调用 MCP 工具"""
        response = await httpx.post(
            f"{self.server_url}/tools/call",
            json={"tool": tool, "params": params},
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        
        if response.status_code != 200:
            raise MCPError(f"MCP call failed: {response.text}")
        
        data = response.json()
        if data.get("error"):
            raise MCPError(data["error"])
        
        return data["result"]
```

### 考虑的替代方案

#### 方案 A：全云端部署

**优势**：
- 架构简单
- 用户无需部署任何组件

**局限**：
- ❌ 凭证存储在云端，安全风险高
- ❌ 需要开放生产环境到公网
- ❌ 不满足合规要求
- ❌ 不适合金融、医疗等高合规行业

#### 方案 B：全本地部署

**优势**：
- 安全性最高
- 满足所有合规要求

**局限**：
- ❌ 用户需要自己部署和维护整个平台
- ❌ 无法享受 SaaS 的便利性
- ❌ 不适合中小企业
- ❌ 平台更新需要用户手动升级

#### 方案 C：VPN 隧道

**优势**：
- 云端可以直接访问用户内网

**局限**：
- ❌ 凭证仍需存储在云端
- ❌ VPN 配置复杂，用户体验差
- ❌ 不满足"凭证不出内网"的要求

### 为什么选择混合部署

1. **安全性**：凭证不离开内网，满足合规要求
2. **便利性**：用户只需部署轻量级 MCP Server
3. **灵活性**：用户控制工具暴露和权限
4. **可扩展性**：支持多种 MCP Server 实现（Python、Go、Rust）
5. **业界标准**：MCP 是 Anthropic 提出的标准化协议

## 后果

### 正面影响

1. **安全保障**：凭证不离开内网，满足合规要求
2. **用户体验**：只需部署轻量级 MCP Server，享受 SaaS 便利性
3. **权限控制**：用户控制工具暴露和权限
4. **审计追溯**：MCP Server 记录所有操作
5. **数据主权**：敏感数据不离开内网

### 负面影响

1. **网络依赖**：需要用户内网到云端的网络连接
2. **延迟增加**：MCP 调用需要跨网络（但可接受）
3. **部署复杂度**：用户需要部署 MCP Server（但已简化）

### 风险缓解

1. **网络可靠性**：
   ```python
   # MCP 调用重试机制
   async def call_with_retry(tool: str, params: dict, max_retries: int = 3):
       for attempt in range(max_retries):
           try:
               return await mcp_client.call(tool, params)
           except MCPError as e:
               if attempt == max_retries - 1:
                   raise
               await asyncio.sleep(2 ** attempt)  # 指数退避
   ```

2. **MCP Server 健康检查**：
   ```python
   # 定期检查 MCP Server 可用性
   async def health_check():
       try:
           await mcp_client.call("health_check", {})
           return True
       except MCPError:
           return False
   ```

3. **降级策略**：
   ```python
   # MCP Server 不可用时，将事故升级
   if not await health_check():
       incident.state = "ESCALATED"
       incident.escalation_reason = "MCP Server unavailable"
       await notify_sre(incident)
   ```

4. **部署简化**：
   ```bash
   # 提供一键部署脚本
   curl -sSL https://oncall.example.com/install-mcp.sh | bash
   
   # 或 Docker Compose
   docker-compose -f mcp-server.yml up -d
   
   # 或 Kubernetes Helm Chart
   helm install mcp-server oncall/mcp-server
   ```

5. **监控告警**：
   ```python
   # Prometheus 指标
   mcp_call_duration = Histogram(
       "mcp_call_duration_seconds",
       "MCP call duration",
       ["tenant_id", "tool"]
   )
   
   mcp_call_failures = Counter(
       "mcp_call_failures_total",
       "MCP call failures",
       ["tenant_id", "tool", "error_type"]
   )
   ```

### 实施检查清单

- [ ] 实现 MCP Client（云端 Agent）
- [ ] 实现 MCP Server（用户内网）
- [ ] 实现 MCP 协议（工具调用、工具列表）
- [ ] 实现 API Key 认证
- [ ] 实现工具权限控制
- [ ] 实现审计日志记录
- [ ] 提供 Docker Compose 部署文件
- [ ] 提供 Kubernetes Helm Chart
- [ ] 提供一键部署脚本
- [ ] 编写 MCP Server 部署文档
- [ ] 配置监控告警（MCP 调用失败、延迟）

## 相关决策

- ADR-0001: 使用 LangGraph StateGraph 替代 Plan-Execute 模式
- ADR-0003: 使用 PostgreSQL RLS 作为数据隔离的最后防线

## 参考资料

- [Model Context Protocol (MCP)](https://www.anthropic.com/news/model-context-protocol)
- [MCP Specification](https://spec.modelcontextprotocol.io/)
- [Hybrid Cloud Architecture Best Practices](https://cloud.google.com/architecture/hybrid-and-multi-cloud-architecture-patterns)
- ONCALL_FINAL.md 第三章：混合部署架构设计

## 决策日期

2026-03-22

## 决策者

项目团队
