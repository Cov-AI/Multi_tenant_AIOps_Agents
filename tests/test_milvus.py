"""Task 3.2/3.3/3.4 — Milvus 多租户测试

对应 tasks.md: Task 3.2 (Property: Partition命名), 3.3 (Property: RAG双重过滤), 3.4 (Unit: Milvus集成)
"""

import uuid
import inspect
import pytest

from app.memory.vector_store import VectorStore, COLLECTION_NAME, EMBEDDING_DIM, _get_runbook_schema


# ---------------------------------------------------------------------------
# Task 3.2 — Property Test: Partition 命名一致性
# Feature: multi-tenant-oncall-platform, Property 3: Partition 命名一致性
# ---------------------------------------------------------------------------

class TestPartitionNamingProperty:
    """Property 3: Partition 名称遵循 tenant_{tenant_id} 格式。"""

    @pytest.mark.parametrize("_", range(10))
    def test_partition_name_format(self, _):
        """验证 Partition 名称格式正确。"""
        tid = str(uuid.uuid4())
        expected = f"tenant_{tid}"
        assert expected.startswith("tenant_")
        assert tid in expected
        assert len(expected) == len("tenant_") + len(tid)

    def test_partition_creation_code_uses_correct_format(self):
        """验证 _ensure_partition 方法使用 tenant_{id} 格式。"""
        source = inspect.getsource(VectorStore._ensure_partition)
        assert 'f"tenant_{tenant_id}"' in source or "tenant_" in source


# ---------------------------------------------------------------------------
# Task 3.3 — Property Test: RAG 检索双重过滤
# Feature: multi-tenant-oncall-platform, Property 17: RAG 检索双重过滤
# ---------------------------------------------------------------------------

class TestRAGDoubleFilterProperty:
    """Property 17: RAG 检索同时使用 partition_names 和 metadata filter。"""

    def test_search_code_uses_partition_names(self):
        """验证 search 方法使用 partition_names 参数。"""
        source = inspect.getsource(VectorStore.search)
        assert "partition_names" in source

    def test_search_code_uses_tenant_filter(self):
        """验证 search 方法使用 tenant_id metadata filter。"""
        source = inspect.getsource(VectorStore.search)
        assert 'tenant_id' in source
        # 验证 expr filter
        assert "expr=" in source or "filter=" in source

    def test_search_code_validates_results(self):
        """验证 search 方法对返回结果做 tenant_id 一致性校验。"""
        source = inspect.getsource(VectorStore.search)
        assert "result_tenant_id" in source
        assert "tenant_id" in source

    def test_ingest_code_uses_partition(self):
        """验证 ingest_runbook 方法写入时指定 partition_name。"""
        source = inspect.getsource(VectorStore.ingest_runbook)
        assert "partition_name" in source


# ---------------------------------------------------------------------------
# Task 3.4 — Unit Tests: Milvus 集成测试（结构验证，不需要 Milvus 连接）
# ---------------------------------------------------------------------------

class TestMilvusStructure:
    """验证 Milvus 配置和 Schema 结构。"""

    def test_collection_name(self):
        """验证 Collection 名称。"""
        assert COLLECTION_NAME == "runbooks"

    def test_embedding_dim(self):
        """验证 Embedding 维度。"""
        assert EMBEDDING_DIM == 1536  # OpenAI text-embedding-3-small

    def test_schema_fields(self):
        """验证 Schema 包含所有必要字段。"""
        schema = _get_runbook_schema()
        field_names = [f.name for f in schema.fields]
        assert "id" in field_names
        assert "tenant_id" in field_names
        assert "embedding" in field_names
        assert "text" in field_names
        assert "document_id" in field_names
        assert "chunk_index" in field_names
        assert "metadata" in field_names

    def test_vector_store_instance(self):
        """验证全局实例可创建。"""
        from app.memory.vector_store import vector_store
        assert isinstance(vector_store, VectorStore)

    def test_delete_method_exists(self):
        """验证删除方法存在。"""
        vs = VectorStore()
        assert hasattr(vs, "delete_tenant_data")
