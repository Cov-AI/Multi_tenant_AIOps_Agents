"""
Prometheus Metrics 指标和注册表的单元测试
对应 tasks.md: Task 21.2, 21.3
"""

import time
import pytest
from prometheus_client import REGISTRY

from app.observability.metrics import MetricsManager, app_registry, AIOPS_REQUEST_COUNT, AIOPS_EXECUTION_LATENCY

def test_21_2_property_metrics_generation():
    """Property 29: Metrics generation - 验证核心的指标被生成且类型无污染"""
    
    # 模拟一次 AIOps 请求并且成功
    MetricsManager.record_aiops_invocation("tenant_A", success=True)
    
    # 模拟一次耗时代码块
    with MetricsManager.get_aiops_latency_timer("tenant_A", "analyze_node"):
        time.sleep(0.01)
        
    # 查询当前 app_registry 中的取值！
    count_val = app_registry.get_sample_value(
        "aiops_invocations_total", 
        {"tenant_id": "tenant_A", "status": "success"}
    )
    assert count_val is not None
    assert count_val >= 1.0  # 可能受其他测试用例影响累积，只要保证其可以测且增加了即可
    
    # 验证 Histogram 会统计 count 与 sum
    hist_count = app_registry.get_sample_value(
        "aiops_execution_duration_seconds_count",
        {"tenant_id": "tenant_A", "node_name": "analyze_node"}
    )
    assert hist_count is not None
    assert hist_count >= 1.0
    
    hist_sum = app_registry.get_sample_value(
        "aiops_execution_duration_seconds_sum",
        {"tenant_id": "tenant_A", "node_name": "analyze_node"}
    )
    assert hist_sum is not None
    assert hist_sum >= 0.01


def test_21_3_unit_metrics_registry_isolation():
    """Unit Tests: Prometheus Registry Isolation - 防止污染全局指标"""
    # 验证自己使用的库独立对象 app_registry 不是全局的默认单例 REGISTRY
    assert app_registry is not REGISTRY
    
    # 我们的业务指标绝对没有也不该混在 global python metrics 中
    # 因为 FastAPI 我们往往用专门的 Exporter，而独立的 registry 能防止把 python os details 泄漏出去
    global_samples = REGISTRY.get_sample_value(
        "aiops_invocations_total", 
        {"tenant_id": "tenant_A", "status": "success"}
    )
    assert global_samples is None  # 不在 default 中
