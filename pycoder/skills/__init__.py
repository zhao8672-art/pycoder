"""
技能市场模块 — OpenClaw ClawHub 风格技能生态

提供技能的注册、发现、安装、管理和评分功能。
技能元数据存储在 SQLite 数据库中，技能内容存储在文件系统 data/skills/ 目录中。

V2 升级 (2026-07):
- 字段对齐前端 SkillItem（stars/downloads/has_update/verified/publisher/reviews）
- FTS5 全文索引 + BM25 相关性排序
- 递归安装依赖 + 拓扑排序 + 环检测 + 失败回滚
- 原子评分 + UNIQUE(skill_id, user_id) 防刷分
- 详情页扩展：截图/版本历史/评分分布/评论正文
- 异步安装任务 + 进度推送
- 版本检查 + 更新流程

用法:
    from pycoder.skills import SkillMarketplace, SkillDefinition, register_capabilities

    # 获取单例
    marketplace = SkillMarketplace()

    # 注册技能
    await marketplace.register_skill(skill_def, markdown_content)

    # 搜索技能（V2 FTS5）
    results = await marketplace.search_skills_v2("code review")
"""

from __future__ import annotations

from pycoder.skills.models import SkillDefinition
from pycoder.skills.marketplace import SkillMarketplace
from pycoder.skills.capabilities import register_capabilities

# ── 全局单例 ──────────────────────────────────────

_marketplace: SkillMarketplace | None = None


def get_marketplace() -> SkillMarketplace:
    """获取技能市场全局单例"""
    global _marketplace
    if _marketplace is None:
        _marketplace = SkillMarketplace()
    return _marketplace


__all__ = [
    "SkillDefinition",
    "SkillMarketplace",
    "get_marketplace",
    "register_capabilities",
]
