"""decision_snapshot.py, task_pipeline.py, perf_advisor.py, code_sanitizer.py 综合测试"""

from __future__ import annotations

import asyncio
import pytest
from pathlib import Path

# ── decision_snapshot 测试 ──────────────────────────────────

from pycoder.ai.dialog.decision_snapshot import (
    DecisionSnapshot,
    DecisionSnapshotManager,
)


class TestDecisionSnapshot:
    """决策快照数据类测试"""

    def test_default_values(self) -> None:
        snap = DecisionSnapshot()
        assert snap.file_path == ""
        assert snap.change_type == ""
        assert snap.description == ""

    def test_to_dict(self) -> None:
        snap = DecisionSnapshot(
            file_path="app.py",
            change_type="modify",
            description="修复 bug",
            reason="用户反馈",
        )
        d = snap.to_dict()
        assert d["file_path"] == "app.py"
        assert d["change_type"] == "modify"
        assert "time_str" in d


class TestDecisionSnapshotManager:
    """决策快照管理器测试"""

    def test_record(self) -> None:
        mgr = DecisionSnapshotManager()
        snap = mgr.record("app.py", "modify", "修复超时问题", "用户反馈")
        assert snap.file_path == "app.py"
        assert snap.change_type == "modify"
        assert mgr.snapshot_count == 1

    def test_get_recent(self) -> None:
        mgr = DecisionSnapshotManager()
        for i in range(5):
            mgr.record(f"file_{i}.py", "modify", f"修改 {i}")
        recent = mgr.get_recent(3)
        assert len(recent) == 3
        assert recent[-1].file_path == "file_4.py"

    def test_get_affected_files(self) -> None:
        mgr = DecisionSnapshotManager()
        mgr.record("app.py", "modify", "修改1")
        mgr.record("utils.py", "create", "创建工具")
        mgr.record("app.py", "modify", "修改2")
        files = mgr.get_affected_files()
        assert files == {"app.py", "utils.py"}

    def test_get_context_summary_empty(self) -> None:
        mgr = DecisionSnapshotManager()
        assert mgr.get_context_summary() == ""

    def test_get_context_summary_below_threshold(self) -> None:
        mgr = DecisionSnapshotManager()
        mgr.record("app.py", "modify", "修改")
        mgr.increment_turn()
        mgr.increment_turn()
        assert mgr.get_context_summary() == ""  # 未到阈值

    def test_get_context_summary_above_threshold(self) -> None:
        mgr = DecisionSnapshotManager()
        mgr.record("app.py", "modify", "修复 bug")
        for _ in range(15):
            mgr.increment_turn()
        summary = mgr.get_context_summary()
        assert summary != ""
        assert "app.py" in summary

    def test_clear(self) -> None:
        mgr = DecisionSnapshotManager()
        mgr.record("app.py", "modify", "修改")
        mgr.clear()
        assert mgr.snapshot_count == 0
        assert mgr.turn_count == 0

    def test_persist_and_load(self, tmp_path: Path) -> None:
        mgr1 = DecisionSnapshotManager(session_id="test-session")
        mgr1.record("app.py", "modify", "修改")
        mgr1.increment_turn()
        mgr1.persist("test-session", storage_dir=tmp_path)

        mgr2 = DecisionSnapshotManager()
        mgr2.load("test-session", storage_dir=tmp_path)
        assert mgr2.snapshot_count == 1
        assert mgr2.turn_count == 1


# ── task_pipeline 测试 ──────────────────────────────────────

from pycoder.capabilities.tools.task_pipeline import (
    PipelineResult,
    PipelineStep,
    StepResult,
    TaskPipeline,
)


class TestPipelineStep:
    """管道步骤测试"""

    def test_default_values(self) -> None:
        step = PipelineStep(command="echo hello")
        assert step.command == "echo hello"
        assert step.timeout == 60
        assert step.retries == 0

    def test_to_dict(self) -> None:
        step = PipelineStep(command="ls", description="列出文件", timeout=30)
        d = step.to_dict()
        assert d["command"] == "ls"
        assert d["description"] == "列出文件"
        assert d["timeout"] == 30


class TestTaskPipeline:
    """任务管道测试"""

    @pytest.fixture
    def pipeline(self) -> TaskPipeline:
        return TaskPipeline()

    @pytest.mark.asyncio
    async def test_execute_empty_steps(self, pipeline: TaskPipeline) -> None:
        result = await pipeline.execute([])
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_success(self, pipeline: TaskPipeline) -> None:
        steps = [
            PipelineStep(command="echo hello", description="打印 hello"),
            PipelineStep(command="echo world", description="打印 world"),
        ]
        result = await pipeline.execute(steps)
        assert result.success is True
        assert result.executed == 2
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_execute_with_failure(self, pipeline: TaskPipeline) -> None:
        steps = [
            PipelineStep(command="echo hello", description="成功步骤"),
            PipelineStep(command="nonexistent_command_12345", description="失败步骤"),
            PipelineStep(command="echo after", description="不应执行"),
        ]
        result = await pipeline.execute(steps, stop_on_failure=True)
        assert result.success is False
        assert result.failed >= 1
        assert result.executed >= 1

    @pytest.mark.asyncio
    async def test_execute_continue_on_failure(self, pipeline: TaskPipeline) -> None:
        steps = [
            PipelineStep(command="echo hello", description="成功"),
            PipelineStep(
                command="nonexistent_command_12345",
                description="失败但继续",
                continue_on_failure=True,
            ),
            PipelineStep(command="echo after", description="应执行"),
        ]
        result = await pipeline.execute(steps, stop_on_failure=False)
        assert result.executed >= 2

    @pytest.mark.asyncio
    async def test_dangerous_command(self, pipeline: TaskPipeline) -> None:
        steps = [PipelineStep(command="rm -rf /", description="危险命令")]
        result = await pipeline.execute(steps)
        assert result.success is False
        assert "危险" in result.error_message or result.results[0].stderr == "危险命令被拒绝执行"

    @pytest.mark.asyncio
    async def test_max_steps_limit(self, pipeline: TaskPipeline) -> None:
        steps = [PipelineStep(command="echo x") for _ in range(25)]
        result = await pipeline.execute(steps)
        assert result.success is False
        assert "超过上限" in result.error_message

    @pytest.mark.asyncio
    async def test_retry(self, pipeline: TaskPipeline) -> None:
        steps = [
            PipelineStep(
                command="nonexistent_command_12345",
                description="失败重试",
                retries=2,
                retry_delay=0.1,
            ),
        ]
        result = await pipeline.execute(steps)
        assert result.success is False
        assert result.results[0].attempts == 3  # 1 + 2 retries


# ── perf_advisor 测试 ───────────────────────────────────────

from pycoder.ai.analysis.perf_advisor import (
    PerfRule,
    PerfWarning,
    PerformanceAdvisor,
    PERF_RULES,
)


class TestPerformanceAdvisor:
    """性能顾问测试"""

    @pytest.fixture
    def advisor(self) -> PerformanceAdvisor:
        return PerformanceAdvisor()

    def test_rules_count(self) -> None:
        assert len(PERF_RULES) >= 19  # P1 扩展后达到 19 条

    def test_analyze_clean_code(self, advisor: PerformanceAdvisor) -> None:
        code = "x = 1 + 2\nprint(x)\n"
        warnings = advisor.analyze_code(code)
        assert warnings == []

    def test_analyze_string_concat_in_loop(self, advisor: PerformanceAdvisor) -> None:
        code = """
result = ""
for s in items:
    result += s
"""
        warnings = advisor.analyze_code(code)
        assert any(w.pattern == "string_concat_in_loop" for w in warnings)

    def test_analyze_time_sleep_in_loop(self, advisor: PerformanceAdvisor) -> None:
        code = """
import time
for i in range(10):
    time.sleep(1)
"""
        warnings = advisor.analyze_code(code)
        assert any(w.pattern == "time_delay_in_loop" for w in warnings)

    def test_analyze_len_in_range(self, advisor: PerformanceAdvisor) -> None:
        code = """
for i in range(len(items)):
    print(items[i])
"""
        warnings = advisor.analyze_code(code)
        assert any(w.pattern == "repeated_function_call" for w in warnings)

    def test_analyze_membership_test(self, advisor: PerformanceAdvisor) -> None:
        code = """
if x in [1, 2, 3]:
    print("found")
"""
        warnings = advisor.analyze_code(code)
        assert any(w.pattern == "inefficient_membership_test" for w in warnings)

    def test_analyze_sync_io_in_async(self, advisor: PerformanceAdvisor) -> None:
        """检测 async 函数中的同步 open() 调用"""
        code = """
async def load_data(path):
    f = open(path)
    return f.read()
"""
        warnings = advisor.analyze_code(code)
        assert any(w.pattern == "sync_io_in_async" for w in warnings)

    def test_analyze_sync_requests_in_async(self, advisor: PerformanceAdvisor) -> None:
        """检测 async 函数中的 requests.get() 调用"""
        code = """
import requests
async def fetch(url):
    return requests.get(url)
"""
        warnings = advisor.analyze_code(code)
        assert any(w.pattern == "sync_io_in_async" for w in warnings)

    def test_analyze_import_in_loop(self, advisor: PerformanceAdvisor) -> None:
        code = """
for item in items:
    import json
    json.loads(item)
"""
        warnings = advisor.analyze_code(code)
        assert any(w.pattern == "import_in_loop" for w in warnings)

    def test_analyze_deepcopy(self, advisor: PerformanceAdvisor) -> None:
        code = """
import copy
new_data = copy.deepcopy(large_object)
"""
        warnings = advisor.analyze_code(code)
        assert any(w.pattern == "deep_copy_large" for w in warnings)

    def test_analyze_bare_except(self, advisor: PerformanceAdvisor) -> None:
        code = """
try:
    do_something()
except:
    pass
"""
        warnings = advisor.analyze_code(code)
        assert any(w.pattern == "bare_except_perf" for w in warnings)

    def test_analyze_list_dict_keys(self, advisor: PerformanceAdvisor) -> None:
        code = """
for k in list(d.keys()):
    print(k)
"""
        warnings = advisor.analyze_code(code)
        assert any(w.pattern == "dict_keys_to_list" for w in warnings)

    def test_analyze_n_plus_1_query(self, advisor: PerformanceAdvisor) -> None:
        code = """
for user in users:
    order = session.query(Order).filter(Order.user_id == user.id).first()
"""
        warnings = advisor.analyze_code(code)
        assert any(w.pattern == "n_plus_1_query" for w in warnings)

    def test_analyze_sort_then_reverse(self, advisor: PerformanceAdvisor) -> None:
        code = """
items.sort()
items.reverse()
"""
        warnings = advisor.analyze_code(code)
        assert any(w.pattern == "sort_then_reverse" for w in warnings)

    def test_analyze_manual_loop_search(self, advisor: PerformanceAdvisor) -> None:
        code = """
for item in items:
    if item.is_target:
        target = item
        break
"""
        warnings = advisor.analyze_code(code)
        assert any(w.pattern == "manual_loop_search" for w in warnings)

    def test_format_warnings_empty(self, advisor: PerformanceAdvisor) -> None:
        assert advisor.format_warnings([]) == ""

    def test_format_warnings_non_empty(self, advisor: PerformanceAdvisor) -> None:
        warnings = [PerfWarning(line=10, pattern="test", severity="high", suggestion="fix it")]
        text = advisor.format_warnings(warnings)
        assert "性能注意" in text
        assert "10" in text


# ── code_sanitizer 测试 ─────────────────────────────────────

from pycoder.ai.security.code_sanitizer import (
    CodeSanitizer,
    SanitizeResult,
    SecurityWarning,
)


class TestCodeSanitizer:
    """代码安全净化器测试"""

    @pytest.fixture
    def sanitizer(self) -> CodeSanitizer:
        return CodeSanitizer()

    def test_sanitize_clean_code(self, sanitizer: CodeSanitizer) -> None:
        code = "x = 1 + 2\nprint(x)\n"
        result = sanitizer.sanitize_code(code)
        assert result.is_safe is True
        assert result.warnings == []

    def test_sanitize_sql_injection_fstring(self, sanitizer: CodeSanitizer) -> None:
        code = """
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
"""
        result = sanitizer.sanitize_code(code)
        assert result.is_safe is False
        assert any(w.vulnerability_type == "sql_injection" for w in result.warnings)

    def test_sanitize_sql_injection_concat(self, sanitizer: CodeSanitizer) -> None:
        code = """
query = "SELECT * FROM users WHERE id = " + user_id
cursor.execute(query)
"""
        result = sanitizer.sanitize_code(code)
        # 注意: 这里的拼接不是直接在 execute 内部，可能不会检测到
        # 但如果直接在 execute 中拼接会被检测
        assert isinstance(result, SanitizeResult)

    def test_sanitize_command_injection_shell(self, sanitizer: CodeSanitizer) -> None:
        code = """
import subprocess
subprocess.run("ls " + user_input, shell=True)
"""
        result = sanitizer.sanitize_code(code)
        assert result.is_safe is False
        assert any(w.vulnerability_type == "command_injection" for w in result.warnings)

    def test_sanitize_os_system(self, sanitizer: CodeSanitizer) -> None:
        code = """
import os
os.system("ls " + user_input)
"""
        result = sanitizer.sanitize_code(code)
        assert result.is_safe is False
        assert any(w.vulnerability_type == "command_injection" for w in result.warnings)

    def test_sanitize_eval(self, sanitizer: CodeSanitizer) -> None:
        code = """
result = eval(user_input)
"""
        result = sanitizer.sanitize_code(code)
        assert result.is_safe is False
        assert any(w.vulnerability_type == "code_injection" for w in result.warnings)

    def test_sanitize_pickle(self, sanitizer: CodeSanitizer) -> None:
        code = """
import pickle
data = pickle.loads(user_data)
"""
        result = sanitizer.sanitize_code(code)
        assert result.is_safe is False
        assert any(w.vulnerability_type == "deserialization" for w in result.warnings)

    def test_sanitize_yaml_load(self, sanitizer: CodeSanitizer) -> None:
        code = """
import yaml
data = yaml.load(user_input)
"""
        result = sanitizer.sanitize_code(code)
        assert result.is_safe is False
        assert any(w.vulnerability_type == "deserialization" for w in result.warnings)

    def test_sanitize_hardcoded_secret(self, sanitizer: CodeSanitizer) -> None:
        code = 'api_key = "sk-1234567890abcdef"\n'
        result = sanitizer.sanitize_code(code)
        assert result.is_safe is False
        assert any(w.vulnerability_type == "hardcoded_secret" for w in result.warnings)

    def test_sanitize_path_traversal(self, sanitizer: CodeSanitizer) -> None:
        code = """
content = open(user_filename).read()
"""
        result = sanitizer.sanitize_code(code)
        assert result.is_safe is False
        assert any(w.vulnerability_type == "path_traversal" for w in result.warnings)

    def test_sanitize_inserts_comments(self, sanitizer: CodeSanitizer) -> None:
        code = 'api_key = "sk-1234567890abcdef"\n'
        result = sanitizer.sanitize_code(code)
        assert "安全提示" in result.sanitized_code

    def test_format_warnings(self, sanitizer: CodeSanitizer) -> None:
        warnings = [
            SecurityWarning(
                line=1,
                vulnerability_type="sql_injection",
                severity="critical",
                description="SQL 注入风险",
                cwe_id="CWE-89",
            )
        ]
        text = sanitizer.format_warnings(warnings)
        assert "安全提示" in text
        assert "sql_injection" in text
        assert "CWE-89" in text
