"""
知识包自动刷新 — 定期检查 skills registry 时效性并自动同步
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class SkillsAutoUpdater:
    """知识包自动刷新"""

    def __init__(self, max_age_hours: int = 24):
        self._max_age_sec = max_age_hours * 3600

    async def refresh_if_stale(self) -> dict:
        """检查知识包时效，过期则刷新"""
        registry_path = self._get_registry_path()

        if registry_path and registry_path.exists():
            age = time.time() - registry_path.stat().st_mtime
            hours_old = age / 3600
            if age > self._max_age_sec:
                logger.info(
                    "技能包已过期 (%.1f 小时 > %d 小时)，自动刷新...",
                    hours_old, self._max_age_sec / 3600,
                )
                return await self._refresh()
            else:
                logger.debug("技能包有效 (%.1f 小时 < %d 小时)", hours_old, self._max_age_sec / 3600)
                return {
                    "success": True,
                    "refreshed": False,
                    "message": f"技能包有效 ({hours_old:.1f} 小时内已更新)",
                }

        # 不存在或不可读，强制刷新
        logger.info("技能包不存在，首次加载...")
        return await self._refresh()

    async def force_refresh(self) -> dict:
        """强制刷新技能包"""
        return await self._refresh()

    async def _refresh(self) -> dict:
        """执行刷新"""
        try:
            from pycoder.server.app import get_v2_engine
            v2 = get_v2_engine()
            if v2:
                result = await v2.registry.call("tools_marketplace_skills_sync", {})
                logger.info("技能包刷新完成")
                return {"success": True, "refreshed": True, "result": str(result)[:200]}
            return {"success": False, "error": "V2 引擎不可用"}
        except Exception as exc:
            logger.warning("技能包刷新失败: %s", exc)
            return {"success": False, "error": str(exc)}

    def _get_registry_path(self) -> Path | None:
        """获取技能注册表路径"""
        candidates = [
            Path(os.getcwd()) / ".skills-registry.json",
            Path(os.getcwd()) / ".skills-registry-enhanced.json",
            Path.home() / ".pycoder" / "skills_registry.json",
        ]
        for p in candidates:
            if p.exists():
                return p
        return candidates[0]


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_updater: SkillsAutoUpdater | None = None


def get_skills_updater() -> SkillsAutoUpdater:
    global _updater
    if _updater is None:
        _updater = SkillsAutoUpdater()
    return _updater
