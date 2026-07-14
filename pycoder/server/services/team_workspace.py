"""
团队协作工作区 — 共享 AI 会话与代码审查

基于现有 SessionShareManager (pub/sub) 扩展:
  1. 创建/加入/离开工作区
  2. 工作区内共享 AI 会话
  3. 代码审查请求: 生成请求 → @成员 → 审查响应
  4. 活动 Feed: 查看队友的 AI 交互

存储: SQLite (与 session_store 共享数据库)
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# ── 数据模型 ──


@dataclass
class TeamWorkspace:
    """团队工作区"""

    id: str
    name: str
    created_by: str = ""
    created_at: float = 0.0
    member_count: int = 0
    active_sessions: int = 0
    settings_json: str = "{}"


@dataclass
class TeamMember:
    """团队成员"""

    id: str
    workspace_id: str
    display_name: str
    role: str = "member"  # owner | admin | member
    joined_at: float = 0.0
    last_active_at: float = 0.0


@dataclass
class ReviewRequest:
    """代码审查请求"""

    id: str
    workspace_id: str
    title: str
    file_path: str = ""
    code_snippet: str = ""
    description: str = ""
    requested_by: str = ""
    assigned_to: list[str] = field(default_factory=list)
    status: str = "open"  # open | approved | changes_requested | closed
    created_at: float = 0.0
    resolved_at: float | None = None
    comments: list[dict] = field(default_factory=list)


@dataclass
class ActivityEntry:
    """活动 Feed 条目"""

    id: str
    workspace_id: str
    user_id: str
    user_name: str
    action: str  # chat | review | file_edit | session_share | member_join
    detail: str = ""
    timestamp: float = 0.0


# ── 管理器 ──


class TeamWorkspaceManager:
    """团队协作工作区管理器 — 单例"""

    def __init__(self):
        self._db_path = Path.home() / ".pycoder" / "teams.db"
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS workspaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_by TEXT DEFAULT '',
                created_at REAL DEFAULT (strftime('%s','now')),
                settings_json TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS members (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                role TEXT DEFAULT 'member',
                joined_at REAL DEFAULT (strftime('%s','now')),
                last_active_at REAL DEFAULT (strftime('%s','now')),
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
            );
            CREATE TABLE IF NOT EXISTS review_requests (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                title TEXT NOT NULL,
                file_path TEXT DEFAULT '',
                code_snippet TEXT DEFAULT '',
                description TEXT DEFAULT '',
                requested_by TEXT DEFAULT '',
                assigned_to TEXT DEFAULT '[]',
                status TEXT DEFAULT 'open',
                created_at REAL DEFAULT (strftime('%s','now')),
                resolved_at REAL,
                comments TEXT DEFAULT '[]',
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
            );
            CREATE TABLE IF NOT EXISTS activities (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                user_name TEXT DEFAULT '',
                action TEXT NOT NULL,
                detail TEXT DEFAULT '',
                timestamp REAL DEFAULT (strftime('%s','now')),
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
            );
            CREATE INDEX IF NOT EXISTS idx_members_ws ON members(workspace_id);
            CREATE INDEX IF NOT EXISTS idx_reviews_ws ON review_requests(workspace_id);
            CREATE INDEX IF NOT EXISTS idx_activities_ws ON activities(workspace_id);
        """)
        conn.commit()

    # ── 工作区管理 ──

    def create_workspace(self, name: str, created_by: str = "local") -> dict:
        """创建工作区"""
        ws_id = str(uuid.uuid4())[:8]
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO workspaces (id, name, created_by) VALUES (?, ?, ?)",
            (ws_id, name, created_by),
        )
        # 创建者自动成为 owner
        member_id = str(uuid.uuid4())[:8]
        conn.execute(
            "INSERT INTO members (id, workspace_id, display_name, role) VALUES (?, ?, ?, 'owner')",
            (member_id, ws_id, created_by),
        )
        conn.commit()
        self._add_activity(
            ws_id, created_by, created_by, "create_workspace", f"创建了工作区 {name}"
        )
        return {"success": True, "workspace_id": ws_id, "name": name}

    def list_workspaces(self) -> list[dict]:
        """列出所有工作区"""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT w.*, (SELECT COUNT(*) FROM members m WHERE m.workspace_id = w.id) as member_count
            FROM workspaces w ORDER BY w.created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def get_workspace(self, ws_id: str) -> dict | None:
        """获取工作区详情"""
        conn = self._get_conn()
        row = conn.execute(
            """
            SELECT w.*, (SELECT COUNT(*) FROM members m WHERE m.workspace_id = w.id) as member_count
            FROM workspaces w WHERE w.id = ?
        """,
            (ws_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["members"] = self.list_members(ws_id)
        return result

    def delete_workspace(self, ws_id: str) -> dict:
        """删除工作区"""
        conn = self._get_conn()
        conn.execute("DELETE FROM activities WHERE workspace_id = ?", (ws_id,))
        conn.execute("DELETE FROM review_requests WHERE workspace_id = ?", (ws_id,))
        conn.execute("DELETE FROM members WHERE workspace_id = ?", (ws_id,))
        conn.execute("DELETE FROM workspaces WHERE id = ?", (ws_id,))
        conn.commit()
        return {"success": True}

    # ── 成员管理 ──

    def join_workspace(self, ws_id: str, display_name: str = "guest") -> dict:
        """加入工作区"""
        conn = self._get_conn()
        ws = conn.execute("SELECT id FROM workspaces WHERE id = ?", (ws_id,)).fetchone()
        if not ws:
            return {"success": False, "error": "工作区不存在"}
        member_id = str(uuid.uuid4())[:8]
        conn.execute(
            "INSERT INTO members (id, workspace_id, display_name) VALUES (?, ?, ?)",
            (member_id, ws_id, display_name),
        )
        conn.commit()
        self._add_activity(
            ws_id, member_id, display_name, "member_join", f"{display_name} 加入了工作区"
        )
        return {"success": True, "member_id": member_id, "workspace_id": ws_id}

    def leave_workspace(self, member_id: str) -> dict:
        """离开工作区"""
        conn = self._get_conn()
        conn.execute("DELETE FROM members WHERE id = ?", (member_id,))
        conn.commit()
        return {"success": True}

    def list_members(self, ws_id: str) -> list[dict]:
        """列出工作区成员"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM members WHERE workspace_id = ? ORDER BY role, joined_at",
            (ws_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_last_active(self, member_id: str):
        """更新最后活跃时间"""
        conn = self._get_conn()
        conn.execute(
            "UPDATE members SET last_active_at = ? WHERE id = ?",
            (time.time(), member_id),
        )
        conn.commit()

    # ── 代码审查 ──

    def create_review_request(
        self,
        ws_id: str,
        title: str,
        requested_by: str,
        file_path: str = "",
        code_snippet: str = "",
        description: str = "",
        assigned_to: list[str] = None,
    ) -> dict:
        """创建代码审查请求"""
        review_id = str(uuid.uuid4())[:8]
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO review_requests
               (id, workspace_id, title, file_path, code_snippet, description,
                requested_by, assigned_to, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            (
                review_id,
                ws_id,
                title,
                file_path,
                code_snippet,
                description,
                requested_by,
                json.dumps(assigned_to or [], ensure_ascii=False),
                time.time(),
            ),
        )
        conn.commit()
        assign_str = ", ".join(assigned_to) if assigned_to else "所有成员"
        self._add_activity(
            ws_id,
            requested_by,
            requested_by,
            "review",
            f"{requested_by} 请求 {assign_str} 审查: {title}",
        )
        return {"success": True, "review_id": review_id}

    def list_review_requests(self, ws_id: str, status: str = "") -> list[dict]:
        """列出审查请求"""
        conn = self._get_conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM review_requests"
                " WHERE workspace_id = ? AND status = ? ORDER BY created_at DESC",
                (ws_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM review_requests WHERE workspace_id = ? ORDER BY created_at DESC",
                (ws_id,),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["assigned_to"] = json.loads(d.get("assigned_to", "[]"))
            d["comments"] = json.loads(d.get("comments", "[]"))
            result.append(d)
        return result

    def add_review_comment(self, review_id: str, user: str, comment: str) -> dict:
        """添加审查评论"""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM review_requests WHERE id = ?", (review_id,)).fetchone()
        if not row:
            return {"success": False, "error": "审查请求不存在"}
        comments = json.loads(row["comments"])
        comments.append(
            {
                "user": user,
                "comment": comment,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        conn.execute(
            "UPDATE review_requests SET comments = ? WHERE id = ?",
            (json.dumps(comments, ensure_ascii=False), review_id),
        )
        conn.commit()
        return {"success": True}

    def update_review_status(self, review_id: str, status: str) -> dict:
        """更新审查状态"""
        valid = ("open", "approved", "changes_requested", "closed")
        if status not in valid:
            return {"success": False, "error": f"无效状态: {status}"}
        conn = self._get_conn()
        now = time.time() if status in ("approved", "closed") else None
        conn.execute(
            "UPDATE review_requests SET status = ?, resolved_at = ? WHERE id = ?",
            (status, now, review_id),
        )
        conn.commit()
        return {"success": True, "new_status": status}

    # ── 活动 Feed ──

    def _add_activity(
        self, ws_id: str, user_id: str, user_name: str, action: str, detail: str = ""
    ):
        """添加活动条目"""
        aid = str(uuid.uuid4())[:8]
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO activities (id, workspace_id, user_id, user_name, action, detail) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (aid, ws_id, user_id, user_name, action, detail),
        )
        conn.commit()

    def get_activity_feed(self, ws_id: str, limit: int = 30) -> list[dict]:
        """获取活动 Feed"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM activities WHERE workspace_id = ? ORDER BY timestamp DESC LIMIT ?",
            (ws_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def share_session(self, ws_id: str, session_id: str, user_name: str) -> dict:
        """在工作区中共享一个 AI 会话"""
        self._add_activity(
            ws_id, user_name, user_name, "session_share", f"共享了会话 {session_id[:8]}"
        )
        return {"success": True, "workspace_id": ws_id, "session_id": session_id}


# 全局单例
_manager: TeamWorkspaceManager | None = None


def get_team_workspace_manager() -> TeamWorkspaceManager:
    global _manager
    if _manager is None:
        _manager = TeamWorkspaceManager()
    return _manager
