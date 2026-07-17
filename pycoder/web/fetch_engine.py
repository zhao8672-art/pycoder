"""
网页抓取引擎 — Layer 1: httpx 直连 / Layer 2: Playwright 浏览器降级

自动检测目标页面是否需要 JS 渲染，按需降级。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    """抓取结果"""
    url: str
    html: str = ""
    text: str = ""
    status_code: int = 0
    headers: dict = None
    screenshot: bytes | None = None
    error: str = ""


class NeedJSError(Exception):
    """页面需要 JS 渲染才能获取内容"""
    pass


class FetchEngine:
    """双层网页抓取引擎

    Layer 1: httpx 快速直连（适用于静态页面）
    Layer 2: Playwright 无头浏览器（适用于 SPA/JS 渲染页面）
    """

    def __init__(self):
        self._browser_pool: object = None
        self._client: object = None

    async def fetch(self, url: str, timeout: int = 20) -> FetchResult:
        """获取网页内容 — 自动选择最优抓取方式"""
        if not url.startswith(("http://", "https://")):
            return FetchResult(url=url, error="URL 必须以 http:// 或 https:// 开头")

        # Layer 1: httpx 直连
        result = await self._http_fetch(url, timeout)
        if result.status_code == 200:
            # 检查是否空内容（可能是 JS 渲染页面）
            if len(result.html) > 200:
                return result
            logger.debug("httpx 返回空内容，可能需 JS 渲染: %s", url)

        # Layer 2: Playwright 浏览器降级
        return await self._browser_fetch(url, timeout)

    async def _http_fetch(self, url: str, timeout: int) -> FetchResult:
        """httpx 快速直连"""
        try:
            if self._client is None:
                import httpx
                self._client = httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=timeout,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/125.0.0.0 Safari/537.36"
                        ),
                    },
                )
            resp = await self._client.get(url)
            return FetchResult(
                url=url,
                html=resp.text,
                status_code=resp.status_code,
                headers=dict(resp.headers),
            )
        except Exception as exc:
            return FetchResult(url=url, error=str(exc))

    async def _browser_fetch(self, url: str, timeout: int) -> FetchResult:
        """Playwright 浏览器抓取 (JS 渲染)"""
        try:
            from pycoder.browser.browser_pool import BrowserPool

            if self._browser_pool is None:
                self._browser_pool = BrowserPool()
                await self._browser_pool.start()

            instance = await self._browser_pool.acquire()
            try:
                page = instance.page
                await page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
                html = await page.content()
                text = await page.evaluate("document.body?.innerText || ''")
                result = FetchResult(
                    url=url,
                    html=html,
                    text=text[:50000],
                    status_code=200,
                )
                return result
            finally:
                await self._browser_pool.release(instance)
        except ImportError:
            return FetchResult(url=url, error="Playwright 未安装，无法进行 JS 渲染抓取")
        except Exception as exc:
            return FetchResult(url=url, error=f"浏览器抓取失败: {exc}")

    async def screenshot(self, url: str, timeout: int = 20) -> bytes | None:
        """网页截图"""
        try:
            from pycoder.browser.browser_pool import BrowserPool

            if self._browser_pool is None:
                self._browser_pool = BrowserPool()
                await self._browser_pool.start()

            instance = await self._browser_pool.acquire()
            try:
                await instance.page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
                return await instance.page.screenshot(full_page=True)
            finally:
                await self._browser_pool.release(instance)
        except Exception as exc:
            logger.warning("网页截图失败: %s", exc)
            return None

    async def close(self):
        """释放资源"""
        if self._client:
            await self._client.aclose()
