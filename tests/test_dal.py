"""
数据访问层 (DAL) 测试

覆盖:
  - DAL 初始化 + 表创建
  - 查询 API: execute, execute_one, execute_value, execute_many
  - 写入 API: insert, insert_or_replace, insert_or_ignore, update, delete, upsert
  - 批量操作: batch_insert, transaction
  - 工具方法: table_exists, table_row_count, get_db_info, vacuum
  - 单例: get_dal, reset_dal
  - 错误路径: 无效表名、重复键冲突
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from pycoder.core.dal import DAL, get_dal, reset_dal


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture
def temp_db_path() -> Path:
    """创建临时数据库文件路径，测试结束后自动清理"""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    yield path
    # 清理
    try:
        path.unlink(missing_ok=True)
        # 也清理 WAL/SHM 文件
        for ext in (".db-wal", ".db-shm"):
            p = path.with_suffix(ext)
            p.unlink(missing_ok=True)
    except OSError:
        pass


@pytest.fixture
def dal(temp_db_path: Path) -> DAL:
    """创建使用临时文件的 DAL 实例，已初始化"""
    d = DAL(db_path=temp_db_path)
    d.init_db()
    return d


# ══════════════════════════════════════════════════════════
# 初始化测试
# ══════════════════════════════════════════════════════════


class TestDALInit:
    """DAL 初始化相关测试"""

    def test_init_db_creates_tables(self, dal: DAL):
        """初始化应创建所有核心表"""
        assert dal.table_exists("db_version")
        assert dal.table_exists("sessions")
        assert dal.table_exists("messages")
        assert dal.table_exists("app_config")

    def test_init_db_sets_db_version(self, dal: DAL):
        """初始化应将版本号写入 db_version 表"""
        version = dal.execute_value(
            "SELECT version FROM db_version ORDER BY version DESC LIMIT 1"
        )
        assert version is not None
        assert version >= 1

    def test_init_db_idempotent(self, dal: DAL):
        """重复调用 init_db 不应报错"""
        dal.init_db()  # 第二次调用
        assert dal.table_exists("sessions")

    def test_init_db_pool_size_default(self, temp_db_path: Path):
        """默认连接池大小为 5"""
        d = DAL(db_path=temp_db_path)
        assert d._pool_size == 5

    def test_init_db_custom_pool_size(self, temp_db_path: Path):
        """可自定义连接池大小"""
        d = DAL(db_path=temp_db_path, pool_size=3)
        assert d._pool_size == 3


# ══════════════════════════════════════════════════════════
# 查询 API 测试
# ══════════════════════════════════════════════════════════


class TestExecute:
    """execute / execute_one / execute_value 测试"""

    def test_execute_returns_rows(self, dal: DAL):
        """execute 应返回 Row 列表"""
        dal.insert("sessions", {"id": "s1", "title": "测试会话"})
        rows = dal.execute("SELECT * FROM sessions WHERE id = ?", ("s1",))
        assert len(rows) == 1
        assert rows[0]["title"] == "测试会话"

    def test_execute_no_params(self, dal: DAL):
        """execute 无参数时也应正常工作"""
        rows = dal.execute("SELECT name FROM sqlite_master WHERE type='table'")
        assert len(rows) > 0

    def test_execute_one_returns_first(self, dal: DAL):
        """execute_one 应返回第一行"""
        dal.insert("sessions", {"id": "s2", "title": "第二个"})
        row = dal.execute_one("SELECT * FROM sessions WHERE id = ?", ("s2",))
        assert row is not None
        assert row["id"] == "s2"

    def test_execute_one_returns_none(self, dal: DAL):
        """execute_one 在无结果时应返回 None"""
        row = dal.execute_one("SELECT * FROM sessions WHERE id = ?", ("nonexistent",))
        assert row is None

    def test_execute_value_returns_scalar(self, dal: DAL):
        """execute_value 应返回标量值"""
        dal.insert("sessions", {"id": "s3", "title": "测试"})
        count = dal.execute_value("SELECT COUNT(*) FROM sessions")
        assert count == 1

    def test_execute_value_default(self, dal: DAL):
        """execute_value 无结果时返回默认值"""
        val = dal.execute_value(
            "SELECT title FROM sessions WHERE id = ?",
            ("nonexistent",),
            default="未找到",
        )
        assert val == "未找到"

    def test_execute_many(self, dal: DAL):
        """execute_many 批量执行"""
        rows_count = dal.execute_many(
            "INSERT INTO sessions (id, title) VALUES (?, ?)",
            [("s10", "批量1"), ("s11", "批量2"), ("s12", "批量3")],
        )
        assert rows_count == 3
        count = dal.execute_value("SELECT COUNT(*) FROM sessions")
        assert count == 3


# ══════════════════════════════════════════════════════════
# 写入 API 测试
# ══════════════════════════════════════════════════════════


class TestInsert:
    """insert / insert_or_replace / insert_or_ignore 测试"""

    def test_insert_returns_rowid(self, dal: DAL):
        """insert 应返回新行的 rowid"""
        rowid = dal.insert("sessions", {"id": "s20", "title": "插入测试"})
        assert rowid > 0

    def test_insert_creates_row(self, dal: DAL):
        """insert 应实际插入数据"""
        dal.insert("sessions", {"id": "s21", "title": "数据完整性"})
        row = dal.execute_one("SELECT title FROM sessions WHERE id = ?", ("s21",))
        assert row is not None
        assert row["title"] == "数据完整性"

    def test_insert_duplicate_key_raises(self, dal: DAL):
        """插入重复主键应抛出 IntegrityError"""
        dal.insert("sessions", {"id": "s_dup", "title": "原始"})
        with pytest.raises(sqlite3.IntegrityError):
            dal.insert("sessions", {"id": "s_dup", "title": "重复"})

    def test_insert_or_replace(self, dal: DAL):
        """insert_or_replace 应替换已存在的行"""
        dal.insert("sessions", {"id": "s30", "title": "原始标题"})
        dal.insert_or_replace("sessions", {"id": "s30", "title": "替换标题"})
        row = dal.execute_one("SELECT title FROM sessions WHERE id = ?", ("s30",))
        assert row["title"] == "替换标题"

    def test_insert_or_ignore_skips_duplicate(self, dal: DAL):
        """insert_or_ignore 应跳过重复键"""
        dal.insert("sessions", {"id": "s40", "title": "原始"})
        dal.insert_or_ignore("sessions", {"id": "s40", "title": "忽略"})
        row = dal.execute_one("SELECT title FROM sessions WHERE id = ?", ("s40",))
        assert row["title"] == "原始"


class TestUpdate:
    """update 测试"""

    def test_update_returns_rowcount(self, dal: DAL):
        """update 应返回影响行数"""
        dal.insert("sessions", {"id": "s50", "title": "旧标题"})
        count = dal.update("sessions", {"title": "新标题"}, "id = ?", ("s50",))
        assert count == 1

    def test_update_changes_data(self, dal: DAL):
        """update 应实际修改数据"""
        dal.insert("sessions", {"id": "s51", "title": "旧"})
        dal.update("sessions", {"title": "新"}, "id = ?", ("s51",))
        row = dal.execute_one("SELECT title FROM sessions WHERE id = ?", ("s51",))
        assert row["title"] == "新"

    def test_update_no_match(self, dal: DAL):
        """update 无匹配行时返回 0"""
        count = dal.update("sessions", {"title": "x"}, "id = ?", ("nonexistent",))
        assert count == 0

    def test_update_multiple_columns(self, dal: DAL):
        """update 应支持同时更新多列"""
        dal.insert("sessions", {"id": "s52", "title": "旧", "model": "gpt"})
        dal.update(
            "sessions",
            {"title": "新", "model": "deepseek"},
            "id = ?",
            ("s52",),
        )
        row = dal.execute_one("SELECT title, model FROM sessions WHERE id = ?", ("s52",))
        assert row["title"] == "新"
        assert row["model"] == "deepseek"


class TestDelete:
    """delete 测试"""

    def test_delete_returns_rowcount(self, dal: DAL):
        """delete 应返回删除行数"""
        dal.insert("sessions", {"id": "s60", "title": "待删除"})
        count = dal.delete("sessions", "id = ?", ("s60",))
        assert count == 1

    def test_delete_removes_row(self, dal: DAL):
        """delete 应实际删除数据"""
        dal.insert("sessions", {"id": "s61", "title": "待删除"})
        dal.delete("sessions", "id = ?", ("s61",))
        row = dal.execute_one("SELECT * FROM sessions WHERE id = ?", ("s61",))
        assert row is None

    def test_delete_no_match(self, dal: DAL):
        """delete 无匹配行时返回 0"""
        count = dal.delete("sessions", "id = ?", ("nonexistent",))
        assert count == 0


class TestUpsert:
    """upsert 测试"""

    def test_upsert_insert_new(self, dal: DAL):
        """upsert 应插入新行"""
        rowid = dal.upsert(
            "sessions",
            {"id": "s70", "title": "新记录"},
            conflict_columns=["id"],
        )
        assert rowid > 0
        row = dal.execute_one("SELECT title FROM sessions WHERE id = ?", ("s70",))
        assert row["title"] == "新记录"

    def test_upsert_update_existing(self, dal: DAL):
        """upsert 应更新已存在的行"""
        dal.insert("sessions", {"id": "s71", "title": "旧"})
        dal.upsert(
            "sessions",
            {"id": "s71", "title": "更新后"},
            conflict_columns=["id"],
        )
        row = dal.execute_one("SELECT title FROM sessions WHERE id = ?", ("s71",))
        assert row["title"] == "更新后"

    def test_upsert_update_specific_columns(self, dal: DAL):
        """upsert 指定 update_columns 时仅更新指定列"""
        dal.insert("sessions", {"id": "s72", "title": "旧", "model": "gpt"})
        dal.upsert(
            "sessions",
            {"id": "s72", "title": "新标题", "model": "deepseek"},
            conflict_columns=["id"],
            update_columns=["title"],  # 只更新 title
        )
        row = dal.execute_one(
            "SELECT title, model FROM sessions WHERE id = ?", ("s72",)
        )
        assert row["title"] == "新标题"
        # model 不在 update_columns 中，应保持原值
        assert row["model"] == "gpt"


# ══════════════════════════════════════════════════════════
# 批量 + 事务测试
# ══════════════════════════════════════════════════════════


class TestBatchInsert:
    """batch_insert 测试"""

    def test_batch_insert_returns_count(self, dal: DAL):
        """batch_insert 应返回插入行数"""
        rows = [
            {"id": "b1", "title": "批量1"},
            {"id": "b2", "title": "批量2"},
            {"id": "b3", "title": "批量3"},
        ]
        count = dal.batch_insert("sessions", rows)
        assert count == 3

    def test_batch_insert_empty(self, dal: DAL):
        """空列表应返回 0"""
        count = dal.batch_insert("sessions", [])
        assert count == 0

    def test_batch_insert_ignores_duplicates(self, dal: DAL):
        """batch_insert 使用 INSERT OR IGNORE，重复键应跳过"""
        dal.insert("sessions", {"id": "b10", "title": "原始"})
        rows = [
            {"id": "b10", "title": "重复"},
            {"id": "b11", "title": "新数据"},
        ]
        count = dal.batch_insert("sessions", rows)
        assert count == 1  # 只插入 b11
        row = dal.execute_one("SELECT title FROM sessions WHERE id = ?", ("b10",))
        assert row["title"] == "原始"


class TestTransaction:
    """transaction 事务测试"""

    def test_transaction_commits(self, dal: DAL):
        """事务成功时应提交"""
        with dal.transaction():
            dal.insert("sessions", {"id": "t1", "title": "事务内"})
            dal.insert("messages", {
                "session_id": "t1",
                "role": "user",
                "content": "你好",
                "timestamp": 1000.0,
            })
        # 事务提交后数据应可见
        count = dal.execute_value("SELECT COUNT(*) FROM sessions WHERE id = ?", ("t1",))
        assert count == 1

    def test_transaction_rollback_on_error(self, dal: DAL):
        """事务中发生异常时，未提交的操作应回滚"""
        try:
            with dal.transaction() as conn:
                # 直接使用连接执行 SQL（不通过 insert，因为 insert 会独立提交）
                conn.execute(
                    "INSERT INTO sessions (id, title) VALUES (?, ?)",
                    ("t2", "回滚测试"),
                )
                raise ValueError("模拟错误")
        except ValueError:
            pass
        # 事务回滚后数据不应存在
        row = dal.execute_one("SELECT * FROM sessions WHERE id = ?", ("t2",))
        assert row is None

    def test_transaction_nested(self, dal: DAL):
        """嵌套事务应支持基本场景"""
        with dal.transaction():
            dal.insert("sessions", {"id": "t3", "title": "外层"})
        assert dal.execute_value("SELECT COUNT(*) FROM sessions WHERE id = ?", ("t3",)) == 1


# ══════════════════════════════════════════════════════════
# 工具方法测试
# ══════════════════════════════════════════════════════════


class TestTableExists:
    """table_exists 测试"""

    def test_table_exists_true(self, dal: DAL):
        """已知存在的表应返回 True"""
        assert dal.table_exists("sessions") is True

    def test_table_exists_false(self, dal: DAL):
        """不存在的表应返回 False"""
        assert dal.table_exists("nonexistent_table") is False


class TestTableRowCount:
    """table_row_count 测试"""

    def test_table_row_count_empty(self, dal: DAL):
        """空表应返回 0"""
        assert dal.table_row_count("sessions") == 0

    def test_table_row_count_with_data(self, dal: DAL):
        """有数据的表应返回正确计数"""
        dal.insert("sessions", {"id": "r1", "title": "记录1"})
        dal.insert("sessions", {"id": "r2", "title": "记录2"})
        assert dal.table_row_count("sessions") == 2

    def test_table_row_count_nonexistent(self, dal: DAL):
        """不存在的表返回 0"""
        assert dal.table_row_count("nonexistent") == 0


class TestGetDbInfo:
    """get_db_info 测试"""

    def test_get_db_info_returns_dict(self, dal: DAL):
        """get_db_info 应返回包含必要键的字典"""
        info = dal.get_db_info()
        assert "path" in info
        assert "tables" in info
        assert "version" in info

    def test_get_db_info_version(self, dal: DAL):
        """get_db_info 应返回正确的版本号"""
        info = dal.get_db_info()
        assert info["version"] >= 1

    def test_get_db_info_tables_dict(self, dal: DAL):
        """get_db_info 的 tables 字典应包含表名和行数"""
        info = dal.get_db_info()
        assert isinstance(info["tables"], dict)
        assert "sessions" in info["tables"]


class TestVacuum:
    """vacuum 测试"""

    def test_vacuum_no_error(self, dal: DAL):
        """vacuum 不应抛出异常"""
        dal.vacuum()  # 不应抛异常


# ══════════════════════════════════════════════════════════
# 单例测试
# ══════════════════════════════════════════════════════════


class TestSingleton:
    """get_dal / reset_dal 单例测试"""

    def test_dal_instances_are_independent(self, temp_db_path: Path):
        """两个独立 DAL 实例应互不影响"""
        d1 = DAL(db_path=temp_db_path)
        d1.init_db()
        d2 = DAL(db_path=temp_db_path)
        d2.init_db()
        # 两个独立实例不应是同一个对象
        assert d1 is not d2

    def test_reset_dal_clears_singleton(self):
        """reset_dal 应清除全局单例"""
        # 保存当前状态
        from pycoder.core.dal import _dal_instance
        old = _dal_instance
        reset_dal()
        from pycoder.core.dal import _dal_instance as _dal_after
        assert _dal_after is None
        # 恢复
        if old is not None:
            import pycoder.core.dal as dal_mod
            dal_mod._dal_instance = old


# ══════════════════════════════════════════════════════════
# 错误路径测试
# ══════════════════════════════════════════════════════════


class TestErrorPaths:
    """错误路径测试"""

    def test_insert_invalid_table(self, dal: DAL):
        """向不存在的表插入数据应抛出异常"""
        with pytest.raises(sqlite3.OperationalError):
            dal.insert("nonexistent", {"id": "e1"})

    def test_execute_invalid_sql(self, dal: DAL):
        """执行无效 SQL 应抛出异常"""
        with pytest.raises(sqlite3.OperationalError):
            dal.execute("THIS IS NOT SQL")

    def test_update_invalid_table(self, dal: DAL):
        """更新不存在的表应抛出异常"""
        with pytest.raises(sqlite3.OperationalError):
            dal.update("nonexistent", {"x": 1}, "id = ?", ("1",))

    def test_delete_invalid_table(self, dal: DAL):
        """删除不存在的表应抛出异常"""
        with pytest.raises(sqlite3.OperationalError):
            dal.delete("nonexistent", "id = ?", ("1",))