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

# 导入 GitHub 数据源
try:
    from pycoder.server.services.github_source import fetch_github_skills
except ImportError:
    log.warning("github_source_not_available", message="GitHub 数据源模块未找到")
    fetch_github_skills = None


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
            
            # 额外同步 GitHub 数据源
            github_skills = []
            if fetch_github_skills:
                try:
                    github_skills = await fetch_github_skills()
                    log.info("github_skills_synced", count=len(github_skills))
                except Exception as e:
                    log.warning("github_sync_failed", error=str(e))
            
            # 合并 GitHub 技能到现有结果中
            if github_skills:
                result["github_skills"] = github_skills
                result["total_skills"] = result.get("total_skills", 0) + len(github_skills)
                if "sources" not in result:
                    result["sources"] = []
                result["sources"].append("github_trending")
            
            return {
                "success": True,
                "timestamp": result.get("timestamp", ""),
                "total": result.get("total_skills", 0),
                "sources": result.get("sources", []),
            }
        except Exception as e:
            log.warning("sync_failed", error=str(e))
            return {"success": False, "error": str(e)}

    async def sync_github_only(self) -> dict:
        """仅同步 GitHub 数据源"""
        if not fetch_github_skills:
            return {"success": False, "error": "GitHub 数据源不可用"}
        
        try:
            github_skills = await fetch_github_skills()
            self._load_registry(force=True)
            
            # 更新注册表
            for skill in github_skills:
                self._registry[skill["id"]] = skill
            
            self._save_registry()
            
            return {
                "success": True,
                "count": len(github_skills),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception as e:
            log.warning("github_sync_failed", error=str(e))
            return {"success": False, "error": str(e)}

    def _save_registry(self):
        """保存注册表到磁盘"""
        try:
            registry_path = Path(os.getcwd()) / ".skills-registry-enhanced.json"
            registry_path.parent.mkdir(parents=True, exist_ok=True)
            registry_path.write_text(
                json.dumps(
                    {"skills": list(self._registry.values())},
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self._loaded = True
            log.info("registry_saved", count=len(self._registry))
        except Exception as e:
            log.warning("registry_save_failed", error=str(e))

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
