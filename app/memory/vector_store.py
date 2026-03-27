"""Milvus 多租户向量存储

对应 design.md: Memory 层 → Milvus 多租户隔离 (L419-482)
对应 design.md: Milvus Collection Schema (L804-831)
对应 tasks.md: Task 3.1 — 修改向量存储以支持租户 Partition

隔离策略（三重防护）：
1. 每个租户一个 Partition（tenant_{tenant_id}）
2. 查询时同时指定 partition_names 和 filter（双重防护）
3. 返回结果后验证 tenant_id 一致性
"""

from typing import Optional

from loguru import logger
from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from app.config import config
from app.core.llm_factory import get_embeddings


# ---------------------------------------------------------------------------
# Collection Schema
# design.md L806-831: runbooks Collection
# ---------------------------------------------------------------------------

COLLECTION_NAME = "runbooks"

# Embedding 维度 — OpenAI text-embedding-3-small 默认 1536
EMBEDDING_DIM = 1536


def _get_runbook_schema() -> CollectionSchema:
    """定义 runbooks Collection 的 schema。"""
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="tenant_id", dtype=DataType.VARCHAR, max_length=36),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
        FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=8192),
        FieldSchema(name="document_id", dtype=DataType.VARCHAR, max_length=36),
        FieldSchema(name="chunk_index", dtype=DataType.INT64),
        FieldSchema(name="metadata", dtype=DataType.JSON),
    ]
    return CollectionSchema(fields, description="Runbook embeddings with tenant isolation")


# ---------------------------------------------------------------------------
# VectorStore — 多租户向量存储
# ---------------------------------------------------------------------------

class VectorStore:
    """多租户 Milvus 向量存储。

    每个租户通过 Partition 隔离数据，查询时使用双重过滤。
    """

    def __init__(self):
        self._collection: Optional[Collection] = None
        self._embeddings = None

    def _ensure_collection(self) -> Collection:
        """确保 Collection 存在，不存在则创建。"""
        if self._collection is not None:
            return self._collection

        if not utility.has_collection(COLLECTION_NAME):
            schema = _get_runbook_schema()
            self._collection = Collection(name=COLLECTION_NAME, schema=schema)

            # 创建索引
            # design.md L822-827: IVF_FLAT + COSINE
            index_params = {
                "metric_type": "COSINE",
                "index_type": "IVF_FLAT",
                "params": {"nlist": 1024},
            }
            self._collection.create_index("embedding", index_params)
            logger.info(f"Collection '{COLLECTION_NAME}' 已创建并建立索引")
        else:
            self._collection = Collection(name=COLLECTION_NAME)

        self._collection.load()
        return self._collection

    def _ensure_partition(self, tenant_id: str) -> str:
        """确保租户的 Partition 存在。

        design.md L829: "为每个租户创建 Partition: tenant_{tenant_id}"
        """
        partition_name = f"tenant_{tenant_id}"
        collection = self._ensure_collection()

        if not collection.has_partition(partition_name):
            collection.create_partition(partition_name)
            logger.info(f"Partition '{partition_name}' 已创建")

        return partition_name

    def _get_embeddings(self):
        """懒初始化 Embedding 模型。"""
        if self._embeddings is None:
            self._embeddings = get_embeddings()
        return self._embeddings

    # -------------------------------------------------------------------
    # 写入 — Runbook 摄入
    # design.md L430-457: ingest_runbook
    # -------------------------------------------------------------------

    async def ingest_runbook(
        self,
        tenant_id: str,
        chunks: list[str],
        document_id: str,
        metadata: Optional[dict] = None,
    ) -> int:
        """摄入 runbook（已分好的文本块）到指定租户的 Partition。

        Args:
            tenant_id: 租户 ID
            chunks: 已切片的文本块列表
            document_id: 文档唯一 ID
            metadata: 额外元数据

        Returns:
            成功写入的 chunk 数量
        """
        partition_name = self._ensure_partition(tenant_id)
        collection = self._ensure_collection()
        embeddings_model = self._get_embeddings()

        # 生成 embeddings
        embeddings = await embeddings_model.aembed_documents(chunks)

        # 构造插入数据
        data = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            data.append({
                "tenant_id": tenant_id,
                "embedding": embedding,
                "text": chunk,
                "document_id": document_id,
                "chunk_index": i,
                "metadata": metadata or {},
            })

        # 写入指定 Partition
        collection.insert(data, partition_name=partition_name)
        collection.flush()

        logger.info(
            f"Runbook 写入完成: tenant={tenant_id}, doc={document_id}, "
            f"chunks={len(chunks)}, partition={partition_name}"
        )
        return len(chunks)

    # -------------------------------------------------------------------
    # 检索 — RAG 检索
    # design.md L459-482: search（双重过滤 + 结果验证）
    # -------------------------------------------------------------------

    async def search(
        self,
        tenant_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[dict]:
        """检索 runbook（双重过滤 + 结果验证）。

        design.md: "指定 partition 和 filter（双重防护）"

        Args:
            tenant_id: 租户 ID
            query: 查询文本
            top_k: 返回前 K 个结果

        Returns:
            检索结果列表 [{text, score, document_id, chunk_index, metadata}]
        """
        partition_name = self._ensure_partition(tenant_id)
        collection = self._ensure_collection()
        embeddings_model = self._get_embeddings()

        # 生成查询 embedding
        query_embedding = await embeddings_model.aembed_query(query)

        # 双重过滤：partition_names + metadata filter
        # design.md: "查询时同时指定 partition_names 和 filter"
        search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}

        results = collection.search(
            data=[query_embedding],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            partition_names=[partition_name],
            expr=f'tenant_id == "{tenant_id}"',
            output_fields=["text", "tenant_id", "document_id", "chunk_index", "metadata"],
        )

        # 解析结果 + 验证 tenant_id 一致性
        # design.md L478: "验证结果的 tenant_id"
        output = []
        for hits in results:
            for hit in hits:
                entity = hit.entity
                result_tenant_id = entity.get("tenant_id")

                # 第三重防护：结果验证
                if result_tenant_id != tenant_id:
                    logger.error(
                        f"租户隔离违规! 请求 tenant={tenant_id}, "
                        f"结果 tenant={result_tenant_id}"
                    )
                    continue  # 跳过泄漏数据

                output.append({
                    "text": entity.get("text", ""),
                    "score": hit.score,
                    "document_id": entity.get("document_id", ""),
                    "chunk_index": entity.get("chunk_index", 0),
                    "metadata": entity.get("metadata", {}),
                })

        logger.debug(
            f"RAG 检索完成: tenant={tenant_id}, query_len={len(query)}, "
            f"results={len(output)}"
        )
        return output

    # -------------------------------------------------------------------
    # 管理操作
    # -------------------------------------------------------------------

    def delete_tenant_data(self, tenant_id: str) -> None:
        """删除租户的所有向量数据。"""
        partition_name = f"tenant_{tenant_id}"
        collection = self._ensure_collection()

        if collection.has_partition(partition_name):
            collection.drop_partition(partition_name)
            logger.info(f"Partition '{partition_name}' 已删除")


# ---------------------------------------------------------------------------
# 全局实例
# ---------------------------------------------------------------------------

vector_store = VectorStore()
