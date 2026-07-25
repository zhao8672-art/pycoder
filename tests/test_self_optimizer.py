"""P3-A: self_optimizer 模块单元测试

覆盖:
  - SelfHealer: 静态扫描/AI修复解析/安全应用/学习记录
  - UsageAnalyzer: 优化建议生成/会话错误进化分析
  - PromptOptimizer: 提示词检查/批量优化/报告生成
  - SelfOptimizer: 统一入口/完整周期/Markdown 报告

目标: 将 self_optimizer.py 的测试覆盖率从 0% 提升至 60%+
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pycoder.capabilities.self_evo.learning.self_optimizer import (
    HealFix,
    HealReport,
    PromptOptimization,
    PromptOptimizer,
    SelfHealer,
    SelfOptimizer,
    UsageAnalyzer,
    UsageReport,
    get_self_optimizer,
)


# ════════════════════════════════════════════════════════════
# 数据模型测试
# ════════════════════════════════════════════════════════════


class TestHealFixDataclass:
    """HealFix 数据模型"""

    def test_default_values(self) -> None:
        fix = HealFix(file="a.py", reason="bug", severity="high")
        assert fix.file == "a.py"
        assert fix.reason == "bug"
        assert fix.severity == "high"
        assert fix.old_code == ""
        assert fix.new_code == ""
        assert fix.applied is False
        assert fix.test_passed is False

    def test_custom_values(self) -> None:
        fix = HealFix(
            file="b.py",
            reason="syntax",
            severity="critical",
            old_code="old",
            new_code="new",
            applied=True,
            test_passed=True,
        )
        assert fix.new_code == "new"
        assert fix.applied is True
        assert fix.test_passed is True


class TestHealReportDataclass:
    """HealReport 数据模型"""

    def test_default_values(self) -> None:
        report = HealReport()
        assert report.task_id == ""
        assert report.files_scanned == 0
        assert report.issues_found == 0
        assert report.fixes_applied == 0
        assert report.fixes_successful == 0
        assert report.test_passed is False
        assert report.fixes == []
        assert report.error == ""

    def test_task_id_set(self) -> None:
        report = HealReport(task_id="HEAL-123")
        assert report.task_id == "HEAL-123"


class TestUsageReportDataclass:
    """UsageReport 数据模型"""

    def test_default_values(self) -> None:
        report = UsageReport()
        assert report.total_sessions == 0
        assert report.total_messages == 0
        assert report.top_topics == []
        assert report.model_distribution == {}
        assert report.optimization_hints == []


class TestPromptOptimizationDataclass:
    """PromptOptimization 数据模型"""

    def test_default_values(self) -> None:
        opt = PromptOptimization()
        assert opt.agent_id == ""
        assert opt.original_lines == 0
        assert opt.optimized_lines == 0
        assert opt.changes == []


# ════════════════════════════════════════════════════════════
# SelfHealer 测试
# ════════════════════════════════════════════════════════════


class TestSelfHealerInit:
    """初始化"""

    def test_init_with_default_root(self) -> None:
        healer = SelfHealer()
        assert healer._root is not None
        assert healer._backup_dir.name == ".pycoder_backups"

    def test_init_with_custom_root(self, tmp_path: Path) -> None:
        healer = SelfHealer(project_root=tmp_path)
        assert healer._root == tmp_path

    def test_protect_list_contains_self_optimizer(self) -> None:
        healer = SelfHealer()
        assert "self_optimizer.py" in healer._protect_list
        assert "self_evolution.py" in healer._protect_list


class TestSelfHealerStaticScan:
    """静态扫描"""

    def test_scan_skips_protected_files(self, tmp_path: Path) -> None:
        """保护列表中的文件应被跳过"""
        # 创建一个 self_optimizer.py 文件
        (tmp_path / "self_optimizer.py").write_text(
            "api_key = 'hardcoded_secret_12345'\n", encoding="utf-8"
        )
        healer = SelfHealer(project_root=tmp_path)
        # target_dir 为空字符串，扫描整个根目录
        issues = healer._static_scan("")
        # self_optimizer.py 应被跳过
        assert all("self_optimizer.py" not in i.file for i in issues)

    def test_scan_skips_pycache(self, tmp_path: Path) -> None:
        """__pycache__ 应被跳过"""
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "mod.cpython-314.pyc").write_bytes(b"\x00\x01")

        healer = SelfHealer(project_root=tmp_path)
        issues = healer._static_scan("")
        assert all("__pycache__" not in i.file for i in issues)

    def test_scan_detects_bom(self, tmp_path: Path) -> None:
        """检测 BOM 头"""
        bad_file = tmp_path / "bom.py"
        bad_file.write_bytes(b"\xef\xbb\xbfx = 1\n")

        healer = SelfHealer(project_root=tmp_path)
        issues = healer._static_scan("")
        bom_issues = [i for i in issues if "BOM" in i.reason]
        assert len(bom_issues) >= 1
        assert bom_issues[0].severity == "medium"

    def test_scan_detects_syntax_error(self, tmp_path: Path) -> None:
        """检测语法错误"""
        (tmp_path / "broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")

        healer = SelfHealer(project_root=tmp_path)
        issues = healer._static_scan("")
        syntax_issues = [i for i in issues if "语法错误" in i.reason]
        assert len(syntax_issues) >= 1
        assert syntax_issues[0].severity == "critical"

    def test_scan_detects_hardcoded_key(self, tmp_path: Path) -> None:
        """检测硬编码密钥"""
        (tmp_path / "auth.py").write_text(
            'api_key = "sk-1234567890abcdef"\n',
            encoding="utf-8",
        )

        healer = SelfHealer(project_root=tmp_path)
        issues = healer._static_scan("")
        key_issues = [i for i in issues if "硬编码密钥" in i.reason]
        assert len(key_issues) >= 1
        assert key_issues[0].severity == "high"

    def test_scan_detects_mixed_indent(self, tmp_path: Path) -> None:
        """检测混合缩进"""
        (tmp_path / "mixed.py").write_text(
            "def f():\n\tpass\n    x = 1\n", encoding="utf-8"
        )

        healer = SelfHealer(project_root=tmp_path)
        issues = healer._static_scan("")
        indent_issues = [i for i in issues if "混合缩进" in i.reason]
        assert len(indent_issues) >= 1

    def test_scan_clean_file_no_issues(self, tmp_path: Path) -> None:
        """干净文件无问题"""
        (tmp_path / "clean.py").write_text(
            "def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8"
        )

        healer = SelfHealer(project_root=tmp_path)
        issues = healer._static_scan("")
        assert issues == []

    def test_scan_nonexistent_dir_returns_empty(self, tmp_path: Path) -> None:
        """不存在的目录返回空列表"""
        healer = SelfHealer(project_root=tmp_path)
        issues = healer._static_scan("nonexistent_subdir")
        assert issues == []


class TestSelfHealerParseAiFixes:
    """AI 修复结果解析"""

    def test_parse_valid_blocks(self) -> None:
        healer = SelfHealer()
        result = """一些前置文本
[FIX:pycoder/foo.py]
```python
def foo():
    return "fixed"
```
[END:FIX]
后置文本
"""
        issues = [HealFix(file="pycoder/foo.py", reason="bug", severity="high")]
        fixes = healer._parse_ai_fixes(result, issues)

        assert len(fixes) == 1
        assert fixes[0].file == "pycoder/foo.py"
        assert "def foo" in fixes[0].new_code
        assert fixes[0].reason == "bug"

    def test_parse_multiple_blocks(self) -> None:
        healer = SelfHealer()
        result = """[FIX:a.py]
```python
def func_a():
    return 1
```
[END:FIX]
[FIX:b.py]
```python
def func_b():
    return 2
```
[END:FIX]
"""
        issues = [
            HealFix(file="a.py", reason="ra", severity="high"),
            HealFix(file="b.py", reason="rb", severity="low"),
        ]
        fixes = healer._parse_ai_fixes(result, issues)
        assert len(fixes) == 2

    def test_parse_empty_result(self) -> None:
        healer = SelfHealer()
        issues = [HealFix(file="a.py", reason="r", severity="high")]
        fixes = healer._parse_ai_fixes("", issues)
        assert fixes == []

    def test_parse_short_code_rejected(self) -> None:
        """过短的代码块被拒绝（< 20 字符）"""
        healer = SelfHealer()
        result = """[FIX:a.py]
```
short
```
[END:FIX]
"""
        issues = [HealFix(file="a.py", reason="r", severity="high")]
        fixes = healer._parse_ai_fixes(result, issues)
        assert fixes == []

    def test_parse_unmatched_issue_falls_back_to_first(self) -> None:
        """未匹配到 issue 时回退到第一个"""
        healer = SelfHealer()
        result = """[FIX:unknown.py]
```python
def new_code_here():
    pass
```
[END:FIX]
"""
        issues = [HealFix(file="other.py", reason="r", severity="high")]
        fixes = healer._parse_ai_fixes(result, issues)
        assert len(fixes) == 1
        assert fixes[0].file == "unknown.py"

    def test_parse_empty_issues_returns_empty(self) -> None:
        healer = SelfHealer()
        result = """[FIX:a.py]
```python
x = 1
```
[END:FIX]
"""
        fixes = healer._parse_ai_fixes(result, [])
        assert fixes == []


class TestSelfHealerApplyFixSafe:
    """安全应用修复"""

    def test_apply_nonexistent_file_returns_false(self, tmp_path: Path) -> None:
        healer = SelfHealer(project_root=tmp_path)
        fix = HealFix(file="missing.py", reason="r", severity="low", new_code="x = 1\n")
        assert healer._apply_fix_safe(fix) is False

    def test_apply_empty_code_returns_false(self, tmp_path: Path) -> None:
        (tmp_path / "target.py").write_text("x = 1\n", encoding="utf-8")
        healer = SelfHealer(project_root=tmp_path)
        fix = HealFix(file="target.py", reason="r", severity="low", new_code="")
        assert healer._apply_fix_safe(fix) is False

    def test_apply_short_code_returns_false(self, tmp_path: Path) -> None:
        (tmp_path / "target.py").write_text("x = 1\n", encoding="utf-8")
        healer = SelfHealer(project_root=tmp_path)
        fix = HealFix(file="target.py", reason="r", severity="low", new_code="short")
        assert healer._apply_fix_safe(fix) is False

    def test_apply_placeholder_code_returns_false(self, tmp_path: Path) -> None:
        (tmp_path / "target.py").write_text("x = 1\n", encoding="utf-8")
        healer = SelfHealer(project_root=tmp_path)
        fix = HealFix(
            file="target.py",
            reason="r",
            severity="low",
            new_code="# ... 代码保持不变\n# placeholder\n",
        )
        assert healer._apply_fix_safe(fix) is False

    def test_apply_valid_code_writes_and_returns_true(self, tmp_path: Path) -> None:
        (tmp_path / "target.py").write_text("x = 1\n", encoding="utf-8")
        healer = SelfHealer(project_root=tmp_path)
        new_code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        fix = HealFix(file="target.py", reason="r", severity="low", new_code=new_code)

        result = healer._apply_fix_safe(fix)
        assert result is True
        # 验证写入
        assert (tmp_path / "target.py").read_text(encoding="utf-8") == new_code
        # 验证备份
        backups = list((tmp_path / ".pycoder_backups").glob("target.py.*.bak"))
        assert len(backups) >= 1

    def test_apply_syntax_error_rolls_back(self, tmp_path: Path) -> None:
        original = "x = 1\n"
        (tmp_path / "target.py").write_text(original, encoding="utf-8")
        healer = SelfHealer(project_root=tmp_path)
        fix = HealFix(
            file="target.py",
            reason="r",
            severity="low",
            new_code="def broken(:\n    pass\n",
        )

        result = healer._apply_fix_safe(fix)
        assert result is False
        # 验证回滚
        assert (tmp_path / "target.py").read_text(encoding="utf-8") == original


class TestSelfHealerAutoHeal:
    """auto_heal 主流程"""

    @pytest.mark.asyncio
    async def test_auto_heal_clean_dir_no_issues(self, tmp_path: Path) -> None:
        """干净目录无问题"""
        (tmp_path / "clean.py").write_text(
            "def add(a: int, b: int) -> int:\n    return a + b\n",
            encoding="utf-8",
        )
        healer = SelfHealer(project_root=tmp_path)

        report = await healer.auto_heal(target_dir="", dry_run=True)
        assert isinstance(report, HealReport)
        assert report.task_id.startswith("HEAL-")
        assert report.error == ""
        assert report.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_auto_heal_dry_run_no_modifications(self, tmp_path: Path) -> None:
        """dry_run 模式不修改文件"""
        original = "def broken(:\n    pass\n"
        (tmp_path / "bad.py").write_text(original, encoding="utf-8")
        healer = SelfHealer(project_root=tmp_path)

        report = await healer.auto_heal(target_dir="", dry_run=True)
        assert report.issues_found >= 1
        # dry_run 不应修改文件
        assert (tmp_path / "bad.py").read_text(encoding="utf-8") == original

    @pytest.mark.asyncio
    async def test_auto_heal_nonexistent_dir_returns_empty(self, tmp_path: Path) -> None:
        healer = SelfHealer(project_root=tmp_path)
        report = await healer.auto_heal(target_dir="nonexistent", dry_run=True)
        assert report.issues_found == 0


class TestSelfHealerMatchKnowledge:
    """知识库匹配"""

    def test_match_knowledge_empty_issues_returns_empty(self, tmp_path: Path) -> None:
        """空 issues 返回空列表（不调用知识库）"""
        healer = SelfHealer(project_root=tmp_path)
        result = healer._match_knowledge([])
        assert result == []

    def test_match_knowledge_normal_flow(self, tmp_path: Path) -> None:
        """正常流程：mock 知识库返回 None，结果应为空"""
        healer = SelfHealer(project_root=tmp_path)
        issues = [HealFix(file="a.py", reason="bug", severity="high")]

        # mock knowledge_base 模块，让 get_knowledge_base 返回 mock 对象
        mock_kb = MagicMock()
        mock_kb.suggest_fix.return_value = None  # 无匹配模式

        with patch(
            "pycoder.capabilities.self_evo.learning.knowledge_base.get_knowledge_base",
            return_value=mock_kb,
        ):
            result = healer._match_knowledge(issues)
        assert isinstance(result, list)
        assert result == []


# ════════════════════════════════════════════════════════════
# UsageAnalyzer 测试
# ════════════════════════════════════════════════════════════


class TestUsageAnalyzerGenerateHints:
    """优化建议生成"""

    def test_generate_hints_low_sessions(self) -> None:
        analyzer = UsageAnalyzer()
        report = UsageReport(total_sessions=2)

        analyzer._generate_hints(report)

        assert any("会话数较少" in h for h in report.optimization_hints)

    def test_generate_hints_high_ai_ratio(self) -> None:
        analyzer = UsageAnalyzer()
        report = UsageReport(
            total_sessions=10,
            user_messages=10,
            ai_messages=50,  # 比例 5:1，>3
        )

        analyzer._generate_hints(report)

        assert any("AI/用户消息比" in h for h in report.optimization_hints)

    def test_generate_hints_top_error(self) -> None:
        analyzer = UsageAnalyzer()
        report = UsageReport(
            top_error_types=[("SyntaxError", 15)],
        )

        analyzer._generate_hints(report)

        assert any("最高频错误" in h and "SyntaxError" in h for h in report.optimization_hints)

    def test_generate_hints_model_distribution_low_usage(self) -> None:
        analyzer = UsageAnalyzer()
        report = UsageReport(
            model_distribution={"gpt-4": 100, "cheap-model": 5},  # 5/105 < 10%
        )

        analyzer._generate_hints(report)

        assert any("cheap-model" in h and "使用率" in h for h in report.optimization_hints)


class TestUsageAnalyzerAnalyze:
    """综合分析"""

    def test_analyze_handles_session_store_error(self) -> None:
        """会话存储异常时不崩溃"""
        analyzer = UsageAnalyzer()

        # 模拟 session_store 导入失败
        with patch.dict(
            "sys.modules",
            {"pycoder.server.session_store": None},
        ):
            report = analyzer.analyze(days=7)

        assert isinstance(report, UsageReport)
        # 异常时仍返回空 report
        assert report.total_sessions == 0


# ════════════════════════════════════════════════════════════
# PromptOptimizer 测试
# ════════════════════════════════════════════════════════════


class TestPromptOptimizer:
    """提示词优化器"""

    def test_optimize_agent_prompt_returns_result(self) -> None:
        opt = PromptOptimizer()
        result = opt.optimize_agent_prompt("nonexistent_agent")
        assert isinstance(result, PromptOptimization)
        assert result.agent_id == "nonexistent_agent"

    def test_optimize_all_agents_returns_5(self) -> None:
        opt = PromptOptimizer()
        results = opt.optimize_all_agents()
        assert len(results) == 5
        agent_ids = {r.agent_id for r in results}
        assert agent_ids == {"pm", "architect", "developer", "qa", "devops"}

    def test_generate_optimization_report_returns_string(self) -> None:
        opt = PromptOptimizer()
        report = opt.generate_optimization_report()
        assert isinstance(report, str)
        assert "Agent 提示词优化报告" in report


# ════════════════════════════════════════════════════════════
# SelfOptimizer 统一入口测试
# ════════════════════════════════════════════════════════════


class TestSelfOptimizer:
    """统一入口"""

    def test_init_creates_components(self) -> None:
        opt = SelfOptimizer()
        assert opt.healer is not None
        assert opt.analyzer is not None
        assert opt.prompt_opt is not None

    def test_optimize_prompts_returns_list(self) -> None:
        opt = SelfOptimizer()
        results = opt.optimize_prompts()
        assert isinstance(results, list)
        assert len(results) == 5

    def test_full_optimization_cycle_returns_dict(self) -> None:
        opt = SelfOptimizer()
        result = opt.full_optimization_cycle()

        assert isinstance(result, dict)
        assert "usage" in result
        assert "prompts" in result
        assert "heal" in result
        assert "recommendations" in result

    def test_generate_optimization_markdown_returns_string(self) -> None:
        opt = SelfOptimizer()
        md = opt.generate_optimization_markdown()

        assert isinstance(md, str)
        assert "PyCoder 自优化报告" in md
        assert "使用分析" in md


# ════════════════════════════════════════════════════════════
# 全局单例测试
# ════════════════════════════════════════════════════════════


class TestGetSelfOptimizer:
    """全局单例"""

    def test_returns_instance(self) -> None:
        opt = get_self_optimizer()
        assert isinstance(opt, SelfOptimizer)

    def test_returns_same_instance(self) -> None:
        opt1 = get_self_optimizer()
        opt2 = get_self_optimizer()
        assert opt1 is opt2
