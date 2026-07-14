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
    error_count: int = 0
    last_error: str = ""


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
    MAX_ERRORS_PER_INSTANCE = 3
    CREATE_RETRY_COUNT = 2
    CREATE_RETRY_DELAY = 1.0

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
                # 健康检查：验证实例是否仍可用
                if await self._health_check(instance):
                    instance.in_use = True
                    return instance
                # 实例不健康，关闭并移除
                await self._close_instance(instance)
                self._all_instances = [i for i in self._all_instances if i.id != instance.id]
            instance = await self._create_instance_with_retry()
            if instance:
                self._all_instances.append(instance)
                instance.in_use = True
                return instance
            self._semaphore.release()
            return None
        except (OSError, RuntimeError) as e:
            logger.warning("browser_pool_acquire_failed: %s", e)
            self._semaphore.release()
            return None

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

    async def _create_instance_with_retry(self) -> BrowserInstance | None:
        """带重试的实例创建"""
        for attempt in range(self.CREATE_RETRY_COUNT):
            instance = await self._create_instance()
            if instance:
                return instance
            if attempt < self.CREATE_RETRY_COUNT - 1:
                await asyncio.sleep(self.CREATE_RETRY_DELAY)
        return None

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

    async def _health_check(self, instance: BrowserInstance) -> bool:
        """检查实例是否健康"""
        if instance.error_count >= self.MAX_ERRORS_PER_INSTANCE:
            return False
        try:
            await asyncio.wait_for(
                instance.page.evaluate("() => true"),
                timeout=5.0,
            )
            return True
        except (TimeoutError, OSError, RuntimeError) as e:
            instance.error_count += 1
            instance.last_error = str(e)
            logger.debug("browser_pool_health_check_failed: id=%s error=%s", instance.id, e)
            return False

    async def _close_instance(self, instance: BrowserInstance):
        """安全关闭实例"""
        try:
            await instance.browser.close()
        except (OSError, RuntimeError) as e:
            logger.debug("browser_pool_close_instance_failed: %s", e)

    async def _cleanup_loop(self):
        """定期清理空闲实例"""
        while True:
            await asyncio.sleep(60)
            now = time.time()
            idle = [
                i for i in self._all_instances
                if not i.in_use and now - i.last_used > self.IDLE_TIMEOUT
            ]
            pool_size = self._pool.qsize()
            # 保留至少 MIN_INSTANCES 个实例在池中
            keep_count = max(0, pool_size - self.MIN_INSTANCES)
            to_remove = idle[keep_count:] if len(idle) > keep_count else []
            for inst in to_remove:
                await self._close_instance(inst)
                self._all_instances = [i for i in self._all_instances if i.id != inst.id]

    def get_stats(self) -> dict:
        """获取池状态统计"""
        return {
            "total_instances": len(self._all_instances),
            "pool_size": self._pool.qsize(),
            "in_use": sum(1 for i in self._all_instances if i.in_use),
            "idle": sum(1 for i in self._all_instances if not i.in_use),
            "max_instances": self.MAX_INSTANCES,
        }

    async def stop(self):
        """停止池，关闭所有实例"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        for inst in self._all_instances:
            await self._close_instance(inst)
        self._all_instances.clear()
        if self._pw:
            try:
                await self._pw.stop()
            except (OSError, RuntimeError) as e:
                logger.debug("browser_pool_stop_pw_failed: %s", e)
