"""code_exec 路由单元测试 — 沙箱代码执行 API

覆盖 pycoder.server.routers.code_exec 的核心功能：
- SandboxConfig — 沙箱配置数据类与 to_dict
- pre_scan_code — 危险模式静态扫描（__import__/__subclasses__/dunder/compile）
- scan_banned_imports — 禁止模块导入检查
- _run_in_subprocess — 子进程沙箱执行（安全检查+执行+结果解析）
- ExecutionResult — 执行结果数据类
- API 端点 — get/update_sandbox_config、execute_code、install_packages、get_capabilities

测试策略：
- 纯函数（pre_scan_code, scan_banned_imports）直接测试各种输入
- _run_in_subprocess 用真实子进程测试正常执行路径 + mock 测试超时/异常
- API 端点直接调用 async 函数（绕过 HTTP/认证层）
- install_packages 用 mock 隔离 asyncio.create_subprocess_exec，避免真实 pip install

目标覆盖率：42.6% → 85%+
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import pycoder.server.routers.code_exec as code_exec_mod
from pycoder.server.routers.code_exec import (
    BANNED_MODULES,
    DANGEROUS_CALLS,
    DEFAULT_TIMEOUT,
    IMPORT_SCAN,
    MAX_OUTPUT_LENGTH,
    SCAN_PATTERNS,
    CodeExecRequest,
    CodeExecResponse,
    ExecutionResult,
    PipInstallRequest,
    PipInstallResponse,
    SandboxConfig,
    SandboxConfigResponse,
    _run_in_subprocess,
    _sandbox_config,
    execute_code,
    get_capabilities,
    get_sandbox_config,
    install_packages,
    pre_scan_code,
    scan_banned_imports,
    update_sandbox_config,
)


# ══════════════════════════════════════════════════════════
# SandboxConfig 测试
# ══════════════════════════════════════════════════════════


class TestSandboxConfig:
    """SandboxConfig 数据类"""

    def test_default_values(self):
        """默认值验证"""
        cfg = SandboxConfig()
        assert cfg.default_timeout == 30
        assert cfg.max_timeout == 600
        assert cfg.max_output_length == 10000
        assert cfg.max_code_length == 100000
        assert cfg.memory_limit_mb == 512
        assert cfg.allow_network is False
        assert cfg.allow_multithreading is False

    def test_to_dict_contains_all_fields(self):
        """to_dict 包含所有字段"""
        cfg = SandboxConfig()
        d = cfg.to_dict()
        assert "default_timeout" in d
        assert "max_timeout" in d
        assert "max_output_length" in d
        assert "max_code_length" in d
        assert "memory_limit_mb" in d
        assert "allow_network" in d
        assert "allow_multithreading" in d
        assert len(d) == 7

    def test_custom_values(self):
        """自定义值"""
        cfg = SandboxConfig(
            default_timeout=60, max_timeout=1200,
            allow_network=True, allow_multithreading=True,
        )
        assert cfg.default_timeout == 60
        assert cfg.max_timeout == 1200
        assert cfg.allow_network is True
        assert cfg.allow_multithreading is True

    def test_global_config_is_sandbox_config(self):
        """全局 _sandbox_config 是 SandboxConfig 实例"""
        assert isinstance(_sandbox_config, SandboxConfig)


# ══════════════════════════════════════════════════════════
# pre_scan_code 测试
# ══════════════════════════════════════════════════════════


class TestPreScanCode:
    """pre_scan_code 危险模式静态扫描"""

    def test_clean_code_no_violations(self):
        """安全代码无违规"""
        assert pre_scan_code("print('hello')") == []
        assert pre_scan_code("x = 1 + 2\nprint(x)") == []
        assert pre_scan_code("import math\nprint(math.pi)") == []

    def test_detects_import_call(self):
        """检测 __import__() 调用"""
        violations = pre_scan_code("__import__('os')")
        assert len(violations) == 1
        assert "__import__" in violations[0]

    def test_detects_import_with_spaces(self):
        """检测带空格的 __import__"""
        violations = pre_scan_code("__import__  ('os')")
        assert len(violations) == 1

    def test_detects_subclasses_traversal(self):
        """检测 __subclasses__() 遍历"""
        violations = pre_scan_code("object.__subclasses__()")
        assert len(violations) == 1
        assert "subclass" in violations[0]

    def test_detects_dunder_getattr(self):
        """检测 getattr + dunder 属性访问"""
        violations = pre_scan_code("getattr(obj, '__class__')")
        assert len(violations) == 1
        assert "dunder" in violations[0]

    def test_detects_compile_call(self):
        """检测 compile() 调用"""
        violations = pre_scan_code("compile('code', '<test>', 'exec')")
        assert len(violations) == 1
        assert "compile" in violations[0]

    def test_detects_multiple_violations(self):
        """检测多个违规"""
        code = "__import__('os')\nobject.__subclasses__()"
        violations = pre_scan_code(code)
        assert len(violations) == 2

    def test_empty_code_no_violations(self):
        """空代码无违规"""
        assert pre_scan_code("") == []

    def test_normal_getattr_allowed(self):
        """正常 getattr（非 dunder）允许"""
        violations = pre_scan_code("getattr(obj, 'name')")
        assert violations == []

    def test_scan_patterns_defined(self):
        """SCAN_PATTERNS 已定义且非空"""
        assert len(SCAN_PATTERNS) > 0
        for pattern, label in SCAN_PATTERNS:
            assert isinstance(label, str)
            assert label


# ══════════════════════════════════════════════════════════
# scan_banned_imports 测试
# ══════════════════════════════════════════════════════════


class TestScanBannedImports:
    """scan_banned_imports 禁止模块检查"""

    def test_clean_imports_allowed(self):
        """安全模块导入无阻塞"""
        assert scan_banned_imports("import math") == []
        assert scan_banned_imports("from json import loads") == []
        assert scan_banned_imports("import time, datetime") == []

    def test_detects_banned_import(self):
        """检测 banned import"""
        blocked = scan_banned_imports("import os")
        assert "os" in blocked

    def test_detects_banned_from_import(self):
        """检测 banned from import"""
        blocked = scan_banned_imports("from subprocess import run")
        assert "subprocess" in blocked

    def test_detects_multiple_banned(self):
        """检测多个禁止模块"""
        blocked = scan_banned_imports("import os\nimport socket\nimport threading")
        assert "os" in blocked
        assert "socket" in blocked
        assert "threading" in blocked

    def test_dotted_module_name(self):
        """点分模块名取第一段"""
        blocked = scan_banned_imports("import urllib.request")
        assert "urllib" in blocked

    def test_safe_modules_not_blocked(self):
        """安全模块不被阻塞"""
        for mod in ["math", "json", "time", "datetime", "re", "collections"]:
            assert scan_banned_imports(f"import {mod}") == []

    def test_banned_modules_set_not_empty(self):
        """BANNED_MODULES 非空"""
        assert len(BANNED_MODULES) > 0
        for mod in ["os", "subprocess", "socket", "threading", "pickle"]:
            assert mod in BANNED_MODULES

    def test_empty_code_no_blocked(self):
        """空代码无阻塞"""
        assert scan_banned_imports("") == []

    def test_indented_import(self):
        """缩进的 import 也能检测"""
        blocked = scan_banned_imports("    import os")
        assert "os" in blocked


# ══════════════════════════════════════════════════════════
# ExecutionResult 测试
# ══════════════════════════════════════════════════════════


class TestExecutionResult:
    """ExecutionResult 数据类"""

    def test_default_values(self):
        """默认值"""
        r = ExecutionResult()
        assert r.success is False
        assert r.stdout == ""
        assert r.stderr == ""
        assert r.error_type == ""
        assert r.error_message == ""
        assert r.traceback == ""
        assert r.execution_time == 0.0

    def test_custom_values(self):
        """自定义值"""
        r = ExecutionResult(
            success=True, stdout="hello", stderr="",
            execution_time=0.5,
        )
        assert r.success is True
        assert r.stdout == "hello"
        assert r.execution_time == 0.5


# ══════════════════════════════════════════════════════════
# _run_in_subprocess 测试
# ══════════════════════════════════════════════════════════


class TestRunInSubprocess:
    """_run_in_subprocess 子进程沙箱执行"""

    def test_security_violation_blocks_execution(self):
        """安全违规阻止执行"""
        result = _run_in_subprocess("__import__('os')", timeout=5)
        assert result.success is False
        assert result.error_type == "SecurityViolation"
        assert "__import__" in result.error_message

    def test_banned_import_blocks_execution(self):
        """禁止模块导入阻止执行"""
        result = _run_in_subprocess("import os", timeout=5)
        assert result.success is False
        assert result.error_type == "BannedImport"
        assert "os" in result.error_message

    def test_dangerous_calls_blocked(self):
        """危险函数调用阻止执行"""
        # exec() 调用会被 DANGEROUS_CALLS 检测到
        result = _run_in_subprocess("exec('x = 1')", timeout=5)
        assert result.success is False
        assert result.error_type == "SecurityViolation"

    def test_safe_code_executes_successfully(self):
        """安全代码成功执行"""
        result = _run_in_subprocess("print('hello sandbox')", timeout=10)
        assert result.success is True
        assert "hello sandbox" in result.stdout

    def test_arithmetic_execution(self):
        """算术运算执行"""
        result = _run_in_subprocess("print(2 + 3)", timeout=10)
        assert result.success is True
        assert "5" in result.stdout

    def test_syntax_error_captured(self):
        """语法错误被捕获"""
        result = _run_in_subprocess("def broken(:", timeout=10)
        assert result.success is False
        assert result.error_type == "SyntaxError"

    def test_runtime_error_captured(self):
        """运行时错误被捕获"""
        result = _run_in_subprocess("raise ValueError('test error')", timeout=10)
        assert result.success is False
        assert result.error_type == "ValueError"
        assert "test error" in result.error_message

    def test_stdout_captured(self):
        """stdout 被捕获"""
        result = _run_in_subprocess(
            "print('line1')\nprint('line2')", timeout=10
        )
        assert result.success is True
        assert "line1" in result.stdout
        assert "line2" in result.stdout

    def test_execution_time_positive(self):
        """执行时间为正"""
        result = _run_in_subprocess("print('x')", timeout=10)
        assert result.execution_time >= 0.0

    def test_timeout_returns_timeout_error(self):
        """超时返回 TimeoutError"""
        # 死循环触发超时
        result = _run_in_subprocess("while True: pass", timeout=2)
        assert result.success is False
        assert result.error_type == "TimeoutError"
        assert "2" in result.error_message  # 包含超时秒数

    def test_subprocess_exception_handled(self, monkeypatch):
        """子进程异常被捕获"""
        def raise_exception(*args, **kwargs):
            raise OSError("subprocess failed")

        monkeypatch.setattr(subprocess, "run", raise_exception)
        result = _run_in_subprocess("print('x')", timeout=10)
        assert result.success is False
        assert result.error_type == "OSError"

    def test_timeout_expired_handled(self, monkeypatch):
        """TimeoutExpired 异常被捕获"""
        def raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=["python"], timeout=5)

        monkeypatch.setattr(subprocess, "run", raise_timeout)
        result = _run_in_subprocess("print('x')", timeout=5)
        assert result.success is False
        assert result.error_type == "TimeoutError"

    def test_no_sandbox_marker_falls_back(self, monkeypatch):
        """无 SANDBOX_RESULT 标记时回退到原始输出"""
        mock_proc = MagicMock()
        mock_proc.stdout = b"raw output without markers"
        mock_proc.stderr = b""
        mock_proc.returncode = 0

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        result = _run_in_subprocess("print('x')", timeout=10)
        assert result.success is True
        assert "raw output" in result.stdout

    def test_invalid_json_in_marker_falls_back(self, monkeypatch):
        """SANDBOX_RESULT 标记内 JSON 无效时回退"""
        mock_proc = MagicMock()
        mock_proc.stdout = b"__SANDBOX_RESULT__not valid json__SANDBOX_END__"
        mock_proc.stderr = b""
        mock_proc.returncode = 0

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        result = _run_in_subprocess("print('x')", timeout=10)
        # 无效 JSON 回退到原始输出
        assert isinstance(result.stdout, str)

    def test_nonzero_returncode_falls_back(self, monkeypatch):
        """非零返回码回退到 SubprocessError"""
        mock_proc = MagicMock()
        mock_proc.stdout = b"some output"
        mock_proc.stderr = b"error output"
        mock_proc.returncode = 1

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        result = _run_in_subprocess("print('x')", timeout=10)
        assert result.success is False
        assert result.error_type == "SubprocessError"

    def test_long_output_truncated(self, monkeypatch):
        """超长输出被截断"""
        long_output = "x" * (MAX_OUTPUT_LENGTH + 1000)
        mock_proc = MagicMock()
        mock_proc.stdout = long_output.encode("utf-8")
        mock_proc.stderr = b""
        mock_proc.returncode = 0

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        result = _run_in_subprocess("print('x')", timeout=10)
        assert len(result.stdout) <= MAX_OUTPUT_LENGTH + 100  # 截断 + 提示
        assert "truncated" in result.stdout

    def test_stderr_captured(self, monkeypatch):
        """stderr 被捕获"""
        mock_proc = MagicMock()
        mock_proc.stdout = b"__SANDBOX_RESULT__" + json.dumps({
            "success": True, "stdout": "", "stderr": "stderr msg",
            "error_type": "", "error_message": "", "traceback": "",
            "execution_time": 0.1,
        }).encode() + b"__SANDBOX_END__"
        mock_proc.stderr = b""
        mock_proc.returncode = 0

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        result = _run_in_subprocess("print('x')", timeout=10)
        assert result.stderr == "stderr msg"


# ══════════════════════════════════════════════════════════
# API 端点测试 — 沙箱配置
# ══════════════════════════════════════════════════════════


class TestGetSandboxConfig:
    """get_sandbox_config API 端点"""

    @pytest.mark.asyncio
    async def test_returns_config(self):
        """返回当前配置"""
        result = await get_sandbox_config()
        assert result.success is True
        assert hasattr(result, "config")
        assert "default_timeout" in result.config
        assert "max_timeout" in result.config
        assert hasattr(result, "message")


class TestUpdateSandboxConfig:
    """update_sandbox_config API 端点"""

    @pytest.mark.asyncio
    async def test_update_default_timeout(self):
        """更新 default_timeout"""
        result = await update_sandbox_config({"default_timeout": 60})
        assert result.success is True
        assert result.config["default_timeout"] == 60
        # 恢复默认值
        await update_sandbox_config({"default_timeout": 30})

    @pytest.mark.asyncio
    async def test_clamps_to_min(self):
        """低于最小值时钳制到 min"""
        result = await update_sandbox_config({"default_timeout": 1})
        assert result.config["default_timeout"] == 10  # min is 10

    @pytest.mark.asyncio
    async def test_clamps_to_max(self):
        """超过最大值时钳制到 max"""
        result = await update_sandbox_config({"default_timeout": 99999})
        assert result.config["default_timeout"] == 600  # max is 600

    @pytest.mark.asyncio
    async def test_update_bool_field(self):
        """更新布尔字段"""
        result = await update_sandbox_config({"allow_network": True})
        assert result.config["allow_network"] is True
        # 恢复
        await update_sandbox_config({"allow_network": False})

    @pytest.mark.asyncio
    async def test_invalid_value_ignored(self):
        """无效值被忽略"""
        result = await update_sandbox_config({"default_timeout": "not_a_number"})
        # 无效值不更新，返回当前配置
        assert result.success is True

    @pytest.mark.asyncio
    async def test_unknown_key_ignored(self):
        """未知字段被忽略"""
        result = await update_sandbox_config({"unknown_field": 123})
        assert result.success is True
        assert "unknown_field" not in result.config

    @pytest.mark.asyncio
    async def test_update_multiple_fields(self):
        """同时更新多个字段"""
        result = await update_sandbox_config({
            "default_timeout": 45,
            "max_output_length": 5000,
        })
        assert result.config["default_timeout"] == 45
        assert result.config["max_output_length"] == 5000
        assert "2 个" in result.message or "2" in result.message
        # 恢复
        await update_sandbox_config({"default_timeout": 30, "max_output_length": 10000})

    @pytest.mark.asyncio
    async def test_empty_request(self):
        """空请求返回当前配置"""
        result = await update_sandbox_config({})
        assert result.success is True
        assert hasattr(result, "config")


# ══════════════════════════════════════════════════════════
# API 端点测试 — execute_code
# ══════════════════════════════════════════════════════════


class TestExecuteCode:
    """execute_code API 端点"""

    @pytest.mark.asyncio
    async def test_executes_simple_code(self):
        """执行简单代码"""
        req = CodeExecRequest(code="print('hello world')", timeout=10)
        result = await execute_code(req)
        assert result.success is True
        assert "hello world" in result.stdout
        assert result.execution_time >= 0

    @pytest.mark.asyncio
    async def test_empty_code_raises_400(self):
        """空代码返回 400"""
        req = CodeExecRequest(code="", timeout=10)
        with pytest.raises(HTTPException) as exc:
            await execute_code(req)
        assert exc.value.status_code == 400
        assert "empty" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_whitespace_code_raises_400(self):
        """纯空白代码返回 400"""
        req = CodeExecRequest(code="   \n\t  ", timeout=10)
        with pytest.raises(HTTPException) as exc:
            await execute_code(req)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_too_long_code_raises_400(self, monkeypatch):
        """超长代码返回 400"""
        # 修改 max_code_length 为较小值以避免生成超大字符串
        original = code_exec_mod._sandbox_config.max_code_length
        monkeypatch.setattr(code_exec_mod._sandbox_config, "max_code_length", 100)
        req = CodeExecRequest(code="x" * 200, timeout=10)
        with pytest.raises(HTTPException) as exc:
            await execute_code(req)
        assert exc.value.status_code == 400
        assert "too long" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_security_violation_in_code(self):
        """代码含安全违规"""
        req = CodeExecRequest(code="__import__('os')", timeout=10)
        result = await execute_code(req)
        assert result.success is False
        assert result.error_type == "SecurityViolation"

    @pytest.mark.asyncio
    async def test_banned_import_in_code(self):
        """代码含禁止模块"""
        req = CodeExecRequest(code="import os", timeout=10)
        result = await execute_code(req)
        assert result.success is False
        assert result.error_type == "BannedImport"

    @pytest.mark.asyncio
    async def test_long_running_uses_max_timeout(self, monkeypatch):
        """long_running=True 使用 max_timeout"""
        # 用 mock 避免真实执行
        mock_result = ExecutionResult(success=True, stdout="ok", execution_time=0.1)
        monkeypatch.setattr(
            code_exec_mod, "_run_in_subprocess",
            lambda code, timeout: mock_result,
        )
        req = CodeExecRequest(
            code="print('x')", timeout=300, long_running=True
        )
        result = await execute_code(req)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_response_contains_config_used(self):
        """响应包含 config_used"""
        req = CodeExecRequest(code="print('x')", timeout=10)
        result = await execute_code(req)
        assert "config_used" in result.config_used or hasattr(result, "config_used")
        assert result.config_used["default_timeout"] is not None

    @pytest.mark.asyncio
    async def test_output_length_calculated(self):
        """output_length 被计算"""
        req = CodeExecRequest(code="print('test')", timeout=10)
        result = await execute_code(req)
        assert result.output_length > 0


# ══════════════════════════════════════════════════════════
# API 端点测试 — install_packages
# ══════════════════════════════════════════════════════════


class TestInstallPackages:
    """install_packages API 端点（用 mock 隔离子进程）"""

    @pytest.mark.asyncio
    async def test_empty_packages_raises_400(self):
        """空包列表返回 400"""
        req = PipInstallRequest(packages=[])
        with pytest.raises(HTTPException) as exc:
            await install_packages(req)
        assert exc.value.status_code == 400
        assert "No packages" in exc.value.detail

    @pytest.mark.asyncio
    async def test_too_many_packages_raises_400(self):
        """超过 10 个包返回 400"""
        req = PipInstallRequest(packages=[f"pkg{i}" for i in range(11)])
        with pytest.raises(HTTPException) as exc:
            await install_packages(req)
        assert exc.value.status_code == 400
        assert "10" in exc.value.detail

    @pytest.mark.asyncio
    async def test_invalid_package_name_rejected(self, monkeypatch):
        """无效包名被拒绝

        注意：install_packages 的 sanitized 逻辑会 split [ ; #，
        所以 "invalid;rm -rf /" 会被 sanitized 为 "invalid"（有效）。
        使用含 | & $ 等 allowed_chars 外字符且不被 split 的包名。
        """
        req = PipInstallRequest(packages=["valid_pkg", "bad|pkg"])
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        monkeypatch.setattr(
            asyncio, "create_subprocess_exec",
            AsyncMock(return_value=mock_proc),
        )
        result = await install_packages(req)
        assert "bad|pkg" in result.failed
        assert "Invalid" in result.failed["bad|pkg"]

    @pytest.mark.asyncio
    async def test_successful_install(self, monkeypatch):
        """成功安装包"""
        req = PipInstallRequest(packages=["requests"])
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"Successfully installed", b""))
        monkeypatch.setattr(
            asyncio, "create_subprocess_exec",
            AsyncMock(return_value=mock_proc),
        )
        result = await install_packages(req)
        assert result.success is True
        assert "requests" in result.installed
        assert "Successfully" in result.message

    @pytest.mark.asyncio
    async def test_install_failure(self, monkeypatch):
        """安装失败"""
        req = PipInstallRequest(packages=["nonexistent_pkg_xyz"])
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(
            return_value=(b"", b"ERROR: Could not find package"),
        )
        monkeypatch.setattr(
            asyncio, "create_subprocess_exec",
            AsyncMock(return_value=mock_proc),
        )
        result = await install_packages(req)
        assert result.success is False
        assert "nonexistent_pkg_xyz" in result.failed
        assert "Could not find" in result.failed["nonexistent_pkg_xyz"]

    @pytest.mark.asyncio
    async def test_install_timeout(self, monkeypatch):
        """安装超时"""
        req = PipInstallRequest(packages=["slow_pkg"])
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        # kill 是同步方法，用 MagicMock 避免协程未 await warning
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()
        monkeypatch.setattr(
            asyncio, "create_subprocess_exec",
            AsyncMock(return_value=mock_proc),
        )
        result = await install_packages(req)
        assert result.success is False
        assert "slow_pkg" in result.failed
        assert "timed out" in result.failed["slow_pkg"].lower()

    @pytest.mark.asyncio
    async def test_partial_success(self, monkeypatch):
        """部分成功"""
        req = PipInstallRequest(packages=["good_pkg", "bad_pkg"])

        # 第一个包成功，第二个失败
        good_proc = AsyncMock()
        good_proc.returncode = 0
        good_proc.communicate = AsyncMock(return_value=(b"ok", b""))

        bad_proc = AsyncMock()
        bad_proc.returncode = 1
        bad_proc.communicate = AsyncMock(return_value=(b"", b"error"))

        mock_exec = AsyncMock(side_effect=[good_proc, bad_proc])
        monkeypatch.setattr(asyncio, "create_subprocess_exec", mock_exec)
        result = await install_packages(req)
        assert result.success is False
        assert "good_pkg" in result.installed
        assert "bad_pkg" in result.failed

    @pytest.mark.asyncio
    async def test_package_name_too_long_rejected(self, monkeypatch):
        """包名过长被拒绝"""
        long_name = "a" * 201
        req = PipInstallRequest(packages=[long_name])
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        monkeypatch.setattr(
            asyncio, "create_subprocess_exec",
            AsyncMock(return_value=mock_proc),
        )
        result = await install_packages(req)
        assert long_name in result.failed
        assert "Invalid" in result.failed[long_name]

    @pytest.mark.asyncio
    async def test_subprocess_exception_captured(self, monkeypatch):
        """子进程异常被捕获"""
        req = PipInstallRequest(packages=["test_pkg"])
        mock_exec = AsyncMock(side_effect=OSError("spawn failed"))
        monkeypatch.setattr(asyncio, "create_subprocess_exec", mock_exec)
        result = await install_packages(req)
        assert result.success is False
        assert "test_pkg" in result.failed
        assert "spawn failed" in result.failed["test_pkg"]


# ══════════════════════════════════════════════════════════
# API 端点测试 — get_capabilities
# ══════════════════════════════════════════════════════════


class TestGetCapabilities:
    """get_capabilities API 端点"""

    @pytest.mark.asyncio
    async def test_returns_capabilities(self):
        """返回能力信息"""
        result = await get_capabilities()
        assert "max_timeout" in result
        assert "max_code_length" in result
        assert "max_output_length" in result
        assert "available_modules" in result
        assert "banned_modules" in result
        assert "pip_install_supported" in result
        assert result["pip_install_supported"] is True

    @pytest.mark.asyncio
    async def test_banned_modules_in_capabilities(self):
        """banned_modules 列表包含禁止模块"""
        result = await get_capabilities()
        assert "os" in result["banned_modules"]
        assert "subprocess" in result["banned_modules"]

    @pytest.mark.asyncio
    async def test_available_modules_in_capabilities(self):
        """available_modules 列表包含安全模块"""
        result = await get_capabilities()
        assert "math" in result["available_modules"]
        assert "json" in result["available_modules"]


# ══════════════════════════════════════════════════════════
# 请求/响应模型测试
# ══════════════════════════════════════════════════════════


class TestCodeExecRequest:
    """CodeExecRequest Pydantic 模型"""

    def test_default_values(self):
        """默认值"""
        req = CodeExecRequest(code="print('x')")
        assert req.timeout == DEFAULT_TIMEOUT
        assert req.long_running is False
        assert req.memory_mb is None

    def test_custom_values(self):
        """自定义值"""
        req = CodeExecRequest(
            code="print('x')", timeout=60, long_running=True, memory_mb=1024,
        )
        assert req.timeout == 60
        assert req.long_running is True
        assert req.memory_mb == 1024


class TestCodeExecResponse:
    """CodeExecResponse Pydantic 模型"""

    def test_construction(self):
        """构造"""
        resp = CodeExecResponse(
            success=True, stdout="hello", execution_time=0.5,
        )
        assert resp.success is True
        assert resp.stdout == "hello"
        assert resp.execution_time == 0.5
        assert resp.output_length == 0  # 默认


class TestPipInstallRequest:
    """PipInstallRequest Pydantic 模型"""

    def test_valid_request(self):
        """有效请求"""
        req = PipInstallRequest(packages=["requests", "numpy>=1.20"])
        assert len(req.packages) == 2

    def test_empty_packages_allowed(self):
        """空列表允许（端点会拒绝）"""
        req = PipInstallRequest(packages=[])
        assert req.packages == []


# ══════════════════════════════════════════════════════════
# 常量与正则验证
# ══════════════════════════════════════════════════════════


class TestConstants:
    """常量与正则表达式验证"""

    def test_default_timeout_is_30(self):
        """默认超时 30 秒"""
        assert DEFAULT_TIMEOUT == 30

    def test_max_output_length_is_10000(self):
        """最大输出 10000 字符"""
        assert MAX_OUTPUT_LENGTH == 10000

    def test_dangerous_calls_regex_matches(self):
        """DANGEROUS_CALLS 正则匹配危险调用"""
        assert DANGEROUS_CALLS.search("__import__('os')")
        assert DANGEROUS_CALLS.search("exec('code')")
        assert DANGEROUS_CALLS.search("eval('1+1')")
        assert DANGEROUS_CALLS.search("compile('x', 'f', 'exec')")

    def test_dangerous_calls_regex_no_false_positive(self):
        """DANGEROUS_CALLS 不误报安全代码"""
        assert not DANGEROUS_CALLS.search("print('hello')")
        assert not DANGEROUS_CALLS.search("x = 1 + 2")

    def test_import_scan_regex_matches(self):
        """IMPORT_SCAN 正则匹配 import 语句"""
        matches = IMPORT_SCAN.findall("import os")
        assert matches

    def test_import_scan_matches_from_import(self):
        """IMPORT_SCAN 匹配 from import"""
        matches = IMPORT_SCAN.findall("from os import path")
        assert matches
