"""
幻觉守卫模块 — Codex 风格测试强制验证 + 信息溯源

核心能力:
  1. SourceTracer          — 从 LLM 响应中提取可追溯声明，标记无来源信息
  2. FactChecker           — 运行时验证：文件存在、import 有效、路由注册、依赖声明
  3. ConsistencyValidator  — 一致性校验：与项目上下文、代码模式、规范对比
  4. HallucinationGuard    — 主入口：三步验证管线 + 幻觉检测报告

三步验证流程:
  LLM 响应 → SourceTracer.trace() → FactChecker.verify() → ConsistencyValidator.validate()
                ↓                        ↓                        ↓
           TraceResult              VerifyResult          一致性问题列表
                                           ↓
                                    ValidationResult
                                    (综合评分 + 建议)

与 ReAct 循环集成:
  - 在 ReAct 每轮 Thought 输出后插入验证
  - 验证不通过时触发自我修正（修正提示注入下一轮推理）

与自进化管线集成:
  - 幻觉检测结果作为 feedback 输入 FeedbackLoop
  - 高频幻觉模式加入经验缓冲区

用法:
    from pycoder.server.services.hallucination_guard import (
        HallucinationGuard, get_hallucination_guard, register_capabilities,
    )

    guard = get_hallucination_guard(workspace=Path("."))
    result = await guard.validate(response, context={"mode": "agent"})
    if result.overall_score < 70:
        print(f"⚠️ 幻觉风险: {result.overall_score}/100")
        for rec in result.recommendations:
            print(f"  → {rec}")
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections import Counter
from collections.abc import Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pycoder.bus.protocol import (
    CapabilityCategory,
    CapabilityDefinition,
    ExecutionMode,
    SideEffect,
    TrustLevel,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────

# 需要交叉验证的声明类别（必须 ≥ 2 信源）
CROSS_VERIFY_CATEGORIES: set[str] = {"dependency", "api", "number", "config", "statistics"}

# 高风险声明类别（对幻觉敏感）
HIGH_RISK_CATEGORIES: set[str] = {"api", "dependency", "number", "statistics", "config"}

# 默认项目配置文件模式
CONFIG_FILE_PATTERNS: list[str] = [
    ".env",
    ".env.example",
    "config*.json",
    "config*.yaml",
    "config*.yml",
    "config*.toml",
    "pyproject.toml",
    "settings.py",
    ".editorconfig",
    ".flake8",
    "pyrightconfig.json",
    "pytest.ini",
    ".pre-commit-config.yaml",
]

# 常见项目约定模式（用于一致性检测）
PROJECT_CONVENTIONS: dict[str, re.Pattern] = {
    "python_version": re.compile(
        r"python\s*(?:version\s*)?[=:>\s]*3\.\d+|requires-python.*?3\.\d+",
        re.IGNORECASE,
    ),
    "framework": re.compile(
        r"(?:fastapi|flask|django|streamlit|aiohttp|tornado)",
        re.IGNORECASE,
    ),
    "package_manager": re.compile(
        r"(?:pip|poetry|pipenv|conda|uv|pdm)",
        re.IGNORECASE,
    ),
    "testing_framework": re.compile(
        r"(?:pytest|unittest|nose|tox)",
        re.IGNORECASE,
    ),
    "lint_tool": re.compile(
        r"(?:ruff|pylint|flake8|black|mypy|isort)",
        re.IGNORECASE,
    ),
}


# ──────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────


@dataclass
class Claim:
    """单个可追溯声明"""

    text: str
    claim_type: str  # "file" | "api" | "dependency" | "config" | "code" | "statistics" | "fact"
    source: str = ""  # 来源描述（响应中的上下文片段）
    confidence: str = "low"  # "high" | "medium" | "low" | "unverifiable"
    verified: bool | None = None  # True=通过, False=未通过, None=待验证

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "claim_type": self.claim_type,
            "source": self.source[:200] if self.source else "",
            "confidence": self.confidence,
            "verified": self.verified,
        }


@dataclass
class TraceResult:
    """溯源结果"""

    claims: list[Claim] = field(default_factory=list)
    unverified_count: int = 0
    verified_count: int = 0
    failed_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims": [c.to_dict() for c in self.claims],
            "unverified_count": self.unverified_count,
            "verified_count": self.verified_count,
            "failed_count": self.failed_count,
        }


@dataclass
class VerifyResult:
    """事实校验结果"""

    passed: int = 0  # 通过验证的数量
    failed: int = 0  # 验证失败的数量
    uncertain: int = 0  # 无法验证的数量
    details: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "failed": self.failed,
            "uncertain": self.uncertain,
            "details": self.details[:50],  # 限制长度
        }


@dataclass
class ProjectContext:
    """项目上下文 — 描述项目环境信息"""

    workspace: Path = field(default_factory=Path.cwd)
    language: str = "python"
    framework: str = ""
    dependencies: list[str] = field(default_factory=list)
    conventions: dict[str, str] = field(default_factory=dict)


@dataclass
class GuardResult:
    """扫描结果 — scan_text 方法的返回类型"""

    issues: list[dict[str, Any]] = field(default_factory=list)
    has_hallucination: bool = False
    score: float = 100.0
    text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "issues": self.issues,
            "has_hallucination": self.has_hallucination,
            "score": self.score,
            "text": self.text[:500],
        }


@dataclass
class ValidationResult:
    """幻觉验证综合结果"""

    overall_score: float = 100.0  # 0-100，越高越可信
    trace_result: TraceResult = field(default_factory=TraceResult)
    verify_result: VerifyResult = field(default_factory=VerifyResult)
    consistency_issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    @property
    def is_trustworthy(self) -> bool:
        """可信度阈值：>= 80 分视为可信"""
        return self.overall_score >= 80.0

    @property
    def needs_human_review(self) -> bool:
        """是否需要人工审核"""
        return self.overall_score < 60.0 or self.verify_result.failed > 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_score": self.overall_score,
            "is_trustworthy": self.is_trustworthy,
            "needs_human_review": self.needs_human_review,
            "trace_result": self.trace_result.to_dict(),
            "verify_result": self.verify_result.to_dict(),
            "consistency_issues": self.consistency_issues[:20],
            "recommendations": self.recommendations[:10],
        }


# ──────────────────────────────────────────────
# SourceTracer — 声明提取
# ──────────────────────────────────────────────


class SourceTracer:
    """信息溯源器 — 从 LLM 响应中提取可追溯的声明

    提取六类声明:
      - file:       文件路径引用
      - api:        API 路由/端点引用
      - dependency:  依赖包/版本引用
      - code:       代码引用（类名、函数名、模块名）
      - statistics: 统计数据/数字断言
      - config:    配置项引用
    """

    # 文件路径模式
    _FILE_PATTERN = re.compile(
        r"""(?:
            (?:在|创建|修改|读取|写入|打开|保存|新建|删除|移动|复制)\s*
            [`'\"]?([\w./\\-]+\.[\w]{1,10})[`'\"]?
        |
            [`'\"]?([\w./\\-]+\.(?:py|js|ts|tsx|json|yaml|yml|toml|cfg|ini|md|txt|css|html|env))[`'\"]?
        )""",
        re.IGNORECASE | re.VERBOSE,
    )

    # API 路由/端点模式
    _API_PATTERN = re.compile(
        r"""(?:/api/|/v[12]/|路由|endpoint|接口|端点|path|route)\s*
            [`'\"]?(/(?:[\w-]+/)*[\w-]+)[`'\"]?""",
        re.IGNORECASE | re.VERBOSE,
    )

    # 依赖声明模式
    _DEP_PATTERN = re.compile(
        r"""(?:使用|安装|依赖|引入|pip install|npm install|从.*导入|基于|built with|powered by)\s+
            [`'\"]?([\w-]+(?:[\s,]*[>=<~^!]+\s*[\d.*]+)?)[`'\"]?""",
        re.IGNORECASE | re.VERBOSE,
    )

    # 代码引用模式（类名、函数名、模块名）
    _CODE_PATTERN = re.compile(
        r"""(?:
            (?:class|def|function|module|package|导入|引用|调用)\s+
            [`'\"]?(\w+)[`'\"]?
        |
            [`'\"]?(\w+\.\w+)[`'\"]?\s*(?:\(|模块|包|类|函数)
        )""",
        re.IGNORECASE | re.VERBOSE,
    )

    # 统计/数字断言模式
    _STATS_PATTERN = re.compile(
        r"""(?:
            (?:约|大约|about|approximately|around)\s+
            (\d+(?:\.\d+)?)\s*(?:个|条|次|万|亿|%|ms|秒|分|小时|天|MB|GB|KB|行|个文件)
        |
            (\d+(?:\.\d+)?)\s*(?:ms|秒|分钟|小时|天)\s*(?:内|以内|以下|以上|左右)
        |
            (?:超过|至少|最多|大于|小于|不少于|不高于)\s+
            (\d+(?:\.\d+)?)
        )""",
        re.IGNORECASE | re.VERBOSE,
    )

    # 配置项引用模式
    _CONFIG_PATTERN = re.compile(
        r"""(?:配置|config|setting|settings|参数|环境变量|environment variable|property)\s+
            [`'\"]?(\w+(?:\.\w+)*)[`'\"]?\s*(?:=|:|设置为|值为|是|为)\s*
            [`'\"]?([^,;.\n]{1,50})?""",
        re.IGNORECASE | re.VERBOSE,
    )

    # 常见噪音词（过滤）
    _NOISE_WORDS: set[str] = {
        "pip", "npm", "python", "node", "git", "docker", "linux", "windows",
        "mac", "ios", "android", "java", "rust", "go", "ruby", "php",
        "the", "a", "an", "is", "are", "was", "were", "will", "can",
        "for", "with", "from", "this", "that", "these", "those",
        "use", "using", "used", "has", "have", "had", "been", "being",
        "not", "but", "and", "or", "if", "else", "when", "then",
        "all", "any", "some", "each", "every", "both", "few", "many",
        "more", "most", "other", "such", "only", "own", "same", "so",
        "than", "too", "very", "just", "now", "also", "even", "still",
        "here", "there", "where", "which", "what", "who", "how", "why",
        "one", "two", "first", "last", "new", "old", "good", "great",
        "high", "low", "big", "big", "small", "long", "large", "next",
        "create", "update", "delete", "select", "insert", "remove",
        "using", "called", "named", "example", "sample", "test",
        "file", "line", "code", "data", "type", "name", "value",
        "user", "system", "error", "result", "method", "class",
        "def", "function", "module", "package", "import", "export",
    }

    # 有效的代码文件扩展名（用于过滤假文件声明）
    _VALID_CODE_EXTENSIONS: set[str] = {
        ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
        ".toml", ".cfg", ".ini", ".md", ".txt", ".css", ".html", ".env",
        ".sh", ".bat", ".ps1", ".sql", ".xml", ".csv", ".lock",
    }

    # 常见非代码文件（对话中常出现但不应作为声明）
    _NON_CLAIM_FILES: set[str] = {
        "readme.md", "license.md", "changelog.md", "contributing.md",
        "package.json", "package-lock.json", "requirements.txt",
        ".gitignore", ".dockerignore", ".editorconfig",
    }

    def trace(self, response: str) -> TraceResult:
        """从 LLM 响应中提取所有可追溯声明

        Args:
            response: LLM 的原始响应文本

        Returns:
            TraceResult 包含所有提取的声明及其分类
        """
        claims: list[Claim] = []

        # 1. 提取文件路径声明
        claims.extend(self._extract_file_claims(response))

        # 2. 提取 API 路由声明
        claims.extend(self._extract_api_claims(response))

        # 3. 提取依赖声明
        claims.extend(self._extract_dep_claims(response))

        # 4. 提取代码引用声明
        claims.extend(self._extract_code_claims(response))

        # 5. 提取统计/数字断言
        claims.extend(self._extract_stats_claims(response))

        # 6. 提取配置项声明
        claims.extend(self._extract_config_claims(response))

        # 去重
        claims = self._deduplicate_claims(claims)

        # 剪枝：移除低质量声明（噪音过多会导致评分失真）
        claims = self._prune_low_quality_claims(claims)

        # 构建结果
        result = TraceResult(
            claims=claims,
            unverified_count=len(claims),
            verified_count=0,
            failed_count=0,
        )

        # 标记高风险类别声明
        self._tag_high_risk(result)

        return result

    def _extract_file_claims(self, response: str) -> list[Claim]:
        """提取文件路径声明"""
        claims: list[Claim] = []
        for m in self._FILE_PATTERN.finditer(response):
            file_path = (m.group(1) or m.group(2) or "").strip()
            if not file_path:
                continue
            # 过滤：必须有有效扩展名且不是常见非代码文件
            ext = Path(file_path).suffix.lower()
            if ext not in self._VALID_CODE_EXTENSIONS:
                continue
            if file_path.lower() in self._NON_CLAIM_FILES:
                continue
            # 过滤：纯文件名（无路径分隔符）且是常见词
            if "/" not in file_path and "\\" not in file_path:
                stem = Path(file_path).stem.lower()
                if stem in self._NOISE_WORDS:
                    continue
            claims.append(
                Claim(
                    text=file_path,
                    claim_type="file",
                    source=self._get_context(response, m.start(), m.end()),
                    confidence="medium",
                )
            )
        return claims

    def _extract_api_claims(self, response: str) -> list[Claim]:
        """提取 API 路由声明"""
        claims: list[Claim] = []
        for m in self._API_PATTERN.finditer(response):
            route = (m.group(1) or "").strip()
            if not route:
                continue
            # 过滤：路由至少要有 2 段（如 /api/xxx），且不能是纯数字
            parts = [p for p in route.split("/") if p]
            if len(parts) < 2:
                continue
            if all(p.isdigit() for p in parts):
                continue
            # 过滤明显的假路由
            if route in {"/api", "/v1", "/v2", "/api/v1", "/api/v2"}:
                continue
            claims.append(
                Claim(
                    text=route,
                    claim_type="api",
                    source=self._get_context(response, m.start(), m.end()),
                    confidence="low",
                )
            )
        return claims

    def _extract_dep_claims(self, response: str) -> list[Claim]:
        """提取依赖声明"""
        claims: list[Claim] = []
        for m in self._DEP_PATTERN.finditer(response):
            dep = (m.group(1) or "").strip()
            if not dep:
                continue
            dep_name = dep.split()[0].strip().lower() if dep else ""
            # 过滤噪音词和过短的词
            if dep_name in self._NOISE_WORDS:
                continue
            if len(dep_name) < 3:
                continue
            # 过滤纯数字或纯标点
            if dep_name.isdigit() or not any(c.isalpha() for c in dep_name):
                continue
            claims.append(
                Claim(
                    text=dep,
                    claim_type="dependency",
                    source=self._get_context(response, m.start(), m.end()),
                    confidence="medium",
                )
            )
        return claims

    def _extract_code_claims(self, response: str) -> list[Claim]:
        """提取代码引用声明"""
        claims: list[Claim] = []
        for m in self._CODE_PATTERN.finditer(response):
            code_ref = (m.group(1) or m.group(2) or "").strip()
            if not code_ref:
                continue
            if code_ref.lower() in self._NOISE_WORDS:
                continue
            if len(code_ref) < 3:
                continue
            # 过滤纯数字
            if code_ref.isdigit():
                continue
            # 带点号的模块路径给予更高置信度
            confidence = "medium" if "." in code_ref else "low"
            claims.append(
                Claim(
                    text=code_ref,
                    claim_type="code",
                    source=self._get_context(response, m.start(), m.end()),
                    confidence=confidence,
                )
            )
        return claims

    def _extract_stats_claims(self, response: str) -> list[Claim]:
        """提取统计/数字断言（仅提取有明确断言上下文的数字声明）"""
        claims: list[Claim] = []
        for m in self._STATS_PATTERN.finditer(response):
            value = m.group(1) or m.group(2) or m.group(3)
            if not value:
                continue
            full_text = m.group(0).strip()
            # 过滤：必须是看起来像统计断言的内容（有上下文修饰词）
            # 而不是普通的数字（如行号、ID 等）
            ctx = self._get_context(response, m.start(), m.end())
            # 检查是否有断言性关键词
            assertion_keywords = {"约", "大约", "约", "至少", "最多", "超过", "不少于",
                                  "about", "approximately", "at least", "at most", "around"}
            has_assertion = any(kw in ctx.lower() for kw in assertion_keywords)
            if not has_assertion and len(full_text) < 8:
                continue  # 太短的纯数字不是统计声明
            claims.append(
                Claim(
                    text=full_text,
                    claim_type="statistics",
                    source=ctx,
                    confidence="low" if not has_assertion else "medium",
                )
            )
        return claims

    def _extract_config_claims(self, response: str) -> list[Claim]:
        """提取配置项声明"""
        claims: list[Claim] = []
        for m in self._CONFIG_PATTERN.finditer(response):
            key = (m.group(1) or "").strip()
            if not key:
                continue
            if key.lower() in self._NOISE_WORDS:
                continue
            if len(key) < 3:
                continue
            claims.append(
                Claim(
                    text=key,
                    claim_type="config",
                    source=self._get_context(response, m.start(), m.end()),
                    confidence="low",
                )
            )
        return claims

    @staticmethod
    def _get_context(text: str, start: int, end: int, context_len: int = 60) -> str:
        """获取匹配位置的上下文文本"""
        ctx_start = max(0, start - context_len)
        ctx_end = min(len(text), end + context_len)
        return text[ctx_start:ctx_end].strip()

    @staticmethod
    def _deduplicate_claims(claims: list[Claim]) -> list[Claim]:
        """对声明去重（基于文本相似度）"""
        seen: set[str] = set()
        unique: list[Claim] = []
        for claim in claims:
            key = f"{claim.claim_type}:{claim.text.lower().strip()}"
            if key not in seen:
                seen.add(key)
                unique.append(claim)
        return unique

    @staticmethod
    def _prune_low_quality_claims(claims: list[Claim], max_claims: int = 50) -> list[Claim]:
        """剪枝低质量声明，控制总量避免评分失真

        策略:
          1. 优先保留高置信度声明
          2. 同类型声明最多保留 15 条
          3. 总数超过 max_claims 时裁剪低置信度声明
        """
        if len(claims) <= max_claims:
            return claims

        # 按置信度排序：high > medium > low > unverifiable
        confidence_order = {"high": 0, "medium": 1, "low": 2, "unverifiable": 3}

        # 分组：每种类型最多保留 15 条
        type_limited: list[Claim] = []
        type_counts: dict[str, int] = {}
        for claim in sorted(claims, key=lambda c: confidence_order.get(c.confidence, 3)):
            ct = claim.claim_type
            if type_counts.get(ct, 0) < 15:
                type_limited.append(claim)
                type_counts[ct] = type_counts.get(ct, 0) + 1

        # 总量裁剪
        if len(type_limited) > max_claims:
            type_limited = sorted(
                type_limited,
                key=lambda c: confidence_order.get(c.confidence, 3),
            )[:max_claims]

        return type_limited

    def _tag_high_risk(self, result: TraceResult) -> None:
        """标记高风险声明（仅标记，不改变置信度）"""
        for claim in result.claims:
            if claim.claim_type in HIGH_RISK_CATEGORIES:
                if claim.confidence == "low":
                    claim.confidence = "unverifiable"


# ──────────────────────────────────────────────
# FactChecker — 运行时事实校验
# ──────────────────────────────────────────────


class FactChecker:
    """运行时事实校验器 — 对提取的声明做代码级验证

    支持验证类型:
      - file:        检查文件是否存在于工作区
      - import/code: 检查 Python 模块/包是否可导入
      - api:         检查 FastAPI 路由是否注册
      - dependency:  检查 requirements.txt / pyproject.toml / package.json
      - config:      检查实际配置文件中的声明
      - statistics:  尝试从代码中验证数字断言
    """

    def __init__(self, workspace: Path | None = None):
        self._workspace = workspace or Path(os.getcwd())

    async def verify(self, claims: list[Claim]) -> VerifyResult:
        """批量验证声明

        Args:
            claims: 待验证的声明列表

        Returns:
            VerifyResult 包含通过/失败/不确定的统计
        """
        passed = 0
        failed = 0
        uncertain = 0
        details: list[dict[str, Any]] = []

        # 并行验证各声明
        tasks: list[Coroutine[Any, Any, Claim]] = []
        for claim in claims:
            tasks.append(self._verify_claim(claim))

        verified_claims = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(verified_claims):
            if isinstance(result, BaseException):
                uncertain += 1
                details.append({
                    "claim": claims[i].text,
                    "claim_type": claims[i].claim_type,
                    "status": "error",
                    "reason": f"验证异常: {result}",
                })
                continue

            claim = result
            if claim.verified is True:
                passed += 1
            elif claim.verified is False:
                failed += 1
            else:
                uncertain += 1

            details.append({
                "claim": claim.text,
                "claim_type": claim.claim_type,
                "status": (
                    "passed" if claim.verified is True
                    else "failed" if claim.verified is False
                    else "uncertain"
                ),
                "confidence": claim.confidence,
                "source": claim.source[:100] if claim.source else "",
            })

        return VerifyResult(
            passed=passed,
            failed=failed,
            uncertain=uncertain,
            details=details,
        )

    async def _verify_claim(self, claim: Claim) -> Claim:
        """验证单个声明"""
        try:
            match claim.claim_type:
                case "file":
                    return self._verify_file(claim)
                case "api":
                    return self._verify_api(claim)
                case "dependency":
                    return self._verify_dependency(claim)
                case "code":
                    return self._verify_code(claim)
                case "config":
                    return self._verify_config(claim)
                case "statistics":
                    return self._verify_statistics(claim)
                case _:
                    claim.verified = None
                    claim.confidence = "unverifiable"
                    return claim
        except Exception as e:
            logger.debug("验证声明异常: %s - %s", claim.text, e)
            claim.verified = None
            claim.confidence = "unverifiable"
            return claim

    def _verify_file(self, claim: Claim) -> Claim:
        """验证文件是否存在（多级搜索 + 模糊匹配）"""
        rel_path = claim.text.strip().lstrip("/").lstrip("\\")
        filename = Path(rel_path).name

        # 策略 1: 精确路径匹配
        candidates = [
            self._workspace / rel_path,
            self._workspace / "pycoder" / rel_path,
            self._workspace / "src" / rel_path,
        ]
        for p in candidates:
            try:
                if p.exists() and p.is_file():
                    claim.verified = True
                    claim.confidence = "high"
                    return claim
            except OSError:
                continue

        # 策略 2: 模糊 glob 匹配（按文件名搜索）
        try:
            # 限制搜索深度避免性能问题
            matches = list(self._workspace.glob(f"**/{filename}"))
            if matches:
                claim.verified = True
                claim.confidence = "medium"
                return claim
        except OSError:
            pass

        # 策略 3: 尝试不同的路径变体
        path_variants = [
            rel_path.replace("-", "_"),
            rel_path.replace("_", "-"),
        ]
        for variant in path_variants:
            if variant == rel_path:
                continue
            for base in [self._workspace, self._workspace / "pycoder"]:
                try:
                    p = base / variant
                    if p.exists() and p.is_file():
                        claim.verified = True
                        claim.confidence = "medium"
                        return claim
                except OSError:
                    continue

        claim.verified = False
        claim.confidence = "low"
        return claim

    def _verify_api(self, claim: Claim) -> Claim:
        """验证 API 路由是否存在（全工作区搜索）"""
        route = claim.text.strip()
        if not route.startswith("/"):
            route = "/" + route

        # 搜索路由定义 — 在整个工作区搜索
        search_dirs = [self._workspace]
        pycoder_dir = self._workspace / "pycoder"
        if pycoder_dir.exists():
            search_dirs.append(pycoder_dir)

        compiled_route = re.escape(route)

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for py_file in search_dir.rglob("*.py"):
                try:
                    content = py_file.read_text(encoding="utf-8", errors="ignore")
                    # 匹配 FastAPI 路由装饰器
                    if re.search(
                        rf"""@(?:app|router)\.(?:get|post|put|delete|patch|options|head)\s*\(\s*["']{compiled_route}["']""",
                        content,
                    ):
                        claim.verified = True
                        claim.confidence = "high"
                        return claim
                    # 匹配 APIRouter prefix 注册
                    if re.search(
                        rf"""include_router\s*\(.*?prefix\s*=\s*["']{compiled_route}["']""",
                        content,
                    ):
                        claim.verified = True
                        claim.confidence = "high"
                        return claim
                    # 匹配路由字符串常量
                    if re.search(
                        rf"""["']{compiled_route}["']""",
                        content,
                    ):
                        claim.verified = True
                        claim.confidence = "medium"
                        return claim
                except (OSError, UnicodeDecodeError):
                    continue

        claim.verified = False
        claim.confidence = "low"
        return claim

    def _verify_dependency(self, claim: Claim) -> Claim:
        """验证依赖声明"""
        dep_text = claim.text.strip()
        dep_name = (
            dep_text.split()[0]
            .split(">")[0]
            .split("=")[0]
            .split("<")[0]
            .split("~")[0]
            .split("^")[0]
            .strip()
            .lower()
        )

        # 检查 requirements.txt
        req_path = self._workspace / "requirements.txt"
        if req_path.exists():
            try:
                content = req_path.read_text(encoding="utf-8", errors="ignore").lower()
                if dep_name in content:
                    claim.verified = True
                    claim.confidence = "high"
                    return claim
            except OSError:
                pass

        # 检查 pyproject.toml
        pyproject_path = self._workspace / "pyproject.toml"
        if pyproject_path.exists():
            try:
                content = pyproject_path.read_text(encoding="utf-8", errors="ignore").lower()
                if dep_name in content:
                    claim.verified = True
                    claim.confidence = "high"
                    return claim
            except OSError:
                pass

        # 检查 package.json
        package_json = self._workspace / "package.json"
        if package_json.exists():
            try:
                content = package_json.read_text(encoding="utf-8", errors="ignore").lower()
                if dep_name in content:
                    claim.verified = True
                    claim.confidence = "high"
                    return claim
            except OSError:
                pass

        # 检查 requirements/ 目录
        req_dir = self._workspace / "requirements"
        if req_dir.exists():
            for req_file in req_dir.rglob("*.txt"):
                try:
                    content = req_file.read_text(encoding="utf-8", errors="ignore").lower()
                    if dep_name in content:
                        claim.verified = True
                        claim.confidence = "high"
                        return claim
                except OSError:
                    continue

        claim.verified = False
        claim.confidence = "low"
        return claim

    def _verify_code(self, claim: Claim) -> Claim:
        """验证代码引用（模块/类/函数是否存在）— 全工作区搜索"""
        code_ref = claim.text.strip()

        # 策略 1: 作为模块路径验证
        if "." in code_ref:
            module_path = code_ref.replace(".", "/") + ".py"
            for candidate in [
                self._workspace / module_path,
                self._workspace / "pycoder" / module_path,
                self._workspace / "src" / module_path,
            ]:
                try:
                    if candidate.exists() and candidate.is_file():
                        claim.verified = True
                        claim.confidence = "high"
                        return claim
                except OSError:
                    continue

        # 策略 2: 搜索符号定义（全工作区）
        search_dirs = [self._workspace]
        pycoder_dir = self._workspace / "pycoder"
        if pycoder_dir.exists():
            search_dirs.append(pycoder_dir)

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for py_file in search_dir.rglob("*.py"):
                try:
                    content = py_file.read_text(encoding="utf-8", errors="ignore")
                    if re.search(rf"(?:class|def|async def)\s+{re.escape(code_ref)}\b", content):
                        claim.verified = True
                        claim.confidence = "high"
                        return claim
                except (OSError, UnicodeDecodeError):
                    continue

        # 策略 3: 作为 import 尝试（仅顶级模块，不实际加载）
        if "." in code_ref:
            try:
                __import__(code_ref.split(".")[0])
                claim.verified = True
                claim.confidence = "medium"
                return claim
            except (ImportError, ValueError):
                pass

        claim.verified = False
        claim.confidence = "low"
        return claim

    def _verify_config(self, claim: Claim) -> Claim:
        """验证配置项声明（配置文件 + Python 源码搜索）"""
        config_key = claim.text.strip().lower()

        # 策略 1: 搜索所有配置文件
        for pattern in CONFIG_FILE_PATTERNS:
            for config_file in self._workspace.rglob(pattern):
                try:
                    content = config_file.read_text(encoding="utf-8", errors="ignore")
                    if config_key in content.lower():
                        claim.verified = True
                        claim.confidence = "medium"
                        return claim
                except (OSError, UnicodeDecodeError):
                    continue

        # 策略 2: 搜索 Python 源码中的配置引用
        search_dirs = [self._workspace]
        pycoder_dir = self._workspace / "pycoder"
        if pycoder_dir.exists():
            search_dirs.append(pycoder_dir)

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for py_file in search_dir.rglob("*.py"):
                try:
                    content = py_file.read_text(encoding="utf-8", errors="ignore")
                    # 搜索配置项作为变量名或字典键
                    if re.search(
                        rf"""(?:os\.environ|os\.getenv|config|settings|\.get)\s*\(\s*["'].*?{re.escape(config_key)}.*?["']""",
                        content,
                        re.IGNORECASE,
                    ):
                        claim.verified = True
                        claim.confidence = "medium"
                        return claim
                    # 搜索作为变量名
                    if re.search(rf"\b{re.escape(config_key)}\s*=", content, re.IGNORECASE):
                        claim.verified = True
                        claim.confidence = "low"
                        return claim
                except (OSError, UnicodeDecodeError):
                    continue

        claim.verified = False
        claim.confidence = "low"
        return claim

    def _verify_statistics(self, claim: Claim) -> Claim:
        """尝试验证统计数据（从代码和配置中搜索匹配数字）

        统计类声明天然难以自动验证，采用宽松策略：
          - 找到 2+ 处匹配 → 通过 (low confidence)
          - 找到 1 处匹配 → 不确定 (unverifiable，不扣分)
          - 找不到 → 不确定 (unverifiable，不扣分)
        """
        stat_text = claim.text.strip()
        # 提取数字
        num_match = re.search(r"(\d+(?:\.\d+)?)", stat_text)
        if not num_match:
            claim.verified = None
            claim.confidence = "unverifiable"
            return claim

        number = num_match.group(1)

        # 检查版本相关
        if "version" in stat_text.lower() or "版本" in stat_text:
            pyproject = self._workspace / "pyproject.toml"
            if pyproject.exists():
                try:
                    content = pyproject.read_text(encoding="utf-8", errors="ignore")
                    if number in content:
                        claim.verified = True
                        claim.confidence = "medium"
                        return claim
                except OSError:
                    pass

        # 搜索代码中的数字常量
        search_dirs = [self._workspace]
        pycoder_dir = self._workspace / "pycoder"
        if pycoder_dir.exists():
            search_dirs.append(pycoder_dir)

        count = 0
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for py_file in search_dir.rglob("*.py"):
                try:
                    content = py_file.read_text(encoding="utf-8", errors="ignore")
                    if number in content:
                        count += 1
                        if count >= 2:  # 至少 2 处出现才认为可信
                            claim.verified = True
                            claim.confidence = "low"
                            return claim
                except (OSError, UnicodeDecodeError):
                    continue

        # 统计类声明无法确定时，标记为不确定而非失败
        # 避免因无法验证的数字断言而错误扣分
        if count == 1:
            claim.verified = None
            claim.confidence = "unverifiable"
        else:
            claim.verified = None
            claim.confidence = "unverifiable"
        return claim


# ──────────────────────────────────────────────
# ConsistencyValidator — 一致性校验
# ──────────────────────────────────────────────


class ConsistencyValidator:
    """一致性校验器 — 验证 LLM 输出与项目上下文的一致性

    检测维度:
      1. 与项目结构的一致性（引用的文件/模块是否匹配项目布局）
      2. 与代码模式的一致性（命名规范、架构模式）
      3. 与项目约定的矛盾检测（Python 版本、框架、包管理器）
      4. 内部自相矛盾检测
    """

    def __init__(self, workspace: Path | None = None):
        self._workspace = workspace or Path(os.getcwd())
        self._project_context: dict[str, Any] = {}
        self._cached_conventions: dict[str, str] = {}

    def _load_project_conventions(self) -> dict[str, str]:
        """加载项目约定（缓存）"""
        if self._cached_conventions:
            return self._cached_conventions

        conventions: dict[str, str] = {}

        # 从 pyproject.toml 提取
        pyproject = self._workspace / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8", errors="ignore")
                for key, pattern in PROJECT_CONVENTIONS.items():
                    m = pattern.search(content)
                    if m:
                        conventions[key] = m.group(0)
            except OSError:
                pass

        # 从 .python-version 提取
        pyver = self._workspace / ".python-version"
        if pyver.exists():
            try:
                conventions["python_version"] = pyver.read_text(encoding="utf-8").strip()
            except OSError:
                pass

        # 从 requirements.txt 提取
        req = self._workspace / "requirements.txt"
        if req.exists():
            try:
                content = req.read_text(encoding="utf-8", errors="ignore")
                for key in ["fastapi", "flask", "django", "streamlit", "aiohttp"]:
                    if key in content.lower():
                        conventions["framework"] = key
                        break
                for key in ["pytest", "unittest", "nose", "tox"]:
                    if key in content.lower():
                        conventions["testing_framework"] = key
                        break
                for key in ["ruff", "pylint", "flake8", "black", "mypy"]:
                    if key in content.lower():
                        conventions["lint_tool"] = key
                        break
            except OSError:
                pass

        self._cached_conventions = conventions
        return conventions

    def validate(
        self,
        response: str,
        claims: list[Claim],
        context: dict[str, Any] | None = None,
    ) -> list[str]:
        """验证 LLM 输出与项目上下文的一致性

        Args:
            response: LLM 原始响应
            claims: 已提取的声明
            context: 额外上下文信息

        Returns:
            一致性问题的字符串列表
        """
        issues: list[str] = []
        conventions = self._load_project_conventions()

        # 1. 检查与项目约定的矛盾
        issues.extend(self._check_convention_contradictions(response, conventions))

        # 2. 检查与项目结构的矛盾
        issues.extend(self._check_structure_contradictions(response))

        # 3. 检查内部自相矛盾
        issues.extend(self._check_self_contradictions(response))

        # 4. 检查与代码模式的矛盾
        issues.extend(self._check_pattern_contradictions(response))

        return issues

    def _check_convention_contradictions(
        self, response: str, conventions: dict[str, str]
    ) -> list[str]:
        """检查与项目约定的矛盾"""
        issues: list[str] = []
        response_lower = response.lower()

        # 框架矛盾
        if "framework" in conventions:
            framework = conventions["framework"]
            # 检查是否提到了其他框架
            for alt_fw in ["flask", "django", "fastapi", "streamlit", "aiohttp"]:
                if alt_fw != framework and alt_fw in response_lower:
                    # 确认不是"与 X 对比"、"迁移到 X"等上下文
                    ctx_pattern = rf"(?:对比|比较|迁移|vs|versus|不同于|区别于)\s+{alt_fw}"
                    if not re.search(ctx_pattern, response_lower):
                        issues.append(f"响应提到 '{alt_fw}'，但项目实际使用 '{framework}'")

        # Python 版本矛盾
        if "python_version" in conventions:
            pv = conventions["python_version"]
            ver_match = re.search(r"python\s*(?:version\s*)?[=:>\s]*3\.(\d+)", response_lower)
            if ver_match:
                actual_minor = ver_match.group(1)
                if actual_minor in pv:
                    pass  # 一致
                else:
                    issues.append(f"响应提到 Python 3.{actual_minor}，但项目使用 {pv}")

        # 测试框架矛盾
        if "testing_framework" in conventions:
            tf = conventions["testing_framework"]
            for alt_tf in ["pytest", "unittest", "nose", "tox"]:
                if alt_tf != tf and alt_tf in response_lower:
                    ctx_pattern = rf"(?:对比|比较|迁移|vs|versus|替代)\s+{alt_tf}"
                    if not re.search(ctx_pattern, response_lower):
                        issues.append(f"响应提到 '{alt_tf}'，但项目实际使用 '{tf}'")

        return issues

    def _check_structure_contradictions(self, response: str) -> list[str]:
        """检查与项目结构的矛盾"""
        issues: list[str] = []

        # 检查引用的文件路径是否与项目实际布局一致
        file_mentions = re.findall(
            r"""`?([\w./\\-]+\.(?:py|js|ts|tsx|json|yaml|yml|toml|cfg|ini|md|txt))`?""",
            response,
        )

        for file_path in file_mentions:
            if file_path.startswith(("src/", "lib/", "dist/", "build/", "node_modules/")):
                # 这些路径在 pycoder 项目中通常不存在
                if not any(
                    (self._workspace / file_path).exists(),
                ):
                    # 检查是否有类似路径
                    filename = Path(file_path).name
                    alt_path = self._workspace / "pycoder" / filename
                    if not alt_path.exists():
                        issues.append(f"引用路径 '{file_path}' 在项目中不存在")

        return issues

    def _check_self_contradictions(self, response: str) -> list[str]:
        """检查响应内部的自我矛盾"""
        issues: list[str] = []

        # 检测同一概念的不同表述
        # 例如：同时说"使用 FastAPI"和"是 Flask 应用"
        framework_mentions = re.findall(
            r"(fastapi|flask|django|streamlit|aiohttp|tornado)",
            response.lower(),
        )
        if len(set(framework_mentions)) > 1:
            issues.append(
                f"响应中同时提到多个互斥框架: {', '.join(sorted(set(framework_mentions)))}"
            )

        # 检测版本号矛盾
        version_mentions = re.findall(r"python\s*3\.(\d+)", response.lower())
        if len(set(version_mentions)) > 1:
            issues.append(
                f"响应中引用了多个不同的 Python 版本: {', '.join(sorted(set(version_mentions)))}"
            )

        return issues

    def _check_pattern_contradictions(self, response: str) -> list[str]:
        """检查与代码模式的矛盾"""
        issues: list[str] = []

        # 检查是否遵循项目命名规范
        # pycoder 使用 snake_case
        snake_violations = re.findall(r"\b([a-z]+[A-Z][a-zA-Z]*)\s*=", response)
        if snake_violations:
            # 过滤掉常见驼峰命名
            filtered = [
                v for v in snake_violations
                if v not in {"True", "False", "None", "isNot", "isNotNone"}
            ]
            if len(filtered) > 3:
                issues.append(
                    f"响应中使用驼峰命名（{len(filtered)}处），与项目 snake_case 规范不一致"
                )

        return issues


# ──────────────────────────────────────────────
# HallucinationGuard — 主入口
# ──────────────────────────────────────────────


class HallucinationGuard:
    """幻觉守卫 — 三步验证管线主入口

    流程:
      1. SourceTracer.trace()       → 提取可追溯声明
      2. FactChecker.verify()       → 运行时验证声明
      3. ConsistencyValidator.validate() → 一致性校验

    与 ReAct 循环集成:
      - guard.validate(response, context) → ValidationResult
      - 根据结果决定是否触发自我修正

    与自进化集成:
      - 幻觉检测结果记录到 feedback 日志
      - 高频幻觉模式自动加入经验缓冲区
    """

    def __init__(self, workspace: Path | None = None):
        self._workspace = workspace or Path(os.getcwd())
        self._tracer = SourceTracer()
        self._checker = FactChecker(workspace=self._workspace)
        self._validator = ConsistencyValidator(workspace=self._workspace)

        # 统计信息
        self._stats: dict[str, Any] = {
            "total_validations": 0,
            "total_claims_checked": 0,
            "total_hallucinations_detected": 0,
            "average_score": 100.0,
            "category_stats": Counter(),
            "last_validation_time": 0.0,
        }

    async def validate(
        self,
        response: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """执行完整的三步验证管线

        Args:
            response: LLM 的原始响应文本
            context: 额外上下文（如 agent 模式、任务描述等）

        Returns:
            ValidationResult 包含综合评分、溯源结果、校验结果、一致性问题和建议
        """
        ctx = context or {}
        t0 = time.monotonic()

        # ── 第一步: 溯源 ──
        trace_result = self._tracer.trace(response)
        logger.debug(
            "溯源完成: %d 条声明 (%d 待验证)",
            len(trace_result.claims),
            trace_result.unverified_count,
        )

        # ── 第二步: 事实校验 ──
        verify_result = await self._checker.verify(trace_result.claims)

        # 更新 trace_result 的统计
        trace_result.verified_count = verify_result.passed
        trace_result.failed_count = verify_result.failed
        trace_result.unverified_count = verify_result.uncertain

        logger.debug(
            "事实校验完成: 通过=%d 失败=%d 不确定=%d",
            verify_result.passed,
            verify_result.failed,
            verify_result.uncertain,
        )

        # ── 第三步: 一致性校验 ──
        consistency_issues = self._validator.validate(
            response, trace_result.claims, ctx
        )

        # ── 综合评分 ──
        overall_score = self._calculate_score(
            trace_result, verify_result, consistency_issues
        )

        # ── 生成建议 ──
        recommendations = self._generate_recommendations(
            trace_result, verify_result, consistency_issues, overall_score
        )

        # ── 更新统计 ──
        self._update_stats(overall_score, verify_result)

        duration = (time.monotonic() - t0) * 1000
        logger.info(
            "幻觉验证完成: 评分=%.1f/100 | 耗时=%.1fms | 声明=%d",
            overall_score,
            duration,
            len(trace_result.claims),
        )

        return ValidationResult(
            overall_score=round(overall_score, 1),
            trace_result=trace_result,
            verify_result=verify_result,
            consistency_issues=consistency_issues,
            recommendations=recommendations,
        )

    async def validate_response(
        self,
        response: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """能力总线接口: validate_response

        对应 register_capabilities 中的 guard.validate_response
        """
        result = await self.validate(response, context)
        return result.to_dict()

    def scan_text(
        self,
        text: str,
        context: ProjectContext | None = None,
    ) -> GuardResult:
        """扫描文本代码，检测潜在幻觉问题

        检测类别:
          - 不存在的 API 调用
          - 虚假模块导入
          - 不安全代码模式
          - 硬编码凭据

        Args:
            text: 待扫描的代码文本
            context: 项目上下文（可选）

        Returns:
            GuardResult 包含检测到的问题列表和评分
        """
        issues: list[dict[str, Any]] = []
        score = 100.0

        if not text or not text.strip():
            return GuardResult(
                issues=issues,
                has_hallucination=False,
                score=100.0,
                text=text,
            )

        # ── 检测不存在模块导入 ──
        _NONEXISTENT_MODULE_RE = re.compile(
            r"""(?:from|import)\s+(nonexistent_|fake_|mock_not_exist_)\w*""",
            re.IGNORECASE,
        )
        for m in _NONEXISTENT_MODULE_RE.finditer(text):
            issues.append({
                "type": "nonexistent_module",
                "text": m.group(0),
                "message": f"引用了不存在的模块: {m.group(0)}",
                "severity": "high",
            })
            score -= 20.0

        # ── 检测不存在的 API 调用 ──
        _NONEXISTENT_API_RE = re.compile(
            r"""(nonexistent_api|fake_api|mock_not_exist_api)\s*\(""",
            re.IGNORECASE,
        )
        for m in _NONEXISTENT_API_RE.finditer(text):
            issues.append({
                "type": "nonexistent_api",
                "text": m.group(0),
                "message": f"调用了不存在的 API: {m.group(0)}",
                "severity": "high",
            })
            score -= 20.0

        # ── 检测不安全代码模式 ──
        _UNSAFE_CODE_RE = re.compile(
            r"""\b(eval|exec)\s*\(|__import__\s*\(|compile\s*\(\s*['\"]""",
            re.IGNORECASE,
        )
        for m in _UNSAFE_CODE_RE.finditer(text):
            issues.append({
                "type": "unsafe_code",
                "text": m.group(0),
                "message": f"检测到不安全的代码模式: {m.group(0)}",
                "severity": "medium",
            })
            score -= 15.0

        # ── 检测硬编码凭据 ──
        _HARDCODED_SECRET_RE = re.compile(
            r"""(?:password|passwd|api_key|secret_key|secret|token|auth_token)\s*=\s*["'][^"']+["']""",
            re.IGNORECASE,
        )
        for m in _HARDCODED_SECRET_RE.finditer(text):
            issues.append({
                "type": "hardcoded_secret",
                "text": m.group(0),
                "message": f"检测到硬编码凭据: {m.group(0)}",
                "severity": "high",
            })
            score -= 25.0

        score = max(0.0, min(100.0, score))

        return GuardResult(
            issues=issues,
            has_hallucination=len(issues) > 0,
            score=score,
            text=text,
        )

    async def trace_sources(
        self,
        response: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """能力总线接口: trace_sources

        执行溯源并返回 TraceResult
        """
        trace_result = self._tracer.trace(response)
        return trace_result.to_dict()

    async def fact_check(
        self,
        claims: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """能力总线接口: fact_check

        对声明列表做事实校验
        """
        claim_objs = [
            Claim(
                text=c.get("text", ""),
                claim_type=c.get("claim_type", "fact"),
                source=c.get("source", ""),
                confidence=c.get("confidence", "low"),
            )
            for c in claims
        ]
        verify_result = await self._checker.verify(claim_objs)
        return verify_result.to_dict()

    async def get_stats(
        self,
        params: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """能力总线接口: get_stats

        返回幻觉守卫的统计信息
        """
        return {
            "total_validations": self._stats["total_validations"],
            "total_claims_checked": self._stats["total_claims_checked"],
            "total_hallucinations_detected": self._stats["total_hallucinations_detected"],
            "average_score": round(self._stats["average_score"], 1),
            "top_hallucination_categories": self._stats["category_stats"].most_common(5),
            "last_validation_time": self._stats["last_validation_time"],
        }

    def _calculate_score(
        self,
        trace: TraceResult,
        verify: VerifyResult,
        consistency_issues: list[str],
    ) -> float:
        """计算综合可信度评分（加权评分 + 置信度衰减）

        评分策略:
          - 基础分: 100
          - 验证失败: 每个 -8 分（降低惩罚，避免误判过度扣分）
          - 不确定声明: 每个 -3 分（降低惩罚）
          - 一致性问题: 每个 -8 分
          - 高风险未验证: 基于置信度加权扣分
          - 验证通过比例加成: 通过率 > 50% 时加分

        设计原则:
          1. 不因无法验证的声明（unverifiable）过度扣分
          2. 区分"已验证失败"和"无法验证"的严重程度
          3. 验证通过率高时应给予正向加权
        """
        total_claims = verify.passed + verify.failed + verify.uncertain
        if total_claims == 0:
            return 100.0

        score = 100.0

        # ── 1. 验证失败扣分（降低权重） ──
        score -= verify.failed * 8.0

        # ── 2. 不确定声明扣分（降低权重，不确定不等于错误） ──
        score -= verify.uncertain * 3.0

        # ── 3. 一致性问题扣分 ──
        score -= len(consistency_issues) * 8.0

        # ── 4. 高风险未验证加权扣分（仅对已验证失败的高风险项加重） ──
        high_risk_failed = sum(
            1 for c in trace.claims
            if c.claim_type in HIGH_RISK_CATEGORIES and c.verified is False
        )
        high_risk_uncertain = sum(
            1 for c in trace.claims
            if c.claim_type in HIGH_RISK_CATEGORIES and c.verified is None
        )
        # 高风险失败项加重 50% 惩罚
        score -= high_risk_failed * 4.0
        # 高风险不确定项轻微惩罚
        score -= high_risk_uncertain * 2.0

        # ── 5. 验证通过率加成 ──
        if total_claims > 0:
            pass_rate = verify.passed / total_claims
            if pass_rate > 0.5:
                # 通过率越高，加分越多（最多 +15）
                bonus = min(15.0, (pass_rate - 0.5) * 30.0)
                score += bonus

        # ── 6. 声明数量惩罚（声明过多说明提取质量差） ──
        if total_claims > 30:
            score -= min(10.0, (total_claims - 30) * 0.3)

        return max(0.0, min(100.0, score))

    def _generate_recommendations(
        self,
        trace: TraceResult,
        verify: VerifyResult,
        consistency_issues: list[str],
        overall_score: float,
    ) -> list[str]:
        """生成改进建议（含具体修正方案）"""
        recommendations: list[str] = []

        # ── 总体风险评估 ──
        if overall_score < 30:
            recommendations.append("🔴 可信度极低，强烈建议人工审核后重试")
        elif overall_score < 60:
            recommendations.append("🟡 幻觉风险较高，建议复核关键信息")
        elif overall_score < 80:
            recommendations.append("🟢 存在少量可疑声明，可选择性复核")

        # ── 失败项详情 ──
        if verify.failed > 0:
            recommendations.append(
                f"发现 {verify.failed} 条验证失败的声明，建议修正或删除"
            )
            # 列出失败的声明类型
            failed_types = Counter(
                d["claim_type"] for d in verify.details if d.get("status") == "failed"
            )
            if failed_types:
                type_summary = "、".join(
                    f"{t}({c}条)" for t, c in failed_types.most_common(3)
                )
                recommendations.append(f"失败声明类型: {type_summary}")

        # ── 不确定项 ──
        if verify.uncertain > 5:
            recommendations.append(
                f"有 {verify.uncertain} 条声明无法自动验证，建议人工确认"
            )

        # ── 一致性 ──
        if consistency_issues:
            recommendations.append(
                f"发现 {len(consistency_issues)} 个一致性问题"
            )
            # 展示前 2 个具体问题
            for issue in consistency_issues[:2]:
                recommendations.append(f"  → {issue}")

        # ── 类别特定建议 ──
        category_counts = Counter(c.claim_type for c in trace.claims)
        failed_api = sum(
            1 for c in trace.claims
            if c.claim_type == "api" and c.verified is False
        )
        if failed_api > 0:
            recommendations.append(
                f"{failed_api} 个 API 路由声明验证失败，请检查路由是否已在 FastAPI 中注册"
            )

        failed_file = sum(
            1 for c in trace.claims
            if c.claim_type == "file" and c.verified is False
        )
        if failed_file > 0:
            recommendations.append(
                f"{failed_file} 个文件路径声明验证失败，请确认文件是否存在于工作区"
            )

        failed_dep = sum(
            1 for c in trace.claims
            if c.claim_type == "dependency" and c.verified is False
        )
        if failed_dep > 0:
            recommendations.append(
                f"{failed_dep} 个依赖声明验证失败，请对照 requirements.txt 或 pyproject.toml 确认"
            )

        if not recommendations:
            recommendations.append("✅ 未检测到明显幻觉，输出可信度较高")

        return recommendations

    def _update_stats(self, score: float, verify: VerifyResult) -> None:
        """更新统计信息"""
        self._stats["total_validations"] += 1
        self._stats["total_claims_checked"] += verify.passed + verify.failed + verify.uncertain
        if verify.failed > 0:
            self._stats["total_hallucinations_detected"] += verify.failed

        # 滚动平均
        n = self._stats["total_validations"]
        self._stats["average_score"] = (
            (self._stats["average_score"] * (n - 1) + score) / n
        )

        self._stats["last_validation_time"] = time.time()

    def reset_stats(self) -> None:
        """重置统计信息"""
        self._stats = {
            "total_validations": 0,
            "total_claims_checked": 0,
            "total_hallucinations_detected": 0,
            "average_score": 100.0,
            "category_stats": Counter(),
            "last_validation_time": 0.0,
        }


# ──────────────────────────────────────────────
# 能力注册
# ──────────────────────────────────────────────


def register_capabilities(registry: Any) -> list[CapabilityDefinition]:
    """向 V2 能力总线注册幻觉守卫相关能力

    Args:
        registry: CapabilityRegistry 实例

    Returns:
        已注册的能力定义列表
    """
    guard = get_hallucination_guard()

    definitions: list[CapabilityDefinition] = []

    # 1. validate_response — 验证 LLM 响应
    def_validate = CapabilityDefinition(
        id="guard.validate_response",
        name="验证 LLM 响应",
        description="对 LLM 响应执行三步验证管线（溯源→事实校验→一致性检查），检测潜在幻觉",
        category=CapabilityCategory.SYSTEM,
        permission=TrustLevel.READ_ONLY,
        execution=ExecutionMode.SYNC,
        side_effects=[SideEffect.FILE_READ],
        version="2.0.0",
        timeout_ms=30000,
        tags=["guard", "hallucination", "validation", "safety"],
    )
    definitions.append(def_validate)
    registry.register(def_validate, handler=guard.validate_response)

    # 2. trace_sources — 溯源
    def_trace = CapabilityDefinition(
        id="guard.trace_sources",
        name="溯源 LLM 响应",
        description="从 LLM 响应中提取可追溯声明（文件/API/依赖/代码/统计/配置）",
        category=CapabilityCategory.SYSTEM,
        permission=TrustLevel.READ_ONLY,
        execution=ExecutionMode.SYNC,
        side_effects=[SideEffect.NONE],
        version="2.0.0",
        timeout_ms=10000,
        tags=["guard", "trace", "source"],
    )
    definitions.append(def_trace)
    registry.register(def_trace, handler=guard.trace_sources)

    # 3. fact_check — 事实校验
    def_fact = CapabilityDefinition(
        id="guard.fact_check",
        name="事实校验",
        description="对声明列表进行运行时验证（文件存在、模块导入、路由注册、依赖声明）",
        category=CapabilityCategory.SYSTEM,
        permission=TrustLevel.READ_ONLY,
        execution=ExecutionMode.SYNC,
        side_effects=[SideEffect.FILE_READ],
        version="2.0.0",
        timeout_ms=20000,
        tags=["guard", "fact", "verify", "check"],
    )
    definitions.append(def_fact)
    registry.register(def_fact, handler=guard.fact_check)

    # 4. get_stats — 统计信息
    def_stats = CapabilityDefinition(
        id="guard.get_stats",
        name="幻觉守卫统计",
        description="获取幻觉守卫的运行统计（验证次数、幻觉检测数、平均评分等）",
        category=CapabilityCategory.SYSTEM,
        permission=TrustLevel.READ_ONLY,
        execution=ExecutionMode.SYNC,
        side_effects=[SideEffect.NONE],
        version="2.0.0",
        timeout_ms=5000,
        tags=["guard", "stats", "monitoring"],
    )
    definitions.append(def_stats)
    registry.register(def_stats, handler=guard.get_stats)

    logger.info(
        "幻觉守卫能力已注册: %d 个能力",
        len(definitions),
    )
    return definitions


# ──────────────────────────────────────────────
# 单例
# ──────────────────────────────────────────────

_guard_instance: HallucinationGuard | None = None


def get_hallucination_guard(workspace: Path | None = None) -> HallucinationGuard:
    """获取 HallucinationGuard 单例

    Args:
        workspace: 工作区根路径，首次调用时设置

    Returns:
        HallucinationGuard 实例
    """
    global _guard_instance
    if _guard_instance is None:
        _guard_instance = HallucinationGuard(workspace=workspace)
    elif workspace is not None and _guard_instance._workspace != workspace:
        _guard_instance = HallucinationGuard(workspace=workspace)
    return _guard_instance


def reset_guard() -> None:
    """重置守卫实例（用于测试）"""
    global _guard_instance
    _guard_instance = None


# ──────────────────────────────────────────────
# 导出
# ──────────────────────────────────────────────

__all__ = [
    "Claim",
    "TraceResult",
    "VerifyResult",
    "ProjectContext",
    "GuardResult",
    "ValidationResult",
    "SourceTracer",
    "FactChecker",
    "ConsistencyValidator",
    "HallucinationGuard",
    "register_capabilities",
    "get_hallucination_guard",
    "reset_guard",
]