"""P1-4: 核心端口（Port）— 业务逻辑依赖的抽象接口

按 Clean Architecture 原则，核心业务逻辑应依赖接口而非具体实现。
本包定义以下端口：

- LLMProvider: 大语言模型调用接口
- CodeSandbox: 代码执行沙箱接口
- FileSystem: 文件系统操作接口

具体实现位于 pycoder.adapters 包。
"""

from __future__ import annotations

from pycoder.core.ports.code_sandbox import (
    CodeExecutionResult,
    CodeSandbox,
)
from pycoder.core.ports.file_system import FileSystem
from pycoder.core.ports.llm_provider import LLMEvent, LLMProvider, LLMResponse

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "LLMEvent",
    "CodeSandbox",
    "CodeExecutionResult",
    "FileSystem",
]
