"""
幻觉守卫模块单元测试 — 覆盖 HallucinationGuard.scan_text 各项检测能力

测试范围:
  - 守卫实例创建
  - 干净文本扫描（无幻觉）
  - 不存在的 API 检测
  - 虚假模块导入检测
  - 不安全代码模式检测
  - 硬编码凭据检测
  - 空文本扫描
  - 统计信息获取
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pycoder.server.services.hallucination_guard import (
    GuardResult,
    HallucinationGuard,
    ProjectContext,
    reset_guard,
)


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def guard(tmp_path: Path) -> HallucinationGuard:
    """创建使用临时目录的 HallucinationGuard 实例"""
    reset_guard()
    return HallucinationGuard(workspace=tmp_path)


@pytest.fixture
def project_ctx(tmp_path: Path) -> ProjectContext:
    """创建项目上下文"""
    return ProjectContext(
        workspace=tmp_path,
        language="python",
        framework="fastapi",
    )


# ── 实例创建测试 ──────────────────────────────────────────


class TestCreateGuard:
    """守卫实例创建"""

    def test_create_guard(self, tmp_path: Path) -> None:
        """创建守卫实例"""
        guard = HallucinationGuard(workspace=tmp_path)
        assert guard is not None
        assert guard._workspace == tmp_path

    def test_create_guard_default_workspace(self) -> None:
        """使用默认工作区创建守卫"""
        guard = HallucinationGuard()
        assert guard is not None
        assert guard._workspace is not None


# ── 扫描测试 ──────────────────────────────────────────────


class TestScanText:
    """scan_text 方法各项检测"""

    def test_scan_text_no_hallucination(self, guard: HallucinationGuard) -> None:
        """干净文本扫描返回无问题"""
        clean_text = (
            "def hello_world():\n"
            '    """打印问候语"""\n'
            '    print("Hello, World!")\n'
            "\n"
            "def add(a: int, b: int) -> int:\n"
            "    return a + b\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    hello_world()\n"
        )
        result = guard.scan_text(clean_text)
        assert isinstance(result, GuardResult)
        assert result.has_hallucination is False
        assert result.score == 100.0
        assert len(result.issues) == 0

    def test_scan_text_detect_nonexistent_api(self, guard: HallucinationGuard) -> None:
        """检测不存在的 API 调用"""
        fake_text = (
            "from some_lib import helper\n\n"
            "def process():\n"
            "    result = nonexistent_api('data')\n"
            "    return result\n"
        )
        result = guard.scan_text(fake_text)
        assert result.has_hallucination is True
        assert result.score < 100.0
        assert len(result.issues) >= 1
        # 验证检测到 nonexistent_api 类型
        api_issues = [i for i in result.issues if i["type"] == "nonexistent_api"]
        assert len(api_issues) >= 1
        assert "nonexistent_api" in api_issues[0]["text"]

    def test_scan_text_detect_fake_module(self, guard: HallucinationGuard) -> None:
        """检测不存在的模块导入"""
        fake_text = (
            "import nonexistent_quantum_engine\n\n"
            "def compute():\n"
            "    return nonexistent_quantum_engine.run()\n"
        )
        result = guard.scan_text(fake_text)
        assert result.has_hallucination is True
        assert result.score < 100.0
        assert len(result.issues) >= 1
        module_issues = [i for i in result.issues if i["type"] == "nonexistent_module"]
        assert len(module_issues) >= 1
        assert "nonexistent_quantum_engine" in module_issues[0]["text"]

    def test_scan_text_detect_unsafe_code(self, guard: HallucinationGuard) -> None:
        """检测不安全代码模式"""
        unsafe_text = (
            "def execute_dynamic(user_input: str) -> None:\n"
            "    eval(user_input)\n"
            "    exec('print(42)')\n"
        )
        result = guard.scan_text(unsafe_text)
        assert result.has_hallucination is True
        assert result.score < 100.0
        assert len(result.issues) >= 1
        unsafe_issues = [i for i in result.issues if i["type"] == "unsafe_code"]
        assert len(unsafe_issues) >= 1

    def test_scan_text_detect_hardcoded_secret(self, guard: HallucinationGuard) -> None:
        """检测硬编码凭据"""
        secret_text = (
            "import os\n\n"
            'API_KEY = "sk-abc123def456ghi789"\n'
            'PASSWORD = "super_secret_123"\n'
            'SECRET_KEY = "my-secret-key"\n'
        )
        result = guard.scan_text(secret_text)
        assert result.has_hallucination is True
        assert result.score < 100.0
        assert len(result.issues) >= 1
        secret_issues = [i for i in result.issues if i["type"] == "hardcoded_secret"]
        assert len(secret_issues) >= 1

    def test_scan_text_empty(self, guard: HallucinationGuard) -> None:
        """空文本扫描"""
        result = guard.scan_text("")
        assert isinstance(result, GuardResult)
        assert result.has_hallucination is False
        assert result.score == 100.0
        assert len(result.issues) == 0

    def test_scan_text_whitespace_only(self, guard: HallucinationGuard) -> None:
        """仅空白文本扫描"""
        result = guard.scan_text("   \n  \t  \n  ")
        assert isinstance(result, GuardResult)
        assert result.has_hallucination is False
        assert result.score == 100.0
        assert len(result.issues) == 0

    def test_scan_text_multiple_issues(self, guard: HallucinationGuard) -> None:
        """同时检测多种问题"""
        multi_text = (
            "import nonexistent_lib\n"
            "from fake_module import helper\n\n"
            'PASSWORD = "admin123"\n\n'
            "def run():\n"
            "    eval('1 + 1')\n"
            "    nonexistent_api('test')\n"
        )
        result = guard.scan_text(multi_text)
        assert result.has_hallucination is True
        assert result.score < 60.0
        # 应检测到多种类型
        issue_types = {i["type"] for i in result.issues}
        assert len(issue_types) >= 3

    def test_scan_text_with_context(
        self, guard: HallucinationGuard, project_ctx: ProjectContext
    ) -> None:
        """带项目上下文扫描"""
        fake_text = "import nonexistent_module_xyz\n"
        result = guard.scan_text(fake_text, context=project_ctx)
        assert result.has_hallucination is True
        assert len(result.issues) >= 1


# ── 统计测试 ──────────────────────────────────────────────


class TestGetStats:
    """get_stats 方法"""

    @pytest.mark.asyncio
    async def test_get_stats_initial(self, guard: HallucinationGuard) -> None:
        """初始统计信息"""
        stats = await guard.get_stats()
        assert isinstance(stats, dict)
        assert "total_validations" in stats
        assert stats["total_validations"] == 0

    @pytest.mark.asyncio
    async def test_get_stats_after_validation(self, guard: HallucinationGuard) -> None:
        """验证后的统计信息"""
        clean_text = "def foo():\n    return 42\n"
        await guard.validate(clean_text)
        stats = await guard.get_stats()
        assert stats["total_validations"] >= 1
        assert "average_score" in stats


# ── 综合验证测试 ──────────────────────────────────────────


class TestValidate:
    """validate 三步验证管线"""

    @pytest.mark.asyncio
    async def test_validate_clean_response(self, guard: HallucinationGuard) -> None:
        """验证干净响应"""
        clean_response = (
            "在 pycoder/server/services/ 目录下创建新文件 example.py，"
            "其中定义 ExampleService 类和 get_example 函数。"
            "使用 FastAPI 框架，遵循 PEP 8 规范。"
        )
        result = await guard.validate(clean_response)
        assert result.overall_score >= 0.0
        assert result.overall_score <= 100.0

    @pytest.mark.asyncio
    async def test_validate_returns_recommendations(self, guard: HallucinationGuard) -> None:
        """验证返回建议列表"""
        response = "这是一段普通文本，没有明显的代码声明。"
        result = await guard.validate(response)
        assert isinstance(result.recommendations, list)
        assert result.to_dict() is not None


# ── 数据模型测试 ──────────────────────────────────────────


class TestDataModels:
    """数据模型序列化"""

    def test_guard_result_to_dict(self) -> None:
        """GuardResult 序列化"""
        result = GuardResult(
            issues=[{"type": "test", "message": "test issue"}],
            has_hallucination=True,
            score=75.0,
            text="test text",
        )
        d = result.to_dict()
        assert d["has_hallucination"] is True
        assert d["score"] == 75.0
        assert len(d["issues"]) == 1

    def test_project_context_defaults(self) -> None:
        """ProjectContext 默认值"""
        ctx = ProjectContext()
        assert ctx.language == "python"
        assert ctx.framework == ""
        assert ctx.dependencies == []