"""
AI 驱动的浏览器操作代理

让 AI 能够驱动浏览器执行复杂的交互操作：
- 点击元素、填写表单、导航页面
- 多步操作链
- 观察页面变化
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class BrowserAgent:
    """AI 驱动的浏览器操作代理"""

    def __init__(self):
        self._pool: object = None
        self._current_page: object = None

    async def navigate(self, url: str) -> dict:
        """导航到指定 URL"""
        page = await self._get_page()
        await page.goto(url, wait_until="networkidle")
        return {
            "url": page.url,
            "title": await page.title(),
            "content_length": len(await page.content()),
        }

    async def click(self, selector: str) -> dict:
        """点击元素"""
        page = await self._get_page()
        await page.click(selector)
        return {"success": True, "url": page.url}

    async def fill(self, selector: str, value: str) -> dict:
        """填写表单"""
        page = await self._get_page()
        await page.fill(selector, value)
        return {"success": True}

    async def get_text(self, selector: str) -> str:
        """获取元素文本"""
        page = await self._get_page()
        return await page.inner_text(selector)

    async def evaluate(self, js: str) -> object:
        """执行 JavaScript"""
        page = await self._get_page()
        return await page.evaluate(js)

    async def _get_page(self):
        from pycoder.browser.browser_pool import BrowserPool

        if self._pool is None:
            self._pool = BrowserPool()
            await self._pool.start()

        if self._current_page is None:
            inst = await self._pool.acquire()
            self._current_page = inst.page
            self._current_instance = inst

        return self._current_page

    async def close(self):
        """释放资源"""
        if self._current_page:
            await self._current_page.close()
