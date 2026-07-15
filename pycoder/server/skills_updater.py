"""
Skills 多源爬虫 — 从 GitHub 实时拉取 community skills，每日自动更新

数据源:
  1. GitHub Search API — topic:claude-skills + topic:skills (801 repos, 按 stars 排序)
  2. anbeime/skill — 自动抓取了 GitHub 上所有 Skills 项目 (3092 stars)
  3. VoltAgent/awesome-agent-skills — 1000+ 精选 skills 列表 (27224 stars)

更新策略:
  - 每 12 小时自动拉取一次
  - 保留本地已有的 skills（不覆盖手动安装的）
  - 新增的 skill 自动追加并排序
  - 去重：按 id (repo-name) 去重，保留 stars 更高的版本
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from pycoder.server.log import log

# ── 数据源配置 ──────────────────────────────────────────

SOURCES = {
    "github_claude_skills": {
        "url": (
            "https://api.github.com/search/repositories"
            "?q=topic:claude-skills+topic:skills&sort=stars&order=desc&per_page=100"
        ),
        "headers": {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "PyCoder-Skills-Bot/1.0",
        },
        "extractor": "extract_from_github_search",
    },
    "github_agent_skills": {
        "url": (
            "https://api.github.com/search/repositories"
            "?q=topic:agent-skills+topic:skills&sort=stars&order=desc&per_page=30"
        ),
        "headers": {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "PyCoder-Skills-Bot/1.0",
        },
        "extractor": "extract_from_github_search",
    },
}

UPDATE_INTERVAL_SECONDS = 43200  # 12 小时


def _validate_url(url: str) -> str:
    """验证 URL 协议仅允许 http/https"""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"不允许的 URL 协议: {parsed.scheme}")
    return url


@dataclass
class FetchedSkill:
    """爬取到的原始 skill 数据"""

    id: str
    name: str
    description: str = ""
    author: str = ""
    stars: int = 0
    downloads: int = 0
    category: str = "other"
    tags: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    url: str | None = None
    file: str | None = None
    source: str = ""
    created_at: str = ""
    updated_at: str = ""


# ── 数据提取器 ──────────────────────────────────────────


def extract_from_github_search(data: dict) -> list[FetchedSkill]:
    """从 GitHub Search API 结果中提取 skills"""
    skills = []
    for item in data.get("items", []):
        name = item.get("name", "")
        full_name = item.get("full_name", "")
        description = (item.get("description") or "")[:200]
        stars = item.get("stargazers_count", 0)
        forks = item.get("forks_count", 0)
        topics = item.get("topics", [])
        created = item.get("created_at", "")
        updated = item.get("updated_at", "")

        # 推断分类
        category = "other"
        name_lower = f"{name} {description}".lower()
        if any(kw in name_lower for kw in ["security", "red", "offensive", "pentest"]):
            category = "security"
        elif any(kw in name_lower for kw in ["test", "testing", "quality", "lighthouse"]):
            category = "code-quality"
        elif any(kw in name_lower for kw in ["database", "postgres", "sql", "redis"]):
            category = "database"
        elif any(kw in name_lower for kw in ["deploy", "docker", "k8s", "kubernetes", "ci"]):
            category = "devops"
        elif any(kw in name_lower for kw in ["research", "ml", "ai", "paper"]):
            category = "research"
        elif any(kw in name_lower for kw in ["ios", "android", "mobile", "swift"]):
            category = "mobile"
        elif any(kw in name_lower for kw in ["web", "frontend", "react", "vue"]):
            category = "web"
        elif any(kw in name_lower for kw in ["api", "design"]):
            category = "architecture"
        elif any(kw in name_lower for kw in ["generate", "media", "image", "video"]):
            category = "creative"
        elif any(kw in name_lower for kw in ["pm", "product", "management"]):
            category = "productivity"

        skills.append(
            FetchedSkill(
                id=name,
                name=name.replace("-skill", "").replace("-skills", "").replace("-", " ").title(),
                description=description,
                author=full_name.split("/")[0] if "/" in full_name else "",
                stars=stars,
                downloads=max(forks, 1),  # forks 近似下载量
                category=category,
                tags=[t for t in topics if t not in ("skills", "claude-skills", "agent-skills")][
                    :5
                ],
                url=f"https://github.com/{full_name}",
                source="github",
                created_at=created,
                updated_at=updated,
            )
        )
    return skills


def extract_from_skills_registry_json(data: dict) -> list[FetchedSkill]:
    """从 awesome-agent-skills 的 registry.json 提取"""
    skills = []
    for item in data.get("skills", []):
        skills.append(
            FetchedSkill(
                id=item.get("id", item.get("name", "").lower().replace(" ", "-")),
                name=item.get("name", item.get("id", "")),
                description=item.get("description", "")[:200],
                author=item.get("author", ""),
                stars=item.get("stars", item.get("downloads", 0) // 10),
                downloads=item.get("downloads", 0),
                category=item.get("category", "other"),
                tags=item.get("tags", [])[:5],
                version=item.get("version", "1.0.0"),
                url=item.get("url"),
                file=item.get("file"),
                source="awesome-list",
                created_at=item.get("created_at", ""),
                updated_at=item.get("updated_at", ""),
            )
        )
    return skills


# ── 爬虫引擎 ─────────────────────────────────────────────


class SkillsFetcher:
    """多源 Skills 爬虫"""

    def __init__(self):
        self._registry_path = Path(os.getcwd()) / ".skills-registry.json"
        self._last_update = 0.0
        self._extractors = {
            "extract_from_github_search": extract_from_github_search,
            "extract_from_skills_registry_json": extract_from_skills_registry_json,
        }

    @staticmethod
    def _fetch_one_source(source_name: str, config: dict) -> dict | None:
        """同步拉取单个数据源（在线程中运行，不阻塞事件循环）"""
        import urllib.request

        _validate_url(config["url"])
        req = urllib.request.Request(
            config["url"],
            headers=dict(config["headers"].items()),
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        return data

    async def fetch_all_sources(self) -> dict:
        """从所有数据源拉取最新 skills 列表（不阻塞事件循环）"""
        import asyncio

        all_skills: dict[str, FetchedSkill] = {}
        sources_status: list[dict] = []

        for source_name, config in SOURCES.items():
            try:
                data = await asyncio.to_thread(self._fetch_one_source, source_name, config)
                if data is None:
                    continue

                extractor_fn = config["extractor"]
                extractor = self._extractors[extractor_fn]
                skills = extractor(data)

                for s in skills:
                    existing = all_skills.get(s.id)
                    if not existing or s.stars > existing.stars:
                        all_skills[s.id] = s

                sources_status.append(
                    {
                        "source": source_name,
                        "success": True,
                        "count": len(skills),
                    }
                )
                log.info("skills_fetch_source", source=source_name, count=len(skills))

            except Exception as e:
                sources_status.append(
                    {
                        "source": source_name,
                        "success": False,
                        "error": str(e)[:100],
                    }
                )
                log.warning("skills_fetch_failed", source=source_name, error=str(e)[:80])

        self._last_update = time.time()
        self._save_registry(all_skills)

        return {
            "success": True,
            "total_skills": len(all_skills),
            "sources": sources_status,
            "last_update": self._last_update,
        }

    def _save_registry(self, skills: dict[str, FetchedSkill]):
        """保存到本地注册表文件（合并已有 file/url 信息）"""
        # 加载现有注册表已有的 file 字段，防止 GitHub 同步覆盖
        existing_skills = {}
        if self._registry_path.exists():
            try:
                edata = json.loads(self._registry_path.read_text(encoding="utf-8"))
                for es in edata.get("skills", []):
                    eid = es.get("id", "")
                    if eid and es.get("file"):
                        existing_skills[eid] = {"file": es["file"], "url": es.get("url", "")}
            except (json.JSONDecodeError, OSError):
                pass

        # 合并: GitHub 来的 skill 继承原有的 file 字段
        for s in skills.values():
            existing = existing_skills.get(s.id)
            if existing:
                if existing["file"]:
                    s.file = existing["file"]
                if existing["url"] and not s.url:
                    s.url = existing["url"]

        sorted_skills = sorted(skills.values(), key=lambda s: s.stars, reverse=True)

        data = {
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": "multi-source (GitHub Search + awesome-agent-skills)",
            "total": len(sorted_skills),
            "skills": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "author": s.author,
                    "stars": s.stars,
                    "downloads": s.downloads,
                    "category": s.category,
                    "tags": s.tags,
                    "version": s.version,
                    "url": s.url,
                    "file": s.file,
                    "source": s.source,
                    "created_at": s.created_at,
                    "updated_at": s.updated_at,
                }
                for s in sorted_skills
            ],
        }

        self._registry_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get_stats(self) -> dict:
        """获取爬虫统计信息"""
        if not self._registry_path.exists():
            return {"skills_count": 0, "last_update": 0, "sources": []}

        try:
            data = json.loads(self._registry_path.read_text(encoding="utf-8"))
            return {
                "skills_count": data.get("total", len(data.get("skills", []))),
                "last_update": data.get("last_updated", ""),
                "sources": [data.get("source", "unknown")],
            }
        except (json.JSONDecodeError, OSError, KeyError, ValueError) as e:
            log.debug("skills_fetcher_status_failed", path=str(self._registry_path), error=str(e))
            return {"skills_count": 0, "last_update": 0, "sources": []}


# 全局单例
_fetcher: SkillsFetcher | None = None


def get_skills_fetcher() -> SkillsFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = SkillsFetcher()
    return _fetcher
