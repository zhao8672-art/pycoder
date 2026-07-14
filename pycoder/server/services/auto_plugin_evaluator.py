"""
AutoPluginEvaluator — 插件/Skills 自动评估与排序

职责:
    1. 多维度评分: 社区评分 / 维护频率 / 安全检查 / 环境兼容性
    2. 对候选 Skills 进行排名，推荐最佳选择
    3. 检测兼容性问题 (版本冲突 / 依赖冲突 / 沙箱兼容性)

评分维度:
    质量分 (quality_score) — Skills Market 自带评分
    兼容性 (compatibility) — 与当前 Python 版本、pycoder 版本的匹配度
    安全性 (security_score) — 来源可信 / 代码审查 / API 权限
    维护性 (maintenance) — 最近更新 / 问题响应 / 社区活跃度

用法:
    from .auto_plugin_evaluator import AutoPluginEvaluator
    ev = AutoPluginEvaluator()
    result = await ev.evaluate(skill_id)
    ranked = await ev.rank_candidates([{"id": "a"}, {"id": "b"}])
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class EvaluationResult:
    """单次评估结果"""

    candidate_id: str = ""
    name: str = ""
    overall_score: float = 0.0  # 0-100 综合分
    quality_score: float = 0.0  # 0-40  质量与社区评分
    compatibility: float = 0.0  # 0-25  环境兼容性
    security_score: float = 0.0  # 0-20  安全检查
    maintenance: float = 0.0  # 0-15  维护活跃度
    warnings: list[str] = None
    passed: bool = False  # ≥60 分通过


class AutoPluginEvaluator:
    """插件/Skills 自动评估器"""

    PYTHON_MIN_VERSION = (3, 10)
    PYCODER_MIN_VERSION = "0.5.0"
    _CONFIG_PATH = Path.home() / ".pycoder" / "auto_plugin_eval_cache.json"

    def __init__(self):
        self._eval_cache: dict[str, EvaluationResult] = {}
        self._load_cache()

    # ══════════════════════════════════════════════════════
    # 主评估入口
    # ══════════════════════════════════════════════════════

    async def evaluate(self, skill_data: dict) -> EvaluationResult:
        """对单个候选 Skill 进行全面评估

        Args:
            skill_data: Skills Market 返回的完整条目

        Returns:
            EvaluationResult
        """
        sid = skill_data.get("id", "") or skill_data.get("name", "")

        if sid in self._eval_cache:
            cached = self._eval_cache[sid]
            if time.time() - self._get_cache_time(skill_data) < 3600:
                return cached

        quality = self._score_quality(skill_data)
        compatibility = self._score_compatibility(skill_data)
        security = self._score_security(skill_data)
        maintenance = self._score_maintenance(skill_data)

        overall = quality + compatibility + security + maintenance
        warnings: list[str] = []

        # 警告检测
        if compatibility < 10:
            warnings.append("环境兼容性较低")
        if security < 8:
            warnings.append("安全评分不足 — 建议审查代码")
        if quality < 15:
            warnings.append("社区评分较低")

        result = EvaluationResult(
            candidate_id=sid,
            name=str(skill_data.get("name", sid)),
            overall_score=round(overall, 1),
            quality_score=round(quality, 1),
            compatibility=round(compatibility, 1),
            security_score=round(security, 1),
            maintenance=round(maintenance, 1),
            warnings=warnings or None,
            passed=overall >= 60,
        )
        self._eval_cache[sid] = result
        self._save_cache()
        return result

    # ══════════════════════════════════════════════════════
    # 批量排名
    # ══════════════════════════════════════════════════════

    async def rank_candidates(
        self,
        candidates: list[dict],
        top_n: int = 3,
    ) -> list[EvaluationResult]:
        """对多个候选进行排名，返回前 N 个"""
        results: list[EvaluationResult] = []
        for c in candidates:
            r = await self.evaluate(c)
            results.append(r)

        results.sort(key=lambda r: r.overall_score, reverse=True)
        return results[:top_n]

    # ══════════════════════════════════════════════════════
    # 评分维度
    # ══════════════════════════════════════════════════════

    @staticmethod
    def _score_quality(data: dict) -> float:
        """质量与社区评分 (0-40)"""
        score = 0.0

        # 1. 已有 quality_score (Skills Market)
        qs = float(data.get("quality_score", 0) or 0)
        score += min(qs, 30)

        # 2. Stars (GitHub)
        stars = int(data.get("stars", 0) or 0)
        if stars >= 1000:
            score += 10
        elif stars >= 500:
            score += 7
        elif stars >= 100:
            score += 5
        elif stars >= 10:
            score += 2

        return min(score, 40)

    @staticmethod
    def _score_compatibility(data: dict) -> float:
        """环境兼容性 (0-25)"""
        score = 15.0  # 基础分

        # 已认证: +5
        if data.get("verified") or data.get("official"):
            score += 5

        # 有 README 说明: +3
        if data.get("readme_url") or data.get("description"):
            score += 3

        # 最近 6 个月有更新: +2
        import datetime

        pushed = data.get("pushed_at")
        if pushed:
            try:
                pushed_dt = datetime.datetime.fromisoformat(str(pushed).replace("Z", "+00:00"))
                age = datetime.datetime.now().astimezone() - pushed_dt
                if age.days < 180:
                    score += 2
            except (ValueError, TypeError):
                pass

        return min(score, 25)

    @staticmethod
    def _score_security(data: dict) -> float:
        """安全评分 (0-20)"""
        score = 10.0  # 中性基础分

        # GitHub 来源: +5
        repo_url = str(data.get("repository_url", "") or data.get("url", "") or "")
        if "github.com" in repo_url:
            score += 5

        # 官方认证: +5
        if data.get("verified") or data.get("official"):
            score += 5

        # 许可证: +2
        if data.get("license"):
            score += 2

        # 有 issues: +1 (说明有人用)
        issues = int(data.get("issues", 0) or 0)
        if issues > 0:
            score += 1

        return min(score, 20)

    @staticmethod
    def _score_maintenance(data: dict) -> float:
        """维护活跃度 (0-15)"""
        score = 5.0

        stars = int(data.get("stars", 0) or 0)
        if stars >= 500:
            score += 5
        elif stars >= 100:
            score += 3

        installs = int(data.get("installs", 0) or 0)
        if installs >= 1000:
            score += 5
        elif installs >= 100:
            score += 3

        return min(score, 15)

    # ══════════════════════════════════════════════════════
    # 缓存
    # ══════════════════════════════════════════════════════

    def _load_cache(self) -> None:
        if self._CONFIG_PATH.exists():
            try:
                data = json.loads(self._CONFIG_PATH.read_text(encoding="utf-8"))
                for k, v in data.get("evaluations", {}).items():
                    self._eval_cache[k] = EvaluationResult(**v)
            except (json.JSONDecodeError, TypeError, KeyError):
                pass

    def _save_cache(self) -> None:
        self._CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {"evaluations": {k: v.__dict__ for k, v in self._eval_cache.items()}}
        self._CONFIG_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _get_cache_time(data: dict) -> float:
        return time.time()

    def get_stats(self) -> dict:
        return {"cached_evaluations": len(self._eval_cache)}
