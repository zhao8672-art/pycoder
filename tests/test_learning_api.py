"""
封闭学习循环 API 路由单元测试 — 覆盖 learning_api.py 所有端点

测试范围:
  - POST /api/learning/observe        — 观察执行
  - POST /api/learning/reflect        — 反思模式
  - POST /api/learning/generate-skill — 生成技能
  - POST /api/learning/apply          — 应用反馈
  - POST /api/learning/cycle          — 一键运行完整闭环
  - GET  /api/learning/stats          — 获取学习统计
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pycoder.capabilities.self_evo.learning.closed_loop import (
    LearningObservation,
    LearnedSkill,
)


# ── 辅助函数 ──────────────────────────────────────────────


def _make_observation(
    task_id: str = "task-001",
    success: bool = True,
    steps: int = 5,
    errors: list[str] | None = None,
) -> LearningObservation:
    """创建模拟的 LearningObservation"""
    return LearningObservation(
        task_id=task_id,
        task_description="测试任务",
        success=success,
        steps_taken=steps,
        errors_encountered=errors or [],
        patterns_used=["pattern_a", "pattern_b"],
        patterns_failed=[],
    )


def _make_skill(
    skill_id: str = "skill_abc123",
    name: str = "测试技能",
    description: str = "从测试中习得的技能",
) -> LearnedSkill:
    """创建模拟的 LearnedSkill"""
    return LearnedSkill(
        id=skill_id,
        name=name,
        description=description,
        pattern="test_pattern",
        strategy="先分析再编码",
        success_rate=0.85,
        usage_count=10,
    )


def _make_reflection() -> dict:
    """创建模拟的反思结果"""
    return {
        "patterns_found": [
            {"pattern": "先读后写", "confidence": 0.9},
            {"pattern": "小步提交", "confidence": 0.8},
        ],
        "patterns_avoid": [
            {"pattern": "一次性大改", "reason": "风险高"},
        ],
        "confidence": 0.85,
        "recommendations": ["建议小步迭代", "定期运行测试"],
        "task_id": "task-001",
    }


def _make_cycle_result(task_id: str = "task-001") -> dict:
    """创建模拟的闭环结果"""
    return {
        "task_id": task_id,
        "cycle_duration_ms": 1234.5,
        "observation": {"success": True, "steps": 3, "errors": 0},
        "reflection": {
            "patterns_found": 2,
            "patterns_avoid": 1,
            "confidence": 0.85,
            "recommendations": ["建议1"],
        },
        "skills_generated": 2,
        "new_skill_ids": ["skill_abc", "skill_def"],
        "feedback": {
            "matched_skills": 2,
            "context_hints": ["提示1"],
        },
        "refine": {"pruned": 0, "updated": 0},
        "timestamp": 1700000000.0,
    }


def _make_stats() -> dict:
    """创建模拟的学习统计"""
    return {
        "total_observations": 42,
        "success_rate": 0.78,
        "total_skills": 15,
        "active_skills": 12,
        "top_errors": [
            ("路径穿越", 5),
            ("类型错误", 3),
        ],
        "recent_trends": [],
        "avg_steps_per_task": 8.5,
    }


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def mock_loop() -> MagicMock:
    """创建模拟的 ClosedLearningLoop"""
    loop = MagicMock()

    # observe 返回 LearningObservation
    loop.observe = AsyncMock(return_value=_make_observation())

    # reflect 返回反思字典
    loop.reflect = AsyncMock(return_value=_make_reflection())

    # generate_skill 返回技能列表
    loop.generate_skill = AsyncMock(
        return_value=[
            _make_skill("skill_abc", "技能A"),
            _make_skill("skill_def", "技能B"),
        ]
    )

    # apply_feedback 返回反馈字典
    loop.apply_feedback = AsyncMock(
        return_value={
            "matched_skills": [
                {"id": "skill_abc", "name": "技能A", "score": 0.9},
            ],
            "context_hints": ["使用小步提交策略"],
            "augmented_prompt": "增强后的提示词...",
        }
    )

    # run_cycle 返回完整闭环结果
    loop.run_cycle = AsyncMock(return_value=_make_cycle_result())

    # get_stats 返回统计信息
    loop.get_stats = MagicMock(return_value=_make_stats())

    return loop


@pytest.fixture
def client_with_loop(mock_loop: MagicMock) -> TestClient:
    """注入模拟 ClosedLearningLoop 的 TestClient"""
    from pycoder.server.routers import learning_api

    # 保存原始单例
    orig_loop = learning_api._loop
    learning_api._loop = mock_loop

    from pycoder.server.app import app

    with TestClient(app) as c:
        yield c

    learning_api._loop = orig_loop


# ── POST /api/learning/observe 测试 ───────────────────────


class TestObserveExecution:
    """观察执行端点"""

    def test_observe_success(self, client_with_loop: TestClient) -> None:
        """测试成功记录执行观察"""
        resp = client_with_loop.post(
            "/api/learning/observe",
            json={
                "task_id": "task-001",
                "execution_result": {
                    "description": "测试任务",
                    "success": True,
                    "steps": 5,
                    "errors": [],
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["task_id"] == "task-001"
        assert data["recorded"] is True
        assert data["steps"] == 5
        assert data["errors_count"] == 0

    def test_observe_with_errors(self, client_with_loop: TestClient, mock_loop: MagicMock) -> None:
        """测试记录包含错误的观察"""
        mock_loop.observe = AsyncMock(
            return_value=_make_observation(
                task_id="task-002", success=False, steps=3, errors=["类型错误", "路径错误"]
            )
        )
        resp = client_with_loop.post(
            "/api/learning/observe",
            json={
                "task_id": "task-002",
                "execution_result": {
                    "description": "失败任务",
                    "success": False,
                    "steps": 3,
                    "errors": ["类型错误", "路径错误"],
                    "patterns_used": ["pattern_x"],
                    "patterns_failed": ["pattern_y"],
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["errors_count"] == 2
        assert data["steps"] == 3

    def test_observe_empty_task_id(self, client_with_loop: TestClient) -> None:
        """测试空 task_id 返回 400"""
        resp = client_with_loop.post(
            "/api/learning/observe",
            json={
                "task_id": "",
                "execution_result": {"success": True},
            },
        )
        assert resp.status_code == 400
        assert "task_id" in resp.json()["detail"]

    def test_observe_whitespace_task_id(self, client_with_loop: TestClient) -> None:
        """测试纯空白 task_id 返回 400"""
        resp = client_with_loop.post(
            "/api/learning/observe",
            json={
                "task_id": "   ",
                "execution_result": {"success": True},
            },
        )
        assert resp.status_code == 400

    def test_observe_loop_exception(self, client_with_loop: TestClient, mock_loop: MagicMock) -> None:
        """测试循环异常返回 500"""
        mock_loop.observe = AsyncMock(side_effect=Exception("数据库连接失败"))

        resp = client_with_loop.post(
            "/api/learning/observe",
            json={
                "task_id": "task-err",
                "execution_result": {"success": True},
            },
        )
        assert resp.status_code == 500
        assert "观察记录失败" in resp.json()["detail"]

    def test_observe_with_metadata(self, client_with_loop: TestClient, mock_loop: MagicMock) -> None:
        """测试带元数据的观察记录"""
        mock_loop.observe = AsyncMock(
            return_value=_make_observation(task_id="task-meta", steps=1)
        )
        resp = client_with_loop.post(
            "/api/learning/observe",
            json={
                "task_id": "task-meta",
                "execution_result": {
                    "description": "元数据测试",
                    "success": True,
                    "steps": 1,
                    "metadata": {"model": "gpt-4", "temperature": 0.3},
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["task_id"] == "task-meta"


# ── POST /api/learning/reflect 测试 ───────────────────────


class TestReflectPatterns:
    """反思模式端点"""

    def test_reflect_success(self, client_with_loop: TestClient) -> None:
        """测试成功反思"""
        resp = client_with_loop.post(
            "/api/learning/reflect",
            json={
                "observation": {
                    "task_id": "task-001",
                    "task_description": "分析任务",
                    "success": True,
                    "steps_taken": 5,
                    "errors_encountered": [],
                    "patterns_used": ["先读后写"],
                    "patterns_failed": [],
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "reflection" in data
        assert "patterns_found" in data["reflection"]
        assert "patterns_avoid" in data["reflection"]
        assert "confidence" in data["reflection"]
        assert "recommendations" in data["reflection"]

    def test_reflect_empty_observation(self, client_with_loop: TestClient) -> None:
        """测试空 observation 返回 400"""
        resp = client_with_loop.post(
            "/api/learning/reflect",
            json={"observation": {}},
        )
        assert resp.status_code == 400
        assert "observation" in resp.json()["detail"]

    def test_reflect_with_failed_patterns(self, client_with_loop: TestClient) -> None:
        """测试反射失败模式"""
        resp = client_with_loop.post(
            "/api/learning/reflect",
            json={
                "observation": {
                    "task_id": "task-fail",
                    "task_description": "失败任务",
                    "success": False,
                    "steps_taken": 10,
                    "errors_encountered": ["超时", "内存不足"],
                    "patterns_used": ["批量处理"],
                    "patterns_failed": ["大文件读取"],
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_reflect_loop_exception(self, client_with_loop: TestClient, mock_loop: MagicMock) -> None:
        """测试反思异常返回 500"""
        mock_loop.reflect = AsyncMock(side_effect=Exception("分析失败"))

        resp = client_with_loop.post(
            "/api/learning/reflect",
            json={
                "observation": {
                    "task_id": "task-err",
                    "success": True,
                },
            },
        )
        assert resp.status_code == 500
        assert "反思分析失败" in resp.json()["detail"]

    def test_reflect_minimal_observation(self, client_with_loop: TestClient) -> None:
        """测试最小观察数据"""
        resp = client_with_loop.post(
            "/api/learning/reflect",
            json={
                "observation": {
                    "task_id": "minimal-task",
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


# ── POST /api/learning/generate-skill 测试 ────────────────


class TestGenerateSkill:
    """生成技能端点"""

    def test_generate_skill_success(self, client_with_loop: TestClient) -> None:
        """测试成功生成技能"""
        resp = client_with_loop.post(
            "/api/learning/generate-skill",
            json={
                "reflection": {
                    "patterns_found": [
                        {"pattern": "先读后写", "confidence": 0.9},
                        {"pattern": "小步提交", "confidence": 0.8},
                    ],
                    "patterns_avoid": [],
                    "task_id": "task-001",
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["skills_generated"] == 2
        assert len(data["skill_ids"]) == 2
        assert len(data["skill_names"]) == 2
        assert "skill_abc" in data["skill_ids"]
        assert "skill_def" in data["skill_ids"]

    def test_generate_skill_empty_reflection(self, client_with_loop: TestClient) -> None:
        """测试空 reflection 返回 400"""
        resp = client_with_loop.post(
            "/api/learning/generate-skill",
            json={"reflection": {}},
        )
        assert resp.status_code == 400
        assert "reflection" in resp.json()["detail"]

    def test_generate_skill_zero_skills(self, client_with_loop: TestClient, mock_loop: MagicMock) -> None:
        """测试未生成任何技能"""
        mock_loop.generate_skill = AsyncMock(return_value=[])

        resp = client_with_loop.post(
            "/api/learning/generate-skill",
            json={
                "reflection": {
                    "patterns_found": [],
                    "patterns_avoid": [],
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["skills_generated"] == 0
        assert data["skill_ids"] == []

    def test_generate_skill_loop_exception(self, client_with_loop: TestClient, mock_loop: MagicMock) -> None:
        """测试生成异常返回 500"""
        mock_loop.generate_skill = AsyncMock(side_effect=Exception("技能生成失败"))

        resp = client_with_loop.post(
            "/api/learning/generate-skill",
            json={
                "reflection": {
                    "patterns_found": [{"pattern": "test", "confidence": 0.5}],
                },
            },
        )
        assert resp.status_code == 500
        assert "技能生成失败" in resp.json()["detail"]

    def test_generate_skill_single_skill(self, client_with_loop: TestClient, mock_loop: MagicMock) -> None:
        """测试生成单个技能"""
        mock_loop.generate_skill = AsyncMock(
            return_value=[_make_skill("skill_single", "单技能")]
        )

        resp = client_with_loop.post(
            "/api/learning/generate-skill",
            json={
                "reflection": {
                    "patterns_found": [{"pattern": "单一模式", "confidence": 0.7}],
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["skills_generated"] == 1
        assert data["skill_ids"] == ["skill_single"]
        assert data["skill_names"] == ["单技能"]


# ── POST /api/learning/apply 测试 ─────────────────────────


class TestApplyFeedback:
    """应用反馈端点"""

    def test_apply_feedback_success(self, client_with_loop: TestClient) -> None:
        """测试成功应用反馈"""
        resp = client_with_loop.post(
            "/api/learning/apply",
            json={"task_description": "实现一个登录功能"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "feedback" in data
        assert "matched_skills" in data["feedback"]
        assert "context_hints" in data["feedback"]

    def test_apply_feedback_empty_description(self, client_with_loop: TestClient) -> None:
        """测试空任务描述返回 400"""
        resp = client_with_loop.post(
            "/api/learning/apply",
            json={"task_description": ""},
        )
        assert resp.status_code == 400
        assert "task_description" in resp.json()["detail"]

    def test_apply_feedback_whitespace_description(self, client_with_loop: TestClient) -> None:
        """测试纯空白描述返回 400"""
        resp = client_with_loop.post(
            "/api/learning/apply",
            json={"task_description": "   "},
        )
        assert resp.status_code == 400

    def test_apply_feedback_loop_exception(self, client_with_loop: TestClient, mock_loop: MagicMock) -> None:
        """测试反馈异常返回 500"""
        mock_loop.apply_feedback = AsyncMock(side_effect=Exception("反馈服务不可用"))

        resp = client_with_loop.post(
            "/api/learning/apply",
            json={"task_description": "新任务"},
        )
        assert resp.status_code == 500
        assert "反馈应用失败" in resp.json()["detail"]

    def test_apply_feedback_no_matches(self, client_with_loop: TestClient, mock_loop: MagicMock) -> None:
        """测试无匹配技能时返回空反馈"""
        mock_loop.apply_feedback = AsyncMock(
            return_value={
                "matched_skills": [],
                "context_hints": [],
                "augmented_prompt": "原始提示词",
            }
        )
        resp = client_with_loop.post(
            "/api/learning/apply",
            json={"task_description": "完全陌生的任务"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["feedback"]["matched_skills"] == []


# ── POST /api/learning/cycle 测试 ─────────────────────────


class TestRunCycle:
    """完整闭环端点"""

    def test_run_cycle_success(self, client_with_loop: TestClient) -> None:
        """测试成功运行完整闭环"""
        resp = client_with_loop.post(
            "/api/learning/cycle",
            json={
                "task_id": "task-001",
                "execution_result": {
                    "description": "完整闭环测试",
                    "success": True,
                    "steps": 3,
                    "errors": [],
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "task-001"
        assert data["cycle_duration_ms"] > 0
        assert "observation" in data
        assert "reflection" in data
        assert data["skills_generated"] == 2
        assert len(data["new_skill_ids"]) == 2
        assert "feedback" in data
        assert "refine" in data
        assert "timestamp" in data

    def test_run_cycle_empty_task_id(self, client_with_loop: TestClient) -> None:
        """测试空 task_id 返回 400"""
        resp = client_with_loop.post(
            "/api/learning/cycle",
            json={
                "task_id": "",
                "execution_result": {"success": True},
            },
        )
        assert resp.status_code == 400

    def test_run_cycle_loop_exception(self, client_with_loop: TestClient, mock_loop: MagicMock) -> None:
        """测试闭环异常返回 500"""
        mock_loop.run_cycle = AsyncMock(side_effect=Exception("闭环执行异常"))

        resp = client_with_loop.post(
            "/api/learning/cycle",
            json={
                "task_id": "task-err",
                "execution_result": {"success": True},
            },
        )
        assert resp.status_code == 500
        assert "闭环执行失败" in resp.json()["detail"]

    def test_run_cycle_with_failed_task(self, client_with_loop: TestClient, mock_loop: MagicMock) -> None:
        """测试失败任务的闭环"""
        mock_loop.run_cycle = AsyncMock(
            return_value=_make_cycle_result("task-fail")
        )
        # 修改 cycle_result 中 observation.success 为 False
        mock_loop.run_cycle.return_value["observation"]["success"] = False
        mock_loop.run_cycle.return_value["observation"]["errors"] = 2

        resp = client_with_loop.post(
            "/api/learning/cycle",
            json={
                "task_id": "task-fail",
                "execution_result": {
                    "description": "失败任务",
                    "success": False,
                    "steps": 1,
                    "errors": ["解析错误", "类型错误"],
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "task-fail"


# ── GET /api/learning/stats 测试 ──────────────────────────


class TestGetStats:
    """学习统计端点"""

    def test_get_stats_success(self, client_with_loop: TestClient) -> None:
        """测试获取学习统计"""
        resp = client_with_loop.get("/api/learning/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "stats" in data
        assert data["stats"]["total_observations"] == 42
        assert data["stats"]["success_rate"] == 0.78
        assert data["stats"]["total_skills"] == 15
        assert "top_errors" in data["stats"]
        assert "recent_trends" in data["stats"]

    def test_get_stats_no_data(self, client_with_loop: TestClient, mock_loop: MagicMock) -> None:
        """测试空统计信息"""
        mock_loop.get_stats = MagicMock(
            return_value={
                "total_observations": 0,
                "success_rate": 0.0,
                "total_skills": 0,
                "active_skills": 0,
                "top_errors": [],
                "recent_trends": [],
                "avg_steps_per_task": 0.0,
            }
        )
        resp = client_with_loop.get("/api/learning/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["stats"]["total_observations"] == 0
        assert data["stats"]["total_skills"] == 0

    def test_get_stats_loop_exception(self, client_with_loop: TestClient, mock_loop: MagicMock) -> None:
        """测试统计异常返回 500"""
        mock_loop.get_stats = MagicMock(side_effect=Exception("统计获取失败"))

        resp = client_with_loop.get("/api/learning/stats")
        assert resp.status_code == 500
        assert "统计获取失败" in resp.json()["detail"]