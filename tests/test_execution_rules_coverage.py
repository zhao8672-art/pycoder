"""覆盖率测试: pycoder/server/services/execution_rules.py

目标: 行覆盖率 >= 80%
覆盖内容:
  - ExecutionRules: BOM 检测/清理、备份/恢复、安全模式扫描、端口检查、JSON 验证、违规报告
  - SharedState: 任务状态、验证合约、预算追踪、检查点、追踪日志
  - 数据模型: TaskState / ValidationContract / BudgetTracker
  - 常量: FIVE_STEP_WORKFLOW / FAILURE_MODES / SHARED_STATE_DIR

测试策略:
  - 使用 tmp_path 隔离文件系统副作用
  - 用 monkeypatch 替换 SHARED_STATE_DIR 到临时目录
  - 用 monkeypatch 模拟 subprocess（端口检查）
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pycoder.server.services.execution_rules import (
    BudgetTracker,
    ExecutionRules,
    FAILURE_MODES,
    FIVE_STEP_WORKFLOW,
    SHARED_STATE_DIR,
    SharedState,
    TaskState,
    ValidationContract,
)


# ── Fixture: 隔离的 SharedState 目录 ─────────────────────

@pytest.fixture
def shared_state(tmp_path, monkeypatch):
    """构造使用临时目录的 SharedState，避免污染用户家目录"""
    new_dir = tmp_path / "shared_state"
    monkeypatch.setattr(
        "pycoder.server.services.execution_rules.SHARED_STATE_DIR", new_dir
    )
    return SharedState(task_id="TEST-001")


# ══════════════════════════════════════════════════════════
# ExecutionRules 测试
# ══════════════════════════════════════════════════════════

class TestExecutionRulesInit:
    """__init__ 与属性初始化"""

    def test_default_workspace_is_cwd(self):
        rules = ExecutionRules()
        assert rules._workspace == Path.cwd().resolve()
        assert rules._backup_dir == Path.cwd().resolve() / ".pycoder_backups"
        assert rules.violations == []

    def test_custom_workspace(self, tmp_path):
        rules = ExecutionRules(workspace=tmp_path)
        assert rules._workspace == tmp_path.resolve()
        assert rules._backup_dir == tmp_path.resolve() / ".pycoder_backups"


class TestBomCheck:
    """check_bom 静态方法"""

    def test_no_bom_returns_true(self, tmp_path):
        f = tmp_path / "no_bom.py"
        f.write_text("print('hi')", encoding="utf-8")
        assert ExecutionRules.check_bom(f) is True

    def test_with_bom_returns_false(self, tmp_path):
        f = tmp_path / "bom.py"
        f.write_bytes(b"\xef\xbb\xbfprint('hi')")
        assert ExecutionRules.check_bom(f) is False

    def test_nonexistent_returns_true(self, tmp_path):
        # 文件不存在视为通过
        assert ExecutionRules.check_bom(tmp_path / "missing.py") is True


class TestStripBom:
    """strip_bom 静态方法"""

    def test_strip_bom_success(self, tmp_path):
        f = tmp_path / "bom.py"
        f.write_bytes(b"\xef\xbb\xbfprint('hi')")
        assert ExecutionRules.strip_bom(f) is True
        # 验证 BOM 已被去除
        assert f.read_bytes() == b"print('hi')"

    def test_no_bom_returns_false(self, tmp_path):
        f = tmp_path / "plain.py"
        f.write_text("print('hi')", encoding="utf-8")
        assert ExecutionRules.strip_bom(f) is False

    def test_nonexistent_returns_false(self, tmp_path):
        assert ExecutionRules.strip_bom(tmp_path / "missing.py") is False


class TestBackup:
    """create_backup / restore_backup"""

    def test_create_backup_returns_path(self, tmp_path):
        rules = ExecutionRules(workspace=tmp_path)
        src = tmp_path / "src.txt"
        src.write_text("hello", encoding="utf-8")
        bak = rules.create_backup(src)
        assert bak is not None
        assert bak.exists()
        assert bak.read_text() == "hello"

    def test_create_backup_relative_path(self, tmp_path):
        rules = ExecutionRules(workspace=tmp_path)
        src = tmp_path / "src.txt"
        src.write_text("hi", encoding="utf-8")
        bak = rules.create_backup("src.txt")
        assert bak is not None
        assert bak.exists()

    def test_create_backup_nonexistent_returns_none(self, tmp_path):
        rules = ExecutionRules(workspace=tmp_path)
        assert rules.create_backup(tmp_path / "missing.txt") is None

    def test_restore_backup_returns_path(self, tmp_path):
        rules = ExecutionRules(workspace=tmp_path)
        src = tmp_path / "src.txt"
        src.write_text("v1", encoding="utf-8")
        rules.create_backup(src)
        # 修改文件
        src.write_text("v2", encoding="utf-8")
        # 恢复
        bak = rules.restore_backup(src)
        assert bak is not None
        assert src.read_text() == "v1"

    def test_restore_backup_no_backup_returns_none(self, tmp_path):
        rules = ExecutionRules(workspace=tmp_path)
        src = tmp_path / "src.txt"
        src.write_text("hi", encoding="utf-8")
        assert rules.restore_backup(src) is None

    def test_restore_backup_relative_path(self, tmp_path):
        rules = ExecutionRules(workspace=tmp_path)
        src = tmp_path / "src.txt"
        src.write_text("v1", encoding="utf-8")
        rules.create_backup("src.txt")
        src.write_text("v2", encoding="utf-8")
        bak = rules.restore_backup("src.txt")
        assert bak is not None


class TestValidateCodeSafety:
    """validate_code_safety — 危险模式检测"""

    def test_clean_code_no_issues(self):
        rules = ExecutionRules()
        code = "x = 1\ny = 2\n"
        assert rules.validate_code_safety(code) == []

    def test_detects_hardcoded_api_key(self):
        rules = ExecutionRules()
        code = 'api_key = "sk-1234567890abcdef"\n'
        issues = rules.validate_code_safety(code, "config.py")
        assert len(issues) == 1
        assert issues[0]["severity"] == "high"
        assert "API密钥" in issues[0]["description"]
        assert issues[0]["file"] == "config.py"
        assert "line" in issues[0]
        # violations 应该被追加
        assert len(rules.violations) == 1

    def test_detects_private_key(self):
        rules = ExecutionRules()
        code = "key = '-----BEGIN RSA PRIVATE KEY-----'\n"
        issues = rules.validate_code_safety(code)
        assert any("私钥" in i["description"] for i in issues)

    def test_detects_database_url(self):
        rules = ExecutionRules()
        code = 'url = "mongodb://user:pass@host:27017/db"\n'
        issues = rules.validate_code_safety(code)
        assert any("数据库" in i["description"] for i in issues)

    def test_detects_aws_key(self):
        rules = ExecutionRules()
        code = 'aws = "AKIAIOSFODNN7EXAMPLE"\n'
        issues = rules.validate_code_safety(code)
        assert any("AWS" in i["description"] for i in issues)

    def test_detects_os_system(self):
        rules = ExecutionRules()
        code = "os.system('rm -rf /')\n"
        issues = rules.validate_code_safety(code)
        assert any("os.system" in i["description"] for i in issues)
        assert issues[0]["severity"] == "medium"

    def test_detects_eval(self):
        rules = ExecutionRules()
        code = "eval('1+1')\n"
        issues = rules.validate_code_safety(code)
        assert any("eval" in i["description"] for i in issues)

    def test_detects_exec(self):
        rules = ExecutionRules()
        code = "exec('code')\n"
        issues = rules.validate_code_safety(code)
        assert any("exec" in i["description"] for i in issues)

    def test_detects_dunder_import(self):
        rules = ExecutionRules()
        code = "__import__('os')\n"
        issues = rules.validate_code_safety(code)
        assert any("__import__" in i["description"] for i in issues)

    def test_detects_pickle(self):
        rules = ExecutionRules()
        code = "pickle.loads(data)\n"
        issues = rules.validate_code_safety(code)
        assert any("pickle" in i["description"] for i in issues)

    def test_skips_comment_lines(self):
        rules = ExecutionRules()
        code = "# api_key = 'sk-1234567890abcdef'\n// os.system('rm')\n"
        issues = rules.validate_code_safety(code)
        # 注释行应被跳过
        assert issues == []

    def test_multiple_violations_accumulate(self):
        rules = ExecutionRules()
        code = (
            "api_key = 'sk-1234567890abcdef'\n"
            "eval('x')\n"
            "os.system('ls')\n"
        )
        issues = rules.validate_code_safety(code)
        assert len(issues) == 3
        assert len(rules.violations) == 3


class TestCheckPortAvailable:
    """check_port_available — 静态方法，调用 subprocess"""

    def test_windows_port_free(self, monkeypatch):
        """Windows 路径：netstat 返回无 LISTENING 行 → 端口空闲"""
        fake = MagicMock(stdout="", stderr="")
        monkeypatch.setattr("os.name", "nt")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)
        ok, occupied = ExecutionRules.check_port_available(9999)
        assert ok is True
        assert occupied == []

    def test_windows_port_occupied(self, monkeypatch):
        """Windows 路径：netstat 返回含 LISTENING 行 → 端口被占用"""
        fake = MagicMock(
            stdout="TCP 0.0.0.0:8080 LISTENING 1234\n", stderr=""
        )
        monkeypatch.setattr("os.name", "nt")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)
        ok, occupied = ExecutionRules.check_port_available(8080)
        assert ok is False
        assert len(occupied) == 1

    def test_unix_port_free(self, monkeypatch):
        """非 Windows 路径：lsof 返回无 LISTEN 行"""
        fake = MagicMock(stdout="", stderr="")
        monkeypatch.setattr("os.name", "posix")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)
        ok, occupied = ExecutionRules.check_port_available(9999)
        assert ok is True

    def test_unix_port_occupied(self, monkeypatch):
        # 注: lsof 匹配任何含 "LISTEN" 的行；header 不含 LISTEN
        fake = MagicMock(
            stdout="COMMAND PID USER NAME\nlsof 123 root LISTEN\n", stderr=""
        )
        monkeypatch.setattr("os.name", "posix")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)
        ok, occupied = ExecutionRules.check_port_available(8080)
        assert ok is False
        assert len(occupied) == 1

    def test_subprocess_error_returns_true(self, monkeypatch):
        """subprocess 异常时返回 True（放行）"""
        monkeypatch.setattr("os.name", "nt")
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
                subprocess.SubprocessError("boom")
            )
        )
        ok, occupied = ExecutionRules.check_port_available(8080)
        assert ok is True
        assert occupied == []

    def test_os_error_returns_true(self, monkeypatch):
        monkeypatch.setattr("os.name", "nt")
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("fail"))
        )
        ok, _ = ExecutionRules.check_port_available(8080)
        assert ok is True


class TestValidateJson:
    """validate_json 静态方法"""

    def test_valid_json_dict(self, tmp_path):
        f = tmp_path / "a.json"
        f.write_text('{"k": "v"}', encoding="utf-8")
        ok, msg = ExecutionRules.validate_json(f)
        assert ok is True
        assert "k" in msg

    def test_valid_json_array(self, tmp_path):
        f = tmp_path / "a.json"
        f.write_text("[1,2,3]", encoding="utf-8")
        ok, msg = ExecutionRules.validate_json(f)
        assert ok is True
        assert "array" in msg

    def test_invalid_json(self, tmp_path):
        f = tmp_path / "a.json"
        f.write_text("{bad json", encoding="utf-8")
        ok, msg = ExecutionRules.validate_json(f)
        assert ok is False
        assert "JSON" in msg

    def test_nonexistent_file(self, tmp_path):
        ok, msg = ExecutionRules.validate_json(tmp_path / "missing.json")
        assert ok is False
        assert "不存在" in msg

    def test_read_failure(self, tmp_path):
        """触发非 JSONDecodeError 的异常分支"""
        f = tmp_path / "a.json"
        # 制造读取异常：目录而非文件
        ok, msg = ExecutionRules.validate_json(tmp_path)
        assert ok is False


class TestViolationsReport:
    """get_violations_report"""

    def test_empty_violations(self):
        rules = ExecutionRules()
        assert rules.get_violations_report() == "✅ 无违规"

    def test_with_violations(self):
        rules = ExecutionRules()
        rules.violations = [
            {
                "severity": "high",
                "file": "a.py",
                "line": 1,
                "description": "desc1",
                "suggestion": "fix1",
            },
            {
                "severity": "medium",
                "file": "b.py",
                "line": 5,
                "description": "desc2",
                "suggestion": "fix2",
            },
        ]
        report = rules.get_violations_report()
        assert "违规报告" in report
        assert "[HIGH]" in report
        assert "[MEDIUM]" in report
        assert "a.py:1" in report
        assert "desc1" in report


# ══════════════════════════════════════════════════════════
# 数据模型测试
# ══════════════════════════════════════════════════════════

class TestDataModels:
    """TaskState / ValidationContract / BudgetTracker 默认值"""

    def test_task_state_defaults(self):
        t = TaskState(task_id="T1")
        assert t.task_id == "T1"
        assert t.status == "pending"
        assert t.title == ""
        assert t.steps == []
        assert t.progress == 0
        assert t.completed_items == []
        assert t.pending_items == []
        assert t.context == {}
        assert t.completed_at == 0.0

    def test_validation_contract_defaults(self):
        c = ValidationContract(task_id="T1")
        assert c.task_id == "T1"
        assert c.criteria == []
        assert c.status == "pending"
        assert c.score == 0.0
        assert c.created_by == "hermes"

    def test_budget_tracker_defaults(self):
        b = BudgetTracker(workflow_id="W1")
        assert b.workflow_id == "W1"
        assert b.token_limit == 100000
        assert b.tokens_used == 0
        assert b.cost_limit_usd == 5.0
        assert b.cost_used == 0.0
        assert b.status == "active"


# ══════════════════════════════════════════════════════════
# SharedState 测试
# ══════════════════════════════════════════════════════════

class TestSharedStateInit:
    """SharedState __init__ 创建目录结构"""

    def test_init_creates_directories(self, tmp_path, monkeypatch):
        new_dir = tmp_path / "shared"
        monkeypatch.setattr(
            "pycoder.server.services.execution_rules.SHARED_STATE_DIR", new_dir
        )
        ss = SharedState(task_id="X")
        assert new_dir.exists()
        assert (new_dir / "contracts").exists()
        assert (new_dir / "budgets").exists()
        assert (new_dir / "traces").exists()
        assert (new_dir / "workflow_checkpoints").exists()
        assert ss.task_id == "X"

    def test_init_generates_task_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pycoder.server.services.execution_rules.SHARED_STATE_DIR", tmp_path / "s"
        )
        ss = SharedState()
        assert ss.task_id.startswith("TASK-")


class TestTaskStateOps:
    """任务状态 CRUD"""

    def test_get_task_when_not_exists(self, shared_state):
        state = shared_state.get_task()
        assert state.task_id == "TEST-001"
        assert state.status == "pending"

    def test_save_task(self, shared_state):
        state = TaskState(task_id="TEST-001", status="executing", progress=50)
        shared_state.save_task(state)
        # 重新读取
        loaded = shared_state.get_task()
        assert loaded.status == "executing"
        assert loaded.progress == 50

    def test_update_task_status(self, shared_state):
        state = shared_state.update_task(status="executing", progress=30, title="hello")
        assert state.status == "executing"
        assert state.progress == 30
        assert state.title == "hello"
        # 验证已落盘
        reloaded = shared_state.get_task()
        assert reloaded.status == "executing"
        assert reloaded.title == "hello"

    def test_update_task_done_sets_progress_100(self, shared_state):
        state = shared_state.update_task(status="done")
        assert state.status == "done"
        assert state.progress == 100
        assert state.completed_at > 0

    def test_update_task_ignores_unknown_kwargs(self, shared_state):
        """未知字段应被忽略"""
        state = shared_state.update_task(unknown_field="x")
        assert not hasattr(state, "unknown_field")

    def test_add_step(self, shared_state):
        shared_state.add_step("step1", "done")
        state = shared_state.get_task()
        assert len(state.steps) == 1
        assert state.steps[0]["name"] == "step1"
        assert state.steps[0]["status"] == "done"
        assert "timestamp" in state.steps[0]


class TestValidationContractOps:
    """验证合约 CRUD"""

    def test_create_contract(self, shared_state):
        criteria = [{"name": "c1", "check": "exists", "weight": 1.0}]
        contract = shared_state.create_contract(criteria)
        assert contract.task_id == "TEST-001"
        assert contract.criteria == criteria
        assert contract.status == "pending"
        # 文件已落盘
        loaded = shared_state.get_contract()
        assert loaded is not None
        assert loaded.task_id == "TEST-001"
        assert loaded.criteria == criteria

    def test_get_contract_when_not_exists(self, shared_state):
        assert shared_state.get_contract() is None


class TestBudgetOps:
    """预算追踪"""

    def test_track_budget_new(self, shared_state):
        tracker = shared_state.track_budget("W1", tokens=100, cost=0.5)
        assert tracker.workflow_id == "W1"
        assert tracker.tokens_used == 100
        assert tracker.cost_used == 0.5
        assert tracker.status == "active"

    def test_track_budget_accumulate(self, shared_state):
        shared_state.track_budget("W1", tokens=100, cost=0.5)
        tracker = shared_state.track_budget("W1", tokens=200, cost=1.0)
        assert tracker.tokens_used == 300
        assert tracker.cost_used == 1.5
        assert tracker.status == "active"

    def test_track_budget_warning_threshold(self, shared_state):
        """cost_used >= 80% limit → warning"""
        # 默认 limit 5.0, 80% = 4.0
        tracker = shared_state.track_budget("W1", tokens=100, cost=4.0)
        assert tracker.status == "warning"

    def test_track_budget_exceeded_threshold(self, shared_state):
        """cost_used >= limit → exceeded"""
        tracker = shared_state.track_budget("W1", tokens=100, cost=5.0)
        assert tracker.status == "exceeded"


class TestCheckpointOps:
    """工作流检查点"""

    def test_save_and_load_checkpoint(self, shared_state):
        path = shared_state.save_checkpoint("stage1", {"data": "value"})
        assert path.exists()
        loaded = shared_state.load_checkpoint("stage1")
        assert loaded is not None
        assert loaded["stage"] == "stage1"
        assert loaded["data"] == {"data": "value"}
        assert "timestamp" in loaded

    def test_load_checkpoint_when_not_exists(self, shared_state):
        assert shared_state.load_checkpoint("missing") is None


class TestTraceOps:
    """追踪日志"""

    def test_trace_appends_ndjson(self, shared_state, tmp_path):
        shared_state.trace("event1", {"k": "v"})
        shared_state.trace("event2", {"k2": "v2"})
        # fixture 将 SHARED_STATE_DIR 重定向到 tmp_path / "shared_state"
        trace_path = tmp_path / "shared_state" / "traces" / "TEST-001.ndjson"
        assert trace_path.exists()
        lines = trace_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        # 每行是合法 JSON
        e1 = json.loads(lines[0])
        assert e1["event"] == "event1"
        assert e1["task_id"] == "TEST-001"
        assert e1["data"] == {"k": "v"}


# ══════════════════════════════════════════════════════════
# 常量测试
# ══════════════════════════════════════════════════════════

class TestConstants:
    """FIVE_STEP_WORKFLOW / FAILURE_MODES / SHARED_STATE_DIR"""

    def test_five_step_workflow_has_5_phases(self):
        assert len(FIVE_STEP_WORKFLOW) == 5
        for key in ["1_diagnose", "2_plan", "3_execute", "4_verify", "5_finalize"]:
            assert key in FIVE_STEP_WORKFLOW
            assert "name" in FIVE_STEP_WORKFLOW[key]
            assert "checks" in FIVE_STEP_WORKFLOW[key]

    def test_failure_modes_has_5(self):
        assert len(FAILURE_MODES) == 5
        for fm in FAILURE_MODES:
            assert "id" in fm
            assert "scenario" in fm
            assert "root_cause" in fm
            assert "prevention" in fm

    def test_shared_state_dir_is_path(self):
        assert isinstance(SHARED_STATE_DIR, Path)
