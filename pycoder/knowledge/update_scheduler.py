"""知识更新调度器 — 定时触发知识抓取和索引

复用现有 Scheduler 框架，注册定时知识更新任务。
"""
from __future__ import annotations


class KnowledgeUpdateScheduler:
    """知识更新调度器

    用法:
        kus = KnowledgeUpdateScheduler(fetcher, index, scheduler)
        kus.setup_default_tasks()
        await kus.run_update("python-docs")
    """

    def __init__(self, fetcher, index, scheduler=None):
        self._fetcher = fetcher
        self._index = index
        self._scheduler = scheduler

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
            return 0
        chunks = await self._fetcher.fetch_source(source, fetch_fn=fetch_fn)
        new_count = self._index.index_chunks(chunks)
        return new_count

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