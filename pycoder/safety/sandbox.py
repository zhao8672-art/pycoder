"""安全沙箱执行模块 — 代码隔离执行与兼容性导出"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# 兼容性数据类 — 供外部模块导入
# ══════════════════════════════════════════════════════════


@dataclass
class SandboxConfig:
    """沙箱配置"""

    timeout: int = 30
    max_cpu_percent: float = 30.0
    max_memory_mb: int = 512
    max_disk_mb: int = 100
    max_timeout_seconds: float = 60.0
    allow_network: bool = False
    allow_file_write: bool = False
    restricted_paths: list[str] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    network_whitelist: list[str] = field(default_factory=list)


@dataclass
class SandboxResult:
    """沙箱执行结果"""

    success: bool = True
    output: str = ""
    error: str = ""
    exit_code: int = 0
    execution_time: float = 0.0
    duration_ms: float = 0.0
    memory_usage_mb: float = 0.0
    memory_used_mb: float = 0.0
    cpu_time_ms: float = 0.0
    stdout: str = ""
    stderr: str = ""
    killed_by_timeout: bool = False
    killed_by_memory: bool = False


class ProcessSandbox:
    """进程沙箱 — 使用 subprocess 隔离执行代码"""

    # 语言到解释器的映射
    _INTERPRETERS: dict[str, str] = {
        "python": "python3",
        "javascript": "node",
        "bash": "bash",
    }

    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig(max_timeout_seconds=60)

    def _get_interpreter(self, language: str) -> str:
        """获取指定语言对应的解释器路径"""
        return self._INTERPRETERS.get(language, "python3")

    def _prepare_code(self, code: str, language: str, work_dir: Path) -> Path:
        """将代码写入临时文件，返回文件路径"""
        suffix_map = {
            "python": ".py",
            "javascript": ".js",
            "bash": ".sh",
        }
        suffix = suffix_map.get(language, ".txt")
        file_path = work_dir / f"code{suffix}"
        file_path.write_text(code, encoding="utf-8")
        return file_path

    async def execute(
        self,
        code: str,
        language: str = "python",
        timeout: float | None = None,
        files: dict[str, str] | None = None,
        stdin: str = "",
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """在隔离进程中异步执行代码"""
        import tempfile

        _start = time.time()

        timeout = timeout if timeout is not None else float(self.config.max_timeout_seconds)
        interpreter = self._get_interpreter(language)

        # 使用临时目录管理工作文件
        with tempfile.TemporaryDirectory() as work_dir_str:
            work_dir = Path(work_dir_str)
            code_file = self._prepare_code(code, language, work_dir)

            # 写入额外文件
            if files:
                for fname, fcontent in files.items():
                    fpath = work_dir / fname
                    fpath.parent.mkdir(parents=True, exist_ok=True)
                    fpath.write_text(fcontent, encoding="utf-8")

            try:
                proc = await asyncio.create_subprocess_exec(
                    interpreter,
                    str(code_file),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    stdin=asyncio.subprocess.PIPE if stdin else None,
                    cwd=str(work_dir),
                    env={**os.environ, **(env or {})},
                )

                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(input=stdin.encode() if stdin else None),
                        timeout=timeout,
                    )
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
                    elapsed = (time.time() - _start) * 1000
                    return SandboxResult(
                        success=False,
                        error="执行超时",
                        exit_code=-1,
                        duration_ms=round(elapsed, 2),
                        killed_by_timeout=True,
                    )

                stdout_str = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
                stderr_str = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
                elapsed = (time.time() - _start) * 1000

                return SandboxResult(
                    success=proc.returncode == 0,
                    output=stdout_str,
                    error=stderr_str,
                    exit_code=proc.returncode,
                    execution_time=round(time.time() - _start, 4),
                    duration_ms=round(elapsed, 2),
                    stdout=stdout_str,
                    stderr=stderr_str,
                )
            except Exception as e:
                elapsed = (time.time() - _start) * 1000
                return SandboxResult(
                    success=False,
                    error=str(e),
                    exit_code=-1,
                    duration_ms=round(elapsed, 2),
                )


class SandboxManager:
    """沙箱管理器 — 统一管理所有沙箱实例"""

    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig()
        self._sandboxes: dict[str, Any] = {}

    def execute(self, code: str) -> SandboxResult:
        """在沙箱中执行代码"""
        _start = time.time()
        result = safe_execute(code)
        return SandboxResult(
            success=result.get("success", False),
            output=str(result.get("result", result.get("output", ""))),
            error=result.get("error", ""),
            exit_code=0 if result.get("success") else 1,
            execution_time=round(time.time() - _start, 4),
        )

    def list_sandboxes(self) -> dict[str, str]:
        """列出所有沙箱，返回 {名称: 类型} 映射"""
        return {name: type(s).__name__ for name, s in self._sandboxes.items()}

    def create_process_sandbox(self, name: str) -> ProcessSandbox:
        """创建进程沙箱"""
        sandbox = ProcessSandbox(self.config)
        self._sandboxes[name] = sandbox
        return sandbox

    def create_code_sandbox(self, name: str, timeout: float = 5.0) -> CodeSandbox:
        """创建代码沙箱"""
        sandbox = CodeSandbox(timeout=timeout)
        self._sandboxes[name] = sandbox
        return sandbox

    def create_plugin_sandbox(self, name: str, plugin_name: str) -> PluginSandbox:
        """创建插件沙箱"""
        sandbox = PluginSandbox(plugin_name)
        self._sandboxes[name] = sandbox
        return sandbox

    def get(self, name: str) -> Any:
        """获取指定名称的沙箱，不存在则返回 None"""
        return self._sandboxes.get(name)

    def remove(self, name: str) -> None:
        """移除指定名称的沙箱"""
        self._sandboxes.pop(name, None)

    async def cleanup_all(self) -> None:
        """清理所有沙箱"""
        self._sandboxes.clear()


class CodeSandbox:
    """代码沙箱（已弃用，请使用 SubprocessSandbox 或 DockerSandbox）"""

    _DEPRECATED: bool = True

    def __init__(self, timeout: float = 5.0, **kwargs: Any) -> None:
        import warnings

        warnings.warn(
            "CodeSandbox 已弃用，请使用 SubprocessSandbox 或 DockerSandbox 替代",
            DeprecationWarning,
            stacklevel=2,
        )
        self.timeout = timeout

    async def execute(self, code: str) -> SandboxResult:
        """执行 Python 代码，返回沙箱结果"""
        import time as _time

        _start = _time.time()
        result = safe_execute(code, timeout=int(self.timeout))
        elapsed = (_time.time() - _start) * 1000
        return SandboxResult(
            success=result.get("success", False),
            output=str(result.get("result", result.get("output", ""))),
            error=result.get("error", ""),
            exit_code=0 if result.get("success") else 1,
            execution_time=round(_time.time() - _start, 4),
            duration_ms=round(elapsed, 2),
        )


class PluginSandbox:
    """插件沙箱 — 为插件提供隔离的执行环境"""

    def __init__(self, plugin_name: str, config: SandboxConfig | None = None):
        self.plugin_name = plugin_name
        self.config = config or SandboxConfig(
            max_memory_mb=256,
            max_timeout_seconds=30,
            allow_network=False,
        )
        self._process = None

    @property
    def is_running(self) -> bool:
        """检查沙箱是否正在运行"""
        return self._process is not None

    async def start(self) -> bool:
        """启动插件沙箱"""
        self._process = "started"  # 简化实现
        return True

    async def stop(self) -> None:
        """停止插件沙箱"""
        self._process = None

    async def health_check(self) -> bool:
        """健康检查"""
        return self._process is not None


# ══════════════════════════════════════════════════════════
# 核心沙箱执行函数
# ══════════════════════════════════════════════════════════


def safe_execute(code: str, timeout: int = 5) -> dict[str, Any]:
    """安全执行 Python 代码 — 使用 AST 限制 + 受限 globals

    使用 AST 解析限制允许的操作，在受限命名空间中执行。
    """
    # 1. AST 解析检查
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {"success": False, "error": f"SyntaxError: {e}"}

    # 2. 安全检查 - 禁止危险操作
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in ("__import__", "eval", "exec", "compile", "open"):
                    return {"success": False, "error": f"禁止使用危险函数: {node.func.id}"}
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr in ("__import__", "eval", "exec", "compile"):
                    return {"success": False, "error": f"禁止使用危险方法: {node.func.attr}"}

    # 3. 在受限命名空间中执行
    restricted_globals = {
        "__builtins__": {
            "print": print,
            "len": len,
            "range": range,
            "int": int,
            "float": float,
            "str": str,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "bool": bool,
            "True": True,
            "False": False,
            "None": None,
            "abs": abs,
            "all": all,
            "any": any,
            "enumerate": enumerate,
            "filter": filter,
            "map": map,
            "max": max,
            "min": min,
            "reversed": reversed,
            "sorted": sorted,
            "sum": sum,
            "zip": zip,
            "isinstance": isinstance,
            "type": type,
            "hasattr": hasattr,
            "getattr": getattr,
            "setattr": setattr,
            "ValueError": ValueError,
            "TypeError": TypeError,
            "KeyError": KeyError,
            "IndexError": IndexError,
            "AttributeError": AttributeError,
            "Exception": Exception,
        }
    }

    result = {"success": True, "output": "", "error": ""}

    try:
        # 编译并执行
        compiled = compile(tree, "<sandbox>", "exec")

        # 捕获 print 输出和执行结果
        import io
        from contextlib import redirect_stdout

        local_ns: dict[str, Any] = {}
        f = io.StringIO()
        with redirect_stdout(f):
            exec(compiled, restricted_globals, local_ns)

        output = f.getvalue()
        # 如果 stdout 为空且 local_ns 中有 'result' 变量，则将其值加入输出
        if not output and "result" in local_ns:
            output = str(local_ns["result"])
        result["output"] = output
    except Exception as e:
        result["success"] = False
        result["error"] = f"{type(e).__name__}: {e}"

    return result


def safe_exec(code: str, safe_globals: dict | None = None, safe_locals: dict | None = None) -> dict:
    """安全的代码执行 - 在隔离的子进程中运行

    替代 exec() 的安全方案：
    - 在独立的 Python 子进程中执行代码
    - 使用 subprocess 隔离，避免影响主进程
    - 设置超时防止无限循环
    - 限制可用的内置函数
    """
    safe_builtins = {
        "True": True,
        "False": False,
        "None": None,
        "int": int,
        "float": float,
        "str": str,
        "bool": bool,
        "list": list,
        "dict": dict,
        "tuple": tuple,
        "set": set,
        "len": len,
        "range": range,
        "abs": abs,
        "max": max,
        "min": min,
        "sum": sum,
        "round": round,
        "isinstance": isinstance,
        "type": type,
        "enumerate": enumerate,
        "zip": zip,
        "map": map,
        "filter": filter,
        "reversed": reversed,
        "sorted": sorted,
        "any": any,
        "all": all,
        "print": print,
        "open": open,
        "Exception": Exception,
        "ValueError": ValueError,
        "TypeError": TypeError,
        "KeyError": KeyError,
        "IndexError": IndexError,
        "AttributeError": AttributeError,
        "ImportError": ImportError,
        "RuntimeError": RuntimeError,
        "OSError": OSError,
    }

    wrapper_code = f"""
import json
import sys

safe_builtins = {json.dumps({k: str(v) for k, v in safe_builtins.items()})}

try:
    safe_globals = {{'__builtins__': safe_builtins}}
    safe_locals = {{}}

    exec({json.dumps(code)}, safe_globals, safe_locals)

    result = {{
        'success': True,
        'locals': {{k: str(v) for k, v in safe_locals.items() if not k.startswith('_')}},
        'error': None
    }}
except Exception as e:
    result = {{
        'success': False,
        'locals': {{}},
        'error': str(e)
    }}

print(json.dumps(result))
"""

    try:
        proc = subprocess.run(
            ["python", "-c", wrapper_code],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "PYTHONPATH": ""},
        )

        if proc.returncode == 0:
            try:
                result = json.loads(proc.stdout.strip())
                return result
            except json.JSONDecodeError:
                return {
                    "success": False,
                    "locals": {},
                    "error": f"无法解析执行结果: {proc.stdout[:200]}",
                }
        else:
            return {
                "success": False,
                "locals": {},
                "error": f"子进程执行失败: {proc.stderr[:200]}",
            }

    except subprocess.TimeoutExpired:
        return {"success": False, "locals": {}, "error": "代码执行超时（30秒）"}
    except Exception as e:
        return {"success": False, "locals": {}, "error": f"执行异常: {str(e)[:200]}"}
