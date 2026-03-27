"""向量嵌入服务模块 - 基于 LLM Factory

对应 tasks.md: Task 2.5 — 实现 LLM Factory 抽象层
原 DashScopeEmbeddings 已重构为通过 unified get_embeddings() 获取，
支持 OpenRouter / OpenAI 等。
"""

from loguru import logger
from app.core.llm_factory import get_embeddings
from langchain_core.embeddings import Embeddings

# 为了向下兼容旧代码，我们在此提供一个全局单例/代理

class LazyEmbeddingProxy(Embeddings):
    """延迟初始化的 Embedding 代理。
    
    避免在应用启动时如果没有配置 API Key 直接报错。
    只有在第一次真的调用时才从 factory 获取并调用。
    """
    def __init__(self):
        self._instance = None
        
    @property
    def instance(self) -> Embeddings:
        if self._instance is None:
            try:
                self._instance = get_embeddings()
                logger.info("全局 Embedding 服务已按需初始化")
            except ValueError as e:
                # 为了防止服务在无 config 时启动崩溃，抛出警告，等真正使用时再报错
                logger.warning(f"Embedding 服务未配置: {e}")
                # 为了向下兼容和让应用先启动，返回一个空的 Dummy 或抛错
                # 但是为了满足 Langchain interface 和避免启动报错，这里必须能抛异常或者返回空
                raise RuntimeError("Embedding API Key 未配置") from e
        return self._instance

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # 如果当前在健康检查或尚未配置，则不调用真实 API
        return self.instance.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.instance.embed_query(text)

# 全局单例
vector_embedding_service = LazyEmbeddingProxy()
