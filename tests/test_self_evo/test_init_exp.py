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


