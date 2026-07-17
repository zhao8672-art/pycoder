"""
文件监控服务 — 监听文件变化并自动触发 AI 分析

使用 watchdog 库监听指定目录的文件变化事件。
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class WatchService:
    """文件监控服务"""

    def __init__(self):
        self._watchers: dict[str, object] = {}
        self._running = False

    async def start(self):
        """启动监控服务"""
        self._running = True
        logger.info("文件监控服务已启动")

    async def stop(self):
        """停止所有监控"""
        self._running = False
        for path, observer in list(self._watchers.items()):
            observer.stop()
        self._watchers.clear()
        logger.info("文件监控服务已停止")

    async def watch(self, path: str, pattern: str = "*",
                    on_change: callable = None) -> dict:
        """监控目录文件变化

        Args:
            path: 监控的目录路径
            pattern: 文件匹配模式, 如 "*.py"
            on_change: 变化时的回调函数
        """
        import os
        if not os.path.isdir(path):
            return {"success": False, "error": f"目录不存在: {path}"}

        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class AIHandler(FileSystemEventHandler):
                def __init__(self, cb, pat):
                    self._cb = cb
                    self._pat = pat

                def on_modified(self, event):
                    if event.is_directory:
                        return
                    import fnmatch
                    if fnmatch.fnmatch(os.path.basename(event.src_path), self._pat):
                        asyncio.ensure_future(self._cb(event.src_path))

                def on_created(self, event):
                    if event.is_directory:
                        return
                    import fnmatch
                    if fnmatch.fnmatch(os.path.basename(event.src_path), self._pat):
                        asyncio.ensure_future(self._cb(event.src_path))

            observer = Observer()
            handler = AIHandler(on_change, pattern)
            observer.schedule(handler, path, recursive=True)
            observer.start()
            self._watchers[path] = observer

            return {
                "success": True,
                "message": f"正在监控 {path} 中的 {pattern} 文件变化",
            }
        except ImportError:
            return {"success": False, "error": "watchdog 未安装，请执行: pip install watchdog"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def unwatch(self, path: str) -> dict:
        """停止监控指定目录"""
        if path in self._watchers:
            self._watchers[path].stop()
            del self._watchers[path]
            return {"success": True, "message": f"已停止监控 {path}"}
        return {"success": False, "error": f"未在监控: {path}"}

    def status(self) -> dict:
        """监控状态"""
        return {
            "running": self._running,
            "watching": list(self._watchers.keys()),
        }


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_service: WatchService | None = None


def get_watch_service() -> WatchService:
    global _service
    if _service is None:
        _service = WatchService()
    return _service
