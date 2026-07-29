"""诊断自动修复循环 — Write → Diagnose → Fix 闭环

将 LSP 诊断集成到代码生成→修复循环中，实现:
  1. 代码生成后自动收集 LSP 诊断
  2. 诊断错误 → 构造修复 prompt → 重新生成 → 再次诊断（最多 3 轮）
  3. 修复成功率统计

与 AgentLoop 集成:
    agent_loop 写入文件后调用 collect_diagnostics_for_files()
    下一轮迭代时调用 inject_diagnostics_prompt() 将诊断注入 prompt

用法:
    from pycoder.ai.diagnostic_auto_fix import DiagnosticAutoFixer
    fixer = DiagnosticAutoFixer(orchestrator=ctx_orch)
    fixer.track_files(["main.py", "utils.py"])
    prompt = fixer.inject_diagnostics_prompt(base_prompt)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pycoder.lsp.context_integration import LSPContextIntegrator
    from pycoder.server.services.context_orchestrator import ContextOrchestrator

logger = logging.getLogger(__name__)

# 最大自动修复轮数
MAX_FIX_ROUNDS = 3


@dataclass
class FixRound:
    """单轮修复记录"""

    round_number: int
    file_path: str
    errors_before: int
    warnings_before: int
    errors_after: int = 0
    warnings_after: int = 0
    fix_applied: bool = False
    fix_content: str = ""
    duration_ms: float = 0


@dataclass
class DiagnosticFixReport:
    """诊断修复报告"""

    session_id: str = ""
    total_rounds: int = 0
    successful_fixes: int = 0
    failed_fixes: int = 0
    files_affected: int = 0
    initial_errors: int = 0
    final_errors: int = 0
    rounds: list[FixRound] = field(default_factory=list)
    total_duration_ms: float = 0

    @property
    def error_reduction_pct(self) -> float:
        """错误减少百分比"""
        if self.initial_errors == 0:
            return 0.0
        return (self.initial_errors - self.final_errors) / self.initial_errors * 100

    @property
    def fix_success_rate(self) -> float:
        """修复成功率"""
        if self.total_rounds == 0:
            return 0.0
        return self.successful_fixes / self.total_rounds * 100


class DiagnosticAutoFixer:
    """诊断自动修复器 — 代码生成→诊断→修复循环"""

    def __init__(
        self,
        orchestrator: ContextOrchestrator | None = None,
        max_rounds: int = MAX_FIX_ROUNDS,
        workspace: Path | None = None,
    ) -> None:
        """初始化诊断自动修复器

        Args:
            orchestrator: 上下文编排器 (用于获取 LSP 集成器)
            max_rounds: 最大修复轮数
            workspace: 工作区路径
        """
        self._orchestrator = orchestrator
        self._max_rounds = max_rounds
        self._workspace = workspace or Path.cwd()
        self._tracked_files: list[str] = []
        self._fix_history: list[FixRound] = []
        self._session_start: float = 0
        self._session_id: str = ""

    @property
    def _lsp_integrator(self) -> LSPContextIntegrator | None:
        """获取 LSP 集成器"""
        if self._orchestrator is None:
            return None
        return self._orchestrator._lsp_integrator

    def start_session(self, session_id: str = "") -> None:
        """开始新的修复会话"""
        self._session_id = session_id or f"fix_{int(time.time())}"
        self._session_start = time.monotonic()
        self._tracked_files = []
        self._fix_history = []

    def track_files(self, file_paths: list[str]) -> None:
        """追踪文件（代码生成后调用）"""
        for fp in file_paths:
            if fp not in self._tracked_files:
                self._tracked_files.append(fp)
        if self._orchestrator is not None:
            self._orchestrator.set_context_files(self._tracked_files)

    def untrack_file(self, file_path: str) -> None:
        """移除文件追踪"""
        if file_path in self._tracked_files:
            self._tracked_files.remove(file_path)

    def collect_diagnostics_for_files(
        self, file_paths: list[str] | None = None
    ) -> dict[str, list]:
        """收集指定文件的 LSP 诊断

        Args:
            file_paths: 文件列表 (None 则使用所有追踪文件)

        Returns:
            {file_path: [Diagnostic, ...]} 映射
        """
        integrator = self._lsp_integrator
        if integrator is None or not integrator.enabled:
            return {}

        targets = file_paths or self._tracked_files
        if not targets:
            return {}

        return integrator.collect_diagnostics(targets)

    def get_diagnostics_prompt(
        self, file_paths: list[str] | None = None
    ) -> str:
        """获取诊断提示词片段（用于注入 LLM prompt）

        Args:
            file_paths: 文件列表 (None 则使用所有追踪文件)

        Returns:
            AI 友好的诊断提示词
        """
        integrator = self._lsp_integrator
        if integrator is None or not integrator.enabled:
            return ""

        targets = file_paths or self._tracked_files
        if not targets:
            return ""

        return integrator.build_diagnostics_context(targets)

    def inject_diagnostics_prompt(self, base_prompt: str) -> str:
        """将 LSP 诊断注入到基础 prompt 中

        Args:
            base_prompt: 原始 prompt

        Returns:
            注入诊断后的 prompt
        """
        diagnostics = self.get_diagnostics_prompt()
        if not diagnostics:
            return base_prompt

        injected = (
            f"{base_prompt}\n\n"
            f"---\n"
            f"## 当前代码诊断 (请优先修复以下错误)\n\n"
            f"{diagnostics}\n\n"
            f"请在修复上述错误后，继续完成原始任务。"
        )
        return injected

    def get_diagnostics_summary(self) -> dict:
        """获取诊断摘要（供前端显示）

        Returns:
            {total_errors, total_warnings, files_affected, diagnostics}
        """
        diagnostics = self.collect_diagnostics_for_files()
        total_errors = 0
        total_warnings = 0
        file_list: list[dict] = []

        for file_path, diags in diagnostics.items():
            errs = [d for d in diags if getattr(d, "severity", "") == "error"]
            warns = [d for d in diags if getattr(d, "severity", "") == "warning"]
            total_errors += len(errs)
            total_warnings += len(warns)
            file_list.append({
                "file": file_path,
                "errors": len(errs),
                "warnings": len(warns),
                "diagnostics": [
                    {
                        "line": d.line + 1,
                        "message": d.message,
                        "severity": d.severity,
                    }
                    for d in diags
                ],
            })

        return {
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "files_affected": len(file_list),
            "files": file_list,
        }

    def record_fix_round(
        self,
        file_path: str,
        errors_before: int,
        warnings_before: int,
        errors_after: int = 0,
        warnings_after: int = 0,
        fix_applied: bool = False,
    ) -> FixRound:
        """记录一轮修复"""
        round_num = len(self._fix_history) + 1
        rnd = FixRound(
            round_number=round_num,
            file_path=file_path,
            errors_before=errors_before,
            warnings_before=warnings_before,
            errors_after=errors_after,
            warnings_after=warnings_after,
            fix_applied=fix_applied,
            duration_ms=(time.monotonic() - self._session_start) * 1000,
        )
        self._fix_history.append(rnd)
        return rnd

    def generate_report(self) -> DiagnosticFixReport:
        """生成修复报告"""
        report = DiagnosticFixReport(
            session_id=self._session_id,
            total_rounds=len(self._fix_history),
            rounds=list(self._fix_history),
            total_duration_ms=(time.monotonic() - self._session_start) * 1000,
        )

        # 统计
        successful = sum(1 for r in self._fix_history if r.fix_applied)
        failed = sum(1 for r in self._fix_history if not r.fix_applied)
        report.successful_fixes = successful
        report.failed_fixes = failed

        # 初始和最终错误数
        if self._fix_history:
            report.initial_errors = self._fix_history[0].errors_before
            report.final_errors = self._fix_history[-1].errors_after

        # 影响文件数
        affected = {r.file_path for r in self._fix_history}
        report.files_affected = len(affected)

        return report

    def get_fix_stats(self) -> dict:
        """获取修复统计（供前端显示）"""
        report = self.generate_report()
        return {
            "session_id": report.session_id,
            "total_rounds": report.total_rounds,
            "successful_fixes": report.successful_fixes,
            "failed_fixes": report.failed_fixes,
            "fix_success_rate": round(report.fix_success_rate, 1),
            "error_reduction_pct": round(report.error_reduction_pct, 1),
            "initial_errors": report.initial_errors,
            "final_errors": report.final_errors,
            "files_affected": report.files_affected,
            "total_duration_ms": report.total_duration_ms,
        }


# 全局单例
_instance: DiagnosticAutoFixer | None = None


def get_diagnostic_fixer(
    orchestrator: ContextOrchestrator | None = None,
) -> DiagnosticAutoFixer:
    """获取 DiagnosticAutoFixer 单例"""
    global _instance
    if _instance is None:
        _instance = DiagnosticAutoFixer(orchestrator=orchestrator)
    elif orchestrator is not None and _instance._orchestrator is None:
        _instance._orchestrator = orchestrator
    return _instance
