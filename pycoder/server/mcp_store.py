"""
MCP 工具生态增强 — SQLite 持久化 + 模板市场 + 自动重连

1. MCP Store: 服务器配置持久化 + 调用审计日志
2. MCP Marketplace: 一键连接模板
3. AutoReconnect: 断开自动重连
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 模板市场 ──

MCP_MARKETPLACE: dict[str, dict] = {
    "github": {
        "name": "GitHub",
        "description": "管理 Issues, PRs, Code Review",
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env_vars": ["GITHUB_TOKEN"],
        "icon": "🐙",
    },
    "postgres": {
        "name": "PostgreSQL",
        "description": "数据库查询与 Schema 管理",
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@anthropic/mcp-server-postgres"],
        "env_vars": ["POSTGRES_CONNECTION_STRING"],
        "icon": "🐘",
    },
    "filesystem": {
        "name": "文件系统 (沙箱)",
        "description": "安全的沙箱化文件读写操作",
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem"],
        "env_vars": [],
        "icon": "📁",
    },
    "sqlite": {
        "name": "SQLite 数据库",
        "description": "本地 SQLite 数据库查询和管理",
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@anthropic/mcp-server-sqlite"],
        "env_vars": [],
        "icon": "🗄️",
    },
    "fetch": {
        "name": "网页抓取",
        "description": "获取网页内容 (兼容 firecrawl)",
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@anthropic/mcp-server-fetch"],
        "env_vars": [],
        "icon": "🌐",
    },
}


# ── MCP 配置存储 ──

class MCPStore:
    """MCP 服务器配置持久化 + 调用审计"""

    def __init__(self):
        db_path = Path.home() / ".pycoder" / "mcp_servers.db"
        os.makedirs(db_path.parent, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), timeout=5)
        self._init_tables()

    def _init_tables(self):
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS mcp_servers (
                name TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                command TEXT DEFAULT '',
                url TEXT DEFAULT '',
                env_json TEXT DEFAULT '{}',
                auto_connect INTEGER DEFAULT 0,
                created_at REAL,
                last_connected_at REAL,
                status TEXT DEFAULT 'disconnected'
            )
        """)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS mcp_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server TEXT,
                tool TEXT,
                params_summary TEXT,
                success INTEGER,
                duration_ms REAL,
                created_at REAL
            )
        """)
        self._db.commit()

    def save_server(self, name: str, server_type: str, command: str = "",
                    url: str = "", env_vars: dict = None,
                    auto_connect: bool = False) -> bool:
        """保存/更新 MCP 服务器配置"""
        try:
            self._db.execute("""
                INSERT OR REPLACE INTO mcp_servers
                (name, type, command, url, env_json, auto_connect, created_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'disconnected')
            """, (name, server_type, command, url,
                  json.dumps(env_vars or {}),
                  1 if auto_connect else 0,
                  time.time()))
            self._db.commit()
            return True
        except Exception as exc:
            logger.error("MCP 服务器保存失败: %s", exc)
            return False

    def delete_server(self, name: str) -> bool:
        try:
            self._db.execute("DELETE FROM mcp_servers WHERE name=?", (name,))
            self._db.commit()
            return True
        except Exception:
            return False

    def list_servers(self) -> list[dict]:
        rows = self._db.execute("SELECT * FROM mcp_servers ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def get_auto_connect_servers(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT * FROM mcp_servers WHERE auto_connect=1 AND status='disconnected'"
        ).fetchall()
        return [dict(row) for row in rows]

    def update_status(self, name: str, status: str):
        self._db.execute(
            "UPDATE mcp_servers SET status=?, last_connected_at=? WHERE name=?",
            (status, time.time(), name),
        )
        self._db.commit()

    def log_audit(self, server: str, tool: str, params: str, success: bool, duration_ms: float):
        sql = ("INSERT INTO mcp_audit "
               "(server, tool, params_summary, success, duration_ms, created_at) "
               "VALUES (?, ?, ?, ?, ?, ?)")
        self._db.execute(
            sql,
            (server, tool, params[:200], 1 if success else 0, duration_ms, time.time()),
        )
        self._db.commit()

    def get_audit_log(self, limit: int = 50) -> list[dict]:
        rows = self._db.execute(
            "SELECT * FROM mcp_audit ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self):
        self._db.close()


# ── MCP 自动重连管理器 ──

class MCPAutoReconnect:
    """MCP 自动重连管理器 — 健康检查 + 自动重连"""

    def __init__(self, store: MCPStore):
        self._store = store
        self._task: object = None
        self._running = False

    async def start(self):
        """启动健康检查循环"""
        self._running = True
        self._task = asyncio.create_task(self._health_loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _health_loop(self):
        """每 60s 检查并重连"""
        while self._running:
            try:
                await self._check_and_reconnect()
            except Exception as exc:
                logger.warning("MCP 健康检查异常: %s", exc)
            await asyncio.sleep(60)

    async def _check_and_reconnect(self):
        servers = self._store.get_auto_connect_servers()
        for server in servers:
            try:
                from pycoder.server.mcp_tools import get_mcp_client_manager
                mgr = get_mcp_client_manager()
                name = server["name"]
                if server["type"] == "stdio":
                    await mgr.connect_stdio(name, server["command"])
                elif server["type"] == "sse":
                    await mgr.connect_sse(name, server["url"])
                self._store.update_status(name, "connected")
                logger.info("MCP 自动重连成功: %s", name)
            except Exception as exc:
                logger.debug("MCP 重连失败 %s: %s", server["name"], exc)


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_store: MCPStore | None = None
_reconnect: MCPAutoReconnect | None = None


def get_mcp_store() -> MCPStore:
    global _store
    if _store is None:
        _store = MCPStore()
    return _store


def get_mcp_reconnect() -> MCPAutoReconnect:
    global _reconnect
    if _reconnect is None:
        _reconnect = MCPAutoReconnect(get_mcp_store())
    return _reconnect
