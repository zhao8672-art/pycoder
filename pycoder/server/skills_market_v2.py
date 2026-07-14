"""
Skills Market 管理器升级版
功能:
- 整合多源数据（本地 + GitHub + HuggingFace）
- 质量评分系统
- 高级搜索和过滤
- 智能推荐引擎
- 性能优化（分页、缓存）
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from pycoder.server.log import log

# 导入升级的 Fetcher
try:
    from pycoder.server.skills_updater_v2 import (
        get_enhanced_fetcher,
    )
except ImportError:
    pass


@dataclass
class SkillRecommendation:
    """技能推荐结果"""

    skill_id: str
    skill_name: str
    reason: str
    score: float
    category: str


class EnhancedSkillsMarketManager:
    """升级版 Skills Market 管理器"""

    def __init__(self):
        self._registry: dict[str, dict] = {}
        self._local_ratings: dict[str, dict] = {}  # 用户本地评分
        self._last_sync = 0.0
        self._loaded = False
        self._ratings_file = Path.home() / ".pycoder" / "skill_ratings.json"

    def _load_registry(self, force: bool = False):
        """加载注册表"""
        if self._loaded and not force:
            return

        registry_path = Path(os.getcwd()) / ".skills-registry-enhanced.json"
        if registry_path.exists():
            try:
                data = json.loads(registry_path.read_text(encoding="utf-8"))
                self._registry = {s["id"]: s for s in data.get("skills", [])}
                self._loaded = True
                log.info("registry_loaded", count=len(self._registry))
            except Exception as e:
                log.warning("registry_load_failed", error=str(e))

    def _load_ratings(self):
        """加载用户评分"""
        if self._ratings_file.exists():
            try:
                self._local_ratings = json.loads(self._ratings_file.read_text(encoding="utf-8"))
            except Exception:
                self._local_ratings = {}

    async def sync_from_all_sources(self) -> dict:
        """从所有数据源同步"""
        try:
            fetcher = get_enhanced_fetcher()
            result = await fetcher.fetch_all()
            self._load_registry(force=True)
            return {
                "success": True,
                "timestamp": result.get("timestamp", ""),
                "total": result.get("total_skills", 0),
                "sources": result.get("sources", []),
            }
        except Exception as e:
            log.warning("sync_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def search(
        self,
        query: str = "",
        category: str = "",
        sort_by: str = "quality",
        tags: list[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """高级搜索"""
        self._load_registry()

        results = list(self._registry.values())

        # 关键词搜索
        if query:
            q = query.lower()
            results = [
                s
                for s in results
                if q in s.get("name", "").lower()
                or q in s.get("description", "").lower()
                or any(q in t.lower() for t in s.get("tags", []))
            ]

        # 分类过滤
        if category:
            results = [s for s in results if s.get("category") == category]

        # 标签过滤
        if tags:
            results = [s for s in results if any(t in s.get("tags", []) for t in tags)]

        # 质量过滤（默认 ≥30 或 verified）
        quality_min_val = 30
        results = [
            s
            for s in results
            if s.get("quality_score", 0) >= quality_min_val or s.get("verified", False)
        ]

        # 新增 quality_tier 字段 + 可用性检测
        from pycoder.server.skills_checker import check_skill_usability

        for s in results:
            qs = s.get("quality_score", 0)
            s["quality_tier"] = "high" if qs > 80 else "medium" if qs > 50 else "low"
            s["usable"] = qs >= 30
            # 集成可用性检测
            usability = check_skill_usability(s)
            s["needs_external_api"] = usability["needs_external_api"]
            s["api_services"] = usability["api_services"]
            s["usable_offline"] = usability["usable_offline"]

        # 排序
        if sort_by == "quality":
            results.sort(key=lambda s: s.get("quality_score", 0), reverse=True)
        elif sort_by == "stars":
            results.sort(key=lambda s: s.get("stars", 0), reverse=True)
        elif sort_by == "downloads":
            results.sort(key=lambda s: s.get("downloads", 0), reverse=True)
        elif sort_by == "rating":
            results.sort(key=lambda s: s.get("rating", 0), reverse=True)
        elif sort_by == "name":
            results.sort(key=lambda s: s.get("name", ""))

        total = len(results)
        paginated = results[offset : offset + limit]

        return {
            "query": query,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total,
            "skills": paginated,
            "quality_disclaimer": "质量评分基于提交者自评和简易算法，不代表实际可用性。建议安装前查看技能详情和用户评价。",
        }

    def get_skill_detail(self, skill_id: str) -> dict:
        """获取技能详情"""
        self._load_registry()
        self._load_ratings()

        skill = self._registry.get(skill_id)
        if not skill:
            return {"error": f"技能 '{skill_id}' 不存在"}

        # 合并用户评分
        rating_info = self._local_ratings.get(skill_id, {})

        return {
            "skill": {
                **skill,
                "user_rating": rating_info.get("rating"),
                "user_review": rating_info.get("review"),
                "user_installed": rating_info.get("installed", False),
            }
        }

    def rate_skill(self, skill_id: str, rating: int, review: str = "") -> dict:
        """评分技能"""
        if rating < 1 or rating > 5:
            return {"success": False, "error": "评分必须在 1-5 之间"}

        self._load_ratings()
        self._local_ratings[skill_id] = {
            "rating": rating,
            "review": review,
            "timestamp": time.time(),
        }

        self._ratings_file.parent.mkdir(parents=True, exist_ok=True)
        self._ratings_file.write_text(
            json.dumps(self._local_ratings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return {"success": True, "skill_id": skill_id, "rating": rating}

    def get_recommendations(self, category: str = "", limit: int = 10) -> list[SkillRecommendation]:
        """获取推荐（含质量警告）"""
        self._load_registry()

        skills = list(self._registry.values())

        if category:
            skills = [s for s in skills if s.get("category") == category]

        # 综合评分: quality_score * 0.5 + user_rating * 0.3 + downloads_factor * 0.2
        self._load_ratings()
        for s in skills:
            user_rating = self._local_ratings.get(s.get("id", ""), {}).get("rating", 0)
            downloads = s.get("downloads", 0)
            downloads_factor = min(downloads / 1000, 100)
            quality = s.get("quality_score", 0)
            s["_composite_score"] = quality * 0.5 + user_rating * 15 + downloads_factor * 0.2

        skills.sort(key=lambda s: s.get("_composite_score", 0), reverse=True)

        recommendations = []
        for skill in skills[:limit]:
            score = skill.get("_composite_score", 0)
            quality = skill.get("quality_score", 0)
            if quality > 80:
                reason = "高质量社区验证"
            elif quality > 50:
                reason = "社区推荐"
            else:
                reason = "新上架（评分较低，请自行评估）"

            recommendations.append(
                SkillRecommendation(
                    skill_id=skill["id"],
                    skill_name=skill.get("name", ""),
                    reason=reason,
                    score=round(score, 1),
                    category=skill.get("category", ""),
                )
            )

        return recommendations

    def get_categories(self) -> dict:
        """获取分类统计"""
        self._load_registry()

        categories: dict[str, int] = {}
        for skill in self._registry.values():
            cat = skill.get("category", "other")
            categories[cat] = categories.get(cat, 0) + 1

        return categories

    def get_trending(self, limit: int = 10) -> list[dict]:
        """获取热门技能"""
        self._load_registry()

        skills = sorted(
            self._registry.values(),
            key=lambda s: (
                s.get("stars", 0) * 0.4 + s.get("downloads", 0) * 0.3 + s.get("rating", 0) * 25
            ),
            reverse=True,
        )

        return skills[:limit]

    def get_stats(self) -> dict:
        """获取统计信息"""
        self._load_registry()

        categories = self.get_categories()
        total_skills = len(self._registry)

        total_stars = sum(s.get("stars", 0) for s in self._registry.values())
        avg_rating = (
            sum(s.get("rating", 0) for s in self._registry.values()) / total_skills
            if total_skills > 0
            else 0
        )

        return {
            "total_skills": total_skills,
            "categories_count": len(categories),
            "categories": categories,
            "total_stars": total_stars,
            "avg_rating": round(avg_rating, 1),
            "total_downloads": sum(s.get("downloads", 0) for s in self._registry.values()),
        }


# 全局单例
_manager: EnhancedSkillsMarketManager | None = None


def get_enhanced_market() -> EnhancedSkillsMarketManager:
    """获取全局管理器"""
    global _manager
    if _manager is None:
        _manager = EnhancedSkillsMarketManager()
    return _manager
