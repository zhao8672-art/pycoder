"""
幻觉守卫 API 路由单元测试 — 覆盖 guard_api.py 所有端点

测试范围:
  - POST /api/guard/validate   — 验证 LLM 响应
  - POST /api/guard/trace      — 溯源声明
  - POST /api/guard/fact-check — 事实核查
  - GET  /api/guard/stats      — 获取统计
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pycoder.server.services.hallucination_guard import (
    HallucinationGuard,
    ValidationResult,
    reset_guard,
)


# ── 辅助函数 ──────────────────────────────────────────────


def _make_validation_result(
    score: float = 85.0,
    is_trustworthy: bool = True,
) -> dict[str, object]:
    """创建模拟的验证结果字典"""
    return {
        "overall_score": score,
        "trace_result": {
            "total_claims": 5,
            "claims": {
                "files": [{"text": "src/main.py", "confidence": "high"}],
                "apis": [],
                "dependencies": [],
                "code": [],
                "stats": [],
                "config": [],
            },
        },
        "verify_result": {
            "total_verified": 5,
            "verified": 3,
            "failed": 1,
            "uncertain": 1,
            "pass_rate": 0.6,
            "items": [],
        },
        "consistency_issues": [],
        "recommendations": [],
        "is_trustworthy": is_trustworthy,
        "duration_ms": 150.0,
    }


def _make_trace_result() -> dict[str, object]:
    """创建模拟的溯源结果"""
    return {
        "total_claims": 3,
        "claims": {
            "files": [
                {"text": "tests/test_app.py", "confidence": "high"},
                {"text": "pycoder/server/app.py", "confidence": "high"},
            ],
            "apis": [],
            "dependencies": [],
            "code": [{"text": "def test_example(): ...", "confidence": "medium"}],
            "stats": [],
            "config": [],
        },
    }


def _make_fact_check_result() -> dict[str, object]:
    """创建模拟的事实核查结果"""
    return {
        "total_verified": 2,
        "verified": 1,
        "failed": 0,
        "uncertain": 1,
        "pass_rate": 0.5,
        "items": [
            {
                "claim": {"text": "文件存在", "claim_type": "file"},
                "status": "verified",
                "evidence": "文件已找到",
            },
            {
                "claim": {"text": "模块可导入", "claim_type": "import"},
                "status": "uncertain",
                "evidence": "无法确认",
            },
        ],
    }


def _make_stats_result() -> dict[str, object]:
    """创建模拟的统计信息"""
    return {
        "total_validations": 42,
        "total_claims_checked": 210,
        "total_hallucinations_detected": 15,
        "average_score": 87.5,
        "top_hallucination_categories": [
            ("fake_api", 8),
            ("fake_import", 5),
            ("unsafe_code", 2),
        ],
        "last_validation_time": 1700000000.0,
    }


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def mock_guard() -> MagicMock:
    """创建模拟的 HallucinationGuard"""
    guard = MagicMock(spec=HallucinationGuard)

    # validate 返回的是 ValidationResult 对象，有 to_dict() 方法
    _validate_result = MagicMock()
    _validate_result.to_dict.return_value = _make_validation_result()
    guard.validate = AsyncMock(return_value=_validate_result)

    guard.trace_sources = AsyncMock(return_value=_make_trace_result())
    guard.fact_check = AsyncMock(return_value=_make_fact_check_result())
    guard.get_stats = AsyncMock(return_value=_make_stats_result())
    return guard


@pytest.fixture
def client_with_guard(mock_guard: MagicMock) -> TestClient:
    """注入模拟 HallucinationGuard 的 TestClient"""
    from pycoder.server.routers import guard_api

    # 替换 get_hallucination_guard 单例
    with patch(
        "pycoder.server.routers.guard_api.get_hallucination_guard",
        return_value=mock_guard,
    ):
        from pycoder.server.app import app

        with TestClient(app) as c:
            yield c


# ── POST /api/guard/validate 测试 ─────────────────────────


class TestValidateResponse:
    """验证 LLM 响应端点"""

    def test_validate_success(self, client_with_guard: TestClient) -> None:
        """测试成功验证 LLM 响应"""
        resp = client_with_guard.post(
            "/api/guard/validate",
            json={
                "response": "根据 src/main.py 的分析，该模块包含 3 个函数",
                "context": {"agent": "developer", "task": "代码分析"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "overall_score" in data
        assert data["overall_score"] == 85.0
        assert data["is_trustworthy"] is True
        assert "trace_result" in data
        assert "verify_result" in data
        assert "consistency_issues" in data
        assert "recommendations" in data

    def test_validate_without_context(self, client_with_guard: TestClient) -> None:
        """测试不提供上下文验证"""
        resp = client_with_guard.post(
            "/api/guard/validate",
            json={"response": "这是一个简单的响应"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "overall_score" in data

    def test_validate_empty_response(self, client_with_guard: TestClient) -> None:
        """测试空响应返回 422"""
        resp = client_with_guard.post(
            "/api/guard/validate",
            json={"response": ""},
        )
        assert resp.status_code == 422

    def test_validate_low_score(self, client_with_guard: TestClient, mock_guard: MagicMock) -> None:
        """测试低评分结果"""
        _low_result = MagicMock()
        _low_result.to_dict.return_value = _make_validation_result(score=30.0, is_trustworthy=False)
        mock_guard.validate = AsyncMock(return_value=_low_result)

        resp = client_with_guard.post(
            "/api/guard/validate",
            json={"response": "这个函数调用了一个不存在的 API"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_score"] == 30.0
        assert data["is_trustworthy"] is False

    def test_validate_with_consistency_issues(
        self, client_with_guard: TestClient, mock_guard: MagicMock
    ) -> None:
        """测试包含一致性问题的验证结果"""
        result = _make_validation_result(score=60.0)
        result["consistency_issues"] = [
            "变量命名不一致: 'user_id' vs 'userId'",
            "类型注解缺失",
        ]
        _consistency_mock = MagicMock()
        _consistency_mock.to_dict.return_value = result
        mock_guard.validate = AsyncMock(return_value=_consistency_mock)

        resp = client_with_guard.post(
            "/api/guard/validate",
            json={"response": "def get_user(user_id): return user_id"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["consistency_issues"]) == 2

    def test_validate_guard_exception(self, client_with_guard: TestClient, mock_guard: MagicMock) -> None:
        """测试守卫异常返回 500"""
        mock_guard.validate = AsyncMock(side_effect=Exception("内部错误"))

        resp = client_with_guard.post(
            "/api/guard/validate",
            json={"response": "任意响应"},
        )
        assert resp.status_code == 500
        assert "验证异常" in resp.json()["detail"]

    def test_validate_with_recommendations(self, client_with_guard: TestClient, mock_guard: MagicMock) -> None:
        """测试包含建议的验证结果"""
        result = _make_validation_result(score=70.0)
        result["recommendations"] = [
            "建议添加类型注解",
            "建议使用 pathlib 替代 os.path",
        ]
        _rec_mock = MagicMock()
        _rec_mock.to_dict.return_value = result
        mock_guard.validate = AsyncMock(return_value=_rec_mock)

        resp = client_with_guard.post(
            "/api/guard/validate",
            json={"response": "import os; os.path.join('a', 'b')"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["recommendations"]) == 2


# ── POST /api/guard/trace 测试 ────────────────────────────


class TestTraceSources:
    """溯源端点"""

    def test_trace_success(self, client_with_guard: TestClient) -> None:
        """测试成功溯源"""
        resp = client_with_guard.post(
            "/api/guard/trace",
            json={
                "response": "在 test_app.py 中定义了 def test_example() 测试函数"
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_claims" in data
        assert data["total_claims"] == 3
        assert "claims" in data
        assert "files" in data["claims"]
        assert "code" in data["claims"]

    def test_trace_empty_response(self, client_with_guard: TestClient) -> None:
        """测试空响应返回 422"""
        resp = client_with_guard.post(
            "/api/guard/trace",
            json={"response": ""},
        )
        assert resp.status_code == 422

    def test_trace_no_claims(self, client_with_guard: TestClient, mock_guard: MagicMock) -> None:
        """测试无声明可溯源"""
        empty_trace = {
            "total_claims": 0,
            "claims": {
                "files": [], "apis": [], "dependencies": [],
                "code": [], "stats": [], "config": [],
            },
        }
        mock_guard.trace_sources = AsyncMock(return_value=empty_trace)

        resp = client_with_guard.post(
            "/api/guard/trace",
            json={"response": "这是一个纯文本回复，没有任何可追溯的声明"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_claims"] == 0

    def test_trace_guard_exception(self, client_with_guard: TestClient, mock_guard: MagicMock) -> None:
        """测试守卫异常返回 500"""
        mock_guard.trace_sources = AsyncMock(side_effect=Exception("溯源失败"))

        resp = client_with_guard.post(
            "/api/guard/trace",
            json={"response": "任意响应"},
        )
        assert resp.status_code == 500
        assert "溯源异常" in resp.json()["detail"]


# ── POST /api/guard/fact-check 测试 ───────────────────────


class TestFactCheck:
    """事实核查端点"""

    def test_fact_check_success(self, client_with_guard: TestClient) -> None:
        """测试成功事实核查"""
        resp = client_with_guard.post(
            "/api/guard/fact-check",
            json={
                "claims": [
                    {
                        "text": "文件 tests/test_app.py 存在",
                        "claim_type": "file",
                        "source": "LLM 响应",
                        "confidence": "high",
                    },
                    {
                        "text": "模块 pycoder.server.app 可导入",
                        "claim_type": "import",
                        "source": "LLM 响应",
                        "confidence": "medium",
                    },
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_verified" in data
        assert "verified" in data
        assert "failed" in data
        assert "uncertain" in data
        assert "pass_rate" in data
        assert "items" in data

    def test_fact_check_single_claim(self, client_with_guard: TestClient) -> None:
        """测试单条声明核查"""
        resp = client_with_guard.post(
            "/api/guard/fact-check",
            json={
                "claims": [
                    {"text": "存在一个名为 main 的函数", "claim_type": "fact"}
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_verified"] == 2

    def test_fact_check_empty_claims(self, client_with_guard: TestClient) -> None:
        """测试空声明列表返回 422"""
        resp = client_with_guard.post(
            "/api/guard/fact-check",
            json={"claims": []},
        )
        assert resp.status_code == 422

    def test_fact_check_all_verified(self, client_with_guard: TestClient, mock_guard: MagicMock) -> None:
        """测试所有声明都通过验证"""
        all_verified = {
            "total_verified": 3,
            "verified": 3,
            "failed": 0,
            "uncertain": 0,
            "pass_rate": 1.0,
            "items": [
                {"claim": {"text": "claim 1"}, "status": "verified"},
                {"claim": {"text": "claim 2"}, "status": "verified"},
                {"claim": {"text": "claim 3"}, "status": "verified"},
            ],
        }
        mock_guard.fact_check = AsyncMock(return_value=all_verified)

        resp = client_with_guard.post(
            "/api/guard/fact-check",
            json={
                "claims": [
                    {"text": "claim 1"}, {"text": "claim 2"}, {"text": "claim 3"}
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["pass_rate"] == 1.0
        assert data["failed"] == 0

    def test_fact_check_guard_exception(self, client_with_guard: TestClient, mock_guard: MagicMock) -> None:
        """测试守卫异常返回 500"""
        mock_guard.fact_check = AsyncMock(side_effect=Exception("核查失败"))

        resp = client_with_guard.post(
            "/api/guard/fact-check",
            json={"claims": [{"text": "test claim"}]},
        )
        assert resp.status_code == 500
        assert "事实核查异常" in resp.json()["detail"]


# ── GET /api/guard/stats 测试 ─────────────────────────────


class TestGuardStats:
    """统计信息端点"""

    def test_get_stats_success(self, client_with_guard: TestClient) -> None:
        """测试获取统计信息"""
        resp = client_with_guard.get("/api/guard/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_validations"] == 42
        assert data["total_claims_checked"] == 210
        assert data["total_hallucinations_detected"] == 15
        assert data["average_score"] == 87.5
        assert "top_hallucination_categories" in data
        assert "last_validation_time" in data

    def test_get_stats_zero_validations(self, client_with_guard: TestClient, mock_guard: MagicMock) -> None:
        """测试零验证统计"""
        zero_stats = {
            "total_validations": 0,
            "total_claims_checked": 0,
            "total_hallucinations_detected": 0,
            "average_score": 0.0,
            "top_hallucination_categories": [],
            "last_validation_time": None,
        }
        mock_guard.get_stats = AsyncMock(return_value=zero_stats)

        resp = client_with_guard.get("/api/guard/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_validations"] == 0
        assert data["total_hallucinations_detected"] == 0

    def test_get_stats_guard_exception(self, client_with_guard: TestClient, mock_guard: MagicMock) -> None:
        """测试守卫异常返回 500"""
        mock_guard.get_stats = AsyncMock(side_effect=Exception("统计获取失败"))

        resp = client_with_guard.get("/api/guard/stats")
        assert resp.status_code == 500
        assert "获取统计异常" in resp.json()["detail"]