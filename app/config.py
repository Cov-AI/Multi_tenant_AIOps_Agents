"""配置管理模块

使用 Pydantic Settings 实现类型安全的配置管理
"""

from typing import Dict, Any
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 应用配置
    app_name: str = "OnCall Agent Platform"
    app_version: str = "2.0.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 9900

    # --- P0 新增配置 ---

    # 数据库配置（Task 1.5）
    database_url: str = ""  # postgresql://user:pass@localhost:5432/oncall

    # Redis 配置（Task 5 Compaction 需要）
    redis_url: str = "redis://localhost:6379"

    # JWT 认证配置（Task 2.1）
    jwt_secret: str = "dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24 小时

    # OpenRouter / LLM 配置（Task 2.5 — 替代 DashScope）
    openrouter_api_key: str = ""
    default_model: str = "anthropic/claude-sonnet-4-20250514"
    embedding_model: str = "text-embedding-3-small"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Embedding 可以直接走 OpenAI（OpenRouter 也支持）
    openai_api_key: str = ""  # 用于 embedding，如果留空则使用 openrouter_api_key

    # 多租户模式（Task 24 — 可降级为单租户）
    multi_tenant_mode: bool = True

    # DashScope 配置
    dashscope_api_key: str = ""  # 默认空字符串，实际使用需从环境变量加载
    dashscope_model: str = "qwen-max"
    dashscope_embedding_model: str = "text-embedding-v4"  # v4 支持多种维度（默认 1024）

    # Milvus 配置
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_timeout: int = 10000  # 毫秒

    # RAG 配置
    rag_top_k: int = 3
    rag_model: str = "qwen-max"  # 使用快速响应模型，不带扩展思考

    # 文档分块配置
    chunk_max_size: int = 800
    chunk_overlap: int = 100

    # MCP 服务配置
    mcp_cls_transport: str = "streamable-http"
    mcp_cls_url: str = "http://localhost:8003/mcp"
    mcp_monitor_transport: str = "streamable-http"
    mcp_monitor_url: str = "http://localhost:8004/mcp"

    @property
    def mcp_servers(self) -> Dict[str, Dict[str, Any]]:
        """获取完整的 MCP 服务器配置"""
        return {
            "cls": {
                "transport": self.mcp_cls_transport,
                "url": self.mcp_cls_url,
            },
            "monitor": {
                "transport": self.mcp_monitor_transport,
                "url": self.mcp_monitor_url,
            }
        }


# 全局配置实例
config = Settings()
