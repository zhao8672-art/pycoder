"""P1-4: CodeSandbox 端口 — 代码执行沙箱抽象接口

核心业务逻辑通过此接口执行用户代码，不依赖具体的子进程实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class CodeExecutionResult:
    """代码执行结果"""

    success: bool
    stdout: str = ""
    stderr: str = ""
    error_type: str = ""
    error_message: str = ""
    traceback: str = ""
    execution_time: float = 0.0
    return_value: str = ""


@runtime_checkable
class CodeSandbox(Protocol):
    """代码执行沙箱端口

    实现示例：SubprocessSandbox（包装 _run_in_subprocess）

    安全要求：
        - 必须在隔离环境中执行（子进程 / 容器）
        - 禁止访问主进程变量与文件系统
        - 必须有超时保护
        - 必须拦截危险模块（os / subprocess / socket 等）
    """

    async def execute(
        self,
        code: str,
        timeout: int = 30,
    ) -> CodeExecutionResult:
        """执行 Python 代码片段

        Args:
            code: 要执行的代码
            timeout: 超时时间（秒）

        Returns:
            CodeExecutionResult — 包含 stdout/stderr/error 等
        """
        ...
