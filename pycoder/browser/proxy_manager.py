"""代理与缓存管理 — 减少重复网络请求

使用 diskcache（SQLite 后端）持久化缓存，支持 TTL 过期和请求去重。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path


class ProxyCacheManager:
    """浏览器请求缓存管理器

    用法:
        cache = ProxyCacheManager()
        result = await cache.fetch("https://example.com", fetch_fn=my_fetch)
    """

    def __init__(self, cache_dir: Path | None = None):
        cache_dir = cache_dir or (Path.home() / ".pycoder" / "browser_cache")
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_dir = cache_dir
        # 简单文件缓存（不依赖 diskcache）
        self._pending: dict[str, asyncio.Future] = {}

    async def fetch(self, url: str, fetch_fn=None, ttl: int = 3600) -> str:
        """带缓存的 HTTP 请求

        Args:
            url: 请求 URL
            fetch_fn: 实际请求函数 async (url) -> str
            ttl: 缓存有效期（秒）

        Returns:
            响应内容
        """
        cache_key = self._make_key(url)
        cache_file = self._cache_dir / f"{cache_key}.txt"

        # 检查缓存
        if cache_file.exists():
            age = time.time() - cache_file.stat().st_mtime
            if age < ttl:
                return cache_file.read_text(encoding="utf-8")

        # 请求去重
        if cache_key in self._pending:
            return await self._pending[cache_key]

        future = asyncio.get_event_loop().create_future()
        self._pending[cache_key] = future
        try:
            if fetch_fn:
                result = await fetch_fn(url)
            else:
                result = ""
            cache_file.write_text(result, encoding="utf-8")
            future.set_result(result)
            return result
        except Exception as e:
            future.set_exception(e)
            raise
        finally:
            self._pending.pop(cache_key, None)

    @staticmethod
    def _make_key(url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:32]


import time  # noqa: E402