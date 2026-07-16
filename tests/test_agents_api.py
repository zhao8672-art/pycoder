"""
专业 Agent 团队 API 路由单元测试 — 覆盖 agents_api.py 所有端点

测试范围:
  - GET  /api/agents/roles              — 列出角色
  - POST /api/agents/select             — 自动选角
  - POST /api/agents/team/create        — 创建团队
  - POST /api/agents/team/{team_id}/assign — 分配任务
  - GET  /api/agents/team/{team_id}/progress — 获取进度
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pycoder.brain.specialized_agents import (
    AgentProfile,
    AgentRole,
    SpecializedAgentTeam,
    Team,
    TeamTask,
)


# ── Fixtures ──────────────────────────────────────────────


def _make_mock_profile(
    role: AgentRole = AgentRole.DEVELOPER,
    name: str = "测试角色",
    description: str = "测试描述",
) -> AgentProfile:
    """创建模拟的 AgentProfile"""
    return AgentProfile(
        role=role,
        name=name,
        description=description,
        system_prompt="你是一个测试助手",
        allowed_tools=["read_file", "write_file"],
        temperature=0.3,
        max_tokens=8192,
        priority=5,
    )


@pytest.fixture
def mock_team_mgr() -> MagicMock:
    """创建模拟的 SpecializedAgentTeam"""
    mgr = MagicMock(spec=SpecializedAgentTeam)
    # 默认返回 10 个角色配置
    profiles = [
        _make_mock_profile(role=r)
        for r in AgentRole
    ]
    mgr.get_all_profiles.return_value = profiles
    mgr.select_agents.return_value = profiles[:3]
    return mgr


@pytest.fixture
def client_with_mgr(mock_team_mgr: MagicMock) -> TestClient:
    """注入模拟 team mgr 的 TestClient"""
    from pycoder.server.routers import agents_api

    # 替换全局单例
    orig = agents_api._agent_team
    agents_api._agent_team = mock_team_mgr

    from pycoder.server.app import app

    with TestClient(app) as c:
        yield c

    agents_api._agent_team = orig


# ── GET /api/agents/roles 测试 ────────────────────────────


class TestListRoles:
    """列出所有 Agent 角色"""

    def test_list_roles_success(self, client_with_mgr: TestClient) -> None:
        """测试成功列出所有角色"""
        resp = client_with_mgr.get("/api/agents/roles")
        assert resp.status_code == 200
        data = resp.json()
        assert "roles" in data
        assert "count" in data
        assert data["count"] == 10
        assert len(data["roles"]) == 10
        # 验证每个角色包含必要字段
        for role_data in data["roles"]:
            assert "role" in role_data
            assert "name" in role_data
            assert "description" in role_data

    def test_list_roles_empty(self, client_with_mgr: TestClient, mock_team_mgr: MagicMock) -> None:
        """测试角色列表为空的情况"""
        mock_team_mgr.get_all_profiles.return_value = []
        resp = client_with_mgr.get("/api/agents/roles")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["roles"] == []


# ── POST /api/agents/select 测试 ──────────────────────────


class TestSelectAgents:
    """自动选角端点"""

    def test_select_agents_success(self, client_with_mgr: TestClient) -> None:
        """测试根据任务描述自动选角"""
        resp = client_with_mgr.post(
            "/api/agents/select",
            json={"task_description": "编写代码并测试功能"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["task"] == "编写代码并测试功能"
        assert "selected" in data
        assert "count" in data
        assert data["count"] == len(data["selected"])

    def test_select_agents_empty_description(self, client_with_mgr: TestClient) -> None:
        """测试空任务描述返回 400"""
        resp = client_with_mgr.post(
            "/api/agents/select",
            json={"task_description": ""},
        )
        assert resp.status_code == 400
        assert "task_description" in resp.json()["detail"]

    def test_select_agents_whitespace_only(self, client_with_mgr: TestClient) -> None:
        """测试纯空白任务描述返回 400"""
        resp = client_with_mgr.post(
            "/api/agents/select",
            json={"task_description": "   "},
        )
        assert resp.status_code == 400

    def test_select_agents_no_match(self, client_with_mgr: TestClient, mock_team_mgr: MagicMock) -> None:
        """测试无匹配角色时返回空列表"""
        mock_team_mgr.select_agents.return_value = []
        resp = client_with_mgr.post(
            "/api/agents/select",
            json={"task_description": "xyz_abc_123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["selected"] == []

    def test_select_agents_response_fields(self, client_with_mgr: TestClient) -> None:
        """测试响应包含完整的角色字段"""
        resp = client_with_mgr.post(
            "/api/agents/select",
            json={"task_description": "设计系统架构"},
        )
        assert resp.status_code == 200
        data = resp.json()
        for role_data in data["selected"]:
            assert "role" in role_data
            assert "name" in role_data
            assert "description" in role_data
            assert "system_prompt" in role_data
            assert "allowed_tools" in role_data
            assert "temperature" in role_data
            assert "max_tokens" in role_data
            assert "priority" in role_data


# ── POST /api/agents/team/create 测试 ─────────────────────


class TestCreateTeam:
    """创建团队端点"""

    def test_create_team_success(self, client_with_mgr: TestClient, mock_team_mgr: MagicMock) -> None:
        """测试成功创建团队"""
        mock_team = Team(
            name="测试团队",
            roles=[AgentRole.ARCHITECT, AgentRole.DEVELOPER],
        )
        mock_team_mgr.create_team.return_value = mock_team

        resp = client_with_mgr.post(
            "/api/agents/team/create",
            json={
                "name": "测试团队",
                "roles": ["architect", "developer"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["team_name"] == "测试团队"
        assert "architect" in data["members"]
        assert "developer" in data["members"]
        assert data["member_count"] == 2

    def test_create_team_empty_name(self, client_with_mgr: TestClient) -> None:
        """测试空团队名返回 400"""
        resp = client_with_mgr.post(
            "/api/agents/team/create",
            json={"name": "", "roles": ["developer"]},
        )
        assert resp.status_code == 400
        assert "团队名称" in resp.json()["detail"]

    def test_create_team_no_roles(self, client_with_mgr: TestClient) -> None:
        """测试无角色列表返回 400"""
        resp = client_with_mgr.post(
            "/api/agents/team/create",
            json={"name": "测试", "roles": []},
        )
        assert resp.status_code == 400
        assert "至少需要一个角色" in resp.json()["detail"]

    def test_create_team_invalid_roles(self, client_with_mgr: TestClient) -> None:
        """测试无效角色名返回错误信息"""
        resp = client_with_mgr.post(
            "/api/agents/team/create",
            json={
                "name": "测试",
                "roles": ["invalid_role", "superhero"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "无效角色" in data["error"]
        assert "valid_roles" in data

    def test_create_team_mixed_valid_invalid(self, client_with_mgr: TestClient) -> None:
        """测试部分有效部分无效角色 —— 全部失败"""
        resp = client_with_mgr.post(
            "/api/agents/team/create",
            json={
                "name": "测试",
                "roles": ["developer", "superhero"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "superhero" in str(data["error"])


# ── POST /api/agents/team/{team_id}/assign 测试 ───────────


class TestAssignTask:
    """分配任务端点"""

    def test_assign_task_success(self, client_with_mgr: TestClient, mock_team_mgr: MagicMock) -> None:
        """测试成功分配任务"""
        mock_team = MagicMock()
        mock_team.name = "测试团队"
        mock_team.roles = [AgentRole.DEVELOPER, AgentRole.TESTER]
        mock_task = TeamTask(
            task_id="task-001",
            description="实现登录功能",
            assigned_role=AgentRole.DEVELOPER,
            status="pending",
        )
        mock_team.assign_task.return_value = mock_task
        mock_team_mgr.get_team.return_value = mock_team

        resp = client_with_mgr.post(
            "/api/agents/team/test-team/assign",
            json={
                "agent_role": "developer",
                "task": "实现登录功能",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["task_id"] == "task-001"
        assert data["role"] == "developer"
        assert data["status"] == "pending"

    def test_assign_task_team_not_found(self, client_with_mgr: TestClient, mock_team_mgr: MagicMock) -> None:
        """测试团队不存在返回 404"""
        mock_team_mgr.get_team.return_value = None

        resp = client_with_mgr.post(
            "/api/agents/team/nonexistent/assign",
            json={
                "agent_role": "developer",
                "task": "任务",
            },
        )
        assert resp.status_code == 404
        assert "团队不存在" in resp.json()["detail"]

    def test_assign_task_empty_role(self, client_with_mgr: TestClient) -> None:
        """测试空角色名返回 400"""
        resp = client_with_mgr.post(
            "/api/agents/team/test-team/assign",
            json={
                "agent_role": "",
                "task": "任务",
            },
        )
        assert resp.status_code == 400
        assert "agent_role" in resp.json()["detail"]

    def test_assign_task_empty_task(self, client_with_mgr: TestClient) -> None:
        """测试空任务描述返回 400"""
        resp = client_with_mgr.post(
            "/api/agents/team/test-team/assign",
            json={
                "agent_role": "developer",
                "task": "",
            },
        )
        assert resp.status_code == 400
        assert "task" in resp.json()["detail"]

    def test_assign_task_invalid_role(self, client_with_mgr: TestClient, mock_team_mgr: MagicMock) -> None:
        """测试无效角色名返回错误"""
        mock_team = Team(
            name="测试团队",
            roles=[AgentRole.DEVELOPER],
        )
        mock_team_mgr.get_team.return_value = mock_team

        resp = client_with_mgr.post(
            "/api/agents/team/test-team/assign",
            json={
                "agent_role": "superhero",
                "task": "任务",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "无效角色" in data["error"]

    def test_assign_task_role_not_in_team(self, client_with_mgr: TestClient, mock_team_mgr: MagicMock) -> None:
        """测试角色不在团队中返回错误"""
        mock_team = Team(
            name="测试团队",
            roles=[AgentRole.DEVELOPER],
        )
        mock_team_mgr.get_team.return_value = mock_team

        resp = client_with_mgr.post(
            "/api/agents/team/test-team/assign",
            json={
                "agent_role": "tester",
                "task": "任务",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "不在团队" in data["error"]
        assert "team_members" in data


# ── GET /api/agents/team/{team_id}/progress 测试 ──────────


class TestTeamProgress:
    """团队进度端点"""

    def test_get_progress_success(self, client_with_mgr: TestClient, mock_team_mgr: MagicMock) -> None:
        """测试成功获取进度"""
        mock_team = MagicMock()
        mock_team.name = "测试团队"
        mock_team.roles = [AgentRole.DEVELOPER, AgentRole.TESTER]
        mock_team.get_progress.return_value = {
            "team_name": "测试团队",
            "members": ["developer", "tester"],
            "total_tasks": 5,
            "done": 3,
            "failed": 0,
            "running": 1,
            "pending": 1,
            "progress_pct": 60.0,
            "tasks": {"task-1": {"status": "done", "role": "developer"}},
        }
        mock_team_mgr.get_team.return_value = mock_team

        resp = client_with_mgr.get("/api/agents/team/test-team/progress")
        assert resp.status_code == 200
        data = resp.json()
        assert data["team_name"] == "测试团队"
        assert data["total_tasks"] == 5
        assert data["done"] == 3
        assert data["progress_pct"] == 60.0
        assert "tasks" in data

    def test_get_progress_team_not_found(self, client_with_mgr: TestClient, mock_team_mgr: MagicMock) -> None:
        """测试团队不存在返回 404"""
        mock_team_mgr.get_team.return_value = None

        resp = client_with_mgr.get("/api/agents/team/nonexistent/progress")
        assert resp.status_code == 404
        assert "团队不存在" in resp.json()["detail"]

    def test_get_progress_zero_tasks(self, client_with_mgr: TestClient, mock_team_mgr: MagicMock) -> None:
        """测试空任务进度"""
        mock_team = MagicMock()
        mock_team.name = "空团队"
        mock_team.roles = [AgentRole.ARCHITECT]
        mock_team.get_progress.return_value = {
            "team_name": "空团队",
            "members": ["architect"],
            "total_tasks": 0,
            "done": 0,
            "failed": 0,
            "running": 0,
            "pending": 0,
            "progress_pct": 0.0,
            "tasks": {},
        }
        mock_team_mgr.get_team.return_value = mock_team

        resp = client_with_mgr.get("/api/agents/team/empty-team/progress")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_tasks"] == 0
        assert data["progress_pct"] == 0.0