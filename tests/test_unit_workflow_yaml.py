"""
YAML Workflow Engine Tests
对应 tasks.md: Task 10.2 - 10.5
"""

import pytest
import yaml
from pathlib import Path
from pydantic import ValidationError

from app.workflow.engine import (
    parse_workflow, 
    workflow_engine, 
    Workflow,
    ApprovalRequired,
    _interpolate_string,
    _interpolate_dict
)

# ---------------------------------------------------------------------------
# Test 10.5 & 10.2: String Interpolation & YAML Parsing (Property 14)
# ---------------------------------------------------------------------------

def test_interpolate_string():
    """测试嵌套模板字符串替换逻辑"""
    context = {
        "tenant_id": "tenant-123",
        "steps": {
            "fetch_logs": {"output": "OOM Killed"}
        }
    }
    
    # 基础替换
    assert _interpolate_string("ID: {{ tenant_id }}", context) == "ID: tenant-123"
    
    # 嵌套字典替换 (steps.fetch_logs.output)
    result = _interpolate_string("Reason: {{steps.fetch_logs.output}}", context)
    assert result == "Reason: OOM Killed"
    
    # 找不到变量时不替换
    assert _interpolate_string("{{not_exist}}", context) == "{{ not_exist }}"


def test_interpolate_dict():
    """测试字典的递归替换"""
    context = {"db": "master-db", "query": "select *"}
    params = {
        "target": "{{db}}",
        "nested": {
            "q": "{{query}}"
        },
        "list": ["{{db}}", "static"]
    }
    
    result = _interpolate_dict(params, context)
    assert result["target"] == "master-db"
    assert result["nested"]["q"] == "select *"
    assert result["list"] == ["master-db", "static"]


# ---------------------------------------------------------------------------
# Test 10.4: Validation errors (Property 28)
# ---------------------------------------------------------------------------

def test_invalid_yaml_format():
    """测试非法 YAML 会被 Pydantic 拒绝"""
    invalid_yaml = """
    name: test_fail
    steps:
      - name: oops
        type: not_a_real_type
    """
    
    with pytest.raises(ValidationError) as exc:
        parse_workflow(invalid_yaml)
    
    assert "type" in str(exc.value)
    
def test_missing_required_fields():
    """测试必填字段校验"""
    invalid_yaml = """
    name: test_fail
    # missing description
    steps:
      - type: mcp_call  # missing name
    """
    
    with pytest.raises(ValidationError):
        parse_workflow(invalid_yaml)


# ---------------------------------------------------------------------------
# Test 10.3: Execution & Approval (Property 15)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workflow_execution_and_approval():
    """
    测试 workflow 遇到 approval 节点挂断的要求。
    并测试正常节点被 Mock 执行后能存入 context。
    """
    yaml_content = """
    name: restart_flow
    description: "test"
    steps:
      - name: get_status
        type: mcp_call
        tool: mock_tool
      - name: confirm
        type: approval
        message: "Status is {{steps.get_status.output}}"
      - name: final
        type: llm_call
    """
    
    workflow = parse_workflow(yaml_content)
    
    # 执行应该在 confirm 步骤抛出异常
    with pytest.raises(ApprovalRequired) as exc:
        await workflow_engine.execute(
            workflow=workflow,
            initial_context={}
        )
        
    # 断言：消息已正确进行了前端节点的模板变量推导
    assert "Mock output from MCP mock_tool" in exc.value.message
    assert exc.value.token is not None


@pytest.mark.asyncio
async def test_template_loadable():
    """测试真实的 YAML 模板是否符合 Schema (加载不报错即可)"""
    template_dir = Path(__file__).parent.parent / "app" / "workflow" / "templates"
    for file_path in template_dir.glob("*.yaml"):
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            workflow = parse_workflow(content)
            assert isinstance(workflow, Workflow)
            assert len(workflow.steps) > 0
