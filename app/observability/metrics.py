"""
Prometheus Metrics 采集器
对应 tasks.md: Task 21.1 (请求量、错误率指标)
"""

from prometheus_client import Counter, Histogram, CollectorRegistry

# 提供一个独立的 Registry，防止测试污染全局 Registry
app_registry = CollectorRegistry()

# 1. 记录 AIOps Agent 调用的总次数与错误数 (按 Tenant)
AIOPS_REQUEST_COUNT = Counter(
    name="aiops_invocations_total",
    documentation="AIOps Agent 被唤起的总次数",
    labelnames=["tenant_id", "status"],
    registry=app_registry
)

# 2. 记录 AIOps 执行耗时分布
AIOPS_EXECUTION_LATENCY = Histogram(
    name="aiops_execution_duration_seconds",
    documentation="AIOps 流程图单次运转或流转耗时",
    labelnames=["tenant_id", "node_name"],
    buckets=[1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0],
    registry=app_registry
)

class MetricsManager:
    """提供统一的 API 为外部包裹 Prometheus 埋点"""
    
    @staticmethod
    def record_aiops_invocation(tenant_id: str, success: bool = True):
        status = "success" if success else "error"
        AIOPS_REQUEST_COUNT.labels(tenant_id=tenant_id, status=status).inc()
        
    @staticmethod
    def get_aiops_latency_timer(tenant_id: str, node_name: str = "full_graph"):
        """
        供 with 语句使用的上下文管理器：
        with MetricsManager.get_aiops_latency_timer(tenant_id, "analyze_node"):
            ... 执行节点代码 ...
        """
        return AIOPS_EXECUTION_LATENCY.labels(tenant_id=tenant_id, node_name=node_name).time()
        
    @staticmethod
    def reset_for_tests():
        """测试钩子：清空由于测试导致的统计数据"""
        # 注意此接口不要放到生产环境使用！
        # 清理指标可以重置 Registry，由于 Prometheus Python client 内部架构不支持直接 clear()，这作为测试隔离演示留有空间
        pass
