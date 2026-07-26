"""DeepMemorySystem — 四级记忆编排器

统一管理 Working / Iteration / Project / Global 四级记忆，
提供统一的存储、检索、摘要、清理接口。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from pycoder.memory.deep_memory_models import (
    MemoryEntry,
    MemoryContext,
    MemoryStats,
    _CHROMA_AVAILABLE,
    _estimate_tokens,
    _now_iso,
)
from pycoder.memory.working_memory import WorkingMemory
from pycoder.memory.iteration_memory import IterationMemory
from pycoder.memory.project_memory import ProjectMemory
from pycoder.memory.global_memory import GlobalMemory

logger = logging.getLogger(__name__)


class DeepMemorySystem:
    """深度记忆系统 — 编排四级记忆

    统一管理 Working / Iteration / Project / Global 四级记忆，
    提供统一的存储、检索、摘要、清理接口。

    用法:
        system = DeepMemorySystem(
            project_root=Path("./myproject"),
            global_dir=Path.home() / ".pycoder" / "global_memory",
        )
        await system.store(1, "current_task", "修复登录 Bug")
        ctx = await system.retrieve("登录", level="all")
        stats = system.get_stats()
    """

    def __init__(self, project_root: Path, global_dir: Path | None = None):
        self._project_root = project_root
        self._global_dir = global_dir or Path.home() / ".pycoder" / "global_memory"

        # P1-B: 子层懒加载 — 首次访问才初始化
        self._working: WorkingMemory | None = None
        self._iteration: IterationMemory | None = None
        self._project: ProjectMemory | None = None
        self._global: GlobalMemory | None = None

        self._last_cleanup = _now_iso()

    # ── 懒加载访问器 ────────────────────────────────

    @property
    def working(self) -> WorkingMemory:
        """工作记忆（首次访问时初始化）"""
        if self._working is None:
            self._working = WorkingMemory()
            logger.debug("lazy_init working_memory")
        return self._working

    @property
    def iteration(self) -> IterationMemory:
        """迭代记忆（首次访问时初始化，触发 SQLite 打开）"""
        if self._iteration is None:
            self._iteration = IterationMemory(
                self._project_root / ".pycoder" / "iteration_memory"
            )
            logger.debug("lazy_init iteration_memory")
        return self._iteration

    @property
    def project(self) -> ProjectMemory:
        """项目记忆（首次访问时初始化，触发 ChromaDB 连接）"""
        if self._project is None:
            self._project = ProjectMemory(self._project_root)
            logger.debug("lazy_init project_memory")
        return self._project

    @property
    def global_memory(self) -> GlobalMemory:
        """全局记忆（首次访问时初始化）"""
        if self._global is None:
            self._global = GlobalMemory(self._global_dir)
            logger.debug("lazy_init global_memory")
        return self._global

    def _ensure_working(self) -> WorkingMemory:
        return self.working

    def _ensure_iteration(self) -> IterationMemory:
        return self.iteration

    def _ensure_project(self) -> ProjectMemory:
        return self.project

    def _ensure_global(self) -> GlobalMemory:
        return self.global_memory

    # ── 统一存储 ──

    async def store(
        self,
        level: int,
        key: str,
        value: str,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """统一存储接口，按级别路由"""
        match level:
            case 1:
                return self.working.store(key, value, metadata)
            case 2:
                return await self.iteration._store(
                    "note", key, value, metadata or {}
                )
            case 3:
                return await self.project.store(key, value, metadata)
            case 4:
                return await self.global_memory.store(key, value, metadata)
            case _:
                raise ValueError(f"无效的记忆层级: {level}，有效值为 1-4")

    # ── 统一检索 ──

    async def retrieve(
        self,
        query: str,
        level: str | int = "all",
        k: int = 5,
    ) -> MemoryContext:
        """多级记忆检索"""
        start = time.time()
        entries: list[MemoryEntry] = []
        source_levels: list[int] = []

        if level == "all" or level == 1:
            wm_entry = self.working.retrieve(query)
            if wm_entry:
                entries.append(wm_entry)
                source_levels.append(1)
            for e in self.working.get_all_entries():
                if query.lower() in e.content.lower() and e not in entries:
                    entries.append(e)
                    source_levels.append(1)

        if level == "all" or level == 2:
            im_entries = await self.iteration.search(query, limit=k)
            for e in im_entries:
                if e not in entries:
                    entries.append(e)
                    source_levels.append(2)

        if level == "all" or level == 3:
            pm_entries = await self.project.search(query, k=k)
            for e in pm_entries:
                if e not in entries:
                    entries.append(e)
                    source_levels.append(3)

        if level == "all" or level == 4:
            gm_entries = await self.global_memory.search(query, k=k)
            for e in gm_entries:
                if e not in entries:
                    entries.append(e)
                    source_levels.append(4)

        total_tokens = sum(_estimate_tokens(e.content) for e in entries)
        elapsed = (time.time() - start) * 1000

        return MemoryContext(
            entries=entries,
            source_levels=list(set(source_levels)),
            total_tokens=total_tokens,
            query=query,
            retrieval_time_ms=elapsed,
        )

    # ── 摘要 ──

    async def summarize(self, level: str | int = "all", llm_provider=None) -> dict[int, str]:
        """生成记忆摘要"""
        summaries: dict[int, str] = {}
        if level == "all" or level == 1:
            summaries[1] = await self.working.summarize(llm_provider)
        if level == "all" or level == 2:
            summaries[2] = await self.iteration.summarize(llm_provider)
        if level == "all" or level == 3:
            summaries[3] = await self.project.summarize(llm_provider)
        if level == "all" or level == 4:
            summaries[4] = await self.global_memory.summarize(llm_provider)
        return summaries

    # ── 清理 ──

    async def cleanup(self, level: str | int = "all") -> dict[int, int]:
        """清理过期记忆"""
        cleaned: dict[int, int] = {}
        if level == "all" or level == 1:
            self.working.clear()
            cleaned[1] = 0
        if level == "all" or level == 2:
            cleaned[2] = await self.iteration.cleanup(older_than_days=14)
        if level == "all" or level == 3:
            cleaned[3] = await self.project.cleanup(older_than_days=90)
        if level == "all" or level == 4:
            cleaned[4] = await self.global_memory.cleanup(older_than_days=365)
        self._last_cleanup = _now_iso()
        logger.info("deep_memory_cleanup cleaned=%s", cleaned)
        return cleaned

    # ── 语义搜索（跨级） ──

    async def deep_search(
        self,
        query: str,
        k: int = 5,
        embedding: list[float] | None = None,
    ) -> MemoryContext:
        """深度语义搜索 — 优先在 Project 和 Global 级做向量搜索"""
        start = time.time()
        entries: list[MemoryEntry] = []
        source_levels: list[int] = []

        pm_entries = await self.project.search(query, k=k, embedding=embedding)
        for e in pm_entries:
            entries.append(e)
            source_levels.append(3)

        gm_entries = await self.global_memory.search(query, k=k, embedding=embedding)
        for e in gm_entries:
            entries.append(e)
            source_levels.append(4)

        im_entries = await self.iteration.search(query, limit=k)
        for e in im_entries:
            if e not in entries:
                entries.append(e)
                source_levels.append(2)

        total_tokens = sum(_estimate_tokens(e.content) for e in entries)
        elapsed = (time.time() - start) * 1000

        return MemoryContext(
            entries=entries,
            source_levels=list(set(source_levels)),
            total_tokens=total_tokens,
            query=query,
            retrieval_time_ms=elapsed,
        )

    # ── 统计 ──

    def get_stats(self) -> MemoryStats:
        """获取所有级别的记忆统计"""
        level_stats: dict[int, dict[str, int]] = {
            1: {"entries": self.working.entry_count, "tokens": self.working.token_count},
            2: self.iteration.get_stats(),
            3: self.project.get_stats(),
            4: self.global_memory.get_stats(),
        }
        total_entries = self.working.entry_count
        for level in (2, 3, 4):
            stats = level_stats[level]
            total_entries += stats.get("total", stats.get("total_sqlite", 0))
        return MemoryStats(
            level_stats=level_stats,
            total_entries=total_entries,
            total_size_bytes=0,
            last_cleanup=self._last_cleanup,
            chroma_available=_CHROMA_AVAILABLE,
        )

    # ── 迭代管理 ──

    async def start_iteration(self, iteration_id: str) -> None:
        """开始新迭代"""
        await self.iteration.start_iteration(iteration_id)

    async def end_iteration(self) -> None:
        """结束当前迭代"""
        await self.iteration.end_iteration()

    # ── 便捷方法 ──

    async def track_file(self, file_path: str, action: str = "modified") -> MemoryEntry:
        """便捷：追踪文件变更"""
        return await self.iteration.track_file(file_path, action)

    async def track_command(
        self, command: str, exit_code: int = 0, output: str = "",
    ) -> MemoryEntry:
        """便捷：追踪命令执行"""
        return await self.iteration.track_command(command, exit_code, output)

    async def track_error(self, error_message: str, resolved: bool = False) -> MemoryEntry:
        """便捷：追踪错误"""
        return await self.iteration.track_error(error_message, resolved)

    def close(self) -> None:
        """关闭所有资源"""
        self.iteration.close()

    @property
    def global_(self) -> GlobalMemory:
        """向后兼容: 旧 API 用 system.global_，新代码用 system.global_memory"""
        return self.global_memory
