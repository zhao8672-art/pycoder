"""
team_workspace.py 模块单元测试 — 覆盖率目标 ≥80%

覆盖内容:
  - 数据模型 dataclass 字段默认值
  - TeamWorkspaceManager: 工作区 CRUD
  - 成员管理: 加入/离开/列出/更新活跃时间
  - 代码审查: 创建/列出/评论/状态更新
  - 活动 Feed: 添加/查询
  - 共享会话
  - 全局单例 get_team_workspace_manager

测试策略: 每个测试用 monkeypatch 将 _db_path 重定向到临时文件，避免污染用户家目录。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from pycoder.server.services.team_workspace import (
    ActivityEntry,
    ReviewRequest,
    TeamMember,
    TeamWorkspace,
    TeamWorkspaceManager,
    get_team_workspace_manager,
)


# ── Fixture: 隔离的临时数据库 ──

@pytest.fixture
def mgr(tmp_path, monkeypatch):
    """构造一个使用临时数据库的 TeamWorkspaceManager 实例"""
    db_path = tmp_path / "teams.db"
    instance = TeamWorkspaceManager.__new__(TeamWorkspaceManager)
    import threading
    instance._db_path = db_path
    instance._local = threading.local()
    instance._init_db()
    return instance


# ── 数据模型 ──

def test_team_workspace_dataclass_defaults():
    """TeamWorkspace 默认值"""
    ws = TeamWorkspace(id="x", name="N")
    assert ws.id == "x"
    assert ws.name == "N"
    assert ws.created_by == ""
    assert ws.created_at == 0.0
    assert ws.member_count == 0
    assert ws.active_sessions == 0
    assert ws.settings_json == "{}"


def test_team_member_defaults():
    """TeamMember 默认 role=member"""
    m = TeamMember(id="m", workspace_id="w", display_name="D")
    assert m.role == "member"
    assert m.joined_at == 0.0
    assert m.last_active_at == 0.0


def test_review_request_defaults():
    """ReviewRequest 默认状态、列表字段"""
    r = ReviewRequest(id="r", workspace_id="w", title="T")
    assert r.status == "open"
    assert r.assigned_to == []
    assert r.comments == []
    assert r.resolved_at is None
    assert r.file_path == ""
    assert r.description == ""


def test_activity_entry_fields():
    a = ActivityEntry(id="a", workspace_id="w", user_id="u", user_name="U", action="chat")
    assert a.action == "chat"
    assert a.detail == ""
    assert a.timestamp == 0.0


# ── 工作区管理 ──

def test_create_workspace_returns_id_and_owner_member(mgr):
    """创建工作区返回 success+workspace_id, 创建者自动成为 owner"""
    result = mgr.create_workspace("项目A", "alice")
    assert result["success"] is True
    assert "workspace_id" in result
    assert result["name"] == "项目A"

    members = mgr.list_members(result["workspace_id"])
    assert len(members) == 1
    assert members[0]["display_name"] == "alice"
    assert members[0]["role"] == "owner"


def test_list_workspaces_includes_member_count(mgr):
    """list_workspaces 返回 member_count 字段"""
    r1 = mgr.create_workspace("A", "alice")
    r2 = mgr.create_workspace("B", "bob")
    mgr.join_workspace(r2["workspace_id"], "charlie")

    rows = mgr.list_workspaces()
    assert len(rows) == 2
    counts = {row["name"]: row["member_count"] for row in rows}
    assert counts["A"] == 1
    assert counts["B"] == 2


def test_get_workspace_includes_members(mgr):
    """get_workspace 返回成员列表，未知工作区返回 None"""
    r = mgr.create_workspace("X", "alice")
    detail = mgr.get_workspace(r["workspace_id"])
    assert detail is not None
    assert "members" in detail
    assert len(detail["members"]) == 1
    assert mgr.get_workspace("no-such-id") is None


def test_delete_workspace_cascades(mgr):
    """delete_workspace 删除工作区及其关联数据"""
    r = mgr.create_workspace("Z", "alice")
    ws_id = r["workspace_id"]
    mgr.join_workspace(ws_id, "bob")
    mgr.create_review_request(ws_id, "标题", "alice")
    mgr.share_session(ws_id, "session-1", "alice")

    assert mgr.delete_workspace(ws_id) == {"success": True}
    assert mgr.get_workspace(ws_id) is None
    assert mgr.list_members(ws_id) == []
    assert mgr.list_review_requests(ws_id) == []
    assert mgr.get_activity_feed(ws_id) == []


# ── 成员管理 ──

def test_join_workspace_nonexistent_returns_error(mgr):
    """join_workspace 对不存在的工作区返回 success=False"""
    result = mgr.join_workspace("no-such-ws", "guest")
    assert result["success"] is False
    assert "不存在" in result["error"]


def test_join_workspace_success(mgr):
    """join_workspace 成功加入并触发 member_join 活动"""
    r = mgr.create_workspace("W", "alice")
    result = mgr.join_workspace(r["workspace_id"], "bob")
    assert result["success"] is True
    assert "member_id" in result
    assert result["workspace_id"] == r["workspace_id"]
    feed = mgr.get_activity_feed(r["workspace_id"])
    assert any("bob" in a["detail"] for a in feed)


def test_leave_workspace(mgr):
    """leave_workspace 删除成员"""
    r = mgr.create_workspace("W", "alice")
    join = mgr.join_workspace(r["workspace_id"], "bob")
    assert len(mgr.list_members(r["workspace_id"])) == 2
    result = mgr.leave_workspace(join["member_id"])
    assert result == {"success": True}
    assert len(mgr.list_members(r["workspace_id"])) == 1


def test_list_members_ordering(mgr):
    """list_members 按 role, joined_at 排序（SQLite 字典序 member<owner）"""
    r = mgr.create_workspace("W", "alice")  # owner
    mgr.join_workspace(r["workspace_id"], "bob")
    mgr.join_workspace(r["workspace_id"], "carol")
    members = mgr.list_members(r["workspace_id"])
    # 'member' 字典序小于 'owner'，所以 owner 排在最后
    roles = [m["role"] for m in members]
    assert roles.count("member") == 2
    assert roles.count("owner") == 1
    assert members[-1]["display_name"] == "alice"
    # bob 先加入，应排在 carol 之前
    member_names = [m["display_name"] for m in members if m["role"] == "member"]
    assert member_names == ["bob", "carol"]


def test_update_last_active(mgr):
    """update_last_active 更新成员 last_active_at"""
    r = mgr.create_workspace("W", "alice")
    join = mgr.join_workspace(r["workspace_id"], "bob")
    members = mgr.list_members(r["workspace_id"])
    bob = next(m for m in members if m["display_name"] == "bob")
    old = bob["last_active_at"]
    # 直接用源码的 time.time() 写入新值，时间戳应大于等于 old
    # 注：SQLite strftime('%s','now') 默认精度为秒，可能相等
    mgr.update_last_active(join["member_id"])
    members_after = mgr.list_members(r["workspace_id"])
    bob_after = next(m for m in members_after if m["display_name"] == "bob")
    assert bob_after["last_active_at"] >= old


def test_update_last_active_nonexistent_member(mgr):
    """update_last_active 对不存在成员 ID 也不报错"""
    # 不抛异常即可（UPDATE 影响 0 行）
    mgr.update_last_active("no-such-member")


# ── 代码审查 ──

def test_create_review_request(mgr):
    """create_review_request 写入数据库并返回 review_id"""
    r = mgr.create_workspace("W", "alice")
    result = mgr.create_review_request(
        r["workspace_id"], "标题1", "alice",
        file_path="a.py", code_snippet="x=1",
        description="测试", assigned_to=["bob", "carol"],
    )
    assert result["success"] is True
    assert "review_id" in result
    feed = mgr.get_activity_feed(r["workspace_id"])
    assert any("alice" in a["detail"] and "审查" in a["detail"] for a in feed)


def test_create_review_request_assigned_to_default_all(mgr):
    """assigned_to=None 时活动详情写 '所有成员'"""
    r = mgr.create_workspace("W", "alice")
    mgr.create_review_request(r["workspace_id"], "T", "alice")
    feed = mgr.get_activity_feed(r["workspace_id"])
    review_act = next(a for a in feed if a["action"] == "review")
    assert "所有成员" in review_act["detail"]


def test_list_review_requests_no_status_filter(mgr):
    """list_review_requests 不带状态返回全部"""
    r = mgr.create_workspace("W", "alice")
    mgr.create_review_request(r["workspace_id"], "T1", "alice")
    mgr.create_review_request(r["workspace_id"], "T2", "alice")
    reviews = mgr.list_review_requests(r["workspace_id"])
    assert len(reviews) == 2
    # 默认字段反序列化
    assert isinstance(reviews[0]["assigned_to"], list)
    assert isinstance(reviews[0]["comments"], list)


def test_list_review_requests_status_filter(mgr):
    """list_review_requests 按 status 过滤"""
    r = mgr.create_workspace("W", "alice")
    rev = mgr.create_review_request(r["workspace_id"], "T1", "alice")
    mgr.update_review_status(rev["review_id"], "approved")
    mgr.create_review_request(r["workspace_id"], "T2", "alice")  # open
    open_reviews = mgr.list_review_requests(r["workspace_id"], status="open")
    approved = mgr.list_review_requests(r["workspace_id"], status="approved")
    assert len(open_reviews) == 1
    assert len(approved) == 1
    assert approved[0]["status"] == "approved"


def test_add_review_comment(mgr):
    """add_review_comment 添加评论到 reviews.comments"""
    r = mgr.create_workspace("W", "alice")
    rev = mgr.create_review_request(r["workspace_id"], "T1", "alice")
    result = mgr.add_review_comment(rev["review_id"], "bob", "需要修改")
    assert result == {"success": True}
    reviews = mgr.list_review_requests(r["workspace_id"])
    assert len(reviews[0]["comments"]) == 1
    assert reviews[0]["comments"][0]["user"] == "bob"
    assert reviews[0]["comments"][0]["comment"] == "需要修改"
    assert "timestamp" in reviews[0]["comments"][0]


def test_add_review_comment_nonexistent(mgr):
    """add_review_comment 对不存在的 review 返回错误"""
    result = mgr.add_review_comment("no-such-id", "bob", "x")
    assert result["success"] is False
    assert "不存在" in result["error"]


def test_update_review_status_valid(mgr):
    """update_review_status 支持所有合法状态"""
    r = mgr.create_workspace("W", "alice")
    rev = mgr.create_review_request(r["workspace_id"], "T", "alice")

    for status in ("approved", "changes_requested", "open", "closed"):
        result = mgr.update_review_status(rev["review_id"], status)
        assert result["success"] is True
        assert result["new_status"] == status


def test_update_review_status_sets_resolved_at(mgr):
    """approved/closed 状态会设置 resolved_at, open/changes_requested 不会"""
    r = mgr.create_workspace("W", "alice")
    rev = mgr.create_review_request(r["workspace_id"], "T", "alice")

    mgr.update_review_status(rev["review_id"], "changes_requested")
    assert mgr.list_review_requests(r["workspace_id"])[0]["resolved_at"] is None

    mgr.update_review_status(rev["review_id"], "approved")
    assert mgr.list_review_requests(r["workspace_id"])[0]["resolved_at"] is not None


def test_update_review_status_invalid(mgr):
    """update_review_status 非法状态返回错误"""
    r = mgr.create_workspace("W", "alice")
    rev = mgr.create_review_request(r["workspace_id"], "T", "alice")
    result = mgr.update_review_status(rev["review_id"], "garbage")
    assert result["success"] is False
    assert "无效状态" in result["error"]


# ── 活动 Feed ──

def test_get_activity_feed_limit(mgr):
    """get_activity_feed 默认 limit=30"""
    r = mgr.create_workspace("W", "alice")
    # 创建 5 个 review 触发 5 条活动
    for i in range(5):
        mgr.create_review_request(r["workspace_id"], f"T{i}", "alice")
    feed = mgr.get_activity_feed(r["workspace_id"], limit=3)
    assert len(feed) == 3


def test_share_session(mgr):
    """share_session 写入 session_share 活动"""
    r = mgr.create_workspace("W", "alice")
    result = mgr.share_session(r["workspace_id"], "session-xyz-123", "alice")
    assert result["success"] is True
    assert result["workspace_id"] == r["workspace_id"]
    assert result["session_id"] == "session-xyz-123"
    feed = mgr.get_activity_feed(r["workspace_id"])
    # share_session 取 session_id 前 8 个字符: "session-"（s-e-s-s-i-o-n-dash）
    assert any(a["action"] == "session_share" and "session-" in a["detail"] for a in feed)


# ── 单例 ──

def test_get_team_workspace_manager_singleton():
    """get_team_workspace_manager 返回同一个实例"""
    a = get_team_workspace_manager()
    b = get_team_workspace_manager()
    assert a is b
    assert isinstance(a, TeamWorkspaceManager)


# ── _get_conn 复用 ──

def test_get_conn_reuses_threadlocal(mgr):
    """_get_conn 在同一线程多次调用返回同一连接"""
    conn1 = mgr._get_conn()
    conn2 = mgr._get_conn()
    assert conn1 is conn2


def test_get_conn_creates_db_dir(tmp_path):
    """_get_conn 创建数据库父目录"""
    db_path = tmp_path / "sub" / "teams.db"
    import threading
    instance = TeamWorkspaceManager.__new__(TeamWorkspaceManager)
    instance._db_path = db_path
    instance._local = threading.local()
    instance._init_db()
    assert db_path.exists()
