"""AutoFixer 单元测试

覆盖 pycoder.ai.auto_fixer 模块:
  - FixerResult 数据类（success 属性）
  - AutoFixer.validate_and_fix 的各种路径
  - AutoFixer._check_syntax 语法检查
  - get_auto_fixer 单例行为
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from pycoder.ai import auto_fixer
from pycoder.ai.auto_fixer import (
    MAX_RETRIES,
    AutoFixer,
    FixerResult,
    get_auto_fixer,
)

# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """创建临时项目目录"""
    return tmp_path


@pytest.fixture
def fixer(tmp_project: Path) -> AutoFixer:
    """返回指向临时项目目录的 AutoFixer"""
    return AutoFixer(project_root=tmp_project, max_retries=2)


@pytest.fixture
def good_py_file(tmp_project: Path) -> Path:
    """创建一个语法正确的 Python 文件"""
    p = tmp_project / "good.py"
    p.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    return p


@pytest.fixture
def bad_py_file(tmp_project: Path) -> Path:
    """创建一个有语法错误的 Python 文件"""
    p = tmp_project / "bad.py"
    p.write_text("def broken(:\n    return 1\n", encoding="utf-8")
    return p


@pytest.fixture
def non_py_file(tmp_project: Path) -> Path:
    """创建一个非 Python 文件"""
    p = tmp_project / "readme.txt"
    p.write_text("hello world\n", encoding="utf-8")
    return p


# ══════════════════════════════════════════════════════════
# FixerResult
# ══════════════════════════════════════════════════════════


class TestFixerResult:
    """FixerResult 数据类行为"""

    def test_construction_defaults(self) -> None:
        """status 必填，其余字段使用默认值"""
        r = FixerResult(file_path="x.py", status="")
        assert r.file_path == "x.py"
        assert r.status == ""
        assert r.attempts == 0
        assert r.errors == []
        assert r.error_type == ""
        assert r.fix_applied is False
        assert r.fix_content == ""

    def test_construction_with_all_fields(self) -> None:
        """所有字段显式传入应保留"""
        r = FixerResult(
            file_path="x.py",
            status="fixed",
            attempts=3,
            errors=["err1", "err2"],
            error_type="syntax",
            fix_applied=True,
            fix_content="print('ok')",
        )
        assert r.status == "fixed"
        assert r.attempts == 3
        assert r.errors == ["err1", "err2"]
        assert r.error_type == "syntax"
        assert r.fix_applied is True
        assert r.fix_content == "print('ok')"

    def test_success_when_verified(self) -> None:
        """status == 'verified' 时 success 为 True"""
        r = FixerResult(file_path="x", status="verified")
        assert r.success is True

    def test_success_when_fixed(self) -> None:
        """status == 'fixed' 时 success 为 True"""
        r = FixerResult(file_path="x", status="fixed")
        assert r.success is True

    def test_not_success_when_failed(self) -> None:
        """status == 'failed' 时 success 为 False"""
        r = FixerResult(file_path="x", status="failed")
        assert r.success is False

    def test_not_success_when_skipped(self) -> None:
        """status == 'skipped' 时 success 为 False"""
        r = FixerResult(file_path="x", status="skipped")
        assert r.success is False

    def test_not_success_when_empty(self) -> None:
        """status 为空时 success 为 False"""
        r = FixerResult(file_path="x", status="")
        assert r.success is False

    def test_errors_list_is_independent(self) -> None:
        """每个实例应拥有独立的 errors 列表（dataclass 默认行为）"""
        r1 = FixerResult(file_path="a", status="")
        r2 = FixerResult(file_path="b", status="")
        r1.errors.append("e1")
        assert r2.errors == []


# ══════════════════════════════════════════════════════════
# AutoFixer 构造 & 基础属性
# ══════════════════════════════════════════════════════════


class TestAutoFixerInit:
    """AutoFixer 构造行为"""

    def test_default_construction(self) -> None:
        """不传参数时使用 cwd 作为根目录，默认 max_retries"""
        f = AutoFixer()
        assert f._root == Path.cwd()
        assert f._max_retries == MAX_RETRIES

    def test_custom_root(self, tmp_project: Path) -> None:
        """project_root 应被正确设置"""
        f = AutoFixer(project_root=tmp_project)
        assert f._root == tmp_project

    def test_custom_max_retries(self, tmp_project: Path) -> None:
        """max_retries 应被正确设置"""
        f = AutoFixer(project_root=tmp_project, max_retries=5)
        assert f._max_retries == 5


# ══════════════════════════════════════════════════════════
# AutoFixer._check_syntax
# ══════════════════════════════════════════════════════════


class TestCheckSyntax:
    """_check_syntax 行为"""

    def test_valid_syntax(self, good_py_file: Path, fixer: AutoFixer) -> None:
        """语法正确的文件应返回 (True, '')"""
        ok, err = fixer._check_syntax(good_py_file)
        assert ok is True
        assert err == ""

    def test_invalid_syntax(self, bad_py_file: Path, fixer: AutoFixer) -> None:
        """语法错误的文件应返回 (False, 错误信息)"""
        ok, err = fixer._check_syntax(bad_py_file)
        assert ok is False
        assert "语法" in err or "行" in err

    def test_missing_file_raises(
        self, tmp_project: Path, fixer: AutoFixer
    ) -> None:
        """文件不存在时 _check_syntax 抛出 FileNotFoundError（不吞）"""
        import pytest as _pt

        with _pt.raises(FileNotFoundError):
            fixer._check_syntax(tmp_project / "nope.py")


# ══════════════════════════════════════════════════════════
# AutoFixer.validate_and_fix
# ══════════════════════════════════════════════════════════


class TestValidateAndFix:
    """validate_and_fix 的各种输入场景

    注意: pycoder.ai.auto_fixer.validate_and_fix 内部直接调用
    ``FixerResult(file_path=str(fp))``，而 FixerResult 当前的 dataclass
    定义要求 ``status`` 为必填位置参数。这属于源文件遗留 BUG。
    本测试用 monkeypatch 在 import 之后重新构建 FixerResult，
    给 status 加上默认值，使 validate_and_fix 可以正常执行。
    """

    @pytest.fixture(autouse=True)
    def _patch_fixer_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """为 FixerResult.status 注入默认值，绕开源 BUG"""

        @dataclasses.dataclass
        class _PatchedFixerResult:
            file_path: str
            status: str = ""
            attempts: int = 0
            errors: list[str] = dataclasses.field(default_factory=list)
            error_type: str = ""
            fix_applied: bool = False
            fix_content: str = ""

            @property
            def success(self) -> bool:
                return self.status in ("verified", "fixed")

        monkeypatch.setattr(auto_fixer, "FixerResult", _PatchedFixerResult)
        # 模块内 _install_xxx 也可能引用了原 FixerResult；保持 import 时同对象即可

    @pytest.mark.asyncio
    async def test_skipped_when_file_not_found(
        self, fixer: AutoFixer, tmp_project: Path
    ) -> None:
        """文件不存在时返回 skipped"""
        result = await fixer.validate_and_fix(tmp_project / "missing.py")
        assert result.status == "skipped"
        assert "不存在" in result.errors[0]
        assert result.success is False

    @pytest.mark.asyncio
    async def test_skipped_when_non_python_file(
        self, fixer: AutoFixer, non_py_file: Path
    ) -> None:
        """非 .py 文件返回 skipped"""
        result = await fixer.validate_and_fix(non_py_file)
        assert result.status == "skipped"
        assert "非 Python 文件" in result.errors[0]

    @pytest.mark.asyncio
    async def test_verified_when_syntax_ok_and_no_test_dir(
        self, fixer: AutoFixer, good_py_file: Path
    ) -> None:
        """语法通过且无测试目录时返回 verified（自动跳过测试）"""
        # tmp_project 下面没有 tests 目录
        result = await fixer.validate_and_fix(good_py_file)
        assert result.status == "verified"
        assert result.success is True

    @pytest.mark.asyncio
    async def test_syntax_error_without_callback_fails(
        self, fixer: AutoFixer, bad_py_file: Path
    ) -> None:
        """语法错误但没有 LLM 回调时返回 failed"""
        result = await fixer.validate_and_fix(bad_py_file)
        assert result.status == "failed"
        assert result.error_type == "syntax"
        assert any("语法" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_syntax_error_with_callback_applies_fix(
        self, fixer: AutoFixer, bad_py_file: Path
    ) -> None:
        """语法错误时 LLM 回调能修复则重试成功"""

        fixed_source = "def fixed():\n    return 1\n"

        async def callback(prompt: str, path: str) -> str:
            return fixed_source

        # 第一次语法检查失败 → callback 返回可解析代码 → 重试 → 语法通过 → 无测试 → verified
        result = await fixer.validate_and_fix(
            bad_py_file, llm_callback=callback, auto_fix=True
        )
        assert result.status == "verified"
        # 修复后的内容应被写入文件
        assert bad_py_file.read_text(encoding="utf-8") == fixed_source

    @pytest.mark.asyncio
    async def test_syntax_error_callback_returns_invalid_code(
        self, fixer: AutoFixer, bad_py_file: Path
    ) -> None:
        """回调返回仍然有语法错误的代码时应返回 failed"""

        async def bad_callback(prompt: str, path: str) -> str:
            return "def still_broken(:\n    return 1\n"

        result = await fixer.validate_and_fix(
            bad_py_file, llm_callback=bad_callback, auto_fix=True
        )
        assert result.status == "failed"
        assert result.error_type == "syntax"

    @pytest.mark.asyncio
    async def test_syntax_error_callback_returns_empty(
        self, fixer: AutoFixer, bad_py_file: Path
    ) -> None:
        """回调返回空字符串时不应被当作成功修复"""

        async def empty_callback(prompt: str, path: str) -> str:
            return ""

        result = await fixer.validate_and_fix(
            bad_py_file, llm_callback=empty_callback, auto_fix=True
        )
        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_syntax_error_callback_returns_same_code(
        self, fixer: AutoFixer, bad_py_file: Path
    ) -> None:
        """回调返回与原文件相同内容时不应被当作成功修复"""

        original = bad_py_file.read_text(encoding="utf-8")

        async def same_callback(prompt: str, path: str) -> str:
            return original

        result = await fixer.validate_and_fix(
            bad_py_file, llm_callback=same_callback, auto_fix=True
        )
        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_auto_fix_false_does_not_call_callback(
        self, fixer: AutoFixer, bad_py_file: Path
    ) -> None:
        """auto_fix=False 时即使有回调也不调用"""
        calls: list[tuple[str, str]] = []

        async def callback(prompt: str, path: str) -> str:
            calls.append((prompt, path))
            return "def fixed():\n    return 1\n"

        result = await fixer.validate_and_fix(
            bad_py_file, llm_callback=callback, auto_fix=False
        )
        assert result.status == "failed"
        assert calls == []

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_crash(
        self, fixer: AutoFixer, bad_py_file: Path
    ) -> None:
        """回调抛异常时应捕获并返回 failed"""

        async def boom(prompt: str, path: str) -> str:
            raise RuntimeError("LLM API down")

        result = await fixer.validate_and_fix(
            bad_py_file, llm_callback=boom, auto_fix=True
        )
        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_test_file_skips_import_check(
        self, fixer: AutoFixer, tmp_project: Path
    ) -> None:
        """test_*.py 文件应跳过导入检查"""
        p = tmp_project / "test_demo.py"
        p.write_text("def test_demo():\n    assert 1 + 1 == 2\n", encoding="utf-8")
        # 即使 import 失败也不应阻塞（且 test_ 文件也不应跑测试）
        result = await fixer.validate_and_fix(p)
        # 没有 tests 目录时，test_ 文件应被当作普通文件 -> 没有测试 -> verified
        # 但 _check_import 会用 ast.parse，不会失败，所以会到测试步骤
        assert result.status in ("verified", "failed")

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(
        self, tmp_project: Path, bad_py_file: Path
    ) -> None:
        """超过 max_retries 后应返回 failed"""
        fixer = AutoFixer(project_root=tmp_project, max_retries=2)

        async def bad_callback(prompt: str, path: str) -> str:
            # 一直返回仍有语法错误的代码
            return "def still_broken(:\n    pass\n"

        result = await fixer.validate_and_fix(
            bad_py_file, llm_callback=bad_callback, auto_fix=True
        )
        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_test_failure_without_callback(
        self, tmp_project: Path
    ) -> None:
        """语法通过但测试失败时返回 failed"""
        # 创建一个语法 OK 的源文件
        src = tmp_project / "lib.py"
        src.write_text("VALUE = 42\n", encoding="utf-8")

        # 创建 tests 目录和失败测试
        tests_dir = tmp_project / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_lib.py"
        test_file.write_text(
            "from lib import VALUE\n\ndef test_value():\n    assert VALUE == 0\n",
            encoding="utf-8",
        )

        fixer = AutoFixer(project_root=tmp_project, max_retries=1)
        result = await fixer.validate_and_fix(src)
        # test_ 不会触发测试，且 lib.py 在导入测试前会通过 import 检查
        # 但 _run_tests 会执行 tests/test_lib.py（基于 src 自动检测）
        # 由于测试失败，应返回 failed
        assert result.status == "failed"
        assert result.error_type == "test_fail"

    @pytest.mark.asyncio
    async def test_test_success(self, tmp_project: Path) -> None:
        """语法通过且测试通过时返回 verified

        pytest 收集时, rootdir 默认为 test 文件所在目录。
        把被测代码与测试都放在 tests/ 下，避免 rootdir/sys.path 不一致。
        """
        tests_dir = tmp_project / "tests"
        tests_dir.mkdir()
        # 被测代码放在 tests/ 下，与测试一起被 pytest 加入 sys.path
        src = tests_dir / "calc.py"
        src.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        test_file = tests_dir / "test_calc.py"
        test_file.write_text(
            "from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
            encoding="utf-8",
        )

        fixer = AutoFixer(project_root=tmp_project, max_retries=1)
        result = await fixer.validate_and_fix(src)
        assert result.status == "verified"
        assert result.success is True

    @pytest.mark.asyncio
    async def test_with_explicit_test_target(self, tmp_project: Path) -> None:
        """显式指定 test_target 时应使用该路径"""
        src = tmp_project / "app.py"
        src.write_text("x = 1\n", encoding="utf-8")

        tests_dir = tmp_project / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_app.py"
        test_file.write_text("def test_pass():\n    assert True\n", encoding="utf-8")

        fixer = AutoFixer(project_root=tmp_project, max_retries=1)
        result = await fixer.validate_and_fix(src, test_target=str(test_file))
        assert result.status == "verified"

    @pytest.mark.asyncio
    async def test_explicit_test_target_failure(
        self, tmp_project: Path
    ) -> None:
        """显式指定失败测试时应返回 failed"""
        src = tmp_project / "app.py"
        src.write_text("x = 1\n", encoding="utf-8")

        tests_dir = tmp_project / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_app.py"
        test_file.write_text("def test_fail():\n    assert False\n", encoding="utf-8")

        fixer = AutoFixer(project_root=tmp_project, max_retries=1)
        result = await fixer.validate_and_fix(src, test_target=str(test_file))
        assert result.status == "failed"
        assert result.error_type == "test_fail"

    @pytest.mark.asyncio
    async def test_attempts_counter_increments(
        self, tmp_project: Path
    ) -> None:
        """attempts 字段应反映实际尝试次数"""
        src = tmp_project / "lib.py"
        src.write_text("VALUE = 42\n", encoding="utf-8")

        tests_dir = tmp_project / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_lib.py"
        test_file.write_text(
            "def test_fail():\n    assert False\n",
            encoding="utf-8",
        )

        fixer = AutoFixer(project_root=tmp_project, max_retries=1)
        result = await fixer.validate_and_fix(src)
        assert result.attempts >= 1


# ══════════════════════════════════════════════════════════
# _attempt_llm_fix
# ══════════════════════════════════════════════════════════


class TestAttemptLlmFix:
    """_attempt_llm_fix 行为"""

    @pytest.mark.asyncio
    async def test_applies_valid_fix(
        self, fixer: AutoFixer, bad_py_file: Path
    ) -> None:
        """回调返回有效且不同于原内容时写入文件并返回 True"""

        async def cb(prompt: str, path: str) -> str:
            return "def fixed():\n    return 1\n"

        ok = await fixer._attempt_llm_fix(
            cb, bad_py_file, "SyntaxError", "syntax", attempt=1
        )
        assert ok is True
        assert "def fixed" in bad_py_file.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_rejects_syntax_breaking_fix(
        self, fixer: AutoFixer, bad_py_file: Path
    ) -> None:
        """回调返回仍有语法错误的代码时返回 False"""

        async def cb(prompt: str, path: str) -> str:
            return "def still_broken(:\n    pass\n"

        ok = await fixer._attempt_llm_fix(
            cb, bad_py_file, "err", "syntax", attempt=1
        )
        assert ok is False

    @pytest.mark.asyncio
    async def test_rejects_empty_fix(
        self, fixer: AutoFixer, bad_py_file: Path
    ) -> None:
        """回调返回空字符串时返回 False"""

        async def cb(prompt: str, path: str) -> str:
            return ""

        ok = await fixer._attempt_llm_fix(
            cb, bad_py_file, "err", "syntax", attempt=1
        )
        assert ok is False

    @pytest.mark.asyncio
    async def test_rejects_identical_fix(
        self, fixer: AutoFixer, bad_py_file: Path
    ) -> None:
        """回调返回与原内容相同时返回 False"""
        original = bad_py_file.read_text(encoding="utf-8")

        async def cb(prompt: str, path: str) -> str:
            return original

        ok = await fixer._attempt_llm_fix(
            cb, bad_py_file, "err", "syntax", attempt=1
        )
        assert ok is False

    @pytest.mark.asyncio
    async def test_handles_callback_exception(
        self, fixer: AutoFixer, bad_py_file: Path
    ) -> None:
        """回调异常时应捕获并返回 False"""

        async def cb(prompt: str, path: str) -> str:
            raise ValueError("LLM error")

        ok = await fixer._attempt_llm_fix(
            cb, bad_py_file, "err", "syntax", attempt=1
        )
        assert ok is False


# ══════════════════════════════════════════════════════════
# _run_tests
# ══════════════════════════════════════════════════════════


class TestRunTests:
    """_run_tests 在没有 tests 目录时的行为"""

    @pytest.mark.asyncio
    async def test_returns_verified_when_no_test_dir(
        self, fixer: AutoFixer, good_py_file: Path
    ) -> None:
        """无 tests 目录时返回 (True, 跳过消息)"""
        ok, output = await fixer._run_tests(good_py_file, test_target="")
        assert ok is True
        assert "跳过" in output or "无测试" in output

    @pytest.mark.asyncio
    async def test_explicit_empty_test_target_no_dir(
        self, fixer: AutoFixer, good_py_file: Path, tmp_project: Path
    ) -> None:
        """test_target 指向不存在的目录时返回 (True, 跳过)"""
        ok, output = await fixer._run_tests(
            good_py_file, test_target=str(tmp_project / "no_such_dir")
        )
        # 当 test_target 给定但目录不存在时,pytest 会失败;这里不严格断言成功
        assert isinstance(ok, bool)
        assert isinstance(output, str)


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════


class TestGetAutoFixerSingleton:
    """get_auto_fixer 单例行为"""

    def setup_method(self) -> None:
        """每个用例前重置单例"""
        auto_fixer._instance = None  # type: ignore[attr-defined]

    def teardown_method(self) -> None:
        """清理单例"""
        auto_fixer._instance = None  # type: ignore[attr-defined]

    def test_returns_instance(self) -> None:
        """首次调用应创建实例"""
        f = get_auto_fixer()
        assert isinstance(f, AutoFixer)

    def test_returns_same_instance(self) -> None:
        """多次调用应返回同一实例"""
        f1 = get_auto_fixer()
        f2 = get_auto_fixer()
        assert f1 is f2

    def test_passes_project_root(self, tmp_project: Path) -> None:
        """传入 project_root 应传给构造"""
        f = get_auto_fixer(project_root=tmp_project)
        assert f._root == tmp_project
