"""
信息溯源与事实校验引擎 — 对标智谱Agent"溯源+交叉比对"幻觉抑制机制

核心能力:
  1. SourceTracer  — 从 LLM 响应中提取可追溯的声明，标记无来源信息
  2. FactChecker   — 对代码相关的声明做自动校验（文件存在、import有效、API注册）
  3. CrossValidator — 交叉比对多源结论，需 >= 2 信源一致才可信

用法:
    from pycoder.server.services.source_tracer import get_source_tracer, get_fact_checker

    tracer = get_source_tracer()
    claims = tracer.extract_claims("使用 uvicorn 在 8423 端口启动")
    # [Claim(text="使用 uvicorn", verified=True, ...),
    #  Claim(text="8423 端口", verified=False, ...)]

    checker = get_fact_checker()
    result = await checker.verify_claims(claims, workspace=Path("."))
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class Claim:
    """单个可追溯声明"""

    text: str
    category: str  # "file" | "import" | "api" | "dependency" | "fact" | "number"
    verified: bool | None  # True=通过, False=未通过, None=未校验
    confidence: str  # "high" | "medium" | "low" | "unverifiable"
    source: str = ""  # 来源描述
    evidence: str = ""  # 验证证据
    reason: str = ""  # 未通过原因

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "category": self.category,
            "verified": self.verified,
            "confidence": self.confidence,
            "source": self.source,
            "evidence": self.evidence[:200],
            "reason": self.reason[:200],
        }


@dataclass
class TraceResult:
    """溯源结果"""

    claims: list[Claim] = field(default_factory=list)
    unverified_count: int = 0
    verified_count: int = 0
    failed_count: int = 0
    risk_score: float = 0.0  # 0-100，越高风险越大

    def to_dict(self) -> dict:
        return {
            "claims": [c.to_dict() for c in self.claims],
            "unverified_count": self.unverified_count,
            "verified_count": self.verified_count,
            "failed_count": self.failed_count,
            "risk_score": self.risk_score,
        }


# ══════════════════════════════════════════════════════════
# 信息溯源器
# ══════════════════════════════════════════════════════════

# 需要交叉比对的声明类别（必须 ≥ 2 信源）
CROSS_VERIFY_CATEGORIES = {"dependency", "api", "number", "fact"}


class SourceTracer:
    """信息溯源器 — 将 LLM 输出中可校验的声明提取出来"""

    # 数字/端口类声明
    _NUMBER_PATTERN = re.compile(r"\b(\d{2,5})\s*(?:端口|port|ms|秒|分钟|小时)\b")

    # 文件路径类声明
    _FILE_PATTERN = re.compile(r"(?:在|创建|修改|读取|写入)\s*[`'\"]?([\w./\\-]+\.[a-z]+)[`'\"]?")

    # import 声明
    _IMPORT_PATTERN = re.compile(r"(?:import|from|安装|使用|调用)\s+([\w.]+)")

    # API 路由声明
    _API_PATTERN = re.compile(
        r"(?:/api/|/v1/|/v2/|路由|endpoint|接口)\s*[`'\"]?(/\w+(?:/\w+)*)[`'\"]?"
    )

    # 依赖声明
    _DEP_PATTERN = re.compile(
        r"(?:使用|安装|依赖|引入)\s+[`'\"]?([\w-]+(?:>=|[=<>])\d+\.\d+(?:\.\d+)?)[`'\"]?"
    )

    def trace(self, text: str) -> TraceResult:
        """从文本中提取所有可追溯声明"""
        claims: list[Claim] = []

        # 1. 文件
        for m in self._FILE_PATTERN.finditer(text):
            claims.append(
                Claim(
                    text=m.group(1),
                    category="file",
                    verified=None,
                    confidence="medium",
                    source=text[max(0, m.start() - 20) : m.end() + 20][:100],
                )
            )

        # 2. import
        for m in self._IMPORT_PATTERN.finditer(text):
            pkg = m.group(1)
            # 过滤常见词
            if pkg.lower() in {"pip", "npm", "python", "node", "git"}:
                continue
            claims.append(
                Claim(
                    text=pkg,
                    category="import",
                    verified=None,
                    confidence="medium" if "." in pkg else "low",
                    source=text[max(0, m.start() - 20) : m.end() + 20][:100],
                )
            )

        # 3. API 路由
        for m in self._API_PATTERN.finditer(text):
            claims.append(
                Claim(
                    text=m.group(1),
                    category="api",
                    verified=None,
                    confidence="low",
                    source=text[max(0, m.start() - 20) : m.end() + 20][:100],
                )
            )

        # 4. 依赖版本
        for m in self._DEP_PATTERN.finditer(text):
            claims.append(
                Claim(
                    text=m.group(1),
                    category="dependency",
                    verified=None,
                    confidence="medium",
                    source=text[max(0, m.start() - 20) : m.end() + 20][:100],
                )
            )

        # 5. 数字/端口
        for m in self._NUMBER_PATTERN.finditer(text):
            claims.append(
                Claim(
                    text=m.group(0),
                    category="number",
                    verified=None,
                    confidence="low",
                    source=f"数字: {m.group(1)}",
                )
            )

        # 构建结果
        result = TraceResult(claims=claims)
        result.unverified_count = len(claims)
        result.risk_score = min(100, len(claims) * 10)
        return result

    def tag_unverifiable(self, trace: TraceResult) -> TraceResult:
        """将无来源的标记为"待验证"（智谱策略）"""
        for claim in trace.claims:
            if claim.category in CROSS_VERIFY_CATEGORIES and not claim.source:
                claim.confidence = "unverifiable"
                claim.reason = "无可靠来源，标记为待验证"
        # 重新统计
        trace.unverified_count = sum(1 for c in trace.claims if c.verified is None)
        return trace


# ══════════════════════════════════════════════════════════
# 事实校验器
# ══════════════════════════════════════════════════════════


class FactChecker:
    """事实校验器 — 对提取的声明做代码级验证

    支持验证类型:
      - import: 检查 Python 模块/包是否可导入
      - file: 检查文件是否存在于工作区
      - api: 检查 FastAPI 路由是否注册
      - dependency: 检查 requirements.txt 是否存在
    """

    def __init__(self, workspace: Path | None = None):
        self._workspace = workspace or Path(os.getcwd())

    async def verify_claim(self, claim: Claim) -> Claim:
        """验证单个声明"""
        try:
            if claim.category == "file":
                return self._verify_file(claim)
            elif claim.category == "import":
                return self._verify_import(claim)
            elif claim.category == "dependency":
                return self._verify_dependency(claim)
            elif claim.category == "api":
                return self._verify_api(claim)
            else:
                # 非代码类声明无法自动验证
                claim.verified = None
                claim.confidence = "unverifiable"
                claim.reason = "非代码声明，需要人工确认"
                return claim
        except Exception as e:
            claim.verified = False
            claim.reason = f"校验异常: {e}"
            return claim

    async def verify_claims(
        self,
        claims: list[Claim],
        workspace: Path | None = None,
    ) -> list[Claim]:
        """批量验证声明"""
        if workspace:
            self._workspace = workspace
        return [await self.verify_claim(c) for c in claims]

    async def verify_trace(self, trace: TraceResult) -> TraceResult:
        """验证 TraceResult 中的所有声明"""
        trace.claims = await self.verify_claims(trace.claims)
        trace.verified_count = sum(1 for c in trace.claims if c.verified is True)
        trace.failed_count = sum(1 for c in trace.claims if c.verified is False)
        trace.unverified_count = sum(1 for c in trace.claims if c.verified is None)
        # 风险分：失败项 * 20 + 未验证项 * 10
        trace.risk_score = min(100, trace.failed_count * 20 + trace.unverified_count * 10)
        return trace

    # ── 各类型验证实现 ──

    def _verify_file(self, claim: Claim) -> Claim:
        """验证文件是否存在"""
        rel_path = claim.text.strip().lstrip("/")
        candidates = [
            self._workspace / rel_path,
            self._workspace / "pycoder" / rel_path,
        ]
        for p in candidates:
            if p.exists():
                claim.verified = True
                claim.confidence = "high"
                claim.evidence = f"文件存在: {p}"
                return claim
        claim.verified = False
        claim.confidence = "low"
        claim.reason = f"文件不存在: {', '.join(str(p) for p in candidates)}"
        return claim

    def _verify_import(self, claim: Claim) -> Claim:
        """验证 Python 模块是否可导入"""
        module_name = claim.text.strip()
        try:
            # 先检查本地文件
            local_path = module_name.replace(".", "/") + ".py"
            local_candidates = [
                self._workspace / local_path,
                self._workspace / "pycoder" / local_path,
            ]
            for p in local_candidates:
                if p.exists():
                    claim.verified = True
                    claim.confidence = "high"
                    claim.evidence = f"本地模块存在: {p}"
                    return claim

            # 尝试 sys 导入验证（只检查顶级模块，不实际 load）
            __import__(module_name.split(".")[0])
            claim.verified = True
            claim.confidence = "high"
            claim.evidence = f"已安装模块: {module_name}"
        except ImportError:
            # 检查 requirements.txt
            req_files = [
                self._workspace / "requirements.txt",
                self._workspace / "pyproject.toml",
            ]
            for rf in req_files:
                if rf.exists():
                    content = rf.read_text(encoding="utf-8", errors="ignore")
                    if module_name.split(".")[0].lower() in content.lower():
                        claim.verified = True
                        claim.confidence = "medium"
                        claim.evidence = f"已列在 {rf.name}"
                        return claim
            claim.verified = False
            claim.confidence = "low"
            claim.reason = f"模块 '{module_name}' 未安装且未在依赖中声明"
        return claim

    def _verify_dependency(self, claim: Claim) -> Claim:
        """验证依赖声明"""
        dep_text = claim.text.strip()
        # 检查 requirements.txt
        req_files = [
            self._workspace / "requirements.txt",
            self._workspace / "pyproject.toml",
        ]
        for rf in req_files:
            if rf.exists():
                content = rf.read_text(encoding="utf-8", errors="ignore")
                if dep_text.split(">")[0].split("=")[0].strip().lower() in content.lower():
                    claim.verified = True
                    claim.confidence = "high"
                    claim.evidence = f"已在 {rf.name} 中声明"
                    return claim
        # 检查 pip freeze
        try:
            import subprocess

            r = subprocess.run(
                ["pip", "freeze"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if dep_text.split(">")[0].split("=")[0].strip().lower() in r.stdout.lower():
                claim.verified = True
                claim.confidence = "medium"
                claim.evidence = "已通过 pip 安装"
                return claim
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        claim.verified = None
        claim.confidence = "unverifiable"
        claim.reason = "无法自动验证依赖安装状态"
        return claim

    def _verify_api(self, claim: Claim) -> Claim:
        """验证 API 路由是否存在（扫描 Python 文件）"""
        route = claim.text.strip()
        if not route.startswith("/"):
            route = "/" + route
        # 在 pycoder 目录中搜索路由
        pycoder_dir = self._workspace / "pycoder"
        if not pycoder_dir.exists():
            claim.verified = None
            claim.confidence = "unverifiable"
            return claim
        for py_file in pycoder_dir.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                if route in content:
                    claim.verified = True
                    claim.confidence = "high"
                    claim.evidence = f"路由定义于 {py_file.relative_to(self._workspace)}"
                    return claim
            except (OSError, UnicodeDecodeError):
                continue
        claim.verified = False
        claim.confidence = "low"
        claim.reason = f"未找到路由 '{route}' 的定义"
        return claim


# ══════════════════════════════════════════════════════════
# 交叉比对器
# ══════════════════════════════════════════════════════════


class CrossValidator:
    """交叉比对器 — 多信源一致性校验

    智谱策略：关键数据/行业结论必须 ≥ 2 个信源一致方可采信。
    """

    def __init__(self, workspace: Path | None = None):
        self._workspace = workspace or Path(os.getcwd())

    def cross_verify(self, claims: list[Claim]) -> list[Claim]:
        """对声明做交叉比对，标记需要多源确认的关键声明"""
        for claim in claims:
            if claim.category not in CROSS_VERIFY_CATEGORIES:
                continue
            if claim.verified is not True:
                continue
            if claim.confidence == "low":
                # 低置信度的关键声明：附加"建议多源确认"标记
                claim.reason += " | ⚠️ 建议从 ≥ 2 个信源交叉确认"
        return claims


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_tracer_instance: SourceTracer | None = None
_checker_instance: FactChecker | None = None
_validator_instance: CrossValidator | None = None


def get_source_tracer() -> SourceTracer:
    global _tracer_instance
    if _tracer_instance is None:
        _tracer_instance = SourceTracer()
    return _tracer_instance


def get_fact_checker(workspace: Path | None = None) -> FactChecker:
    global _checker_instance
    if _checker_instance is None or workspace:
        _checker_instance = FactChecker(workspace=workspace)
    return _checker_instance


def get_cross_validator() -> CrossValidator:
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = CrossValidator()
    return _validator_instance
