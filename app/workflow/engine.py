"""
YAML Workflow 引擎 - P1 六状态架构
对应 tasks.md: Task 10.1 - YAML Parser & 执行引擎
"""

import re
import yaml
from uuid import uuid4
from typing import Literal, Optional, Dict, Any, List
from pydantic import BaseModel, Field
from loguru import logger


# 定义特殊异常，用于被 LangGraph 的图拦截处理
class ApprovalRequired(Exception):
    def __init__(self, token: str, message: str):
        self.token = token
        self.message = message
        super().__init__(f"Approval Required: {message} (Token: {token})")


# ---------------------------------------------------------------------------
# YAML Schema Definitaion
# ---------------------------------------------------------------------------

class WorkflowStep(BaseModel):
    name: str
    type: Literal["mcp_call", "llm_call", "approval"]
    tool: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    prompt: Optional[str] = None
    message: Optional[str] = None


class Workflow(BaseModel):
    name: str
    description: str
    steps: List[WorkflowStep]


def parse_workflow(yaml_content: str) -> Workflow:
    """解析 YAML workflow 文本结构到强类型 BaseModel"""
    data = yaml.safe_load(yaml_content)
    if not isinstance(data, dict):
        raise ValueError("Invalid YAML format: Workflow must be a dict.")
    return Workflow(**data)


# ---------------------------------------------------------------------------
# Interpolation helper 变量替换辅助
# ---------------------------------------------------------------------------

def _resolve_var(path: str, context: dict) -> Any:
    """从上下文中获取变量，如 steps.fetch_logs.output"""
    parts = path.strip().split('.')
    current = context
    for p in parts:
        if isinstance(current, dict) and p in current:
            current = current[p]
        elif hasattr(current, p):
            current = getattr(current, p)
        else:
            return f"{{{{ {path} }}}}" # 未找到保留原样
    return current


def _interpolate_string(text: str, context: dict) -> str:
    """替换 {{ var.path }} 模板"""
    pattern = re.compile(r'\{\{\s*(.+?)\s*\}\}')
    
    def replace_match(match):
        var_path = match.group(1)
        val = _resolve_var(var_path, context)
        # 如果是字符串则正常替换，其余类型序列化以免报错
        if isinstance(val, (dict, list)):
            import json
            return json.dumps(val, ensure_ascii=False)
        return str(val)
        
    return pattern.sub(replace_match, text)


def _interpolate_dict(params: dict, context: dict) -> dict:
    """递归替换字典中的值"""
    result = {}
    for k, v in params.items():
        if isinstance(v, str):
            result[k] = _interpolate_string(v, context)
        elif isinstance(v, dict):
            result[k] = _interpolate_dict(v, context)
        elif isinstance(v, list):
            result[k] = [
                _interpolate_dict(i, context) if isinstance(i, dict) else 
                _interpolate_string(i, context) if isinstance(i, str) else i 
                for i in v
            ]
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# Workflow 执行引擎 
# ---------------------------------------------------------------------------

class WorkflowEngine:
    """执行已解析好的 YAML 工作流"""

    async def execute(
        self,
        workflow: Workflow,
        initial_context: Dict[str, Any],
        resume_token: Optional[str] = None,
        # TODO: Mock MCP and LLM deps for P1
        db_handler: Any = None 
    ) -> Dict[str, Any]:
        """
        执行 YAML 流程，支持基于 resume_token 从断点恢复
        初始上下文(initial_context)包含用户输入、tenant_id等
        """
        logger.info(f"开启 Workflow 执行: {workflow.name}")
        
        # 1. 恢复记录和偏移量
        completed_steps = {}
        start_index = 0
        
        # NOTE: 此处应该根据 resume_token 去 PostgreSQL 读取已经通过的审批记录
        # P1 暂时全当新任务从头跑（在 test15 中会补全持久化读取）
        if resume_token and db_handler:
            pass # completed_steps = await db_handler.get_approval(resume_token)
            
        context = {"steps": completed_steps.copy()}
        context.update(initial_context)  # 将顶层变量直接放上下文中

        for idx, step in enumerate(workflow.steps[start_index:], start=start_index):
            logger.debug(f"执行工作流步骤 [{idx+1}/{len(workflow.steps)}]: {step.name}")
            
            try:
                # 审批门
                if step.type == "approval":
                    msg = step.message or f"Approval required for step {step.name}"
                    msg = _interpolate_string(msg, context)
                    token = str(uuid4())
                    logger.warning(f"Workflow 遇到审批阻断: {msg} (Token: {token})")
                    # 这里 raise Exception 由外层 LangGraph 捕获并 interrupt
                    raise ApprovalRequired(token=token, message=msg)
                    
                # LLM 调用
                elif step.type == "llm_call":
                    prompt = step.prompt or ""
                    prompt = _interpolate_string(prompt, context)
                    logger.debug(f"[LLM] Mock LLM evaluation with prompt: {prompt[:50]}...")
                    # Mock LLM 返回
                    result = {"output": f"Mock LLM Analysis for {step.name}"}
                    context["steps"][step.name] = result
                    
                # MCP 调用
                elif step.type == "mcp_call":
                    params = step.params or {}
                    params = _interpolate_dict(params, context)
                    logger.debug(f"[MCP] Calling tool: {step.tool} with params: {params}")
                    # Mock MCP 执行结果
                    result = {"output": f"Mock output from MCP {step.tool}", "status": "success"}
                    context["steps"][step.name] = result

            except ApprovalRequired as e:
                # 冒泡给外层
                raise e
            except Exception as e:
                logger.error(f"步骤 {step.name} 执行失败: {e}", exc_info=True)
                # 立即返回当前有的结果，标记失败
                context["steps"][step.name] = {"error": str(e), "status": "failed"}
                return context["steps"]
                
        logger.info(f"Workflow 执行完毕: {workflow.name}")
        return context["steps"]


# Engine 单例
workflow_engine = WorkflowEngine()
