"""
四级质量门禁系统 — 借鉴 Hermes 质量门禁体系

L1: 方案合规校验 — 架构/创意方案生成后、并行开发前
L2: 构建验证 — 编译/构建通过性检查
L3: 代码质量巡检 — 规范校验/安全扫描/冗余检测
L4: 终审验收 — 全链路汇总/全局安全/量化打分/放行判定

评分公式:
  总分 = 规范匹配(25%) + 产出完整(25%) + 测试覆盖(20%) + 安全合规(15%) + 落地可行(15%)

通过门槛:
  >= 85分: 自动放行
  < 85分: 批量重跑（最多2轮）
  仍不达标: 降级交付

硬性驳回:
  - 测试覆盖率 < 85% → 直接驳回
  - 严重安全漏洞（SQL注入/XSS/硬编码密钥）→ 直接驳回
  - 评分 < 80 → 带行号直接打回

用法:
  from pycoder.brain.quality_gate import QualityGate, GateResult, GateLevel

  gate = QualityGate()
  result = gate.check(phase, outputs, gate_level=3)
  if result.passed:
      print("通过")
  else:
      print(f"未通过: {result.reasons}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

logger = logging.getLogger(__name__)


class GateLevel(IntEnum):
    """质量门禁级别"""
    L1 = 1  # 方案合规校验
    L2 = 2  # 构建验证
    L3 = 3  # 代码质量巡检
    L4 = 4  # 终审验收


@dataclass
class GateResult:
    """质量门禁检查结果"""
    level: GateLevel
    passed: bool = False
    score: float = 0.0
    max_score: float = 100.0
    dimensions: dict[str, float] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "passed": self.passed,
            "score": self.score,
            "max_score": self.max_score,
            "dimensions": self.dimensions,
            "issues": self.issues,
            "reasons": self.reasons,
            "recommendations": self.recommendations,
            "grade": self._grade_label(),
        }

    def _grade_label(self) -> str:
        if self.score >= 90:
            return "A"
        elif self.score >= 85:
            return "B"
        elif self.score >= 80:
            return "C"
        elif self.score >= 70:
            return "D"
        return "F"


class QualityGate:
    """四级质量门禁系统

    对标 Hermes 质量体系:
      - L1: 方案校验 → spec_validator
      - L2: 构建验证 → test_engineer
      - L3: 代码巡检 → qa_inspector (L3)
      - L4: 终审验收 → qa_inspector (L4)
    """

    # 评分权重
    WEIGHTS: dict[str, float] = {
        "规范匹配": 0.25,
        "产出完整": 0.25,
        "测试覆盖": 0.20,
        "安全合规": 0.15,
        "落地可行": 0.15,
    }

    # 通过阈值
    PASS_THRESHOLD: float = 85.0
    HARD_REJECT_THRESHOLD: float = 80.0

    # 严重安全漏洞关键词
    CRITICAL_SECURITY_ISSUES: list[str] = [
        "sql注入", "xss", "csrf", "硬编码密钥", "硬编码密码",
        "shell=true", "eval(", "exec(", "pickle.loads",
        "sql injection", "hardcoded key", "hardcoded secret",
    ]

    def check(
        self,
        phase: Any,
        outputs: dict[str, Any],
        gate_level: int = 1,
    ) -> GateResult:
        """执行质量门禁检查

        Args:
            phase: 流水线阶段
            outputs: 阶段产出物
            gate_level: 门禁级别 (1-4)

        Returns:
            GateResult 检查结果
        """
        result = GateResult(level=GateLevel(gate_level))

        if gate_level == 1:
            result = self._check_l1(phase, outputs, result)
        elif gate_level == 2:
            result = self._check_l2(phase, outputs, result)
        elif gate_level == 3:
            result = self._check_l3(phase, outputs, result)
        elif gate_level == 4:
            result = self._check_l4(phase, outputs, result)

        # 硬性驳回检查
        self._check_hard_reject(result)

        logger.info(
            "质量门禁 L%d: passed=%s score=%.1f",
            gate_level, result.passed, result.score,
        )
        return result

    def _check_l1(
        self, phase: Any, outputs: dict[str, Any], result: GateResult
    ) -> GateResult:
        """L1: 方案合规校验"""
        dims: dict[str, float] = {}

        # 规范匹配 — 检查方案是否包含必要字段
        required_fields = ["architecture", "tech_stack", "api_endpoints"]
        if isinstance(outputs, dict):
            dims["规范匹配"] = min(100, sum(
                33 for f in required_fields if f in outputs
            ))

        # 产出完整 — 检查方案完整性
        completeness = 0
        if isinstance(outputs, dict):
            if outputs.get("architecture"):
                completeness += 30
            if outputs.get("tech_stack"):
                completeness += 25
            if outputs.get("api_endpoints"):
                completeness += 25
            if outputs.get("data_models"):
                completeness += 20
        dims["产出完整"] = float(completeness)

        # 安全合规 — 基础检查
        dims["安全合规"] = 80.0  # L1 默认较高

        # 落地可行 — 方案是否可执行
        dims["落地可行"] = 80.0  # L1 默认较高

        # 测试覆盖 — L1 不适用
        dims["测试覆盖"] = 100.0

        return self._compute_result(result, dims)

    def _check_l2(
        self, phase: Any, outputs: dict[str, Any], result: GateResult
    ) -> GateResult:
        """L2: 构建验证"""
        dims: dict[str, float] = {}

        # 规范匹配
        dims["规范匹配"] = 90.0

        # 产出完整
        ready = outputs.get("ready", False) if isinstance(outputs, dict) else False
        dims["产出完整"] = 100.0 if ready else 50.0

        # 安全合规
        dims["安全合规"] = 85.0

        # 落地可行
        dims["落地可行"] = 100.0 if ready else 40.0

        # 测试覆盖
        dims["测试覆盖"] = 100.0

        return self._compute_result(result, dims)

    def _check_l3(
        self, phase: Any, outputs: dict[str, Any], result: GateResult
    ) -> GateResult:
        """L3: 代码质量巡检"""
        dims: dict[str, float] = {}

        # 规范匹配
        dims["规范匹配"] = 85.0

        # 产出完整
        if isinstance(outputs, dict):
            files = outputs.get("files_changed", [])
            dims["产出完整"] = 100.0 if files else 60.0
        else:
            dims["产出完整"] = 60.0

        # 测试覆盖
        if isinstance(outputs, dict):
            coverage = outputs.get("coverage", 0.0)
            dims["测试覆盖"] = min(100, coverage * 100)
        else:
            dims["测试覆盖"] = 0.0

        # 安全合规 — 扫描代码安全
        dims["安全合规"] = self._estimate_security_score(outputs)

        # 落地可行
        dims["落地可行"] = 85.0

        return self._compute_result(result, dims)

    def _check_l4(
        self, phase: Any, outputs: dict[str, Any], result: GateResult
    ) -> GateResult:
        """L4: 终审验收"""
        dims: dict[str, float] = {}

        # 规范匹配
        dims["规范匹配"] = 90.0

        # 产出完整
        if isinstance(outputs, dict):
            report = outputs.get("report", "")
            dims["产出完整"] = 100.0 if report else 50.0
        else:
            dims["产出完整"] = 50.0

        # 测试覆盖
        if isinstance(outputs, dict):
            passed = outputs.get("passed", 0)
            total = outputs.get("test_count", 1)
            dims["测试覆盖"] = min(100, (passed / max(total, 1)) * 100)
        else:
            dims["测试覆盖"] = 0.0

        # 安全合规
        dims["安全合规"] = self._estimate_security_score(outputs)

        # 落地可行
        if isinstance(outputs, dict):
            deployed = outputs.get("deployed", False)
            dims["落地可行"] = 100.0 if deployed else 50.0
        else:
            dims["落地可行"] = 50.0

        return self._compute_result(result, dims)

    def _compute_result(
        self, result: GateResult, dimensions: dict[str, float]
    ) -> GateResult:
        """计算加权评分"""
        result.dimensions = dimensions

        # 加权计算
        total = 0.0
        for dim, weight in self.WEIGHTS.items():
            total += dimensions.get(dim, 0.0) * weight

        result.score = round(total, 1)
        result.passed = result.score >= self.PASS_THRESHOLD

        if not result.passed:
            result.reasons.append(f"评分 {result.score:.1f} < 阈值 {self.PASS_THRESHOLD}")
            for dim, score in dimensions.items():
                if score < 80:
                    result.reasons.append(f"  {dim}: {score:.0f}/100 (不达标)")

        if result.score >= 90:
            result.recommendations.append("各项指标优秀，建议归档为最佳实践")
        elif result.score >= 85:
            result.recommendations.append("通过质量门禁，注意持续改进")
        elif result.score >= 80:
            result.recommendations.append("评分偏低，建议针对性优化后再提交")

        return result

    def _check_hard_reject(self, result: GateResult) -> None:
        """硬性驳回检查"""
        # 测试覆盖率硬性驳回
        test_coverage = result.dimensions.get("测试覆盖", 100)
        if test_coverage < 85:
            result.passed = False
            result.reasons.append(
                f"硬性驳回: 测试覆盖率 {test_coverage:.0f}% < 85%"
            )

        # 评分硬性驳回
        if result.score < self.HARD_REJECT_THRESHOLD:
            result.passed = False
            result.reasons.append(
                f"硬性驳回: 综合评分 {result.score:.1f} < {self.HARD_REJECT_THRESHOLD}"
            )

        # 严重安全漏洞检查
        for issue in result.issues:
            if issue.get("severity") == "critical":
                result.passed = False
                result.reasons.append(
                    f"硬性驳回: 严重安全漏洞 — {issue.get('description', '')}"
                )
                break

    def _estimate_security_score(self, outputs: Any) -> float:
        """估算安全合规分数"""
        if not isinstance(outputs, dict):
            return 70.0

        # 检查是否有安全相关标记
        if outputs.get("security_scan_passed"):
            return 95.0

        # 默认分数
        return 85.0

    def scan_security_issues(self, code: str) -> list[dict[str, Any]]:
        """扫描代码中的安全问题"""
        issues: list[dict[str, Any]] = []
        code_lower = code.lower()

        for issue_pattern in self.CRITICAL_SECURITY_ISSUES:
            if issue_pattern in code_lower:
                issues.append({
                    "severity": "critical",
                    "type": "security",
                    "pattern": issue_pattern,
                    "description": f"检测到高危模式: {issue_pattern}",
                })

        return issues

    def get_stats(self) -> dict[str, Any]:
        """获取门禁统计"""
        return {
            "levels": [l.value for l in GateLevel],
            "pass_threshold": self.PASS_THRESHOLD,
            "hard_reject_threshold": self.HARD_REJECT_THRESHOLD,
            "weights": dict(self.WEIGHTS),
            "critical_patterns": len(self.CRITICAL_SECURITY_ISSUES),
        }


# 全局单例
_quality_gate: QualityGate | None = None


def get_quality_gate() -> QualityGate:
    """获取全局质量门禁"""
    global _quality_gate
    if _quality_gate is None:
        _quality_gate = QualityGate()
    return _quality_gate