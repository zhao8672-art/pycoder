"""LSP 反馈采集器 — 将 LSP 诊断接入自进化反馈闭环

职责:
    1. 监听 LSPClient 的诊断回调 (register_diagnostics_handler)
    2. 按文件/任务聚合诊断
    3. 周期性将聚合诊断推送到 FeedbackLoop
    4. 学习高频错误模式 (基于 LSP code/source 聚合)
    5. 生成错误模式学习报告 (供 AI 提示词注入)

设计原则:
    - 解耦: 不直接依赖 LSPClient 或 FeedbackLoop 的具体实现
    - 周期聚合: 避免每个诊断都触发反馈 (减少噪音)
    - 优雅降级: FeedbackLoop 异常不影响 LSP 主流程
    - 可观测: 提供统计接口供外部监控

用法:
    collector = LSPFeedbackCollector(lsp_client=client)
    collector.start(task_id="T-001")
    # ... LSP 推送诊断 ...
    collector.flush()  # 主动推送聚合结果到 FeedbackLoop
    report = collector.get_learning_report()  # 获取学习报告
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from typing import Any, TYPE_CHECKING

from pycoder.lsp.client import Diagnostic

if TYPE_CHECKING:
    from pycoder.capabilities.self_evo.learning.feedback_loop import FeedbackLoop
    from pycoder.lsp.client import LSPClient

logger = logging.getLogger(__name__)


# 默认聚合周期 (秒): 累积诊断超过此周期后自动 flush
DEFAULT_FLUSH_INTERVAL = 30.0
# 默认聚合阈值 (诊断数): 累积超过此数后自动 flush
DEFAULT_FLUSH_THRESHOLD = 20
# 学习报告 top N 错误码
DEFAULT_TOP_N = 10


class LSPFeedbackCollector:
    """LSP 反馈采集器 — 诊断到反馈闭环的桥梁

    工作流程:
        1. start(task_id): 开启新任务的诊断聚合窗口
        2. LSPClient 推送诊断 → on_diagnostics_pushed 回调累积
        3. flush() 或自动触发 → 推送 FeedbackSignal 到 FeedbackLoop
        4. get_learning_report() → 输出错误模式学习报告
    """

    def __init__(
        self,
        lsp_client: LSPClient | None = None,
        feedback_loop: FeedbackLoop | None = None,
        lsp_source: str = "pyright",
        flush_interval: float = DEFAULT_FLUSH_INTERVAL,
        flush_threshold: int = DEFAULT_FLUSH_THRESHOLD,
        auto_flush: bool = True,
    ) -> None:
        """初始化采集器

        Args:
            lsp_client: LSP 客户端实例 (None 表示仅手动模式)
            feedback_loop: 反馈闭环实例 (None 表示禁用推送)
            lsp_source: LSP 来源标识
            flush_interval: 自动 flush 周期 (秒)
            flush_threshold: 自动 flush 阈值 (诊断数)
            auto_flush: 是否启用自动 flush
        """
        self._client = lsp_client
        self._loop = feedback_loop
        self._lsp_source = lsp_source
        self._flush_interval = flush_interval
        self._flush_threshold = flush_threshold
        self._auto_flush = auto_flush

        # 当前任务上下文
        self._current_task_id: str = ""
        self._task_started_at: float = 0.0

        # 诊断累积缓冲 (file_path → Diagnostic 列表)
        self._buffer: dict[str, list[Diagnostic]] = {}
        # 已 flush 的历史统计 (用于学习报告)
        self._history: list[dict[str, Any]] = []
        # 最近一次 flush 时间
        self._last_flush_at: float = time.time()

        # 注册到 LSPClient
        if self._client is not None:
            try:
                self._client.register_diagnostics_handler(self._on_diagnostics_pushed)
            except Exception as e:
                logger.warning("lsp_register_handler_failed: %s", e)

    @property
    def enabled(self) -> bool:
        """是否启用 (LSPClient 与 FeedbackLoop 均可用)"""
        return self._client is not None and self._loop is not None

    # ══════════════════════════════════════════════════════
    # 任务生命周期
    # ══════════════════════════════════════════════════════

    def start(self, task_id: str) -> None:
        """开始新任务的诊断聚合窗口

        Args:
            task_id: 任务 ID
        """
        # 若有未 flush 的诊断, 先 flush
        if self._buffer:
            self.flush()
        self._current_task_id = task_id
        self._task_started_at = time.time()
        self._last_flush_at = time.time()
        logger.debug("lsp_collector_start: task=%s", task_id)

    def stop(self) -> None:
        """停止当前任务并 flush 剩余诊断"""
        if self._buffer:
            self.flush()
        self._current_task_id = ""
        self._task_started_at = 0.0

    # ══════════════════════════════════════════════════════
    # 诊断回调与聚合
    # ══════════════════════════════════════════════════════

    def _on_diagnostics_pushed(
        self, file_path: str, diagnostics: list[Diagnostic]
    ) -> None:
        """LSPClient 诊断回调 (注册到 register_diagnostics_handler)

        累积诊断到缓冲区, 满足条件时自动 flush。
        """
        # 更新缓冲: 用最新诊断覆盖 (LSP 推送空列表表示文件已无错误)
        if diagnostics:
            self._buffer[file_path] = list(diagnostics)
        else:
            self._buffer.pop(file_path, None)

        # 自动 flush 检查
        if self._auto_flush and self._should_auto_flush():
            self.flush()

    def _should_auto_flush(self) -> bool:
        """判断是否应自动 flush"""
        # 时间触发
        if time.time() - self._last_flush_at >= self._flush_interval:
            return True
        # 数量触发
        total = sum(len(diags) for diags in self._buffer.values())
        if total >= self._flush_threshold:
            return True
        return False

    def add_diagnostics(
        self, file_path: str, diagnostics: list[Diagnostic]
    ) -> None:
        """手动添加诊断 (不依赖 LSPClient 回调)

        Args:
            file_path: 文件路径
            diagnostics: 诊断列表
        """
        self._on_diagnostics_pushed(file_path, diagnostics)

    # ══════════════════════════════════════════════════════
    # Flush 到 FeedbackLoop
    # ══════════════════════════════════════════════════════

    def flush(self) -> dict[str, Any] | None:
        """将缓冲区诊断聚合后推送到 FeedbackLoop

        Returns:
            推送的统计信息 (无诊断或未启用时返回 None)
        """
        if not self._buffer:
            self._last_flush_at = time.time()
            return None

        # 收集所有诊断
        all_diags: list[Diagnostic] = []
        for diags in self._buffer.values():
            all_diags.extend(diags)

        if not all_diags:
            self._last_flush_at = time.time()
            return None

        # 推送到 FeedbackLoop
        stats = self._compute_stats(all_diags)
        if self._loop is not None:
            try:
                self._loop.collect_from_lsp_diagnostics(
                    task_id=self._current_task_id or "lsp_auto",
                    diagnostics=all_diags,
                    lsp_source=self._lsp_source,
                )
            except Exception as e:
                logger.warning("lsp_feedback_push_failed: %s", e)

        # 记录历史
        stats["task_id"] = self._current_task_id
        stats["timestamp"] = time.time()
        self._history.append(stats)
        # 保留最近 100 条历史
        if len(self._history) > 100:
            self._history = self._history[-100:]

        # 清空缓冲
        self._buffer.clear()
        self._last_flush_at = time.time()

        logger.debug(
            "lsp_collector_flush: errors=%s warnings=%s files=%s",
            stats["error_count"],
            stats["warning_count"],
            stats["files_affected"],
        )
        return stats

    @staticmethod
    def _compute_stats(diagnostics: list[Diagnostic]) -> dict[str, Any]:
        """计算诊断统计"""
        error_count = sum(1 for d in diagnostics if d.severity == "error")
        warning_count = sum(1 for d in diagnostics if d.severity == "warning")
        info_count = sum(1 for d in diagnostics if d.severity == "information")
        hint_count = sum(1 for d in diagnostics if d.severity == "hint")
        files = {d.file_path for d in diagnostics if d.file_path}
        codes = [d.code for d in diagnostics if d.code]
        sources = {d.source for d in diagnostics if d.source}

        return {
            "total": len(diagnostics),
            "error_count": error_count,
            "warning_count": warning_count,
            "info_count": info_count,
            "hint_count": hint_count,
            "files_affected": len(files),
            "error_codes": Counter(codes).most_common(DEFAULT_TOP_N),
            "sources": list(sources),
        }

    # ══════════════════════════════════════════════════════
    # 错误模式学习
    # ══════════════════════════════════════════════════════

    def get_learning_report(self) -> str:
        """生成错误模式学习报告 (供 AI 提示词注入)

        报告内容:
            - 累计 LSP 反馈信号数
            - Top N 高频错误码 (基于历史聚合)
            - 受影响文件数 / 平均错误数
            - 错误码 → 推荐修复建议 (若错误码在 ERROR_PATTERN_DB 中)

        Returns:
            格式化的学习报告文本 (空字符串表示无历史)
        """
        if not self._history:
            return ""

        # 聚合所有历史的错误码
        all_codes: list[str] = []
        total_errors = 0
        total_warnings = 0
        total_files = 0
        for h in self._history:
            for code, count in h.get("error_codes", []):
                all_codes.extend([code] * count)
            total_errors += h.get("error_count", 0)
            total_warnings += h.get("warning_count", 0)
            total_files += h.get("files_affected", 0)

        if not all_codes and total_errors == 0 and total_warnings == 0:
            return ""

        code_counter = Counter(all_codes)
        top_codes = code_counter.most_common(DEFAULT_TOP_N)

        lines: list[str] = ["## LSP 错误模式学习报告 (自进化反馈)"]
        lines.append(
            f"累计 {len(self._history)} 次诊断聚合, "
            f"共 {total_errors} 个错误, {total_warnings} 个警告, "
            f"影响 {total_files} 个文件"
        )
        lines.append("")

        if top_codes:
            lines.append("### 高频错误码 Top 10")
            for code, count in top_codes:
                suggestion = self._lookup_fix_suggestion(code)
                if suggestion:
                    lines.append(f"- `{code}` (×{count}): {suggestion}")
                else:
                    lines.append(f"- `{code}` (×{count})")
            lines.append("")

        # 生成建议
        lines.append("**自进化建议**:")
        if top_codes:
            top_code = top_codes[0][0]
            lines.append(
                f"- 最高频错误码 `{top_code}` 应在生成代码时主动避免"
            )
        if total_errors > total_warnings and total_errors > 10:
            lines.append(
                "- 错误数远超警告数, 建议加强类型注解与导入检查"
            )
        lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _lookup_fix_suggestion(code: str) -> str:
        """查询错误码对应的修复建议

        优先从 ERROR_PATTERN_DB 查询, 其次从内置 LSP 错误码建议表查询。
        """
        # 内置 LSP 错误码建议表 (pyright/通用 LSP)
        LSP_CODE_SUGGESTIONS = {
            "reportMissingImports": "缺少导入 — 检查包是否已安装或路径是否正确",
            "reportMissingModuleSource": "模块源码缺失 — 检查 stub 文件或安装类型提示包",
            "reportUndefinedVariable": "未定义变量 — 检查拼写或导入",
            "reportGeneralTypeIssues": "类型不匹配 — 检查函数签名与调用参数",
            "reportArgumentMissing": "参数缺失 — 检查函数调用参数数量",
            "reportOptionalMemberAccess": "可选类型成员访问 — 添加 None 检查",
            "reportOptionalSubscript": "可选类型下标访问 — 添加 None 检查",
            "reportCallIssue": "函数调用问题 — 检查参数类型与数量",
            "reportAttributeAccessIssue": "属性访问问题 — 检查对象类型是否有该属性",
            "reportIndexIssue": "索引问题 — 检查索引类型与范围",
            "reportReturnType": "返回类型不匹配 — 检查函数返回值类型",
            "reportUnusedImport": "未使用的导入 — 删除或使用它",
            "reportUnusedVariable": "未使用的变量 — 删除或使用它",
            "reportUnusedFunction": "未使用的函数 — 删除或导出",
            "reportDuplicateDeclaration": "重复声明 — 重命名以避免冲突",
            "reportInvalidStringEscape": "无效字符串转义 — 使用原始字符串或修正转义",
            "reportUnnecessaryTypeIgnoreComment": "不必要的 type:ignore — 删除该注释",
        }
        suggestion = LSP_CODE_SUGGESTIONS.get(code, "")
        if suggestion:
            return suggestion

        # 尝试从 ERROR_PATTERN_DB 查询
        try:
            from pycoder.capabilities.self_evo.learning.error_patterns import (
                ERROR_PATTERN_DB,
            )

            pattern = ERROR_PATTERN_DB.get(code)
            if pattern and pattern.fix_templates:
                return pattern.fix_templates[0]
        except (ImportError, KeyError):
            pass

        return ""

    def get_stats(self) -> dict[str, Any]:
        """获取采集器统计信息"""
        buffered = sum(len(diags) for diags in self._buffer.values())
        return {
            "current_task_id": self._current_task_id,
            "buffered_files": len(self._buffer),
            "buffered_diagnostics": buffered,
            "history_count": len(self._history),
            "enabled": self.enabled,
            "lsp_source": self._lsp_source,
        }

    def get_history(self) -> list[dict[str, Any]]:
        """获取历史 flush 记录"""
        return list(self._history)

    def reset(self) -> None:
        """重置采集器 (清空缓冲与历史)"""
        self._buffer.clear()
        self._history.clear()
        self._last_flush_at = time.time()


__all__ = [
    "LSPFeedbackCollector",
    "DEFAULT_FLUSH_INTERVAL",
    "DEFAULT_FLUSH_THRESHOLD",
]
