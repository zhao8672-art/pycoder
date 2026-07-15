"""
Skills 市场管理器 — 社区技能的发现、安装、更新、排行

功能:
- 从远程注册表同步最新的技能列表（每日自动更新）
- 按 ⭐ 星数 / 下载量 / 更新时间 排序浏览
- 一键安装技能到本地 .skills/ 目录
- 检测已安装技能的版本更新
- 离线模式下使用本地缓存的注册表

架构:
    远程注册表 (GitHub Raw JSON)
        ↓ 每日自动拉取
    本地缓存 (.skills-registry.json)
        ↓
    MCP Tool: skills_market [list|install|update|search|publish]
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from pycoder.server.log import log

REMOTE_REGISTRY_URL = (
    "https://raw.githubusercontent.com/zhao8672-art/pycoder-skills/main/registry.json"
)
LOCAL_REGISTRY_PATH = Path.home() / ".pycoder" / "skills_registry.json"
UPDATE_INTERVAL_SECONDS = 43200  # 24 小时


def _validate_url(url: str) -> str:
    """验证 URL 协议仅允许 http/https"""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"不允许的 URL 协议: {parsed.scheme}")
    return url


@dataclass
class SkillEntry:
    """注册表中的单个技能条目"""

    id: str
    name: str
    description: str = ""
    author: str = ""
    stars: int = 0
    downloads: int = 0
    category: str = "other"
    tags: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    file: str | None = None  # 本地文件路径（相对项目根）
    url: str | None = None  # 远程下载 URL
    created_at: str = ""
    updated_at: str = ""
    # ── 新增商店字段 ──
    rating: float = 0.0  # 评分 1-5
    ratings_count: int = 0  # 评分人数
    reviews: list[dict] = field(default_factory=list)  # 评论
    publisher: str = ""  # 发布者
    installs: int = 0  # 安装次数
    verified: bool = False  # 官方认证

    @classmethod
    def from_dict(cls, d: dict) -> SkillEntry:
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            description=d.get("description", ""),
            author=d.get("author", ""),
            stars=d.get("stars", 0),
            downloads=d.get("downloads", 0),
            category=d.get("category", "other"),
            tags=d.get("tags", []),
            version=d.get("version", "1.0.0"),
            file=d.get("file"),
            url=d.get("url"),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            rating=d.get("rating", 0.0),
            ratings_count=d.get("ratings_count", 0),
            reviews=d.get("reviews", []),
            publisher=d.get("publisher", ""),
            installs=d.get("installs", 0),
            verified=d.get("verified", False),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "stars": self.stars,
            "downloads": self.downloads,
            "category": self.category,
            "tags": self.tags,
            "version": self.version,
            "file": self.file,
            "url": self.url,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "rating": self.rating,
            "ratings_count": self.ratings_count,
            "reviews": self.reviews,
            "publisher": self.publisher,
            "installs": self.installs,
            "verified": self.verified,
        }


class SkillsMarketManager:
    """Skills 市场管理器 — 单例"""

    def __init__(self):
        self._registry: dict[str, SkillEntry] = {}
        self._last_sync: float = 0.0
        self._loaded = False

    def _load_local(self, force: bool = False):
        """加载本地缓存注册表。force=True 时强制重新加载。"""
        if self._loaded and not force:
            return

        registry_files = [
            Path(os.getcwd()) / ".skills-registry.json",
            LOCAL_REGISTRY_PATH,
        ]
        for rf in registry_files:
            if rf.exists():
                try:
                    data = json.loads(rf.read_text(encoding="utf-8"))
                    for s in data.get("skills", []):
                        entry = SkillEntry.from_dict(s)
                        self._registry[entry.id] = entry
                    self._last_sync = time.time()
                    log.info("skills_registry_loaded", source=str(rf), count=len(self._registry))
                    self._loaded = True
                    return
                except Exception as e:
                    log.warning("skills_registry_load_error", file=str(rf), error=str(e))

        self._loaded = True

    async def sync_from_remote(self) -> dict:
        """从远程拉取最新注册表（不覆盖本地安装的 skill）"""
        try:
            import urllib.request

            # 强制重新加载本地注册表，并重置缓存标志
            self._load_local(force=True)

            _validate_url(REMOTE_REGISTRY_URL)
            req = urllib.request.Request(
                REMOTE_REGISTRY_URL,
                headers={"User-Agent": "PyCoder-Skills/1.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            # 更新注册表
            new_count = 0
            updated_count = 0
            for s in data.get("skills", []):
                entry = SkillEntry.from_dict(s)
                existing = self._registry.get(entry.id)
                if existing:
                    if entry.version != existing.version:
                        self._registry[entry.id] = entry
                        updated_count += 1
                else:
                    self._registry[entry.id] = entry
                    new_count += 1

            # 保存到本地缓存
            self._save_local(data)
            self._last_sync = time.time()

            return {
                "success": True,
                "total": len(self._registry),
                "new": new_count,
                "updated": updated_count,
                "last_sync": self._last_sync,
            }
        except Exception as e:
            log.warning("skills_sync_failed", error=str(e))
            return {"success": False, "error": str(e), "fallback": "使用本地缓存"}

    def _save_local(self, data: dict | None = None):
        """保存注册表到本地缓存"""
        if data is None:
            data = {
                "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "skills": [s.to_dict() for s in self._registry.values()],
            }
        LOCAL_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(data, ensure_ascii=False, indent=2)
        LOCAL_REGISTRY_PATH.write_text(text, encoding="utf-8")

    def list_skills(
        self,
        sort_by: str = "stars",
        category: str = "",
        search: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """
        列出注册表中的技能，支持分页。

        Args:
            sort_by: stars / downloads / name / updated
            category: 分类过滤
            search: 名称/描述/标签模糊搜索
            limit: 每页数量
            offset: 偏移量

        Returns:
            dict: {"skills": [...], "total": int, "has_more": bool}
        """
        self._load_local()

        skills = list(self._registry.values())

        if category:
            skills = [s for s in skills if s.category == category]

        if search:
            q = search.lower()
            skills = [
                s
                for s in skills
                if q in s.name.lower()
                or q in s.description.lower()
                or any(q in t.lower() for t in s.tags)
            ]

        skills.sort(
            key=lambda s: (
                getattr(s, sort_by, s.stars) if sort_by in ("stars", "downloads") else s.name
            ),
            reverse=sort_by in ("stars", "downloads"),
        )

        total = len(skills)
        paginated = skills[offset : offset + limit]

        return {
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
                    "installed": self._is_installed(s),
                    "has_update": self._has_update(s),
                    "rating": s.rating,
                    "ratings_count": s.ratings_count,
                    "publisher": s.publisher,
                    "verified": s.verified,
                }
                for s in paginated
            ],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < total,
        }

    def install_skill(self, skill_id: str) -> dict:
        """安装技能到本地 .skills/ 目录"""
        self._load_local()

        entry = self._registry.get(skill_id)
        if not entry:
            return {"success": False, "error": f"技能 '{skill_id}' 不存在"}

        target_dir = Path(os.getcwd()) / ".skills"
        target_dir.mkdir(parents=True, exist_ok=True)

        # 如果有本地 file 路径，直接复制
        if entry.file:
            src = Path(os.getcwd()) / entry.file
            if src.exists():
                dest = target_dir / src.name
                dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                return {
                    "success": True,
                    "skill_id": skill_id,
                    "name": entry.name,
                    "file": str(dest),
                    "method": "local_copy",
                }
            return {"success": False, "error": f"源文件不存在: {entry.file}"}

        # 如果有远程 URL，尝试下载
        if entry.url:
            try:
                import urllib.request

                # 如果是 GitHub 仓库 URL, 尝试获取 raw 内容
                gh_match = __import__("re").match(r"https://github\.com/([^/]+)/([^/]+)", entry.url)
                if gh_match:
                    owner, repo = gh_match.group(1), gh_match.group(2)
                    raw_urls = [
                        f"https://raw.githubusercontent.com/{owner}/{repo}/main/SKILL.md",
                        f"https://raw.githubusercontent.com/{owner}/{repo}/main/skill.md",
                        f"https://raw.githubusercontent.com/{owner}/{repo}/main/README.md",
                    ]
                    for raw_url in raw_urls:
                        try:
                            _validate_url(raw_url)
                            req = urllib.request.Request(
                                raw_url,
                                headers={"User-Agent": "PyCoder-Skills/1.0"},
                            )
                            with urllib.request.urlopen(req, timeout=10) as resp:
                                content = resp.read().decode()
                            dest = target_dir / f"{skill_id}.md"
                            dest.write_text(content, encoding="utf-8")
                            return {
                                "success": True,
                                "skill_id": skill_id,
                                "name": entry.name,
                                "file": str(dest),
                                "method": "github_raw",
                            }
                        except (OSError, UnicodeDecodeError, ValueError) as e:
                            log.debug("skills_github_raw_failed", url=raw_url, error=str(e))
                            continue

                _validate_url(entry.url)
                req = urllib.request.Request(
                    entry.url,
                    headers={"User-Agent": "PyCoder-Skills/1.0"},
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    content = resp.read().decode()
                dest = target_dir / f"{skill_id}.md"
                dest.write_text(content, encoding="utf-8")
                entry.file = str(dest.relative_to(os.getcwd()))
                return {
                    "success": True,
                    "skill_id": skill_id,
                    "name": entry.name,
                    "file": str(dest),
                    "method": "remote_download",
                }
            except (OSError, UnicodeDecodeError, ValueError) as e:
                log.debug(
                    "skills_remote_download_failed", url=entry.url, error=str(e)
                )  # 下载失败 -> 降级到描述生成

        # 降级: 先尝试从 GitHub README 抓取
        if entry.url:
            import re as _re

            gh_match = _re.search(r"github\.com/([^/]+/[^/]+)", entry.url)
            if gh_match:
                repo_path = gh_match.group(1)
                for branch in ["main", "master"]:
                    readme_url = f"https://raw.githubusercontent.com/{repo_path}/{branch}/README.md"
                    try:
                        import urllib.request

                        _validate_url(readme_url)
                        req = urllib.request.Request(
                            readme_url, headers={"User-Agent": "PyCoder-Skills/1.0"}
                        )
                        import urllib.error

                        try:
                            with urllib.request.urlopen(req, timeout=5) as resp:
                                content = resp.read().decode("utf-8")
                                dest = target_dir / f"{skill_id}.md"
                                dest.write_text(content, encoding="utf-8")
                                return {
                                    "success": True,
                                    "skill_id": skill_id,
                                    "name": entry.name,
                                    "file": str(dest),
                                    "method": "readme_fallback",
                                }
                        except urllib.error.HTTPError:
                            continue
                    except (OSError, UnicodeDecodeError, ValueError) as e:
                        log.debug("skills_readme_fallback_failed", url=readme_url, error=str(e))
                        continue

        # 降级: 根据描述自动生成包含完整元数据的 skill 文件
        if entry.name and entry.description:
            text = (
                f"# {entry.name}\n\n"
                f"{entry.description}\n\n"
                f"## 技能信息\n\n"
                f"- **作者**: {entry.author or '未知'}\n"
                f"- **版本**: {entry.version}\n"
                f"- **分类**: {entry.category}\n"
                f"- **标签**: {', '.join(entry.tags) if entry.tags else '无'}\n"
                f"- **来源**: {entry.url or '本地'}\n"
                f"\n---\n\n"
                f"> Auto-generated by PyCoder Skills Market\n"
                f"> Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            )
            dest = target_dir / f"{skill_id}.md"
            dest.write_text(text, encoding="utf-8")
            return {
                "success": True,
                "skill_id": skill_id,
                "name": entry.name,
                "file": str(dest),
                "method": "auto_generated",
            }

        return {"success": False, "error": "该技能无可下载的文件"}

    def get_categories(self) -> list[dict]:
        """获取所有分类及其技能数"""
        self._load_local()
        cat_counts: dict[str, int] = {}
        for s in self._registry.values():
            cat_counts[s.category] = cat_counts.get(s.category, 0) + 1
        return [{"name": cat, "count": count} for cat, count in sorted(cat_counts.items())]

    def uninstall_skill(self, skill_id: str) -> dict:
        """卸载已安装的技能"""
        self._load_local()
        target_dir = Path(os.getcwd()) / ".skills"
        local_file = target_dir / f"{skill_id}.md"
        if local_file.exists():
            local_file.unlink()
            return {"success": True, "skill_id": skill_id, "action": "uninstalled"}
        return {"success": False, "error": f"技能 '{skill_id}' 未安装"}

    def update_all_skills(self) -> dict:
        """更新所有已安装的技能到最新版本"""
        self._load_local()
        updated = []
        failed = []
        for skill_id, entry in self._registry.items():
            if self._is_installed(entry) and self._has_update(entry):
                result = self.install_skill(skill_id)
                if result.get("success"):
                    updated.append(skill_id)
                else:
                    failed.append({"id": skill_id, "error": result.get("error", "?")})
        return {"success": True, "updated": updated, "failed": failed, "total": len(updated)}

    def rate_skill(self, skill_id: str, rating: int, review: str = "") -> dict:
        """评分技能"""
        self._load_local()
        entry = self._registry.get(skill_id)
        if not entry:
            return {"success": False, "error": f"技能 '{skill_id}' 不存在"}
        if rating < 1 or rating > 5:
            return {"success": False, "error": "评分必须在 1-5 之间"}
        # 更新本地注册表评分
        total = entry.rating * entry.ratings_count + rating
        entry.ratings_count += 1
        entry.rating = round(total / entry.ratings_count, 1)
        if review:
            entry.reviews.append(
                {
                    "user": "local",
                    "rating": rating,
                    "review": review,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            )
        self._save_local()
        return {
            "success": True,
            "skill_id": skill_id,
            "new_rating": entry.rating,
            "ratings_count": entry.ratings_count,
        }

    def get_skill_detail(self, skill_id: str) -> dict:
        """获取技能详情（含评论）"""
        self._load_local()
        entry = self._registry.get(skill_id)
        if not entry:
            return {"error": f"技能 '{skill_id}' 不存在"}
        base = self.list_skills(search=skill_id, limit=1)
        # Bug fix: list_skills 返回 dict 而非 list，原 base[0] 会抛 KeyError
        skills_list = base.get("skills", []) if isinstance(base, dict) else []
        detail = skills_list[0] if skills_list else {}
        detail["rating"] = entry.rating
        detail["ratings_count"] = entry.ratings_count
        detail["reviews"] = entry.reviews[-10:]  # 最近 10 条
        detail["publisher"] = entry.publisher
        detail["verified"] = entry.verified
        detail["installs"] = entry.installs
        detail["created_at"] = entry.created_at
        detail["updated_at"] = entry.updated_at
        return {"skill": detail}

    def publish_skill(self, skill_data: dict) -> dict:
        """发布新技能（保存到本地注册表）"""
        self._load_local()
        entry = SkillEntry.from_dict(skill_data)
        entry.installs = 0
        entry.rating = 0.0
        entry.ratings_count = 0
        if entry.id in self._registry:
            return {"success": False, "error": f"技能 ID '{entry.id}' 已存在"}
        self._registry[entry.id] = entry
        self._save_local()
        return {"success": True, "skill_id": entry.id, "name": entry.name}

    def _is_installed(self, entry: SkillEntry) -> bool:
        """检查技能是否已安装"""
        if entry.file:
            return (Path(os.getcwd()) / entry.file).exists()
        local_file = Path(os.getcwd()) / ".skills" / f"{entry.id}.md"
        return local_file.exists()

    @staticmethod
    def _compare_versions(v1: str, v2: str) -> int:
        """语义化版本号比较。v1 < v2 返回 -1, v1 == v2 返回 0, v1 > v2 返回 1。"""
        parts1 = [int(p) for p in v1.split(".") if p.isdigit()]
        parts2 = [int(p) for p in v2.split(".") if p.isdigit()]
        for p1, p2 in zip(parts1, parts2, strict=False):
            if p1 < p2:
                return -1
            if p1 > p2:
                return 1
        return len(parts1) - len(parts2)

    def _has_update(self, entry: SkillEntry) -> bool:
        """检查技能是否有更新（使用语义化版本号比较）"""
        if not self._is_installed(entry):
            return False
        local_file = (
            Path(os.getcwd()) / entry.file
            if entry.file
            else Path(os.getcwd()) / ".skills" / f"{entry.id}.md"
        )
        if local_file.exists():
            try:
                content = local_file.read_text(encoding="utf-8")
                import re

                # 尝试从文件中提取已安装的版本号
                match = re.search(r"version[\s:]+([\d.]+)", content, re.IGNORECASE)
                if match:
                    local_version = match.group(1)
                    return self._compare_versions(local_version, entry.version) < 0
            except (OSError, UnicodeDecodeError, PermissionError, re.error) as e:
                log.debug("skills_has_update_read_failed", path=str(local_file), error=str(e))
        return False


# 全局单例
_manager: SkillsMarketManager | None = None


def get_skills_market() -> SkillsMarketManager:
    global _manager
    if _manager is None:
        _manager = SkillsMarketManager()
    return _manager
