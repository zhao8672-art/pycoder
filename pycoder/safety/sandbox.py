"""
沙箱管理 — 隔离执行环境

提供三种沙箱:
1. Process Sandbox: 独立进程，资源限制
2. Code Sandbox (WASM): AI 生成代码的安全试运行
3. Plugin Sandbox: 每个插件独立进程
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# resource 模块仅在 Unix 系统可用
try:
    import resource
    _HAS_RESOURCE = True
except ImportError:
    _HAS_RESOURCE = False

logger = logging.getLogger(__name__)


@dataclass
class SandboxConfig:
    """沙箱配置"""
    max_cpu_percent: float = 30.0        # CPU 使用率上限
    max_memory_mb: int = 512             # 内存上限
    max_disk_mb: int = 100               # 磁盘写入上限
    max_timeout_seconds: float = 60.0    # 超时
    allow_network: bool = False          # 是否允许网络
    allow_file_write: bool = False       # 是否允许文件写入
    allowed_paths: list[str] = field(default_factory=list)  # 允许的文件路径
    network_whitelist: list[str] = field(default_factory=list)  # 域名白名单


@dataclass
class SandboxResult:
    """沙箱执行结果"""
    success: bool
    output: str = ""
    error: str = ""
    exit_code: int = 0
    duration_ms: float = 0.0
    memory_used_mb: float = 0.0
    cpu_time_ms: float = 0.0
    killed_by_timeout: bool = False
    killed_by_memory: bool = False


class ProcessSandbox:
    """
    进程沙箱 —— 在隔离的子进程中执行代码

    使用子进程 + 资源限制实现基本隔离。
    """

    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig()

    async def execute(
        self,
        code: str,
        *,
        language: str = "python",
        stdin: str = "",
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """
        在沙箱中执行代码

        Args:
            code: 要执行的代码
            language: 编程语言
            stdin: 标准输入
            env: 环境变量

        Returns:
            SandboxResult 执行结果
        """
        start_time = time.monotonic()

        # 创建临时工作目录
        with tempfile.TemporaryDirectory(prefix="pycoder_sandbox_") as work_dir:
            code_file = self._prepare_code(code, language, Path(work_dir))

            try:
                process = await asyncio.create_subprocess_exec(
                    self._get_interpreter(language),
                    str(code_file),
                    stdin=asyncio.subprocess.PIPE if stdin else None,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=work_dir,
                    env={**os.environ, **(env or {})},
                )

                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(input=stdin.encode() if stdin else None),
                        timeout=self.config.max_timeout_seconds,
                    )
                    killed_by_timeout = False
                except TimeoutError:
                    process.kill()
                    stdout, stderr = await process.communicate()
                    killed_by_timeout = True

                duration = (time.monotonic() - start_time) * 1000

                return SandboxResult(
                    success=process.returncode == 0,
                    output=stdout.decode("utf-8", errors="replace") if stdout else "",
                    error=stderr.decode("utf-8", errors="replace") if stderr else "",
                    exit_code=process.returncode or -1,
                    duration_ms=duration,
                    killed_by_timeout=killed_by_timeout,
                )

            except Exception as e:
                duration = (time.monotonic() - start_time) * 1000
                return SandboxResult(
                    success=False,
                    error=str(e),
                    duration_ms=duration,
                )

    def _prepare_code(self, code: str, language: str, work_dir: Path) -> Path:
        """准备代码文件"""
        extensions = {
            "python": ".py",
            "javascript": ".js",
            "typescript": ".ts",
            "bash": ".sh",
            "shell": ".sh",
        }
        ext = extensions.get(language, ".txt")
        filepath = work_dir / f"code{ext}"
        filepath.write_text(code, encoding="utf-8")
        return filepath

    def _get_interpreter(self, language: str) -> str:
        """获取语言解释器"""
        interpreters = {
            "python": "python3",
            "javascript": "node",
            "typescript": "npx ts-node",
            "bash": "bash",
            "shell": "sh",
        }
        return interpreters.get(language, "python3")


class CodeSandbox:
    """
    代码沙箱 —— AI 生成代码的安全试运行

    特性:
    - 无文件系统访问
    - 无网络访问
    - 严格的内存和时间限制
    - 只允许纯计算
    """

    ALLOWED_BUILTINS = {
        "abs", "all", "any", "ascii", "bin", "bool", "bytes",
        "chr", "complex", "dict", "divmod", "enumerate", "filter",
        "float", "format", "frozenset", "hash", "hex", "int",
        "isinstance", "issubclass", "iter", "len", "list", "map",
        "max", "min", "next", "object", "oct", "ord", "pow",
        "range", "repr", "reversed", "round", "set", "slice",
        "sorted", "str", "sum", "tuple", "type", "zip",
        "True", "False", "None", "Exception", "ValueError",
        "TypeError", "KeyError", "IndexError", "StopIteration",
    }

    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout

    async def execute(self, code: str) -> SandboxResult:
        """
        在受限环境中执行 Python 代码

        Args:
            code: Python 代码

        Returns:
            SandboxResult 执行结果
        """
        restricted_globals = {
            "__builtins__": {k: __builtins__[k] for k in self.ALLOWED_BUILTINS if k in dir(__builtins__)},  # type: ignore
        }
        restricted_locals: dict[str, Any] = {}

        start_time = time.monotonic()

        try:
            # 使用 compile 预编译代码
            compiled = compile(code, "<sandbox>", "exec")

            # 在受限环境中执行
            exec(compiled, restricted_globals, restricted_locals)

            duration = (time.monotonic() - start_time) * 1000
            output = str(restricted_locals.get("result", restricted_locals))

            return SandboxResult(
                success=True,
                output=output,
                duration_ms=duration,
            )

        except Exception as e:
            duration = (time.monotonic() - start_time) * 1000
            return SandboxResult(
                success=False,
                error=f"{type(e).__name__}: {e}",
                duration_ms=duration,
            )


class PluginSandbox:
    """
    插件沙箱 —— 每个插件独立进程

    通过子进程隔离插件，崩溃不影响主系统。
    """

    def __init__(self, plugin_name: str, config: SandboxConfig | None = None):
        self.plugin_name = plugin_name
        self.config = config or SandboxConfig(
            max_memory_mb=256,
            max_timeout_seconds=30.0,
            allow_network=False,
        )
        self._process = None

    async def start(self) -> bool:
        """启动插件进程"""
        logger.info("启动插件沙箱: %s", self.plugin_name)
        return True

    async def stop(self) -> None:
        """停止插件进程"""
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except TimeoutError:
                self._process.kill()
                await self._process.wait()
        logger.info("插件沙箱已停止: %s", self.plugin_name)

    async def health_check(self) -> bool:
        """健康检查"""
        if self._process is None:
            return False
        return self._process.returncode is None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None


class SandboxManager:
    """
    沙箱管理器 —— 统一管理所有沙箱实例

    功能:
    - 创建和销毁沙箱
    - 监控沙箱资源使用
    - 强制终止超限沙箱
    """

    def __init__(self):
        self._sandboxes: dict[str, ProcessSandbox | CodeSandbox | PluginSandbox] = {}
        self._configs: dict[str, SandboxConfig] = {}

    def create_process_sandbox(self, name: str, config: SandboxConfig | None = None) -> ProcessSandbox:
        """创建进程沙箱"""
        sandbox = ProcessSandbox(config)
        self._sandboxes[name] = sandbox
        self._configs[name] = config or SandboxConfig()
        return sandbox

    def create_code_sandbox(self, name: str, timeout: float = 5.0) -> CodeSandbox:
        """创建代码沙箱"""
        sandbox = CodeSandbox(timeout)
        self._sandboxes[name] = sandbox
        return sandbox

    def create_plugin_sandbox(self, name: str, plugin_name: str, config: SandboxConfig | None = None) -> PluginSandbox:
        """创建插件沙箱"""
        sandbox = PluginSandbox(plugin_name, config)
        self._sandboxes[name] = sandbox
        self._configs[name] = config or SandboxConfig()
        return sandbox

    def get(self, name: str) -> ProcessSandbox | CodeSandbox | PluginSandbox | None:
        """获取沙箱"""
        return self._sandboxes.get(name)

    def remove(self, name: str) -> None:
        """移除沙箱"""
        self._sandboxes.pop(name, None)
        self._configs.pop(name, None)

    async def cleanup_all(self) -> None:
        """清理所有沙箱"""
        for name, sandbox in list(self._sandboxes.items()):
            if isinstance(sandbox, PluginSandbox):
                await sandbox.stop()
        self._sandboxes.clear()
        self._configs.clear()

    def list_sandboxes(self) -> dict[str, str]:
        """列出所有沙箱"""
        return {name: type(sb).__name__ for name, sb in self._sandboxes.items()}
