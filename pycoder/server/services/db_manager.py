"""数据库连接统一管理服务 — F6 数据库可视化

功能:
- 连接管理: SQLite 直接可用; PostgreSQL/MySQL 驱动可选（缺驱动时给出明确错误）
- 元数据: list_tables / describe_table / list_databases
- 查询执行: 强制参数化、默认只读（拒绝非 SELECT，除非显式 allow_write）、
  行数上限、执行计时
- ER 数据: 基于外键的表关系

安全设计:
- 方言白名单（sqlite / postgresql / mysql），拒绝未知方言
- 连接参数白名单 + URL 构建使用 SQLAlchemy URL.create（自动转义，防 URL 注入）
- 日志与 API 响应只输出脱敏 URL（密码替换为 ***），连接串仅存内存、不落盘
- 只读校验: 剥离注释后判断首关键字；WITH 语句额外扫描写关键字；
  拒绝字符串字面量之外的多语句（分号拼接注入）
- 参数一律通过 SQLAlchemy text() 绑定变量传递，绝不字符串拼接
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from datetime import time as dt_time
from decimal import Decimal
from pathlib import Path
from typing import Any

try:
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.engine import URL, Engine, make_url

    HAS_SQLALCHEMY = True
except ImportError:  # pragma: no cover - 环境缺依赖时的明确降级
    HAS_SQLALCHEMY = False
    Engine = Any  # type: ignore[assignment, misc]
    URL = Any  # type: ignore[assignment, misc]
    make_url = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ── 方言与驱动映射 ─────────────────────────────────────────────
# 方言 -> (驱动 pip 包, 驱动模块名); sqlite 使用标准库 sqlite3，无需额外驱动
DRIVER_MAP: dict[str, tuple[str, str] | None] = {
    "sqlite": None,
    "postgresql": ("psycopg2-binary", "psycopg2"),
    "mysql": ("pymysql", "pymysql"),
}

# 各方言允许的连接参数白名单（防 URL 注入）
_PARAMS_WHITELIST: dict[str, set[str]] = {
    "sqlite": {"path"},
    "postgresql": {"host", "port", "database", "username", "password"},
    "mysql": {"host", "port", "database", "username", "password"},
}

# 只读模式允许的首关键字
_READONLY_FIRST_KEYWORDS = {"select", "explain", "pragma", "show", "describe", "desc"}
# WITH 语句中禁止出现的写操作关键字
_WRITE_KEYWORDS_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|replace|attach|detach"
    r"|vacuum|reindex|grant|revoke|merge|call|exec|execute)\b",
    re.IGNORECASE,
)


class DatabaseError(Exception):
    """数据库操作通用错误（消息可安全返回给前端）"""


class ReadOnlyViolation(DatabaseError):
    """只读模式下执行了写操作"""


def _require_sqlalchemy() -> None:
    """确保 SQLAlchemy 可用，否则给出明确安装提示"""
    if not HAS_SQLALCHEMY:
        raise DatabaseError("缺少依赖 sqlalchemy，请执行: pip install 'sqlalchemy>=2.0'")


def _check_driver(driver: str) -> str:
    """校验方言合法性并确认驱动已安装，返回 SQLAlchemy 方言名"""
    if driver not in DRIVER_MAP:
        raise DatabaseError(
            f"不支持的数据库类型: {driver!r}（支持: {', '.join(sorted(DRIVER_MAP))}）"
        )
    requirement = DRIVER_MAP[driver]
    if requirement is None:
        return "sqlite"
    package, module = requirement
    try:
        __import__(module)
    except ImportError as exc:
        raise DatabaseError(f"缺少 {driver} 驱动，请执行: pip install {package}") from exc
    return f"{driver}+{module}"


def _strip_sql_comments(sql: str) -> str:
    """剥离 SQL 注释（行注释与块注释），避免注释隐藏恶意关键字"""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def _has_extra_statements(sql: str) -> bool:
    """检测字符串字面量之外是否含有语句分隔符（多语句注入防护）"""
    in_single = in_double = False
    for ch in sql:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == ";" and not in_single and not in_double:
            return True
    return False


def is_readonly_sql(sql: str) -> bool:
    """判断 SQL 是否为只读语句

    规则:
    1. 剥离注释后取首关键字，须在只读白名单内（select/explain/pragma/...）
    2. WITH 开头的语句额外全文扫描写操作关键字（防 CTE 内嵌 DELETE）
    3. 拒绝字符串字面量之外的多语句（分号拼接）
    """
    cleaned = _strip_sql_comments(sql).strip()
    if not cleaned:
        return False
    # 允许多余的末尾分号，但不允许中间分号拼接多条语句
    body = cleaned[:-1] if cleaned.endswith(";") else cleaned
    if _has_extra_statements(body):
        return False
    first = re.split(r"[\s(]+", body, maxsplit=1)[0].lower()
    if first in _READONLY_FIRST_KEYWORDS:
        return True
    if first == "with":
        # CTE 可能内嵌写操作（如 WITH x AS (...) DELETE ...），需额外扫描
        return _WRITE_KEYWORDS_RE.search(body) is None
    return False


def _json_safe(value: Any) -> Any:
    """将数据库值转换为 JSON 可序列化类型"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


@dataclass
class ConnectionInfo:
    """连接元信息（safe_url 已脱敏，可安全用于日志/响应）"""

    name: str
    driver: str
    safe_url: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "driver": self.driver,
            "url": self.safe_url,
            "created_at": self.created_at,
        }


@dataclass
class QueryResult:
    """查询执行结果"""

    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    elapsed_ms: float
    truncated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "truncated": self.truncated,
        }


class DatabaseManager:
    """数据库连接管理器（进程内单例，连接串仅存内存）"""

    MAX_LIMIT = 1000  # 单次查询最大返回行数（硬上限）
    DEFAULT_LIMIT = 200  # 默认行数上限
    NAME_RE = re.compile(r"^[\w][\w\-]{0,63}$")  # 连接名白名单字符

    def __init__(self) -> None:
        self._engines: dict[str, Engine] = {}
        self._infos: dict[str, ConnectionInfo] = {}
        self._lock = threading.RLock()

    # ── 连接管理 ──────────────────────────────────────────────

    def connect(
        self,
        name: str,
        url: str | None = None,
        driver: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> ConnectionInfo:
        """建立连接（两种方式：完整 url，或 driver + params 白名单参数）

        Args:
            name: 连接别名（白名单字符，防路径/日志注入）
            url: 完整 SQLAlchemy 连接串（优先级高）
            driver: 方言名（sqlite / postgresql / mysql）
            params: 连接参数（仅白名单键生效）

        Raises:
            DatabaseError: 参数非法、方言不支持或驱动缺失
        """
        _require_sqlalchemy()
        if not self.NAME_RE.match(name):
            raise DatabaseError(f"非法连接名: {name!r}（仅允许字母/数字/下划线/中划线）")

        if url:
            conn_url = self._validate_url(url)
            driver_name = conn_url.get_dialect().name
        elif driver and params is not None:
            conn_url = self._build_url(driver, params)
            driver_name = driver
        else:
            raise DatabaseError("必须提供 url 或 driver+params")

        engine = create_engine(conn_url, pool_pre_ping=True)
        # 立即验证连通性（失败时不留下半初始化状态）
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except DatabaseError:
            engine.dispose()
            raise
        except Exception as exc:  # noqa: BLE001 - 驱动异常类型各异，统一包装
            engine.dispose()
            raise DatabaseError(f"连接失败: {exc}") from exc

        info = ConnectionInfo(
            name=name,
            driver=driver_name,
            safe_url=conn_url.render_as_string(hide_password=True),
        )
        with self._lock:
            old = self._engines.pop(name, None)
            if old is not None:
                old.dispose()
            self._engines[name] = engine
            self._infos[name] = info
        # 日志只记录脱敏 URL，绝不输出明文密码
        logger.info("db_connected name=%s url=%s", name, info.safe_url)
        return info

    def _validate_url(self, url: str) -> URL:
        """校验完整连接串：方言必须在白名单内"""
        try:
            conn_url = make_url(url)
        except Exception as exc:  # noqa: BLE001
            raise DatabaseError(f"无效的连接串: {exc}") from exc
        dialect = conn_url.get_dialect().name
        if dialect not in DRIVER_MAP:
            raise DatabaseError(f"不支持的数据库方言: {dialect!r}")
        if dialect != "sqlite":
            _check_driver(dialect)
        return conn_url

    def _build_url(self, driver: str, params: dict[str, Any]) -> URL:
        """由白名单参数构建连接 URL（防 URL 注入）"""
        dialect = _check_driver(driver)
        unknown = set(params) - _PARAMS_WHITELIST[driver]
        if unknown:
            raise DatabaseError(f"不支持的连接参数: {sorted(unknown)}")

        if driver == "sqlite":
            raw_path = str(params.get("path") or "")
            if not raw_path:
                raise DatabaseError("sqlite 连接必须提供 path")
            if raw_path != ":memory:":
                # 路径校验：展开为绝对路径，禁止 URL 方案注入（如 file:...?uri=true）
                p = Path(raw_path).expanduser()
                if p.suffix and p.suffix.lower() not in {
                    ".db",
                    ".sqlite",
                    ".sqlite3",
                    ".s3db",
                    ".db3",
                }:
                    raise DatabaseError(f"可疑的 SQLite 文件扩展名: {p.suffix}")
                database = str(p.resolve())
            else:
                database = ":memory:"
            return URL.create("sqlite", database=database)

        # postgresql / mysql: host 禁止特殊字符，防 URL 注入
        host = str(params.get("host") or "localhost")
        if not re.match(r"^[\w.\-]+$", host):
            raise DatabaseError(f"非法主机名: {host!r}")
        port = params.get("port")
        return URL.create(
            dialect,
            username=str(params["username"]) if params.get("username") else None,
            password=str(params["password"]) if params.get("password") else None,
            host=host,
            port=int(port) if port else None,
            database=str(params.get("database") or ""),
        )

    def disconnect(self, name: str) -> bool:
        """断开并移除连接，返回是否存在"""
        with self._lock:
            engine = self._engines.pop(name, None)
            self._infos.pop(name, None)
        if engine is None:
            return False
        engine.dispose()
        logger.info("db_disconnected name=%s", name)
        return True

    def list_connections(self) -> list[dict[str, Any]]:
        """列出所有连接（仅脱敏信息）"""
        with self._lock:
            return [info.to_dict() for info in self._infos.values()]

    def _get_engine(self, name: str) -> Engine:
        with self._lock:
            engine = self._engines.get(name)
        if engine is None:
            raise DatabaseError(f"连接不存在: {name!r}")
        return engine

    # ── 元数据 ────────────────────────────────────────────────

    def list_databases(self, name: str) -> list[str]:
        """列出当前连接可见的数据库/schema"""
        engine = self._get_engine(name)
        dialect = engine.dialect.name
        with engine.connect() as conn:
            if dialect == "sqlite":
                rows = conn.execute(text("PRAGMA database_list")).fetchall()
                return [row[1] for row in rows]
            if dialect == "postgresql":
                rows = conn.execute(
                    text("SELECT datname FROM pg_database WHERE NOT datistemplate")
                ).fetchall()
                return [row[0] for row in rows]
            if dialect == "mysql":
                rows = conn.execute(text("SHOW DATABASES")).fetchall()
                return [row[0] for row in rows]
        return []

    def list_tables(self, name: str) -> list[dict[str, Any]]:
        """列出表与视图"""
        engine = self._get_engine(name)
        insp = inspect(engine)
        result: list[dict[str, Any]] = [
            {"name": t, "type": "table"} for t in sorted(insp.get_table_names())
        ]
        result.extend({"name": v, "type": "view"} for v in sorted(insp.get_view_names()))
        return result

    def describe_table(self, name: str, table: str) -> dict[str, Any]:
        """表结构详情：列/类型/主键/索引/外键"""
        engine = self._get_engine(name)
        insp = inspect(engine)
        known = set(insp.get_table_names()) | set(insp.get_view_names())
        if table not in known:
            raise DatabaseError(f"表不存在: {table!r}")

        pk_cols = set(insp.get_pk_constraint(table).get("constrained_columns") or [])
        columns = [
            {
                "name": col["name"],
                "type": str(col["type"]),
                "nullable": bool(col.get("nullable", True)),
                "default": None if col.get("default") is None else str(col["default"]),
                "primary_key": col["name"] in pk_cols,
            }
            for col in insp.get_columns(table)
        ]
        indexes = [
            {
                "name": idx.get("name"),
                "columns": idx.get("column_names") or [],
                "unique": bool(idx.get("unique")),
            }
            for idx in insp.get_indexes(table)
        ]
        foreign_keys = [
            {
                "columns": fk.get("constrained_columns") or [],
                "referred_table": fk.get("referred_table"),
                "referred_columns": fk.get("referred_columns") or [],
            }
            for fk in insp.get_foreign_keys(table)
        ]
        return {
            "table": table,
            "columns": columns,
            "primary_key": sorted(pk_cols),
            "indexes": indexes,
            "foreign_keys": foreign_keys,
        }

    # ── 查询执行 ──────────────────────────────────────────────

    def execute_query(
        self,
        name: str,
        sql: str,
        params: dict[str, Any] | None = None,
        limit: int | None = None,
        allow_write: bool = False,
    ) -> QueryResult:
        """执行 SQL（强制参数化 + 默认只读 + 行数上限 + 计时）

        Args:
            name: 连接别名
            sql: SQL 文本，参数必须使用 :name 绑定变量，禁止字符串拼接
            params: 绑定参数（命名风格 dict）
            limit: 返回行数上限（clamp 到 [1, MAX_LIMIT]）
            allow_write: 显式允许写操作（默认 False，写操作将被拒绝）

        Raises:
            ReadOnlyViolation: 只读模式下执行非只读语句
            DatabaseError: 参数非法或执行失败
        """
        engine = self._get_engine(name)
        if not sql or not sql.strip():
            raise DatabaseError("SQL 不能为空")
        if not allow_write and not is_readonly_sql(sql):
            raise ReadOnlyViolation(
                "只读模式：仅允许 SELECT 查询（如需写操作请显式开启 allow_write）"
            )
        if params is not None and not isinstance(params, dict):
            raise DatabaseError('params 必须是命名参数 dict（如 {"name": "x"}）')

        effective_limit = self.DEFAULT_LIMIT if limit is None else int(limit)
        effective_limit = max(1, min(effective_limit, self.MAX_LIMIT))

        started = time.perf_counter()
        try:
            with engine.connect() as conn:
                result = conn.execute(text(sql), params or {})
                if not result.returns_rows:
                    # 写操作（allow_write=true）：提交并返回受影响行数
                    conn.commit()
                    elapsed = (time.perf_counter() - started) * 1000
                    return QueryResult(
                        columns=[],
                        rows=[],
                        row_count=result.rowcount or 0,
                        elapsed_ms=elapsed,
                        truncated=False,
                    )
                # 多取一行用于判断是否截断
                fetched = result.fetchmany(effective_limit + 1)
                truncated = len(fetched) > effective_limit
                fetched = fetched[:effective_limit]
                columns = list(result.keys())
        except (DatabaseError, ReadOnlyViolation):
            raise
        except Exception as exc:  # noqa: BLE001 - 驱动异常类型各异，统一包装
            raise DatabaseError(f"查询执行失败: {exc}") from exc
        elapsed = (time.perf_counter() - started) * 1000

        rows = [[_json_safe(v) for v in row] for row in fetched]
        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            elapsed_ms=elapsed,
            truncated=truncated,
        )

    # ── ER 数据 ───────────────────────────────────────────────

    def table_relationships(self, name: str) -> dict[str, Any]:
        """ER 图数据：节点（表+列）与边（外键关系）"""
        engine = self._get_engine(name)
        insp = inspect(engine)
        table_names = sorted(insp.get_table_names())

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        for table in table_names:
            pk_cols = set(insp.get_pk_constraint(table).get("constrained_columns") or [])
            columns = [
                {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "primary_key": col["name"] in pk_cols,
                }
                for col in insp.get_columns(table)
            ]
            nodes.append({"name": table, "columns": columns})
            for fk in insp.get_foreign_keys(table):
                edges.append(
                    {
                        "from_table": table,
                        "from_columns": fk.get("constrained_columns") or [],
                        "to_table": fk.get("referred_table"),
                        "to_columns": fk.get("referred_columns") or [],
                    }
                )
        return {"nodes": nodes, "edges": edges}


# ── 模块级单例 ────────────────────────────────────────────────
db_manager = DatabaseManager()
