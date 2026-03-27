"""模拟事故数据

对应 design.md: Testing Strategy → 测试数据生成 (L1404-1423)
对应 tasks.md: Task 6.1 — 创建 20 个模拟事故对话场景

提供 20 个常见 OnCall 场景，用于：
- Token 消耗 A/B 测试
- 事故响应时间评估
- RAGAS 评估
"""

from dataclasses import dataclass, field


@dataclass
class MockIncident:
    """模拟事故场景"""
    name: str
    severity: str  # P0/P1/P2/P3
    alert_content: str
    expected_diagnosis: str
    expected_action: str
    conversation_turns: int = 10  # 模拟对话轮次
    human_baseline_minutes: float = 30.0  # 人工处理基线时间（分钟）


# ---------------------------------------------------------------------------
# 20 个模拟事故场景
# design.md L1407-1423
# ---------------------------------------------------------------------------

MOCK_INCIDENTS: list[MockIncident] = [
    # P0 — 紧急
    MockIncident(
        name="OOM_Kill",
        severity="P0",
        alert_content="Pod payment-service-7d8f9c restarted due to OOMKilled",
        expected_diagnosis="Memory limit too low or memory leak",
        expected_action="Increase memory limit to 2Gi",
        conversation_turns=8,
        human_baseline_minutes=25.0,
    ),
    MockIncident(
        name="CrashLoopBackOff",
        severity="P1",
        alert_content="Pod api-gateway in CrashLoopBackOff state",
        expected_diagnosis="Configuration error or missing environment variable",
        expected_action="Check environment variables and rollback",
        conversation_turns=12,
        human_baseline_minutes=35.0,
    ),
    MockIncident(
        name="Database_Connection_Exhausted",
        severity="P0",
        alert_content="PostgreSQL max_connections reached (100/100)",
        expected_diagnosis="Connection leak in order-service",
        expected_action="Restart order-service and increase max_connections",
        conversation_turns=10,
        human_baseline_minutes=40.0,
    ),
    MockIncident(
        name="High_5xx_Rate",
        severity="P0",
        alert_content="5xx error rate > 10% on checkout-service",
        expected_diagnosis="Upstream payment gateway timeout",
        expected_action="Enable circuit breaker and fallback",
        conversation_turns=15,
        human_baseline_minutes=45.0,
    ),
    MockIncident(
        name="Disk_Full",
        severity="P1",
        alert_content="Disk usage > 95% on worker-node-3",
        expected_diagnosis="Unrotated log files consuming disk space",
        expected_action="Clean logs and configure logrotate",
        conversation_turns=6,
        human_baseline_minutes=20.0,
    ),
    # P1 — 高优先级
    MockIncident(
        name="Kafka_Consumer_Lag",
        severity="P1",
        alert_content="Kafka consumer lag > 100000 on notification-topic",
        expected_diagnosis="Consumer processing too slow",
        expected_action="Scale consumers and optimize processing logic",
        conversation_turns=10,
        human_baseline_minutes=30.0,
    ),
    MockIncident(
        name="Redis_Memory_High",
        severity="P1",
        alert_content="Redis memory usage > 90%",
        expected_diagnosis="Large keys and missing TTL",
        expected_action="Analyze key distribution and enable eviction",
        conversation_turns=8,
        human_baseline_minutes=25.0,
    ),
    MockIncident(
        name="SSL_Cert_Expiry",
        severity="P1",
        alert_content="SSL certificate expires in 3 days for api.example.com",
        expected_diagnosis="cert-manager renewal failure",
        expected_action="Manually renew cert and fix cert-manager",
        conversation_turns=6,
        human_baseline_minutes=20.0,
    ),
    MockIncident(
        name="Pod_Eviction",
        severity="P1",
        alert_content="Multiple pods evicted on node worker-2 due to memory pressure",
        expected_diagnosis="Node memory overcommitted",
        expected_action="Drain node, add resource limits, consider node scaling",
        conversation_turns=10,
        human_baseline_minutes=35.0,
    ),
    MockIncident(
        name="DNS_Resolution_Failure",
        severity="P1",
        alert_content="DNS resolution failing for internal services",
        expected_diagnosis="CoreDNS pods crashed",
        expected_action="Restart CoreDNS and investigate root cause",
        conversation_turns=8,
        human_baseline_minutes=25.0,
    ),
    # P2 — 中优先级
    MockIncident(
        name="Slow_Query",
        severity="P2",
        alert_content="Query execution time > 5s on user-service database",
        expected_diagnosis="Missing index on users.email",
        expected_action="Add index and optimize query",
        conversation_turns=8,
        human_baseline_minutes=30.0,
    ),
    MockIncident(
        name="Container_Image_Pull_Failure",
        severity="P2",
        alert_content="ImagePullBackOff for registry.example.com/app:v2.3.1",
        expected_diagnosis="Registry auth token expired",
        expected_action="Refresh registry credentials",
        conversation_turns=6,
        human_baseline_minutes=15.0,
    ),
    MockIncident(
        name="Service_Latency_Spike",
        severity="P2",
        alert_content="p99 latency > 2s on search-service",
        expected_diagnosis="Elasticsearch cluster under heavy load",
        expected_action="Scale ES data nodes and optimize queries",
        conversation_turns=12,
        human_baseline_minutes=40.0,
    ),
    MockIncident(
        name="Ingress_502",
        severity="P2",
        alert_content="Ingress returning 502 Bad Gateway for /api/v2/*",
        expected_diagnosis="Backend pods not ready after deployment",
        expected_action="Check readiness probe and rollout status",
        conversation_turns=8,
        human_baseline_minutes=20.0,
    ),
    MockIncident(
        name="Cron_Job_Failure",
        severity="P2",
        alert_content="CronJob backup-daily failed 3 consecutive times",
        expected_diagnosis="S3 bucket permissions changed",
        expected_action="Fix IAM role and rerun backup",
        conversation_turns=8,
        human_baseline_minutes=25.0,
    ),
    MockIncident(
        name="Network_Policy_Block",
        severity="P2",
        alert_content="Service-to-service calls blocked after network policy update",
        expected_diagnosis="Overly restrictive network policy",
        expected_action="Update network policy to allow required traffic",
        conversation_turns=10,
        human_baseline_minutes=30.0,
    ),
    MockIncident(
        name="PVC_Pending",
        severity="P2",
        alert_content="PVC data-volume-0 stuck in Pending state",
        expected_diagnosis="StorageClass provisioner error",
        expected_action="Check CSI driver and storage quota",
        conversation_turns=8,
        human_baseline_minutes=25.0,
    ),
    MockIncident(
        name="HPA_Max_Replicas",
        severity="P2",
        alert_content="HPA for frontend reached max replicas (20/20)",
        expected_diagnosis="Traffic spike exceeding HPA capacity",
        expected_action="Increase max replicas or enable cluster autoscaler",
        conversation_turns=8,
        human_baseline_minutes=20.0,
    ),
    # P3 — 低优先级
    MockIncident(
        name="Deprecated_API",
        severity="P3",
        alert_content="Kubernetes API v1beta1 deprecated, used by monitoring stack",
        expected_diagnosis="Helm chart using old API version",
        expected_action="Update Helm chart and test in staging",
        conversation_turns=6,
        human_baseline_minutes=60.0,
    ),
    MockIncident(
        name="Log_Volume_Spike",
        severity="P3",
        alert_content="Log ingestion rate 10x normal on debug-service",
        expected_diagnosis="Debug logging accidentally enabled in production",
        expected_action="Disable debug logging and clean up",
        conversation_turns=6,
        human_baseline_minutes=15.0,
    ),
]


def generate_mock_conversation(incident: MockIncident) -> list[dict]:
    """为给定事故生成模拟对话。

    用于 Token A/B 测试的对话数据。
    """
    messages = [
        {"role": "user", "content": f"[告警] {incident.alert_content}"},
        {"role": "assistant", "content": f"收到告警。正在分析 {incident.name} 事故...\n"
         f"严重级别：{incident.severity}\n"
         f"开始诊断步骤：\n1. 查询相关日志\n2. 检查监控指标\n3. 分析根因"},
        {"role": "user", "content": "请查询最近 30 分钟的日志"},
        {"role": "assistant", "content": f"日志分析完成。\n"
         f"发现关键信息：{incident.expected_diagnosis}\n"
         f"正在生成修复方案..."},
    ]

    # 根据 conversation_turns 添加更多轮次
    for i in range(4, incident.conversation_turns):
        if i % 2 == 0:
            messages.append({
                "role": "user",
                "content": f"继续执行下一步（步骤 {i // 2}）",
            })
        else:
            messages.append({
                "role": "assistant",
                "content": f"步骤 {i // 2} 执行完成。"
                f"{'建议执行：' + incident.expected_action if i == incident.conversation_turns - 1 else '继续分析中...'}",
            })

    return messages
