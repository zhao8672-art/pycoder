"""
Skills 市场升级版 - 支持多个开源数据源
新增开源数据源:
1. Awesome Claude Skills (GitHub) - 精选 Claude Skills
2. GitHub Claude Skills Topic - Claude Skills
3. GitHub Agent Skills Topic - Agent Skills
4. Hugging Face Spaces - ML/AI Skills
5. Awesome Agent Architecture - Agent 框架 Skills
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from pycoder.server.log import log


def _validate_url(url: str) -> str:
    """验证 URL 协议仅允许 http/https"""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"不允许的 URL 协议: {parsed.scheme}")
    return url


@dataclass
class EnhancedSkill:
    """增强的技能数据模型"""

    id: str
    name: str
    description: str = ""
    author: str = ""
    repository_url: str = ""
    # 评分指标
    stars: int = 0
    forks: int = 0
    watchers: int = 0
    issues: int = 0
    # 社区指标
    downloads: int = 0
    installs: int = 0
    rating: float = 0.0
    ratings_count: int = 0
    # 分类
    category: str = "other"
    tags: list[str] = field(default_factory=list)
    # 版本管理
    version: str = "1.0.0"
    latest_version: str = "1.0.0"
    # 文件路径
    file: str | None = None
    url: str = ""
    # 时间戳
    created_at: str = ""
    updated_at: str = ""
    pushed_at: str = ""
    # 额外信息
    readme_url: str = ""
    license: str = ""
    language: str = "Python"
    topics: list[str] = field(default_factory=list)
    source: str = ""  # 数据源标识
    verified: bool = False
    official: bool = False
    archived: bool = False

    def quality_score(self) -> float:
        """计算技能质量分数 (0-100)"""
        score = 0.0
        # Stars权重: 30%
        score += min(100, (self.stars / 100)) * 0.3
        # 下载量权重: 25%
        score += min(100, (self.downloads / 1000)) * 0.25
        # 评分权重: 25%
        score += (self.rating / 5) * 25
        # 官方认证权重: 20%
        if self.verified:
            score += 10
        if self.official:
            score += 10
        return min(100, score)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "repository_url": self.repository_url,
            "stars": self.stars,
            "forks": self.forks,
            "downloads": self.downloads,
            "category": self.category,
            "tags": self.tags,
            "version": self.version,
            "file": self.file,
            "url": self.url,
            "rating": self.rating,
            "ratings_count": self.ratings_count,
            "quality_score": self.quality_score(),
            "source": self.source,
            "verified": self.verified,
            "official": self.official,
        }


class EnhancedSkillsFetcher:
    """增强的多源 Skills 爬虫"""

    # 开源数据源配置
    SOURCES = {
        "github_awesome_claude": {
            "name": "Awesome Claude Skills",
            "description": "精选 Claude Skills 列表 (GitHub)",
            "url": "https://api.github.com/repos/secondstate/awesome-claude-skills/contents/",
            "type": "github_list",
        },
        "github_topic_claude_skills": {
            "name": "GitHub Claude Skills Topic",
            "description": "GitHub 上所有标记为 'claude-skills' 的项目",
            "url": (
                "https://api.github.com/search/repositories"
                "?q=topic:claude-skills&sort=stars&order=desc&per_page=100"
            ),
            "type": "github_search",
        },
        "github_topic_agent_skills": {
            "name": "GitHub Agent Skills Topic",
            "description": "GitHub 上所有标记为 'agent-skills' 的项目",
            "url": (
                "https://api.github.com/search/repositories"
                "?q=topic:agent-skills&sort=stars&order=desc&per_page=100"
            ),
            "type": "github_search",
        },
        "github_awesome_agents": {
            "name": "Awesome Agent Skills",
            "description": "精选 Agent 框架和 Skills",
            "url": "https://raw.githubusercontent.com/e2b-dev/awesome-ai-agents/main/README.md",
            "type": "markdown_list",
        },
        "huggingface_spaces": {
            "name": "Hugging Face Spaces",
            "description": "HF 上的 AI Skills (通过 API)",
            "url": "https://huggingface.co/api/spaces?sort=likes&limit=100",
            "type": "huggingface",
        },
        # ── 新增在线数据源（2026-07） ──
        "github_trending_python": {
            "name": "GitHub Trending Python",
            "description": "GitHub 热门 Python 项目（stars:>500, 近期活跃）",
            "url": (
                "https://api.github.com/search/repositories"
                "?q=language:python+stars:>500+pushed:>2025-01-01"
                "&sort=stars&order=desc&per_page=50"
            ),
            "type": "github_search",
        },
        "github_mcp_servers": {
            "name": "GitHub MCP Servers",
            "description": "GitHub 上的 MCP Server 项目",
            "url": (
                "https://api.github.com/search/repositories"
                "?q=topic:mcp-server+stars:>10&sort=stars&order=desc&per_page=50"
            ),
            "type": "github_search",
        },
        "github_awesome_prompts": {
            "name": "GitHub Awesome Prompts",
            "description": "精选 Prompt 工程和 AI 提示词资源",
            "url": "https://raw.githubusercontent.com/f/awesome-chatgpt-prompts/main/README.md",
            "type": "markdown_list",
        },
        # ── 新增高价值数据源（2026-07-10） ──
        "github_awesome_mcp": {
            "name": "Awesome MCP Servers",
            "description": "精选 MCP Server 列表（模型上下文协议）",
            "url": "https://raw.githubusercontent.com/punkpeye/awesome-mcp-servers/main/README.md",
            "type": "markdown_list",
        },
        "github_awesome_code_assistants": {
            "name": "Awesome Code Assistants",
            "description": "精选 AI 代码助手和编码 Agent",
            "url": "https://raw.githubusercontent.com/ricklamers/awesome-ai-code-assistants/main/README.md",
            "type": "markdown_list",
        },
        "github_topic_ai_agent": {
            "name": "GitHub AI Agent Topic",
            "description": "GitHub 上标记为 'ai-agent' 的热门项目",
            "url": (
                "https://api.github.com/search/repositories"
                "?q=topic:ai-agent+stars:>100&sort=stars&order=desc&per_page=50"
            ),
            "type": "github_search",
        },
        "github_topic_code-assistant": {
            "name": "GitHub Code Assistant Topic",
            "description": "GitHub 上标记为 'code-assistant' 的项目",
            "url": (
                "https://api.github.com/search/repositories"
                "?q=topic:code-assistant+stars:>20&sort=stars&order=desc&per_page=50"
            ),
            "type": "github_search",
        },
    }

    # 种子数据 — 远程源全部失败时的兜底
    SEED_SKILLS: list[dict] = [
        {
            "id": "seed_code_review",
            "name": "Code Review Assistant",
            "description": "AI 代码审查：自动检测 bug、安全漏洞、代码异味",
            "author": "PyCoder Team",
            "category": "code-quality",
            "tags": ["review", "quality", "security"],
            "stars": 50,
            "downloads": 100,
            "rating": 4.5,
            "source": "seed",
            "verified": True,
            "official": True,
        },
        {
            "id": "seed_test_generator",
            "name": "Test Generator",
            "description": "自动生成单元测试，覆盖边界条件和异常路径",
            "author": "PyCoder Team",
            "category": "code-quality",
            "tags": ["testing", "pytest", "automation"],
            "stars": 45,
            "downloads": 90,
            "rating": 4.3,
            "source": "seed",
            "verified": True,
            "official": True,
        },
        {
            "id": "seed_refactor_advisor",
            "name": "Refactor Advisor",
            "description": "代码重构建议：提取方法、简化条件、消除重复",
            "author": "PyCoder Team",
            "category": "code-quality",
            "tags": ["refactor", "clean-code"],
            "stars": 40,
            "downloads": 80,
            "rating": 4.2,
            "source": "seed",
            "verified": True,
            "official": True,
        },
        {
            "id": "seed_doc_generator",
            "name": "Documentation Generator",
            "description": "自动生成文档字符串、API 文档、README",
            "author": "PyCoder Team",
            "category": "productivity",
            "tags": ["docs", "docstring", "readme"],
            "stars": 42,
            "downloads": 85,
            "rating": 4.4,
            "source": "seed",
            "verified": True,
            "official": True,
        },
        {
            "id": "seed_security_scanner",
            "name": "Security Scanner",
            "description": "安全漏洞扫描：SQL 注入、XSS、命令注入、硬编码密钥",
            "author": "PyCoder Team",
            "category": "security",
            "tags": ["security", "owasp", "vulnerability"],
            "stars": 55,
            "downloads": 110,
            "rating": 4.6,
            "source": "seed",
            "verified": True,
            "official": True,
        },
        {
            "id": "seed_perf_optimizer",
            "name": "Performance Optimizer",
            "description": "性能分析优化：识别瓶颈、建议优化、内存泄漏检测",
            "author": "PyCoder Team",
            "category": "code-quality",
            "tags": ["performance", "profiling", "optimization"],
            "stars": 38,
            "downloads": 70,
            "rating": 4.1,
            "source": "seed",
            "verified": True,
            "official": True,
        },
        {
            "id": "seed_git_assistant",
            "name": "Git Assistant",
            "description": "Git 操作助手：智能 commit、分支管理、冲突解决",
            "author": "PyCoder Team",
            "category": "productivity",
            "tags": ["git", "vcs", "commit"],
            "stars": 48,
            "downloads": 95,
            "rating": 4.4,
            "source": "seed",
            "verified": True,
            "official": True,
        },
        {
            "id": "seed_api_designer",
            "name": "API Designer",
            "description": "REST API 设计助手：路由规划、参数校验、OpenAPI 生成",
            "author": "PyCoder Team",
            "category": "web",
            "tags": ["api", "rest", "openapi"],
            "stars": 35,
            "downloads": 65,
            "rating": 4.0,
            "source": "seed",
            "verified": True,
            "official": True,
        },
        {
            "id": "seed_db_migrator",
            "name": "Database Migrator",
            "description": "数据库迁移助手：Schema 变更、数据迁移、索引优化",
            "author": "PyCoder Team",
            "category": "database",
            "tags": ["database", "migration", "sql"],
            "stars": 30,
            "downloads": 60,
            "rating": 3.9,
            "source": "seed",
            "verified": True,
            "official": True,
        },
        {
            "id": "seed_docker_helper",
            "name": "Docker Helper",
            "description": "Docker 容器化助手：Dockerfile 生成、镜像优化、compose 配置",
            "author": "PyCoder Team",
            "category": "devops",
            "tags": ["docker", "container", "devops"],
            "stars": 36,
            "downloads": 72,
            "rating": 4.1,
            "source": "seed",
            "verified": True,
            "official": True,
        },
    ]

    def __init__(self):
        self._registry_path = Path(os.getcwd()) / ".skills-registry-enhanced.json"
        self._cache: dict[str, EnhancedSkill] = {}
        self._last_sync_time: float = 0.0
        self._sync_interval: float = 86400.0  # 默认 24 小时
        self._auto_sync_task: asyncio.Task | None = None

    async def fetch_all(self) -> dict:
        """从所有数据源拉取"""
        import asyncio

        all_skills: dict[str, EnhancedSkill] = {}
        sources_status = []

        for source_id, config in self.SOURCES.items():
            try:
                # 根据类型处理
                if config["type"] == "github_search":
                    skills = await asyncio.to_thread(
                        self._fetch_github_search, config["url"], source_id
                    )
                elif config["type"] == "github_list":
                    skills = await asyncio.to_thread(
                        self._fetch_github_list, config["url"], source_id
                    )
                elif config["type"] == "huggingface":
                    skills = await asyncio.to_thread(
                        self._fetch_huggingface, config["url"], source_id
                    )
                elif config["type"] == "markdown_list":
                    skills = await asyncio.to_thread(
                        self._parse_markdown_list_from_url, config["url"], source_id
                    )
                else:
                    skills = []

                # 合并
                for skill in skills:
                    key = skill.id
                    existing = all_skills.get(key)
                    if not existing or skill.quality_score() > existing.quality_score():
                        all_skills[key] = skill

                sources_status.append(
                    {
                        "source": source_id,
                        "name": config["name"],
                        "success": True,
                        "count": len(skills),
                    }
                )
                log.info("skills_source_fetched", source=source_id, count=len(skills))

            except (OSError, ValueError, KeyError, RuntimeError, TimeoutError) as e:
                sources_status.append(
                    {
                        "source": source_id,
                        "name": config["name"],
                        "success": False,
                        "error": str(e)[:80],
                    }
                )
                log.warning("skills_source_failed", source=source_id, error=str(e)[:80])

        # 种子兜底 — 如果远程源全部失败或数据过少，注入种子数据
        if len(all_skills) < 10:
            for seed in self.SEED_SKILLS:
                sid = seed["id"]
                if sid not in all_skills:
                    all_skills[sid] = EnhancedSkill(**seed)
            sources_status.append(
                {
                    "source": "seed_fallback",
                    "name": "Seed Fallback",
                    "success": True,
                    "count": len(self.SEED_SKILLS),
                }
            )
            log.info("skills_seed_fallback_injected", count=len(self.SEED_SKILLS))

        # 保存
        self._save_registry(all_skills)
        self._cache = all_skills

        return {
            "success": True,
            "total_skills": len(all_skills),
            "sources": sources_status,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def _fetch_github_search(self, url: str, source_id: str) -> list[EnhancedSkill]:
        """从 GitHub Search API 拉取"""
        import urllib.request

        _validate_url(url)
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "PyCoder-Skills-Bot/2.0",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        skills = []
        for item in data.get("items", []):
            skill = EnhancedSkill(
                id=item.get("name", "").lower().replace("-", "_"),
                name=item.get("name", "").replace("-", " ").title(),
                description=(item.get("description") or "")[:300],
                author=item.get("full_name", "").split("/")[0],
                repository_url=item.get("html_url", ""),
                stars=item.get("stargazers_count", 0),
                forks=item.get("forks_count", 0),
                watchers=item.get("watchers_count", 0),
                downloads=max(item.get("forks_count", 0), 1),
                created_at=item.get("created_at", ""),
                updated_at=item.get("updated_at", ""),
                pushed_at=item.get("pushed_at", ""),
                topics=item.get("topics", [])[:5],
                language=item.get("language", "Unknown"),
                source=source_id,
                archived=item.get("archived", False),
            )
            # 分类推断
            skill.category = self._infer_category(skill.name, skill.description)
            skills.append(skill)

        return skills

    def _fetch_github_list(self, url: str, source_id: str) -> list[EnhancedSkill]:
        """从 GitHub 仓库列表拉取（仓库目录/README 解析）"""
        import urllib.request

        skills = []
        try:
            _validate_url(url)
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "PyCoder-Skills-Bot/2.0",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            # GitHub Contents API 返回列表 [{name, type, download_url, ...}]
            if isinstance(data, list):
                # 查找 README.md
                readme_item = next(
                    (item for item in data if item.get("name", "").upper() == "README.md"),
                    None,
                )
                if readme_item and readme_item.get("download_url"):
                    readme_url = readme_item["download_url"]
                    skills = self._parse_markdown_list(readme_url, source_id, "awesome-claude")

                # 同时提取子目录作为独立 skill
                dirs = [item for item in data if item.get("type") == "dir"]
                for d in dirs[:30]:
                    dir_name = d.get("name", "")
                    skill = EnhancedSkill(
                        id=f"{source_id}_{dir_name.lower().replace('-', '_')}",
                        name=dir_name.replace("-", " ").title(),
                        description=f"来自 awesome-claude-skills 列表: {dir_name}",
                        repository_url=d.get(
                            "html_url",
                            f"https://github.com/secondstate/awesome-claude-skills/tree/main/{dir_name}",
                        ),
                        stars=10,
                        downloads=5,
                        source=source_id,
                        category=self._infer_category(dir_name, ""),
                    )
                    skills.append(skill)

        except (OSError, ValueError, KeyError, RuntimeError, TypeError) as e:
            log.warning("github_list_fetch_failed", source=source_id, error=str(e)[:80])

        return skills

    def _parse_markdown_list(
        self, readme_url: str, source_id: str, category_hint: str
    ) -> list[EnhancedSkill]:
        """从 GitHub Awesome List 的 README.md 中提取项目链接"""
        import re
        import urllib.request

        skills = []
        try:
            _validate_url(readme_url)
            req = urllib.request.Request(
                readme_url,
                headers={"User-Agent": "PyCoder-Skills-Bot/2.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode("utf-8", errors="replace")

            # 提取 Markdown 链接: [name](url) - description
            link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)\s*[-–—]\s*([^\n]+)")
            for match in link_pattern.finditer(content):
                name = match.group(1).strip()
                url = match.group(2).strip()
                desc = match.group(3).strip()[:200]
                if not url.startswith("http"):
                    continue
                skill_id = re.sub(r"[^a-z0-9_]", "_", name.lower())[:50]
                if not skill_id:
                    continue
                # 去重
                if skill_id in [s.id for s in skills]:
                    continue
                skill = EnhancedSkill(
                    id=f"{source_id}_{skill_id}",
                    name=name,
                    description=desc,
                    repository_url=url,
                    url=url,
                    stars=5,
                    downloads=1,
                    source=source_id,
                    category=self._infer_category(name, desc) or category_hint,
                )
                skills.append(skill)

        except (OSError, ValueError, KeyError, RuntimeError, TypeError) as e:
            log.warning("markdown_list_parse_failed", source=source_id, error=str(e)[:80])

        return skills

    def _parse_markdown_list_from_url(self, url: str, source_id: str) -> list[EnhancedSkill]:
        """从远程 URL 读取 Markdown 并提取链接列表"""
        import urllib.request

        try:
            _validate_url(url)
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "PyCoder-Skills-Bot/2.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode("utf-8", errors="replace")
            return self._parse_markdown_content(content, url, source_id)
        except (OSError, ValueError, KeyError, RuntimeError, TypeError) as e:
            log.warning("markdown_url_fetch_failed", source=source_id, error=str(e)[:80])
            return []

    def _parse_markdown_content(
        self, content: str, source_url: str, source_id: str
    ) -> list[EnhancedSkill]:
        """从 Markdown 内容中提取项目链接"""
        import re

        skills, seen = [], set()
        # 匹配 [name](url) - description 和 - [name](url) 格式
        patterns = [
            re.compile(r"\[([^\]]+)\]\(([^)]+)\)\s*[-–—]\s*([^\n]+)"),
            re.compile(r"[-*]\s+\[([^\]]+)\]\(([^)]+)\)"),
        ]
        for pattern in patterns:
            for match in pattern.finditer(content):
                name = match.group(1).strip()
                url = match.group(2).strip()
                desc = match.group(3).strip()[:200] if match.lastindex >= 3 else ""
                if not url.startswith("http"):
                    continue
                skill_id = re.sub(r"[^a-z0-9_]", "_", name.lower())[:50]
                if not skill_id or skill_id in seen:
                    continue
                seen.add(skill_id)
                skill = EnhancedSkill(
                    id=f"{source_id}_{skill_id}",
                    name=name,
                    description=desc,
                    repository_url=url,
                    url=url,
                    stars=5,
                    downloads=1,
                    source=source_id,
                    category=self._infer_category(name, desc) or "other",
                )
                skills.append(skill)
        return skills[:100]

    def _fetch_huggingface(self, url: str, source_id: str) -> list[EnhancedSkill]:
        """从 Hugging Face API 拉取"""
        import urllib.request

        _validate_url(url)
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "PyCoder-Skills-Bot/2.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        skills = []
        # HuggingFace API 可能返回列表或字典
        spaces_list = data if isinstance(data, list) else data.get("spaces", [])

        for item in spaces_list:
            if not isinstance(item, dict):
                continue

            # 只选择 Skills 类相关的
            item_id = item.get("id", "")
            item_desc = item.get("description", "")
            if not any(
                kw in (item_id + item_desc).lower()
                for kw in ["skill", "tool", "agent", "extension"]
            ):
                continue

            skill = EnhancedSkill(
                id=item_id.replace("/", "_"),
                name=item_id.split("/")[-1].replace("-", " ").title(),
                description=(item_desc or "")[:300],
                author=item_id.split("/")[0],
                url=f"https://huggingface.co/spaces/{item_id}",
                downloads=item.get("likes", 0),
                rating=min(5.0, item.get("likes", 0) / 100),
                source=source_id,
            )
            skill.category = self._infer_category(skill.name, skill.description)
            skills.append(skill)

        return skills

    @staticmethod
    def _infer_category(name: str, description: str) -> str:
        """推断分类"""
        text = (name + " " + description).lower()
        categories = {
            "security": ["security", "pentest", "red team", "offensive"],
            "code-quality": ["test", "quality", "lint", "analysis"],
            "database": ["database", "postgres", "sql", "redis", "mongodb"],
            "devops": ["deploy", "docker", "k8s", "ci/cd", "kubernetes"],
            "research": ["research", "paper", "ml", "ai", "model"],
            "mobile": ["ios", "android", "mobile", "app"],
            "web": ["web", "frontend", "react", "vue", "api"],
            "creative": ["generate", "image", "video", "audio", "art"],
            "productivity": ["productivity", "pm", "management", "task"],
            "data": ["data", "analytics", "visualization", "dashboard"],
        }
        for category, keywords in categories.items():
            if any(kw in text for kw in keywords):
                return category
        return "other"

    def _save_registry(self, skills: dict[str, EnhancedSkill]):
        """保存注册表"""
        data = {
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total": len(skills),
            "skills": [
                skill.to_dict()
                for skill in sorted(skills.values(), key=lambda s: s.quality_score(), reverse=True)
            ],
        }
        self._registry_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_stats(self) -> dict:
        """获取统计信息"""
        if not self._registry_path.exists():
            return {"skills_count": 0, "categories": {}}

        try:
            data = json.loads(self._registry_path.read_text(encoding="utf-8"))
            # 统计分类
            categories = {}
            for skill in data.get("skills", []):
                cat = skill.get("category", "other")
                categories[cat] = categories.get(cat, 0) + 1

            return {
                "skills_count": data.get("total", 0),
                "categories": categories,
                "last_updated": data.get("last_updated", ""),
            }
        except (json.JSONDecodeError, OSError, KeyError, ValueError, TypeError) as e:
            log.debug("skills_v2_get_stats_failed", path=str(self._registry_path), error=str(e))
            return {"skills_count": 0, "categories": {}}

    async def start_auto_sync(self, interval: float | None = None) -> None:
        """启动定期自动同步后台任务

        Args:
            interval: 同步间隔（秒），默认 24 小时（86400）
        """
        if interval is not None:
            self._sync_interval = max(3600, interval)  # 最少 1 小时

        # 首次立即同步
        await self.fetch_all()
        self._last_sync_time = time.time()

        self._auto_sync_task = asyncio.create_task(self._auto_sync_loop())
        log.info("skills_auto_sync_started", interval_hours=self._sync_interval / 3600)

    async def _auto_sync_loop(self) -> None:
        """后台自动同步循环"""
        while True:
            await asyncio.sleep(self._sync_interval)
            try:
                await self.fetch_all()
                self._last_sync_time = time.time()
                log.info("skills_auto_sync_completed", timestamp=self._last_sync_time)
            except (OSError, ValueError, KeyError, RuntimeError, TimeoutError) as e:
                log.warning("skills_auto_sync_failed", error=str(e)[:80])

    def stop_auto_sync(self) -> None:
        """停止定期自动同步"""
        if self._auto_sync_task and not self._auto_sync_task.done():
            self._auto_sync_task.cancel()
            log.info("skills_auto_sync_stopped")

    def sync_status(self) -> dict:
        """获取同步状态"""
        return {
            "last_sync_time": (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._last_sync_time))
                if self._last_sync_time
                else None
            ),
            "sync_interval_hours": self._sync_interval / 3600,
            "auto_sync_active": self._auto_sync_task is not None
            and not self._auto_sync_task.done(),
            "cached_count": len(self._cache),
        }

    def load_cache(self) -> dict[str, EnhancedSkill]:
        """加载本地缓存"""
        if not self._registry_path.exists():
            return {}

        try:
            data = json.loads(self._registry_path.read_text(encoding="utf-8"))
            skills = {}
            for item in data.get("skills", []):
                skill = EnhancedSkill(**item)
                skills[skill.id] = skill
            self._cache = skills
            return skills
        except (OSError, ValueError, KeyError, RuntimeError, TypeError) as e:
            log.warning("failed_to_load_cache", error=str(e))
            return {}


# 全局单例
_enhanced_fetcher: EnhancedSkillsFetcher | None = None


def get_enhanced_fetcher() -> EnhancedSkillsFetcher:
    """获取全局 Fetcher 实例"""
    global _enhanced_fetcher
    if _enhanced_fetcher is None:
        _enhanced_fetcher = EnhancedSkillsFetcher()
    return _enhanced_fetcher
