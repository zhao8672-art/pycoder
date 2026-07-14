"""P1-4: 适配器层 — 实现 core.ports 中定义的接口

依赖方向：adapters → core（实现接口）
adapters 依赖外部库（ChatBridge / subprocess / pathlib），core 不依赖 adapters。

子模块：
    bridge_llm_provider.py  — 包装 ChatBridge 实现 LLMProvider
    subprocess_sandbox.py   — 包装子进程沙箱实现 CodeSandbox
    local_file_system.py   — 包装 pathlib 实现 FileSystem
"""

from __future__ import annotations

from pycoder.adapters.bridge_llm_provider import BridgeLLMProvider
from pycoder.adapters.local_file_system import LocalFileSystem
from pycoder.adapters.subprocess_sandbox import SubprocessSandbox

__all__ = [
    "BridgeLLMProvider",
    "SubprocessSandbox",
    "LocalFileSystem",
]
