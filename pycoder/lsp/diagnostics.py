"""诊断聚合器 — 汇总所有 LSP 诊断并推送至意识引擎

收集各语言 LSP 诊断信息，按严重度/文件/语言过滤，标记错误时推送系统事件。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AggregatedDiagnostic:
    file_path: str
    language: str
    severity: str  # "error" | "warning" | "info"
    message: str
    line: int
    column: int
    source: str


class DiagnosticsAggregator:
    """诊断聚合器

    用法:
        agg = DiagnosticsAggregator(lsp_manager)
        diags = await agg.scan_file("src/main.py")
    """

    def __init__(self, lsp_manager, consciousness_engine=None):
        self._lsp = lsp_manager
        self._consciousness = consciousness_engine

    async def scan_file(self, file_path: str) -> list[AggregatedDiagnostic]:
        """扫描单个文件的所有语言诊断

        Args:
            file_path: 文件路径

        Returns:
            诊断信息列表
        """
        language = self._lsp.get_language_for_file(file_path)
        if not language:
            return []

        # 确保 LSP 服务器已启动
        status = self._lsp.get_status(language)
        if status.name not in ("RUNNING",):
            await self._lsp.start(language)

        # 当前阶段返回空列表（LSP 通信需要 pygls 协议实现）
        # 后续可扩展为完整的 LSP 客户端通信
        diagnostics: list[AggregatedDiagnostic] = []

        # 推送至意识引擎
        if self._consciousness and diagnostics:
            errors = [d for d in diagnostics if d.severity == "error"]
            if errors:
                await self._consciousness.perceive(
                    type="lsp_errors", data=errors
                )

        return diagnostics

    async def scan_workspace(self, file_extensions: list[str] | None = None) -> list[AggregatedDiagnostic]:
        """扫描整个工作区

        Returns:
            所有文件的诊断信息
        """
        # 当前阶段留空，后续实现
        return []