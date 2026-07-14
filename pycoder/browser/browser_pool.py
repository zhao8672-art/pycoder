"""浏览器实例池 — 预启动 Playwright 实例，减少冷启动延迟

管理 Playwright 浏览器的生命周期：预热、获取、归还、健康检查、空闲回收。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class BrowserInstance:
    id: str
    browser: object
    page: object
    in_use: bool = False
    created_at: float = 0.0
    last_used: float = 0.0


class BrowserPool:
    """Playwright 浏览器实例池

    用法:
        pool = BrowserPool()
        await pool.start()
        instance = await pool.acquire()
        # ... 使用 instance.page ...
        await pool.release(instance)
    """

    MIN_INSTANCES = 1
    MAX_INSTANCES = 4
    IDLE_TIMEOUT = 300

    def __init__(self):
        self._pool: asyncio.Queue[BrowserInstance] = asyncio.Queue()
        self._all_instances: list[BrowserInstance] = []
        self._semaphore = asyncio.Semaphore(self.MAX_INSTANCES)
        self._cleanup_task: asyncio.Task | None = None
        self._pw = None

    async def start(self):
        """启动池，预热最小实例数"""
        try:
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
        except ImportError:
            return

        for _ in range(self.MIN_INSTANCES):
            try:
                instance = await self._create_instance()
                if instance:
                    await self._pool.put(instance)
                    self._all_instances.append(instance)
            except (OSError, RuntimeError) as e:
                logger.warning("browser_pool_prewarm_failed: %s", e)
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def acquire(self) -> BrowserInstance | None:
        """获取一个可用浏览器实例"""
        await self._semaphore.acquire()
        try:
            if not self._pool.empty():
                instance = await self._pool.get()
                instance.in_use = True
                return instance
            instance = await self._create_instance()
            if instance:
                self._all_instances.append(instance)
                instance.in_use = True
                return instance
            return None
        except Exception:
            self._semaphore.release()
            raise

    async def release(self, instance: BrowserInstance):
        """归还实例到池中"""
        instance.in_use = False
        instance.last_used = time.time()
        try:
            await instance.page.goto("about:blank")
        except (OSError, RuntimeError) as e:
            logger.debug("browser_pool_reset_page_failed: %s", e)
        await self._pool.put(instance)
        self._semaphore.release()

    async def _create_instance(self) -> BrowserInstance | None:
        """创建新的浏览器实例"""
        if not self._pw:
            return None
        try:
            browser = await self._pw.chromium.launch(headless=True)
            page = await browser.new_page()
            return BrowserInstance(
                id=f"browser_{id(page)}",
                browser=browser,
                page=page,
                created_at=time.time(),
            )
        except (OSError, RuntimeError) as e:
            logger.warning("browser_pool_create_instance_failed: %s", e)
            return None

    async def _cleanup_loop(self):
        """定期清理空闲实例"""
        while True:
            await asyncio.sleep(60)
            now = time.time()
            idle = [
                i for i in self._all_instances
                if not i.in_use and now - i.last_used > self.IDLE_TIMEOUT
            ]
            # 保留 MIN_INSTANCES 个
            to_remove = idle[len(self._pool.qsize()) - self.MIN_INSTANCES:]
            for inst in to_remove:
                try:
                    await inst.browser.close()
                except (OSError, RuntimeError) as e:
                    logger.debug("browser_pool_cleanup_close_failed: %s", e)
                self._all_instances.remove(inst)

    async def stop(self):
        """停止池，关闭所有实例"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
        for inst in self._all_instances:
            try:
                await inst.browser.close()
            except (OSError, RuntimeError) as e:
                logger.debug("browser_pool_stop_close_failed: %s", e)
        self._all_instances.clear()
        if self._pw:
            try:
                await self._pw.stop()
            except (OSError, RuntimeError) as e:
                logger.debug("browser_pool_stop_pw_failed: %s", e)