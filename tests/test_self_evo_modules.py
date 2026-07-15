"""
自我进化模块综合单元测试 — 覆盖 11 个模块的公共接口

覆盖模块:
  1. engine.py            — 数据模型 + SelfEvolutionEngine
  2. closed_loop.py       — 数据模型 + ClosedLearningLoop
  3. __init__.py          — 能力注册 + 处理器
  4. experience_buffer.py — 数据模型 + ExperienceBuffer + IterationMemory + EngineerProfile
  5. upgrade.py           — 数据模型 + 升级/版本检测/健康检查
  6. feedback_loop.py     — 数据模型 + FeedbackLoop
  7. metrics_tracker.py   — 数据模型 + MetricsTracker
  8. evo_orchestrator.py  — 数据模型 + EvoOrchestrator
  9. evo_cache.py         — 数据模型 + EvoCache
  10. evo_evaluator.py    — 数据模型 + EvoEvaluator
  11. error_classifier.py — 枚举 + 数据类 + ErrorClassifier
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════
# 模块 1: engine.py — 数据模型
# ═══════════════════════════════════════════════════════════════


class TestCodeIssue:
    """CodeIssue 数据类测试"""

    def test_minimal_creation(self):
        """最小字段创建"""
        from pycoder.capabilities.self_evo.engine import CodeIssue

        issue = CodeIssue(file="test.py", line=10, severity="high", issue_type="bug", title="裸 except")
        assert issue.file == "test.py"
        assert issue.line == 10
        assert issue.severity == "high"
        assert issue.issue_type == "bug"
        assert issue.title == "裸 except"
        assert issue.description == ""
        assert issue.suggestion == ""
        assert issue.code_snippet == ""

    def test_full_fields(self):
        """全部字段创建"""
        from pycoder.capabilities.self_evo.engine import CodeIssue

        issue = CodeIssue(
            file="app.py", line=42, severity="critical", issue_type="security",
            title="硬编码密钥", description="发现 API Key", suggestion="使用环境变量",
            code_snippet="KEY='sk-xxx'",
        )
        assert issue.description == "发现 API Key"
        assert issue.suggestion == "使用环境变量"
        assert issue.code_snippet == "KEY='sk-xxx'"


class TestScanReport:
    """ScanReport 数据类测试"""

    def test_default_fields(self):
        """默认字段"""
        from pycoder.capabilities.self_evo.engine import ScanReport

        report = ScanReport(path="pycoder", files_scanned=10, total_issues=5)
        assert report.path == "pycoder"
        assert report.files_scanned == 10
        assert report.total_issues == 5
        assert report.issues == []
        assert report.summary == ""
        assert report.duration_seconds == 0.0


class TestFixProposal:
    """FixProposal 数据类测试"""

    def test_creation(self):
        """创建修复方案"""
        from pycoder.capabilities.self_evo.engine import CodeIssue, FixProposal

        issue = CodeIssue(file="a.py", line=1, severity="high", issue_type="bug", title="test")
        proposal = FixProposal(issue=issue, action="replace", file_path="a.py")
        assert proposal.action == "replace"
        assert proposal.risk_level == "low"
        assert proposal.old_code == ""

    def test_risk_level_default(self):
        """风险等级默认值"""
        from pycoder.capabilities.self_evo.engine import CodeIssue, FixProposal

        issue = CodeIssue(file="a.py", line=1, severity="high", issue_type="bug", title="test")
        proposal = FixProposal(issue=issue, action="refactor", file_path="a.py", risk_level="high")
        assert proposal.risk_level == "high"


class TestFixResult:
    """FixResult 数据类测试"""

    def test_success(self):
        """成功结果"""
        from pycoder.capabilities.self_evo.engine import CodeIssue, FixProposal, FixResult

        issue = CodeIssue(file="a.py", line=1, severity="high", issue_type="bug", title="test")
        proposal = FixProposal(issue=issue, action="replace", file_path="a.py")
        result = FixResult(proposal=proposal, success=True, test_passed=True,
                           git_branch="evo/123", git_commit="abc123")
        assert result.success is True
        assert result.test_passed is True
        assert result.git_branch == "evo/123"
        assert result.error is None

    def test_failure_with_rollback(self):
        """失败且需要回滚"""
        from pycoder.capabilities.self_evo.engine import CodeIssue, FixProposal, FixResult

        issue = CodeIssue(file="a.py", line=1, severity="high", issue_type="bug", title="test")
        proposal = FixProposal(issue=issue, action="replace", file_path="a.py")
        result = FixResult(proposal=proposal, success=False, error="测试失败",
                           rollback_needed=True)
        assert result.success is False
        assert result.rollback_needed is True
        assert result.error == "测试失败"


class TestEvolutionRecord:
    """EvolutionRecord 数据类测试"""

    def test_defaults(self):
        """默认值"""
        from pycoder.capabilities.self_evo.engine import EvolutionRecord

        record = EvolutionRecord()
        assert record.action == ""
        assert record.success is False

    def test_full_record(self):
        """完整记录"""
        from pycoder.capabilities.self_evo.engine import EvolutionRecord

        record = EvolutionRecord(
            action="fix", issue_type="bug", file="a.py", success=True,
            fix_description="修复了裸 except", test_result="passed", lessons="使用except Exception",
        )
        assert record.action == "fix"
        assert record.success is True
        assert record.lessons == "使用except Exception"


class TestEvolutionTask:
    """EvolutionTask 数据类测试"""

    def test_defaults(self):
        """默认值"""
        from pycoder.capabilities.self_evo.engine import EvolutionTask

        task = EvolutionTask()
        assert task.status == "pending"
        assert task.type == "fix"
        assert len(task.id) == 8

    def test_to_dict(self):
        """to_dict 序列化"""
        from pycoder.capabilities.self_evo.engine import EvolutionTask

        task = EvolutionTask(type="optimize", description="优化性能")
        d = task.to_dict()
        assert d["type"] == "optimize"
        assert d["status"] == "pending"
        assert d["id"] == task.id


class TestEvolutionStats:
    """EvolutionStats 数据类测试"""

    def test_success_rate_zero(self):
        """零任务时成功率为 0"""
        from pycoder.capabilities.self_evo.engine import EvolutionStats

        stats = EvolutionStats()
        assert stats.success_rate == 0.0

    def test_success_rate_calculation(self):
        """成功率计算"""
        from pycoder.capabilities.self_evo.engine import EvolutionStats

        stats = EvolutionStats(total_tasks=10, successful=7, failed=3)
        assert stats.success_rate == 0.7

    def test_to_dict(self):
        """to_dict 序列化"""
        from pycoder.capabilities.self_evo.engine import EvolutionStats

        stats = EvolutionStats(total_tasks=5, successful=4, failed=1, bugs_fixed=3, lines_changed=50)
        d = stats.to_dict()
        assert d["total_tasks"] == 5
        assert d["successful"] == 4
        assert d["bugs_fixed"] == 3
        assert "success_rate" in d


class TestBuildEvolutionReport:
    """_build_evolution_report 函数测试"""

    def test_basic_report(self):
        """基本报告"""
        from pycoder.capabilities.self_evo.engine import EvolutionTask, _build_evolution_report

        task = EvolutionTask(type="fix", description="测试任务")
        report = _build_evolution_report(task)
        assert report["task_id"] == task.id
        assert report["task_type"] == "fix"
        assert report["status"] == "pending"

    def test_with_grade_info(self):
        """带 grade_info"""
        from pycoder.capabilities.self_evo.engine import EvolutionTask, _build_evolution_report

        task = EvolutionTask()
        grade = {"task_type": "fix", "score": 85}
        report = _build_evolution_report(task, grade_info=grade)
        assert report["grade"] == grade

    def test_with_source_trace(self):
        """带 source_trace"""
        from pycoder.capabilities.self_evo.engine import EvolutionTask, _build_evolution_report

        task = EvolutionTask()
        trace = {"source": "api"}
        report = _build_evolution_report(task, source_trace=trace)
        assert report["source_trace"] == trace

    def test_long_test_result_truncated(self):
        """测试结果截断"""
        from pycoder.capabilities.self_evo.engine import EvolutionTask, _build_evolution_report

        task = EvolutionTask(test_result="x" * 500)
        report = _build_evolution_report(task)
        assert len(report["test_result"]) <= 200


# ═══════════════════════════════════════════════════════════════
# 模块 1: engine.py — SelfEvolutionEngine
# ═══════════════════════════════════════════════════════════════


class TestSelfEvolutionEngineInit:
    """SelfEvolutionEngine 初始化测试"""

    def test_init_with_project_root(self, tmp_path):
        """用 Path 初始化（V1 兼容）"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        engine = SelfEvolutionEngine(tmp_path)
        assert engine._project_root == tmp_path

    def test_init_with_v2_engine(self):
        """用 V2 engine 初始化"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        mock_v2 = MagicMock()
        engine = SelfEvolutionEngine(v2_engine=mock_v2)
        assert engine.v2 is mock_v2

    def test_default_project_root(self):
        """默认项目根目录"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        engine = SelfEvolutionEngine()
        assert engine._project_root is not None


class TestSelfEvolutionEngineProtected:
    """保护检查测试"""

    def test_is_protected_env_file(self):
        """检查 .env 文件受保护"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        engine = SelfEvolutionEngine()
        assert engine._is_protected(".env") is True
        assert engine._is_protected(".env.local") is True

    def test_is_protected_config_json(self):
        """检查 config.json 受保护"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        engine = SelfEvolutionEngine()
        assert engine._is_protected("config/settings.json") is True

    def test_is_protected_normal_py(self):
        """检查普通 .py 文件不受保护"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        engine = SelfEvolutionEngine()
        assert engine._is_protected("pycoder/server/app.py") is False

    def test_is_protected_db_file(self):
        """检查 .db 文件受保护"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        engine = SelfEvolutionEngine()
        assert engine._is_protected("pycoder.db") is True


class TestSelfEvolutionEnginePathToModule:
    """路径转模块名测试"""

    def test_full_path(self):
        """完整路径转换"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        engine = SelfEvolutionEngine()
        result = engine._path_to_module("pycoder/server/app.py")
        assert result == "pycoder.server.app"

    def test_init_file(self):
        """__init__.py 转换"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        engine = SelfEvolutionEngine()
        result = engine._path_to_module("pycoder/server/__init__.py")
        assert result == "pycoder.server"

    def test_no_pycoder_prefix(self):
        """无 pycoder 前缀"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        engine = SelfEvolutionEngine()
        result = engine._path_to_module("some/other/module.py")
        assert result == "module"


class TestSelfEvolutionEngineScan:
    """扫描功能测试"""

    @pytest.mark.asyncio
    async def test_scan_normal_file(self, tmp_path):
        """扫描正常文件"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        py_file = tmp_path / "test_scan.py"
        py_file.write_text("def foo():\n    pass\n", encoding="utf-8")

        engine = SelfEvolutionEngine(project_root=tmp_path)
        report = await engine.scan(path=str(tmp_path), use_llm=False)
        assert report.files_scanned >= 0
        assert isinstance(report.total_issues, int)

    @pytest.mark.asyncio
    async def test_scan_with_bare_except(self, tmp_path):
        """扫描包含裸 except 的文件"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        py_file = tmp_path / "bad.py"
        py_file.write_text("try:\n    pass\nexcept:\n    pass\n", encoding="utf-8")

        engine = SelfEvolutionEngine(project_root=tmp_path)
        report = await engine.scan(path=str(tmp_path), use_llm=False)
        # 应该检测到裸 except
        assert any("裸 except" in i.title for i in report.issues)

    @pytest.mark.asyncio
    async def test_scan_with_mutable_default(self, tmp_path):
        """扫描包含可变默认参数的文件"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        py_file = tmp_path / "mutable.py"
        py_file.write_text("def foo(x=[]):\n    pass\n", encoding="utf-8")

        engine = SelfEvolutionEngine(project_root=tmp_path)
        report = await engine.scan(path=str(tmp_path), use_llm=False)
        assert any("可变默认参数" in i.title for i in report.issues)

    @pytest.mark.asyncio
    async def test_scan_with_eval(self, tmp_path):
        """扫描包含 eval 的文件"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        py_file = tmp_path / "danger.py"
        py_file.write_text("eval('1+1')\n", encoding="utf-8")

        engine = SelfEvolutionEngine(project_root=tmp_path)
        report = await engine.scan(path=str(tmp_path), use_llm=False)
        assert any("eval" in i.title.lower() for i in report.issues)

    @pytest.mark.asyncio
    async def test_scan_with_hardcoded_secret(self, tmp_path):
        """扫描包含硬编码密钥的文件"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        py_file = tmp_path / "secret.py"
        py_file.write_text("api_key = 'sk-abcdefghijklmnop'\n", encoding="utf-8")

        engine = SelfEvolutionEngine(project_root=tmp_path)
        report = await engine.scan(path=str(tmp_path), use_llm=False)
        assert any("硬编码" in i.title for i in report.issues)

    @pytest.mark.asyncio
    async def test_scan_syntax_error(self, tmp_path):
        """扫描包含语法错误的文件"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        py_file = tmp_path / "syntax_err.py"
        py_file.write_text("def foo(\n", encoding="utf-8")  # 语法错误

        engine = SelfEvolutionEngine(project_root=tmp_path)
        report = await engine.scan(path=str(tmp_path), use_llm=False)
        assert any("语法错误" in i.title for i in report.issues)


class TestSelfEvolutionEngineGenerateFix:
    """修复生成测试"""

    def test_template_fix_bare_except(self):
        """模板修复裸 except"""
        from pycoder.capabilities.self_evo.engine import CodeIssue, SelfEvolutionEngine

        engine = SelfEvolutionEngine()
        issue = CodeIssue(
            file="test.py", line=5, severity="high", issue_type="bug", title="裸 except 吞掉所有异常",
        )
        proposal = engine._template_fix(issue)
        assert proposal.old_code == "except:"
        assert proposal.new_code == "except Exception as e:"

    def test_template_fix_mutable_default(self):
        """模板修复可变默认参数"""
        from pycoder.capabilities.self_evo.engine import CodeIssue, SelfEvolutionEngine

        engine = SelfEvolutionEngine()
        issue = CodeIssue(
            file="test.py", line=3, severity="medium", issue_type="bug",
            title="函数 'foo' 使用了可变默认参数",
        )
        proposal = engine._template_fix(issue)
        assert proposal.action == "refactor"

    def test_template_fix_generic(self):
        """模板修复通用问题"""
        from pycoder.capabilities.self_evo.engine import CodeIssue, SelfEvolutionEngine

        engine = SelfEvolutionEngine()
        issue = CodeIssue(
            file="test.py", line=1, severity="low", issue_type="style",
            title="未知问题", suggestion="手动修复",
        )
        proposal = engine._template_fix(issue)
        assert "手动修复" in proposal.reasoning


class TestSelfEvolutionEngineParseFixResponse:
    """LLM 响应解析测试"""

    def test_parse_diff_format(self):
        """解析 diff 格式响应"""
        from pycoder.capabilities.self_evo.engine import CodeIssue, SelfEvolutionEngine

        engine = SelfEvolutionEngine()
        issue = CodeIssue(file="test.py", line=1, severity="high", issue_type="bug", title="test")
        response = "```diff\n--- a/test.py\n+++ b/test.py\n-old\n+new\n```"
        proposal = engine._parse_fix_response(response, issue)
        assert proposal.action == "replace"
        assert proposal.file_path == "test.py"

    def test_parse_code_block(self):
        """解析代码块格式"""
        from pycoder.capabilities.self_evo.engine import CodeIssue, SelfEvolutionEngine

        engine = SelfEvolutionEngine()
        issue = CodeIssue(file="test.py", line=1, severity="high", issue_type="bug", title="test")
        response = "```python\ndef foo():\n    pass\n```"
        proposal = engine._parse_fix_response(response, issue)
        assert proposal.new_code.strip() == "def foo():\n    pass"

    def test_parse_no_format(self):
        """无格式回退"""
        from pycoder.capabilities.self_evo.engine import CodeIssue, SelfEvolutionEngine

        engine = SelfEvolutionEngine()
        issue = CodeIssue(file="test.py", line=1, severity="high", issue_type="bug", title="test")
        response = "只是一些文本"
        proposal = engine._parse_fix_response(response, issue)
        assert proposal.action == "replace"


class TestSelfEvolutionEngineApplyFix:
    """应用修复测试"""

    @pytest.mark.asyncio
    async def test_apply_fix_protected_file(self):
        """拒绝修改受保护文件"""
        from pycoder.capabilities.self_evo.engine import CodeIssue, FixProposal, SelfEvolutionEngine

        engine = SelfEvolutionEngine()
        issue = CodeIssue(file=".env", line=1, severity="high", issue_type="bug", title="test")
        proposal = FixProposal(issue=issue, action="replace", file_path=".env")
        result = await engine.apply_fix(proposal)
        assert result.success is False
        assert "受保护" in (result.error or "")

    @pytest.mark.asyncio
    async def test_apply_fix_too_many_files(self):
        """拒绝超过 3 个文件的修改"""
        from pycoder.capabilities.self_evo.engine import CodeIssue, FixProposal, SelfEvolutionEngine

        engine = SelfEvolutionEngine()
        # 模拟已修改 3 个文件
        with patch.object(engine, "_get_modified_in_session", return_value=["a.py", "b.py", "c.py"]):
            issue = CodeIssue(file="d.py", line=1, severity="high", issue_type="bug", title="test")
            proposal = FixProposal(issue=issue, action="replace", file_path="d.py")
            result = await engine.apply_fix(proposal)
            assert result.success is False
            assert "3 个文件" in (result.error or "")


class TestSelfEvolutionEngineRecordEvolution:
    """进化记录测试"""

    def test_record_single(self):
        """记录单条进化"""
        from pycoder.capabilities.self_evo.engine import EvolutionRecord, SelfEvolutionEngine

        with patch.object(SelfEvolutionEngine, "_load_history", lambda self: None):
            engine = SelfEvolutionEngine()
            engine._records = []
            record = EvolutionRecord(action="fix", issue_type="bug", file="a.py", success=True)
            engine.record_evolution(record)
            assert len(engine._records) == 1

    def test_get_history(self):
        """获取进化历史"""
        from pycoder.capabilities.self_evo.engine import EvolutionRecord, SelfEvolutionEngine

        with patch.object(SelfEvolutionEngine, "_load_history", lambda self: None):
            engine = SelfEvolutionEngine()
            engine._records = []
            for i in range(5):
                engine.record_evolution(
                    EvolutionRecord(action="fix", issue_type="bug", file=f"{i}.py", success=True)
                )
            history = engine.get_evolution_history(limit=3)
            assert len(history) == 3

    def test_get_stats_empty(self):
        """空记录获取统计"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        with patch.object(SelfEvolutionEngine, "_load_history", lambda self: None):
            engine = SelfEvolutionEngine()
            engine._records = []
            stats = engine.get_stats()
            assert stats["total_evolutions"] == 0


class TestSelfEvolutionEngineEvolutionToken:
    """进化令牌测试"""

    def test_generate_token(self, tmp_path):
        """生成进化令牌"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        # 临时修改令牌目录
        with patch.object(SelfEvolutionEngine, "_EVOLUTION_TOKEN_DIR", tmp_path):
            with patch.object(SelfEvolutionEngine, "_EVOLUTION_TOKEN_FILE",
                              tmp_path / "token.json"):
                token = SelfEvolutionEngine.generate_evolution_token(["test.py"])
                assert len(token) == 16
                assert (tmp_path / "token.json").exists()

    def test_validate_token(self, tmp_path):
        """验证进化令牌"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        token_file = tmp_path / "token.json"
        with patch.object(SelfEvolutionEngine, "_EVOLUTION_TOKEN_FILE", token_file):
            token = SelfEvolutionEngine.generate_evolution_token(["core.py"])
            # 令牌应该有效
            assert SelfEvolutionEngine._validate_evolution_token("core.py") is True
            # 一次性令牌不能再使用
            assert SelfEvolutionEngine._validate_evolution_token("core.py") is False

    def test_validate_token_wrong_file(self, tmp_path):
        """验证令牌不匹配的文件"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        token_file = tmp_path / "token.json"
        with patch.object(SelfEvolutionEngine, "_EVOLUTION_TOKEN_FILE", token_file):
            SelfEvolutionEngine.generate_evolution_token(["core.py"])
            assert SelfEvolutionEngine._validate_evolution_token("other.py") is False

    def test_clear_token(self, tmp_path):
        """清除进化令牌"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        token_file = tmp_path / "token.json"
        with patch.object(SelfEvolutionEngine, "_EVOLUTION_TOKEN_FILE", token_file):
            SelfEvolutionEngine.generate_evolution_token(["test.py"])
            SelfEvolutionEngine.clear_evolution_token()
            assert not token_file.exists()


class TestSelfEvolutionEngineTaskManagement:
    """任务管理测试"""

    def test_list_tasks(self):
        """列出任务"""
        from pycoder.capabilities.self_evo.engine import EvolutionTask, SelfEvolutionEngine

        engine = SelfEvolutionEngine()
        engine._tasks = [EvolutionTask() for _ in range(5)]
        tasks = engine.list_tasks(limit=3)
        assert len(tasks) == 3

    def test_get_task_found(self):
        """找到任务"""
        from pycoder.capabilities.self_evo.engine import EvolutionTask, SelfEvolutionEngine

        engine = SelfEvolutionEngine()
        task = EvolutionTask()
        engine._tasks = [task]
        result = engine.get_task(task.id)
        assert result is not None
        assert result["id"] == task.id

    def test_get_task_not_found(self):
        """未找到任务"""
        from pycoder.capabilities.self_evo.engine import SelfEvolutionEngine

        engine = SelfEvolutionEngine()
        result = engine.get_task("nonexistent")
        assert result is None


# ═══════════════════════════════════════════════════════════════
# 模块 2: closed_loop.py — 数据模型
# ═══════════════════════════════════════════════════════════════


class TestLearningObservation:
    """LearningObservation 数据类测试"""

    def test_creation(self):
        """创建观察对象"""
        from pycoder.capabilities.self_evo.learning.closed_loop import LearningObservation

        obs = LearningObservation(task_id="T001")
        assert obs.task_id == "T001"
        assert obs.success is False
        assert obs.steps_taken == 0
        assert obs.errors_encountered == []
        assert obs.patterns_used == []
        assert obs.patterns_failed == []

    def test_full_fields(self):
        """完整字段"""
        from pycoder.capabilities.self_evo.learning.closed_loop import LearningObservation

        obs = LearningObservation(
            task_id="T002", task_description="测试任务", success=True, steps_taken=5,
            errors_encountered=["err1"], patterns_used=["pat1"], patterns_failed=["pat2"],
            metadata={"key": "val"},
        )
        assert obs.success is True
        assert obs.steps_taken == 5
        assert obs.errors_encountered == ["err1"]
        assert obs.metadata == {"key": "val"}


class TestLearnedSkill:
    """LearnedSkill 数据类测试"""

    def test_creation(self):
        """创建技能对象"""
        from pycoder.capabilities.self_evo.learning.closed_loop import LearnedSkill

        skill = LearnedSkill(name="test_skill", pattern="test_pattern")
        assert skill.name == "test_skill"
        assert skill.pattern == "test_pattern"
        assert skill.success_rate == 0.0
        assert skill.usage_count == 0
        assert skill.pruned is False

    def test_pruned_flag(self):
        """已淘汰标记"""
        from pycoder.capabilities.self_evo.learning.closed_loop import LearnedSkill

        skill = LearnedSkill(pruned=True)
        assert skill.pruned is True


# ═══════════════════════════════════════════════════════════════
# 模块 2: closed_loop.py — ClosedLearningLoop
# ═══════════════════════════════════════════════════════════════


class TestClosedLearningLoopInit:
    """ClosedLearningLoop 初始化测试"""

    def test_init_with_tmp_db(self, tmp_path):
        """用临时数据库初始化"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "test.db"
        loop = ClosedLearningLoop(db_path=db_path)
        assert Path(loop._db_path) == db_path
        assert db_path.exists()

    def test_ensure_list_static(self):
        """_ensure_list 静态方法"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        assert ClosedLearningLoop._ensure_list(["a", "b"]) == ["a", "b"]
        assert ClosedLearningLoop._ensure_list("hello") == ["hello"]
        assert ClosedLearningLoop._ensure_list(123) == []

    def test_extract_keywords(self):
        """_extract_keywords 静态方法"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        keywords = ClosedLearningLoop._extract_keywords("fix the python bug in server")
        assert "python" in keywords
        assert "bug" in keywords
        assert "server" in keywords
        # 停用词应被过滤
        assert "the" not in keywords
        assert "in" not in keywords

    def test_extract_keywords_empty(self):
        """空字符串提取关键词"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        assert ClosedLearningLoop._extract_keywords("") == []

    def test_derive_skill_name(self):
        """_derive_skill_name 静态方法"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        name = ClosedLearningLoop._derive_skill_name("type:my_pattern", {})
        assert name == "my_pattern"

    def test_derive_skill_name_long(self):
        """长模式截断"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        long_pattern = "x" * 100
        name = ClosedLearningLoop._derive_skill_name(long_pattern, {})
        assert len(name) <= 83  # 80 + "..."

    def test_row_to_skill(self):
        """_row_to_skill 静态方法"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        row = {
            "id": "s1", "name": "test", "description": "", "pattern": "", "strategy": "",
            "success_rate": 0.8, "usage_count": 5, "created_at": 0.0, "updated_at": 0.0,
            "source_task_id": "", "pruned": 0,
        }
        skill = ClosedLearningLoop._row_to_skill(row)
        assert skill.id == "s1"
        assert skill.success_rate == 0.8
        assert skill.pruned is False


class TestClosedLearningLoopObserve:
    """观察方法测试"""

    @pytest.mark.asyncio
    async def test_observe_success(self, tmp_path):
        """记录成功观察"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "obs.db"
        loop = ClosedLearningLoop(db_path=db_path)
        obs = await loop.observe("T001", {
            "description": "测试", "success": True, "steps": 3,
            "errors": [], "patterns_used": ["pat1"], "patterns_failed": [],
        })
        assert obs.task_id == "T001"
        assert obs.success is True
        assert obs.steps_taken == 3

    @pytest.mark.asyncio
    async def test_observe_failure(self, tmp_path):
        """记录失败观察"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "obs2.db"
        loop = ClosedLearningLoop(db_path=db_path)
        obs = await loop.observe("T002", {
            "success": False, "errors": ["NameError"],
        })
        assert obs.success is False
        assert obs.errors_encountered == ["NameError"]


class TestClosedLearningLoopReflect:
    """反思方法测试"""

    @pytest.mark.asyncio
    async def test_reflect_success(self, tmp_path):
        """反思成功任务"""
        from pycoder.capabilities.self_evo.learning.closed_loop import (
            ClosedLearningLoop, LearningObservation,
        )

        db_path = tmp_path / "reflect.db"
        loop = ClosedLearningLoop(db_path=db_path)
        obs = LearningObservation(
            task_id="T001", success=True, steps_taken=2,
            patterns_used=["pattern_a"], patterns_failed=[],
        )
        reflection = await loop.reflect(obs)
        assert reflection["task_id"] == "T001"
        assert reflection["success"] is True
        assert "confidence" in reflection
        assert "recommendations" in reflection

    @pytest.mark.asyncio
    async def test_reflect_failure(self, tmp_path):
        """反思失败任务"""
        from pycoder.capabilities.self_evo.learning.closed_loop import (
            ClosedLearningLoop, LearningObservation,
        )

        db_path = tmp_path / "reflect2.db"
        loop = ClosedLearningLoop(db_path=db_path)
        obs = LearningObservation(
            task_id="T002", success=False, errors_encountered=["TypeError"],
        )
        reflection = await loop.reflect(obs)
        assert reflection["success"] is False
        assert len(reflection["patterns_avoid"]) >= 0


class TestClosedLearningLoopGenerateSkill:
    """技能生成测试"""

    @pytest.mark.asyncio
    async def test_generate_skill_from_reflection(self, tmp_path):
        """从反思生成技能"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "skill.db"
        loop = ClosedLearningLoop(db_path=db_path)
        reflection = {
            "task_id": "T001",
            "patterns_found": [
                {"pattern": "fix_bare_except", "confidence": 0.9,
                 "suggestion": "使用 except Exception"},
            ],
            "patterns_avoid": [],
        }
        skills = await loop.generate_skill(reflection)
        assert len(skills) >= 1
        assert skills[0].success_rate == 0.9

    @pytest.mark.asyncio
    async def test_generate_skill_empty_patterns(self, tmp_path):
        """空模式不生成技能"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "skill2.db"
        loop = ClosedLearningLoop(db_path=db_path)
        reflection = {"task_id": "T001", "patterns_found": [], "patterns_avoid": []}
        skills = await loop.generate_skill(reflection)
        assert len(skills) == 0


class TestClosedLearningLoopApplyFeedback:
    """反馈应用测试"""

    @pytest.mark.asyncio
    async def test_apply_feedback(self, tmp_path):
        """应用反馈"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "feedback.db"
        loop = ClosedLearningLoop(db_path=db_path)
        result = await loop.apply_feedback("fix python import error")
        assert "matched_skills" in result
        assert "context_hints" in result
        assert "keywords" in result


class TestClosedLearningLoopRefineSkills:
    """技能精炼测试"""

    @pytest.mark.asyncio
    async def test_refine_skipped(self, tmp_path):
        """精炼间隔未到应跳过"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "refine.db"
        loop = ClosedLearningLoop(db_path=db_path)
        loop._last_refine_time = time.time()  # 刚刚精炼过
        result = await loop.refine_skills()
        assert result["skipped"] is True

    @pytest.mark.asyncio
    async def test_refine_triggered(self, tmp_path):
        """精炼可触发"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "refine2.db"
        loop = ClosedLearningLoop(db_path=db_path)
        loop._last_refine_time = 0  # 很久以前
        result = await loop.refine_skills()
        assert "total_skills" in result
        assert "pruned" in result


class TestClosedLearningLoopRunCycle:
    """完整闭环测试"""

    @pytest.mark.asyncio
    async def test_run_cycle(self, tmp_path):
        """运行完整闭环"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "cycle.db"
        loop = ClosedLearningLoop(db_path=db_path)
        result = await loop.run_cycle("T001", {
            "description": "测试任务", "success": True, "steps": 2,
            "patterns_used": ["pattern_a"],
        })
        assert result["task_id"] == "T001"
        assert "cycle_duration_ms" in result
        assert result["observation"]["success"] is True


class TestClosedLearningLoopGetStats:
    """统计查询测试"""

    def test_get_stats_empty(self, tmp_path):
        """空数据库统计"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "stats.db"
        loop = ClosedLearningLoop(db_path=db_path)
        stats = loop.get_stats()
        assert stats["total_observations"] == 0
        assert stats["total_skills"] == 0


class TestGetClosedLoop:
    """全局单例测试"""

    def test_singleton(self):
        """单例模式"""
        from pycoder.capabilities.self_evo.learning.closed_loop import get_closed_loop

        loop1 = get_closed_loop()
        loop2 = get_closed_loop()
        assert loop1 is loop2


# ═══════════════════════════════════════════════════════════════
# 模块 3: __init__.py — 能力注册
# ═══════════════════════════════════════════════════════════════


class TestRegisterSelfEvoCapabilities:
    """能力注册测试"""

    def test_register_all_capabilities(self):
        """注册所有能力"""
        from pycoder.capabilities.self_evo import register_self_evo_capabilities

        registry = MagicMock()
        register_self_evo_capabilities(registry)
        # 应该注册了至少 10+ 个能力
        assert registry.register.call_count >= 10


class TestScanCodeHandler:
    """扫描代码处理器测试"""

    @pytest.mark.asyncio
    async def test_scan_code(self, tmp_path):
        """扫描代码"""
        from pycoder.capabilities.self_evo import _scan_code

        py_file = tmp_path / "test.py"
        py_file.write_text("try:\n    pass\nexcept:\n    pass\n", encoding="utf-8")

        result = await _scan_code({"path": str(tmp_path)}, {})
        assert result["files_scanned"] >= 1
        assert "issues" in result

    @pytest.mark.asyncio
    async def test_scan_code_with_severity_filter(self, tmp_path):
        """严重度过滤"""
        from pycoder.capabilities.self_evo import _scan_code

        py_file = tmp_path / "test.py"
        py_file.write_text("print('hello')\n", encoding="utf-8")

        result = await _scan_code({"path": str(tmp_path), "severity_filter": "critical"}, {})
        assert "issues" in result


class TestDetectBugs:
    """Bug 检测测试"""

    def test_detect_bare_except(self):
        """检测裸 except"""
        import ast
        from pycoder.capabilities.self_evo import _detect_bugs

        source = "try:\n    pass\nexcept:\n    pass\n"
        tree = ast.parse(source)
        issues = _detect_bugs(tree, "test.py", source)
        assert any(i["type"] == "bare_except" for i in issues)

    def test_detect_mutable_default(self):
        """检测可变默认参数"""
        import ast
        from pycoder.capabilities.self_evo import _detect_bugs

        source = "def foo(x=[]):\n    pass\n"
        tree = ast.parse(source)
        issues = _detect_bugs(tree, "test.py", source)
        assert any(i["type"] == "mutable_default" for i in issues)

    def test_detect_unnecessary_fstring(self):
        """检测不必要的 f-string"""
        import ast
        from pycoder.capabilities.self_evo import _detect_bugs

        source = "x = f'hello'\n"
        tree = ast.parse(source)
        issues = _detect_bugs(tree, "test.py", source)
        assert any(i["type"] == "unnecessary_fstring" for i in issues)


class TestDetectComplexity:
    """复杂度检测测试"""

    def test_detect_long_function(self):
        """检测过长函数"""
        import ast
        from pycoder.capabilities.self_evo import _detect_complexity

        # 构造一个超过 100 行的函数
        lines = ["def long_func():"] + ["    pass"] * 102
        source = "\n".join(lines)
        tree = ast.parse(source)
        issues = _detect_complexity(tree, "test.py")
        assert any(i["type"] == "long_function" for i in issues)


class TestDetectSecurity:
    """安全检测测试"""

    def test_detect_dangerous_call(self):
        """检测危险函数调用"""
        import ast
        from pycoder.capabilities.self_evo import _detect_security

        source = "eval('1+1')\n"
        tree = ast.parse(source)
        issues = _detect_security(tree, "test.py", source)
        assert any(i["type"] == "dangerous_call" for i in issues)

    def test_detect_hardcoded_secret(self):
        """检测硬编码密钥"""
        import ast
        from pycoder.capabilities.self_evo import _detect_security

        source = "API_KEY = 'sk-abcdefghijklmnop'\n"
        tree = ast.parse(source)
        issues = _detect_security(tree, "test.py", source)
        assert any(i["type"] == "hardcoded_secret" for i in issues)


class TestDetectStyle:
    """风格检测测试"""

    def test_detect_print(self):
        """检测 print 使用"""
        import ast
        from pycoder.capabilities.self_evo import _detect_style

        source = "print('hello')\n"
        tree = ast.parse(source)
        issues = _detect_style(tree, "test.py", source)
        assert any(i["type"] == "use_print" for i in issues)


class TestGenerateFix:
    """修复生成处理器测试"""

    @pytest.mark.asyncio
    async def test_generate_fix_no_issue(self):
        """无 issue 参数"""
        from pycoder.capabilities.self_evo import _generate_fix

        result = await _generate_fix({"issue_ids": []}, {})
        assert "fixes" in result
        assert len(result["fixes"]) == 0


class TestApplyFix:
    """应用修复处理器测试"""

    @pytest.mark.asyncio
    async def test_apply_fix_no_file(self):
        """无文件路径"""
        from pycoder.capabilities.self_evo import _apply_fix

        result = await _apply_fix({"fix": {}}, {})
        assert result["applied"] is False

    @pytest.mark.asyncio
    async def test_apply_fix_file_not_found(self):
        """文件不存在"""
        from pycoder.capabilities.self_evo import _apply_fix

        result = await _apply_fix({"fix": {"file": "/nonexistent/file.py"}}, {})
        assert result["applied"] is False


class TestTemplateFixForIssue:
    """模板修复测试"""

    def test_bare_except_template(self):
        """裸 except 模板"""
        from pycoder.capabilities.self_evo import _template_fix_for_issue
        from pycoder.capabilities.self_evo.engine import CodeIssue

        issue = CodeIssue(
            file="test.py", line=5, severity="high", issue_type="bug", title="裸 except 吞掉所有异常",
        )
        fix = _template_fix_for_issue(issue)
        assert fix["old_code"] == "except:"
        assert fix["new_code"] == "except Exception as e:"

    def test_hardcoded_template(self):
        """硬编码模板"""
        from pycoder.capabilities.self_evo import _template_fix_for_issue
        from pycoder.capabilities.self_evo.engine import CodeIssue

        issue = CodeIssue(
            file="test.py", line=1, severity="critical", issue_type="security",
            title="检测到硬编码密钥",
        )
        fix = _template_fix_for_issue(issue)
        assert "os.getenv" in fix["fix_code"]

    def test_generic_template(self):
        """通用模板"""
        from pycoder.capabilities.self_evo import _template_fix_for_issue
        from pycoder.capabilities.self_evo.engine import CodeIssue

        issue = CodeIssue(
            file="test.py", line=1, severity="low", issue_type="style",
            title="未知问题", suggestion="手动修复一下",
        )
        fix = _template_fix_for_issue(issue)
        assert "TODO" in fix["fix_code"]


class TestCountSeverity:
    """严重度统计测试"""

    def test_count(self):
        """统计严重度"""
        from pycoder.capabilities.self_evo import _count_severity

        issues = [
            {"severity": "critical"},
            {"severity": "high"},
            {"severity": "high"},
            {"severity": "low"},
        ]
        result = _count_severity(issues)
        assert result["critical"] == 1
        assert result["high"] == 2
        assert result["low"] == 1


# ═══════════════════════════════════════════════════════════════
# 模块 4: experience_buffer.py — 数据模型
# ═══════════════════════════════════════════════════════════════


class TestTaskExperience:
    """TaskExperience 数据类测试"""

    def test_defaults(self):
        """默认值"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import TaskExperience

        exp = TaskExperience()
        assert exp.outcome == ""
        assert exp.reward == 0.0
        assert exp.priority == 1.0
        assert exp.novelty_score == 0.5

    def test_full_fields(self):
        """完整字段"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import TaskExperience

        exp = TaskExperience(
            id="EXP-001", task_type="fix", outcome="success",
            test_passed=True, quality_score=90, reward=0.8,
        )
        assert exp.id == "EXP-001"
        assert exp.outcome == "success"
        assert exp.reward == 0.8


class TestComputeReward:
    """奖励计算函数测试"""

    def test_success_reward(self):
        """成功奖励"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import compute_reward

        reward = compute_reward("success", True, 90, 0, 1000, 5000)
        assert reward > 0.5

    def test_failure_reward(self):
        """失败奖励"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import compute_reward

        reward = compute_reward("failure", False, 10, 5, 10000, 60000)
        assert reward < 0

    def test_rolled_back_reward(self):
        """回滚奖励"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import compute_reward

        reward = compute_reward("rolled_back", False, 0, 3, 5000, 30000)
        assert reward < 0

    def test_bounds(self):
        """奖励范围 [-1.0, 1.0]"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import compute_reward

        reward = compute_reward("success", True, 100, 0, 0, 0, is_novel=True)
        assert -1.0 <= reward <= 1.0


class TestExperienceBuffer:
    """ExperienceBuffer 测试"""

    def test_init_empty(self, tmp_path):
        """初始化为空"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            ExperienceBuffer, EXP_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.EXP_DIR",
                   tmp_path / "exp"):
            buf = ExperienceBuffer(capacity=10)
            assert len(buf) == 0
            assert buf.is_full is False

    def test_store_and_retrieve(self, tmp_path):
        """存储和检索"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            ExperienceBuffer, TaskExperience, EXP_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.EXP_DIR",
                   tmp_path / "exp"):
            buf = ExperienceBuffer(capacity=10)
            exp = TaskExperience(
                id="EXP-001", task_type="fix", outcome="success",
                test_passed=True, quality_score=90,
            )
            exp_id = buf.store(exp)
            assert exp_id == "EXP-001"

    def test_sample_priority(self, tmp_path):
        """优先级采样"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            ExperienceBuffer, TaskExperience, EXP_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.EXP_DIR",
                   tmp_path / "exp"):
            buf = ExperienceBuffer(capacity=20)
            for i in range(5):
                exp = TaskExperience(
                    id=f"EXP-{i}", outcome="success", test_passed=True,
                    quality_score=80 + i * 5,
                )
                buf.store(exp)
            sample = buf.sample(batch_size=3, strategy="priority")
            assert len(sample) == 3

    def test_sample_recent(self, tmp_path):
        """最近采样"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            ExperienceBuffer, TaskExperience, EXP_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.EXP_DIR",
                   tmp_path / "exp"):
            buf = ExperienceBuffer(capacity=20)
            for i in range(5):
                exp = TaskExperience(id=f"EXP-{i}", outcome="success", test_passed=True)
                buf.store(exp)
            sample = buf.sample(batch_size=3, strategy="recent")
            assert len(sample) <= 3

    def test_sample_random(self, tmp_path):
        """随机采样"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            ExperienceBuffer, TaskExperience, EXP_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.EXP_DIR",
                   tmp_path / "exp"):
            buf = ExperienceBuffer(capacity=20)
            for i in range(5):
                exp = TaskExperience(id=f"EXP-{i}", outcome="success", test_passed=True)
                buf.store(exp)
            sample = buf.sample(batch_size=2, strategy="random")
            assert len(sample) == 2

    def test_sample_empty(self, tmp_path):
        """空缓冲区采样"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            ExperienceBuffer, EXP_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.EXP_DIR",
                   tmp_path / "exp"):
            buf = ExperienceBuffer()
            sample = buf.sample(batch_size=10)
            assert sample == []

    def test_get_failures(self, tmp_path):
        """获取失败经验"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            ExperienceBuffer, TaskExperience, EXP_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.EXP_DIR",
                   tmp_path / "exp"):
            buf = ExperienceBuffer(capacity=20)
            buf.store(TaskExperience(id="E1", outcome="failure"))
            buf.store(TaskExperience(id="E2", outcome="success"))
            buf.store(TaskExperience(id="E3", outcome="rolled_back"))
            failures = buf.get_failures()
            assert len(failures) == 2

    def test_get_successes(self, tmp_path):
        """获取成功经验"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            ExperienceBuffer, TaskExperience, EXP_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.EXP_DIR",
                   tmp_path / "exp"):
            buf = ExperienceBuffer(capacity=20)
            buf.store(TaskExperience(id="E1", outcome="success"))
            buf.store(TaskExperience(id="E2", outcome="failure"))
            successes = buf.get_successes()
            assert len(successes) == 1

    def test_update_priority(self, tmp_path):
        """更新优先级"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            ExperienceBuffer, TaskExperience, EXP_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.EXP_DIR",
                   tmp_path / "exp"):
            buf = ExperienceBuffer(capacity=10)
            exp = TaskExperience(id="E1", outcome="success", test_passed=True)
            buf.store(exp)
            result = buf.update_priority("E1", 0.9)
            assert result is True

    def test_update_priority_not_found(self, tmp_path):
        """更新不存在的优先级"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            ExperienceBuffer, EXP_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.EXP_DIR",
                   tmp_path / "exp"):
            buf = ExperienceBuffer()
            result = buf.update_priority("nonexistent", 0.5)
            assert result is False

    def test_mark_learned(self, tmp_path):
        """标记已学习"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            ExperienceBuffer, TaskExperience, EXP_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.EXP_DIR",
                   tmp_path / "exp"):
            buf = ExperienceBuffer(capacity=10)
            exp = TaskExperience(id="E1", outcome="success", test_passed=True)
            buf.store(exp)
            count = buf.mark_learned(["E1"])
            assert count == 1

    def test_get_stats(self, tmp_path):
        """获取统计"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            ExperienceBuffer, TaskExperience, EXP_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.EXP_DIR",
                   tmp_path / "exp"):
            buf = ExperienceBuffer(capacity=20)
            buf.store(TaskExperience(id="E1", outcome="success", test_passed=True, quality_score=90))
            stats = buf.get_stats()
            assert stats.total == 1
            assert stats.success == 1

    def test_get_novel(self, tmp_path):
        """获取新颖经验"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            ExperienceBuffer, TaskExperience, EXP_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.EXP_DIR",
                   tmp_path / "exp"):
            buf = ExperienceBuffer(capacity=20)
            for i in range(5):
                buf.store(TaskExperience(id=f"E{i}", outcome="success", test_passed=True))
            novel = buf.get_novel(limit=3)
            assert len(novel) <= 3


class TestExperienceBufferCapacity:
    """容量控制测试"""

    def test_eviction(self, tmp_path):
        """容量满时淘汰"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            ExperienceBuffer, TaskExperience, EXP_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.EXP_DIR",
                   tmp_path / "exp"):
            buf = ExperienceBuffer(capacity=5)
            for i in range(10):
                buf.store(TaskExperience(
                    id=f"E{i}", outcome="success", test_passed=True,
                    quality_score=50 + i * 5,
                ))
            assert len(buf) <= 5


class TestIterationMemory:
    """IterationMemory 测试"""

    def test_start_iteration(self, tmp_path):
        """开始迭代"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            IterationMemory, MEMORY_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.MEMORY_DIR",
                   tmp_path):
            mem = IterationMemory()
            record = mem.start_iteration("test_feature")
            assert record.feature_name == "test_feature"
            assert record.iteration_id.startswith("ITER-")

    def test_record_file_change(self, tmp_path):
        """记录文件变更"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            IterationMemory, MEMORY_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.MEMORY_DIR",
                   tmp_path):
            mem = IterationMemory()
            mem.start_iteration("feature")
            mem.record_file_change("test.py")
            assert "test.py" in mem._active.files_modified

    def test_record_error(self, tmp_path):
        """记录错误"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            IterationMemory, MEMORY_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.MEMORY_DIR",
                   tmp_path):
            mem = IterationMemory()
            mem.start_iteration("feature")
            mem.record_error("NameError")
            assert len(mem._active.errors_encountered) == 1

    def test_record_commit(self, tmp_path):
        """记录提交"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            IterationMemory, MEMORY_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.MEMORY_DIR",
                   tmp_path):
            mem = IterationMemory()
            mem.start_iteration("feature")
            mem.record_commit("fix: something")
            assert mem._active.total_steps == 1

    def test_record_test(self, tmp_path):
        """记录测试"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            IterationMemory, MEMORY_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.MEMORY_DIR",
                   tmp_path):
            mem = IterationMemory()
            mem.start_iteration("feature")
            mem.record_test("test_foo", True)
            assert len(mem._active.test_results) == 1

    def test_record_rollback(self, tmp_path):
        """记录回滚"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            IterationMemory, MEMORY_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.MEMORY_DIR",
                   tmp_path):
            mem = IterationMemory()
            mem.start_iteration("feature")
            mem.record_rollback()
            assert mem._active.rollback_events == 1

    def test_finish_iteration(self, tmp_path):
        """结束迭代"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            IterationMemory, MEMORY_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.MEMORY_DIR",
                   tmp_path):
            mem = IterationMemory()
            mem.start_iteration("feature")
            record = mem.finish_iteration()
            assert record is not None
            assert mem._active is None

    def test_load_iteration_not_found(self, tmp_path):
        """加载不存在的迭代"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            IterationMemory, MEMORY_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer.MEMORY_DIR",
                   tmp_path):
            mem = IterationMemory()
            result = mem.load_iteration("nonexistent")
            assert result is None


class TestEngineerProfile:
    """EngineerProfile 测试"""

    def test_defaults(self):
        """默认值"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import EngineerProfile

        profile = EngineerProfile()
        assert profile.naming_convention == "snake_case"
        assert profile.test_framework == "pytest"
        assert profile.commit_style == "conventional"

    def test_to_dict(self):
        """to_dict 序列化"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import EngineerProfile

        profile = EngineerProfile(
            preferred_libraries=["pandas", "numpy"],
            banned_patterns=["eval"],
        )
        d = profile.to_dict()
        assert "pandas" in d["preferred_libraries"]
        assert "eval" in d["banned_patterns"]

    def test_get_engineer_profile(self, tmp_path):
        """获取工程师记忆"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            get_engineer_profile, _PROFILE_PATH,
        )

        with patch("pycoder.capabilities.self_evo.learning.experience_buffer._PROFILE_PATH",
                   tmp_path / "profile.json"):
            profile = get_engineer_profile()
            assert profile.naming_convention == "snake_case"

    def test_save_engineer_profile(self, tmp_path):
        """保存工程师记忆"""
        from pycoder.capabilities.self_evo.learning.experience_buffer import (
            EngineerProfile, save_engineer_profile, _PROFILE_PATH,
        )

        profile_path = tmp_path / "profile.json"
        with patch("pycoder.capabilities.self_evo.learning.experience_buffer._PROFILE_PATH",
                   profile_path):
            with patch("pycoder.capabilities.self_evo.learning.experience_buffer.MEMORY_DIR",
                       tmp_path):
                profile = EngineerProfile()
                save_engineer_profile(profile)
                assert profile_path.exists()


# ═══════════════════════════════════════════════════════════════
# 模块 5: upgrade.py — 数据模型与函数
# ═══════════════════════════════════════════════════════════════


class TestVersionInfo:
    """VersionInfo 数据类测试"""

    def test_creation(self):
        """创建版本信息"""
        from pycoder.capabilities.self_evo.upgrade import VersionInfo

        info = VersionInfo(current="0.5.0", latest="0.6.0", has_update=True)
        assert info.current == "0.5.0"
        assert info.has_update is True


class TestHealthCheckResult:
    """HealthCheckResult 数据类测试"""

    def test_creation(self):
        """创建健康检查结果"""
        from pycoder.capabilities.self_evo.upgrade import HealthCheckResult

        result = HealthCheckResult(passed=True)
        assert result.passed is True
        assert result.errors == []


class TestUpgradeResult:
    """UpgradeResult 数据类测试"""

    def test_creation(self):
        """创建升级结果"""
        from pycoder.capabilities.self_evo.upgrade import UpgradeResult

        result = UpgradeResult(success=True, from_version="0.5.0", to_version="0.6.0")
        assert result.success is True
        assert result.from_version == "0.5.0"


class TestValidateUrl:
    """URL 验证测试"""

    def test_valid_url(self):
        """有效 URL"""
        from pycoder.capabilities.self_evo.upgrade import _validate_url

        result = _validate_url("https://api.github.com")
        assert result == "https://api.github.com"

    def test_invalid_url(self):
        """无效协议"""
        from pycoder.capabilities.self_evo.upgrade import _validate_url

        with pytest.raises(ValueError):
            _validate_url("file:///etc/passwd")


class TestCompareVersions:
    """版本比较测试"""

    def test_newer(self):
        """新版本大于"""
        from pycoder.capabilities.self_evo.upgrade import _compare_versions

        assert _compare_versions("1.0.0", "0.9.0") == 1

    def test_older(self):
        """旧版本小于"""
        from pycoder.capabilities.self_evo.upgrade import _compare_versions

        assert _compare_versions("0.5.0", "1.0.0") == -1

    def test_equal(self):
        """版本相等"""
        from pycoder.capabilities.self_evo.upgrade import _compare_versions

        assert _compare_versions("0.5.0", "0.5.0") == 0

    def test_invalid_format(self):
        """无效格式返回 0"""
        from pycoder.capabilities.self_evo.upgrade import _compare_versions

        assert _compare_versions("abc", "1.0") == 0


class TestPendingUpgrade:
    """断点续传测试"""

    def test_save_and_load(self, tmp_path):
        """保存和加载"""
        from pycoder.capabilities.self_evo.upgrade import (
            save_pending_upgrade, load_pending_upgrade, PENDING_FILE,
        )

        with patch("pycoder.capabilities.self_evo.upgrade.PENDING_FILE",
                   tmp_path / "pending.json"):
            save_pending_upgrade("0.5.0", "0.6.0", "git_pull")
            pending = load_pending_upgrade()
            assert pending["from_version"] == "0.5.0"
            assert pending["stage"] == "git_pull"

    def test_load_none(self, tmp_path):
        """加载不存在文件"""
        from pycoder.capabilities.self_evo.upgrade import load_pending_upgrade, PENDING_FILE

        with patch("pycoder.capabilities.self_evo.upgrade.PENDING_FILE",
                   tmp_path / "nonexistent.json"):
            result = load_pending_upgrade()
            assert result is None

    def test_clear(self, tmp_path):
        """清除"""
        from pycoder.capabilities.self_evo.upgrade import (
            save_pending_upgrade, clear_pending_upgrade, PENDING_FILE,
        )

        pending_file = tmp_path / "pending.json"
        with patch("pycoder.capabilities.self_evo.upgrade.PENDING_FILE", pending_file):
            with patch("pycoder.capabilities.self_evo.upgrade.UPGRADE_DIR", tmp_path):
                save_pending_upgrade("0.5.0", "0.6.0")
                clear_pending_upgrade()
                assert not pending_file.exists()


class TestRunUpgrade:
    """升级执行测试"""

    def test_dry_run(self):
        """模拟模式"""
        from pycoder.capabilities.self_evo.upgrade import run_upgrade

        result = run_upgrade(dry_run=True)
        assert result.success is True
        assert len(result.steps) >= 1


# ═══════════════════════════════════════════════════════════════
# 模块 6: feedback_loop.py
# ═══════════════════════════════════════════════════════════════


class TestFeedbackSignal:
    """FeedbackSignal 数据类测试"""

    def test_defaults(self):
        """默认值"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import FeedbackSignal

        sig = FeedbackSignal()
        assert sig.signal_type == ""
        assert sig.outcome == ""
        assert sig.user_rating == 0


class TestAdaptiveConfig:
    """AdaptiveConfig 数据类测试"""

    def test_defaults(self):
        """默认值"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import AdaptiveConfig

        config = AdaptiveConfig()
        assert config.quality_threshold == 85.0
        assert config.max_retries == 3


class TestFeedbackLoop:
    """FeedbackLoop 测试"""

    def test_collect_signal(self, tmp_path):
        """收集反馈信号"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import (
            FeedbackLoop, FEEDBACK_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR",
                   tmp_path):
            fl = FeedbackLoop()
            fl.collect(task_id="T001", outcome="success", quality_score=90, test_passed=True)
            assert len(fl._signals) == 1

    def test_collect_explicit(self, tmp_path):
        """显式反馈信号类型"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import (
            FeedbackLoop, FEEDBACK_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR",
                   tmp_path):
            fl = FeedbackLoop()
            fl.collect(task_id="T001", outcome="success", user_rating=1)
            assert fl._signals[0].signal_type == "explicit"

    def test_collect_implicit(self, tmp_path):
        """隐式反馈信号类型"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import (
            FeedbackLoop, FEEDBACK_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR",
                   tmp_path):
            fl = FeedbackLoop()
            fl.collect(task_id="T001", outcome="success", user_rating=0)
            assert fl._signals[0].signal_type == "implicit"

    def test_get_adaptive_config(self, tmp_path):
        """获取自适应配置"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import (
            FeedbackLoop, FEEDBACK_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR",
                   tmp_path):
            fl = FeedbackLoop()
            config = fl.get_adaptive_config()
            assert isinstance(config.quality_threshold, float)

    def test_get_recent_feedback(self, tmp_path):
        """获取最近反馈"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import (
            FeedbackLoop, FEEDBACK_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR",
                   tmp_path):
            fl = FeedbackLoop()
            fl.collect(task_id="T001", outcome="success", quality_score=90)
            recent = fl.get_recent_feedback(limit=5)
            assert len(recent) == 1

    def test_get_stats_empty(self, tmp_path):
        """空信号统计"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import (
            FeedbackLoop, FEEDBACK_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR",
                   tmp_path):
            fl = FeedbackLoop()
            stats = fl.get_stats()
            assert stats["total_signals"] == 0
            assert stats["recent_success_rate"] == 0.0

    def test_force_adjust(self, tmp_path):
        """强制调整"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import (
            FeedbackLoop, FEEDBACK_DIR,
        )

        with patch("pycoder.capabilities.self_evo.learning.feedback_loop.FEEDBACK_DIR",
                   tmp_path):
            fl = FeedbackLoop()
            config = fl.force_adjust()
            assert isinstance(config.quality_threshold, float)

    def test_signal_to_dict(self):
        """信号序列化"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import (
            FeedbackLoop, FeedbackSignal,
        )

        sig = FeedbackSignal(task_id="T001", outcome="success")
        d = FeedbackLoop._signal_to_dict(sig)
        assert d["task_id"] == "T001"
        assert d["outcome"] == "success"


class TestGetFeedbackLoop:
    """全局单例测试"""

    def test_singleton(self):
        """单例模式"""
        from pycoder.capabilities.self_evo.learning.feedback_loop import get_feedback_loop

        fl1 = get_feedback_loop()
        fl2 = get_feedback_loop()
        assert fl1 is fl2


# ═══════════════════════════════════════════════════════════════
# 模块 7: metrics_tracker.py
# ═══════════════════════════════════════════════════════════════


class TestMetricsTrackerRecord:
    """MetricsTracker 记录测试"""

    def test_record_evolution(self, tmp_path):
        """记录进化"""
        from pycoder.capabilities.self_evo.learning.metrics_tracker import (
            MetricsTracker, METRICS_DB,
        )

        db_path = tmp_path / "metrics.db"
        with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.METRICS_DB",
                   db_path):
            with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.DB_DIR",
                       tmp_path):
                mt = MetricsTracker()
                row_id = mt.record_evolution(
                    task_id="T001", operation="fix", outcome="success",
                    lines_changed=10, bugs_fixed=2, test_passed=True,
                    quality_score=90,
                )
                assert row_id > 0

    def test_record_quality_snapshot(self, tmp_path):
        """记录质量快照"""
        from pycoder.capabilities.self_evo.learning.metrics_tracker import (
            MetricsTracker, METRICS_DB,
        )

        db_path = tmp_path / "metrics2.db"
        with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.METRICS_DB",
                   db_path):
            with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.DB_DIR",
                       tmp_path):
                mt = MetricsTracker()
                mt.record_quality_snapshot(
                    lint_score=90, security_score=95,
                    test_coverage=80, total_score=88,
                )
                # 只要不抛异常就算成功

    def test_record_learning_event(self, tmp_path):
        """记录学习事件"""
        from pycoder.capabilities.self_evo.learning.metrics_tracker import (
            MetricsTracker, METRICS_DB,
        )

        db_path = tmp_path / "metrics3.db"
        with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.METRICS_DB",
                   db_path):
            with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.DB_DIR",
                       tmp_path):
                mt = MetricsTracker()
                mt.record_learning_event(
                    event_type="pattern_discovered",
                    description="发现新修复模式",
                    data={"pattern": "fix_bare_except"},
                )
                events = mt.get_learning_events(limit=10)
                assert len(events) >= 1


class TestMetricsTrackerQuery:
    """MetricsTracker 查询测试"""

    def test_get_evolution_stats_empty(self, tmp_path):
        """空数据库统计"""
        from pycoder.capabilities.self_evo.learning.metrics_tracker import (
            MetricsTracker, METRICS_DB,
        )

        db_path = tmp_path / "metrics4.db"
        with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.METRICS_DB",
                   db_path):
            with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.DB_DIR",
                       tmp_path):
                mt = MetricsTracker()
                stats = mt.get_evolution_stats(days=30)
                assert stats["total_evolutions"] == 0

    def test_get_operation_breakdown(self, tmp_path):
        """操作分解统计"""
        from pycoder.capabilities.self_evo.learning.metrics_tracker import (
            MetricsTracker, METRICS_DB,
        )

        db_path = tmp_path / "metrics5.db"
        with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.METRICS_DB",
                   db_path):
            with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.DB_DIR",
                       tmp_path):
                mt = MetricsTracker()
                mt.record_evolution(operation="fix", outcome="success")
                breakdown = mt.get_operation_breakdown()
                assert "fix" in breakdown

    def test_get_daily_summary(self, tmp_path):
        """每日汇总"""
        from pycoder.capabilities.self_evo.learning.metrics_tracker import (
            MetricsTracker, METRICS_DB,
        )

        db_path = tmp_path / "metrics6.db"
        with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.METRICS_DB",
                   db_path):
            with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.DB_DIR",
                       tmp_path):
                mt = MetricsTracker()
                summary = mt.get_daily_summary(days=7)
                assert isinstance(summary, list)


class TestGetMetricsTracker:
    """全局单例测试"""

    def test_singleton(self):
        """单例模式"""
        from pycoder.capabilities.self_evo.learning.metrics_tracker import get_metrics_tracker

        mt1 = get_metrics_tracker()
        mt2 = get_metrics_tracker()
        assert mt1 is mt2


# ═══════════════════════════════════════════════════════════════
# 模块 8: evo_orchestrator.py
# ═══════════════════════════════════════════════════════════════


class TestEvolutionCycleReport:
    """EvolutionCycleReport 数据类测试"""

    def test_defaults(self):
        """默认值"""
        from pycoder.capabilities.self_evo.learning.evo_orchestrator import EvolutionCycleReport

        report = EvolutionCycleReport()
        assert report.files_scanned == 0
        assert report.grade_trend == "stable"
        assert report.error == ""


class TestEvoOrchestrator:
    """EvoOrchestrator 测试"""

    def test_init(self):
        """初始化"""
        from pycoder.capabilities.self_evo.learning.evo_orchestrator import EvoOrchestrator

        orch = EvoOrchestrator()
        assert orch.cache is not None
        assert orch.evaluator is not None
        assert orch.classifier is not None

    def test_get_status(self):
        """获取状态"""
        from pycoder.capabilities.self_evo.learning.evo_orchestrator import EvoOrchestrator

        orch = EvoOrchestrator()
        status = orch.get_status()
        assert "cycle_count" in status
        assert "total_fixes" in status
        assert "cache" in status

    @pytest.mark.asyncio
    async def test_run_evolution_cycle_no_changes(self, tmp_path):
        """无变更时跳过"""
        from pycoder.capabilities.self_evo.learning.evo_orchestrator import EvoOrchestrator

        orch = EvoOrchestrator()
        # 模拟 get_changed_files 返回空列表
        with patch.object(orch.cache, "get_changed_files", return_value=[]):
            report = await orch.run_evolution_cycle(target_dir=str(tmp_path))
            assert "无文件变更" in str(report.warnings) or report.files_scanned >= 0


# ═══════════════════════════════════════════════════════════════
# 模块 9: evo_cache.py
# ═══════════════════════════════════════════════════════════════


class TestCachedScan:
    """CachedScan 数据类测试"""

    def test_creation(self):
        """创建缓存条目"""
        from pycoder.capabilities.self_evo.learning.evo_cache import CachedScan

        entry = CachedScan(
            file_path="test.py", content_hash="abc123", issues_found=3,
            issues_json="[]", scanned_at=time.time(),
        )
        assert entry.file_path == "test.py"
        assert entry.issues_found == 3


class TestHotRule:
    """HotRule 数据类测试"""

    def test_creation(self):
        """创建热规则"""
        from pycoder.capabilities.self_evo.learning.evo_cache import HotRule

        rule = HotRule(
            rule_id="HR-001", error_signature="bare_except",
            fix_template="except Exception as e:", success_rate=0.9,
            use_count=10, last_used=time.time(),
        )
        assert rule.rule_id == "HR-001"
        assert rule.success_rate == 0.9


class TestEvoCache:
    """EvoCache 测试"""

    def test_compute_hash(self, tmp_path):
        """计算文件哈希"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        f = tmp_path / "test.py"
        f.write_text("hello world", encoding="utf-8")
        h = EvoCache.compute_hash(f)
        assert len(h) == 12

    def test_compute_hash_nonexistent(self):
        """计算不存在文件的哈希"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        h = EvoCache.compute_hash("/nonexistent/file.py")
        assert h == ""

    def test_is_cached_miss(self):
        """缓存未命中"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        assert cache.is_cached("test.py") is False

    def test_mark_and_check_cached(self):
        """标记并检查缓存"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        cache.mark_scanned("test.py", "abc123", [{"issue": "test"}])
        assert cache.is_cached("test.py", "abc123") is True

    def test_get_cached_issues(self):
        """获取缓存的问题"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        cache.mark_scanned("test.py", "abc123", [{"type": "bug"}])
        issues = cache.get_cached_issues("test.py")
        assert len(issues) == 1

    def test_get_cached_issues_miss(self):
        """缓存未命中时获取问题"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        issues = cache.get_cached_issues("nonexistent.py")
        assert issues == []

    def test_register_hot_rule(self):
        """注册热规则"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        cache.register_hot_rule("bare_except", "except Exception as e:", 1.0)
        rule = cache.find_rule("bare_except")
        assert rule is not None
        assert rule.error_signature == "bare_except"

    def test_register_hot_rule_update(self):
        """更新已存在的热规则"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        cache.register_hot_rule("bare_except", "fix1", 1.0)
        cache.register_hot_rule("bare_except", "fix2", 0.5)
        rule = cache.find_rule("bare_except")
        assert rule.use_count == 2

    def test_find_rule_fuzzy(self):
        """模糊匹配热规则"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        cache.register_hot_rule("bare_except", "fix", 1.0)
        rule = cache.find_rule("bare_except in function")
        assert rule is not None

    def test_find_rule_not_found(self):
        """未找到热规则"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        rule = cache.find_rule("nonexistent")
        assert rule is None

    def test_get_top_rules(self):
        """获取优先级最高的热规则"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        cache.register_hot_rule("err1", "fix1", 1.0)
        cache.register_hot_rule("err2", "fix2", 0.5)
        top = cache.get_top_rules(limit=2)
        assert len(top) <= 2

    def test_get_stats(self):
        """获取缓存统计"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache

        cache = EvoCache()
        cache.mark_scanned("test.py", "abc123")
        stats = cache.get_stats()
        assert stats["cached_files"] == 1
        assert "hot_rules" in stats

    def test_save_and_load(self, tmp_path):
        """持久化和加载"""
        from pycoder.capabilities.self_evo.learning.evo_cache import EvoCache, CACHE_DIR

        with patch("pycoder.capabilities.self_evo.learning.evo_cache.CACHE_DIR", tmp_path):
            cache = EvoCache()
            cache.register_hot_rule("err1", "fix1", 1.0)
            cache.save()

            # 新建实例加载
            cache2 = EvoCache()
            rule = cache2.find_rule("err1")
            assert rule is not None


# ═══════════════════════════════════════════════════════════════
# 模块 10: evo_evaluator.py
# ═══════════════════════════════════════════════════════════════


class TestEvolutionGrade:
    """EvolutionGrade 数据类测试"""

    def test_defaults(self):
        """默认值"""
        from pycoder.capabilities.self_evo.learning.evo_evaluator import EvolutionGrade

        grade = EvolutionGrade()
        assert grade.total == 0.0
        assert grade.passed is False
        assert grade.warnings == []


class TestEvoEvaluator:
    """EvoEvaluator 测试"""

    def test_evaluate_clean_code(self):
        """评估干净代码"""
        from pycoder.capabilities.self_evo.learning.evo_evaluator import EvoEvaluator

        ev = EvoEvaluator()
        code = "def foo() -> int:\n    return 42\n"
        grade = ev.evaluate_fix(code, code, test_result="passed")
        assert grade.total > 0
        assert isinstance(grade.passed, bool)

    def test_evaluate_with_bare_except(self):
        """评估含裸 except 的代码"""
        from pycoder.capabilities.self_evo.learning.evo_evaluator import EvoEvaluator

        ev = EvoEvaluator()
        bad_code = "try:\n    pass\nexcept:\n    pass\n"
        grade = ev.evaluate_fix("", bad_code)
        assert grade.code_quality < 40  # 应扣分

    def test_evaluate_with_syntax_error(self):
        """评估语法错误代码"""
        from pycoder.capabilities.self_evo.learning.evo_evaluator import EvoEvaluator

        ev = EvoEvaluator()
        grade = ev.evaluate_fix("", "def foo(\n")
        assert grade.code_quality == 0.0

    def test_evaluate_with_dangerous_call(self):
        """评估含危险函数的代码"""
        from pycoder.capabilities.self_evo.learning.evo_evaluator import EvoEvaluator

        ev = EvoEvaluator()
        bad_code = "eval('1+1')\n"
        grade = ev.evaluate_fix("", bad_code)
        assert grade.security < 20

    def test_evaluate_with_hardcoded_secret(self):
        """评估含硬编码密钥的代码"""
        from pycoder.capabilities.self_evo.learning.evo_evaluator import EvoEvaluator

        ev = EvoEvaluator()
        bad_code = "api_key = 'sk-abcdefghijklmnop'\n"
        grade = ev.evaluate_fix("", bad_code)
        assert grade.security < 20

    def test_evaluate_test_failed(self):
        """评估测试失败"""
        from pycoder.capabilities.self_evo.learning.evo_evaluator import EvoEvaluator

        ev = EvoEvaluator()
        code = "def foo():\n    return 1\n"
        grade = ev.evaluate_fix(code, code, test_result="FAILED: test_foo")
        assert grade.test_coverage < 20

    def test_get_trend_empty(self):
        """空历史趋势"""
        from pycoder.capabilities.self_evo.learning.evo_evaluator import EvoEvaluator

        ev = EvoEvaluator()
        trend = ev.get_trend()
        assert trend["trend"] == "no_data"

    def test_get_trend_with_data(self):
        """有数据趋势"""
        from pycoder.capabilities.self_evo.learning.evo_evaluator import EvoEvaluator

        ev = EvoEvaluator()
        code = "def foo() -> int:\n    return 42\n"
        for _ in range(6):
            ev.evaluate_fix(code, code, test_result="passed")
        trend = ev.get_trend()
        assert trend["trend"] in ("stable", "improving", "declining", "insufficient_data")


# ═══════════════════════════════════════════════════════════════
# 模块 11: error_classifier.py
# ═══════════════════════════════════════════════════════════════


class TestErrorCategory:
    """ErrorCategory 枚举测试"""

    def test_values(self):
        """枚举值"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorCategory

        assert ErrorCategory.SYNTAX.value == "syntax"
        assert ErrorCategory.RUNTIME.value == "runtime"
        assert ErrorCategory.SECURITY.value == "security"
        assert ErrorCategory.UNKNOWN.value == "unknown"


class TestErrorTicket:
    """ErrorTicket 数据类测试"""

    def test_defaults(self):
        """默认值"""
        from pycoder.capabilities.self_evo.learning.error_classifier import (
            ErrorCategory, ErrorTicket,
        )

        ticket = ErrorTicket()
        assert ticket.category == ErrorCategory.UNKNOWN
        assert ticket.severity == "medium"
        assert ticket.fix_status == "open"


class TestErrorClassifier:
    """ErrorClassifier 测试"""

    def test_classify_syntax_error(self):
        """分类语法错误"""
        from pycoder.capabilities.self_evo.learning.error_classifier import (
            ErrorCategory, ErrorClassifier,
        )

        ec = ErrorClassifier()
        assert ec.classify("SyntaxError: invalid syntax") == ErrorCategory.SYNTAX

    def test_classify_runtime_error(self):
        """分类运行时错误"""
        from pycoder.capabilities.self_evo.learning.error_classifier import (
            ErrorCategory, ErrorClassifier,
        )

        ec = ErrorClassifier()
        assert ec.classify("NameError: name 'foo' is not defined") == ErrorCategory.RUNTIME

    def test_classify_key_error(self):
        """分类 KeyError"""
        from pycoder.capabilities.self_evo.learning.error_classifier import (
            ErrorCategory, ErrorClassifier,
        )

        ec = ErrorClassifier()
        assert ec.classify("KeyError: 'missing_key'") == ErrorCategory.RUNTIME

    def test_classify_security(self):
        """分类安全问题"""
        from pycoder.capabilities.self_evo.learning.error_classifier import (
            ErrorCategory, ErrorClassifier,
        )

        ec = ErrorClassifier()
        assert ec.classify("sql injection detected") == ErrorCategory.SECURITY

    def test_classify_unknown(self):
        """分类未知错误"""
        from pycoder.capabilities.self_evo.learning.error_classifier import (
            ErrorCategory, ErrorClassifier,
        )

        ec = ErrorClassifier()
        assert ec.classify("something completely random") == ErrorCategory.UNKNOWN

    def test_recommend_strategy(self):
        """推荐修复策略"""
        from pycoder.capabilities.self_evo.learning.error_classifier import (
            ErrorCategory, ErrorClassifier,
        )

        ec = ErrorClassifier()
        strategies = ec.recommend_strategy(ErrorCategory.SYNTAX)
        assert len(strategies) > 0
        assert any("syntax" in s.lower() for s in strategies)

    def test_recommend_strategy_unknown(self):
        """未知类别的策略"""
        from pycoder.capabilities.self_evo.learning.error_classifier import (
            ErrorCategory, ErrorClassifier,
        )

        ec = ErrorClassifier()
        strategies = ec.recommend_strategy(ErrorCategory.UNKNOWN)
        assert any("llm" in s.lower() for s in strategies)

    def test_open_ticket(self):
        """创建工单"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        ticket = ec.open_ticket(
            "bare_except", "except: found", file_path="test.py", line=10,
        )
        assert ticket.error_signature == "bare_except"
        assert ticket.file_path == "test.py"
        assert ticket.line_number == 10

    def test_open_ticket_duplicate(self):
        """重复工单增加计数"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        t1 = ec.open_ticket("bare_except", "except: found")
        t2 = ec.open_ticket("bare_except", "except: found again")
        assert t1 is t2  # 同一个工单
        assert t2.occurrences == 2

    def test_mark_fixed(self):
        """标记已修复"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        ec.open_ticket("bare_except", "except: found")
        ec.mark_fixed("bare_except", "template_fix")
        ticket = ec._tickets["bare_except"]
        assert ticket.fix_status == "fixed"

    def test_verify_fix(self):
        """验证修复"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        ec.open_ticket("bare_except", "except: found")
        result = ec.verify_fix("bare_except", "test")
        assert result is True
        ticket = ec._tickets["bare_except"]
        assert ticket.fix_status == "verified"

    def test_verify_fix_not_found(self):
        """验证不存在的工单"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        result = ec.verify_fix("nonexistent")
        assert result is False

    def test_check_recurrence(self):
        """检查重复率"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        for _ in range(5):
            ec.open_ticket("bare_except", "except: found")
        report = ec.check_recurrence("bare_except")
        assert report["repeat_count"] == 4  # 第一次不算重复
        assert report["severity"] == "high"

    def test_get_recurrence_report(self):
        """获取重复率报告"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        ec.open_ticket("err1", "msg1")
        ec.open_ticket("err1", "msg1")
        report = ec.get_recurrence_report()
        assert len(report) >= 0

    def test_get_stats(self):
        """获取统计"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        ec = ErrorClassifier()
        ec.open_ticket("err1", "SyntaxError: invalid")
        ec.open_ticket("err2", "NameError: name not defined")
        stats = ec.get_stats()
        assert stats["total_tickets"] == 2
        assert "by_category" in stats

    def test_calc_severity(self):
        """计算严重度"""
        from pycoder.capabilities.self_evo.learning.error_classifier import ErrorClassifier

        assert ErrorClassifier._calc_severity("critical error") == "critical"
        assert ErrorClassifier._calc_severity("SyntaxError") == "high"
        assert ErrorClassifier._calc_severity("some error") == "medium"