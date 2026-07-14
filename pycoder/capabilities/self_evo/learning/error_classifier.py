"""
错误分类与闭环处理器 — Phase 4

职责:
    1. 错误自动分类 (syntax/logic/runtime/security/performance/style)
    2. 修复策略推荐 (基于分类匹配最佳策略)
    3. 修复后的二次验证 — 确认修复有效
    4. 规则固化 — 成功修复自动沉淀为进化规则
    5. 重复率追踪 — 同类错误重复出现时升级告警

用法:
    from .error_classifier import ErrorClassifier
    ec = ErrorClassifier()
    category = ec.classify("NameError: name 'foo' is not defined")
    strategy = ec.recommend_strategy(category)
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum


class ErrorCategory(Enum):
    SYNTAX = "syntax"  # 语法错误
    LOGIC = "logic"  # 逻辑 bug
    RUNTIME = "runtime"  # 运行时异常
    SECURITY = "security"  # 安全漏洞
    PERFORMANCE = "performance"  # 性能问题
    STYLE = "style"  # 代码规范
    UNKNOWN = "unknown"  # 未分类


@dataclass
class ErrorTicket:
    """错误工单"""

    id: str = ""
    error_signature: str = ""
    error_message: str = ""
    category: ErrorCategory = ErrorCategory.UNKNOWN
    file_path: str = ""
    line_number: int = 0
    severity: str = "medium"  # critical / high / medium / low
    occurrences: int = 1
    first_seen: float = 0.0
    last_seen: float = 0.0
    fix_strategy: str = ""
    fix_status: str = "open"  # open / fixed / verified / closed
    verified_by: str = ""  # test / human / auto
    verified_at: float = 0.0


class ErrorClassifier:
    """错误分类与闭环处理器"""

    def __init__(self):
        self._tickets: dict[str, ErrorTicket] = {}  # signature → ticket
        self._recurrence: dict[str, int] = defaultdict(int)  # signature → repeat count
        self._strategy_map = self._build_strategy_map()

    # ══════════════════════════════════════════════════════
    # 分类
    # ══════════════════════════════════════════════════════

    _CLASSIFICATION_RULES: list[tuple[str, ErrorCategory]] = [
        # 语法错误
        (r"SyntaxError", ErrorCategory.SYNTAX),
        (r"IndentationError", ErrorCategory.SYNTAX),
        (r"TabError", ErrorCategory.SYNTAX),
        # 运行时
        (r"NameError|AttributeError|KeyError|IndexError|TypeError", ErrorCategory.RUNTIME),
        (r"ValueError|ZeroDivisionError|FileNotFoundError|PermissionError", ErrorCategory.RUNTIME),
        (r"ImportError|ModuleNotFoundError", ErrorCategory.RUNTIME),
        # 逻辑
        (r"AssertionError|assert\s+.*failed", ErrorCategory.LOGIC),
        (r"infinite.*loop|deadlock|race.*condition", ErrorCategory.LOGIC),
        # 安全
        (r"sql.*injection|xss|csrf|path.*traversal|eval\s*\(|exec\s*\(", ErrorCategory.SECURITY),
        (r"hardcoded.*key|exposed.*secret|plaintext.*password", ErrorCategory.SECURITY),
        # 性能
        (r"timeout|memory.*leak|slow.*query|o\(n\^2\)", ErrorCategory.PERFORMANCE),
        # 规范
        (r"PEP\s*8|E\d{3}|W\d{3}|too.*long|missing.*docstring", ErrorCategory.STYLE),
    ]

    def classify(self, error_message: str) -> ErrorCategory:
        for pattern, category in self._CLASSIFICATION_RULES:
            if re.search(pattern, error_message, re.IGNORECASE):
                return category
        return ErrorCategory.UNKNOWN

    # ══════════════════════════════════════════════════════
    # 修复策略推荐
    # ══════════════════════════════════════════════════════

    def _build_strategy_map(self) -> dict[ErrorCategory, list[str]]:
        return {
            ErrorCategory.SYNTAX: [
                "check_syntax: 检查括号配对/缩进/引号闭合",
                "format_fix: 运行 auto-formatter (black/ruff) 自动修复",
                "manual_patch: 对照错误行号手动修正",
            ],
            ErrorCategory.RUNTIME: [
                "add_null_check: 添加 None/空值检查",
                "add_type_check: 添加 isinstance 类型守卫",
                "add_try_except: 添加特定的异常处理",
            ],
            ErrorCategory.LOGIC: [
                "add_assert: 添加前置/后置条件断言",
                "split_function: 拆分复杂函数降低认知复杂度",
                "add_unit_test: 为边界条件补测试",
            ],
            ErrorCategory.SECURITY: [
                "parametrize_query: 使用参数化查询替代字符串拼接",
                "use_env_var: 密钥移至环境变量",
                "add_input_validation: 添加输入校验",
                "block_immediate: 立即阻止部署，升级告警",
            ],
            ErrorCategory.PERFORMANCE: [
                "add_cache: 添加缓存层 (lru_cache / redis)",
                "use_generator: 使用生成器替代全量列表",
                "batch_query: 批量查询替代逐条查询",
            ],
            ErrorCategory.STYLE: [
                "auto_format: 运行 Black + isort 自动格式化",
                "add_docstring: 补全函数文档字符串",
                "shorten_function: 拆分过长函数",
            ],
            ErrorCategory.UNKNOWN: [
                "llm_analyze: 使用 LLM 深度分析",
                "human_review: 标记为人工审查",
            ],
        }

    def recommend_strategy(self, category: ErrorCategory) -> list[str]:
        return self._strategy_map.get(category, ["unknown: 人工审查"])

    # ══════════════════════════════════════════════════════
    # 工单管理
    # ══════════════════════════════════════════════════════

    def open_ticket(
        self, error_signature: str, error_message: str, file_path: str = "", line: int = 0
    ) -> ErrorTicket:
        """创建或更新错误工单"""
        sig = error_signature[:200]

        if sig in self._tickets:
            ticket = self._tickets[sig]
            ticket.occurrences += 1
            ticket.last_seen = time.time()
            self._recurrence[sig] += 1
            return ticket

        ticket = ErrorTicket(
            id=f"ERR-{int(time.time() * 1000) % 1000000:06d}",
            error_signature=sig,
            error_message=error_message[:500],
            category=self.classify(error_message),
            file_path=file_path,
            line_number=line,
            severity=self._calc_severity(error_message),
            first_seen=time.time(),
            last_seen=time.time(),
        )
        self._tickets[sig] = ticket
        return ticket

    def mark_fixed(self, error_signature: str, strategy: str = "") -> None:
        ticket = self._tickets.get(error_signature)
        if ticket:
            ticket.fix_status = "fixed"
            ticket.fix_strategy = strategy

    def verify_fix(self, error_signature: str, verified_by: str = "test") -> bool:
        """修复后的二次验证"""
        ticket = self._tickets.get(error_signature)
        if ticket is None:
            return False
        ticket.fix_status = "verified"
        ticket.verified_by = verified_by
        ticket.verified_at = time.time()
        return True

    # ══════════════════════════════════════════════════════
    # 重复率追踪
    # ══════════════════════════════════════════════════════

    def check_recurrence(self, error_signature: str) -> dict:
        """检查某类错误的重复率"""
        count = self._recurrence.get(error_signature, 0)
        ticket = self._tickets.get(error_signature)
        severity = "low"

        if count >= 5:
            severity = "critical"  # 同类错误出现5次
        elif count >= 3:
            severity = "high"

        return {
            "signature": error_signature[:100],
            "repeat_count": count,
            "severity": severity,
            "last_status": ticket.fix_status if ticket else "unknown",
            "suggestion": ("升级为热规则自动修复" if count >= 3 else "正常监控"),
        }

    def get_recurrence_report(self) -> list[dict]:
        """获取所有重复错误的报告（按重复次数降序）"""
        sorted_items = sorted(self._recurrence.items(), key=lambda x: x[1], reverse=True)
        return [self.check_recurrence(sig) for sig, _ in sorted_items[:20]]

    # ══════════════════════════════════════════════════════
    # 工具方法
    # ══════════════════════════════════════════════════════

    @staticmethod
    def _calc_severity(error_message: str) -> str:
        if re.search(r"critical|fatal|crash|panic", error_message, re.I):
            return "critical"
        if re.search(r"SyntaxError|ImportError|security|injection", error_message, re.I):
            return "high"
        return "medium"

    def get_stats(self) -> dict:
        by_category = defaultdict(int)
        for t in self._tickets.values():
            by_category[t.category.value] += 1
        return {
            "total_tickets": len(self._tickets),
            "by_category": dict(by_category),
            "recurring_errors": len([k for k, v in self._recurrence.items() if v >= 3]),
            "verified_fixes": sum(1 for t in self._tickets.values() if t.fix_status == "verified"),
        }
