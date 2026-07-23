from __future__ import annotations

import json
import os
import sys
import time
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


