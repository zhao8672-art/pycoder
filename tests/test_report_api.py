"""
进化报告 API 路由单元测试 — 覆盖 report_api.py 所有端点

测试范围:
  - POST /api/report/generate  — 生成进化报告（closed_loop / git_diff）
  - GET  /api/report/list      — 列出报告
  - GET  /api/report/{task_id} — 获取报告详情
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pycoder.server.services.evolution_report import (
    EvolutionReport,
    ReportGenerator,
)


# ── 辅助函数 ──────────────────────────────────────────────


def _make_evolution_report(
    task_id: str = "EVO-001",
    success: bool = True,
    num_changes: int = 3,
    net_lines: int = 150,
) -> EvolutionReport:
    """创建模拟的 EvolutionReport"""
    report = MagicMock(spec=EvolutionReport)
    report.task_id = task_id
    report.summary = f"进化报告 {task_id}: 共 {num_changes} 个文件变更"
    report.total_files_changed = num_changes
    report.net_lines = net_lines
    report.highest_risk = "INFO"
    report.success = success
    report.duration_seconds = 5.0
    report.created_at = "2025-01-01T00:00:00Z"
    report.to_dict.return_value = {
        "task_id": task_id,
        "summary": report.summary,
        "total_files_changed": num_changes,
        "net_lines": net_lines,
        "highest_risk": "INFO",
        "changes": [],
        "test_results": [],
        "risk_analysis": "无风险",
        "rollback_plan": "git revert",
        "lessons_learned": [],
        "success": success,
        "duration_seconds": 5.0,
        "metrics": {},
    }
    return report


def _make_report_list(count: int = 3) -> list[dict]:
    """创建模拟的报告列表"""
    return [
        {
            "file_name": f"EVO-{i:03d}.json",
            "path": f"reports/EVO-{i:03d}.json",
            "size_bytes": 1024 * (i + 1),
            "modified_at": "2025-01-01T00:00:00Z",
            "format": "json",
        }
        for i in range(1, count + 1)
    ]


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def mock_generator() -> MagicMock:
    """创建模拟的 ReportGenerator"""
    gen = MagicMock(spec=ReportGenerator)

    # 闭环模式报告生成
    gen.generate_from_closed_loop = AsyncMock(
        return_value=_make_evolution_report("EVO-CLOSED-001", success=True, num_changes=5)
    )

    # Git diff 模式报告生成
    gen.generate_from_git_diff = AsyncMock(
        return_value=_make_evolution_report("EVO-DIFF-001", success=True, num_changes=3)
    )

    # 保存报告
    gen.save_report = AsyncMock(return_value=None)

    # 列出报告
    gen.list_reports = AsyncMock(return_value=_make_report_list(3))

    # 获取报告
    gen.get_report = AsyncMock(
        return_value=_make_evolution_report("EVO-001", success=True)
    )

    return gen


@pytest.fixture
def client_with_generator(mock_generator: MagicMock) -> TestClient:
    """注入模拟 ReportGenerator 的 TestClient"""
    from pycoder.server.routers import report_api

    # 保存原始单例
    orig_generator = report_api._generator
    report_api._generator = mock_generator

    from pycoder.server.app import app

    with TestClient(app) as c:
        yield c

    report_api._generator = orig_generator


# ── POST /api/report/generate 测试 ────────────────────────


class TestGenerateReport:
    """生成报告端点"""

    def test_generate_closed_loop_success(self, client_with_generator: TestClient) -> None:
        """测试闭环模式生成报告成功"""
        resp = client_with_generator.post(
            "/api/report/generate",
            json={
                "mode": "closed_loop",
                "task_id": "EVO-001",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["task_id"] == "EVO-CLOSED-001"
        assert "summary" in data
        assert data["total_files_changed"] == 5
        assert "net_lines" in data
        assert "highest_risk" in data
        assert "已生成并保存" in data["message"]

    def test_generate_git_diff_success(self, client_with_generator: TestClient) -> None:
        """测试 Git diff 模式生成报告成功"""
        resp = client_with_generator.post(
            "/api/report/generate",
            json={
                "mode": "git_diff",
                "base_branch": "master",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["task_id"] == "EVO-DIFF-001"
        assert data["total_files_changed"] == 3

    def test_generate_git_diff_custom_branch(self, client_with_generator: TestClient) -> None:
        """测试自定义基准分支"""
        resp = client_with_generator.post(
            "/api/report/generate",
            json={
                "mode": "git_diff",
                "base_branch": "develop",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_generate_invalid_mode(self, client_with_generator: TestClient) -> None:
        """测试无效模式返回 400"""
        resp = client_with_generator.post(
            "/api/report/generate",
            json={
                "mode": "invalid_mode",
                "task_id": "EVO-001",
            },
        )
        assert resp.status_code == 400
        assert "不支持的模式" in resp.json()["detail"]

    def test_generate_closed_loop_no_task_id(self, client_with_generator: TestClient) -> None:
        """测试闭环模式不提供 task_id（使用默认值）"""
        resp = client_with_generator.post(
            "/api/report/generate",
            json={
                "mode": "closed_loop",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_generate_generator_exception(self, client_with_generator: TestClient, mock_generator: MagicMock) -> None:
        """测试生成器异常返回 500"""
        mock_generator.generate_from_git_diff = AsyncMock(
            side_effect=Exception("Git 命令不可用")
        )

        resp = client_with_generator.post(
            "/api/report/generate",
            json={
                "mode": "git_diff",
                "base_branch": "master",
            },
        )
        assert resp.status_code == 500
        assert "报告生成失败" in resp.json()["detail"]

    def test_generate_default_mode(self, client_with_generator: TestClient) -> None:
        """测试默认模式（不指定 mode）"""
        resp = client_with_generator.post(
            "/api/report/generate",
            json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


# ── GET /api/report/list 测试 ─────────────────────────────


class TestListReports:
    """列出报告端点"""

    def test_list_reports_success(self, client_with_generator: TestClient) -> None:
        """测试成功列出报告"""
        resp = client_with_generator.get("/api/report/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["total"] == 3
        assert len(data["reports"]) == 3
        for report in data["reports"]:
            assert "file_name" in report
            assert "path" in report
            assert "size_bytes" in report
            assert "modified_at" in report
            assert "format" in report

    def test_list_reports_with_limit(self, client_with_generator: TestClient) -> None:
        """测试带限制参数的列表"""
        resp = client_with_generator.get("/api/report/list?limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3

    def test_list_reports_empty(self, client_with_generator: TestClient, mock_generator: MagicMock) -> None:
        """测试空报告列表"""
        mock_generator.list_reports = AsyncMock(return_value=[])

        resp = client_with_generator.get("/api/report/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["total"] == 0
        assert data["reports"] == []

    def test_list_reports_invalid_limit(self, client_with_generator: TestClient) -> None:
        """测试无效 limit 返回 422"""
        resp = client_with_generator.get("/api/report/list?limit=0")
        assert resp.status_code == 422

        resp = client_with_generator.get("/api/report/list?limit=101")
        assert resp.status_code == 422

    def test_list_reports_exception(self, client_with_generator: TestClient, mock_generator: MagicMock) -> None:
        """测试列表异常返回 500"""
        mock_generator.list_reports = AsyncMock(side_effect=Exception("存储不可用"))

        resp = client_with_generator.get("/api/report/list")
        assert resp.status_code == 500
        assert "获取报告列表失败" in resp.json()["detail"]


# ── GET /api/report/{task_id} 测试 ────────────────────────


class TestGetReport:
    """获取报告详情端点"""

    def test_get_report_success(self, client_with_generator: TestClient) -> None:
        """测试成功获取报告详情"""
        resp = client_with_generator.get("/api/report/EVO-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "report" in data
        assert data["report"]["task_id"] == "EVO-001"
        assert "summary" in data["report"]
        assert "total_files_changed" in data["report"]
        assert "net_lines" in data["report"]
        assert "highest_risk" in data["report"]

    def test_get_report_not_found(self, client_with_generator: TestClient, mock_generator: MagicMock) -> None:
        """测试获取不存在的报告"""
        mock_generator.get_report = AsyncMock(return_value=None)

        resp = client_with_generator.get("/api/report/EVO-NOTFOUND")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["report"] is None
        assert "未找到报告" in data["error"]

    def test_get_report_exception(self, client_with_generator: TestClient, mock_generator: MagicMock) -> None:
        """测试获取报告异常返回 500"""
        mock_generator.get_report = AsyncMock(side_effect=Exception("读取失败"))

        resp = client_with_generator.get("/api/report/EVO-ERR")
        assert resp.status_code == 500
        assert "获取报告失败" in resp.json()["detail"]

    def test_get_report_with_special_chars(self, client_with_generator: TestClient) -> None:
        """测试包含特殊字符的 task_id"""
        resp = client_with_generator.get("/api/report/EVO-20250101000000-abc12345")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_get_report_fields(self, client_with_generator: TestClient) -> None:
        """测试报告详情包含所有必要字段"""
        resp = client_with_generator.get("/api/report/EVO-001")
        assert resp.status_code == 200
        data = resp.json()
        report = data["report"]
        expected_fields = [
            "task_id", "summary", "total_files_changed", "net_lines",
            "highest_risk", "changes", "test_results", "risk_analysis",
            "rollback_plan", "lessons_learned", "success", "metrics",
        ]
        for field in expected_fields:
            assert field in report, f"缺少字段 {field}"