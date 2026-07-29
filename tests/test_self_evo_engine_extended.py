"""P3-A: SelfEvolutionEngine 补充测试

补充覆盖 engine.py 中未测试的核心方法:
  - _parse_fixes (3 种格式解析)
  - _build_scan_prompt (5 种任务类型)
  - get_task / list_tasks (任务查询)
  - 进化令牌系统: generate_evolution_token / _validate_evolution_token / clear_evolution_token
  - _is_core_modification / _load_github_token
  - _issues_to_prompt
  - _count_by_field / _extract_lessons
  - _apply_patch
  - _get_modified_in_session
  - _load_history / _save_history
  - _build_ast_scan_fallback / _collect_snapshot
  - _record_learning
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pycoder.capabilities.self_evo.engine import (
    CodeIssue,
    EvolutionRecord,
    EvolutionTask,
    FixProposal,
    SelfEvolutionEngine,
)

# ════════════════════════════════════════════════════════════
# 共享 fixture
# ════════════════════════════════════════════════════════════


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """临时项目目录（含 pycoder 子目录）"""
    pycoder = tmp_path / "pycoder"
    pycoder.mkdir()
    (pycoder / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


@pytest.fixture
def engine(tmp_project: Path, monkeypatch: pytest.MonkeyPatch) -> SelfEvolutionEngine:
    """创建引擎实例（隔离持久化路径与令牌文件）"""
    # 隔离持久化历史
    persist_path = tmp_project / "evolution_history.json"
    monkeypatch.setattr(
        "pycoder.capabilities.self_evo.engine.Path.home",
        lambda: tmp_project,
    )

    engine = SelfEvolutionEngine(project_root=tmp_project)
    engine._records.clear()
    engine._persist_path = persist_path

    # 隔离令牌文件
    token_file = tmp_project / "evolution_token.json"
    monkeypatch.setattr(SelfEvolutionEngine, "_EVOLUTION_TOKEN_FILE", token_file)
    monkeypatch.setattr(SelfEvolutionEngine, "_EVOLUTION_TOKEN_DIR", tmp_project)

    return engine


# ════════════════════════════════════════════════════════════
# _parse_fixes 测试
# ════════════════════════════════════════════════════════════


class TestParseFixes:
    """_parse_fixes 三种格式解析"""

    def test_empty_analysis_returns_empty(self, engine: SelfEvolutionEngine) -> None:
        result = engine._parse_fixes("")
        assert result == []

    def test_no_match_returns_empty(self, engine: SelfEvolutionEngine) -> None:
        result = engine._parse_fixes("这段文本没有任何修复块")
        assert result == []

    def test_format1_file_endfile_block(self, engine: SelfEvolutionEngine) -> None:
        """格式1: [FILE:path][END:FILE] 块"""
        analysis = """修复方案:

[FILE:pycoder/test_module.py]
```python
def hello():
    return "hello"
```
[END:FILE]
"""
        result = engine._parse_fixes(analysis)
        assert len(result) == 1
        assert result[0]["file"] == "pycoder/test_module.py"
        assert "def hello" in result[0]["modified"]

    def test_format1_without_code_block(self, engine: SelfEvolutionEngine) -> None:
        """格式1 不带 ```python 包裹的代码也接受"""
        analysis = """
[FILE:pycoder/plain.py]
x = 1
y = 2
[END:FILE]
"""
        result = engine._parse_fixes(analysis)
        assert len(result) == 1
        assert "x = 1" in result[0]["modified"]

    def test_format2_lang_path_block(self, engine: SelfEvolutionEngine) -> None:
        """格式2: ```python:path/to/file.py\\ncode\\n```"""
        analysis = """
修复:
```python:pycoder/format2.py
def add(a, b):
    return a + b
```
"""
        result = engine._parse_fixes(analysis)
        assert len(result) == 1
        assert result[0]["file"] == "pycoder/format2.py"
        assert "def add" in result[0]["modified"]

    def test_format2_typescript_block(self, engine: SelfEvolutionEngine) -> None:
        """格式2 也支持 typescript"""
        analysis = """
```typescript:src/index.ts
const x: number = 1;
```
"""
        result = engine._parse_fixes(analysis)
        assert len(result) == 1
        assert result[0]["file"] == "src/index.ts"

    def test_format3_file_comment(self, engine: SelfEvolutionEngine) -> None:
        """格式3: 文件名注释 + ```python 块"""
        # 先创建文件
        target = engine._project_root / "pycoder" / "format3.py"
        target.write_text("old_code = 1\n", encoding="utf-8")

        analysis = """
# file: pycoder/format3.py
```python
new_code = 2
```
"""
        result = engine._parse_fixes(analysis)
        assert len(result) == 1
        assert result[0]["file"] == "pycoder/format3.py"
        assert "new_code = 2" in result[0]["modified"]

    def test_format3_js_comment(self, engine: SelfEvolutionEngine) -> None:
        """格式3 支持 // 注释"""
        target = engine._project_root / "pycoder" / "format3_js.py"
        target.write_text("old = 0\n", encoding="utf-8")

        analysis = """
// file: pycoder/format3_js.py
```python
new = 1
```
"""
        result = engine._parse_fixes(analysis)
        assert len(result) == 1
        assert result[0]["file"] == "pycoder/format3_js.py"

    def test_format3_skipped_when_file_not_exists(self, engine: SelfEvolutionEngine) -> None:
        """格式3 文件不存在时跳过"""
        analysis = """
# file: pycoder/nonexistent.py
```python
new = 1
```
"""
        result = engine._parse_fixes(analysis)
        assert result == []

    def test_multiple_fixes_combined(self, engine: SelfEvolutionEngine) -> None:
        """多种格式混合"""
        target = engine._project_root / "pycoder" / "multi.py"
        target.write_text("old\n", encoding="utf-8")

        analysis = """
[FILE:pycoder/multi1.py]
```python
a = 1
```
[END:FILE]

```python:pycoder/multi2.py
b = 2
```

# file: pycoder/multi.py
```python
c = 3
```
"""
        result = engine._parse_fixes(analysis)
        files = {f["file"] for f in result}
        assert "pycoder/multi1.py" in files
        assert "pycoder/multi2.py" in files
        assert "pycoder/multi.py" in files

    def test_duplicate_file_only_kept_once(self, engine: SelfEvolutionEngine) -> None:
        """同文件多次出现，格式1优先，后续去重"""
        analysis = """
[FILE:pycoder/dup.py]
```python
a = 1
```
[END:FILE]

```python:pycoder/dup.py
b = 2
```
"""
        result = engine._parse_fixes(analysis)
        # 格式2 应被去重
        assert len(result) == 1
        assert result[0]["file"] == "pycoder/dup.py"

    def test_existing_file_includes_original(self, engine: SelfEvolutionEngine) -> None:
        """修改已存在的文件时，original 字段应包含原内容前100字符"""
        target = engine._project_root / "pycoder" / "exist.py"
        original_content = "old_code_line\n" * 5
        target.write_text(original_content, encoding="utf-8")

        analysis = """
[FILE:pycoder/exist.py]
```python
new_code = 1
```
[END:FILE]
"""
        result = engine._parse_fixes(analysis)
        assert len(result) == 1
        assert result[0]["original"] == original_content[:100]


# ════════════════════════════════════════════════════════════
# _build_scan_prompt 测试
# ════════════════════════════════════════════════════════════


class TestBuildScanPrompt:
    """_build_scan_prompt 构建扫描提示"""

    def test_custom_takes_priority(self, engine: SelfEvolutionEngine) -> None:
        """custom 参数优先级最高"""
        result = engine._build_scan_prompt("fix", "target", "请按特殊要求处理", "## 快照")
        assert "请按特殊要求处理" in result
        assert "## 快照" in result

    def test_fix_type(self, engine: SelfEvolutionEngine) -> None:
        result = engine._build_scan_prompt("fix", "", "", "## 项目代码")
        assert "Bug" in result or "bug" in result
        assert "## 项目代码" in result

    def test_optimize_type(self, engine: SelfEvolutionEngine) -> None:
        result = engine._build_scan_prompt("optimize", "", "", "## 项目代码")
        assert "性能" in result

    def test_security_type(self, engine: SelfEvolutionEngine) -> None:
        result = engine._build_scan_prompt("security", "", "", "## 项目代码")
        assert "安全" in result

    def test_quality_type(self, engine: SelfEvolutionEngine) -> None:
        result = engine._build_scan_prompt("quality", "", "", "## 项目代码")
        assert "重构" in result or "代码异味" in result

    def test_unknown_type_falls_back_to_fix(self, engine: SelfEvolutionEngine) -> None:
        """未知任务类型降级为 fix"""
        result = engine._build_scan_prompt("unknown_type", "", "", "## 项目代码")
        # 应与 fix 类型相同
        fix_result = engine._build_scan_prompt("fix", "", "", "## 项目代码")
        assert result == fix_result


# ════════════════════════════════════════════════════════════
# get_task / list_tasks 测试
# ════════════════════════════════════════════════════════════


class TestTaskQueries:
    """任务查询方法"""

    def test_get_task_empty_returns_none(self, engine: SelfEvolutionEngine) -> None:
        result = engine.get_task("nonexistent")
        assert result is None

    def test_get_task_finds_matching(self, engine: SelfEvolutionEngine) -> None:
        task = EvolutionTask(type="fix", description="测试任务")
        engine._tasks.append(task)

        result = engine.get_task(task.id)
        assert result is not None
        assert result["id"] == task.id
        assert result["description"] == "测试任务"

    def test_list_tasks_respects_limit(self, engine: SelfEvolutionEngine) -> None:
        for i in range(10):
            engine._tasks.append(EvolutionTask(type="fix", description=f"task-{i}"))

        result = engine.list_tasks(limit=3)
        assert len(result) == 3
        # 应取最后 3 个
        descriptions = [t["description"] for t in result]
        assert "task-9" in descriptions

    def test_list_tasks_empty(self, engine: SelfEvolutionEngine) -> None:
        result = engine.list_tasks()
        assert result == []


# ════════════════════════════════════════════════════════════
# 进化令牌系统测试
# ════════════════════════════════════════════════════════════


class TestEvolutionToken:
    """generate_evolution_token / _validate_evolution_token / clear_evolution_token"""

    def test_generate_token_returns_id(self, engine: SelfEvolutionEngine) -> None:
        token_id = SelfEvolutionEngine.generate_evolution_token(["pycoder/core.py"])
        assert isinstance(token_id, str)
        assert len(token_id) > 0

    def test_generate_token_writes_file(self, engine: SelfEvolutionEngine) -> None:
        """生成令牌应写入文件"""
        SelfEvolutionEngine.generate_evolution_token(["pycoder/core.py"])
        assert SelfEvolutionEngine._EVOLUTION_TOKEN_FILE.exists()

        data = json.loads(SelfEvolutionEngine._EVOLUTION_TOKEN_FILE.read_text(encoding="utf-8"))
        assert data["files"] == ["pycoder/core.py"]
        assert data["used"] is False
        assert data["expires_at"] > time.time()

    def test_validate_token_no_file_returns_false(self, engine: SelfEvolutionEngine) -> None:
        """令牌文件不存在时验证失败"""
        SelfEvolutionEngine.clear_evolution_token()
        assert SelfEvolutionEngine._validate_evolution_token("any.py") is False

    def test_validate_token_success(self, engine: SelfEvolutionEngine) -> None:
        """有效令牌验证成功并标记为已使用"""
        SelfEvolutionEngine.generate_evolution_token(["pycoder/core.py"])
        result = SelfEvolutionEngine._validate_evolution_token("pycoder/core.py")
        assert result is True

        # 第二次使用应失败（一次性令牌）
        result2 = SelfEvolutionEngine._validate_evolution_token("pycoder/core.py")
        assert result2 is False

    def test_validate_token_wrong_file_returns_false(self, engine: SelfEvolutionEngine) -> None:
        """令牌不匹配目标文件"""
        SelfEvolutionEngine.generate_evolution_token(["pycoder/core.py"])
        result = SelfEvolutionEngine._validate_evolution_token("pycoder/other.py")
        assert result is False

    def test_validate_token_expired(self, engine: SelfEvolutionEngine) -> None:
        """过期令牌应被删除并返回 False"""
        SelfEvolutionEngine.generate_evolution_token(["pycoder/core.py"])
        # 修改 expires_at 为过去时间
        data = json.loads(SelfEvolutionEngine._EVOLUTION_TOKEN_FILE.read_text(encoding="utf-8"))
        data["expires_at"] = time.time() - 100
        SelfEvolutionEngine._EVOLUTION_TOKEN_FILE.write_text(json.dumps(data), encoding="utf-8")

        result = SelfEvolutionEngine._validate_evolution_token("pycoder/core.py")
        assert result is False
        # 过期令牌文件应被删除
        assert not SelfEvolutionEngine._EVOLUTION_TOKEN_FILE.exists()

    def test_validate_token_corrupted_file_returns_false(self, engine: SelfEvolutionEngine) -> None:
        """损坏的令牌文件返回 False"""
        SelfEvolutionEngine._EVOLUTION_TOKEN_FILE.write_text("not valid json", encoding="utf-8")
        result = SelfEvolutionEngine._validate_evolution_token("pycoder/core.py")
        assert result is False

    def test_clear_token_when_not_exists(self, engine: SelfEvolutionEngine) -> None:
        """清除不存在的令牌不报错"""
        SelfEvolutionEngine.clear_evolution_token()
        # 再次清除也不应报错
        SelfEvolutionEngine.clear_evolution_token()

    def test_clear_token_when_exists(self, engine: SelfEvolutionEngine) -> None:
        """清除已存在的令牌"""
        SelfEvolutionEngine.generate_evolution_token(["pycoder/x.py"])
        assert SelfEvolutionEngine._EVOLUTION_TOKEN_FILE.exists()

        SelfEvolutionEngine.clear_evolution_token()
        assert not SelfEvolutionEngine._EVOLUTION_TOKEN_FILE.exists()


# ════════════════════════════════════════════════════════════
# _is_core_modification 测试
# ════════════════════════════════════════════════════════════


class TestIsCoreModification:
    """_is_core_modification 检测核心文件修改"""

    def test_empty_fixes_returns_false(self, engine: SelfEvolutionEngine) -> None:
        assert engine._is_core_modification([]) is False

    def test_core_file_returns_true(self, engine: SelfEvolutionEngine) -> None:
        """修改 self_evolution.py 应识别为核心修改"""
        fixes = [{"file": "pycoder/server/self_evolution.py"}]
        assert engine._is_core_modification(fixes) is True

    def test_evolution_file_returns_true(self, engine: SelfEvolutionEngine) -> None:
        """修改 evolution 相关文件应识别为核心修改"""
        # CORE_FILE_PATTERNS = ["self_evolution", "evolution.py", "self_optimizer.py"]
        fixes = [{"file": "pycoder/capabilities/evolution.py"}]
        assert engine._is_core_modification(fixes) is True

    def test_self_optimizer_file_returns_true(self, engine: SelfEvolutionEngine) -> None:
        """self_optimizer.py 也是核心文件"""
        fixes = [{"file": "pycoder/capabilities/self_optimizer.py"}]
        assert engine._is_core_modification(fixes) is True

    def test_non_core_file_returns_false(self, engine: SelfEvolutionEngine) -> None:
        fixes = [{"file": "pycoder/server/app.py"}]
        assert engine._is_core_modification(fixes) is False

    def test_mixed_fixes_returns_true(self, engine: SelfEvolutionEngine) -> None:
        """只要有一个核心文件就返回 True"""
        fixes = [
            {"file": "pycoder/server/app.py"},
            {"file": "pycoder/server/self_evolution.py"},
        ]
        assert engine._is_core_modification(fixes) is True

    def test_fix_without_file_key(self, engine: SelfEvolutionEngine) -> None:
        """修复项缺少 file 键不应报错"""
        fixes = [{"other": "value"}]
        assert engine._is_core_modification(fixes) is False


# ════════════════════════════════════════════════════════════
# _load_github_token 测试
# ════════════════════════════════════════════════════════════


class TestLoadGithubToken:
    """_load_github_token 加载 GitHub token"""

    def test_no_file_no_env_returns_empty(
        self,
        engine: SelfEvolutionEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """无文件无环境变量返回空"""
        monkeypatch.setattr(engine, "GITHUB_TOKEN_FILE", engine._project_root / "nonexistent_token")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert engine._load_github_token() == ""

    def test_reads_from_file(
        self,
        engine: SelfEvolutionEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """从文件读取 token"""
        token_file = engine._project_root / "github_token.txt"
        token_file.write_text("ghp_file_token_123\n", encoding="utf-8")
        monkeypatch.setattr(engine, "GITHUB_TOKEN_FILE", token_file)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        result = engine._load_github_token()
        assert result == "ghp_file_token_123"

    def test_falls_back_to_env(
        self,
        engine: SelfEvolutionEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """文件不存在时降级到环境变量"""
        monkeypatch.setattr(engine, "GITHUB_TOKEN_FILE", engine._project_root / "nonexistent")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_env_token")
        assert engine._load_github_token() == "ghp_env_token"


# ════════════════════════════════════════════════════════════
# _issues_to_prompt 测试
# ════════════════════════════════════════════════════════════


class TestIssuesToPrompt:
    """_issues_to_prompt 将扫描结果转为提示词"""

    def test_empty_issues(self, engine: SelfEvolutionEngine) -> None:
        result = engine._issues_to_prompt([], "fix")
        assert "0" in result
        assert "[FILE:" in result  # 包含格式说明

    def test_single_issue(self, engine: SelfEvolutionEngine) -> None:
        issues = [
            CodeIssue(
                file="pycoder/x.py",
                line=10,
                severity="high",
                issue_type="bug",
                title="裸 except",
                description="使用了裸 except 吞掉异常",
                suggestion="改用 except Exception",
            )
        ]
        result = engine._issues_to_prompt(issues, "fix")
        assert "pycoder/x.py" in result
        assert "裸 except" in result
        assert "1" in result  # 1 个问题

    def test_multiple_issues(self, engine: SelfEvolutionEngine) -> None:
        issues = [
            CodeIssue(
                file="pycoder/a.py",
                line=1,
                severity="low",
                issue_type="style",
                title="问题 A",
            ),
            CodeIssue(
                file="pycoder/b.py",
                line=2,
                severity="critical",
                issue_type="security",
                title="问题 B",
            ),
        ]
        result = engine._issues_to_prompt(issues, "fix")
        assert "pycoder/a.py" in result
        assert "pycoder/b.py" in result
        assert "问题 A" in result
        assert "问题 B" in result


# ════════════════════════════════════════════════════════════
# _count_by_field 测试
# ════════════════════════════════════════════════════════════


class TestCountByField:
    """_count_by_field 按字段统计"""

    def test_empty_records_returns_empty(self, engine: SelfEvolutionEngine) -> None:
        result = engine._count_by_field("action")
        assert result == {}

    def test_count_by_action(self, engine: SelfEvolutionEngine) -> None:
        engine._records.append(EvolutionRecord(action="fix", file="a.py", success=True))
        engine._records.append(EvolutionRecord(action="fix", file="b.py", success=False))
        engine._records.append(EvolutionRecord(action="optimize", file="c.py"))

        result = engine._count_by_field("action")
        assert result == {"fix": 2, "optimize": 1}

    def test_count_by_issue_type(self, engine: SelfEvolutionEngine) -> None:
        engine._records.append(EvolutionRecord(issue_type="bug"))
        engine._records.append(EvolutionRecord(issue_type="bug"))
        engine._records.append(EvolutionRecord(issue_type="security"))

        result = engine._count_by_field("issue_type")
        assert result == {"bug": 2, "security": 1}

    def test_count_nonexistent_field_returns_empty(self, engine: SelfEvolutionEngine) -> None:
        """字段不存在返回空字典"""
        engine._records.append(EvolutionRecord(action="fix"))
        result = engine._count_by_field("nonexistent_field")
        assert result == {}


# ════════════════════════════════════════════════════════════
# _extract_lessons 测试
# ════════════════════════════════════════════════════════════


class TestExtractLessons:
    """_extract_lessons 提取常见教训"""

    def test_empty_records_returns_empty(self) -> None:
        result = SelfEvolutionEngine._extract_lessons([])
        assert result == []

    def test_extracts_unique_lessons(self) -> None:
        records = [
            EvolutionRecord(lessons="lesson-1"),
            EvolutionRecord(lessons="lesson-2"),
            EvolutionRecord(lessons="lesson-1"),  # 重复
        ]
        result = SelfEvolutionEngine._extract_lessons(records)
        assert "lesson-1" in result
        assert "lesson-2" in result
        # 不重复
        assert len(result) == 2

    def test_keeps_last_5(self) -> None:
        """只保留最后 5 条"""
        records = [EvolutionRecord(lessons=f"lesson-{i}") for i in range(10)]
        result = SelfEvolutionEngine._extract_lessons(records)
        assert len(result) == 5
        # 应是最后 5 条
        assert "lesson-9" in result
        assert "lesson-5" in result
        assert "lesson-4" not in result

    def test_skips_empty_lessons(self) -> None:
        records = [
            EvolutionRecord(lessons=""),
            EvolutionRecord(lessons="real-lesson"),
            EvolutionRecord(),  # 默认空
        ]
        result = SelfEvolutionEngine._extract_lessons(records)
        assert result == ["real-lesson"]


# ════════════════════════════════════════════════════════════
# _apply_patch 测试
# ════════════════════════════════════════════════════════════


class TestApplyPatch:
    """_apply_patch 应用修复补丁"""

    def test_empty_old_code_returns_without_change(
        self, engine: SelfEvolutionEngine, tmp_path: Path
    ) -> None:
        """old_code 或 new_code 为空时不操作"""
        target = tmp_path / "target.py"
        target.write_text("x = 1\n", encoding="utf-8")

        proposal = FixProposal(
            issue=CodeIssue(file="x", line=1, severity="low", issue_type="style", title="t"),
            action="replace",
            file_path=str(target),
            old_code="",
            new_code="y = 2",
        )
        engine._apply_patch(proposal)
        assert target.read_text(encoding="utf-8") == "x = 1\n"

    def test_file_not_exists_returns_silently(self, engine: SelfEvolutionEngine) -> None:
        """文件不存在时静默返回"""
        proposal = FixProposal(
            issue=CodeIssue(file="x", line=1, severity="low", issue_type="style", title="t"),
            action="replace",
            file_path="/nonexistent/path/file.py",
            old_code="old",
            new_code="new",
        )
        # 不应抛出异常
        engine._apply_patch(proposal)

    def test_replace_success(self, engine: SelfEvolutionEngine, tmp_path: Path) -> None:
        """成功替换内容"""
        target = tmp_path / "patchable.py"
        target.write_text("def foo():\n    return 1\n", encoding="utf-8")

        proposal = FixProposal(
            issue=CodeIssue(file="x", line=1, severity="low", issue_type="style", title="t"),
            action="replace",
            file_path=str(target),
            old_code="return 1",
            new_code="return 2",
        )
        engine._apply_patch(proposal)
        assert "return 2" in target.read_text(encoding="utf-8")
        assert "return 1" not in target.read_text(encoding="utf-8")

    def test_old_code_not_in_file_no_change(
        self, engine: SelfEvolutionEngine, tmp_path: Path
    ) -> None:
        """old_code 不在文件中时不修改"""
        target = tmp_path / "no_match.py"
        original = "x = 1\n"
        target.write_text(original, encoding="utf-8")

        proposal = FixProposal(
            issue=CodeIssue(file="x", line=1, severity="low", issue_type="style", title="t"),
            action="replace",
            file_path=str(target),
            old_code="nonexistent_code",
            new_code="y = 2",
        )
        engine._apply_patch(proposal)
        assert target.read_text(encoding="utf-8") == original

    def test_replace_only_first_occurrence(
        self, engine: SelfEvolutionEngine, tmp_path: Path
    ) -> None:
        """仅替换第一处出现"""
        target = tmp_path / "multi.py"
        target.write_text("a = 1\na = 1\n", encoding="utf-8")

        proposal = FixProposal(
            issue=CodeIssue(file="x", line=1, severity="low", issue_type="style", title="t"),
            action="replace",
            file_path=str(target),
            old_code="a = 1",
            new_code="a = 2",
        )
        engine._apply_patch(proposal)
        content = target.read_text(encoding="utf-8")
        assert content.count("a = 2") == 1
        assert content.count("a = 1") == 1


# ════════════════════════════════════════════════════════════
# _get_modified_in_session 测试
# ════════════════════════════════════════════════════════════


class TestGetModifiedInSession:
    """_get_modified_in_session 获取当前会话已修改文件"""

    def test_returns_list_on_success(
        self,
        engine: SelfEvolutionEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """成功时返回文件列表"""
        mock_run = MagicMock()
        mock_run.stdout = "file1.py\nfile2.py\n"
        monkeypatch.setattr(subprocess, "run", MagicMock(return_value=mock_run))

        result = engine._get_modified_in_session()
        assert "file1.py" in result
        assert "file2.py" in result

    def test_handles_empty_output(
        self,
        engine: SelfEvolutionEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """空输出返回空列表"""
        mock_run = MagicMock()
        mock_run.stdout = ""
        monkeypatch.setattr(subprocess, "run", MagicMock(return_value=mock_run))

        result = engine._get_modified_in_session()
        assert result == []

    def test_handles_subprocess_error(
        self,
        engine: SelfEvolutionEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """subprocess 异常返回空列表"""

        def raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="git", timeout=10)

        monkeypatch.setattr(subprocess, "run", raise_timeout)

        result = engine._get_modified_in_session()
        assert result == []

    def test_handles_os_error(
        self,
        engine: SelfEvolutionEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """OSError 返回空列表"""

        def raise_oserror(*args, **kwargs):
            raise OSError("command not found")

        monkeypatch.setattr(subprocess, "run", raise_oserror)

        result = engine._get_modified_in_session()
        assert result == []


# ════════════════════════════════════════════════════════════
# _load_history / _save_history 测试
# ════════════════════════════════════════════════════════════


class TestHistoryPersistence:
    """_load_history / _save_history 持久化"""

    def test_load_history_nonexistent_file(
        self, engine: SelfEvolutionEngine, tmp_path: Path
    ) -> None:
        """文件不存在时静默返回"""
        engine._persist_path = tmp_path / "nonexistent.json"
        engine._records.clear()
        engine._load_history()
        assert engine._records == []

    def test_load_history_corrupted_file(self, engine: SelfEvolutionEngine, tmp_path: Path) -> None:
        """损坏的 JSON 文件静默失败"""
        persist = tmp_path / "history.json"
        persist.write_text("not valid json", encoding="utf-8")
        engine._persist_path = persist
        engine._records.clear()
        engine._load_history()
        assert engine._records == []

    def test_load_history_valid_file(self, engine: SelfEvolutionEngine, tmp_path: Path) -> None:
        """有效 JSON 加载成功"""
        persist = tmp_path / "history.json"
        records_data = [
            {
                "timestamp": 1000,
                "action": "fix",
                "issue_type": "bug",
                "file": "a.py",
                "success": True,
                "fix_description": "修复了",
                "test_result": "passed",
                "lessons": "lesson-1",
            }
        ]
        persist.write_text(json.dumps(records_data, ensure_ascii=False), encoding="utf-8")
        engine._persist_path = persist
        engine._records.clear()
        engine._load_history()
        assert len(engine._records) == 1
        assert engine._records[0].action == "fix"
        assert engine._records[0].file == "a.py"
        assert engine._records[0].success is True

    def test_save_history_creates_file(self, engine: SelfEvolutionEngine, tmp_path: Path) -> None:
        """保存历史创建文件"""
        persist = tmp_path / "saved_history.json"
        engine._persist_path = persist
        engine._records.append(
            EvolutionRecord(action="fix", file="a.py", success=True, lessons="learned")
        )

        engine._save_history()
        assert persist.exists()

        data = json.loads(persist.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["action"] == "fix"
        assert data[0]["lessons"] == "learned"

    def test_save_history_handles_error(self, engine: SelfEvolutionEngine, tmp_path: Path) -> None:
        """保存到不可写路径静默失败"""
        engine._persist_path = tmp_path / "no_permission" / "deep" / "history.json"
        # 父目录不存在且无法创建（mock）
        with patch.object(Path, "mkdir", side_effect=OSError("denied")):
            engine._save_history()  # 不应抛出异常

    def test_save_and_load_roundtrip(self, engine: SelfEvolutionEngine, tmp_path: Path) -> None:
        """保存后再加载应一致"""
        persist = tmp_path / "roundtrip.json"
        engine._persist_path = persist
        engine._records.append(
            EvolutionRecord(
                action="optimize",
                issue_type="performance",
                file="x.py",
                success=True,
                fix_description="优化",
                test_result="passed",
                lessons="optimization-lesson",
            )
        )
        engine._save_history()

        # 新引擎加载
        engine._records.clear()
        engine._load_history()
        assert len(engine._records) == 1
        assert engine._records[0].action == "optimize"
        assert engine._records[0].issue_type == "performance"


# ════════════════════════════════════════════════════════════
# _build_ast_scan_fallback 测试
# ════════════════════════════════════════════════════════════


class TestBuildAstScanFallback:
    """_build_ast_scan_fallback 离线降级扫描"""

    def test_no_issues_returns_empty(self, engine: SelfEvolutionEngine) -> None:
        engine._last_issues = []
        assert engine._build_ast_scan_fallback() == ""

    def test_with_critical_issues(self, engine: SelfEvolutionEngine) -> None:
        """有严重问题时输出 critical 部分"""
        engine._last_issues = [
            CodeIssue(
                file="a.py",
                line=10,
                severity="critical",
                issue_type="bug",
                title="语法错误",
                suggestion="修复语法",
            )
        ]
        result = engine._build_ast_scan_fallback()
        assert "严重问题" in result
        assert "a.py" in result
        assert "语法错误" in result
        assert "修复语法" in result

    def test_with_high_issues(self, engine: SelfEvolutionEngine) -> None:
        engine._last_issues = [
            CodeIssue(
                file="b.py",
                line=20,
                severity="high",
                issue_type="security",
                title="注入风险",
            )
        ]
        result = engine._build_ast_scan_fallback()
        assert "高风险" in result
        assert "b.py" in result

    def test_with_medium_issues(self, engine: SelfEvolutionEngine) -> None:
        engine._last_issues = [
            CodeIssue(
                file="c.py",
                line=30,
                severity="medium",
                issue_type="style",
                title="命名不规范",
            )
        ]
        result = engine._build_ast_scan_fallback()
        assert "中等" in result
        assert "1" in result  # 1 个中等

    def test_includes_template_format(self, engine: SelfEvolutionEngine) -> None:
        """输出应包含修复模板格式说明"""
        engine._last_issues = [
            CodeIssue(file="x.py", line=1, severity="low", issue_type="style", title="x")
        ]
        result = engine._build_ast_scan_fallback()
        assert "修复方案" in result or "修复格式" in result
        assert "```json" in result


# ════════════════════════════════════════════════════════════
# _collect_snapshot 测试
# ════════════════════════════════════════════════════════════


class TestCollectSnapshot:
    """_collect_snapshot 收集项目结构快照"""

    def test_empty_target_uses_default_dirs(self, engine: SelfEvolutionEngine) -> None:
        """空 target 使用默认目录 (server, capabilities)"""
        # 创建默认目录和文件
        server_dir = engine._project_root / "pycoder" / "server"
        server_dir.mkdir(parents=True, exist_ok=True)
        (server_dir / "app.py").write_text("x = 1\n", encoding="utf-8")

        result = engine._collect_snapshot("")
        assert "项目结构快照" in result
        assert "app.py" in result

    def test_specific_target(self, engine: SelfEvolutionEngine) -> None:
        """指定 target"""
        # 创建目标文件
        target_dir = engine._project_root / "pycoder" / "modules"
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "mod.py").write_text("y = 2\n", encoding="utf-8")

        result = engine._collect_snapshot("modules")
        assert "mod.py" in result

    def test_skips_self_evolution_files(self, engine: SelfEvolutionEngine) -> None:
        """跳过 self_evolution 文件"""
        server_dir = engine._project_root / "pycoder" / "server"
        server_dir.mkdir(parents=True, exist_ok=True)
        (server_dir / "app.py").write_text("x = 1\n", encoding="utf-8")
        (server_dir / "self_evolution.py").write_text("secret = 1\n", encoding="utf-8")

        result = engine._collect_snapshot("")
        assert "app.py" in result
        assert "self_evolution.py" not in result

    def test_truncates_large_files(self, engine: SelfEvolutionEngine) -> None:
        """大文件应被截断"""
        server_dir = engine._project_root / "pycoder" / "server"
        server_dir.mkdir(parents=True, exist_ok=True)
        large_content = "x = 1\n" * 2000  # > 8000 字符
        (server_dir / "large.py").write_text(large_content, encoding="utf-8")

        result = engine._collect_snapshot("")
        assert "前 8000 字节" in result

    def test_handles_unreadable_file(
        self,
        engine: SelfEvolutionEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """不可读文件静默跳过"""
        server_dir = engine._project_root / "pycoder" / "server"
        server_dir.mkdir(parents=True, exist_ok=True)
        (server_dir / "app.py").write_text("x = 1\n", encoding="utf-8")

        # mock read_text 抛 UnicodeDecodeError
        original_read_text = Path.read_text

        def fake_read_text(self, *args, **kwargs):
            if self.name == "app.py":
                raise UnicodeDecodeError("utf-8", b"", 0, 1, "invalid")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", fake_read_text)

        result = engine._collect_snapshot("")
        # 不应抛出异常
        assert "项目结构快照" in result


# ════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════
# _record_learning 测试
# ════════════════════════════════════════════════════════════


class TestRecordLearning:
    """_record_learning 记录学习经验"""

    def test_handles_import_error_silently(self, engine: SelfEvolutionEngine) -> None:
        """LearningEngine 不可用时静默失败"""
        task = EvolutionTask(type="fix", description="测试任务", status="done")
        fixes = [{"file": "x.py", "modified": "y = 1"}]

        # 不应抛出异常
        engine._record_learning(task, fixes, test_passed=True, test_output="")
        # 内部调用被 try/except 包裹

    def test_calls_learning_engine_when_available(self, engine: SelfEvolutionEngine) -> None:
        """LearningEngine 可用时应调用 on_task_complete"""
        task = EvolutionTask(type="fix", description="测试任务", status="done")
        fixes = [{"file": "x.py", "modified": "y = 1"}]

        # mock importlib.import_module 返回模拟模块
        mock_engine = MagicMock()
        mock_module = MagicMock()
        mock_module.get_learning_engine = MagicMock(return_value=mock_engine)

        with patch("importlib.import_module", return_value=mock_module):
            engine._record_learning(task, fixes, test_passed=True, test_output="", quality_score=80)

        mock_engine.on_task_complete.assert_called_once()
        call_kwargs = mock_engine.on_task_complete.call_args
        assert call_kwargs.kwargs["task_id"] == task.id
        assert call_kwargs.kwargs["outcome"] == "success"
        assert call_kwargs.kwargs["test_passed"] is True
        assert call_kwargs.kwargs["quality_score"] == 80

    def test_outcome_rolled_back_when_status_rolled_back(self, engine: SelfEvolutionEngine) -> None:
        """task.status='rolled_back' 时 outcome='rolled_back'"""
        task = EvolutionTask(type="fix", description="失败任务", status="rolled_back")
        fixes = [{"file": "x.py", "modified": "y = 1"}]

        mock_engine = MagicMock()
        mock_module = MagicMock()
        mock_module.get_learning_engine = MagicMock(return_value=mock_engine)

        with patch("importlib.import_module", return_value=mock_module):
            engine._record_learning(task, fixes, test_passed=False, test_output="error")

        call_kwargs = mock_engine.on_task_complete.call_args
        assert call_kwargs.kwargs["outcome"] == "rolled_back"

    def test_outcome_failure_when_test_failed(self, engine: SelfEvolutionEngine) -> None:
        """测试失败时 outcome='failure'"""
        task = EvolutionTask(type="fix", description="测试失败", status="done")
        fixes = [{"file": "x.py", "modified": "y = 1"}]

        mock_engine = MagicMock()
        mock_module = MagicMock()
        mock_module.get_learning_engine = MagicMock(return_value=mock_engine)

        with patch("importlib.import_module", return_value=mock_module):
            engine._record_learning(task, fixes, test_passed=False, test_output="test failed")

        call_kwargs = mock_engine.on_task_complete.call_args
        assert call_kwargs.kwargs["outcome"] == "failure"

    def test_records_error_msg_on_failure(self, engine: SelfEvolutionEngine) -> None:
        """失败时记录错误信息"""
        task = EvolutionTask(type="fix", description="测试", status="done")
        fixes = [{"file": "x.py", "modified": "y = 1"}]

        mock_engine = MagicMock()
        mock_module = MagicMock()
        mock_module.get_learning_engine = MagicMock(return_value=mock_engine)

        with patch("importlib.import_module", return_value=mock_module):
            engine._record_learning(
                task,
                fixes,
                test_passed=False,
                test_output="specific error message",
            )

        call_kwargs = mock_engine.on_task_complete.call_args
        assert call_kwargs.kwargs["error_msg"] == "specific error message"


# ════════════════════════════════════════════════════════════
# 额外的 _apply_fix 测试（V2 路径）
# ════════════════════════════════════════════════════════════


class TestApplyFixV2:
    """_apply_fix 应用单个修复到文件

    注意：所有测试都通过 mock importlib.import_module 阻止
    version_snapshot 模块加载，避免触发重 IO 操作导致测试挂起。
    """

    @pytest.fixture(autouse=True)
    def _mock_version_snapshot(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """自动 mock version_snapshot 导入，触发 ImportError 跳过快照逻辑"""
        import importlib

        real_import = importlib.import_module

        def fake_import(name: str, *args: Any, **kwargs: Any):
            if "version_snapshot" in name:
                raise ImportError(f"mocked unavailable: {name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", fake_import)

    @pytest.mark.asyncio
    async def test_non_pycoder_file_rejected(
        self, engine: SelfEvolutionEngine, tmp_path: Path
    ) -> None:
        """拒绝修改非 pycoder 文件"""
        # 临时修改 project_root 以创建非 pycoder 文件路径
        outside = tmp_path / "outside" / "file.py"
        outside.parent.mkdir()
        outside.write_text("x = 1\n", encoding="utf-8")

        # 修复路径相对于 project_root，但实际路径在 pycoder 外
        # 通过创建特殊路径模拟
        fix = {
            "file": "outside/file.py",
            "modified": "y = 2\n",
        }
        success, err = await engine._apply_fix(fix)
        # 由于路径不含 pycoder，应被拒绝
        assert success is False

    @pytest.mark.asyncio
    async def test_nonexistent_file_rejected(self, engine: SelfEvolutionEngine) -> None:
        """目标文件不存在返回失败"""
        fix = {
            "file": "pycoder/nonexistent_target.py",
            "modified": "y = 2\n",
        }
        success, err = await engine._apply_fix(fix)
        assert success is False
        assert "不存在" in err or "not exist" in err.lower()

    @pytest.mark.asyncio
    async def test_empty_modified_rejected(self, engine: SelfEvolutionEngine) -> None:
        """空的 modified 内容被拒绝"""
        target = engine._project_root / "pycoder" / "target.py"
        target.write_text("x = 1\n", encoding="utf-8")

        fix = {"file": "pycoder/target.py", "modified": ""}
        success, err = await engine._apply_fix(fix)
        assert success is False
        assert "空" in err

    @pytest.mark.asyncio
    async def test_core_file_rejected_without_v2(self, engine: SelfEvolutionEngine) -> None:
        """核心文件（无 v2 引擎）被拒绝"""
        # engine.v2 是 None
        target = engine._project_root / "pycoder" / "server" / "self_evolution.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x = 1\n", encoding="utf-8")

        fix = {
            "file": "pycoder/server/self_evolution.py",
            "modified": "y = 2\n",
        }
        success, err = await engine._apply_fix(fix)
        assert success is False
        assert "核心文件" in err or "core" in err.lower()

    @pytest.mark.asyncio
    async def test_search_replace_success(self, engine: SelfEvolutionEngine) -> None:
        """search/replace 模式成功"""
        target = engine._project_root / "pycoder" / "searchable.py"
        target.write_text("def foo():\n    return 1\n", encoding="utf-8")

        fix = {
            "file": "pycoder/searchable.py",
            "search": "return 1",
            "modified": "return 2",
        }
        success, err = await engine._apply_fix(fix)
        assert success is True
        assert "return 2" in target.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_placeholder_rejected(self, engine: SelfEvolutionEngine) -> None:
        """包含占位符的修改被拒绝"""
        target = engine._project_root / "pycoder" / "placeholder.py"
        target.write_text("x = 1\n" * 250, encoding="utf-8")  # 大文件

        # 制造一个占位符
        fix = {
            "file": "pycoder/placeholder.py",
            "modified": "# ... 前面代码\nnew_code = 1\n",
        }
        success, err = await engine._apply_fix(fix)
        assert success is False
        assert "占位符" in err

    @pytest.mark.asyncio
    async def test_syntax_error_rejected(self, engine: SelfEvolutionEngine) -> None:
        """语法错误的修改被拒绝"""
        target = engine._project_root / "pycoder" / "syntax_target.py"
        target.write_text("x = 1\n", encoding="utf-8")

        fix = {
            "file": "pycoder/syntax_target.py",
            "modified": "def broken(\n",  # 语法错误
        }
        success, err = await engine._apply_fix(fix)
        assert success is False
        assert "语法错误" in err

    @pytest.mark.asyncio
    async def test_successful_write(self, engine: SelfEvolutionEngine) -> None:
        """正常写入成功"""
        target = engine._project_root / "pycoder" / "writable.py"
        target.write_text("x = 1\n", encoding="utf-8")

        fix = {
            "file": "pycoder/writable.py",
            "modified": "y = 2\nz = 3\n",
        }
        success, err = await engine._apply_fix(fix)
        assert success is True
        content = target.read_text(encoding="utf-8")
        assert "y = 2" in content
        assert "z = 3" in content

    @pytest.mark.asyncio
    async def test_import_count_check(self, engine: SelfEvolutionEngine) -> None:
        """导入数量异常检测"""
        # 原始文件有 6 个 import，修改后为 0
        target = engine._project_root / "pycoder" / "imports.py"
        original = (
            "import os\nimport sys\nimport json\n"
            "import re\nimport time\nimport asyncio\n"
            "x = 1\n"
        )
        target.write_text(original, encoding="utf-8")

        fix = {
            "file": "pycoder/imports.py",
            "modified": "x = 1\n",  # 完全无 import
        }
        success, err = await engine._apply_fix(fix)
        assert success is False
        assert "import" in err.lower()

    @pytest.mark.asyncio
    async def test_handles_exception_returns_false(
        self,
        engine: SelfEvolutionEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """异常情况返回 False"""
        target = engine._project_root / "pycoder" / "exc.py"
        target.write_text("x = 1\n", encoding="utf-8")

        # 让 read_text 抛异常
        def raise_exc(*args, **kwargs):
            raise OSError("disk error")

        monkeypatch.setattr(Path, "read_text", raise_exc)

        fix = {"file": "pycoder/exc.py", "modified": "y = 2\n"}
        success, err = await engine._apply_fix(fix)
        assert success is False
        assert "disk error" in err
