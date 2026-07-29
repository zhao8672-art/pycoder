"""LSP 上下文集成器 — 将 LSP 诊断注入 AI 提示词

职责:
    1. 收集指定文件的 LSP 诊断 (通过 LSPClient)
    2. 按严重度/相关性过滤
    3. 格式化为 AI 友好的提示词片段
    4. 提供 ContextOrchestrator 集成接口

设计原则:
    - 不直接依赖 ContextOrchestrator, 保持解耦
    - 优雅降级: LSP 未启动或无诊断时返回空字符串
    - 可控注入: 限制诊断数量避免上下文膨胀

用法 (与 ContextOrchestrator 集成):
    integrator = LSPContextIntegrator(lsp_client)
    orchestrator.set_lsp_integrator(integrator)
    # 之后 orchestrator.process_user_message() 会自动注入诊断

用法 (独立使用):
    integrator = LSPContextIntegrator(lsp_client)
    snippet = await integrator.build_diagnostics_context(["main.py", "utils.py"])
    if snippet:
        messages.insert(0, {"role": "system", "content": snippet})
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from pycoder.lsp.client import Diagnostic, LSPClient

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# 严重度优先级 (用于排序)
_SEVERITY_PRIORITY = {
    "error": 0,
    "warning": 1,
    "information": 2,
    "hint": 3,
}


class LSPContextIntegrator:
    """LSP 上下文集成器 — 诊断到 AI 提示词的桥梁

    将 LSP 实时诊断信息转化为 AI 提示词片段, 帮助 LLM 在代码生成时:
        1. 感知当前文件的错误与警告
        2. 避免生成与现有错误冲突的代码
        3. 提供修复建议的上下文锚点
    """

    def __init__(
        self,
        lsp_client: LSPClient | None = None,
        max_diagnostics_per_file: int = 5,
        max_total_diagnostics: int = 20,
        max_files: int = 8,
        severity_filter: Iterable[str] = ("error", "warning"),
    ) -> None:
        """初始化集成器

        Args:
            lsp_client: LSP 客户端实例 (None 表示禁用)
            max_diagnostics_per_file: 单文件最多注入的诊断数
            max_total_diagnostics: 全局最多注入的诊断数
            max_files: 最多扫描的文件数
            severity_filter: 仅包含这些严重度的诊断
        """
        self._client = lsp_client
        self._max_per_file = max_diagnostics_per_file
        self._max_total = max_total_diagnostics
        self._max_files = max_files
        self._severity_filter = set(severity_filter)
        # 缓存最近一次的诊断快照 (避免重复扫描)
        self._last_snapshot: dict[str, list[Diagnostic]] = {}
        self._enabled: bool = lsp_client is not None

    @property
    def enabled(self) -> bool:
        """是否启用 LSP 集成"""
        return self._enabled and self._client is not None

    def enable(self, lsp_client: LSPClient) -> None:
        """启用 LSP 集成"""
        self._client = lsp_client
        self._enabled = True

    def disable(self) -> None:
        """禁用 LSP 集成"""
        self._enabled = False

    # ══════════════════════════════════════════════════════
    # 诊断收集
    # ══════════════════════════════════════════════════════

    def collect_diagnostics(
        self, file_paths: list[str]
    ) -> dict[str, list[Diagnostic]]:
        """收集指定文件的诊断 (同步, 从 LSPClient 缓存读取)

        Args:
            file_paths: 待扫描的文件路径列表

        Returns:
            {file_path: [Diagnostic, ...]} 已过滤、限量的诊断映射
        """
        if not self.enabled or not file_paths:
            return {}

        result: dict[str, list[Diagnostic]] = {}
        total_count = 0

        # 限制文件数
        for file_path in file_paths[: self._max_files]:
            if total_count >= self._max_total:
                break
            try:
                all_diags = self._client.get_diagnostics(file_path)  # type: ignore[union-attr]
            except Exception as e:
                logger.debug("lsp_collect_failed: %s=%s", file_path, e)
                continue

            # 按严重度过滤
            filtered = [d for d in all_diags if d.severity in self._severity_filter]
            # 按严重度优先级排序
            filtered.sort(
                key=lambda d: (_SEVERITY_PRIORITY.get(d.severity, 99), d.line)
            )
            # 限量
            remaining = self._max_total - total_count
            take = min(self._max_per_file, remaining)
            if filtered:
                result[file_path] = filtered[:take]
                total_count += len(result[file_path])

        self._last_snapshot = dict(result)
        return result

    def collect_all_diagnostics(self) -> dict[str, list[Diagnostic]]:
        """收集所有已缓存文件的诊断"""
        if not self.enabled:
            return {}
        try:
            all_diags = self._client.get_all_diagnostics()  # type: ignore[union-attr]
        except Exception as e:
            logger.debug("lsp_collect_all_failed: %s", e)
            return {}

        result: dict[str, list[Diagnostic]] = {}
        total_count = 0
        for file_path, diags in all_diags.items():
            if total_count >= self._max_total:
                break
            filtered = [d for d in diags if d.severity in self._severity_filter]
            filtered.sort(
                key=lambda d: (_SEVERITY_PRIORITY.get(d.severity, 99), d.line)
            )
            remaining = self._max_total - total_count
            take = min(self._max_per_file, remaining)
            if filtered:
                result[file_path] = filtered[:take]
                total_count += len(result[file_path])

        self._last_snapshot = dict(result)
        return result

    # ══════════════════════════════════════════════════════
    # 提示词格式化
    # ══════════════════════════════════════════════════════

    def format_diagnostics_for_prompt(
        self,
        diagnostics: dict[str, list[Diagnostic]],
        include_suggestions: bool = True,
    ) -> str:
        """将诊断映射格式化为 AI 提示词片段

        Args:
            diagnostics: {file_path: [Diagnostic, ...]} 映射
            include_suggestions: 是否包含修复建议提示

        Returns:
            格式化的提示词文本 (空字符串表示无诊断)
        """
        if not diagnostics:
            return ""

        lines: list[str] = []
        # 错误统计
        total_errors = sum(
            1
            for diags in diagnostics.values()
            for d in diags
            if d.severity == "error"
        )
        total_warnings = sum(
            1
            for diags in diagnostics.values()
            for d in diags
            if d.severity == "warning"
        )

        header = "## LSP 实时诊断 (代码生成参考)"
        summary = (
            f"共 {total_errors} 个错误, {total_warnings} 个警告 "
            f"(来自 {len(diagnostics)} 个文件)"
        )
        lines.extend([header, summary, ""])

        for file_path, diags in diagnostics.items():
            # 显示相对路径 (若可计算)
            display_path = self._relative_path(file_path)
            lines.append(f"### {display_path}")
            for d in diags:
                # 行号从 0-based 转 1-based 以符合编辑器习惯
                line_num = d.line + 1
                col_num = d.character + 1
                severity_marker = self._severity_marker(d.severity)
                code_info = f" [{d.code}]" if d.code else ""
                source_info = f" ({d.source})" if d.source else ""
                lines.append(
                    f"- {severity_marker} L{line_num}:{col_num}{code_info}{source_info} "
                    f"{d.message}"
                )
            lines.append("")

        if include_suggestions and (total_errors > 0 or total_warnings > 0):
            lines.append("**生成建议**:")
            if total_errors > 0:
                lines.append(
                    "- 优先修复上述错误, 避免在错误位置上叠加新代码"
                )
            if total_warnings > 0:
                lines.append(
                    "- 关注警告, 生成新代码时遵循对应最佳实践"
                )
            lines.append("")

        return "\n".join(lines)

    def build_diagnostics_context(
        self,
        file_paths: list[str] | None = None,
        include_suggestions: bool = True,
    ) -> str:
        """构建完整的诊断上下文片段 (供 AI 提示词注入)

        Args:
            file_paths: 待扫描的文件列表 (None 表示扫描所有已缓存文件)
            include_suggestions: 是否包含生成建议

        Returns:
            AI 提示词片段 (空字符串表示无诊断或集成器未启用)
        """
        if not self.enabled:
            return ""

        if file_paths is None:
            diagnostics = self.collect_all_diagnostics()
        else:
            diagnostics = self.collect_diagnostics(file_paths)

        return self.format_diagnostics_for_prompt(
            diagnostics, include_suggestions=include_suggestions
        )

    # ══════════════════════════════════════════════════════
    # 与 ContextOrchestrator 集成的便捷方法
    # ══════════════════════════════════════════════════════

    def get_anchor_section(self, file_paths: list[str] | None = None) -> str:
        """获取锚点片段 (供 ContextOrchestrator 注入 anchor)

        与 build_diagnostics_context 类似, 但增加锚点标记,
        便于 ContextOrchestrator 识别和去重。

        Args:
            file_paths: 待扫描的文件列表

        Returns:
            带锚点标记的诊断片段 (空字符串表示无诊断)
        """
        snippet = self.build_diagnostics_context(file_paths)
        if not snippet:
            return ""
        return f"<!-- LSP_DIAGNOSTICS_ANCHOR_START -->\n{snippet}\n<!-- LSP_DIAGNOSTICS_ANCHOR_END -->"

    def get_stats(self) -> dict[str, int]:
        """获取最近一次诊断快照的统计信息"""
        total = sum(len(diags) for diags in self._last_snapshot.values())
        errors = sum(
            1
            for diags in self._last_snapshot.values()
            for d in diags
            if d.severity == "error"
        )
        warnings = sum(
            1
            for diags in self._last_snapshot.values()
            for d in diags
            if d.severity == "warning"
        )
        return {
            "total_diagnostics": total,
            "errors": errors,
            "warnings": warnings,
            "files_affected": len(self._last_snapshot),
        }

    # ══════════════════════════════════════════════════════
    # 工具方法
    # ══════════════════════════════════════════════════════

    @staticmethod
    def _severity_marker(severity: str) -> str:
        """严重度标记"""
        return {
            "error": "[ERROR]",
            "warning": "[WARN]",
            "information": "[INFO]",
            "hint": "[HINT]",
        }.get(severity, "[?]")

    @staticmethod
    def _relative_path(file_path: str) -> str:
        """转换为相对路径 (若无法计算则返回原路径)"""
        try:
            p = Path(file_path)
            # 尝试取最后两级路径, 既保留语义又避免过长
            parts = p.parts
            if len(parts) >= 2:
                return str(Path(*parts[-2:]))
            return p.name
        except (ValueError, OSError):
            return file_path
