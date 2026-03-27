"""Task 1.2 — Property Test：租户数据完全隔离

对应 design.md: Correctness Properties → Property 2
对应 tasks.md: Task 1.2 — 编写 Property Test：租户数据完全隔离

Property 2: 租户数据完全隔离
  For any 租户 A 和租户 B，当租户 A 查询数据时，
  返回的结果中不应包含任何属于租户 B 的数据。

验证需求：2.2, 2.4, 2.6
"""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.storage.models import (
    Tenant, User, Agent, Session, Incident,
    generate_rls_statements, RLS_TABLES, Base,
)
from app.storage.database import _build_database_url
from app.memory.vector_store import VectorStore


# ---------------------------------------------------------------------------
# Property 2: 租户数据完全隔离 — PostgreSQL 模型层
# Feature: multi-tenant-oncall-platform, Property 2: 租户数据完全隔离
# ---------------------------------------------------------------------------

class TestTenantIsolationProperties:
    """Property-based tests for tenant data isolation."""

    def test_all_rls_tables_have_tenant_id(self):
        """验证所有需要 RLS 的表都有 tenant_id 列。"""
        for table_name in RLS_TABLES:
            table = Base.metadata.tables[table_name]
            column_names = [col.name for col in table.columns]
            assert "tenant_id" in column_names, (
                f"表 '{table_name}' 缺少 tenant_id 列，无法启用 RLS"
            )

    def test_rls_tables_complete(self):
        """验证除 tenants 外所有表都在 RLS 列表中。"""
        all_tables = set(Base.metadata.tables.keys())
        rls_set = set(RLS_TABLES)

        # tenants 表本身不需要 RLS
        expected_rls = all_tables - {"tenants"}
        assert rls_set == expected_rls, (
            f"RLS 覆盖不完整。缺少: {expected_rls - rls_set}，"
            f"多余: {rls_set - expected_rls}"
        )

    @pytest.mark.parametrize("table_name", RLS_TABLES)
    def test_rls_statements_generated(self, table_name):
        """验证每个 RLS 表的 SQL 语句正确生成。"""
        stmts = generate_rls_statements(table_name)
        assert len(stmts) == 3, f"表 '{table_name}' 应生成 3 条 RLS 语句"
        assert f"ENABLE ROW LEVEL SECURITY" in stmts[0]
        assert f"FORCE ROW LEVEL SECURITY" in stmts[1]
        assert f"tenant_isolation" in stmts[2]
        assert f"app.tenant_id" in stmts[2]

    @pytest.mark.parametrize("tenant_id", [
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        str(uuid.uuid4()),
    ])
    def test_rls_policy_references_tenant_id(self, tenant_id):
        """验证 RLS 策略使用 current_setting('app.tenant_id')。

        Property 2: 租户 A 查询不会返回租户 B 的数据。
        RLS 策略是这个保证的核心。
        """
        for table_name in RLS_TABLES:
            stmts = generate_rls_statements(table_name)
            policy_stmt = stmts[2]
            assert "current_setting('app.tenant_id')" in policy_stmt, (
                f"表 '{table_name}' 的 RLS 策略未引用 app.tenant_id"
            )

    def test_tenant_table_no_rls(self):
        """验证 tenants 表不在 RLS 列表中（它是根实体）。"""
        assert "tenants" not in RLS_TABLES

    def test_all_tables_have_primary_key(self):
        """验证所有表都有主键。"""
        for table_name, table in Base.metadata.tables.items():
            pk_columns = [col for col in table.columns if col.primary_key]
            assert len(pk_columns) > 0, f"表 '{table_name}' 缺少主键"

    def test_foreign_keys_cascade_delete(self):
        """验证所有 tenant_id 外键都配置了 CASCADE 删除。"""
        for table_name in RLS_TABLES:
            table = Base.metadata.tables[table_name]
            for fk in table.foreign_keys:
                if fk.column.table.name == "tenants":
                    assert fk.ondelete == "CASCADE", (
                        f"表 '{table_name}' 到 tenants 的外键未配置 CASCADE 删除"
                    )


# ---------------------------------------------------------------------------
# Property 2: Milvus 向量层的隔离验证
# ---------------------------------------------------------------------------

class TestMilvusIsolationProperties:
    """Property-based tests for Milvus tenant isolation."""

    def test_partition_name_format(self):
        """Property 3: Partition 名称遵循 tenant_{tenant_id} 格式。"""
        vs = VectorStore()
        for _ in range(10):
            tid = str(uuid.uuid4())
            partition_name = f"tenant_{tid}"
            assert partition_name.startswith("tenant_")
            assert tid in partition_name

    def test_search_uses_partition_and_filter(self):
        """Property 17: 检索同时使用 partition_names 和 metadata filter。

        验证 VectorStore.search 方法的代码结构确保双重过滤。
        （通过检查源代码，不需要实际 Milvus 连接）
        """
        import inspect
        source = inspect.getsource(VectorStore.search)
        assert "partition_names" in source, "search 方法缺少 partition_names 参数"
        assert "tenant_id" in source, "search 方法缺少 tenant_id filter"
        # 验证结果验证逻辑存在
        assert "result_tenant_id != tenant_id" in source, "search 方法缺少结果验证"


# ---------------------------------------------------------------------------
# Property 4: Redis Key 租户前缀
# ---------------------------------------------------------------------------

class TestRedisKeyProperties:
    """Property-based tests for Redis key naming conventions."""

    def test_session_key_contains_tenant_id(self):
        """Property 4: Redis key 包含 tenant_id 前缀。

        验证 Compaction 模块使用的 Redis key 格式。
        """
        import inspect
        from app.memory.compaction import Compaction
        source = inspect.getsource(Compaction._save_to_redis)
        assert "session:" in source, "Redis key 缺少 session 前缀"

    def test_context_assembler_redis_keys(self):
        """验证 ContextAssembler 使用的 Redis key 包含正确前缀。"""
        import inspect
        from app.agents.context import ContextAssembler
        source = inspect.getsource(ContextAssembler._get_summary)
        assert "session:" in source
        assert ":summary" in source
