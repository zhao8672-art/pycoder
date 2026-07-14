"""
Skills 自动发现 — 类似 Deep Code／Claude Code 的 .skills/ 目录机制

自动扫描项目级 (.skills/) 和用户级 (~/.pycoder/skills/) 目录，
加载 Markdown 格式的技能定义文件。

当本地目录为空时，自动回退到 skills-registry-enhanced.json（~170 个技能）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 扫描路径 ──────────────────────────────────────────

SKILLS_DIRS: list[Path] = []

# ── 注册表回退路径 ──

_REGISTRY_PATHS = [
    Path.cwd() / ".skills-registry-enhanced.json",
    Path.cwd() / ".skills-registry.json",
    Path.home() / ".pycoder" / "skills_registry.json",
]


def _init_skills_dirs() -> list[Path]:
    """懒初始化 skills 搜索路径"""
    if SKILLS_DIRS:
        return SKILLS_DIRS
    dirs = [
        Path.cwd() / ".skills",  # 项目级
        Path.home() / ".pycoder" / "skills",  # 用户级
    ]
    SKILLS_DIRS.extend(dirs)
    return SKILLS_DIRS


def _load_from_registry() -> list[dict]:
    """从 skills-registry-enhanced.json 加载技能（~170 个）"""
    for reg_path in _REGISTRY_PATHS:
        if reg_path.exists():
            try:
                data = json.loads(reg_path.read_text(encoding="utf-8"))
                skills_data = (
                    data if isinstance(data, list) else data.get("skills", data.get("data", []))
                )
                registry_skills = []
                for item in skills_data:
                    if isinstance(item, dict):
                        name = item.get("name", item.get("id", item.get("title", "")))
                        desc = item.get("description", item.get("summary", ""))
                        content = item.get("content", item.get("prompt", ""))
                        tags = item.get("tags", item.get("categories", []))
                        if name:
                            registry_skills.append(
                                {
                                    "name": name,
                                    "file": name.lower().replace(" ", "-") + ".md",
                                    "description": (desc or "")[:200],
                                    "content": content or f"# {name}\n\n{desc}",
                                    "type": "skill",
                                    "source": "registry",
                                    "tags": tags if isinstance(tags, list) else [],
                                    "stars": item.get("stars", item.get("rating", 0)),
                                }
                            )
                if registry_skills:
                    logger.info(
                        "skills_loaded_from_registry count=%d path=%s",
                        len(registry_skills),
                        reg_path,
                    )
                    return registry_skills
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("skills_registry_load_failed path=%s error=%s", reg_path, e)
    return []


def discover_skills() -> list[dict]:
    """
    扫描所有 skills 目录，返回技能列表。

    当本地目录为空时，自动从 skills-registry-enhanced.json 回退加载（~170 个技能）。

    Returns:
        [{"name", "file", "description", "content", "type", "source"}, ...]
    """
    skills: list[dict] = []
    dirs = _init_skills_dirs()

    for skills_dir in dirs:
        if not skills_dir.exists():
            continue

        source_label = "project" if skills_dir.parent == Path.cwd() else "user"
        for f in sorted(skills_dir.glob("*.md")):
            try:
                content = f.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("skills_read_error", file=str(f), error=str(e))
                continue

            first_line = content.strip().split("\n")[0]
            name = first_line.lstrip("#").strip() if first_line.startswith("#") else f.stem
            lines = content.strip().split("\n")
            desc = lines[1].strip() if len(lines) > 1 else ""

            skills.append(
                {
                    "name": name,
                    "file": str(f.relative_to(skills_dir) if f.is_relative_to(skills_dir) else f),
                    "description": desc,
                    "content": content,
                    "type": "skill",
                    "source": source_label,
                }
            )

    # 始终加载注册表数据（170个技能）作为补充
    registry_skills = _load_from_registry()
    if registry_skills:
        # 合并：本地文件优先，注册表补充
        local_names = {s["name"] for s in skills}
        for rs in registry_skills:
            if rs["name"] not in local_names:
                skills.append(rs)

    return skills


def get_skill(name: str) -> dict | None:
    """按名称查找某个技能"""
    for skill in discover_skills():
        if skill["name"] == name or skill["file"] == name:
            return skill
    return None


def reload_skills() -> list[dict]:
    """清空缓存重新扫描"""
    SKILLS_DIRS.clear()
    return discover_skills()
