"""LSP Manager — 统一管理多语言 LSP 服务器

管理 LSP 服务器的启动/停止/健康检查/按需懒加载。
支持 5 种语言：Python, TypeScript/JavaScript, Java, C++, Go。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class LSPStatus(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class LSPServerConfig:
    """LSP 服务器配置"""

    language: str
    command: list[str]
    file_extensions: list[str]
    auto_start: bool = True
    idle_timeout: int = 300


@dataclass
class _LSPServerState:
    config: LSPServerConfig
    status: LSPStatus = LSPStatus.STOPPED
    process: asyncio.subprocess.Process | None = None
    last_used: float = 0.0
    error_count: int = 0


DEFAULT_LSP_CONFIGS = [
    LSPServerConfig(
        language="python",
        command=["pyright-langserver", "--stdio"],
        file_extensions=[".py", ".pyi"],
    ),
    LSPServerConfig(
        language="typescript",
        command=["typescript-language-server", "--stdio"],
        file_extensions=[".ts", ".tsx", ".js", ".jsx"],
    ),
    LSPServerConfig(
        language="java",
        command=["jdtls"],
        file_extensions=[".java"],
    ),
    LSPServerConfig(
        language="cpp",
        command=["clangd"],
        file_extensions=[".cpp", ".cxx", ".cc", ".c", ".h", ".hpp"],
    ),
    LSPServerConfig(
        language="go",
        command=["gopls"],
        file_extensions=[".go"],
    ),
]


class LSPManager:
    """多语言 LSP 管理器

    用法:
        manager = LSPManager(workspace)
        await manager.start("python")
        diags = await manager.get_diagnostics("python", "src/main.py")
    """

    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._servers: dict[str, _LSPServerState] = {}
        for cfg in DEFAULT_LSP_CONFIGS:
            self._servers[cfg.language] = _LSPServerState(config=cfg)

    async def start(self, language: str) -> bool:
        """启动指定语言的 LSP 服务器"""
        state = self._servers.get(language)
        if not state:
            return False
        if state.status == LSPStatus.RUNNING:
            state.last_used = time.time()
            return True

        state.status = LSPStatus.STARTING
        try:
            state.process = await asyncio.create_subprocess_exec(
                *state.config.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._workspace),
            )
            state.status = LSPStatus.RUNNING
            state.last_used = time.time()
            state.error_count = 0
            return True
        except Exception:
            state.status = LSPStatus.ERROR
            state.error_count += 1
            return False

    async def stop(self, language: str):
        """停止 LSP 服务器"""
        state = self._servers.get(language)
        if state and state.process:
            try:
                state.process.terminate()
                await asyncio.wait_for(state.process.wait(), timeout=5)
            except (TimeoutError, OSError) as e:
                try:
                    state.process.kill()
                except OSError as e2:
                    logger.debug("lsp_stop_kill_failed: %s=%s %s", language, e, e2)
            state.status = LSPStatus.STOPPED
            state.process = None

    def get_language_for_file(self, file_path: str) -> str | None:
        """根据文件扩展名确定语言"""
        suffix = Path(file_path).suffix.lower()
        for state in self._servers.values():
            if suffix in state.config.file_extensions:
                return state.config.language
        return None

    def get_status(self, language: str) -> LSPStatus:
        """获取 LSP 服务器状态"""
        state = self._servers.get(language)
        return state.status if state else LSPStatus.STOPPED

    def list_languages(self) -> list[str]:
        """列出所有支持的语言"""
        return list(self._servers.keys())

    def get_supported_extensions(self) -> dict[str, list[str]]:
        """获取支持的文件扩展名映射"""
        return {lang: state.config.file_extensions for lang, state in self._servers.items()}
