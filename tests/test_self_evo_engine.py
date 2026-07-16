"""SelfEvolutionEngine 单元测试 — 扫描、修复、进化管线、令牌系统

覆盖 pycoder.capabilities.self_evo.engine 的:
- 数据模型: CodeIssue, ScanReport, FixProposal, FixResult, EvolutionRecord, EvolutionTask, EvolutionStats
- SelfEvolutionEngine: scan, generate_fix, apply_fix, hot_reload, record_evolution, evolve
- 静态方法: generate_evolution_token, _validate_evolution_token, clear_evolution_token
- 内部方法: _scan_file_ast, _parse_fix_response, _template_fix, _is_protected, _path_to_module
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.capabilities.self_evo.engine import (
    CodeIssue,
    EvolutionRecord,
    EvolutionStats,
    EvolutionTask,
    FixProposal,
    FixResult,
    ScanReport,
    SelfEvolutionEngine,
    _build_evolution_report,
)


# ══════════════════════════════════════════════════════════
# 数据模型测试
# ══════════════════════════════════════════════════════════


class TestCodeIssue:
    """CodeIssue 数据类测试"""

    def test_default_values(self):
        """默认值测试"""
        issue = CodeIssue(
            file="test.py",
            line=10,
            severity="high",
            issue_type="bug",
            title="裸 except",
        )
        assert issue.file == "test.py"
        assert issue.line == 10
        assert issue.description == ""
        assert issue.suggestion == ""
        assert issue.code_snippet == ""

    def test_full_fields(self):
        """完整字段测试"""
        issue = CodeIssue(
            file="app.py",
            line=42,
            severity="critical",
            issue_type="security",
            title="硬编码密钥",
            description="发现硬编码的 API Key",
            suggestion="使用环境变量",
            code_snippet="API_KEY = 'sk-xxx'",
        )
        assert issue.description == "发现硬编码的 API Key"
        assert issue.suggestion == "使用环境变量"
        assert issue.code_snippet == "API_KEY = 'sk-xxx'"


class TestScanReport:
    """ScanReport 数据类测试"""

    def test_default_fields(self):
        """默认字段测试"""
        report = ScanReport(path="pycoder", files_scanned=10, total_issues=5)
        assert report.path == "pycoder"
        assert report.files_scanned == 10
        assert report.total_issues == 5
        assert report.issues == []
        assert report.summary == ""
        assert report.duration_seconds == 0.0

    def test_with_issues(self):
        """带问题列表测试"""
        issue = CodeIssue(
            file="a.py", line=1, severity="low", issue_type="style", title="过长函数"
        )
        report = ScanReport(
            path="pycoder",
            files_scanned=5,
            total_issues=1,
            issues=[issue],
            summary="发现 1 个问题",
            duration_seconds=2.5,
        )
        assert len(report.issues) == 1
        assert report.issues[0].title == "过长函数"
        assert report.summary == "发现 1 个问题"
        assert report.duration_seconds == 2.5


class TestFixProposal:
    """FixProposal 数据类测试"""

    def test_default_values(self):
        """默认值测试"""
        issue = CodeIssue(
            file="x.py", line=1, severity="medium", issue_type="bug", title="可变默认参数"
        )
        proposal = FixProposal(issue=issue, action="replace", file_path="x.py")
        assert proposal.action == "replace"
        assert proposal.old_code == ""
        assert proposal.new_code == ""
        assert proposal.risk_level == "low"

    def test_with_code(self):
        """带代码内容测试"""
        issue = CodeIssue(
            file="x.py", line=1, severity="high", issue_type="bug", title="裸 except"
        )
        proposal = FixProposal(
            issue=issue,
            action="replace",
            file_path="x.py",
            old_code="except:",
            new_code="except Exception as e:",
            reasoning="模板修复",
            risk_level="low",
        )
        assert proposal.old_code == "except:"
        assert proposal.new_code == "except Exception as e:"
        assert proposal.reasoning == "模板修复"


class TestFixResult:
    """FixResult 数据类测试"""

    def test_success_result(self):
        """成功结果测试"""
        issue = CodeIssue(
            file="x.py", line=1, severity="high", issue_type="bug", title="测试问题"
        )
        proposal = FixProposal(issue=issue, action="replace", file_path="x.py")
        result = FixResult(
            proposal=proposal,
            success=True,
            test_passed=True,
            git_branch="self_evo/123",
            git_commit="abc123",
        )
        assert result.success is True
        assert result.test_passed is True
        assert result.git_branch == "self_evo/123"
        assert result.error is None
        assert result.rollback_needed is False

    def test_failure_result(self):
        """失败结果测试"""
        issue = CodeIssue(
            file="x.py", line=1, severity="high", issue_type="bug", title="测试问题"
        )
        proposal = FixProposal(issue=issue, action="replace", file_path="x.py")
        result = FixResult(
            proposal=proposal,
            success=False,
            error="文件受保护",
            rollback_needed=True,
        )
        assert result.success is False
        assert result.error == "文件受保护"
        assert result.rollback_needed is True


class TestEvolutionRecord:
    """EvolutionRecord 数据类测试"""

    def test_default_values(self):
        """默认值测试"""
        record = EvolutionRecord()
        assert record.action == ""
        assert record.success is False
        assert record.fix_description == ""

    def test_full_record(self):
        """完整记录测试"""
        record = EvolutionRecord(
            action="fix",
            issue_type="bug",
            file="app.py",
            success=True,
            fix_description="修复了裸 except",
            test_result="3 passed",
            lessons="不要使用裸 except",
        )
        assert record.action == "fix"
        assert record.success is True
        assert record.lessons == "不要使用裸 except"


class TestEvolutionTask:
    """EvolutionTask 数据类测试"""

    def test_default_fields(self):
        """默认字段测试"""
        task = EvolutionTask()
        assert task.type == "fix"
        assert task.status == "pending"
        assert task.target_files == []
        assert task.changes == []

    def test_to_dict(self):
        """to_dict 序列化测试"""
        task = EvolutionTask(
            type="optimize",
            description="优化性能",
            status="done",
            target_files=["a.py"],
        )
        d = task.to_dict()
        assert d["type"] == "optimize"
        assert d["status"] == "done"
        assert d["target_files"] == ["a.py"]


class TestEvolutionStats:
    """EvolutionStats 数据类测试"""

    def test_success_rate_zero_tasks(self):
        """零任务时成功率测试"""
        stats = EvolutionStats()
        assert stats.success_rate == 0.0

    def test_success_rate_calculation(self):
        """成功率计算测试"""
        stats = EvolutionStats(total_tasks=10, successful=7, failed=3)
        assert stats.success_rate == 0.7

    def test_to_dict(self):
        """to_dict 序列化测试"""
        stats = EvolutionStats(total_tasks=5, successful=3, failed=2, bugs_fixed=10)
        d = stats.to_dict()
        assert d["total_tasks"] == 5
        assert d["successful"] == 3
        assert d["bugs_fixed"] == 10
        assert "success_rate" in d


class TestBuildEvolutionReport:
    """_build_evolution_report 函数测试"""

    def test_basic_report(self):
        """基本报告测试"""
        task = EvolutionTask(
            type="fix",
            description="修复 bug",
            status="done",
            target_files=["a.py"],
        )
        task.test_result = "3 passed"
        report = _build_evolution_report(task)
        assert report["task_id"] == task.id
        assert report["task_type"] == "fix"
        assert report["status"] == "done"
        assert report["test_result"] == "3 passed"

    def test_report_with_grade(self):
        """带评分信息报告测试"""
        task = EvolutionTask(type="fix")
        grade = {"task_type": "fix", "score": 85}
        report = _build_evolution_report(task, grade_info=grade)
        assert report["grade"] == grade

    def test_report_with_source_trace(self):
        """带溯源信息报告测试"""
        task = EvolutionTask(type="fix")
        source = {"origin": "web_ui"}
        report = _build_evolution_report(task, source_trace=source)
        assert report["source_trace"] == source

    def test_long_test_result_truncated(self):
        """长测试结果截断测试"""
        task = EvolutionTask(type="fix")
        task.test_result = "x" * 500
        report = _build_evolution_report(task)
        assert len(report["test_result"]) <= 200


# ══════════════════════════════════════════════════════════
# SelfEvolutionEngine 核心测试
# ══════════════════════════════════════════════════════════


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """创建临时项目目录"""
    pycoder = tmp_path / "pycoder"
    pycoder.mkdir()
    (pycoder / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


@pytest.fixture
def engine_no_llm(tmp_project: Path) -> SelfEvolutionEngine:
    """创建不带 LLM 的引擎实例（清空历史记录）"""
    engine = SelfEvolutionEngine(project_root=tmp_project)
    engine._records.clear()  # 清空从全局历史文件加载的记录
    return engine


@pytest.fixture
def mock_llm() -> MagicMock:
    """创建模拟 LLM"""
    llm = MagicMock()
    llm.chat = AsyncMock(return_value="修复方案: 将裸 except 替换为 except Exception as e:")
    return llm


@pytest.fixture
def engine_with_llm(tmp_project: Path, mock_llm: MagicMock) -> SelfEvolutionEngine:
    """创建带 LLM 的引擎实例"""
    return SelfEvolutionEngine(llm_provider=mock_llm, project_root=tmp_project)


class TestEngineInit:
    """引擎初始化测试"""

    def test_basic_init(self, tmp_project: Path):
        """基本初始化测试"""
        engine = SelfEvolutionEngine(project_root=tmp_project)
        assert engine._project_root == tmp_project
        engine._records.clear()  # 清空从全局历史文件加载的记录
        assert engine._records == []
        assert engine._tasks == []

    def test_init_with_llm(self, tmp_project: Path, mock_llm: MagicMock):
        """带 LLM 初始化测试"""
        engine = SelfEvolutionEngine(llm_provider=mock_llm, project_root=tmp_project)
        assert engine.llm is mock_llm

    def test_init_with_path_as_first_arg(self, tmp_project: Path):
        """Path 作为第一个参数向后兼容测试"""
        engine = SelfEvolutionEngine(tmp_project)
        assert engine._project_root == tmp_project
        assert engine.v2 is None


class TestIsProtected:
    """_is_protected 方法测试"""

    def test_env_file_protected(self, engine_no_llm: SelfEvolutionEngine):
        """.env 文件受保护"""
        assert engine_no_llm._is_protected(".env") is True
        assert engine_no_llm._is_protected("config/.env") is True

    def test_db_file_protected(self, engine_no_llm: SelfEvolutionEngine):
        """数据库文件受保护"""
        assert engine_no_llm._is_protected("pycoder.db") is True

    def test_normal_py_file_not_protected(self, engine_no_llm: SelfEvolutionEngine):
        """普通 py 文件不受保护"""
        assert engine_no_llm._is_protected("pycoder/server/app.py") is False

    def test_pycache_protected(self, engine_no_llm: SelfEvolutionEngine):
        """__pycache__ 受保护"""
        assert engine_no_llm._is_protected("__pycache__/module.pyc") is True

    def test_git_protected(self, engine_no_llm: SelfEvolutionEngine):
        """.git 目录受保护"""
        assert engine_no_llm._is_protected(".git/config") is True


class TestPathToModule:
    """_path_to_module 方法测试"""

    def test_pycoder_module_path(self, engine_no_llm: SelfEvolutionEngine):
        """pycoder 模块路径转换"""
        result = engine_no_llm._path_to_module("pycoder/server/app.py")
        assert result == "pycoder.server.app"

    def test_init_module_path(self, engine_no_llm: SelfEvolutionEngine):
        """__init__ 模块路径转换"""
        result = engine_no_llm._path_to_module("pycoder/__init__.py")
        assert result == "pycoder"

    def test_no_pycoder_prefix(self, engine_no_llm: SelfEvolutionEngine):
        """无 pycoder 前缀路径转换"""
        result = engine_no_llm._path_to_module("some/other/module.py")
        assert result == "module"


class TestScanFileAst:
    """_scan_file_ast 静态分析测试"""

    @pytest.fixture
    def py_file(self, tmp_project: Path) -> Path:
        """创建测试用 Python 文件"""
        f = tmp_project / "pycoder" / "test_module.py"
        return f

    def test_detect_bare_except(self, engine_no_llm: SelfEvolutionEngine, py_file: Path):
        """检测裸 except"""
        import ast
        source = "try:\n    pass\nexcept:\n    pass\n"
        tree = ast.parse(source)
        issues = engine_no_llm._scan_file_ast(tree, py_file, source)
        assert any("裸 except" in i.title for i in issues)

    def test_detect_mutable_default(self, engine_no_llm: SelfEvolutionEngine, py_file: Path):
        """检测可变默认参数"""
        import ast
        source = "def foo(x=[]):\n    pass\n"
        tree = ast.parse(source)
        issues = engine_no_llm._scan_file_ast(tree, py_file, source)
        assert any("可变默认参数" in i.title for i in issues)

    def test_detect_eval(self, engine_no_llm: SelfEvolutionEngine, py_file: Path):
        """检测 eval 危险函数"""
        import ast
        source = "eval('1+1')\n"
        tree = ast.parse(source)
        issues = engine_no_llm._scan_file_ast(tree, py_file, source)
        assert any("eval" in i.title for i in issues)

    def test_detect_hardcoded_key(self, engine_no_llm: SelfEvolutionEngine, py_file: Path):
        """检测硬编码密钥"""
        import ast
        source = 'api_key = "sk-123456789abcdef"\n'
        tree = ast.parse(source)
        issues = engine_no_llm._scan_file_ast(tree, py_file, source)
        assert any("硬编码密钥" in i.title for i in issues)

    def test_clean_code_no_issues(self, engine_no_llm: SelfEvolutionEngine, py_file: Path):
        """干净代码无问题"""
        import ast
        source = "def foo(x: int) -> int:\n    return x + 1\n"
        tree = ast.parse(source)
        issues = engine_no_llm._scan_file_ast(tree, py_file, source)
        assert len(issues) == 0


class TestIsSkippable:
    """_is_skippable 方法测试"""

    def test_skips_pycache(self, engine_no_llm: SelfEvolutionEngine):
        """跳过 __pycache__"""
        assert engine_no_llm._is_skippable(Path("__pycache__/module.pyc")) is True

    def test_skips_git(self, engine_no_llm: SelfEvolutionEngine):
        """跳过 .git"""
        assert engine_no_llm._is_skippable(Path(".git/objects/abc")) is True

    def test_skips_node_modules(self, engine_no_llm: SelfEvolutionEngine):
        """跳过 node_modules"""
        assert engine_no_llm._is_skippable(Path("node_modules/pkg/index.js")) is True

    def test_does_not_skip_normal_py(self, engine_no_llm: SelfEvolutionEngine):
        """不跳过普通 py 文件"""
        assert engine_no_llm._is_skippable(Path("pycoder/server/app.py")) is False


class TestScan:
    """scan 方法测试"""

    @pytest.mark.asyncio
    async def test_scan_basic(self, engine_no_llm: SelfEvolutionEngine):
        """基本扫描测试"""
        # 创建测试文件
        test_file = engine_no_llm._project_root / "pycoder" / "test.py"
        test_file.write_text("x = 1\ny = 2\n", encoding="utf-8")

        report = await engine_no_llm.scan(str(engine_no_llm._project_root / "pycoder"), use_llm=False)
        assert isinstance(report, ScanReport)
        assert report.files_scanned >= 1
        assert report.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_scan_with_syntax_error(self, engine_no_llm: SelfEvolutionEngine):
        """扫描包含语法错误的文件"""
        test_file = engine_no_llm._project_root / "pycoder" / "bad.py"
        test_file.write_text("def broken(\n", encoding="utf-8")

        report = await engine_no_llm.scan(str(engine_no_llm._project_root / "pycoder"), use_llm=False)
        assert any("语法错误" in i.title for i in report.issues)

    @pytest.mark.asyncio
    async def test_scan_saves_last_issues(self, engine_no_llm: SelfEvolutionEngine):
        """扫描后保存 _last_issues"""
        test_file = engine_no_llm._project_root / "pycoder" / "test.py"
        test_file.write_text("def foo(x=[]):\n    pass\n", encoding="utf-8")

        await engine_no_llm.scan(str(engine_no_llm._project_root / "pycoder"), use_llm=False)
        assert len(engine_no_llm._last_issues) > 0

    @pytest.mark.asyncio
    async def test_scan_with_llm(self, engine_with_llm: SelfEvolutionEngine):
        """带 LLM 扫描测试"""
        test_file = engine_with_llm._project_root / "pycoder" / "test.py"
        test_file.write_text("eval('1+1')\n", encoding="utf-8")

        report = await engine_with_llm.scan(
            str(engine_with_llm._project_root / "pycoder"), use_llm=True
        )
        assert isinstance(report, ScanReport)

    @pytest.mark.asyncio
    async def test_scan_skips_skippable(self, engine_no_llm: SelfEvolutionEngine):
        """扫描跳过不可扫描文件"""
        pycache = engine_no_llm._project_root / "pycoder" / "__pycache__"
        pycache.mkdir()
        (pycache / "cached.py").write_text("x=1\n", encoding="utf-8")

        report = await engine_no_llm.scan(str(engine_no_llm._project_root / "pycoder"), use_llm=False)
        # __pycache__ 中的文件应被跳过
        assert all("__pycache__" not in i.file for i in report.issues)


class TestGenerateFix:
    """generate_fix 方法测试"""

    @pytest.mark.asyncio
    async def test_generate_fix_with_llm(self, engine_with_llm: SelfEvolutionEngine):
        """带 LLM 生成修复测试"""
        issue = CodeIssue(
            file="test.py",
            line=10,
            severity="high",
            issue_type="bug",
            title="裸 except",
            suggestion="替换为 except Exception as e:",
        )
        proposal = await engine_with_llm.generate_fix(issue)
        assert isinstance(proposal, FixProposal)
        assert proposal.file_path == "test.py"

    @pytest.mark.asyncio
    async def test_generate_fix_without_llm_uses_template(self, engine_no_llm: SelfEvolutionEngine):
        """无 LLM 时使用模板修复测试"""
        issue = CodeIssue(
            file="test.py",
            line=10,
            severity="high",
            issue_type="bug",
            title="裸 except 吞掉所有异常",
        )
        proposal = await engine_no_llm.generate_fix(issue)
        assert isinstance(proposal, FixProposal)
        assert proposal.old_code == "except:"
        assert proposal.new_code == "except Exception as e:"

    @pytest.mark.asyncio
    async def test_generate_fix_for_mutable_default(self, engine_no_llm: SelfEvolutionEngine):
        """可变默认参数模板修复测试"""
        issue = CodeIssue(
            file="test.py",
            line=5,
            severity="medium",
            issue_type="bug",
            title="函数 'foo' 使用了可变默认参数",
        )
        proposal = await engine_no_llm.generate_fix(issue)
        assert proposal.action == "refactor"

    @pytest.mark.asyncio
    async def test_generate_fix_generic(self, engine_no_llm: SelfEvolutionEngine):
        """通用模板修复测试"""
        issue = CodeIssue(
            file="test.py",
            line=1,
            severity="low",
            issue_type="style",
            title="函数 'bar' 过长 (300 行)",
            suggestion="将函数拆分为多个小函数",
        )
        proposal = await engine_no_llm.generate_fix(issue)
        assert isinstance(proposal, FixProposal)
        assert proposal.file_path == "test.py"


class TestApplyFix:
    """apply_fix 方法测试"""

    @pytest.mark.asyncio
    async def test_apply_fix_protected_file(self, engine_no_llm: SelfEvolutionEngine):
        """受保护文件拒绝修复测试"""
        issue = CodeIssue(
            file=".env", line=1, severity="high", issue_type="bug", title="测试"
        )
        proposal = FixProposal(issue=issue, action="replace", file_path=".env")
        result = await engine_no_llm.apply_fix(proposal)
        assert result.success is False
        assert "受保护" in result.error

    @pytest.mark.asyncio
    async def test_apply_fix_too_many_modifications(
        self, engine_no_llm: SelfEvolutionEngine, monkeypatch
    ):
        """超过修改数量限制测试"""
        # 模拟已有 3 个修改
        monkeypatch.setattr(
            engine_no_llm, "_get_modified_in_session", lambda: ["a.py", "b.py", "c.py"]
        )
        issue = CodeIssue(
            file="test.py", line=1, severity="high", issue_type="bug", title="测试"
        )
        proposal = FixProposal(issue=issue, action="replace", file_path="test.py")
        result = await engine_no_llm.apply_fix(proposal)
        assert result.success is False
        assert "最多修改 3 个文件" in result.error


class TestParseFixResponse:
    """_parse_fix_response 方法测试"""

    def test_parse_diff_format(self, engine_no_llm: SelfEvolutionEngine):
        """解析 diff 格式测试"""
        issue = CodeIssue(
            file="test.py", line=1, severity="high", issue_type="bug", title="测试"
        )
        response = """```diff
--- a/test.py
+++ b/test.py
-except:
+except Exception as e:
```"""
        proposal = engine_no_llm._parse_fix_response(response, issue)
        assert proposal.action == "replace"
        assert "except:" in proposal.old_code

    def test_parse_python_code_block(self, engine_no_llm: SelfEvolutionEngine):
        """解析 Python 代码块测试"""
        issue = CodeIssue(
            file="test.py", line=1, severity="high", issue_type="bug", title="测试"
        )
        response = """```python
def fixed():
    pass
```"""
        proposal = engine_no_llm._parse_fix_response(response, issue)
        assert "def fixed()" in proposal.new_code

    def test_parse_without_code_block(self, engine_no_llm: SelfEvolutionEngine):
        """无代码块响应测试"""
        issue = CodeIssue(
            file="test.py", line=1, severity="high", issue_type="bug", title="测试"
        )
        response = "需要手动修复此问题"
        proposal = engine_no_llm._parse_fix_response(response, issue)
        assert isinstance(proposal, FixProposal)
        assert proposal.reasoning == response[:500]


class TestRecordEvolution:
    """record_evolution 方法测试"""

    def test_record_single(self, engine_no_llm: SelfEvolutionEngine):
        """记录单条进化测试"""
        record = EvolutionRecord(
            action="fix",
            issue_type="bug",
            file="app.py",
            success=True,
            fix_description="修复裸 except",
        )
        engine_no_llm.record_evolution(record)
        assert len(engine_no_llm._records) == 1

    def test_get_evolution_history(self, engine_no_llm: SelfEvolutionEngine):
        """获取进化历史测试"""
        for i in range(3):
            engine_no_llm.record_evolution(
                EvolutionRecord(
                    action="fix",
                    issue_type="bug",
                    file=f"file{i}.py",
                    success=True,
                )
            )
        history = engine_no_llm.get_evolution_history(limit=10)
        assert len(history) == 3

    def test_record_limit(self, engine_no_llm: SelfEvolutionEngine):
        """记录数量限制测试"""
        # 添加超过 1000 条记录
        for i in range(1100):
            engine_no_llm.record_evolution(
                EvolutionRecord(action="fix", issue_type="bug", file=f"f{i}.py")
            )
        assert len(engine_no_llm._records) <= 1000


class TestGetStats:
    """get_stats 方法测试"""

    def test_empty_stats(self, engine_no_llm: SelfEvolutionEngine):
        """空统计测试"""
        stats = engine_no_llm.get_stats()
        assert stats["total_evolutions"] == 0

    def test_stats_with_records(self, engine_no_llm: SelfEvolutionEngine):
        """有记录统计测试"""
        engine_no_llm.record_evolution(
            EvolutionRecord(
                action="fix", issue_type="bug", file="a.py", success=True
            )
        )
        engine_no_llm.record_evolution(
            EvolutionRecord(
                action="fix", issue_type="security", file="b.py", success=False
            )
        )
        stats = engine_no_llm.get_stats()
        assert stats["total_evolutions"] == 2
        assert "by_type" in stats


class TestGetEvolutionStats:
    """get_evolution_stats 方法测试"""

    def test_combined_stats(self, engine_no_llm: SelfEvolutionEngine):
        """合并统计测试"""
        stats = engine_no_llm.get_evolution_stats()
        assert "total_tasks" in stats
        assert "v2_records" in stats
        assert "v2_success_rate" in stats


class TestListTasks:
    """list_tasks 方法测试"""

    def test_empty_tasks(self, engine_no_llm: SelfEvolutionEngine):
        """空任务列表测试"""
        tasks = engine_no_llm.list_tasks()
        assert tasks == []

    def test_with_tasks(self, engine_no_llm: SelfEvolutionEngine):
        """有任务列表测试"""
        # 手动添加任务到 _tasks
        task = EvolutionTask(type="fix", description="测试任务")
        engine_no_llm._tasks.append(task)
        tasks = engine_no_llm.list_tasks()
        assert len(tasks) == 1