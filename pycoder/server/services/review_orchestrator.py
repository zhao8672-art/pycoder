"""F5 代码审查编排器 — diff → 静态扫描 + AI 分析 → 结构化审查意见 → 一键修复

流程:
    diff 文本 / 文件列表
        → 按文件切分（熔断：最多 N 文件、单文件/总长度截断）
        → 每个文件：静态扫描（依赖 CVE + 启发式危险模式）
                  + ChatBridge 调用 LLM 产出严格 JSON 结构化意见
        → 汇总 ReviewResult（overall_score / summary / issues / stats）

容错设计:
    - LLM 输出非 JSON 时尝试 ```json 代码块 / 最外层花括号提取
    - 解析失败降级为一条 info 级 issue，不中断整体审查
    - 单次最多审查 MAX_REVIEW_FILES 个文件，超出部分截断并在 summary 标注
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

# ── 熔断常量 ──────────────────────────────────────────────
MAX_REVIEW_FILES: int = 10  # 单次最多审查的文件数
MAX_FILE_CHARS: int = 20_000  # 单文件送入 LLM 的最大字符数（超出截断）
MAX_TOTAL_CHARS: int = 120_000  # 本次审查总字符预算
LLM_MAX_TOKENS: int = 2048  # 单次 LLM 调用的 max_tokens

# ── 类型定义 ──────────────────────────────────────────────

Severity = Literal["info", "warning", "error", "critical"]
Category = Literal["security", "perf", "style", "bug", "best-practice"]

_VALID_SEVERITIES: tuple[str, ...] = ("info", "warning", "error", "critical")
_VALID_CATEGORIES: tuple[str, ...] = ("security", "perf", "style", "bug", "best-practice")

# 严重级权重（用于 overall_score 扣分）
_SEVERITY_PENALTY: dict[str, float] = {
    "critical": 25.0,
    "error": 12.0,
    "warning": 5.0,
    "info": 1.0,
}


@dataclass
class ReviewIssue:
    """单条结构化审查意见"""

    file_path: str
    line_start: int
    line_end: int
    severity: Severity
    category: Category
    message: str
    suggestion: str = ""
    fix_patch: str = ""  # 可选 unified diff 修复补丁


@dataclass
class ReviewResult:
    """审查汇总结果"""

    overall_score: float  # 0-100
    summary: str
    issues: list[ReviewIssue] = field(default_factory=list)
    stats: dict[str, dict[str, int]] = field(default_factory=dict)
    truncated: bool = False  # 是否因熔断被截断

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化字典"""
        return asdict(self)


# ── 静态扫描（启发式危险模式） ─────────────────────────────

# (正则, 严重级, 分类, 说明, 建议)
_HEURISTIC_RULES: list[tuple[re.Pattern[str], Severity, Category, str, str]] = [
    (
        re.compile(r"\beval\s*\("),
        "critical",
        "security",
        "使用 eval() 执行动态代码，存在任意代码执行风险",
        "改用 ast.literal_eval() 或显式解析逻辑",
    ),
    (
        re.compile(r"\bexec\s*\("),
        "critical",
        "security",
        "使用 exec() 执行动态代码，存在任意代码执行风险",
        "避免 exec，改为显式函数调用或安全沙箱",
    ),
    (
        re.compile(r"subprocess\.[^(]+\([^)]*shell\s*=\s*True"),
        "error",
        "security",
        "subprocess 使用 shell=True，存在命令注入风险",
        "使用参数列表形式并避免 shell=True",
    ),
    (
        re.compile(
            r"(?i)(api_key|secret|password|token)\s*=\s*['\"][A-Za-z0-9_\-]{8,}['\"]"
        ),
        "error",
        "security",
        "疑似硬编码敏感信息（密钥/密码/Token）",
        "改为从环境变量或 .env 文件读取",
    ),
    (
        re.compile(r"except\s*:"),
        "warning",
        "bug",
        "裸 except: 会吞掉所有异常（含 KeyboardInterrupt）",
        "捕获具体异常类型，如 except ValueError:",
    ),
    (
        re.compile(r"\bprint\s*\("),
        "info",
        "style",
        "生产代码中使用 print()，建议使用 logging",
        "替换为 logging.getLogger(__name__) 输出",
    ),
]


def _static_scan_file(file_path: str, content: str) -> list[ReviewIssue]:
    """对单个文件内容做启发式静态扫描.

    Args:
        file_path: 文件路径（用于 issue 归属）
        content: 文件内容

    Returns:
        静态扫描发现的 ReviewIssue 列表
    """
    issues: list[ReviewIssue] = []
    lines = content.splitlines()
    for lineno, line in enumerate(lines, start=1):
        for pattern, severity, category, message, suggestion in _HEURISTIC_RULES:
            if pattern.search(line):
                issues.append(
                    ReviewIssue(
                        file_path=file_path,
                        line_start=lineno,
                        line_end=lineno,
                        severity=severity,
                        category=category,
                        message=message,
                        suggestion=suggestion,
                    )
                )
    return issues


def _scan_dependencies(project_root: Any) -> list[ReviewIssue]:
    """调用 DependencySecurityScanner 做依赖 CVE 扫描（容错）.

    Args:
        project_root: 项目根路径

    Returns:
        依赖漏洞对应的 ReviewIssue 列表
    """
    issues: list[ReviewIssue] = []
    try:
        from pycoder.python.security_scanner import DependencySecurityScanner

        scanner = DependencySecurityScanner(project_root=project_root)
        result = scanner.scan()
        sev_map: dict[str, Severity] = {
            "CRITICAL": "critical",
            "HIGH": "error",
            "MEDIUM": "warning",
            "LOW": "info",
        }
        for vuln in result.vulnerabilities:
            issues.append(
                ReviewIssue(
                    file_path="requirements.txt",
                    line_start=1,
                    line_end=1,
                    severity=sev_map.get(vuln.get("severity", ""), "warning"),
                    category="security",
                    message=(
                        f"依赖漏洞 {vuln.get('cve_id', '')}: "
                        f"{vuln.get('package', '')} {vuln.get('title', '')}"
                    ),
                    suggestion=f"升级到 {vuln.get('fixed_version', '')} 或更高版本",
                )
            )
    except (ImportError, OSError, RuntimeError, ValueError) as e:
        logger.debug("dep_scan_skipped error=%s", e)
    return issues


# ── diff 解析 ──────────────────────────────────────────────


def parse_diff_files(diff_text: str) -> dict[str, str]:
    """将 unified diff 按文件切分.

    Args:
        diff_text: 完整 unified diff 文本

    Returns:
        {文件路径: 该文件的 diff 片段}
    """
    files: dict[str, list[str]] = {}
    current_file = ""
    for line in diff_text.splitlines(keepends=True):
        if line.startswith("+++ "):
            path = line[4:].strip()
            # 去掉 b/ 前缀（git diff 风格）
            if path.startswith("b/"):
                path = path[2:]
            current_file = path
            files.setdefault(current_file, [])
        elif line.startswith("diff --git"):
            # 新文件块开始，重置 current_file 等待 +++ 行
            current_file = ""
        elif current_file:
            files[current_file].append(line)
    return {path: "".join(lines) for path, lines in files.items() if path}


# ── LLM 输出 JSON 容错解析 ─────────────────────────────────


def extract_json_payload(text: str) -> dict[str, Any] | None:
    """从 LLM 输出中容错提取 JSON 对象.

    依次尝试: 直接解析 → ```json 代码块 → 最外层花括号切片。

    Args:
        text: LLM 原始输出文本

    Returns:
        解析出的 dict，失败返回 None
    """
    text = text.strip()
    if not text:
        return None
    # 1. 直接解析
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {"issues": data}
    except json.JSONDecodeError:
        pass
    # 2. ```json ... ``` 代码块
    match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            return data if isinstance(data, dict) else {"issues": data}
        except json.JSONDecodeError:
            pass
    # 3. 最外层花括号 / 方括号切片
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                return data if isinstance(data, dict) else {"issues": data}
            except json.JSONDecodeError:
                continue
    return None


def parse_llm_issues(payload: dict[str, Any], default_file: str) -> list[ReviewIssue]:
    """将 LLM JSON 负载解析为 ReviewIssue 列表（字段容错）.

    Args:
        payload: extract_json_payload 解析出的字典
        default_file: issue 缺省文件归属

    Returns:
        规范化后的 ReviewIssue 列表（非法条目跳过）
    """
    raw_issues = payload.get("issues", [])
    if not isinstance(raw_issues, list):
        return []
    issues: list[ReviewIssue] = []
    for raw in raw_issues:
        if not isinstance(raw, dict):
            continue
        severity = str(raw.get("severity", "info")).lower()
        if severity not in _VALID_SEVERITIES:
            severity = "info"
        category = str(raw.get("category", "best-practice")).lower()
        if category not in _VALID_CATEGORIES:
            category = "best-practice"
        try:
            line_start = max(int(raw.get("line_start", 1)), 1)
        except (TypeError, ValueError):
            line_start = 1
        try:
            line_end = max(int(raw.get("line_end", line_start)), line_start)
        except (TypeError, ValueError):
            line_end = line_start
        issues.append(
            ReviewIssue(
                file_path=str(raw.get("file_path") or default_file),
                line_start=line_start,
                line_end=line_end,
                severity=severity,  # type: ignore[arg-type]
                category=category,  # type: ignore[arg-type]
                message=str(raw.get("message", "")).strip() or "（无描述）",
                suggestion=str(raw.get("suggestion", "")).strip(),
                fix_patch=str(raw.get("fix_patch", "") or ""),
            )
        )
    return issues


def compute_overall_score(issues: list[ReviewIssue]) -> float:
    """按严重级加权扣分计算总体评分.

    Args:
        issues: 全部审查意见

    Returns:
        0-100 的评分（扣分封顶 100，保留 1 位小数）
    """
    penalty = sum(_SEVERITY_PENALTY.get(i.severity, 0.0) for i in issues)
    return round(max(0.0, 100.0 - penalty), 1)


def compute_stats(issues: list[ReviewIssue]) -> dict[str, dict[str, int]]:
    """统计按严重级 / 分类的 issue 数量.

    Args:
        issues: 全部审查意见

    Returns:
        {"by_severity": {...}, "by_category": {...}}
    """
    by_severity = {s: 0 for s in _VALID_SEVERITIES}
    by_category = {c: 0 for c in _VALID_CATEGORIES}
    for issue in issues:
        by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1
        by_category[issue.category] = by_category.get(issue.category, 0) + 1
    return {"by_severity": by_severity, "by_category": by_category}


# ── 提示词 ────────────────────────────────────────────────

_REVIEW_PROMPT_TEMPLATE = """你是资深代码审查专家。请审查以下文件变更，输出严格 JSON（不要输出任何其他文字）。

输出格式:
{{
  "issues": [
    {{
      "file_path": "文件路径",
      "line_start": 起始行号,
      "line_end": 结束行号,
      "severity": "info|warning|error|critical",
      "category": "security|perf|style|bug|best-practice",
      "message": "问题描述（中文，简洁）",
      "suggestion": "修复建议（中文）"
    }}
  ]
}}

若无问题请输出 {{"issues": []}}。

文件: {file_path}
变更内容（unified diff 或源码）:
```
{content}
```"""

_FIX_PROMPT_TEMPLATE = """你是代码修复专家。针对以下代码问题，生成一个 unified diff 格式的修复补丁。

文件: {file_path}
问题: {message}
建议: {suggestion}
涉及行: {line_start}-{line_end}

要求:
- 仅输出 unified diff 补丁文本（以 --- 和 +++ 开头），不要输出任何解释。
- 若无法生成补丁，输出空文本。"""


# ── 编排器 ────────────────────────────────────────────────

# LLM 调用签名：输入 prompt 与 max_tokens，返回文本
LLMChatFn = Callable[[str, int], Awaitable[str]]


async def _default_llm_chat(prompt: str, max_tokens: int) -> str:
    """默认 LLM 调用：通过 ChatBridge 同步聊天接口."""
    from pycoder.server.chat_bridge import ChatBridge

    bridge = ChatBridge()
    bridge.config.max_tokens = max_tokens
    bridge.config.temperature = 0.2
    try:
        return await bridge.chat(prompt, max_tokens=max_tokens) or ""
    finally:
        await bridge.close()


class ReviewOrchestrator:
    """F5 代码审查编排器.

    用法:
        orch = ReviewOrchestrator()
        result = await orch.review_diff(diff_text)
        patch = await orch.generate_fix(result.issues[0])
    """

    def __init__(
        self,
        llm_chat: LLMChatFn | None = None,
        scan_dependencies: bool = False,
        project_root: Any | None = None,
    ) -> None:
        """初始化编排器.

        Args:
            llm_chat: 可注入的 LLM 调用函数（测试时 mock）；None 使用 ChatBridge
            scan_dependencies: 是否附带依赖 CVE 扫描（默认关闭，避免拖慢）
            project_root: 依赖扫描的项目根路径
        """
        self._llm_chat = llm_chat or _default_llm_chat
        self._scan_deps = scan_dependencies
        self._project_root = project_root

    # ── 公共入口 ──────────────────────────────────────────

    async def review_diff(
        self,
        diff_text: str,
        *,
        max_files: int = MAX_REVIEW_FILES,
        include_static: bool = True,
        include_llm: bool = True,
    ) -> ReviewResult:
        """审查 unified diff.

        Args:
            diff_text: unified diff 文本
            max_files: 单次最多审查文件数（熔断）
            include_static: 是否运行静态扫描
            include_llm: 是否调用 LLM 分析

        Returns:
            ReviewResult 汇总结果
        """
        file_chunks = parse_diff_files(diff_text)
        if not file_chunks:
            return ReviewResult(
                overall_score=100.0,
                summary="未解析到有效的 diff 文件变更",
                stats=compute_stats([]),
            )
        return await self._review_chunks(
            file_chunks,
            max_files=max_files,
            include_static=include_static,
            include_llm=include_llm,
        )

    async def review_files(
        self,
        files: list[dict[str, str]],
        *,
        max_files: int = MAX_REVIEW_FILES,
        include_static: bool = True,
        include_llm: bool = True,
    ) -> ReviewResult:
        """审查文件列表.

        Args:
            files: [{"path": ..., "content": ...}, ...]
            max_files: 单次最多审查文件数（熔断）
            include_static: 是否运行静态扫描
            include_llm: 是否调用 LLM 分析

        Returns:
            ReviewResult 汇总结果
        """
        file_chunks = {str(f.get("path", "")): str(f.get("content", "")) for f in files}
        file_chunks = {p: c for p, c in file_chunks.items() if p}
        if not file_chunks:
            return ReviewResult(
                overall_score=100.0,
                summary="无待审查文件",
                stats=compute_stats([]),
            )
        return await self._review_chunks(
            file_chunks,
            max_files=max_files,
            include_static=include_static,
            include_llm=include_llm,
        )

    async def generate_fix(self, issue: ReviewIssue) -> str:
        """用 LLM 为单条 issue 生成修复补丁.

        Args:
            issue: 待修复的审查意见

        Returns:
            unified diff 补丁文本；生成失败返回空字符串
        """
        prompt = _FIX_PROMPT_TEMPLATE.format(
            file_path=issue.file_path,
            message=issue.message,
            suggestion=issue.suggestion,
            line_start=issue.line_start,
            line_end=issue.line_end,
        )
        try:
            raw = await self._llm_chat(prompt, LLM_MAX_TOKENS)
        except Exception as e:  # noqa: BLE001 — LLM 调用失败不应中断流程
            logger.warning("generate_fix_llm_failed error=%s", e)
            return ""
        return _extract_patch_text(raw)

    # ── 内部实现 ──────────────────────────────────────────

    async def _review_chunks(
        self,
        file_chunks: dict[str, str],
        *,
        max_files: int,
        include_static: bool,
        include_llm: bool,
    ) -> ReviewResult:
        """核心编排：逐文件静态扫描 + LLM 分析，汇总结果."""
        issues: list[ReviewIssue] = []
        truncated = False
        total_chars = 0

        paths = list(file_chunks.keys())
        if len(paths) > max_files:
            truncated = True
            paths = paths[:max_files]

        for path in paths:
            content = file_chunks[path]
            # 单文件长度截断
            if len(content) > MAX_FILE_CHARS:
                content = content[:MAX_FILE_CHARS]
                truncated = True
            # 总长度预算
            if total_chars + len(content) > MAX_TOTAL_CHARS:
                truncated = True
                break
            total_chars += len(content)

            # 1. 静态扫描（对 diff 取 + 行内容做扫描更精准；源码直接扫描）
            if include_static:
                scan_content = content
                if content.lstrip().startswith(("@@", "-", "+")):
                    scan_content = "\n".join(
                        ln[1:]
                        for ln in content.splitlines()
                        if ln.startswith("+") and not ln.startswith("+++")
                    )
                issues.extend(_static_scan_file(path, scan_content))

            # 2. LLM 结构化分析
            if include_llm:
                llm_issues = await self._llm_review_file(path, content)
                issues.extend(llm_issues)

        # 3. 可选依赖 CVE 扫描
        if self._scan_deps and self._project_root is not None:
            issues.extend(_scan_dependencies(self._project_root))

        # 4. 汇总
        stats = compute_stats(issues)
        score = compute_overall_score(issues)
        summary = self._build_summary(issues, stats, len(paths), truncated)
        return ReviewResult(
            overall_score=score,
            summary=summary,
            issues=issues,
            stats=stats,
            truncated=truncated,
        )

    async def _llm_review_file(self, path: str, content: str) -> list[ReviewIssue]:
        """调用 LLM 审查单文件，容错解析 JSON 输出."""
        prompt = _REVIEW_PROMPT_TEMPLATE.format(file_path=path, content=content)
        try:
            raw = await self._llm_chat(prompt, LLM_MAX_TOKENS)
        except Exception as e:  # noqa: BLE001 — 单文件 LLM 失败降级为 info
            logger.warning("llm_review_failed file=%s error=%s", path, e)
            return [
                ReviewIssue(
                    file_path=path,
                    line_start=1,
                    line_end=1,
                    severity="info",
                    category="best-practice",
                    message=f"AI 审查调用失败: {str(e)[:100]}",
                    suggestion="检查 API Key 配置后重试",
                )
            ]
        payload = extract_json_payload(raw or "")
        if payload is None:
            # JSON 解析失败：降级为一条 info，保留原始输出摘要
            logger.warning("llm_review_json_parse_failed file=%s", path)
            return [
                ReviewIssue(
                    file_path=path,
                    line_start=1,
                    line_end=1,
                    severity="info",
                    category="best-practice",
                    message="AI 输出非结构化内容，无法解析为审查意见",
                    suggestion=(raw or "")[:200],
                )
            ]
        return parse_llm_issues(payload, default_file=path)

    @staticmethod
    def _build_summary(
        issues: list[ReviewIssue],
        stats: dict[str, dict[str, int]],
        file_count: int,
        truncated: bool,
    ) -> str:
        """生成中文审查摘要."""
        by_sev = stats["by_severity"]
        parts = [f"审查 {file_count} 个文件，共发现 {len(issues)} 个问题"]
        detail = []
        if by_sev.get("critical"):
            detail.append(f"严重 {by_sev['critical']}")
        if by_sev.get("error"):
            detail.append(f"错误 {by_sev['error']}")
        if by_sev.get("warning"):
            detail.append(f"警告 {by_sev['warning']}")
        if by_sev.get("info"):
            detail.append(f"提示 {by_sev['info']}")
        if detail:
            parts.append("（" + "，".join(detail) + "）")
        if truncated:
            parts.append("；因成本熔断部分内容被截断")
        if not issues:
            parts.append("，代码质量良好")
        return "".join(parts)


def _extract_patch_text(raw: str) -> str:
    """从 LLM 输出中提取 unified diff 补丁文本."""
    text = (raw or "").strip()
    if not text:
        return ""
    # 去掉 markdown 代码块包裹
    match = re.search(r"```(?:diff|patch)?\s*(---\s.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1)
    # 定位首个 --- 行
    idx = text.find("--- ")
    if idx >= 0:
        return text[idx:]
    return ""


__all__ = [
    "Category",
    "LLMChatFn",
    "ReviewIssue",
    "ReviewOrchestrator",
    "ReviewResult",
    "Severity",
    "compute_overall_score",
    "compute_stats",
    "extract_json_payload",
    "parse_diff_files",
    "parse_llm_issues",
]
