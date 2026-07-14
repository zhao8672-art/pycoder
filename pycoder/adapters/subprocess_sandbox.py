"""P1-4: SubprocessSandbox — 包装子进程沙箱实现 CodeSandbox 端口

将现有的 _run_in_subprocess 适配为符合 CodeSandbox Protocol 的实现。

H3: 通过依赖注入接收 run_fn 和 max_timeout_fn，消除 adapter → server 反向依赖。
调用方（server 层）在构造时注入具体实现；适配器本身不直接 import server。
"""

from __future__ import annotations

from collections.abc import Callable

from pycoder.core.ports.code_sandbox import (
    CodeExecutionResult,
)


class SubprocessSandbox:
    """CodeSandbox 适配器 — 通过依赖注入接收沙箱执行函数

    用法（依赖注入 — 推荐，adapter 不依赖 server）：
        sandbox = SubprocessSandbox(run_fn=_run_in_subprocess, max_timeout_fn=lambda: 600)
        result = await sandbox.execute("print('hello')")

    用法（向后兼容 — 不传 run_fn 时惰性导入 server）：
        sandbox = SubprocessSandbox()
        result = await sandbox.execute("print('hello')")
    """

    def __init__(
        self,
        default_timeout: int = 30,
        max_timeout: int = 120,
        run_fn: Callable[[str, int], object] | None = None,
        max_timeout_fn: Callable[[], int] | None = None,
    ) -> None:
        self._default_timeout = default_timeout
        self._max_timeout = max_timeout
        # H3: 依赖注入 — 若未提供则惰性从 server 导入（向后兼容）
        self._run_fn = run_fn
        self._max_timeout_fn = max_timeout_fn

    def _resolve_run_fn(self) -> tuple[Callable[[str, int], object], int]:
        """解析执行函数与最大超时。

        P0: 优先使用 DI 注入的函数。如果未注入，发出弃用警告后惰性导入。
        v1.0 将移除惰性导入路径。
        """
        if self._run_fn is not None and self._max_timeout_fn is not None:
            return self._run_fn, self._max_timeout_fn()

        # 向后兼容：未注入时惰性导入 (DEPRECATED, v1.0 移除)
        import logging
        logging.getLogger(__name__).warning(
            "SubprocessSandbox 未通过 DI 注入 run_fn。"
            "请使用 registry.register(CodeSandbox, SubprocessSandbox(run_fn=...))。"
            "惰性导入将在 v1.0 移除。"
        )
        from pycoder.server.routers.code_exec import (  # noqa: E402
            _run_in_subprocess,
            _sandbox_config,
        )

        run = self._run_fn or _run_in_subprocess
        max_t = self._max_timeout_fn() if self._max_timeout_fn else _sandbox_config.max_timeout
        return run, max_t

    async def execute(
        self,
        code: str,
        timeout: int = 30,
    ) -> CodeExecutionResult:
        """执行 Python 代码片段（子进程沙箱隔离）"""
        import asyncio

        run_fn, config_max_timeout = self._resolve_run_fn()
        # 限制超时上限
        timeout = min(timeout, self._max_timeout, config_max_timeout)

        # 子进程沙箱执行（run_fn 是同步函数，用 to_thread 避免阻塞）
        result = await asyncio.to_thread(run_fn, code, timeout)

        return CodeExecutionResult(
            success=result.success,
            stdout=result.stdout,
            stderr=result.stderr,
            error_type=result.error_type,
            error_message=result.error_message,
            traceback=result.traceback,
            execution_time=result.execution_time,
            return_value="",
        )
