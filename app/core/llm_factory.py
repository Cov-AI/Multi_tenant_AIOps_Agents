"""LLM Factory — 统一 LLM 抽象层

对应 ONCALL_FINAL.md: "LLM 抽象层，配置切换支持国产模型"
对应 tasks.md: Task 2.5 — 实现 LLM Factory 抽象层（从 Qwen/DashScope 迁移到 OpenRouter）

核心思路：
- 用 langchain_openai.ChatOpenAI + OpenRouter base_url 替代所有 ChatQwen
- 用 langchain_openai.OpenAIEmbeddings 替代 DashScopeEmbeddings
- 所有 Agent 通过此 Factory 获取 LLM 实例，不再直接 import ChatQwen

OpenRouter 兼容 OpenAI API，一个 API Key 即可切换 Claude / GPT-4o / Gemini 等模型。
"""

from functools import lru_cache
from typing import Optional

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from loguru import logger

from app.config import config


# ---------------------------------------------------------------------------
# Chat LLM Factory
# ---------------------------------------------------------------------------

def get_chat_llm(
    model: Optional[str] = None,
    temperature: float = 0.7,
    streaming: bool = True,
    **kwargs,
) -> ChatOpenAI:
    """获取 Chat LLM 实例（通过 OpenRouter）。

    Args:
        model: 模型名称，如 "anthropic/claude-sonnet-4-20250514", "openai/gpt-4o"
               默认使用 config.default_model
        temperature: 生成温度
        streaming: 是否流式输出
        **kwargs: 传递给 ChatOpenAI 的其他参数

    Returns:
        已配置的 ChatOpenAI 实例

    使用方式::

        llm = get_chat_llm()
        result = await llm.ainvoke("Hello!")

        # 指定模型
        llm = get_chat_llm(model="openai/gpt-4o", temperature=0.3)
    """
    model_name = model or config.default_model
    api_key = config.openrouter_api_key

    # 如果 OpenRouter key 为空，尝试使用 OpenAI key（开发环境可能直连 OpenAI）
    base_url = config.openrouter_base_url
    if not api_key and config.openai_api_key:
        api_key = config.openai_api_key
        base_url = "https://api.openai.com/v1"
        logger.info("OpenRouter key 未配置，使用 OpenAI API 直连")

    # 降级：如果都没配置，尝试使用旧的 DashScope 配置（向后兼容）
    if not api_key and config.dashscope_api_key:
        api_key = config.dashscope_api_key
        base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        model_name = model or config.dashscope_model
        logger.warning("使用 DashScope 降级模式（建议迁移到 OpenRouter）")

    if not api_key:
        raise ValueError(
            "未配置 LLM API Key。请设置 OPENROUTER_API_KEY 或 OPENAI_API_KEY 环境变量。"
        )

    llm = ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        streaming=streaming,
        **kwargs,
    )

    logger.debug(f"LLM 实例已创建: model={model_name}, base_url={base_url}")
    return llm


# ---------------------------------------------------------------------------
# Embedding Factory
# ---------------------------------------------------------------------------

def get_embeddings(
    model: Optional[str] = None,
) -> OpenAIEmbeddings:
    """获取 Embedding 模型实例。

    OpenAI / OpenRouter 都兼容 OpenAI Embeddings API。

    Args:
        model: Embedding 模型名称，默认使用 config.embedding_model

    Returns:
        已配置的 OpenAIEmbeddings 实例
    """
    model_name = model or config.embedding_model

    # Embedding 优先使用 OpenAI key（质量更稳定），然后 OpenRouter
    api_key = config.openai_api_key or config.openrouter_api_key
    base_url = "https://api.openai.com/v1"

    if not config.openai_api_key and config.openrouter_api_key:
        base_url = config.openrouter_base_url

    # 降级：DashScope
    if not api_key and config.dashscope_api_key:
        api_key = config.dashscope_api_key
        base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        model_name = model or config.dashscope_embedding_model
        logger.warning("Embedding 使用 DashScope 降级模式")

    if not api_key:
        raise ValueError(
            "未配置 Embedding API Key。请设置 OPENAI_API_KEY 或 OPENROUTER_API_KEY 环境变量。"
        )

    embeddings = OpenAIEmbeddings(
        model=model_name,
        openai_api_key=api_key,
        openai_api_base=base_url,
    )

    logger.debug(f"Embedding 实例已创建: model={model_name}")
    return embeddings


# ---------------------------------------------------------------------------
# 便捷函数：用于评估和基准测试
# ---------------------------------------------------------------------------

def count_tokens(text: str, model: Optional[str] = None) -> int:
    """粗略估算文本的 token 数量。

    使用简单的字符数 / 4 估算（英文约 4 字符 = 1 token，中文约 2 字符 = 1 token）。
    精确计算需要 tiktoken，但对于 A/B 测试的对比目的足够。
    """
    # 混合语言：取中英文估算的平均值
    char_count = len(text)
    # 英文估算
    en_tokens = char_count / 4
    # 中文估算（中文字符占比）
    cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    cn_tokens = cn_chars / 2 + (char_count - cn_chars) / 4

    return int((en_tokens + cn_tokens) / 2)
