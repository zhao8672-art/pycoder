"""
外部技能数据源采集器 — Phase 1

数据源:
1. Tech Leads Club Agent Skills (200+ 安全验证技能)
   GitHub: https://github.com/tech-leads-club/agent-skills
   结构: packages/skills-catalog/skills/<category>/<skill>/SKILL.md

2. OpenClaw Awesome Skills (5400+ 技能)
   GitHub: https://github.com/VoltAgent/awesome-openclaw-skills
   结构: 按分类整理的技能列表

用法:
    from pycoder.server.skills_external_sources import (
        fetch_techleads_skills,
        build_external_sources_config,
    )
"""

from __future__ import annotations

import time
from pathlib import Path

from pycoder.core.services.log import log
from pycoder.server.skills_data_sources import make_github_request
from pycoder.server.skills_updater_v2 import EnhancedSkill


# ── Tech Leads Club ─────────────────────────────

TECHLEADS_OWNER = "tech-leads-club"
TECHLEADS_REPO = "agent-skills"
TECHLEADS_BASE = "packages/skills-catalog/skills"

# 分类映射: 括号名 → ONET 分类
TECHLEADS_CATEGORY_MAP = {
    "architecture": "web",
    "cloud": "devops",
    "creation": "ai-ml",
    "decision-making": "ai-ml",
    "design": "web",
    "development": "programming-language",
    "gtm": "other",
    "learning": "ai-ml",
    "monitoring": "devops",
    "performance": "devops",
    "quality": "testing",
    "security": "security",
    "tooling": "mcp-tools",
    "web-automation": "web",
}


def fetch_techleads_skills() -> list[EnhancedSkill]:
    """从 Tech Leads Club 拉取技能列表

    获取策略:
    1. 列出 skills/ 下的所有分类目录 (1 次 API)
    2. 列出每个分类下的技能 (N 次 API)
    3. 构建 EnhancedSkill 对象（不拉取 SKILL.md 内容，仅元数据）
    """
    all_skills: dict[str, EnhancedSkill] = {}
    source_id = "techleads-club"

    try:
        # 1. 列出顶级分类
        categories_raw = make_github_request(
            f"https://api.github.com/repos/{TECHLEADS_OWNER}/{TECHLEADS_REPO}"
            f"/contents/{TECHLEADS_BASE}",
        )
    except RuntimeError as e:
        log.warning("techleads_list_failed", error=str(e)[:80])
        return []

    if not isinstance(categories_raw, list):
        return []

    categories = [
        item for item in categories_raw
        if item.get("type") == "dir"
    ]
    total_categories = len(categories)
    log.info("techleads_categories_found", count=total_categories)

    for cat_item in categories:
        cat_name = cat_item["name"].strip("()")
        onet_category = TECHLEADS_CATEGORY_MAP.get(cat_name, "other")

        try:
            skills_raw = make_github_request(cat_item["url"])
        except RuntimeError:
            continue

        if not isinstance(skills_raw, list):
            continue

        skill_dirs = [s for s in skills_raw if s.get("type") == "dir"]

        for skill_item in skill_dirs:
            skill_name = skill_item["name"]
            skill_id = f"tlc_{cat_name}_{skill_name}".replace("-", "_")

            # 使用技能名和分类构造描述，避免逐个读 SKILL.md
            description = f"{cat_name} 分类技能: {skill_name.replace('-', ' ').title()}"

            skill = EnhancedSkill(
                id=skill_id,
                name=skill_name.replace("-", " ").title(),
                description=description[:300],
                author="Tech Leads Club",
                repository_url=skill_item.get("html_url", ""),
                stars=4943,  # 仓库总 star
                downloads=100,
                source=source_id,
                verified=True,
                category=onet_category,
                official=False,
                tags=[cat_name, "verified", "safe"],
            )
            existing = all_skills.get(skill.id)
            if not existing or skill.quality_score() > existing.quality_score():
                all_skills[skill.id] = skill

    log.info(
        "techleads_fetch_complete",
        count=len(all_skills),
        categories=total_categories,
    )
    return list(all_skills.values())


# ── OpenClaw Awesome Skills ─────────────────────

OPENCLAW_OWNER = "VoltAgent"
OPENCLAW_REPO = "awesome-openclaw-skills"


def fetch_openclaw_skills() -> list[EnhancedSkill]:
    """从 OpenClaw Awesome Skills 的 categories/ 目录解析技能列表（5400+）

    策略:
    1. 列出 categories/ 目录下的所有 .md 文件（1 次 API）
    2. 下载每个 .md 文件，解析 `[name](url) - description` 格式的链接
    3. 每个链接 = 一个独立技能
    """
    all_skills: dict[str, EnhancedSkill] = {}
    source_id = "openclaw"

    try:
        # 1. 列出 categories 目录
        cat_files_raw = make_github_request(
            f"https://api.github.com/repos/{OPENCLAW_OWNER}/{OPENCLAW_REPO}"
            f"/contents/categories",
        )
    except RuntimeError as e:
        log.warning("openclaw_categories_list_failed", error=str(e)[:80])
        return []

    if not isinstance(cat_files_raw, list):
        return []

    md_files = [item for item in cat_files_raw
                if item.get("type") == "file" and item["name"].endswith(".md")]
    log.info("openclaw_category_files_found", count=len(md_files))

    import base64
    import re

    skill_pattern = re.compile(
        r"\[([^\]]+)\]\(https://clawskills\.sh/skills/([^)]+)\)\s*[-–—]\s*([^\n]+)"
    )

    total_skills = 0

    for md_item in md_files:
        api_url = md_item["url"]
        cat_name = md_item["name"].replace(".md", "")

        try:
            data = make_github_request(api_url)
            if not isinstance(data, dict) or "content" not in data:
                continue
            content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        except Exception as e:
            log.debug("openclaw_category_fetch_failed", cat=cat_name, error=str(e)[:60])
            continue

        cat_count = 0
        for match in skill_pattern.finditer(content):
            name = match.group(1).strip()
            skill_slug = match.group(2).strip()
            description = match.group(3).strip()[:300]

            if not name or not skill_slug:
                continue

            skill_id = f"oc_{skill_slug.replace('/', '_')}"
            full_repo_url = f"https://clawskills.sh/skills/{skill_slug}"

            skill = EnhancedSkill(
                id=skill_id,
                name=name.replace("-", " ").title(),
                description=description,
                author=skill_slug.split("-")[0] if "-" in skill_slug else "OpenClaw",
                repository_url=full_repo_url,
                stars=500,  # OpenClaw registry 基础分
                downloads=50,
                source=source_id,
                category="other",
                tags=[cat_name, "openclaw"],
            )

            existing = all_skills.get(skill.id)
            if not existing or skill.quality_score() > existing.quality_score():
                all_skills[skill.id] = skill
                cat_count += 1

        if cat_count:
            log.debug("openclaw_category_parsed", cat=cat_name, count=cat_count)

        total_skills += cat_count

    log.info(
        "openclaw_fetch_complete",
        count=len(all_skills),
        categories=len(md_files),
        total_parsed=total_skills,
    )
    return list(all_skills.values())


# ── 统一采集函数 ────────────────────────────────


def fetch_all_external_skills() -> list[EnhancedSkill]:
    """从所有外部数据源采集技能"""
    all_skills: dict[str, EnhancedSkill] = {}
    sources_status = []

    # 1. Tech Leads Club (200+ 验证技能)
    try:
        tlc_skills = fetch_techleads_skills()
        for s in tlc_skills:
            all_skills[s.id] = s
        sources_status.append({
            "source": "techleads-club",
            "count": len(tlc_skills),
            "success": True,
        })
        log.info("external_source_done", source="techleads-club", count=len(tlc_skills))
    except Exception as e:
        sources_status.append({
            "source": "techleads-club",
            "count": 0,
            "success": False,
            "error": str(e)[:80],
        })
        log.warning("external_source_failed", source="techleads-club", error=str(e)[:80])

    # 2. OpenClaw Awesome (5400+)
    try:
        oc_skills = fetch_openclaw_skills()
        for s in oc_skills:
            if s.id not in all_skills:
                all_skills[s.id] = s
        sources_status.append({
            "source": "openclaw",
            "count": len(oc_skills),
            "success": True,
        })
        log.info("external_source_done", source="openclaw", count=len(oc_skills))
    except Exception as e:
        sources_status.append({
            "source": "openclaw",
            "count": 0,
            "success": False,
            "error": str(e)[:80],
        })
        log.warning("external_source_failed", source="openclaw", error=str(e)[:80])

    return list(all_skills.values()), sources_status


# ── 合并到现有注册表 ─────────────────────────────


def merge_external_skills(
    external_skills: list[EnhancedSkill],
    registry_path: str | Path | None = None,
) -> dict:
    """将外部技能合并到 skills-registry-enhanced.json

    Args:
        external_skills: 外部技能列表
        registry_path: 注册表 JSON 路径

    Returns:
        合并统计
    """
    if registry_path is None:
        registry_path = Path.cwd() / ".skills-registry-enhanced.json"

    import json

    # 读取现有注册表
    existing: dict[str, dict] = {}
    registry_path = Path(registry_path)
    if registry_path.exists():
        try:
            data = json.loads(registry_path.read_text(encoding="utf-8"))
            for skill in data.get("skills", []):
                existing[skill["id"]] = skill
        except (json.JSONDecodeError, OSError):
            pass

    # 合并
    added = 0
    updated = 0
    for es in external_skills:
        d = es.to_dict()
        if es.id in existing:
            # 更新: 保留原有数据, 补充新字段
            old = existing[es.id]
            for k, v in d.items():
                if v and not old.get(k):
                    old[k] = v
            updated += 1
        else:
            existing[es.id] = d
            added += 1

    # 保存
    output = {
        "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total": len(existing),
        "skills": sorted(
            existing.values(),
            key=lambda s: s.get("quality_score", 0),
            reverse=True,
        ),
    }
    registry_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    log.info(
        "external_skills_merged",
        added=added,
        updated=updated,
        total=len(existing),
    )
    return {
        "success": True,
        "added": added,
        "updated": updated,
        "total": len(existing),
        "path": str(registry_path),
    }
