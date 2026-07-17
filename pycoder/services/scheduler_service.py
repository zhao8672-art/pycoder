"""
轻量任务调度器 — 定时/间隔触发 AI 操作

支持:
  - 一次性延迟执行
  - 固定间隔重复执行
  - 定时执行 (CRON 表达式, 需 croniter)
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class SchedulerService:
    """轻量任务调度器"""

    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False

    async def start(self):
        self._running = True
        logger.info("任务调度器已启动")

    async def stop(self):
        self._running = False
        for name, task in list(self._tasks.items()):
            task.cancel()
        self._tasks.clear()
        logger.info("任务调度器已停止")

    async def schedule_once(self, name: str, delay_sec: int,
                            action: callable) -> dict:
        """一次性延迟任务"""
        if name in self._tasks:
            return {"success": False, "error": f"任务名已存在: {name}"}

        async def _run():
            await asyncio.sleep(delay_sec)
            try:
                result = action()
                if asyncio.iscoroutine(result):
                    await result
                logger.info("一次性任务完成: %s", name)
            except Exception as exc:
                logger.error("一次性任务失败 %s: %s", name, exc)
            finally:
                self._tasks.pop(name, None)

        self._tasks[name] = asyncio.create_task(_run())
        return {"success": True, "message": f"任务 {name} 将在 {delay_sec}s 后执行"}

    async def schedule_interval(self, name: str, interval_sec: int,
                                action: callable) -> dict:
        """间隔重复任务"""
        if name in self._tasks:
            return {"success": False, "error": f"任务名已存在: {name}"}

        async def _run():
            while self._running:
                await asyncio.sleep(interval_sec)
                try:
                    result = action()
                    if asyncio.iscoroutine(result):
                        await result
                    logger.debug("间隔任务执行: %s", name)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.error("间隔任务失败 %s: %s", name, exc)

        self._tasks[name] = asyncio.create_task(_run())
        return {
            "success": True,
            "message": f"任务 {name} 每 {interval_sec}s 执行一次",
        }

    async def cancel(self, name: str) -> dict:
        """取消任务"""
        if name in self._tasks:
            self._tasks[name].cancel()
            del self._tasks[name]
            return {"success": True, "message": f"任务已取消: {name}"}
        return {"success": False, "error": f"任务不存在: {name}"}

    def status(self) -> dict:
        """调度器状态"""
        return {
            "running": self._running,
            "scheduled_tasks": list(self._tasks.keys()),
        }


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_scheduler: SchedulerService | None = None


def get_scheduler() -> SchedulerService:
    global _scheduler
    if _scheduler is None:
        _scheduler = SchedulerService()
    return _scheduler
