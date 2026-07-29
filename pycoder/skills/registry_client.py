"""远程技能 Registry 客户端 — 从远程仓库同步技能到本地

支持的 Registry 协议（HTTP REST）：
- GET /index.json — 返回技能索引列表 [{id, name, version, ...}, ...]
- GET /skills/{id}.json — 返回单个技能详情（含 markdown_content）

特性：
- 异步 HTTP（httpx.AsyncClient）
- ETag 缓存避免重复拉取
- 可配置超时/重试
- 进度回调（用于推送 UI 进度条）

用法:
    from pycoder.skills.registry_client import RegistryClient

    client = RegistryClient("https://registry.pycoder.io")
    skills = await client.fetch_all()
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_URL = "https://registry.pycoder.io"
"""默认 Registry URL（占位，实际可配置）"""

DEFAULT_TIMEOUT = 30.0
"""默认 HTTP 超时（秒）"""

DEFAULT_MAX_RETRIES = 2
"""默认最大重试次数"""

ProgressCallback = Callable[[int, int, str], Awaitable[None]]
"""进度回调类型：(completed, total, step_description)"""


@dataclass
class RegistrySkill:
    """远程技能元数据（最小字段集，与本地 SkillDefinition 对齐）"""

    id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = "PyCoder"
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    publisher: str = ""
    verified: bool = False
    source_url: str = ""
    homepage_url: str = ""
    license: str = ""
    icon_url: str = ""
    stars: int = 0
    markdown_content: str = ""


@dataclass
class SyncResult:
    """同步结果统计"""

    total: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "total": self.total,
            "new": self.new,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "failed": self.failed,
            "errors": self.errors,
        }


class RegistryClient:
    """远程技能 Registry 客户端

    通过 HTTP REST 协议从远程仓库拉取技能索引和详情。
    支持 ETag 缓存、超时重试、进度回调。
    """

    def __init__(
        self,
        registry_url: str = DEFAULT_REGISTRY_URL,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        """初始化 Registry 客户端

        Args:
            registry_url: Registry 根 URL（如 https://registry.pycoder.io）
            timeout: HTTP 请求超时（秒）
            max_retries: 失败重试次数
        """
        self._url = registry_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._etags: dict[str, str] = {}
        """URL -> ETag 缓存"""

    @property
    def registry_url(self) -> str:
        """Registry 根 URL"""
        return self._url

    async def fetch_index(self) -> list[dict[str, Any]]:
        """拉取远程技能索引

        Returns:
            技能元数据列表（不含 markdown_content）
        """
        url = f"{self._url}/index.json"
        data = await self._get_json(url)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "skills" in data:
            return list(data["skills"])
        return []

    async def fetch_skill(self, skill_id: str) -> dict[str, Any]:
        """拉取单个技能详情（含 markdown_content）

        Args:
            skill_id: 技能 ID

        Returns:
            技能详情字典
        """
        url = f"{self._url}/skills/{skill_id}.json"
        data = await self._get_json(url)
        if isinstance(data, dict):
            return data
        return {}

    async def _get_json(self, url: str) -> Any:
        """带 ETag 缓存和重试的 GET 请求

        Args:
            url: 完整 URL

        Returns:
            解析后的 JSON 数据（dict 或 list）

        Raises:
            RuntimeError: 多次重试后仍失败
        """
        headers: dict[str, str] = {}
        etag = self._etags.get(url)
        if etag:
            headers["If-None-Match"] = etag

        last_err: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 304:  # Not Modified
                        logger.debug("Registry 资源未修改（ETag 命中）: %s", url)
                        return {}
                    resp.raise_for_status()
                    # 缓存 ETag
                    new_etag = resp.headers.get("ETag")
                    if new_etag:
                        self._etags[url] = new_etag
                    return resp.json()
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                last_err = e
                logger.warning(
                    "Registry 请求失败 (attempt %d/%d): %s - %s",
                    attempt + 1,
                    self._max_retries + 1,
                    url,
                    e,
                )
                if attempt < self._max_retries:
                    # 指数退避
                    await asyncio.sleep(0.5 * (attempt + 1))

        raise RuntimeError(f"Registry 请求失败: {url} - {last_err}")

    async def fetch_all(self, progress: ProgressCallback | None = None) -> list[RegistrySkill]:
        """拉取索引和所有技能详情

        Args:
            progress: 进度回调 (completed, total, step)

        Returns:
            完整技能列表（含 markdown_content）
        """
        if progress:
            await progress(0, 0, "🔍 拉取远程索引")
        index = await self.fetch_index()
        total = len(index)

        skills: list[RegistrySkill] = []
        for i, item in enumerate(index):
            skill_id = str(item.get("id", ""))
            if not skill_id:
                continue
            if progress:
                await progress(i, total, f"📥 拉取 {skill_id} ({i + 1}/{total})")
            try:
                detail = await self.fetch_skill(skill_id)
                # 合并索引和详情（详情优先）
                merged = {**item, **detail}
                skills.append(self._parse_skill(merged))
            except Exception as e:
                logger.error("拉取技能 %s 失败: %s", skill_id, e)

        if progress:
            await progress(total, total, f"✅ 完成（{len(skills)}/{total}）")
        return skills

    @staticmethod
    def _parse_skill(data: dict[str, Any]) -> RegistrySkill:
        """从字典构造 RegistrySkill"""
        return RegistrySkill(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            version=str(data.get("version", "1.0.0")),
            description=str(data.get("description", "")),
            author=str(data.get("author", "PyCoder")),
            category=str(data.get("category", "general")),
            tags=list(data.get("tags", []) or []),
            dependencies=list(data.get("dependencies", []) or []),
            publisher=str(data.get("publisher", "")),
            verified=bool(data.get("verified", False)),
            source_url=str(data.get("source_url", "")),
            homepage_url=str(data.get("homepage_url", "")),
            license=str(data.get("license", "")),
            icon_url=str(data.get("icon_url", "")),
            stars=int(data.get("stars", 0) or 0),
            markdown_content=str(data.get("markdown_content", "")),
        )
