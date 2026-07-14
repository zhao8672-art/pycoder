"""知识更新调度器 — 定时触发知识抓取和索引

复用现有 Scheduler 框架，注册定时知识更新任务。
支持自动批量更新、状态追踪和错误恢复。
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class KnowledgeUpdateScheduler:
    """知识更新调度器

    用法:
        kus = KnowledgeUpdateScheduler(fetcher, index, scheduler)
        kus.setup_default_tasks()
        await kus.run_update("python-docs")
        await kus.run_update_all()  # 批量更新所有源
    """

    DEFAULT_INTERVAL_SECONDS = 86400  # 默认 24 小时

    def __init__(self, fetcher, index, scheduler=None):
        self._fetcher = fetcher
        self._index = index
        self._scheduler = scheduler
        self._update_status: dict[str, dict] = {}  # source_id -> {last_update, last_error, update_count}
        self._auto_task: asyncio.Task | None = None
        self._running = False

    def setup_default_tasks(self):
        """注册默认知识更新任务"""
        if not self._scheduler:
            return
        try:
            from pycoder.server.scheduler import ScheduledTask

            self._scheduler.add_task(ScheduledTask(
                id="knowledge-python-docs",
                name="Python 文档每日更新",
                trigger="interval",
                config={"seconds": 86400},
            ))
            self._scheduler.add_task(ScheduledTask(
                id="knowledge-security",
                name="安全公告定期检查",
                trigger="interval",
                config={"seconds": 21600},
            ))
        except ImportError:
            pass

    async def run_update(self, source_id: str, fetch_fn=None) -> int:
        """执行单次知识更新

        Args:
            source_id: 知识源 ID
            fetch_fn: 异步函数 async (url) -> str

        Returns:
            新增片段数
        """
        source = self._fetcher.get_source(source_id)
        if not source:
            self._update_status[source_id] = {
                "last_error": f"知识源不存在: {source_id}",
                "last_update": datetime.now(timezone.utc).isoformat(),
                "update_count": 0,
            }
            return 0

        try:
            chunks = await self._fetcher.fetch_source(source, fetch_fn=fetch_fn)
            new_count = self._index.index_chunks(chunks)
            self._update_status[source_id] = {
                "last_update": datetime.now(timezone.utc).isoformat(),
                "last_error": None,
                "update_count": self._update_status.get(source_id, {}).get("update_count", 0) + 1,
                "chunks_indexed": new_count,
            }
            logger.info("knowledge_update_done: source=%s chunks=%d", source_id, new_count)
            return new_count
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("knowledge_update_failed: source=%s error=%s", source_id, e)
            self._update_status[source_id] = {
                "last_error": str(e),
                "last_update": datetime.now(timezone.utc).isoformat(),
                "update_count": self._update_status.get(source_id, {}).get("update_count", 0),
            }
            return 0

    async def run_update_all(self, fetch_fn=None) -> dict[str, int]:
        """批量更新所有知识源

        Args:
            fetch_fn: 异步函数 async (url) -> str

        Returns:
            {source_id: chunks_count, ...}
        """
        sources = self._fetcher.list_sources()
        results = {}
        for source in sources:
            try:
                count = await self.run_update(source.id, fetch_fn=fetch_fn)
                results[source.id] = count
            except (OSError, RuntimeError) as e:
                logger.warning("knowledge_update_all_source_failed: source=%s error=%s", source.id, e)
                results[source.id] = 0
        return results

    async def schedule_auto_updates(self, interval_seconds: int | None = None):
        """启动自动定时更新任务

        Args:
            interval_seconds: 更新间隔（秒），默认 86400（24小时）
        """
        if self._running:
            return
        self._running = True
        interval = interval_seconds or self.DEFAULT_INTERVAL_SECONDS
        self._auto_task = asyncio.create_task(self._auto_update_loop(interval))
        logger.info("knowledge_auto_update_started: interval=%ds", interval)

    async def stop_auto_updates(self):
        """停止自动定时更新"""
        self._running = False
        if self._auto_task:
            self._auto_task.cancel()
            try:
                await self._auto_task
            except asyncio.CancelledError:
                pass
            self._auto_task = None

    async def _auto_update_loop(self, interval_seconds: int):
        """自动更新循环"""
        while self._running:
            try:
                await self.run_update_all()
            except (OSError, RuntimeError) as e:
                logger.warning("knowledge_auto_update_cycle_failed: %s", e)
            await asyncio.sleep(interval_seconds)

    def get_update_status(self, source_id: str | None = None) -> dict:
        """获取更新状态

        Args:
            source_id: 知识源 ID，不指定则返回全部

        Returns:
            更新状态字典
        """
        if source_id:
            return self._update_status.get(source_id, {
                "last_update": None,
                "last_error": None,
                "update_count": 0,
            })
        return {
            "sources": dict(self._update_status),
            "total_sources": len(self._fetcher.list_sources()),
            "auto_update_running": self._running,
        }

    def get_next_update_time(self) -> float | None:
        """获取下次自动更新时间（时间戳）"""
        if not self._running or not self._auto_task:
            return None
        all_updates = [
            s.get("last_update")
            for s in self._update_status.values()
            if s.get("last_update")
        ]
        if not all_updates:
            return time.time() + self.DEFAULT_INTERVAL_SECONDS
        return None  # 循环中，无法精确计算

    def search_and_format(self, query: str) -> str:
        """搜索知识并格式化为可注入 prompt 的文本"""
        results = self._index.search(query, top_k=3)
        if not results:
            return ""
        lines = ["\n## 最新相关知识\n"]
        for r in results:
            meta = r.get("metadata", {})
            lines.append(f"- [{meta.get('title', '')}]({meta.get('url', '')})")
            lines.append(f"  {r['content'][:200]}...\n")
        return "\n".join(lines)