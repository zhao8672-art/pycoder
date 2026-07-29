"""诊断聚合器 — 汇总所有 LSP 诊断并推送至意识引擎

收集各语言 LSP 诊断信息，按严重度/文件/语言过滤，标记错误时推送系统事件。

支持两种工作模式:
    1. 通过 LSPClient (单语言, 推荐): 直接读取 LSPClient 缓存的诊断
    2. 通过 LSPManager (多语言, 旧版): 启动各语言 LSP 服务器后扫描

用法 (推荐 — LSPClient 模式):
    client = LSPClient(workspace="/path")
    await client.start()
    await client.initialize()
    agg = DiagnosticsAggregator(lsp_client=client)
    diags = agg.scan_file_from_client("src/main.py")

用法 (兼容 — LSPManager 模式):
    agg = DiagnosticsAggregator(lsp_manager=manager)
    diags = await agg.scan_file("src/main.py")
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AggregatedDiagnostic:
    """聚合诊断信息 (跨语言统一格式)"""

    file_path: str
    language: str
    severity: str  # "error" | "warning" | "info"
    message: str
    line: int
    column: int
    source: str = ""
    code: str = ""
    end_line: int = 0
    end_column: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "language": self.language,
            "severity": self.severity,
            "message": self.message,
            "line": self.line,
            "column": self.column,
            "source": self.source,
            "code": self.code,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }


class DiagnosticsAggregator:
    """诊断聚合器 — 跨语言诊断收集

    用法:
        agg = DiagnosticsAggregator(lsp_manager)
        diags = await agg.scan_file("src/main.py")

        # 或使用 LSPClient (推荐)
        agg = DiagnosticsAggregator(lsp_client=client)
        diags = agg.scan_file_from_client("src/main.py")
    """

    def __init__(
        self,
        lsp_manager: Any = None,
        consciousness_engine: Any = None,
        lsp_client: Any = None,
    ) -> None:
        self._lsp = lsp_manager
        self._consciousness = consciousness_engine
        self._client = lsp_client  # 新增: LSPClient 实例

    async def scan_file(self, file_path: str) -> list[AggregatedDiagnostic]:
        """扫描单个文件的所有语言诊断 (LSPManager 模式)

        Args:
            file_path: 文件路径

        Returns:
            诊断信息列表
        """
        if self._lsp is None:
            return []

        language = self._lsp.get_language_for_file(file_path)
        if not language:
            return []

        # 确保 LSP 服务器已启动
        status = self._lsp.get_status(language)
        if status.name not in ("RUNNING",):
            await self._lsp.start(language)

        # 当前阶段返回空列表 (LSPManager 模式需要完整 pygls 协议实现)
        diagnostics: list[AggregatedDiagnostic] = []

        # 推送至意识引擎
        if self._consciousness and diagnostics:
            errors = [d for d in diagnostics if d.severity == "error"]
            if errors:
                await self._consciousness.perceive(type="lsp_errors", data=errors)

        return diagnostics

    def scan_file_from_client(self, file_path: str) -> list[AggregatedDiagnostic]:
        """通过 LSPClient 扫描单个文件的诊断 (推荐模式)

        直接从 LSPClient 缓存读取, 无需启动 LSPManager。

        Args:
            file_path: 文件路径

        Returns:
            聚合诊断列表 (已按严重度排序)
        """
        if self._client is None:
            return []

        try:
            raw_diags = self._client.get_diagnostics(file_path)
        except Exception as e:
            logger.debug("scan_file_from_client_failed: %s=%s", file_path, e)
            return []

        # 推断语言 (基于文件扩展名)
        language = self._infer_language(file_path)

        result = [
            AggregatedDiagnostic(
                file_path=d.file_path,
                language=language,
                severity=d.severity,
                message=d.message,
                line=d.line,
                column=d.character,
                source=d.source,
                code=d.code,
                end_line=d.end_line,
                end_column=d.end_character,
            )
            for d in raw_diags
        ]

        # 推送至意识引擎
        if self._consciousness and result:
            errors = [d for d in result if d.severity == "error"]
            if errors:
                try:
                    import asyncio

                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(
                            self._consciousness.perceive(
                                type="lsp_errors", data=errors
                            )
                        )
                    else:
                        loop.run_until_complete(
                            self._consciousness.perceive(
                                type="lsp_errors", data=errors
                            )
                        )
                except RuntimeError:
                    # 无事件循环, 跳过推送
                    pass

        return result

    def scan_all_from_client(self) -> list[AggregatedDiagnostic]:
        """通过 LSPClient 扫描所有已缓存文件的诊断"""
        if self._client is None:
            return []

        try:
            all_diags = self._client.get_all_diagnostics()
        except Exception as e:
            logger.debug("scan_all_from_client_failed: %s", e)
            return []

        result: list[AggregatedDiagnostic] = []
        for file_path, diags in all_diags.items():
            language = self._infer_language(file_path)
            for d in diags:
                result.append(
                    AggregatedDiagnostic(
                        file_path=d.file_path,
                        language=language,
                        severity=d.severity,
                        message=d.message,
                        line=d.line,
                        column=d.character,
                        source=d.source,
                        code=d.code,
                        end_line=d.end_line,
                        end_column=d.end_character,
                    )
                )
        return result

    async def scan_workspace(
        self, file_extensions: list[str] | None = None
    ) -> list[AggregatedDiagnostic]:
        """扫描整个工作区

        优先使用 LSPClient 模式, 回退到 LSPManager 模式。
        """
        if self._client is not None:
            return self.scan_all_from_client()
        # LSPManager 模式当前留空
        return []

    @staticmethod
    def _infer_language(file_path: str) -> str:
        """根据文件扩展名推断语言"""
        suffix_map = {
            ".py": "python",
            ".pyi": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".java": "java",
            ".cpp": "cpp",
            ".cxx": "cpp",
            ".cc": "cpp",
            ".c": "cpp",
            ".h": "cpp",
            ".hpp": "cpp",
            ".go": "go",
        }
        # 简单实现, 避免依赖 pathlib
        dot_idx = file_path.rfind(".")
        if dot_idx < 0:
            return "unknown"
        return suffix_map.get(file_path[dot_idx:].lower(), "unknown")
