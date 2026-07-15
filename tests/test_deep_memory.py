"""DeepMemorySystem 深度记忆系统测试 — 4 级渐进式记忆架构"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from pycoder.memory.deep_memory import (
    DeepMemorySystem,
    MemoryEntry,
    MemoryStats,
)


# 记忆层级常量（源码中 level 为 int 1-4，无独立 MemoryLevel 枚举）
WORKING = 1     # 工作记忆
ITERATION = 2   # 迭代记忆
PROJECT = 3     # 项目记忆
GLOBAL = 4      # 全局记忆


class TestDeepMemorySystem:
    """DeepMemorySystem 四级记忆单元测试"""

    @pytest.fixture
    def engine(self, tmp_path: Path) -> DeepMemorySystem:
        """创建 DeepMemorySystem 实例（使用临时目录隔离）"""
        return DeepMemorySystem(
            project_root=tmp_path,
            global_dir=tmp_path / "global_memory",
        )

    # ── 基础测试 ──

    @pytest.mark.asyncio
    async def test_create_engine(self, engine: DeepMemorySystem) -> None:
        """创建引擎实例"""
        assert engine is not None
        assert isinstance(engine, DeepMemorySystem)

    # ── 四级记忆存储测试 ──

    @pytest.mark.asyncio
    async def test_store_working_memory(self, engine: DeepMemorySystem) -> None:
        """存储工作记忆 (Level 1) — 会话级临时记忆"""
        entry = await engine.store(WORKING, "current_task", "修复用户登录页面的 Bug")
        assert isinstance(entry, MemoryEntry)
        assert entry.level == WORKING
        assert entry.key == "current_task"
        assert entry.content == "修复用户登录页面的 Bug"
        assert entry.ttl is not None  # 工作记忆有过期时间

    @pytest.mark.asyncio
    async def test_store_episodic_memory(self, engine: DeepMemorySystem) -> None:
        """存储情节记忆带时间戳 (Level 2) — 迭代级追踪"""
        # Level 2 需要先启动迭代
        await engine.start_iteration("test_episode_iter")

        before = time.time()
        entry = await engine.store(ITERATION, "episode_001", "用户要求添加暗色模式支持")
        after = time.time()

        assert entry.level == ITERATION
        assert entry.key == "episode_001"
        assert entry.content == "用户要求添加暗色模式支持"
        # 验证时间戳在合理范围内
        assert before <= entry.timestamp <= after + 0.1

    @pytest.mark.asyncio
    async def test_store_project_knowledge(self, engine: DeepMemorySystem) -> None:
        """存储项目级知识 (Level 3) — 项目架构与约定"""
        entry = await engine.store(
            PROJECT,
            "architecture",
            "项目使用 FastAPI + SQLAlchemy + PostgreSQL 架构",
        )
        assert entry.level == PROJECT
        assert entry.key == "architecture"
        assert "FastAPI" in entry.content
        assert entry.ttl is None  # 项目记忆永不过期

    @pytest.mark.asyncio
    async def test_store_long_term_knowledge(self, engine: DeepMemorySystem) -> None:
        """存储长期知识 (Level 4) — 跨项目持久化偏好"""
        entry = await engine.store(
            GLOBAL,
            "coding_style",
            "偏好使用 dataclass 而非 namedtuple，使用 pathlib 替代 os.path",
        )
        assert entry.level == GLOBAL
        assert entry.key == "coding_style"
        assert "dataclass" in entry.content
        assert entry.ttl is None  # 全局记忆永不过期

    # ── 检索测试 ──

    @pytest.mark.asyncio
    async def test_retrieve_by_level(self, engine: DeepMemorySystem) -> None:
        """按记忆层级检索"""
        # 存入不同层级的内容
        await engine.store(WORKING, "wm_task", "工作记忆中的任务描述")
        await engine.store(PROJECT, "proj_stack", "项目技术栈 FastAPI React")
        await engine.store(GLOBAL, "global_pref", "用户偏好使用 TypeScript 类型注解")

        # 仅检索 Level 3（项目记忆）
        ctx = await engine.retrieve("FastAPI", level=PROJECT)
        assert len(ctx.entries) >= 1
        assert all(e.level == PROJECT for e in ctx.entries)
        assert ctx.query == "FastAPI"

        # 仅检索 Level 4（全局记忆）
        ctx = await engine.retrieve("TypeScript", level=GLOBAL)
        assert len(ctx.entries) >= 1
        assert all(e.level == GLOBAL for e in ctx.entries)

    @pytest.mark.asyncio
    async def test_retrieve_by_keyword(self, engine: DeepMemorySystem) -> None:
        """按关键词检索 — 跨级全文搜索"""
        # 存入区分度高的内容
        await engine.store(PROJECT, "style_guide", "使用 Black 进行代码格式化")
        await engine.store(PROJECT, "test_guide", "使用 pytest 进行单元测试")
        await engine.store(GLOBAL, "tool_pref", "偏好使用 pytest 作为测试框架")

        # 搜索 "pytest"
        ctx = await engine.retrieve("pytest", level="all")
        assert len(ctx.entries) >= 1
        assert any("pytest" in e.content.lower() for e in ctx.entries)

        # 搜索 "Black 格式化"
        ctx = await engine.retrieve("Black", level="all")
        assert len(ctx.entries) >= 1
        assert any("Black" in e.content for e in ctx.entries)

        # 搜索不存在的关键词
        ctx = await engine.retrieve("xyz_nonexistent_keyword", level="all")
        assert len(ctx.entries) == 0

    @pytest.mark.asyncio
    async def test_retrieve_by_time_range(self, engine: DeepMemorySystem) -> None:
        """按时间范围验证 — 检索结果的时间戳在合理区间内"""
        t0 = time.time()

        await engine.store(PROJECT, "early_entry", "早期项目知识条目")
        # 短暂等待确保时间戳差异
        await engine.store(PROJECT, "later_entry", "后期项目知识条目")

        t1 = time.time()

        # 检索所有 Project 级别的条目
        ctx = await engine.retrieve("知识", level=PROJECT)

        for entry in ctx.entries:
            assert entry.timestamp > 0
            # 时间戳应在存储时间段内（允许微小浮动）
            assert t0 - 1 <= entry.timestamp <= t1 + 1, (
                f"条目 {entry.key} 时间戳 {entry.timestamp} 不在 [{t0}, {t1}] 范围内"
            )

    @pytest.mark.asyncio
    async def test_retrieve_empty(self, engine: DeepMemorySystem) -> None:
        """空查询 / 无匹配 → 返回空结果"""
        # 不存入任何数据，直接检索
        ctx = await engine.retrieve("完全不存在的查询内容", level="all")
        assert len(ctx.entries) == 0
        assert ctx.total_tokens == 0
        assert ctx.retrieval_time_ms >= 0

    # ── 统计与摘要测试 ──

    @pytest.mark.asyncio
    async def test_get_stats(self, engine: DeepMemorySystem) -> None:
        """获取记忆统计信息"""
        await engine.store(WORKING, "task_1", "完成用户模块开发")
        await engine.store(PROJECT, "proj_info", "项目使用微服务架构")
        await engine.store(GLOBAL, "user_pref", "偏好使用 async/await 模式")

        stats = engine.get_stats()
        assert isinstance(stats, MemoryStats)
        assert stats.total_entries >= 3
        # 各级别统计应存在
        assert WORKING in stats.level_stats
        assert PROJECT in stats.level_stats
        assert GLOBAL in stats.level_stats

    @pytest.mark.asyncio
    async def test_stats_after_multiple_stores(self, engine: DeepMemorySystem) -> None:
        """多次存储后统计正确更新"""
        stats_before = engine.get_stats()
        initial_count = stats_before.total_entries

        # 存入多条记忆
        await engine.store(PROJECT, "arch", "架构信息")
        await engine.store(PROJECT, "deps", "依赖信息")
        await engine.store(GLOBAL, "style", "代码风格偏好")

        stats_after = engine.get_stats()
        assert stats_after.total_entries >= initial_count + 3

    # ── 元数据测试 ──

    @pytest.mark.asyncio
    async def test_store_with_metadata(self, engine: DeepMemorySystem) -> None:
        """存储带元数据的记忆"""
        metadata = {"author": "pycoder", "version": "2.0", "tags": ["fastapi", "backend"]}
        entry = await engine.store(
            PROJECT,
            "api_design",
            "RESTful API 设计规范",
            metadata=metadata,
        )
        assert entry.metadata == metadata

    @pytest.mark.asyncio
    async def test_retrieve_result_context(self, engine: DeepMemorySystem) -> None:
        """检索结果包含完整上下文信息"""
        await engine.store(PROJECT, "test_entry", "测试条目内容用于检索")

        ctx = await engine.retrieve("测试条目", level="all")
        assert ctx.query == "测试条目"
        assert ctx.retrieval_time_ms >= 0
        assert isinstance(ctx.source_levels, list)
        assert isinstance(ctx.entries, list)
        assert ctx.total_tokens >= 0

    @pytest.mark.asyncio
    async def test_deep_search(self, engine: DeepMemorySystem) -> None:
        """深度语义搜索（Project + Global + Iteration）"""
        await engine.store(PROJECT, "py_style", "Python 代码风格使用 Black 格式化")
        await engine.store(GLOBAL, "py_pref", "偏好 Python 3.10+ 语法特性")

        ctx = await engine.deep_search("Python 代码风格", k=3)
        assert len(ctx.entries) >= 1
        assert any("Python" in e.content for e in ctx.entries)
        assert ctx.retrieval_time_ms >= 0

    @pytest.mark.asyncio
    async def test_summarize(self, engine: DeepMemorySystem) -> None:
        """生成记忆摘要"""
        await engine.store(WORKING, "task", "当前正在开发用户认证模块")
        await engine.store(PROJECT, "stack", "技术栈: FastAPI, PostgreSQL, Redis")

        summaries = await engine.summarize(level="all")
        assert isinstance(summaries, dict)
        # 至少应包含已存储层级的摘要
        assert len(summaries) >= 1

    @pytest.mark.asyncio
    async def test_cleanup(self, engine: DeepMemorySystem) -> None:
        """清理过期记忆"""
        cleaned = await engine.cleanup(level="all")
        assert isinstance(cleaned, dict)
        for level in cleaned:
            assert level in (1, 2, 3, 4)
            assert cleaned[level] >= 0

    @pytest.mark.asyncio
    async def test_close(self, engine: DeepMemorySystem) -> None:
        """关闭引擎资源"""
        # close 不应抛出异常
        engine.close()
        # 二次关闭也应安全
        engine.close()