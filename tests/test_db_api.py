"""F6 数据库可视化 API 测试: pycoder/server/routers/db_api.py

覆盖:
- 建连（SQLite 内存/临时文件）、连接列表、删除连接
- 表列表、表结构（列/主键/索引/外键）
- SELECT 查询返回列+行、参数化防注入
- 非 SELECT 默认拒绝（只读模式）
- 行数上限截断
- ER 外键关系
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.server.routers import db_api
from pycoder.server.services.db_manager import db_manager, is_readonly_sql

# ── 测试夹具 ─────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE authors (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE books (
    id INTEGER PRIMARY KEY,
    author_id INTEGER NOT NULL REFERENCES authors(id),
    title TEXT NOT NULL,
    price REAL
);
CREATE INDEX idx_books_author ON books(author_id);
"""

SEED_SQL = """
INSERT INTO authors (id, name) VALUES (1, '鲁迅'), (2, '冰心');
INSERT INTO books (id, author_id, title, price) VALUES
    (1, 1, '呐喊', 32.5),
    (2, 1, '彷徨', 28.0),
    (3, 2, '繁星', 19.9);
"""


@pytest.fixture
def sqlite_file(tmp_path: Path) -> str:
    """创建带外键关系与数据的临时 SQLite 数据库文件"""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.executescript(SEED_SQL)
    conn.commit()
    conn.close()
    return str(db_path)


@pytest.fixture
def client(sqlite_file: str):
    """仅包含 db_api 路由的测试应用，并预置一个文件型 SQLite 连接"""
    app = FastAPI()
    app.include_router(db_api.router)
    with TestClient(app) as c:
        resp = c.post(
            "/api/db/connect",
            json={"name": "main", "driver": "sqlite", "params": {"path": sqlite_file}},
        )
        assert resp.json()["success"] is True
        yield c
    # 清理单例中的连接，避免跨用例污染
    for info in db_manager.list_connections():
        db_manager.disconnect(info["name"])


# ── 只读判定单元测试 ──────────────────────────────────────────


class TestIsReadonlySql:
    """is_readonly_sql 纯函数测试"""

    def test_select_is_readonly(self):
        assert is_readonly_sql("SELECT * FROM t") is True

    def test_select_with_trailing_semicolon(self):
        assert is_readonly_sql("SELECT 1;") is True

    def test_semicolon_inside_string_allowed(self):
        assert is_readonly_sql("SELECT ';' AS x") is True

    def test_multi_statement_rejected(self):
        assert is_readonly_sql("SELECT 1; DROP TABLE t") is False

    def test_comment_hidden_write_rejected(self):
        assert is_readonly_sql("/* x */ DELETE FROM t") is False
        assert is_readonly_sql("-- x\nDROP TABLE t") is False

    def test_insert_update_delete_rejected(self):
        assert is_readonly_sql("INSERT INTO t VALUES (1)") is False
        assert is_readonly_sql("UPDATE t SET a = 1") is False
        assert is_readonly_sql("DROP TABLE t") is False

    def test_cte_with_write_rejected(self):
        assert is_readonly_sql("WITH x AS (SELECT 1) DELETE FROM t") is False
        assert is_readonly_sql("WITH x AS (SELECT 1) SELECT * FROM x") is True

    def test_empty_sql_rejected(self):
        assert is_readonly_sql("   ") is False


# ── 连接管理 ─────────────────────────────────────────────────


class TestConnect:
    """POST /api/db/connect 与连接管理端点"""

    def test_connect_sqlite_memory(self, client):
        """内存 SQLite 直接可用"""
        resp = client.post(
            "/api/db/connect",
            json={"name": "mem", "driver": "sqlite", "params": {"path": ":memory:"}},
        )
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["name"] == "mem"
        assert data["data"]["driver"] == "sqlite"

    def test_connect_via_url(self, client, sqlite_file: str):
        """完整 URL 建连（Windows 路径在 URL 中使用正斜杠）"""
        url_path = sqlite_file.replace("\\", "/")
        resp = client.post(
            "/api/db/connect",
            json={"name": "byurl", "url": f"sqlite:///{url_path}"},
        )
        assert resp.json()["success"] is True

    def test_connect_invalid_driver(self, client):
        """未知方言被拒绝"""
        resp = client.post(
            "/api/db/connect",
            json={"name": "bad", "driver": "oracle", "params": {"host": "x"}},
        )
        data = resp.json()
        assert data["success"] is False
        assert "不支持" in data["error"]

    def test_connect_rejects_unknown_param(self, client):
        """白名单外的连接参数被拒绝（防 URL 注入）"""
        resp = client.post(
            "/api/db/connect",
            json={"name": "inj", "driver": "sqlite", "params": {"path": ":memory:", "uri": "true"}},
        )
        data = resp.json()
        assert data["success"] is False
        assert "不支持的连接参数" in data["error"]

    def test_connect_invalid_name(self, client):
        """非法连接名被拒绝"""
        resp = client.post(
            "/api/db/connect",
            json={"name": "a/b", "driver": "sqlite", "params": {"path": ":memory:"}},
        )
        assert resp.json()["success"] is False

    def test_list_connections_masks_password(self, client):
        """连接列表不泄露明文密码"""
        resp = client.get("/api/db/connections")
        data = resp.json()
        assert data["success"] is True
        names = [c["name"] for c in data["data"]]
        assert "main" in names
        for conn_info in data["data"]:
            assert "password" not in conn_info["url"].lower()

    def test_disconnect(self, client):
        """删除连接"""
        client.post(
            "/api/db/connect",
            json={"name": "temp", "driver": "sqlite", "params": {"path": ":memory:"}},
        )
        resp = client.delete("/api/db/connections/temp")
        assert resp.json()["success"] is True
        resp = client.delete("/api/db/connections/temp")
        assert resp.json()["success"] is False


# ── 元数据 ───────────────────────────────────────────────────


class TestMetadata:
    """表列表 / 表结构 / 数据库列表"""

    def test_list_tables(self, client):
        resp = client.get("/api/db/main/tables")
        data = resp.json()
        assert data["success"] is True
        names = [t["name"] for t in data["data"]]
        assert "authors" in names
        assert "books" in names

    def test_describe_table(self, client):
        resp = client.get("/api/db/main/tables/books/schema")
        data = resp.json()
        assert data["success"] is True
        schema = data["data"]
        col_names = [c["name"] for c in schema["columns"]]
        assert col_names == ["id", "author_id", "title", "price"]
        assert schema["primary_key"] == ["id"]
        pk_col = next(c for c in schema["columns"] if c["name"] == "id")
        assert pk_col["primary_key"] is True
        # 索引
        idx_names = [i["name"] for i in schema["indexes"]]
        assert "idx_books_author" in idx_names
        # 外键
        assert schema["foreign_keys"][0]["referred_table"] == "authors"
        assert schema["foreign_keys"][0]["columns"] == ["author_id"]

    def test_describe_missing_table(self, client):
        resp = client.get("/api/db/main/tables/nope/schema")
        data = resp.json()
        assert data["success"] is False
        assert "表不存在" in data["error"]

    def test_list_databases(self, client):
        resp = client.get("/api/db/main/databases")
        data = resp.json()
        assert data["success"] is True
        assert "main" in data["data"]

    def test_unknown_connection(self, client):
        resp = client.get("/api/db/ghost/tables")
        data = resp.json()
        assert data["success"] is False
        assert "连接不存在" in data["error"]


# ── 查询执行 ─────────────────────────────────────────────────


class TestQuery:
    """POST /api/db/{conn}/query"""

    def test_select_returns_columns_and_rows(self, client):
        """SELECT 查询返回列+行+计时"""
        resp = client.post(
            "/api/db/main/query",
            json={"sql": "SELECT id, name FROM authors ORDER BY id"},
        )
        data = resp.json()
        assert data["success"] is True
        result = data["data"]
        assert result["columns"] == ["id", "name"]
        assert result["rows"] == [[1, "鲁迅"], [2, "冰心"]]
        assert result["row_count"] == 2
        assert result["truncated"] is False
        assert result["elapsed_ms"] >= 0

    def test_parameterized_query(self, client):
        """命名参数绑定查询"""
        resp = client.post(
            "/api/db/main/query",
            json={
                "sql": "SELECT title FROM books WHERE author_id = :aid ORDER BY id",
                "params": {"aid": 1},
            },
        )
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["rows"] == [["呐喊"], ["彷徨"]]

    def test_injection_via_params_not_executed(self, client):
        """参数中的注入 payload 仅作为字面值，不被执行"""
        payload = "1 OR 1=1"
        resp = client.post(
            "/api/db/main/query",
            json={
                "sql": "SELECT title FROM books WHERE author_id = :aid",
                "params": {"aid": payload},
            },
        )
        data = resp.json()
        assert data["success"] is True
        # 注入串作为字面值比较，不应返回全部行
        assert data["data"]["rows"] == []
        # 表仍然存在（未被 DROP）
        tables = client.get("/api/db/main/tables").json()["data"]
        assert "books" in [t["name"] for t in tables]

    def test_malicious_multi_statement_rejected(self, client):
        """分号拼接的恶意 SQL 不执行"""
        resp = client.post(
            "/api/db/main/query",
            json={"sql": "SELECT * FROM authors; DROP TABLE books"},
        )
        data = resp.json()
        assert data["success"] is False
        assert data["readonly"] is True
        # 验证表未被删除
        tables = client.get("/api/db/main/tables").json()["data"]
        assert "books" in [t["name"] for t in tables]

    def test_non_select_rejected_by_default(self, client):
        """非 SELECT 默认拒绝（只读模式）"""
        for sql in (
            "INSERT INTO authors (id, name) VALUES (9, 'x')",
            "UPDATE authors SET name = 'x'",
            "DELETE FROM authors",
            "DROP TABLE authors",
        ):
            resp = client.post("/api/db/main/query", json={"sql": sql})
            data = resp.json()
            assert data["success"] is False, sql
            assert data["readonly"] is True
            assert "只读" in data["error"]
        # 数据未被修改
        rows = client.post(
            "/api/db/main/query", json={"sql": "SELECT COUNT(*) FROM authors"}
        ).json()["data"]["rows"]
        assert rows == [[2]]

    def test_allow_write_enables_write(self, client, tmp_path: Path):
        """显式 allow_write=true 时允许写操作（独立连接验证）"""
        db_path = tmp_path / "rw.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE kv (k TEXT, v INTEGER)")
        conn.commit()
        conn.close()
        client.post(
            "/api/db/connect",
            json={"name": "rw", "driver": "sqlite", "params": {"path": str(db_path)}},
        )
        resp = client.post(
            "/api/db/rw/query",
            json={
                "sql": "INSERT INTO kv VALUES (:k, :v)",
                "params": {"k": "a", "v": 1},
                "allow_write": True,
            },
        )
        assert resp.json()["success"] is True
        rows = client.post("/api/db/rw/query", json={"sql": "SELECT k, v FROM kv"}).json()["data"][
            "rows"
        ]
        assert rows == [["a", 1]]

    def test_row_limit_truncation(self, client, tmp_path: Path):
        """行数上限截断并标记 truncated"""
        db_path = tmp_path / "big.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE nums (n INTEGER)")
        conn.executemany("INSERT INTO nums VALUES (?)", [(i,) for i in range(50)])
        conn.commit()
        conn.close()
        client.post(
            "/api/db/connect",
            json={"name": "big", "driver": "sqlite", "params": {"path": str(db_path)}},
        )
        resp = client.post("/api/db/big/query", json={"sql": "SELECT n FROM nums", "limit": 10})
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["row_count"] == 10
        assert data["data"]["truncated"] is True

        # 不截断时 truncated 为 False
        resp = client.post("/api/db/big/query", json={"sql": "SELECT n FROM nums", "limit": 100})
        assert resp.json()["data"]["truncated"] is False
        assert resp.json()["data"]["row_count"] == 50

    def test_limit_hard_cap(self, client):
        """limit 超过硬上限时被 clamp"""
        resp = client.post(
            "/api/db/main/query",
            json={"sql": "SELECT * FROM authors", "limit": 999999},
        )
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["row_count"] == 2

    def test_params_must_be_dict(self, client):
        """params 非 dict 时拒绝"""
        resp = client.post(
            "/api/db/main/query",
            json={"sql": "SELECT 1", "params": {"a": 1}},
        )
        assert resp.json()["success"] is True
        # Pydantic 层面拒绝 list 型 params
        resp = client.post(
            "/api/db/main/query",
            json={"sql": "SELECT 1", "params": [1, 2]},
        )
        assert resp.status_code == 422

    def test_empty_sql_rejected(self, client):
        resp = client.post("/api/db/main/query", json={"sql": "   "})
        assert resp.json()["success"] is False


# ── ER 图 ────────────────────────────────────────────────────


class TestER:
    """GET /api/db/{conn}/er"""

    def test_er_relationships(self, client):
        """基于外键的 ER 节点与边"""
        resp = client.get("/api/db/main/er")
        data = resp.json()
        assert data["success"] is True
        er = data["data"]
        node_names = [n["name"] for n in er["nodes"]]
        assert set(node_names) == {"authors", "books"}
        # 节点含列信息
        books_node = next(n for n in er["nodes"] if n["name"] == "books")
        pk_cols = [c["name"] for c in books_node["columns"] if c["primary_key"]]
        assert pk_cols == ["id"]
        # 边：books.author_id -> authors.id
        assert len(er["edges"]) == 1
        edge = er["edges"][0]
        assert edge["from_table"] == "books"
        assert edge["from_columns"] == ["author_id"]
        assert edge["to_table"] == "authors"
        assert edge["to_columns"] == ["id"]
