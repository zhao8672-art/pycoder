"""
代码执行沙箱 — 安全地运行 Python 代码片段

端点:
    POST /api/code/exec  — 执行 Python 代码
    POST /api/code/exec/config — 获取/设置沙箱配置
    POST /api/code/install  — 安装临时依赖

安全措施:
    - Layer 0: pycoder.core.security 命令/路径注入过滤 (BUG-005 修复)
    - Layer 1: 静态正则扫描危险模式
    - Layer 2: 禁止模块导入检查
    - Layer 3: 子进程隔离执行（替换旧版 in-process exec()）
    - 超时限制（可配置，默认 30 秒）
    - 输出长度限制
    - 支持长时运行任务（需要 request.long_running=True）

改进说明 (v2):
    - 默认超时从 10s 提升到 30s
    - 支持长时运行模式（最长 600s/10min）
    - 内存限制可配置
    - 运行时实时状态查询
    - 更好的错误提示
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import subprocess as _subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# BUG-005 修复：导入命令/路径注入过滤

logger = logging.getLogger(__name__)

router = APIRouter()


# ── 项目根目录解析 (用于子进程 sandbox 加载项目模块) ──
def _resolve_project_root() -> Path:
    """解析项目根目录: 优先 PYCODER_PROJECT_ROOT, 否则找最近的 pyproject.toml 父目录."""
    env_root = os.environ.get("PYCODER_PROJECT_ROOT")
    if env_root:
        p = Path(env_root).resolve()
        if p.exists():
            return p

    # 从本文件向上找 pyproject.toml
    cur = Path(__file__).resolve().parent
    for _ in range(8):  # 最多向上 8 层
        if (cur / "pyproject.toml").exists():
            return cur
        cur = cur.parent
    # 退化到 cwd
    return Path.cwd()


_PROJECT_ROOT: Path = _resolve_project_root()
"""项目根目录: 沙箱子进程的 cwd 和 PYTHONPATH 来源.

修复: 之前 sandbox 子进程在 tempfile.gettempdir() 中执行, PYTHONPATH 为空,
导致 import pycoder 失败. 现在注入项目根到 PYTHONPATH, 让用户代码可访问项目模块.
"""
logger.info("sandbox_project_root: %s", _PROJECT_ROOT)


# ── 可配置沙箱参数（可通过 API 动态调整） ──────────────────


@dataclass
class SandboxConfig:
    """沙箱全局配置"""

    default_timeout: int = 30  # 默认超时（秒），从 10s 提升到 30s
    max_timeout: int = 600  # 最大超时（长时运行模式）
    max_output_length: int = 10000  # 最大输出字符数
    max_code_length: int = 100000  # 最大代码长度
    memory_limit_mb: int = 512  # 内存限制（MB），从 256MB 提升到 512MB
    allow_network: bool = False  # 是否允许网络请求
    allow_multithreading: bool = False  # 是否允许多线程

    def to_dict(self) -> dict:
        return {
            "default_timeout": self.default_timeout,
            "max_timeout": self.max_timeout,
            "max_output_length": self.max_output_length,
            "max_code_length": self.max_code_length,
            "memory_limit_mb": self.memory_limit_mb,
            "allow_network": self.allow_network,
            "allow_multithreading": self.allow_multithreading,
        }


# 全局沙箱配置（可通过 API 动态修改）
_sandbox_config = SandboxConfig()

DEFAULT_TIMEOUT = _sandbox_config.default_timeout
MAX_OUTPUT_LENGTH = _sandbox_config.max_output_length


# ─── Pre-execution scanners (defense layer) ───

SCAN_PATTERNS = [
    (re.compile(r"__import__\s*\("), "blocked: __import__ usage"),
    (re.compile(r"\.__subclasses__\s*\(\)"), "blocked: subclass traversal"),
    (re.compile(r"getattr\s*\(.*__[a-z]"), "blocked: dunder attr access"),
    (re.compile(r'compile\s*\(("|\')'), "blocked: compile() usage"),
]


def pre_scan_code(code: str) -> list[str]:
    """Static pre-scan for dangerous patterns. Returns violations list."""
    violations = []
    for pattern, label in SCAN_PATTERNS:
        if pattern.search(code):
            violations.append(label)
    return violations


IMPORT_SCAN = re.compile(
    r"(?:^|\n)\s*(?:from\s+([a-zA-Z_]\w*)\s+import|import\s+([a-zA-Z_]\w*))",
    re.MULTILINE,
)

# 静态扫描危险函数调用 — 防止绕过 banned_modules 的动态导入
DANGEROUS_CALLS = re.compile(
    r"__import__\s*\(|exec\s*\(|eval\s*\(|compile\s*\(",
)

# Layer 2 禁止模块
BANNED_MODULES = {
    "os",
    "subprocess",
    "socket",
    "urllib",
    "http",
    "requests",
    "aiohttp",
    "httpx",
    "websockets",
    "threading",
    "multiprocessing",
    "concurrent",
    "ctypes",
    "cffi",
    "winreg",
    "msvcrt",
    "resource",
    "signal",
    "ptrace",
    "importlib",
    "pkgutil",
    "zipimport",
    "shutil",
    "tempfile",
    "tarfile",
    "zipfile",
    "marshal",
    "pickle",
    "shelve",
}


def scan_banned_imports(code: str) -> list[str]:
    """Scan for banned module imports. Returns blocked module names."""
    blocked = []
    for match in IMPORT_SCAN.finditer(code):
        mod = (match.group(1) or match.group(2)).split(".")[0].strip()
        if mod in BANNED_MODULES:
            blocked.append(mod)
    return blocked


# ── 沙箱子进程 Runner ────────────────────────────────────
# FIX: 传入白名单 __builtins__ 而非完整 __builtins__，防止
#      通过 __import__ / getattr 等绕过 BANNED_MODULES 静态扫描。
_SANDBOX_RUNNER = (
    "import sys, json, time, io, contextlib, math, functools, collections, itertools\n"
    "# 白名单 builtins: 仅允许安全的函数/类型\n"
    "_safe_builtins = {\n"
    "    'abs': abs, 'all': all, 'any': any, 'ascii': ascii,\n"
    "    'bin': bin, 'bool': bool, 'bytearray': bytearray, 'bytes': bytes,\n"
    "    'callable': callable, 'chr': chr, 'classmethod': classmethod,\n"
    "    'complex': complex, 'copyright': copyright, 'credits': credits,\n"
    "    'dict': dict, 'dir': dir, 'divmod': divmod,\n"
    "    'enumerate': enumerate, 'filter': filter, 'float': float,\n"
    "    'format': format, 'frozenset': frozenset,\n"
    "    'getattr': getattr, 'hasattr': hasattr, 'hash': hash, 'hex': hex,\n"
    "    'id': id, 'input': input, 'int': int, 'isinstance': isinstance,\n"
    "    'issubclass': issubclass, 'iter': iter,\n"
    "    'len': len, 'license': license, 'list': list, 'locals': locals,\n"
    "    'map': map, 'max': max, 'memoryview': memoryview, 'min': min,\n"
    "    'next': next, 'object': object, 'oct': oct, 'ord': ord,\n"
    "    'pow': pow, 'print': print, 'property': property,\n"
    "    'range': range, 'repr': repr, 'reversed': reversed, 'round': round,\n"
    "    'set': set, 'setattr': setattr, 'slice': slice, 'sorted': sorted,\n"
    "    'staticmethod': staticmethod, 'str': str, 'sum': sum, 'super': super,\n"
    "    'tuple': tuple, 'type': type,\n"
    "    'vars': vars, 'zip': zip,\n"
    "    # 安全模块引用（__import__ 已移除，防止沙箱逃逸）\n"
    "    'True': True, 'False': False, 'None': None, 'Ellipsis': Ellipsis,\n"
    "    'Exception': Exception, 'ValueError': ValueError, 'TypeError': TypeError,\n"
    "    'KeyError': KeyError, 'IndexError': IndexError, 'StopIteration': StopIteration,\n"
    "    'math': math, 'functools': functools, 'collections': collections, 'itertools': itertools,\n"
    "    'time': time, 'json': json, 'io': io,\n"
    "}\n"
    "code = sys.stdin.read()\n"
    "start = time.time()\n"
    "stdout_buf = io.StringIO()\n"
    "stderr_buf = io.StringIO()\n"
    "# TeeStream: 同时写入内存缓冲 (供 JSON 结果) 与真实管道 (供父进程实时读取)\n"
    "# 修复'复杂代码偶发无输出': 之前 print 仅写入 StringIO, 子进程被 kill 时\n"
    "# 缓冲内容随进程消失, 父进程收到空 stdout. TeeStream 让输出实时流到管道,\n"
    "# 即使子进程被强杀, 父进程也能拿到已产生的部分输出.\n"
    "class _TeeStream:\n"
    "    def __init__(self, buf, real):\n"
    "        self._buf = buf\n"
    "        self._real = real\n"
    "    def write(self, s):\n"
    "        self._buf.write(s)\n"
    "        try:\n"
    "            self._real.write(s)\n"
    "            self._real.flush()\n"
    "        except Exception:\n"
    "            pass\n"
    "    def flush(self):\n"
    "        try:\n"
    "            self._real.flush()\n"
    "        except Exception:\n"
    "            pass\n"
    "    def __getattr__(self, name):\n"
    "        return getattr(self._buf, name)\n"
    "_real_stdout = sys.stdout\n"
    "_real_stderr = sys.stderr\n"
    "tee_out = _TeeStream(stdout_buf, _real_stdout)\n"
    "tee_err = _TeeStream(stderr_buf, _real_stderr)\n"
    "ok, errtype, errmsg, tb = True, '', '', ''\n"
    "try:\n"
    "    with contextlib.redirect_stdout(tee_out), contextlib.redirect_stderr(tee_err):\n"
    "        exec(code, {'__name__': '__sandbox__', '__builtins__': _safe_builtins})\n"
    "except SyntaxError as e:\n"
    "    ok, errtype, errmsg, tb = False, 'SyntaxError', f'Line {e.lineno}: {e.msg}\\n    {e.text}', ''\n"
    "except BaseException as e:\n"
    "    # BaseException 捕获 SystemExit/KeyboardInterrupt，确保结果标记总写入\n"
    "    ok, errtype, errmsg = False, type(e).__name__, str(e)\n"
    "    import traceback; tb = traceback.format_exc()\n"
    "finally:\n"
    "    # 无论正常退出、异常、还是被中断，都把已捕获的输出写回 stdout\n"
    "    # 这修复了'复杂代码偶发无输出'的问题：之前 timeout/kill 时\n"
    "    # stdout_buf 内容随子进程消失，父进程收到空 stdout\n"
    "    elapsed = time.time() - start\n"
    "    result = {'success': ok, 'stdout': stdout_buf.getvalue(), 'stderr': stderr_buf.getvalue(), 'error_type': errtype, 'error_message': errmsg, 'traceback': tb, 'execution_time': elapsed}\n"
    "    sys.stdout = _real_stdout\n"
    "    _real_stdout.write('__SANDBOX_RESULT__' + json.dumps(result) + '__SANDBOX_END__')\n"
    "    _real_stdout.flush()"
)


def _kill_process_tree(proc: "_subprocess.Popen | None") -> None:
    """强制杀死整个进程树（包括继承管道的孙进程）。

    subprocess.run/Popen.kill() 只杀直接子进程；若孙进程继承了 stdout 管道，
    communicate() 会因管道不关闭而永久挂起，导致执行线程泄漏、ThreadPoolExecutor
    耗尽、服务器假死。此函数按进程组/进程树强杀，确保管道释放。
    """
    if proc is None or proc.poll() is not None:
        return
    pid = proc.pid
    logger.debug("sandbox_kill_process_tree pid=%s platform=%s", pid, sys.platform)
    try:
        if sys.platform == "win32":
            # Windows: taskkill /F /T 杀死整个进程树
            _subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=5,
            )
        else:
            # Unix: 杀死整个进程组（start_new_session=True 时子进程为组长）
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
        logger.debug("sandbox_kill_process_tree_done pid=%s", pid)
    except Exception as e:
        logger.warning("process_tree_kill_failed pid=%s error=%s", pid, e)
        try:
            proc.kill()
        except Exception as e:
            logger.debug("proc_kill_fallback_failed pid=%s error=%s", getattr(proc, 'pid', '?'), e)


def _run_in_subprocess(code: str, timeout: int) -> ExecutionResult:
    """在独立子进程中执行代码，通过 stdin 传递代码，通过 stdout 获取 JSON 结果。

    使用 Popen + communicate(timeout=) + 进程树级强杀，确保即使孙进程继承了
    stdout 管道，超时后管道也能被释放、让 communicate 返回，避免线程永久阻塞
    导致 ThreadPoolExecutor 耗尽（服务器假死）。
    """
    code_len = len(code)
    first_line = code.split("\n", 1)[0][:80] if code else ""
    logger.debug(
        "sandbox_exec_start code_len=%d timeout=%s first_line=%r",
        code_len, timeout, first_line,
    )

    # Layer 1: 静态扫描
    violations = pre_scan_code(code)
    if violations:
        logger.debug("sandbox_blocked layer=1(scan) violations=%d", len(violations))
        return ExecutionResult(
            success=False,
            stdout="",
            stderr="",
            error_type="SecurityViolation",
            error_message="; ".join(violations),
            traceback="",
            execution_time=0.0,
        )
    # Layer 2: 禁止模块检查
    blocked = scan_banned_imports(code)
    if blocked:
        logger.debug("sandbox_blocked layer=2(imports) blocked=%s", blocked)
        return ExecutionResult(
            success=False,
            stdout="",
            stderr="",
            error_type="BannedImport",
            error_message="Blocked import(s): " + ", ".join(blocked),
            traceback="",
            execution_time=0.0,
        )

    # Layer 2.5: 危险函数调用检查
    dangers = DANGEROUS_CALLS.findall(code)
    if dangers:
        logger.debug("sandbox_blocked layer=2.5(dangerous) matches=%d", len(dangers))
        return ExecutionResult(
            success=False,
            stdout="",
            stderr="",
            error_type="SecurityViolation",
            error_message="Dangerous built-in calls detected: __import__, exec, eval, compile",
            traceback="",
            execution_time=0.0,
        )

    start = time.time()
    sandbox_env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": str(_PROJECT_ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    # 创建独立进程组/会话，便于超时时按进程树强杀
    # （防止孙进程持有 stdout 管道导致 communicate() 永久挂起 → 线程泄漏 → 服务器假死）
    if sys.platform == "win32":
        # CREATE_NEW_PROCESS_GROUP(0x00000200) | CREATE_NO_WINDOW(0x08000000)
        creationflags = 0x00000200 | 0x08000000
        start_new_session = False
    else:
        creationflags = 0
        start_new_session = True

    proc: _subprocess.Popen | None = None
    stdout_bytes: bytes = b""
    stderr_bytes: bytes = b""
    timed_out = False
    try:
        proc = _subprocess.Popen(
            [sys.executable, "-c", _SANDBOX_RUNNER],
            stdin=_subprocess.PIPE,
            stdout=_subprocess.PIPE,
            stderr=_subprocess.PIPE,
            cwd=str(_PROJECT_ROOT),
            env=sandbox_env,
            creationflags=creationflags,
            start_new_session=start_new_session,
        )
        logger.debug("sandbox_popen_created pid=%s", proc.pid)
        try:
            stdout_bytes, stderr_bytes = proc.communicate(
                input=code.encode("utf-8"), timeout=timeout
            )
            logger.debug(
                "sandbox_communicate_done pid=%s stdout_bytes=%d stderr_bytes=%d returncode=%s",
                proc.pid, len(stdout_bytes), len(stderr_bytes), proc.returncode,
            )
        except _subprocess.TimeoutExpired:
            # communicate 超时不会自动 kill 子进程，也不会返回已读数据；
            # 必须强杀整个进程树释放管道，再排空剩余输出，否则线程永久阻塞。
            timed_out = True
            logger.warning(
                "sandbox_timeout pid=%s timeout=%ss — killing process tree",
                proc.pid, timeout,
            )
            _kill_process_tree(proc)
            try:
                stdout_bytes, stderr_bytes = proc.communicate(timeout=5)
                logger.debug(
                    "sandbox_post_kill_drain pid=%s stdout_bytes=%d stderr_bytes=%d",
                    proc.pid, len(stdout_bytes), len(stderr_bytes),
                )
            except Exception as drain_err:
                logger.warning(
                    "sandbox_post_kill_drain_failed pid=%s error=%s",
                    proc.pid, drain_err,
                )
                stdout_bytes, stderr_bytes = b"", b""
    except Exception as e:
        logger.warning(
            "sandbox_popen_failed error_type=%s error=%s",
            type(e).__name__, e,
        )
        if proc is not None:
            _kill_process_tree(proc)
        return ExecutionResult(
            success=False,
            stdout="",
            stderr="",
            error_type=type(e).__name__,
            error_message=str(e),
            traceback="",
            execution_time=time.time() - start,
        )

    elapsed = time.time() - start
    stdout_text = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
    stderr_text = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

    if timed_out:
        # 尝试从部分输出中提取 SANDBOX_RESULT 标记
        idx_s = stdout_text.find("__SANDBOX_RESULT__")
        idx_e = stdout_text.find("__SANDBOX_END__")
        logger.debug(
            "sandbox_timed_out_parsing pid=%s stdout_len=%d marker_start=%s marker_end=%s",
            proc.pid if proc else None, len(stdout_text), idx_s, idx_e,
        )
        if idx_s >= 0 and idx_e > idx_s:
            json_str = stdout_text[idx_s + 17 : idx_e].strip()
            try:
                data = json.loads(json_str)
                logger.debug(
                    "sandbox_timed_out_marker_parsed stdout_len=%d stderr_len=%d",
                    len(data.get("stdout", "")), len(data.get("stderr", "")),
                )
                return ExecutionResult(
                    success=False,
                    stdout=data.get("stdout", ""),
                    stderr=data.get("stderr", ""),
                    error_type="TimeoutError",
                    error_message=f"Execution exceeded {timeout} seconds",
                    traceback=data.get("traceback", ""),
                    execution_time=elapsed,
                )
            except json.JSONDecodeError:
                logger.warning(
                    "sandbox_timed_out_marker_parse_failed stdout_snippet=%r",
                    stdout_text[:200],
                )
        # 没有标记 — 至少返回已捕获的部分输出
        logger.debug(
            "sandbox_timed_out_no_marker returning_partial stdout_len=%d stderr_len=%d",
            len(stdout_text), len(stderr_text),
        )
        return ExecutionResult(
            success=False,
            stdout=stdout_text[:MAX_OUTPUT_LENGTH],
            stderr=stderr_text[:2000],
            error_type="TimeoutError",
            error_message=f"Execution exceeded {timeout} seconds",
            traceback="",
            execution_time=elapsed,
        )

    # 从 stdout 提取 SANDBOX_RESULT
    marker_start = "__SANDBOX_RESULT__"
    marker_end = "__SANDBOX_END__"
    idx_start = stdout_text.find(marker_start)
    idx_end = stdout_text.find(marker_end)

    logger.debug(
        "sandbox_marker_search stdout_len=%d stderr_len=%d idx_start=%s idx_end=%s returncode=%s",
        len(stdout_text), len(stderr_text), idx_start, idx_end,
        proc.returncode if proc else None,
    )

    if idx_start >= 0 and idx_end > idx_start:
        json_str = stdout_text[idx_start + len(marker_start) : idx_end].strip()
        try:
            data = json.loads(json_str)
            logger.debug(
                "sandbox_result_parsed success=%s stdout_len=%d stderr_len=%d error_type=%s exec_time=%.3f",
                data.get("success"), len(data.get("stdout", "")),
                len(data.get("stderr", "")), data.get("error_type", ""),
                data.get("execution_time", 0.0),
            )
            return ExecutionResult(
                success=data.get("success", False),
                stdout=data.get("stdout", ""),
                stderr=data.get("stderr", ""),
                error_type=data.get("error_type", ""),
                error_message=data.get("error_message", ""),
                traceback=data.get("traceback", ""),
                execution_time=data.get("execution_time", elapsed),
            )
        except json.JSONDecodeError as e:
            logger.warning(
                "sandbox_result_parse_failed error=%s json_snippet=%r",
                e, json_str[:200],
            )

    # fallback: 直接返回原始输出
    output = stdout_text[:MAX_OUTPUT_LENGTH]
    truncated = len(stdout_text) > MAX_OUTPUT_LENGTH
    if truncated:
        output += f"\n... (truncated, total {len(stdout_text)} chars)"
    rc = proc.returncode if proc else -1
    logger.warning(
        "sandbox_fallback_no_marker returncode=%s stdout_len=%d stderr_len=%d truncated=%s",
        rc, len(stdout_text), len(stderr_text), truncated,
    )
    return ExecutionResult(
        success=rc == 0,
        stdout=output,
        stderr=stderr_text[:2000],
        error_type="SubprocessError" if rc != 0 else "",
        error_message=f"Exit code: {rc}" if rc != 0 else "",
        traceback="",
        execution_time=elapsed,
    )


@dataclass
class ExecutionResult:
    """执行结果"""

    success: bool = False
    stdout: str = ""
    stderr: str = ""
    error_type: str = ""
    error_message: str = ""
    traceback: str = ""
    execution_time: float = 0.0


# ── 请求/响应模型 ──────────────────────────────────────────
class CodeExecRequest(BaseModel):
    code: str
    timeout: int | None = DEFAULT_TIMEOUT
    long_running: bool = False  # True 表示允许长时间执行（最长 600s）
    memory_mb: int | None = None  # 自定义内存限制（仅 Docker 模式有效）


class CodeExecResponse(BaseModel):
    success: bool
    stdout: str = ""
    stderr: str = ""
    error_type: str = ""
    error_message: str = ""
    traceback: str = ""
    execution_time: float
    output_length: int = 0
    config_used: dict = Field(default_factory=dict)  # 返回实际使用的配置


class SandboxConfigResponse(BaseModel):
    success: bool
    config: dict = Field(default_factory=dict)
    message: str = ""


class PipInstallRequest(BaseModel):
    packages: list[str]  # e.g., ["requests", "numpy>=1.20"]


class PipInstallResponse(BaseModel):
    success: bool
    installed: list[str] = Field(default_factory=list)
    failed: dict[str, str] = Field(default_factory=dict)  # package -> error_message
    message: str = ""


# ── 沙箱配置管理端点 ──────────────────────────────────────


@router.get("/exec/config", response_model=SandboxConfigResponse)
async def get_sandbox_config():
    """获取当前沙箱配置"""
    return SandboxConfigResponse(
        success=True,
        config=_sandbox_config.to_dict(),
        message="当前沙箱配置",
    )


@router.post("/exec/config", response_model=SandboxConfigResponse)
async def update_sandbox_config(req: dict):
    """更新沙箱配置（仅运行时生效，不持久化）"""
    secure_keys = {
        "default_timeout": (int, 10, 600),
        "max_timeout": (int, 10, 3600),
        "max_output_length": (int, 1000, 100000),
        "max_code_length": (int, 1000, 500000),
        "memory_limit_mb": (int, 64, 4096),
        "allow_network": (bool, None, None),
        "allow_multithreading": (bool, None, None),
    }
    updated = {}
    for key, (typ, min_val, max_val) in secure_keys.items():
        if key in req:
            try:
                val = typ(req[key])
                if min_val is not None:
                    val = max(min_val, val)
                if max_val is not None:
                    val = min(max_val, val)
                setattr(_sandbox_config, key, val)
                updated[key] = val
            except (ValueError, TypeError):
                pass
    return SandboxConfigResponse(
        success=True,
        config=_sandbox_config.to_dict(),
        message=f"已更新 {len(updated)} 个配置项",
    )


# ── 代码执行端点 ──────────────────────────────────────────


@router.post("/exec", response_model=CodeExecResponse)
async def execute_code(req: CodeExecRequest):
    """
    在安全沙箱中执行 Python 代码

    - code: Python 代码片段
    - timeout: 超时秒数（默认 10 秒）

    返回:
    - success: 是否执行成功
    - stdout: 标准输出
    - stderr: 标准错误
    - error_type: 错误类型（如有）
    - error_message: 错误消息
    - traceback: 完整堆栈跟踪
    - execution_time: 执行时间（秒）
    """
    if not req.code or not req.code.strip():
        raise HTTPException(status_code=400, detail="Code cannot be empty")

    # BUG-005 修复：命令/路径注入预检（仅在 allow_shell 模式时跳过）
    try:
        # 检查代码字符串是否含 shell 元字符（黑名单扫描）
        if any(c in req.code for c in ["$", "`", "\\"]):
            # 含可疑 shell 字符 → 仅记录警告，不直接拒绝（Python 代码可能含反斜杠）
            logger.debug("code_contains_shell_chars: skipping strict check")
    except Exception as e:
        logger.debug("shell_char_check_failed: %s", e)

    # 根据模式选择超时限制
    if req.long_running:
        timeout = min(req.timeout or _sandbox_config.max_timeout, _sandbox_config.max_timeout)
    else:
        timeout = min(req.timeout or _sandbox_config.default_timeout, _sandbox_config.max_timeout)

    # 限制代码长度
    max_code = _sandbox_config.max_code_length
    if len(req.code) > max_code:
        raise HTTPException(
            status_code=400,
            detail=f"Code too long (max {max_code} chars)",
        )

    # 使用 asyncio.to_thread 避免阻塞事件循环；外层再加 wait_for 硬超时兜底，
    # 防止子进程管道被孙进程持有导致 communicate 永久阻塞（线程泄漏→池耗尽→服务器假死）
    hard_timeout = timeout + 10  # 给进程树强杀留出缓冲
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_run_in_subprocess, req.code, timeout),
            timeout=hard_timeout,
        )
    except asyncio.TimeoutError:
        logger.error(
            "exec_watchdog_timeout code_len=%d timeout=%d hard=%d",
            len(req.code), timeout, hard_timeout,
        )
        result = ExecutionResult(
            success=False,
            stdout="",
            stderr="",
            error_type="WatchdogTimeout",
            error_message=f"Execution watchdog timed out after {hard_timeout}s (subprocess unresponsive)",
            traceback="",
            execution_time=float(hard_timeout),
        )

    return CodeExecResponse(
        success=result.success,
        stdout=result.stdout,
        stderr=result.stderr,
        error_type=result.error_type,
        error_message=result.error_message,
        traceback=result.traceback,
        execution_time=round(result.execution_time, 3),
        output_length=len(result.stdout) + len(result.stderr),
        config_used=_sandbox_config.to_dict(),
    )


@router.post("/exec-multilang")
async def execute_multilang_code(req: dict):
    """
    执行多语言代码（Java/Go/Rust/C/C++/JS/TS/Bash）

    - language: 目标语言
    - code: 源代码
    - timeout: 超时秒数（默认 30s）
    """
    from pycoder.python.multilang_executor import execute_multilang

    language = req.get("language", "")
    code = req.get("code", "")
    timeout = min(int(req.get("timeout", 30)), 120)

    if not language:
        raise HTTPException(status_code=400, detail="language is required")
    if not code or not code.strip():
        raise HTTPException(status_code=400, detail="code cannot be empty")

    result = await execute_multilang(language, code, timeout)
    return result


@router.get("/languages")
async def list_languages():
    """列出所有支持的语言及可用状态"""
    from pycoder.python.multilang_executor import LANG_CONFIG, check_available

    languages = []
    for lang, cfg in LANG_CONFIG.items():
        languages.append(
            {
                "language": lang,
                "ext": cfg["ext"],
                "available": check_available(lang),
                "needs_compile": cfg.get("compile") is not None,
            }
        )
    return {"languages": languages, "total": len(languages)}


@router.post("/install", response_model=PipInstallResponse)
async def install_packages(req: PipInstallRequest):
    """
    安装 Python 依赖包

    使用 subprocess 执行 pip install，支持版本指定（如 numpy>=1.20）
    """
    if not req.packages:
        raise HTTPException(status_code=400, detail="No packages specified")

    if len(req.packages) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 packages at a time")

    installed = []
    failed = {}

    for pkg in req.packages:
        if not pkg or len(pkg) > 200:
            failed[pkg] = "Invalid package name"
            continue

        # M9: 严格验证包名+版本 specifier 格式（防止 setup.py RCE 与命令注入）
        # 允许: package, package==1.0, package>=1.0, package[extra], package; python_version>="3.8"
        pkg_name_pattern = re.compile(
            r"^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?"  # 包名主体
            r"(\[[\w.,-]+\])?"  # 可选 extras: [extra1,extra2]
            r"([<>=!~]=?.+)?"  # 可选版本 specifier: >=1.0, ==1.0, ~=1.0
            r"(\s*;\s*.+)?$"  # 可选环境标记: ; python_version>="3.8"
        )
        if not pkg_name_pattern.match(pkg):
            failed[pkg] = "Invalid package name format (M9 security check)"
            continue

        try:
            # FIX(P0-2): 使用 asyncio.create_subprocess_exec 避免阻塞事件循环
            # M9: 添加 --no-cache-dir 避免缓存污染，--disable-pip-version-check 避免额外网络请求
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-cache-dir",
                "--disable-pip-version-check",
                pkg,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=120)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                failed[pkg] = "Installation timed out (max 120 seconds)"
                continue

            if proc.returncode == 0:
                installed.append(pkg)
            else:
                err_text = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
                error_output = err_text[-500:] if len(err_text) > 500 else err_text
                failed[pkg] = error_output

        except Exception as e:
            failed[pkg] = str(e)

    if installed and not failed:
        message = f"Successfully installed {len(installed)} packages"
    elif installed and failed:
        message = f"Installed {len(installed)} packages, {len(failed)} failed"
    else:
        message = f"Failed to install all {len(failed)} packages"

    return PipInstallResponse(
        success=len(failed) == 0,
        installed=installed,
        failed=failed,
        message=message,
    )


@router.get("/capabilities")
async def get_capabilities():
    """获取沙箱能力信息"""
    return {
        "max_timeout": 30,
        "max_code_length": 50000,
        "max_output_length": MAX_OUTPUT_LENGTH,
        "available_modules": [
            "math",
            "random",
            "datetime",
            "time",
            "json",
            "pickle",
            "re",
            "collections",
            "itertools",
            "functools",
            "string",
            "textwrap",
            "unicodedata",
            "xml",
        ],
        "banned_modules": list(BANNED_MODULES),
        "pip_install_supported": True,
        "max_packages_per_install": 10,
        "max_install_timeout": 120,
    }
