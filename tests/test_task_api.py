"""
任务评分与持久化 API 路由单元测试 — 覆盖 task_api.py 所有端点

测试范围:
  - POST /api/task/grade              — 评估任务难度
  - POST /api/task/save               — 保存任务状态
  - GET  /api/task/{task_id}          — 加载任务
  - GET  /api/task/list               — 列出任务
  - POST /api/task/{task_id}/checkpoint — 创建断点
  - POST /api/task/{task_id}/resume   — 从断点恢复
  - GET  /api/task/stats              — 获取任务统计
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pycoder.server.services.task_grader import TaskGrade, TaskGrader
from pycoder.server.services.task_persistence import (
    TaskPersistence,
    TaskState,
)


# ── 辅助函数 ──────────────────────────────────────────────


def _make_task_grade(
    level: str = "MEDIUM",
    score: int = 50,
) -> TaskGrade:
    """创建测试用 TaskGrade"""
    return TaskGrade(
        level=level,
        max_steps=20,
        temperature=0.3,
        max_tokens=4096,
        reasoning_depth="standard",
        description="中等复杂度的编程任务",
        score=score,
        detected_types=["coding", "testing"],
    )


def _make_task_state(
    task_id: str = "task-001",
    description: str = "测试任务",
    status: str = "pending",
    grade: str = "MEDIUM",
    **kwargs: object,
) -> TaskState:
    """创建测试用 TaskState"""
    defaults: dict[str, object] = {
        "task_id": task_id,
        "description": description,
        "status": status,
        "grade": grade,
        "created_at": time.time(),
        "updated_at": time.time(),
        "completed_at": None,
        "steps_completed": 0,
        "current_step": "",
        "checkpoint_data": {},
        "result": {},
        "error": "",
    }
    defaults.update(kwargs)
    return TaskState(**defaults)  # type: ignore


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def mock_grader() -> MagicMock:
    """创建模拟的 TaskGrader"""
    grader = MagicMock(spec=TaskGrader)
    grader.grade.return_value = _make_task_grade()
    return grader


@pytest.fixture
def mock_persistence() -> MagicMock:
    """创建模拟的 TaskPersistence"""
    persistence = MagicMock(spec=TaskPersistence)
    persistence.save_task = AsyncMock(
        return_value=_make_task_state("task-001", status="pending")
    )
    persistence.load_task = AsyncMock(
        return_value=_make_task_state("task-001", status="running")
    )
    persistence.list_tasks = AsyncMock(return_value=[])
    persistence.create_checkpoint = AsyncMock(
        return_value=_make_task_state("task-001", status="paused")
    )
    persistence.resume_from_checkpoint = AsyncMock(
        return_value=_make_task_state("task-001", status="running")
    )
    persistence.get_stats_async = AsyncMock(
        return_value={
            "total": 10,
            "by_status": {"pending": 3, "running": 2, "completed": 5},
            "by_grade": {"LIGHT": 4, "MEDIUM": 4, "HEAVY": 2},
            "avg_steps_completed": 12.5,
            "db_path": "/tmp/test.db",
        }
    )
    return persistence


@pytest.fixture
def client_with_services(
    mock_grader: MagicMock, mock_persistence: MagicMock
) -> TestClient:
    """注入模拟 TaskGrader 和 TaskPersistence 的 TestClient"""
    from pycoder.server.routers import task_api

    # 保存原始单例
    orig_grader = task_api._grader
    orig_persistence = task_api._persistence

    task_api._grader = mock_grader
    task_api._persistence = mock_persistence

    from pycoder.server.app import app

    with TestClient(app) as c:
        yield c

    task_api._grader = orig_grader
    task_api._persistence = orig_persistence


# ── POST /api/task/grade 测试 ─────────────────────────────


class TestGradeTask:
    """任务难度分级端点"""

    def test_grade_task_success(self, client_with_services: TestClient) -> None:
        """测试成功评估任务难度"""
        resp = client_with_services.post(
            "/api/task/grade",
            json={"description": "实现一个完整的用户认证系统"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["level"] == "MEDIUM"
        assert data["max_steps"] == 20
        assert data["temperature"] == 0.3
        assert data["max_tokens"] == 4096
        assert data["reasoning_depth"] == "standard"
        assert data["score"] == 50
        assert "detected_types" in data

    def test_grade_light_task(self, client_with_services: TestClient, mock_grader: MagicMock) -> None:
        """测试简单任务分级"""
        mock_grader.grade.return_value = _make_task_grade(level="LIGHT", score=20)

        resp = client_with_services.post(
            "/api/task/grade",
            json={"description": "写一个 hello world"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["level"] == "LIGHT"
        assert data["score"] == 20

    def test_grade_heavy_task(self, client_with_services: TestClient, mock_grader: MagicMock) -> None:
        """测试复杂任务分级"""
        mock_grader.grade.return_value = _make_task_grade(level="HEAVY", score=85)

        resp = client_with_services.post(
            "/api/task/grade",
            json={"description": "构建一个完整的分布式微服务架构"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["level"] == "HEAVY"
        assert data["score"] == 85

    def test_grade_task_empty_description(self, client_with_services: TestClient) -> None:
        """测试空描述返回 422"""
        resp = client_with_services.post(
            "/api/task/grade",
            json={"description": ""},
        )
        assert resp.status_code == 422

    def test_grade_task_response_fields(self, client_with_services: TestClient) -> None:
        """测试分级响应包含所有字段"""
        resp = client_with_services.post(
            "/api/task/grade",
            json={"description": "一个中等任务"},
        )
        assert resp.status_code == 200
        data = resp.json()
        expected_fields = [
            "level", "max_steps", "temperature", "max_tokens",
            "reasoning_depth", "description", "score", "detected_types",
        ]
        for field in expected_fields:
            assert field in data, f"缺少字段 {field}"


# ── POST /api/task/save 测试 ──────────────────────────────


class TestSaveTask:
    """保存任务端点"""

    def test_save_task_success(self, client_with_services: TestClient) -> None:
        """测试成功保存任务"""
        resp = client_with_services.post(
            "/api/task/save",
            json={
                "description": "新任务",
                "status": "pending",
                "grade": "MEDIUM",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "task_id" in data
        assert data["status"] == "pending"
        assert data["grade"] == "MEDIUM"

    def test_save_task_with_custom_id(self, client_with_services: TestClient, mock_persistence: MagicMock) -> None:
        """测试使用自定义 task_id 保存"""
        mock_persistence.save_task = AsyncMock(
            return_value=_make_task_state("custom-123", status="running")
        )

        resp = client_with_services.post(
            "/api/task/save",
            json={
                "task_id": "custom-123",
                "description": "自定义任务",
                "status": "running",
                "grade": "LIGHT",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "custom-123"

    def test_save_task_auto_generate_id(self, client_with_services: TestClient) -> None:
        """测试自动生成 task_id"""
        resp = client_with_services.post(
            "/api/task/save",
            json={
                "description": "自动 ID 任务",
                "status": "pending",
                "grade": "MEDIUM",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] != ""
        assert len(data["task_id"]) > 0

    def test_save_task_invalid_status(self, client_with_services: TestClient) -> None:
        """测试无效状态返回 400"""
        resp = client_with_services.post(
            "/api/task/save",
            json={
                "description": "无效状态",
                "status": "invalid_status",
                "grade": "MEDIUM",
            },
        )
        assert resp.status_code == 400
        assert "无效状态" in resp.json()["detail"]

    def test_save_task_invalid_grade(self, client_with_services: TestClient) -> None:
        """测试无效级别返回 400"""
        resp = client_with_services.post(
            "/api/task/save",
            json={
                "description": "无效级别",
                "status": "pending",
                "grade": "INVALID_GRADE",
            },
        )
        assert resp.status_code == 400
        assert "无效级别" in resp.json()["detail"]

    def test_save_task_with_checkpoint_data(
        self, client_with_services: TestClient, mock_persistence: MagicMock
    ) -> None:
        """测试带断点数据保存"""
        mock_persistence.save_task = AsyncMock(
            return_value=_make_task_state("task-001", status="paused", grade="HEAVY")
        )
        resp = client_with_services.post(
            "/api/task/save",
            json={
                "description": "带断点任务",
                "status": "paused",
                "grade": "HEAVY",
                "steps_completed": 5,
                "current_step": "数据处理中",
                "checkpoint_data": {"step": 5, "context": {"key": "val"}},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "paused"
        assert data["grade"] == "HEAVY"


# ── GET /api/task/{task_id} 测试 ──────────────────────────


class TestLoadTask:
    """加载任务端点"""

    def test_load_task_success(self, client_with_services: TestClient) -> None:
        """测试加载存在的任务"""
        resp = client_with_services.get("/api/task/task-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "task-001"
        assert data["status"] == "running"
        assert "description" in data

    def test_load_task_not_found(self, client_with_services: TestClient, mock_persistence: MagicMock) -> None:
        """测试加载不存在的任务返回 404"""
        mock_persistence.load_task = AsyncMock(return_value=None)

        resp = client_with_services.get("/api/task/nonexistent")
        assert resp.status_code == 404
        assert "不存在" in resp.json()["detail"]

    def test_load_task_fields(self, client_with_services: TestClient) -> None:
        """测试加载任务包含完整字段"""
        resp = client_with_services.get("/api/task/task-001")
        assert resp.status_code == 200
        data = resp.json()
        expected_fields = [
            "task_id", "description", "status", "grade",
            "created_at", "updated_at", "completed_at",
            "steps_completed", "current_step",
            "checkpoint_data", "result", "error",
        ]
        for field in expected_fields:
            assert field in data, f"缺少字段 {field}"


# ── GET /api/task/list 测试 ───────────────────────────────


class TestListTasks:
    """列出任务端点"""

    def test_list_tasks_default(self, client_with_services: TestClient) -> None:
        """测试默认列出任务"""
        resp = client_with_services.get("/api/task/list")
        assert resp.status_code == 200
        data = resp.json()
        assert "tasks" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data

    def test_list_tasks_with_status_filter(self, client_with_services: TestClient) -> None:
        """测试按状态过滤"""
        resp = client_with_services.get("/api/task/list?status=pending")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 0

    def test_list_tasks_with_grade_filter(self, client_with_services: TestClient) -> None:
        """测试按级别过滤"""
        resp = client_with_services.get("/api/task/list?grade=LIGHT")
        assert resp.status_code == 200

    def test_list_tasks_with_pagination(self, client_with_services: TestClient) -> None:
        """测试分页参数"""
        resp = client_with_services.get("/api/task/list?limit=10&offset=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 10
        assert data["offset"] == 5

    def test_list_tasks_invalid_status(self, client_with_services: TestClient) -> None:
        """测试无效状态过滤返回 400"""
        resp = client_with_services.get("/api/task/list?status=invalid")
        assert resp.status_code == 400
        assert "无效状态" in resp.json()["detail"]

    def test_list_tasks_invalid_grade(self, client_with_services: TestClient) -> None:
        """测试无效级别过滤返回 400"""
        resp = client_with_services.get("/api/task/list?grade=INVALID")
        assert resp.status_code == 400
        assert "无效级别" in resp.json()["detail"]

    def test_list_tasks_with_results(self, client_with_services: TestClient, mock_persistence: MagicMock) -> None:
        """测试列出有结果的任务"""
        mock_persistence.list_tasks = AsyncMock(return_value=[
            _make_task_state("t1", "任务1", "completed"),
            _make_task_state("t2", "任务2", "running"),
            _make_task_state("t3", "任务3", "pending"),
        ])

        resp = client_with_services.get("/api/task/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["tasks"]) == 3


# ── POST /api/task/{task_id}/checkpoint 测试 ──────────────


class TestCreateCheckpoint:
    """创建断点端点"""

    def test_create_checkpoint_success(self, client_with_services: TestClient) -> None:
        """测试成功创建断点"""
        resp = client_with_services.post(
            "/api/task/task-001/checkpoint",
            json={
                "data": {"step": 3, "context": {"var": "value"}},
                "current_step": "正在处理第3步",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "task-001"
        assert data["status"] == "paused"

    def test_create_checkpoint_task_not_found(
        self, client_with_services: TestClient, mock_persistence: MagicMock
    ) -> None:
        """测试任务不存在返回 404"""
        mock_persistence.create_checkpoint = AsyncMock(return_value=None)

        resp = client_with_services.post(
            "/api/task/nonexistent/checkpoint",
            json={
                "data": {"step": 1},
                "current_step": "step 1",
            },
        )
        assert resp.status_code == 404
        assert "不存在" in resp.json()["detail"]

    def test_create_checkpoint_empty_data(self, client_with_services: TestClient) -> None:
        """测试空断点数据"""
        resp = client_with_services.post(
            "/api/task/task-001/checkpoint",
            json={
                "data": {},
                "current_step": "",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "task-001"


# ── POST /api/task/{task_id}/resume 测试 ──────────────────


class TestResumeTask:
    """从断点恢复任务端点"""

    def test_resume_task_success(self, client_with_services: TestClient) -> None:
        """测试成功恢复任务"""
        resp = client_with_services.post("/api/task/task-001/resume")
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "task-001"
        assert data["status"] == "running"

    def test_resume_task_not_found(
        self, client_with_services: TestClient, mock_persistence: MagicMock
    ) -> None:
        """测试恢复不存在的任务返回 404"""
        mock_persistence.resume_from_checkpoint = AsyncMock(return_value=None)

        resp = client_with_services.post("/api/task/nonexistent/resume")
        assert resp.status_code == 404
        assert "无法恢复" in resp.json()["detail"]


# ── GET /api/task/stats 测试 ──────────────────────────────


class TestTaskStats:
    """任务统计端点"""

    def test_get_stats_success(self, client_with_services: TestClient) -> None:
        """测试获取统计信息"""
        resp = client_with_services.get("/api/task/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 10
        assert "by_status" in data
        assert "by_grade" in data
        assert "avg_steps_completed" in data
        assert "db_path" in data

    def test_get_stats_empty(self, client_with_services: TestClient, mock_persistence: MagicMock) -> None:
        """测试空统计信息"""
        mock_persistence.get_stats_async = AsyncMock(
            return_value={
                "total": 0,
                "by_status": {},
                "by_grade": {},
                "avg_steps_completed": 0.0,
                "db_path": "/tmp/test.db",
            }
        )

        resp = client_with_services.get("/api/task/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["by_status"] == {}

    def test_get_stats_distribution(self, client_with_services: TestClient) -> None:
        """测试统计分布数据"""
        resp = client_with_services.get("/api/task/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["by_status"]["pending"] == 3
        assert data["by_status"]["running"] == 2
        assert data["by_status"]["completed"] == 5
        assert data["by_grade"]["LIGHT"] == 4
        assert data["by_grade"]["MEDIUM"] == 4
        assert data["by_grade"]["HEAVY"] == 2