"""SelfOptimizer 覆盖率补充测试

针对 pycoder/server/learning/self_optimizer.py 中未被覆盖的分支:
  - SelfHealer: auto_heal 全流程、_static_scan 各检测项、_match_knowledge、
    _ai_heal（mock ChatBridge）、_parse_ai_fixes、_apply_fix_safe 备份/回滚、
    _run_tests、_record_heal_result
  - UsageAnalyzer: _analyze_sessions（话题/模型分布）、_analyze_errors、
    _analyze_evolution、_generate_hints 各分支
  - PromptOptimizer: optimize_agent_prompt 各分支（短提示词、缺失章节、模型路由）
  - SelfOptimizer: full_optimization_cycle 推荐、generate_optimization_markdown
  - get_self_optimizer 单例
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.server.learning.self_optimizer import (
    SelfHealer,
    UsageAnalyzer,
    PromptOptimizer,
    SelfOptimizer,
    HealFix,
    HealReport,
    UsageReport,
    PromptOptimization,
    get_self_optimizer,
)


# ══════════════════════════════════════════════════════════
# 测试桩
# ══════════════════════════════════════════════════════════


@dataclass
class StubPattern:
    """模拟 KB.suggest_fix 返回的 ErrorPattern"""
    fix_template: str = ""
    error_type: str = ""
    confidence: float = 0.0


@dataclass
class StubErrorPattern:
    """模拟 ErrorPattern（用于 UsageAnalyzer._analyze_errors）"""
    error_type: str = ""
    success_count: int = 0
    fail_count: int = 0


@dataclass
class StubMessage:
    """模拟 session_store.Message"""
    role: str = "user"
    content: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class StubSession:
    """模拟 session_store.Session"""
    id: str = "sess-1"


class StubSessionStore:
    """模拟 SessionStore"""

    def __init__(self, sessions=None, messages_map=None):
        self._sessions = sessions or []
        self._messages_map = messages_map or {}

    def list_sessions(self, limit: int = 50, offset: int = 0):
        return self._sessions[:limit]

    def get_messages(self, session_id: str, limit: int = 200, offset: int = 0):
        return self._messages_map.get(session_id, [])[:limit]


# ══════════════════════════════════════════════════════════
# SelfHealer._static_scan — 各检测项
# ══════════════════════════════════════════════════════════


class TestStaticScan:
    @pytest.fixture
    def project_root(self, tmp_path: Path) -> Path:
        """构造一个虚拟项目根，src 目录下放置测试用 .py 文件"""
        src = tmp_path / "src"
        src.mkdir()
        return tmp_path

    def test_scans_clean_files_no_issues(self, project_root: Path):
        """干净文件无问题"""
        (project_root / "src" / "clean.py").write_text(
            "import os\n\n\ndef hello():\n    return 'world'\n",
            encoding="utf-8",
        )
        healer = SelfHealer(project_root=project_root)
        issues = healer._static_scan("src")
        assert issues == []

    def test_detects_bom(self, project_root: Path):
        """检测 BOM 头"""
        (project_root / "src" / "bom.py").write_bytes(
            b"\xef\xbb\xbfprint('hello')\n"
        )
        healer = SelfHealer(project_root=project_root)
        issues = healer._static_scan("src")
        bom_issues = [i for i in issues if "BOM" in i.reason]
        assert len(bom_issues) == 1
        assert bom_issues[0].severity == "medium"

    def test_detects_mixed_indent(self, project_root: Path):
        """检测 Tab + 空格混合缩进"""
        (project_root / "src" / "mixed.py").write_text(
            "def f():\n\treturn 1\n"
            "def g():\n    return 2\n",
            encoding="utf-8",
        )
        healer = SelfHealer(project_root=project_root)
        issues = healer._static_scan("src")
        mixed = [i for i in issues if "混合缩进" in i.reason]
        assert len(mixed) == 1
        assert mixed[0].severity == "low"

    def test_detects_syntax_error(self, project_root: Path):
        """检测语法错误"""
        (project_root / "src" / "bad.py").write_text(
            "def f(\n", encoding="utf-8",
        )
        healer = SelfHealer(project_root=project_root)
        issues = healer._static_scan("src")
        syntax = [i for i in issues if "语法错误" in i.reason]
        assert len(syntax) == 1
        assert syntax[0].severity == "critical"

    def test_detects_too_many_long_lines(self, project_root: Path):
        """超过 20 行超过 120 字符 → 报告"""
        long_line = "x = " + "a" * 130 + "\n"
        (project_root / "src" / "long.py").write_text(long_line * 25, encoding="utf-8")
        healer = SelfHealer(project_root=project_root)
        issues = healer._static_scan("src")
        long_issues = [i for i in issues if "120" in i.reason]
        assert len(long_issues) == 1

    def test_few_long_lines_not_reported(self, project_root: Path):
        """少于 20 行超长 → 不报告"""
        long_line = "x = " + "a" * 130 + "\n"
        (project_root / "src" / "ok_long.py").write_text(long_line * 5, encoding="utf-8")
        healer = SelfHealer(project_root=project_root)
        issues = healer._static_scan("src")
        long_issues = [i for i in issues if "120" in i.reason]
        assert long_issues == []

    def test_detects_hardcoded_api_key(self, project_root: Path):
        """检测硬编码 API key"""
        (project_root / "src" / "secret.py").write_text(
            'api_key = "sk-abcdefgh1234567890"\n',
            encoding="utf-8",
        )
        healer = SelfHealer(project_root=project_root)
        issues = healer._static_scan("src")
        key_issues = [i for i in issues if "硬编码密钥" in i.reason]
        assert len(key_issues) == 1
        assert key_issues[0].severity == "high"

    def test_ignores_commented_api_key(self, project_root: Path):
        """注释中的 key 模式不被报告"""
        (project_root / "src" / "commented.py").write_text(
            '# api_key = "sk-abcdefgh1234567890"\n',
            encoding="utf-8",
        )
        healer = SelfHealer(project_root=project_root)
        issues = healer._static_scan("src")
        key_issues = [i for i in issues if "硬编码密钥" in i.reason]
        assert key_issues == []

    def test_skips_pycache_files(self, project_root: Path):
        """__pycache__ 目录被跳过"""
        cache_dir = project_root / "src" / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "mod.cpython-314.py").write_text(
            "def f(\n", encoding="utf-8",  # 语法错误
        )
        healer = SelfHealer(project_root=project_root)
        issues = healer._static_scan("src")
        assert all("__pycache__" not in i.file for i in issues)

    def test_skips_protected_files(self, project_root: Path):
        """protect_list 中的文件被跳过"""
        (project_root / "src" / "self_optimizer.py").write_text(
            "def f(\n", encoding="utf-8",  # 语法错误
        )
        healer = SelfHealer(project_root=project_root)
        issues = healer._static_scan("src")
        assert all("self_optimizer" not in i.file for i in issues)

    def test_handles_unreadable_file(self, project_root: Path):
        """无法读取的文件被跳过，不抛异常"""
        # 写入非 UTF-8 字节
        (project_root / "src" / "binary.py").write_bytes(b"\xff\xfe\x00bad")
        healer = SelfHealer(project_root=project_root)
        # 不应抛异常
        issues = healer._static_scan("src")
        # 二进制文件可能解析为问题或被跳过
        assert isinstance(issues, list)

    def test_target_dir_empty_uses_root(self, project_root: Path):
        """target_dir 为空字符串时扫描根目录"""
        (project_root / "root.py").write_text("def f(\n", encoding="utf-8")
        healer = SelfHealer(project_root=project_root)
        issues = healer._static_scan("")
        assert any("root.py" in i.file for i in issues)


# ══════════════════════════════════════════════════════════
# SelfHealer._match_knowledge
# ══════════════════════════════════════════════════════════


class TestMatchKnowledge:
    def test_returns_fixes_from_kb(self, tmp_path: Path):
        healer = SelfHealer(project_root=tmp_path)
        issues = [
            HealFix(file="a.py", reason="语法错误: bad", severity="critical"),
            HealFix(file="b.py", reason="BOM", severity="medium"),
        ]
        # mock knowledge_base — 使用 self_optimizer 模块内的导入路径
        with patch("pycoder.capabilities.self_evo.learning.knowledge_base.get_knowledge_base") as mock_get:
            kb = MagicMock()
            kb.suggest_fix.return_value = StubPattern(
                fix_template="import os\nimport sys\n",
                error_type="SyntaxError",
                confidence=0.8,
            )
            mock_get.return_value = kb
            fixes = healer._match_knowledge(issues)
        assert len(fixes) == 2
        assert fixes[0].file == "a.py"
        assert "import os" in fixes[0].new_code

    def test_filters_low_confidence_patterns(self, tmp_path: Path):
        """confidence < 0.5 的模式被过滤"""
        healer = SelfHealer(project_root=tmp_path)
        issues = [HealFix(file="a.py", reason="err", severity="high")]
        with patch("pycoder.capabilities.self_evo.learning.knowledge_base.get_knowledge_base") as mock_get:
            kb = MagicMock()
            kb.suggest_fix.return_value = StubPattern(
                fix_template="", confidence=0.3,
            )
            mock_get.return_value = kb
            fixes = healer._match_knowledge(issues)
        # fix_template 为空 → 不返回
        assert fixes == []

    def test_dedupes_by_file(self, tmp_path: Path):
        """同一文件的多个问题只返回一个修复"""
        healer = SelfHealer(project_root=tmp_path)
        issues = [
            HealFix(file="a.py", reason="err1", severity="high"),
            HealFix(file="a.py", reason="err2", severity="medium"),
            HealFix(file="b.py", reason="err3", severity="low"),
        ]
        with patch("pycoder.capabilities.self_evo.learning.knowledge_base.get_knowledge_base") as mock_get:
            kb = MagicMock()
            kb.suggest_fix.return_value = StubPattern(
                fix_template="some fix code here", confidence=0.8,
            )
            mock_get.return_value = kb
            fixes = healer._match_knowledge(issues)
        # a.py 只出现一次，b.py 一次 → 2 个修复
        files = {f.file for f in fixes}
        assert files == {"a.py", "b.py"}

    def test_kb_exception_returns_empty(self, tmp_path: Path):
        """KB 抛 OSError 时返回空列表（caught by except 分支）"""
        healer = SelfHealer(project_root=tmp_path)
        issues = [HealFix(file="a.py", reason="err", severity="high")]
        with patch("pycoder.capabilities.self_evo.learning.knowledge_base.get_knowledge_base") as mock_get:
            mock_get.side_effect = OSError("kb down")
            fixes = healer._match_knowledge(issues)
        assert fixes == []

    def test_limits_to_first_10_issues(self, tmp_path: Path):
        """只处理前 10 个问题"""
        healer = SelfHealer(project_root=tmp_path)
        issues = [HealFix(file=f"file{i}.py", reason="err", severity="low") for i in range(20)]
        with patch("pycoder.capabilities.self_evo.learning.knowledge_base.get_knowledge_base") as mock_get:
            kb = MagicMock()
            kb.suggest_fix.return_value = StubPattern(
                fix_template="some fix code here", confidence=0.8,
            )
            mock_get.return_value = kb
            fixes = healer._match_knowledge(issues)
        # 最多 10 个（issues[:10]）
        assert len(fixes) <= 10


# ══════════════════════════════════════════════════════════
# SelfHealer._parse_ai_fixes
# ══════════════════════════════════════════════════════════


class TestParseAiFixes:
    def test_parses_valid_blocks(self, tmp_path: Path):
        healer = SelfHealer(project_root=tmp_path)
        issues = [
            HealFix(file="a.py", reason="bug", severity="high"),
            HealFix(file="b.py", reason="bug2", severity="medium"),
        ]
        result = """[FIX:a.py]
```python
import os
import sys
def main():
    pass
```
[END:FIX]

[FIX:b.py]
```python
def helper():
    return None
```
[END:FIX]"""
        fixes = healer._parse_ai_fixes(result, issues)
        assert len(fixes) == 2
        assert fixes[0].file == "a.py"
        assert "import os" in fixes[0].new_code

    def test_skips_short_code(self, tmp_path: Path):
        """长度 <= 20 的修复被跳过"""
        healer = SelfHealer(project_root=tmp_path)
        issues = [HealFix(file="a.py", reason="bug", severity="high")]
        result = """[FIX:a.py]
short
[END:FIX]"""
        fixes = healer._parse_ai_fixes(result, issues)
        assert fixes == []

    def test_falls_back_to_first_issue_for_unknown_file(self, tmp_path: Path):
        """未匹配的文件用第一个 issue 兜底"""
        healer = SelfHealer(project_root=tmp_path)
        issues = [HealFix(file="a.py", reason="bug", severity="high")]
        result = """[FIX:unknown_file.py]
```python
def some_function_with_enough_length():
    pass
```
[END:FIX]"""
        fixes = healer._parse_ai_fixes(result, issues)
        assert len(fixes) == 1
        assert fixes[0].reason == "bug"  # 来自第一个 issue

    def test_empty_result(self, tmp_path: Path):
        healer = SelfHealer(project_root=tmp_path)
        issues = [HealFix(file="a.py", reason="bug", severity="high")]
        fixes = healer._parse_ai_fixes("", issues)
        assert fixes == []

    def test_no_issues_returns_empty(self, tmp_path: Path):
        healer = SelfHealer(project_root=tmp_path)
        result = """[FIX:a.py]
```python
def some_long_enough_function():
    pass
```
[END:FIX]"""
        fixes = healer._parse_ai_fixes(result, [])
        assert fixes == []


# ══════════════════════════════════════════════════════════
# SelfHealer._apply_fix_safe
# ══════════════════════════════════════════════════════════


class TestApplyFixSafe:
    def test_missing_file_returns_false(self, tmp_path: Path):
        healer = SelfHealer(project_root=tmp_path)
        fix = HealFix(file="nonexistent.py", new_code="def f(): pass\n",
                      reason="r", severity="high")
        assert healer._apply_fix_safe(fix) is False

    def test_short_code_returns_false(self, tmp_path: Path):
        """new_code < 10 字符"""
        (tmp_path / "target.py").write_text("x = 1\n", encoding="utf-8")
        healer = SelfHealer(project_root=tmp_path)
        fix = HealFix(file="target.py", new_code="short",
                      reason="r", severity="medium")
        assert healer._apply_fix_safe(fix) is False

    def test_empty_code_returns_false(self, tmp_path: Path):
        (tmp_path / "target.py").write_text("x = 1\n", encoding="utf-8")
        healer = SelfHealer(project_root=tmp_path)
        fix = HealFix(file="target.py", new_code="",
                      reason="r", severity="medium")
        assert healer._apply_fix_safe(fix) is False

    def test_placeholder_code_returns_false(self, tmp_path: Path):
        """含 # ... 代码 / # ... code 占位符"""
        (tmp_path / "target.py").write_text("x = 1\n", encoding="utf-8")
        healer = SelfHealer(project_root=tmp_path)
        fix = HealFix(
            file="target.py",
            new_code="# ... 代码\ndef f(): pass\n",
            reason="r", severity="medium",
        )
        assert healer._apply_fix_safe(fix) is False

    def test_valid_syntax_applied_and_backed_up(self, tmp_path: Path):
        (tmp_path / "target.py").write_text("x = 1\n", encoding="utf-8")
        healer = SelfHealer(project_root=tmp_path)
        new_code = "def hello_world():\n    return 'fixed'\n"
        fix = HealFix(file="target.py", new_code=new_code,
                      reason="r", severity="high")
        result = healer._apply_fix_safe(fix)
        assert result is True
        # 文件被写入新内容
        assert (tmp_path / "target.py").read_text(encoding="utf-8") == new_code
        # 备份被创建
        backups = list((tmp_path / ".pycoder_backups").glob("target.py.*.bak"))
        assert len(backups) == 1
        # old_code 被记录
        assert "x = 1" in fix.old_code

    def test_invalid_syntax_rolls_back(self, tmp_path: Path):
        """写入的代码语法错误 → 回滚 + 删除备份"""
        original = "x = 1\n"
        (tmp_path / "target.py").write_text(original, encoding="utf-8")
        healer = SelfHealer(project_root=tmp_path)
        # 长度 > 10 但语法错误
        bad_code = "def broken(\n    return 1\n"
        fix = HealFix(file="target.py", new_code=bad_code,
                      reason="r", severity="high")
        result = healer._apply_fix_safe(fix)
        assert result is False
        # 文件被回滚到原始内容
        assert (tmp_path / "target.py").read_text(encoding="utf-8") == original
        # 备份被删除
        backups = list((tmp_path / ".pycoder_backups").glob("target.py.*.bak"))
        assert backups == []

    def test_oserror_returns_false(self, tmp_path: Path):
        """写入失败时返回 False"""
        (tmp_path / "target.py").write_text("x = 1\n", encoding="utf-8")
        healer = SelfHealer(project_root=tmp_path)
        fix = HealFix(file="target.py", new_code="def f(): pass\n",
                      reason="r", severity="high")
        with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            assert healer._apply_fix_safe(fix) is False


# ══════════════════════════════════════════════════════════
# SelfHealer._run_tests
# ══════════════════════════════════════════════════════════


class TestRunTests:
    async def test_returns_true_on_zero_returncode(self, tmp_path: Path):
        healer = SelfHealer(project_root=tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "all passed"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            ok, output = await healer._run_tests()
        assert ok is True
        assert "all passed" in output

    async def test_returns_false_on_nonzero_returncode(self, tmp_path: Path):
        healer = SelfHealer(project_root=tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "FAILED test_x"
        with patch("subprocess.run", return_value=mock_result):
            ok, output = await healer._run_tests()
        assert ok is False
        assert "FAILED" in output

    async def test_returns_false_on_exception(self, tmp_path: Path):
        healer = SelfHealer(project_root=tmp_path)
        with patch("subprocess.run", side_effect=Exception("timeout")):
            ok, output = await healer._run_tests()
        assert ok is False
        assert "timeout" in output


# ══════════════════════════════════════════════════════════
# SelfHealer._record_heal_result
# ══════════════════════════════════════════════════════════


class TestRecordHealResult:
    def test_calls_engine_on_task_complete(self, tmp_path: Path):
        healer = SelfHealer(project_root=tmp_path)
        report = HealReport(task_id="T-1")
        report.fixes = [
            HealFix(file="a.py", reason="bug", severity="high",
                    applied=True, test_passed=True, new_code="def f(): pass\n"),
        ]
        with patch("pycoder.capabilities.self_evo.learning.get_learning_engine") as mock_get:
            engine = MagicMock()
            mock_get.return_value = engine
            healer._record_heal_result(report)
        engine.on_task_complete.assert_called_once()
        kwargs = engine.on_task_complete.call_args.kwargs
        assert kwargs["task_id"] == "T-1"
        assert kwargs["task_type"] == "self_heal"
        assert kwargs["outcome"] == "success"

    def test_failure_outcome_when_test_failed(self, tmp_path: Path):
        healer = SelfHealer(project_root=tmp_path)
        report = HealReport(task_id="T-2")
        report.fixes = [
            HealFix(file="a.py", reason="bug", severity="high",
                    applied=True, test_passed=False, new_code="def f(): pass\n"),
        ]
        with patch("pycoder.capabilities.self_evo.learning.get_learning_engine") as mock_get:
            engine = MagicMock()
            mock_get.return_value = engine
            healer._record_heal_result(report)
        kwargs = engine.on_task_complete.call_args.kwargs
        assert kwargs["outcome"] == "failure"

    def test_engine_exception_silent(self, tmp_path: Path):
        """engine 抛异常时静默"""
        healer = SelfHealer(project_root=tmp_path)
        report = HealReport(task_id="T-3")
        report.fixes = [HealFix(file="a.py", reason="bug", severity="high")]
        with patch("pycoder.capabilities.self_evo.learning.get_learning_engine") as mock_get:
            mock_get.side_effect = ImportError("no module")
            # 不应抛异常
            healer._record_heal_result(report)


# ══════════════════════════════════════════════════════════
# SelfHealer._ai_heal
# ══════════════════════════════════════════════════════════


class TestAiHeal:
    async def test_parses_ai_response(self, tmp_path: Path):
        """AI 返回 [FIX:...] 块被正确解析"""
        healer = SelfHealer(project_root=tmp_path)
        # 创建实际文件，让 _ai_heal 能读取
        (tmp_path / "a.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
        issues = [HealFix(file="a.py", reason="语法错误", severity="critical")]

        # 完整的 [FIX:...][END:FIX] 块
        full_result = (
            "[FIX:a.py]\n"
            "```python\n"
            "def fixed_function():\n"
            "    return None\n"
            "```\n"
            "[END:FIX]"
        )

        # mock ChatBridge 与 _get_api_key_for_model
        async def fake_stream(prompt):
            yield MagicMock(event_type="token", content=full_result)
            yield MagicMock(event_type="done", content=None)

        bridge = MagicMock()
        bridge.config = MagicMock()
        bridge.chat_stream = fake_stream
        bridge.close = AsyncMock()
        bridge.configure = MagicMock()

        with patch("pycoder.server.chat_bridge.ChatBridge", return_value=bridge), \
             patch("pycoder.server.chat_handler._get_api_key_for_model", return_value="fake-key"):
            fixes = await healer._ai_heal(issues)

        assert len(fixes) == 1
        assert fixes[0].file == "a.py"
        assert "fixed_function" in fixes[0].new_code

    async def test_exception_returns_empty(self, tmp_path: Path):
        """ChatBridge() 抛 RuntimeError 时返回空列表（caught by except 分支）"""
        healer = SelfHealer(project_root=tmp_path)
        issues = [HealFix(file="a.py", reason="bug", severity="high")]
        with patch("pycoder.server.chat_bridge.ChatBridge", side_effect=RuntimeError("bridge init failed")):
            fixes = await healer._ai_heal(issues)
        assert fixes == []

    async def test_missing_file_skipped(self, tmp_path: Path):
        """issue 对应的文件不存在时跳过"""
        healer = SelfHealer(project_root=tmp_path)
        issues = [HealFix(file="missing.py", reason="bug", severity="high")]

        async def fake_stream(prompt):
            yield MagicMock(event_type="done", content="")

        bridge = MagicMock()
        bridge.config = MagicMock()
        bridge.chat_stream = fake_stream
        bridge.close = AsyncMock()

        with patch("pycoder.server.chat_bridge.ChatBridge", return_value=bridge), \
             patch("pycoder.server.chat_handler._get_api_key_for_model", return_value="fake-key"):
            fixes = await healer._ai_heal(issues)
        # 空 result → 无 fixes
        assert fixes == []


# ══════════════════════════════════════════════════════════
# SelfHealer.auto_heal — 全流程
# ══════════════════════════════════════════════════════════


class TestAutoHeal:
    async def test_no_issues_returns_early(self, tmp_path: Path):
        healer = SelfHealer(project_root=tmp_path)
        with patch.object(healer, "_static_scan", return_value=[]):
            report = await healer.auto_heal()
        assert report.issues_found == 0
        assert report.fixes_applied == 0
        assert report.test_passed is False

    async def test_dry_run_does_not_apply(self, tmp_path: Path):
        """dry_run=True 时不应用修复"""
        healer = SelfHealer(project_root=tmp_path)
        issues = [HealFix(file="a.py", reason="bug", severity="high")]
        kb_fixes = [HealFix(file="a.py", reason="bug", severity="high",
                            new_code="def f(): pass\n")]
        with patch.object(healer, "_static_scan", return_value=issues), \
             patch.object(healer, "_match_knowledge", return_value=kb_fixes), \
             patch.object(healer, "_apply_fix_safe") as mock_apply, \
             patch.object(healer, "_record_heal_result"):
            report = await healer.auto_heal(dry_run=True)
        # dry_run 时不调用 _apply_fix_safe
        mock_apply.assert_not_called()
        assert report.fixes_applied == 0

    async def test_knowledge_fixes_applied_and_tested(self, tmp_path: Path):
        """知识库修复被应用 + 测试通过"""
        healer = SelfHealer(project_root=tmp_path)
        issues = [HealFix(file="a.py", reason="bug", severity="low")]
        kb_fixes = [HealFix(file="a.py", reason="bug", severity="low",
                            new_code="def f(): pass\n")]
        with patch.object(healer, "_static_scan", return_value=issues), \
             patch.object(healer, "_match_knowledge", return_value=kb_fixes), \
             patch.object(healer, "_apply_fix_safe", return_value=True), \
             patch.object(healer, "_run_tests", new=AsyncMock(return_value=(True, "ok"))), \
             patch.object(healer, "_record_heal_result"):
            report = await healer.auto_heal(dry_run=False)
        assert report.fixes_applied == 1
        assert report.test_passed is True
        assert report.fixes[0].applied is True
        assert report.fixes[0].test_passed is True

    async def test_test_failure_sets_error(self, tmp_path: Path):
        """测试失败时设置 error"""
        healer = SelfHealer(project_root=tmp_path)
        issues = [HealFix(file="a.py", reason="bug", severity="low")]
        kb_fixes = [HealFix(file="a.py", reason="bug", severity="low",
                            new_code="def f(): pass\n")]
        with patch.object(healer, "_static_scan", return_value=issues), \
             patch.object(healer, "_match_knowledge", return_value=kb_fixes), \
             patch.object(healer, "_apply_fix_safe", return_value=True), \
             patch.object(healer, "_run_tests", new=AsyncMock(return_value=(False, "fail"))), \
             patch.object(healer, "_record_heal_result"):
            report = await healer.auto_heal(dry_run=False)
        assert report.test_passed is False
        assert "测试失败" in report.error

    async def test_ai_heal_for_complex_issues(self, tmp_path: Path):
        """critical/high 问题且无知识库修复 → 走 AI 修复"""
        healer = SelfHealer(project_root=tmp_path)
        issues = [HealFix(file="a.py", reason="critical bug", severity="critical")]
        ai_fixes = [HealFix(file="a.py", reason="critical bug", severity="critical",
                            new_code="def fixed(): return None\n")]
        with patch.object(healer, "_static_scan", return_value=issues), \
             patch.object(healer, "_match_knowledge", return_value=[]), \
             patch.object(healer, "_ai_heal", new=AsyncMock(return_value=ai_fixes)), \
             patch.object(healer, "_apply_fix_safe", return_value=True), \
             patch.object(healer, "_run_tests", new=AsyncMock(return_value=(True, "ok"))), \
             patch.object(healer, "_record_heal_result"):
            report = await healer.auto_heal(dry_run=False)
        assert report.fixes_applied == 1
        assert report.fixes[0].file == "a.py"

    async def test_exception_caught_and_recorded(self, tmp_path: Path):
        """auto_heal 中的异常被捕获并写入 error"""
        healer = SelfHealer(project_root=tmp_path)
        with patch.object(healer, "_static_scan", side_effect=RuntimeError("boom")):
            report = await healer.auto_heal()
        assert "boom" in report.error

    async def test_files_scanned_count(self, tmp_path: Path):
        """files_scanned 统计唯一文件数"""
        healer = SelfHealer(project_root=tmp_path)
        issues = [
            HealFix(file="a.py", reason="bug1", severity="low"),
            HealFix(file="a.py", reason="bug2", severity="low"),
            HealFix(file="b.py", reason="bug3", severity="low"),
        ]
        with patch.object(healer, "_static_scan", return_value=issues), \
             patch.object(healer, "_match_knowledge", return_value=[]), \
             patch.object(healer, "_record_heal_result"):
            report = await healer.auto_heal()
        # 2 个唯一文件
        assert report.files_scanned == 2


# ══════════════════════════════════════════════════════════
# UsageAnalyzer._analyze_sessions
# ══════════════════════════════════════════════════════════


class TestAnalyzeSessions:
    def test_counts_messages_and_topics(self):
        analyzer = UsageAnalyzer()
        sessions = [StubSession(id="s1"), StubSession(id="s2")]
        messages_map = {
            "s1": [
                StubMessage(role="user", content="如何修复 bug？"),
                StubMessage(role="assistant", content="修复完成", metadata={"model": "gpt-4"}),
            ],
            "s2": [
                StubMessage(role="user", content="优化性能"),
                StubMessage(role="assistant", content="done", metadata={"model": "claude"}),
            ],
        }
        store = StubSessionStore(sessions=sessions, messages_map=messages_map)
        report = UsageReport()
        with patch("pycoder.server.session_store.get_session_store", return_value=store):
            analyzer._analyze_sessions(report, days=30)
        assert report.total_sessions == 2
        assert report.total_messages == 4
        assert report.user_messages == 2
        assert report.ai_messages == 2
        # 话题统计
        topic_dict = dict(report.top_topics)
        assert "bug" in topic_dict or "修复" in topic_dict
        # 模型分布
        assert "gpt-4" in report.model_distribution
        assert "claude" in report.model_distribution

    def test_handles_message_without_metadata(self):
        """message 无 metadata 属性时不抛异常"""
        analyzer = UsageAnalyzer()
        sessions = [StubSession(id="s1")]
        # 使用 plain object without metadata attr
        @dataclass
        class PlainMsg:
            role: str = "user"
            content: str = "hello"

        messages_map = {"s1": [PlainMsg(role="user", content="hello")]}
        store = StubSessionStore(sessions=sessions, messages_map=messages_map)
        report = UsageReport()
        with patch("pycoder.server.session_store.get_session_store", return_value=store):
            # 不应抛异常
            analyzer._analyze_sessions(report, days=30)
        assert report.total_messages == 1

    def test_session_store_exception_handled_by_analyze(self):
        """session_store 抛异常时 analyze 捕获"""
        analyzer = UsageAnalyzer()
        with patch("pycoder.server.session_store.get_session_store",
                   side_effect=ImportError("no store")):
            report = analyzer.analyze(days=30)
        # analyze 内部捕获 ImportError，返回空 report
        assert report.total_sessions == 0


class TestAnalyzeFullFlow:
    """覆盖 UsageAnalyzer.analyze() 的全流程（含 _analyze_errors/_analyze_evolution/_generate_hints）"""

    def test_analyze_calls_all_sub_analyzers(self):
        """analyze 依次调用 4 个 sub-analyzer"""
        analyzer = UsageAnalyzer()
        store = StubSessionStore(
            sessions=[StubSession(id="s1")],
            messages_map={"s1": [StubMessage(role="user", content="bug fix")]},
        )
        with patch("pycoder.server.session_store.get_session_store", return_value=store), \
             patch("pycoder.capabilities.self_evo.learning.knowledge_base.get_knowledge_base") as mock_kb_get, \
             patch("pycoder.capabilities.self_evo.learning.metrics_tracker.get_metrics_tracker") as mock_mt_get:
            kb = MagicMock()
            kb.get_top_errors.return_value = []
            mock_kb_get.return_value = kb
            mt = MagicMock()
            mt.get_evolution_stats.return_value = {
                "total_evolutions": 5, "success_rate": 0.9,
                "total_bugs_fixed": 3,
            }
            mt.get_daily_summary.return_value = []
            mock_mt_get.return_value = mt
            report = analyzer.analyze(days=30)
        # 验证所有 sub-analyzer 都被调用
        assert report.total_sessions == 1
        assert report.total_messages == 1
        kb.get_top_errors.assert_called_once()
        mt.get_evolution_stats.assert_called_once()
        mt.get_daily_summary.assert_called_once()
        # hints 至少包含 evolution hint
        assert any("5次进化" in h for h in report.optimization_hints)

    def test_analyze_sub_analyzer_exception_caught(self):
        """_analyze_errors 抛异常时 analyze 捕获（不传播）"""
        analyzer = UsageAnalyzer()
        store = StubSessionStore(sessions=[], messages_map={})
        with patch("pycoder.server.session_store.get_session_store", return_value=store), \
             patch("pycoder.capabilities.self_evo.learning.knowledge_base.get_knowledge_base",
                   side_effect=RuntimeError("kb down")):
            # 不应抛异常（_analyze_errors 自身捕获；analyze 也兜底）
            report = analyzer.analyze(days=30)
        assert report.total_sessions == 0


# ══════════════════════════════════════════════════════════
# UsageAnalyzer._analyze_errors
# ══════════════════════════════════════════════════════════


class TestAnalyzeErrors:
    def test_extracts_top_errors_and_common_issues(self):
        analyzer = UsageAnalyzer()
        report = UsageReport()
        # mock kb
        with patch("pycoder.capabilities.self_evo.learning.knowledge_base.get_knowledge_base") as mock_get:
            kb = MagicMock()
            kb.get_top_errors.return_value = [
                StubErrorPattern(error_type="NameError", success_count=1, fail_count=5),
                StubErrorPattern(error_type="TypeError", success_count=5, fail_count=1),
            ]
            mock_get.return_value = kb
            analyzer._analyze_errors(report, days=30)
        # top_error_types 包含 NameError 和 TypeError
        types = [t for t, _ in report.top_error_types]
        assert "NameError" in types
        # common_issues 包含 fail > success 的（NameError）
        assert "NameError" in report.common_issues
        assert "TypeError" not in report.common_issues

    def test_kb_exception_silent(self):
        analyzer = UsageAnalyzer()
        report = UsageReport()
        with patch("pycoder.capabilities.self_evo.learning.knowledge_base.get_knowledge_base",
                   side_effect=RuntimeError("kb down")):
            # 不应抛异常
            analyzer._analyze_errors(report, days=30)
        assert report.top_error_types == []


# ══════════════════════════════════════════════════════════
# UsageAnalyzer._analyze_evolution
# ══════════════════════════════════════════════════════════


class TestAnalyzeEvolution:
    def test_appends_evolution_hint(self):
        analyzer = UsageAnalyzer()
        report = UsageReport()
        with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.get_metrics_tracker") as mock_get:
            mt = MagicMock()
            mt.get_evolution_stats.return_value = {
                "total_evolutions": 10,
                "success_rate": 0.8,
                "total_bugs_fixed": 5,
            }
            mt.get_daily_summary.return_value = [{"day": "2026-01-01", "evolutions": 1}]
            mock_get.return_value = mt
            analyzer._analyze_evolution(report, days=30)
        assert len(report.optimization_hints) >= 1
        assert "10次进化" in report.optimization_hints[0]
        assert report.weekly_activity == [{"day": "2026-01-01", "evolutions": 1}]

    def test_metrics_exception_silent(self):
        analyzer = UsageAnalyzer()
        report = UsageReport()
        with patch("pycoder.capabilities.self_evo.learning.metrics_tracker.get_metrics_tracker",
                   side_effect=ImportError("no tracker")):
            analyzer._analyze_evolution(report, days=30)
        assert report.optimization_hints == []


# ══════════════════════════════════════════════════════════
# UsageAnalyzer._generate_hints
# ══════════════════════════════════════════════════════════


class TestGenerateHints:
    def test_high_freq_error_hint(self):
        analyzer = UsageAnalyzer()
        report = UsageReport(top_error_types=[("NameError", 10)])
        analyzer._generate_hints(report)
        assert any("最高频错误" in h for h in report.optimization_hints)

    def test_low_usage_model_hint(self):
        """某模型使用率 < 10% → 提示增加路由"""
        analyzer = UsageAnalyzer()
        report = UsageReport(model_distribution={"gpt-4": 90, "cheap-model": 5})
        analyzer._generate_hints(report)
        assert any("cheap-model" in h and "使用率" in h for h in report.optimization_hints)

    def test_no_low_usage_hint_when_balanced(self):
        """模型分布均衡时不提示（>10%）"""
        analyzer = UsageAnalyzer()
        report = UsageReport(model_distribution={"a": 50, "b": 50})
        analyzer._generate_hints(report)
        assert not any("使用率仅" in h for h in report.optimization_hints)

    def test_low_sessions_hint(self):
        analyzer = UsageAnalyzer()
        report = UsageReport(total_sessions=2)
        analyzer._generate_hints(report)
        assert any("会话数较少" in h for h in report.optimization_hints)

    def test_high_ai_user_ratio_hint(self):
        """AI/用户消息比 > 3 → 提示精简提示词"""
        analyzer = UsageAnalyzer()
        report = UsageReport(user_messages=10, ai_messages=50)
        analyzer._generate_hints(report)
        assert any("AI/用户消息比" in h for h in report.optimization_hints)

    def test_balanced_ratio_no_hint(self):
        analyzer = UsageAnalyzer()
        report = UsageReport(user_messages=10, ai_messages=20)
        analyzer._generate_hints(report)
        assert not any("AI/用户消息比" in h for h in report.optimization_hints)

    def test_empty_report_only_session_hint(self):
        """空 report 触发 '会话数较少' 提示（total_sessions < 3）"""
        analyzer = UsageAnalyzer()
        report = UsageReport()
        analyzer._generate_hints(report)
        # 仅 '会话数较少' 提示（无其他数据）
        assert any("会话数较少" in h for h in report.optimization_hints)

    def test_report_with_sessions_no_other_hints(self):
        """有足够 sessions 但无其他数据时无额外提示"""
        analyzer = UsageAnalyzer()
        report = UsageReport(total_sessions=10)  # 足够，不触发会话提示
        analyzer._generate_hints(report)
        assert report.optimization_hints == []


# ══════════════════════════════════════════════════════════
# PromptOptimizer
# ══════════════════════════════════════════════════════════


class TestPromptOptimizer:
    def test_unknown_agent_returns_empty(self):
        po = PromptOptimizer()
        result = po.optimize_agent_prompt("nonexistent_agent")
        assert result.agent_id == "nonexistent_agent"
        assert result.original_lines == 0
        assert result.changes == []

    def test_short_prompt_triggers_warning(self):
        """< 400 行提示词触发扩充建议"""
        po = PromptOptimizer()
        with patch("pycoder.server.services.agent_definitions.AGENT_ROLES") as mock_roles:
            mock_roles.get.return_value = MagicMock(
                system_prompt="短提示词\n",
                model="deepseek-chat",
            )
            result = po.optimize_agent_prompt("pm")
        assert any("提示词仅" in c and "400" in c for c in result.changes)

    def test_missing_required_sections(self):
        """缺少必需章节触发警告"""
        po = PromptOptimizer()
        # 提示词够长但缺少关键词
        long_prompt = "x\n" * 500  # 500 行
        with patch("pycoder.server.services.agent_definitions.AGENT_ROLES") as mock_roles:
            mock_roles.get.return_value = MagicMock(
                system_prompt=long_prompt,
                model="deepseek-chat",
            )
            with patch("pycoder.server.learning.feedback_loop.get_feedback_loop") as mock_fb:
                mock_fb.return_value.get_adaptive_config.return_value = MagicMock(
                    preferred_models={},
                )
                result = po.optimize_agent_prompt("developer")
        # 应报告缺失章节
        assert any("缺少关键部分" in c for c in result.changes)
        assert "expected_improvement" in vars(result) or result.expected_improvement

    def test_preferred_model_differs_from_current(self):
        """推荐模型与当前模型不同 → 提示更新"""
        po = PromptOptimizer()
        long_prompt = "职责\n输出格式\n原则\n备份\n" + "x\n" * 500
        with patch("pycoder.server.services.agent_definitions.AGENT_ROLES") as mock_roles:
            mock_roles.get.return_value = MagicMock(
                system_prompt=long_prompt,
                model="deepseek-chat",
            )
            with patch("pycoder.server.learning.feedback_loop.get_feedback_loop") as mock_fb:
                mock_fb.return_value.get_adaptive_config.return_value = MagicMock(
                    preferred_models={"developer": "deepseek-reasoner"},
                )
                result = po.optimize_agent_prompt("developer")
        assert any("推荐模型" in c for c in result.changes)

    def test_feedback_loop_exception_silent(self):
        """feedback_loop 异常时静默"""
        po = PromptOptimizer()
        long_prompt = "x\n" * 500
        with patch("pycoder.server.services.agent_definitions.AGENT_ROLES") as mock_roles:
            mock_roles.get.return_value = MagicMock(
                system_prompt=long_prompt,
                model="deepseek-chat",
            )
            with patch("pycoder.server.learning.feedback_loop.get_feedback_loop",
                       side_effect=ImportError("no fb")):
                result = po.optimize_agent_prompt("developer")
        # 不应抛异常，仍返回结果
        assert result.agent_id == "developer"

    def test_agent_definitions_get_exception_silent(self):
        """AGENT_ROLES.get() 抛异常时静默（caught by except 分支）"""
        po = PromptOptimizer()
        mock_roles = MagicMock()
        mock_roles.get.side_effect = RuntimeError("dict broken")
        with patch("pycoder.server.services.agent_definitions.AGENT_ROLES", mock_roles):
            result = po.optimize_agent_prompt("pm")
        assert result.changes == []
        assert result.agent_id == "pm"

    def test_optimize_all_agents_returns_5(self):
        po = PromptOptimizer()
        results = po.optimize_all_agents()
        assert len(results) == 5
        agent_ids = {r.agent_id for r in results}
        assert agent_ids == {"pm", "architect", "developer", "qa", "devops"}

    def test_generate_optimization_report_markdown(self):
        po = PromptOptimizer()
        md = po.generate_optimization_report()
        assert "Agent 提示词优化报告" in md
        # 应包含 5 个 agent 的章节
        assert md.count("## ") >= 5

    def test_generate_optimization_report_with_no_changes_agent(self):
        """某 agent 无 changes 时输出 ✅ 无需优化"""
        po = PromptOptimizer()
        # generate_optimization_report 调用 self.optimize_all_agents
        # 直接 patch 该方法返回控制结果
        with patch.object(po, "optimize_all_agents", return_value=[
            PromptOptimization(agent_id="pm", original_lines=500,
                               changes=["change1"], expected_improvement="imp"),
            PromptOptimization(agent_id="qa", original_lines=500, changes=[]),
        ]):
            md = po.generate_optimization_report()
        assert "无需优化" in md  # qa 的章节
        assert "change1" in md  # pm 的章节


# ══════════════════════════════════════════════════════════
# SelfOptimizer — 统一入口
# ══════════════════════════════════════════════════════════


class TestSelfOptimizer:
    async def test_auto_heal_delegates_to_healer(self):
        opt = SelfOptimizer()
        fake_report = HealReport(task_id="T-X")
        with patch.object(opt.healer, "auto_heal", new=AsyncMock(return_value=fake_report)):
            result = await opt.auto_heal(dry_run=True)
        assert result is fake_report

    def test_analyze_usage_delegates(self):
        opt = SelfOptimizer()
        fake_report = UsageReport(total_sessions=42)
        with patch.object(opt.analyzer, "analyze", return_value=fake_report):
            result = opt.analyze_usage(days=7)
        assert result.total_sessions == 42

    def test_optimize_prompts_delegates(self):
        opt = SelfOptimizer()
        fake_results = [PromptOptimization(agent_id="pm")]
        with patch.object(opt.prompt_opt, "optimize_all_agents", return_value=fake_results):
            result = opt.optimize_prompts()
        assert result is fake_results

    def test_full_optimization_cycle_with_recommendations(self):
        """common_issues / prompts changes / top_topics / model_distribution 推荐"""
        opt = SelfOptimizer()
        usage = UsageReport(
            total_sessions=10,
            total_messages=100,
            common_issues=["NameError"],
            top_topics=[("bug", 5)],
            model_distribution={"gpt-4": 80, "claude": 20},
        )
        prompts = [
            PromptOptimization(agent_id="developer", changes=["change1"]),
            PromptOptimization(agent_id="qa"),  # 无 changes
        ]
        with patch.object(opt, "analyze_usage", return_value=usage), \
             patch.object(opt, "optimize_prompts", return_value=prompts):
            result = opt.full_optimization_cycle()
        # recommendations 应包含所有 4 类
        recs = result["recommendations"]
        assert any("高频问题" in r for r in recs)
        assert any("提示词" in r for r in recs)
        assert any("最热话题" in r for r in recs)
        assert any("模型分布" in r for r in recs)
        # prompts 字段只含有 changes 的
        assert len(result["prompts"]) == 1
        assert result["prompts"][0]["agent"] == "developer"

    def test_full_optimization_cycle_no_recommendations(self):
        """无数据时不生成推荐"""
        opt = SelfOptimizer()
        usage = UsageReport()  # 全空
        with patch.object(opt, "analyze_usage", return_value=usage), \
             patch.object(opt, "optimize_prompts", return_value=[]):
            result = opt.full_optimization_cycle()
        assert result["recommendations"] == []

    def test_generate_optimization_markdown_full(self):
        opt = SelfOptimizer()
        usage = UsageReport(
            total_sessions=5,
            total_messages=50,
            top_topics=[("bug", 3)],
            top_error_types=[("NameError", 2)],
            optimization_hints=["hint1"],
        )
        prompts_with_changes = [
            PromptOptimization(agent_id="pm", original_lines=500,
                               changes=["change1"], expected_improvement="improve"),
        ]
        with patch.object(opt, "full_optimization_cycle", return_value={
            "usage": {
                "sessions": 5, "messages": 50,
                "top_topics": [("bug", 3)],
                "top_errors": [("NameError", 2)],
                "hints": ["hint1"],
            },
            "prompts": [
                {"agent": "pm", "lines": 500, "issues": 1, "changes": ["change1"]},
            ],
            "recommendations": ["rec1"],
        }):
            md = opt.generate_optimization_markdown()
        assert "自优化报告" in md
        assert "bug(3)" in md
        assert "NameError(2)" in md
        assert "hint1" in md
        assert "pm" in md
        assert "rec1" in md

    def test_generate_optimization_markdown_empty(self):
        opt = SelfOptimizer()
        with patch.object(opt, "full_optimization_cycle", return_value={
            "usage": {}, "prompts": [], "recommendations": [],
        }):
            md = opt.generate_optimization_markdown()
        assert "自优化报告" in md
        # 空数据不应崩溃
        assert isinstance(md, str)


# ══════════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════════


class TestGetSelfOptimizer:
    def test_returns_same_instance(self):
        a = get_self_optimizer()
        b = get_self_optimizer()
        assert a is b
        assert isinstance(a, SelfOptimizer)


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


class TestDataModels:
    def test_heal_fix_defaults(self):
        fix = HealFix(file="a.py", reason="r", severity="high")
        assert fix.applied is False
        assert fix.test_passed is False
        assert fix.old_code == ""
        assert fix.new_code == ""

    def test_heal_report_defaults(self):
        r = HealReport()
        assert r.task_id == ""
        assert r.fixes == []
        assert r.duration_ms == 0.0

    def test_usage_report_defaults(self):
        r = UsageReport()
        assert r.top_topics == []
        assert r.model_distribution == {}
        assert r.weekly_activity == []

    def test_prompt_optimization_defaults(self):
        p = PromptOptimization()
        assert p.agent_id == ""
        assert p.changes == []
