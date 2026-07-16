"""
数据库 Schema 测试

覆盖:
  - SCHEMA_SQL 有效性（在临时数据库中执行不报错）
  - DB_VERSION 常量
  - Tables 表名常量
  - _get_env_db_path 环境变量覆盖
  - 所有核心表的存在性验证
  - 索引创建验证
  - 外键约束验证
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pycoder.core.db_schema import (
    DB_VERSION,
    SCHEMA_SQL,
    UNIFIED_DB_PATH,
    Tables,
    _get_env_db_path,
)


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture
def schema_db() -> sqlite3.Connection:
    """创建临时数据库并执行 SCHEMA_SQL"""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = tmp.name

    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.row_factory = sqlite3.Row

    yield conn

    conn.close()
    try:
        Path(db_path).unlink(missing_ok=True)
        for ext in (".db-wal", ".db-shm"):
            Path(db_path + ext).unlink(missing_ok=True) if False else None
    except OSError:
        pass


# ══════════════════════════════════════════════════════════
# DB_VERSION 测试
# ══════════════════════════════════════════════════════════


class TestDBVersion:
    """数据库版本常量测试"""

    def test_db_version_is_positive(self):
        """DB_VERSION 应为正整数"""
        assert DB_VERSION > 0

    def test_db_version_is_integer(self):
        """DB_VERSION 应为整数类型"""
        assert isinstance(DB_VERSION, int)

    def test_db_version_at_least_2(self):
        """当前版本至少为 2（v2 schema）"""
        assert DB_VERSION >= 2


# ══════════════════════════════════════════════════════════
# SCHEMA_SQL 测试
# ══════════════════════════════════════════════════════════


class TestSchemaSQL:
    """SCHEMA_SQL 验证"""

    def test_schema_sql_not_empty(self):
        """SCHEMA_SQL 不应为空"""
        assert len(SCHEMA_SQL) > 0

    def test_schema_sql_contains_pragmas(self):
        """SCHEMA_SQL 应包含 WAL 和 FK 配置"""
        assert "PRAGMA journal_mode=WAL" in SCHEMA_SQL
        assert "PRAGMA foreign_keys=ON" in SCHEMA_SQL

    def test_schema_sql_contains_version_table(self):
        """SCHEMA_SQL 应包含 db_version 表"""
        assert "CREATE TABLE IF NOT EXISTS db_version" in SCHEMA_SQL

    def test_schema_executes_without_error(self, schema_db: sqlite3.Connection):
        """SCHEMA_SQL 在空数据库中执行不应报错"""
        # 如果 executescript 失败，fixture 会抛异常
        tables = schema_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        assert len(tables) > 0

    def test_schema_is_idempotent(self, schema_db: sqlite3.Connection):
        """重复执行 SCHEMA_SQL 不应报错（IF NOT EXISTS）"""
        schema_db.executescript(SCHEMA_SQL)  # 第二次执行
        tables = schema_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        assert len(tables) > 0


# ══════════════════════════════════════════════════════════
# 表存在性验证
# ══════════════════════════════════════════════════════════


class TestTableExistence:
    """所有核心表应在 Schema 中定义"""

    CORE_TABLES = [
        "db_version",
        "sessions",
        "messages",
        "memory_items",
        "evolution_error_patterns",
        "evolution_fix_history",
        "evolution_records",
        "evolution_quality_snapshots",
        "evolution_learning_events",
        "cloud_users",
        "cloud_api_keys",
        "cloud_usage_log",
        "team_workspaces",
        "team_members",
        "team_review_requests",
        "team_activities",
        "app_config",
        "plugin_data",
    ]

    @pytest.mark.parametrize("table_name", CORE_TABLES)
    def test_table_exists(self, schema_db: sqlite3.Connection, table_name: str):
        """每张核心表都应存在"""
        row = schema_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        assert row is not None, f"表 {table_name} 不存在"


# ══════════════════════════════════════════════════════════
# 索引验证
# ══════════════════════════════════════════════════════════


class TestIndexes:
    """索引创建验证"""

    EXPECTED_INDEXES = [
        "idx_memory_key",
        "idx_memory_importance",
        "idx_memory_session",
        "idx_evo_ts",
        "idx_evo_outcome",
        "idx_evo_err_sig",
        "idx_evo_fix_ts",
        "idx_qual_ts",
        "idx_msg_session",
        "idx_sessions_updated",
        "idx_cloud_usage_user",
        "idx_cloud_usage_date",
        "idx_team_members_ws",
        "idx_team_reviews_ws",
        "idx_team_activities_ws",
        "idx_plugin_data_plugin",
    ]

    @pytest.mark.parametrize("index_name", EXPECTED_INDEXES)
    def test_index_exists(self, schema_db: sqlite3.Connection, index_name: str):
        """每个预期索引都应存在"""
        row = schema_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (index_name,),
        ).fetchone()
        assert row is not None, f"索引 {index_name} 不存在"


# ══════════════════════════════════════════════════════════
# 外键约束验证
# ══════════════════════════════════════════════════════════


class TestForeignKeys:
    """外键约束验证"""

    def test_messages_fk_session(self, schema_db: sqlite3.Connection):
        """messages 表应有外键引用 sessions"""
        # 插入孤儿消息应失败
        with pytest.raises(sqlite3.IntegrityError):
            schema_db.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) "
                "VALUES (?, ?, ?, ?)",
                ("nonexistent", "user", "测试", 1000.0),
            )

    def test_cloud_usage_log_fk_user(self, schema_db: sqlite3.Connection):
        """cloud_usage_log 表应有外键引用 cloud_users"""
        with pytest.raises(sqlite3.IntegrityError):
            schema_db.execute(
                "INSERT INTO cloud_usage_log (id, user_id) VALUES (?, ?)",
                ("log1", "nonexistent_user"),
            )

    def test_team_members_fk_workspace(self, schema_db: sqlite3.Connection):
        """team_members 表应有外键引用 team_workspaces"""
        with pytest.raises(sqlite3.IntegrityError):
            schema_db.execute(
                "INSERT INTO team_members (id, workspace_id, display_name) "
                "VALUES (?, ?, ?)",
                ("m1", "nonexistent_ws", "测试成员"),
            )


# ══════════════════════════════════════════════════════════
# Tables 常量类测试
# ══════════════════════════════════════════════════════════


class TestTables:
    """Tables 表名常量测试"""

    def test_tables_has_sessions(self):
        """Tables 应包含 SESSIONS"""
        assert Tables.SESSIONS == "sessions"

    def test_tables_has_messages(self):
        """Tables 应包含 MESSAGES"""
        assert Tables.MESSAGES == "messages"

    def test_tables_has_memory_items(self):
        """Tables 应包含 MEMORY_ITEMS"""
        assert Tables.MEMORY_ITEMS == "memory_items"

    def test_tables_all_are_strings(self):
        """所有 Tables 常量应为字符串"""
        for attr_name in dir(Tables):
            if attr_name.isupper() and not attr_name.startswith("_"):
                value = getattr(Tables, attr_name)
                assert isinstance(value, str), f"Tables.{attr_name} 不是字符串"

    def test_tables_all_match_schema(self, schema_db: sqlite3.Connection):
        """所有 Tables 常量对应的表应在 Schema 中存在"""
        existing = schema_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        existing_names = {r[0] for r in existing}

        for attr_name in dir(Tables):
            if attr_name.isupper() and not attr_name.startswith("_"):
                table_name = getattr(Tables, attr_name)
                assert table_name in existing_names, (
                    f"Tables.{attr_name} = '{table_name}' 不在 Schema 中"
                )


# ══════════════════════════════════════════════════════════
# _get_env_db_path 测试
# ══════════════════════════════════════════════════════════


class TestGetEnvDbPath:
    """环境变量路径覆盖测试"""

    def test_default_path_is_home(self):
        """默认路径应为 ~/.pycoder/unified.db"""
        with patch.dict(os.environ, {}, clear=True):
            path = _get_env_db_path()
            assert path == UNIFIED_DB_PATH

    def test_env_var_overrides_path(self):
        """PYCODER_DB_PATH 环境变量应覆盖默认路径"""
        custom = "/tmp/custom_pycoder.db" if os.name != "nt" else "C:/temp/custom_pycoder.db"
        with patch.dict(os.environ, {"PYCODER_DB_PATH": custom}, clear=True):
            path = _get_env_db_path()
            assert path == Path(custom)

    def test_env_var_empty_uses_default(self):
        """空环境变量应使用默认路径"""
        with patch.dict(os.environ, {"PYCODER_DB_PATH": ""}, clear=True):
            path = _get_env_db_path()
            assert path == UNIFIED_DB_PATH


# ══════════════════════════════════════════════════════════
# 列结构验证
# ══════════════════════════════════════════════════════════


class TestColumnStructure:
    """核心表列结构验证"""

    def test_sessions_has_required_columns(self, schema_db: sqlite3.Connection):
        """sessions 表应有核心列"""
        columns = {
            r[1]
            for r in schema_db.execute("PRAGMA table_info(sessions)").fetchall()
        }
        required = {"id", "created_at", "updated_at", "model", "title", "message_count"}
        assert required.issubset(columns), f"缺少列: {required - columns}"

    def test_messages_has_required_columns(self, schema_db: sqlite3.Connection):
        """messages 表应有核心列"""
        columns = {
            r[1]
            for r in schema_db.execute("PRAGMA table_info(messages)").fetchall()
        }
        required = {"id", "session_id", "role", "content", "timestamp"}
        assert required.issubset(columns), f"缺少列: {required - columns}"

    def test_app_config_has_required_columns(self, schema_db: sqlite3.Connection):
        """app_config 表应有核心列"""
        columns = {
            r[1]
            for r in schema_db.execute("PRAGMA table_info(app_config)").fetchall()
        }
        required = {"key", "value", "kind", "updated_at"}
        assert required.issubset(columns), f"缺少列: {required - columns}"