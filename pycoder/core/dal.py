"""
数据访问层 (Data Access Layer) — 统一数据库接口

职责:
    1. 提供所有模块访问 unified.db 的标准 API
    2. 连接池管理 + WAL 模式 + 线程安全
    3. 查询构建器 (QueryBuilder) — 防 SQL 注入
    4. 事务支持 + 批量操作
    5. Schema 版本管理 + 自动升级

设计约束:
    - 所有数据库操作必须通过 DAL，禁止模块直接 sqlite3.connect()
    - 查询必须使用参数化（防注入）
    - 写入操作默认在事务中
    - 读取操作使用连接池，写入操作串行化

用法:
    from pycoder.core.dal import DAL

    dal = DAL()
    dal.init_db()  # 首次调用时自动初始化 schema

    # 标准查询
    rows = dal.execute("SELECT * FROM sessions WHERE id = ?", (sid,))
    # 插入
    dal.insert("sessions", {"id": "abc", "title": "test"})
    # 事务
    with dal.transaction():
        dal.insert("sessions", {...})
        dal.insert("messages", {...})
"""

from __future__ import annotations

import logging
import queue
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pycoder.core.db_schema import (
    DB_VERSION,
    SCHEMA_SQL,
    _get_env_db_path,
    Tables,
)

logger = logging.getLogger(__name__)

# 全局单例锁
_dal_instance: DAL | None = None
_dal_lock = threading.Lock()


def get_dal() -> "DAL":
    """获取全局 DAL 单例"""
    global _dal_instance
    if _dal_instance is None:
        with _dal_lock:
            if _dal_instance is None:
                _dal_instance = DAL()
                _dal_instance.init_db()
    return _dal_instance


def reset_dal() -> None:
    """重置 DAL 单例（测试用）"""
    global _dal_instance
    with _dal_lock:
        _dal_instance = None


class DAL:
    """统一数据访问层

    特性:
        - 连接池 (默认 5 个连接)
        - 线程本地连接缓存
        - WAL 模式 + FK 强制
        - 参数化查询
        - 事务管理器
        - Schema 版本自动升级
    """

    def __init__(self, db_path: str | Path | None = None, pool_size: int = 5):
        self._db_path = Path(db_path) if db_path else _get_env_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._pool_size = pool_size
        self._pool: queue.Queue[sqlite3.Connection] = queue.Queue(pool_size)
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._write_lock = threading.Lock()  # SQLite 写串行化
        self._initialized = False

    # ══════════════════════════════════════════════════════
    # 初始化
    # ══════════════════════════════════════════════════════

    def init_db(self) -> None:
        """初始化数据库：创建表 + 检测版本"""
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self._execute_schema()
            self._check_and_upgrade()
            self._initialized = True
            logger.info("dal_initialized: path=%s pool=%d", self._db_path, self._pool_size)

    def _execute_schema(self) -> None:
        """执行建表 DDL"""
        conn = self._new_raw_conn()
        try:
            conn.executescript(SCHEMA_SQL)

            # 写入当前版本
            existing = conn.execute(
                "SELECT version FROM db_version ORDER BY version DESC LIMIT 1"
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO db_version (version, description) VALUES (?, ?)",
                    (DB_VERSION, "Initial unified schema"),
                )
            conn.commit()
        finally:
            conn.close()

    def _check_and_upgrade(self) -> None:
        """检查并执行 schema 版本升级"""
        conn = self._new_raw_conn()
        try:
            row = conn.execute(
                "SELECT version FROM db_version ORDER BY version DESC LIMIT 1"
            ).fetchone()
            current = row[0] if row else 0

            if current < DB_VERSION:
                logger.info(
                    "dal_upgrade_needed: from=%d to=%d", current, DB_VERSION,
                )
                # 执行升级迁移（当前 v2）
                if current < 2:
                    self._migrate_v1_to_v2(conn)
                conn.execute(
                    "INSERT INTO db_version (version, description) VALUES (?, ?)",
                    (DB_VERSION, f"Auto-upgrade from v{current}"),
                )
                conn.commit()
                logger.info("dal_upgraded: to=v%d", DB_VERSION)
        finally:
            conn.close()

    def _migrate_v1_to_v2(self, conn: sqlite3.Connection) -> None:
        """v1 → v2 迁移：从旧多库文件合并数据

        仅在旧数据库文件存在且新表为空时执行。
        """
        migrations = [
            # (旧路径, 旧表名, 新表名, 字段映射)
            ("sessions.db", "sessions", Tables.SESSIONS, None),
            ("sessions.db", "messages", Tables.MESSAGES, None),
            ("memory.db", "session_memories", Tables.MEMORY_ITEMS, self._map_memory_row),
            ("long_term_memory.db", "long_term_memory", Tables.MEMORY_ITEMS, self._map_ltm_row),
            ("knowledge.db", "error_patterns", Tables.EVO_ERROR_PATTERNS, None),
            ("knowledge.db", "fix_history", Tables.EVO_FIX_HISTORY, None),
            ("knowledge.db", "project_knowledge", Tables.EVO_LEARNING, self._map_pk_row),
            ("metrics.db", "evolution_records", Tables.EVO_RECORDS, None),
            ("metrics.db", "quality_snapshots", Tables.EVO_QUALITY, None),
            ("metrics.db", "learning_events", Tables.EVO_LEARNING, None),
            ("cloud.db", "users", Tables.CLOUD_USERS, None),
            ("cloud.db", "api_keys", Tables.CLOUD_API_KEYS, None),
            ("cloud.db", "usage_log", Tables.CLOUD_USAGE_LOG, None),
            ("teams.db", "workspaces", Tables.TEAM_WORKSPACES, None),
            ("teams.db", "members", Tables.TEAM_MEMBERS, None),
            ("teams.db", "review_requests", Tables.TEAM_REVIEW, None),
            ("teams.db", "activities", Tables.TEAM_ACTIVITIES, None),
        ]

        base_dir = Path.home() / ".pycoder"
        migrated_count = 0

        for old_file, old_table, new_table, mapper in migrations:
            old_path = base_dir / old_file
            if not old_path.exists():
                continue

            # 检查新表是否已有数据
            count = conn.execute(
                f"SELECT COUNT(*) FROM {new_table}"
            ).fetchone()[0]
            if count > 0:
                continue  # 已经迁移过

            try:
                old_conn = sqlite3.connect(str(old_path))
                old_rows = old_conn.execute(
                    f"SELECT * FROM {old_table}"
                ).fetchall()

                if not old_rows:
                    old_conn.close()
                    continue

                columns = [d[0] for d in old_conn.execute(
                    f"PRAGMA table_info({old_table})"
                ).fetchall()]

                for row in old_rows:
                    data = dict(zip(columns, row))
                    if mapper:
                        data = mapper(data, conn)
                    if data:
                        placeholders = ", ".join(["?"] * len(data))
                        col_names = ", ".join(data.keys())
                        conn.execute(
                            f"INSERT OR IGNORE INTO {new_table} ({col_names}) "
                            f"VALUES ({placeholders})",
                            tuple(data.values()),
                        )
                        migrated_count += 1

                old_conn.close()
                logger.info(
                    "dal_migrated: %s.%s → %s (%d rows)",
                    old_file, old_table, new_table, len(old_rows),
                )
            except Exception as e:
                logger.warning(
                    "dal_migrate_failed: %s.%s → %s: %s",
                    old_file, old_table, new_table, e,
                )

        if migrated_count > 0:
            logger.info("dal_migration_complete: total=%d rows", migrated_count)

    @staticmethod
    def _map_memory_row(data: dict, conn) -> dict | None:
        return {
            "key": data.get("key", data.get("fact_type", "")),
            "content": data.get("content", ""),
            "fact_type": data.get("fact_type", ""),
            "tags": data.get("tags", "[]"),
            "importance": data.get("importance", 0.5),
            "session_id": data.get("session_id", ""),
            "created_at": data.get("created_at", data.get("timestamp", 0)),
        }

    @staticmethod
    def _map_ltm_row(data: dict, conn) -> dict | None:
        return {
            "key": data.get("key", ""),
            "content": data.get("content", ""),
            "project": data.get("project", ""),
            "tags": data.get("tags", "[]"),
            "importance": data.get("importance", 0.5),
            "access_count": data.get("access_count", 0),
            "created_at": data.get("created_at", 0),
            "last_accessed": data.get("last_accessed", 0),
            "ttl_days": data.get("ttl_days", 90),
        }

    @staticmethod
    def _map_pk_row(data: dict, conn) -> dict | None:
        return {
            "event_type": data.get("entity_type", "project_knowledge"),
            "description": data.get("entity", ""),
            "data": data.get("metadata", "{}"),
            "timestamp": data.get("last_modified", 0),
        }

    # ══════════════════════════════════════════════════════
    # 连接管理
    # ══════════════════════════════════════════════════════

    def _get_conn(self) -> sqlite3.Connection:
        """获取连接：线程本地缓存 > 连接池 > 新建"""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            try:
                self._local.conn.execute("SELECT 1")
                return self._local.conn
            except (sqlite3.ProgrammingError, sqlite3.OperationalError):
                self._local.conn = None

        try:
            conn = self._pool.get_nowait()
        except queue.Empty:
            conn = self._new_conn()

        self._local.conn = conn
        return conn

    def _new_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        return conn

    def _new_raw_conn(self) -> sqlite3.Connection:
        """创建不受池管理的裸连接（用于 DDL/迁移）"""
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _return_conn(self, conn: sqlite3.Connection) -> None:
        """归还连接到池"""
        try:
            if self._pool.qsize() < self._pool_size:
                self._pool.put_nowait(conn)
            else:
                conn.close()
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

    # ══════════════════════════════════════════════════════
    # 查询 API
    # ══════════════════════════════════════════════════════

    def execute(
        self,
        sql: str,
        params: tuple | dict | None = None,
    ) -> list[sqlite3.Row]:
        """执行查询并返回结果列表

        Args:
            sql: 参数化 SQL 语句（使用 ? 占位符）
            params: 参数元组或字典

        Returns:
            sqlite3.Row 列表（支持 dict-like 访问）
        """
        conn = self._get_conn()
        try:
            if params:
                cursor = conn.execute(sql, params)
            else:
                cursor = conn.execute(sql)
            return cursor.fetchall()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._return_conn(conn)

    def execute_one(
        self,
        sql: str,
        params: tuple | dict | None = None,
    ) -> sqlite3.Row | None:
        """执行查询并返回第一行"""
        rows = self.execute(sql, params)
        return rows[0] if rows else None

    def execute_value(
        self,
        sql: str,
        params: tuple | dict | None = None,
        default: Any = None,
    ) -> Any:
        """执行查询并返回单个标量值"""
        row = self.execute_one(sql, params)
        if row:
            return row[0]
        return default

    def execute_many(
        self,
        sql: str,
        params_list: list[tuple] | list[dict],
    ) -> int:
        """批量执行相同 SQL（executemany）

        Returns:
            影响的行数
        """
        conn = self._get_conn()
        try:
            cursor = conn.executemany(sql, params_list)
            conn.commit()
            return cursor.rowcount
        except Exception:
            conn.rollback()
            raise
        finally:
            self._return_conn(conn)

    # ══════════════════════════════════════════════════════
    # 写入 API
    # ══════════════════════════════════════════════════════

    def insert(self, table: str, data: dict) -> int:
        """插入一行

        Args:
            table: 表名
            data: 列名 → 值的字典

        Returns:
            新插入行的 rowid
        """
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"

        with self._write_lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(sql, tuple(data.values()))
                conn.commit()
                return cursor.lastrowid or 0
            except Exception:
                conn.rollback()
                raise
            finally:
                self._return_conn(conn)

    def insert_or_replace(self, table: str, data: dict) -> int:
        """插入或替换（冲突时 REPLACE）"""
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        sql = f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({placeholders})"

        with self._write_lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(sql, tuple(data.values()))
                conn.commit()
                return cursor.lastrowid or 0
            except Exception:
                conn.rollback()
                raise
            finally:
                self._return_conn(conn)

    def insert_or_ignore(self, table: str, data: dict) -> int:
        """插入或忽略（冲突时跳过）"""
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        sql = f"INSERT OR IGNORE INTO {table} ({columns}) VALUES ({placeholders})"

        with self._write_lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(sql, tuple(data.values()))
                conn.commit()
                return cursor.lastrowid or 0
            except Exception:
                conn.rollback()
                raise
            finally:
                self._return_conn(conn)

    def update(
        self,
        table: str,
        data: dict,
        where: str,
        where_params: tuple | list = (),
    ) -> int:
        """更新行

        Args:
            table: 表名
            data: 要更新的列 → 值
            where: WHERE 子句（使用 ? 占位符）
            where_params: WHERE 参数

        Returns:
            影响的行数
        """
        set_clause = ", ".join(f"{k} = ?" for k in data)
        sql = f"UPDATE {table} SET {set_clause} WHERE {where}"
        params = tuple(data.values()) + tuple(where_params)

        with self._write_lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(sql, params)
                conn.commit()
                return cursor.rowcount
            except Exception:
                conn.rollback()
                raise
            finally:
                self._return_conn(conn)

    def delete(self, table: str, where: str, params: tuple = ()) -> int:
        """删除行"""
        sql = f"DELETE FROM {table} WHERE {where}"

        with self._write_lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(sql, params)
                conn.commit()
                return cursor.rowcount
            except Exception:
                conn.rollback()
                raise
            finally:
                self._return_conn(conn)

    def upsert(
        self,
        table: str,
        data: dict,
        conflict_columns: list[str],
        update_columns: list[str] | None = None,
    ) -> int:
        """INSERT OR UPDATE (UPSERT)

        SQLite 3.24+ 支持 ON CONFLICT DO UPDATE
        """
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        conflict = ", ".join(conflict_columns)

        if update_columns:
            set_clause = ", ".join(
                f"{c} = excluded.{c}" for c in update_columns
            )
        else:
            # 更新所有非冲突列
            set_clause = ", ".join(
                f"{c} = excluded.{c}"
                for c in data if c not in conflict_columns
            )

        sql = (
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT({conflict}) DO UPDATE SET {set_clause}"
        )

        with self._write_lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(sql, tuple(data.values()))
                conn.commit()
                return cursor.lastrowid or 0
            except Exception:
                conn.rollback()
                raise
            finally:
                self._return_conn(conn)

    # ══════════════════════════════════════════════════════
    # 批量 + 事务
    # ══════════════════════════════════════════════════════

    @contextmanager
    def transaction(self):
        """事务管理器

        Usage:
            with dal.transaction():
                dal.insert(...)
                dal.update(...)
        """
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
            logger.debug("dal_transaction_committed")
        except Exception:
            conn.rollback()
            logger.warning("dal_transaction_rolled_back")
            raise
        finally:
            self._return_conn(conn)

    def batch_insert(self, table: str, rows: list[dict]) -> int:
        """批量插入（单事务）"""
        if not rows:
            return 0
        columns = rows[0].keys()
        placeholders = ", ".join(["?"] * len(columns))
        col_names = ", ".join(columns)
        sql = f"INSERT OR IGNORE INTO {table} ({col_names}) VALUES ({placeholders})"

        params_list = [tuple(r[c] for c in columns) for r in rows]

        with self._write_lock:
            conn = self._get_conn()
            try:
                cursor = conn.executemany(sql, params_list)
                conn.commit()
                return cursor.rowcount
            except Exception:
                conn.rollback()
                raise
            finally:
                self._return_conn(conn)

    # ══════════════════════════════════════════════════════
    # 工具方法
    # ══════════════════════════════════════════════════════

    def table_exists(self, table: str) -> bool:
        row = self.execute_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        return row is not None

    def table_row_count(self, table: str) -> int:
        try:
            return self.execute_value(
                f"SELECT COUNT(*) FROM {table}",
            ) or 0
        except Exception:
            return 0

    def vacuum(self) -> None:
        """清理数据库碎片"""
        conn = self._new_raw_conn()
        try:
            conn.execute("VACUUM")
        finally:
            conn.close()

    def get_db_info(self) -> dict:
        """获取数据库元信息"""
        info: dict = {"path": str(self._db_path), "tables": {}, "version": 0}

        row = self.execute_one(
            "SELECT version FROM db_version ORDER BY version DESC LIMIT 1"
        )
        info["version"] = row[0] if row else 0

        tables = self.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        for t in tables:
            name = t[0]
            count = self.table_row_count(name)
            info["tables"][name] = count

        return info
