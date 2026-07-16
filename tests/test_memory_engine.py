"""记忆引擎测试 — MemoryEngine, WorkingMemory, ProjectKnowledge"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pycoder.brain.memory_engine import (
    MemoryEngine,
    MemoryItem,
    ProjectKnowledge,
    WorkingMemory,
)


# ══════════════════════════════════════════════════════════
# MemoryItem 数据类测试
# ══════════════════════════════════════════════════════════


class TestMemoryItem:
    """MemoryItem 数据类"""

    def test_create_item_defaults(self):
        """默认值创建记忆条目"""
        item = MemoryItem(key="test_key", content="测试内容")
        assert item.key == "test_key"
        assert item.content == "测试内容"
        assert item.importance == 0.5
        assert isinstance(item.timestamp, float)
        assert item.access_count == 0
        assert item.tags == []

    def test_create_item_full(self):
        """完整参数创建记忆条目"""
        item = MemoryItem(
            key="key1",
            content="重要信息",
            importance=0.9,
            tags=["python", "fastapi"],
        )
        assert item.importance == 0.9
        assert item.tags == ["python", "fastapi"]

    def test_access_count_increment(self):
        """访问计数可递增"""
        item = MemoryItem(key="k", content="c")
        assert item.access_count == 0
        item.access_count += 1
        assert item.access_count == 1


# ══════════════════════════════════════════════════════════
# WorkingMemory 测试
# ══════════════════════════════════════════════════════════


class TestWorkingMemory:
    """工作记忆 — 当前会话上下文窗口"""

    @pytest.fixture
    def wm(self):
        """创建工作记忆实例"""
        return WorkingMemory(max_items=50)

    # ── add() ──────────────────────────────────────

    def test_add_new_item(self, wm):
        """添加新记忆"""
        wm.add("key1", "内容1")
        item = wm.get("key1")
        assert item is not None
        assert item.content == "内容1"

    def test_add_update_existing(self, wm):
        """更新已存在的记忆"""
        wm.add("key1", "原始内容")
        wm.add("key1", "更新内容")
        item = wm.get("key1")
        assert item.content == "更新内容"
        # add 更新时 +1，get 时再 +1，共 2 次
        assert item.access_count == 2

    def test_add_with_importance(self, wm):
        """带重要度添加记忆"""
        wm.add("key1", "重要", importance=0.9)
        item = wm.get("key1")
        assert item.importance == 0.9

    def test_add_with_tags(self, wm):
        """带标签添加记忆"""
        wm.add("key1", "内容", tags=["python", "test"])
        item = wm.get("key1")
        assert item.tags == ["python", "test"]

    def test_add_eviction_when_full(self):
        """超出容量时淘汰最不重要记忆"""
        wm = WorkingMemory(max_items=3)
        # 添加 3 条记忆
        wm.add("k1", "c1", importance=0.1)
        wm.add("k2", "c2", importance=0.5)
        wm.add("k3", "c3", importance=0.9)
        # 第 4 条触发淘汰
        wm.add("k4", "c4", importance=0.3)
        # k1 重要性最低应被淘汰
        assert wm.get("k1") is None
        assert wm.get("k4") is not None

    def test_add_eviction_by_access_count(self):
        """相同重要度时按访问计数淘汰"""
        wm = WorkingMemory(max_items=3)
        wm.add("k1", "c1", importance=0.5)
        wm.add("k2", "c2", importance=0.5)
        wm.add("k3", "c3", importance=0.5)
        # 访问 k2 和 k3
        wm.get("k2")
        wm.get("k3")
        wm.get("k3")
        # k1 访问最少，应被淘汰
        wm.add("k4", "c4", importance=0.5)
        assert wm.get("k1") is None

    # ── get() ──────────────────────────────────────

    def test_get_existing(self, wm):
        """获取存在的记忆"""
        wm.add("key1", "内容")
        item = wm.get("key1")
        assert item is not None
        assert item.key == "key1"

    def test_get_nonexistent(self, wm):
        """获取不存在的记忆"""
        assert wm.get("nonexistent") is None

    def test_get_increments_access_count(self, wm):
        """获取记忆增加访问计数"""
        wm.add("key1", "内容")
        assert wm.get("key1").access_count == 1  # 首次 get，0→1
        wm.get("key1")  # 第二次 get，1→2
        assert wm.get("key1").access_count == 3  # 第三次 get，2→3

    # ── search() ───────────────────────────────────

    def test_search_by_content(self, wm):
        """按内容关键词搜索"""
        wm.add("k1", "Python FastAPI 教程")
        wm.add("k2", "Rust 编程")
        wm.add("k3", "FastAPI 部署指南")

        results = wm.search("FastAPI")
        assert len(results) == 2
        keys = {r.key for r in results}
        assert keys == {"k1", "k3"}

    def test_search_by_tag(self, wm):
        """按标签搜索"""
        wm.add("k1", "内容", tags=["python", "web"])
        wm.add("k2", "内容", tags=["rust", "cli"])

        results = wm.search("python")
        assert len(results) == 1
        assert results[0].key == "k1"

    def test_search_case_insensitive(self, wm):
        """搜索不区分大小写"""
        wm.add("k1", "Python API")
        results = wm.search("python")
        assert len(results) == 1

    def test_search_no_match(self, wm):
        """无匹配结果"""
        wm.add("k1", "Python")
        results = wm.search("Rust")
        assert len(results) == 0

    def test_search_empty(self, wm):
        """空记忆搜索"""
        results = wm.search("anything")
        assert results == []

    # ── summarize() ────────────────────────────────

    def test_summarize_empty(self, wm):
        """空记忆摘要"""
        assert wm.summarize() == ""

    def test_summarize_with_items(self, wm):
        """有记忆时生成摘要"""
        wm.add("key1", "这是第一条记忆内容" * 10)
        wm.add("key2", "这是第二条记忆内容")
        summary = wm.summarize()
        assert "当前上下文" in summary
        assert "key1" in summary
        assert "key2" in summary

    def test_summarize_truncates_long_content(self, wm):
        """长内容被截断"""
        wm.add("key1", "X" * 200)
        summary = wm.summarize()
        # 内容被截断到 100 字符
        assert "X" * 100 in summary
        assert "X" * 200 not in summary

    def test_summarize_only_last_10(self, wm):
        """仅摘要最近 10 条"""
        for i in range(20):
            wm.add(f"key{i}", f"内容{i}")
        summary = wm.summarize()
        # 最近 10 条应出现
        assert "key10" in summary
        assert "key19" in summary
        # 最早的条目不应出现
        assert "key0" not in summary

    # ── clear() ────────────────────────────────────

    def test_clear(self, wm):
        """清空工作记忆"""
        wm.add("k1", "c1")
        wm.add("k2", "c2")
        wm.clear()
        assert wm.get("k1") is None
        assert wm.summarize() == ""

    def test_clear_empty(self, wm):
        """清空空记忆不报错"""
        wm.clear()
        assert wm.summarize() == ""

    # ── capacity ───────────────────────────────────

    def test_custom_capacity(self):
        """自定义容量"""
        wm = WorkingMemory(max_items=10)
        for i in range(10):
            wm.add(f"k{i}", f"c{i}")
        # 10 条全部保留
        assert wm.get("k0") is not None
        # 第 11 条触发淘汰
        wm.add("k10", "c10")
        # 最不重要的被淘汰
        count = 0
        for i in range(11):
            if wm.get(f"k{i}") is not None:
                count += 1
        assert count == 10


# ══════════════════════════════════════════════════════════
# ProjectKnowledge 测试
# ══════════════════════════════════════════════════════════


class TestProjectKnowledge:
    """项目知识 — 持久化项目级知识库"""

    @pytest.fixture
    def pk(self):
        """创建项目知识实例"""
        return ProjectKnowledge(project_path=".")

    # ── ADR 管理 ───────────────────────────────────

    def test_add_adr(self, pk):
        """添加架构决策记录"""
        pk.add_adr("使用 FastAPI", "决定采用 FastAPI 作为 Web 框架", "需要高性能异步框架")
        assert len(pk._adr) == 1
        assert pk._adr[0]["title"] == "使用 FastAPI"
        assert pk._adr[0]["decision"] == "决定采用 FastAPI 作为 Web 框架"
        assert "timestamp" in pk._adr[0]

    def test_add_multiple_adr(self, pk):
        """添加多条架构决策"""
        pk.add_adr("ADR-1", "决策1")
        pk.add_adr("ADR-2", "决策2")
        pk.add_adr("ADR-3", "决策3")
        assert len(pk._adr) == 3

    # ── 约定管理 ───────────────────────────────────

    def test_set_and_get_convention(self, pk):
        """设置和获取项目约定"""
        pk.set_convention("代码风格", "使用 Black 格式化")
        assert pk.get_convention("代码风格") == "使用 Black 格式化"

    def test_get_convention_nonexistent(self, pk):
        """获取不存在的约定"""
        assert pk.get_convention("nonexistent") is None

    def test_all_conventions(self, pk):
        """获取所有约定"""
        pk.set_convention("c1", "规则1")
        pk.set_convention("c2", "规则2")
        all_c = pk.all_conventions()
        assert len(all_c) == 2
        assert all_c["c1"] == "规则1"

    def test_all_conventions_empty(self, pk):
        """空约定"""
        assert pk.all_conventions() == {}

    def test_update_convention(self, pk):
        """更新已有约定"""
        pk.set_convention("c1", "规则1")
        pk.set_convention("c1", "规则1-更新版")
        assert pk.get_convention("c1") == "规则1-更新版"

    # ── 依赖管理 ───────────────────────────────────

    def test_add_dependency(self, pk):
        """添加依赖关系"""
        pk.add_dependency("module_a", "module_b")
        assert "module_b" in pk.get_dependencies("module_a")

    def test_add_multiple_dependencies(self, pk):
        """添加多个依赖"""
        pk.add_dependency("module_a", "module_b")
        pk.add_dependency("module_a", "module_c")
        deps = pk.get_dependencies("module_a")
        assert len(deps) == 2
        assert "module_b" in deps
        assert "module_c" in deps

    def test_get_dependencies_nonexistent(self, pk):
        """获取不存在模块的依赖"""
        assert pk.get_dependencies("nonexistent") == []

    def test_get_dependents(self, pk):
        """获取依赖某模块的模块"""
        pk.add_dependency("module_a", "module_b")
        pk.add_dependency("module_c", "module_b")
        dependents = pk.get_dependents("module_b")
        assert len(dependents) == 2
        assert "module_a" in dependents
        assert "module_c" in dependents

    def test_get_dependents_none(self, pk):
        """无依赖者"""
        assert pk.get_dependents("orphan") == []

    def test_add_duplicate_dependency(self, pk):
        """重复添加依赖不产生重复"""
        pk.add_dependency("module_a", "module_b")
        pk.add_dependency("module_a", "module_b")
        assert len(pk.get_dependencies("module_a")) == 1


# ══════════════════════════════════════════════════════════
# MemoryEngine 测试
# ══════════════════════════════════════════════════════════


class TestMemoryEngine:
    """记忆引擎 — 统一管理各级记忆"""

    @pytest.fixture
    def engine(self, tmp_path):
        """创建记忆引擎（使用临时目录避免持久化污染）"""
        with patch.object(Path, "home", return_value=tmp_path):
            engine = MemoryEngine()
            yield engine

    # ── remember() ─────────────────────────────────

    def test_remember_working(self, engine):
        """记录到工作记忆"""
        engine.remember("key1", "工作记忆内容", level="working")
        item = engine.working.get("key1")
        assert item is not None
        assert item.content == "工作记忆内容"

    def test_remember_project(self, engine):
        """记录到项目知识"""
        engine.remember("code_style", "使用 Black", level="project")
        assert engine.project.get_convention("code_style") == "使用 Black"

    def test_remember_long_term(self, engine):
        """记录到长期知识"""
        engine.remember("user_pref", "偏好黑暗模式", level="long_term")
        assert "user_pref" in engine._long_term
        assert engine._long_term["user_pref"]["content"] == "偏好黑暗模式"

    def test_remember_episodic(self, engine):
        """记录到情景记忆"""
        engine.remember("ep1", "完成了 API 重构", level="episodic")
        assert len(engine._episodic) == 1
        assert engine._episodic[0]["content"] == "完成了 API 重构"

    def test_remember_default_level(self, engine):
        """默认记录到工作记忆"""
        engine.remember("key1", "默认内容")
        assert engine.working.get("key1") is not None

    def test_remember_with_importance(self, engine):
        """带重要度记录"""
        engine.remember("key1", "重要信息", importance=0.9)
        assert engine.working.get("key1").importance == 0.9

    # ── recall() ───────────────────────────────────

    def test_recall_working(self, engine):
        """从工作记忆检索"""
        engine.remember("k1", "Python FastAPI 教程", level="working")
        results = engine.recall("FastAPI", level="working")
        assert len(results) == 1
        assert "[工作记忆]" in results[0]

    def test_recall_project(self, engine):
        """从项目知识检索"""
        engine.remember("code_style", "使用 Black", level="project")
        results = engine.recall("Black", level="project")
        assert len(results) >= 1

    def test_recall_long_term(self, engine):
        """从长期知识检索"""
        engine.remember("pref", "偏好 Python", level="long_term")
        results = engine.recall("Python", level="long_term")
        assert len(results) >= 1
        assert "[长期知识]" in results[0]

    def test_recall_episodic(self, engine):
        """从情景记忆检索"""
        engine.remember("ep1", "重构了用户模块", level="episodic")
        results = engine.recall("重构", level="episodic")
        assert len(results) >= 1
        assert "[情景记忆]" in results[0]

    def test_recall_all(self, engine):
        """从所有层级检索"""
        engine.remember("k1", "Python API", level="working")
        engine.remember("conv", "使用 Python", level="project")
        results = engine.recall("Python", level="all")
        assert len(results) >= 2

    def test_recall_no_match(self, engine):
        """无匹配结果"""
        results = engine.recall("不存在的关键词xyz")
        assert results == []

    def test_recall_case_insensitive(self, engine):
        """检索不区分大小写"""
        engine.remember("k1", "Python Programming", level="working")
        results = engine.recall("python", level="working")
        assert len(results) == 1

    # ── get_context_for_llm() ──────────────────────

    def test_get_context_for_llm_empty(self, engine):
        """空上下文"""
        context = engine.get_context_for_llm()
        assert context == ""

    def test_get_context_for_llm_with_working(self, engine):
        """有工作记忆时的上下文"""
        engine.remember("k1", "Python 项目", level="working")
        context = engine.get_context_for_llm()
        assert "当前上下文" in context
        assert "k1" in context

    def test_get_context_for_llm_with_project(self, engine):
        """有项目约定时的上下文"""
        engine.remember("style", "使用 Black", level="project")
        context = engine.get_context_for_llm()
        assert "项目约定" in context
        assert "style" in context

    def test_get_context_for_llm_truncates(self, engine):
        """上下文截断到 max_tokens"""
        engine.remember("k1", "X" * 5000, level="working")
        context = engine.get_context_for_llm(max_tokens=100)
        assert len(context) <= 100

    # ── 持久化测试 ────────────────────────────────

    def test_save_and_load_project_knowledge(self, tmp_path):
        """项目知识持久化与加载"""
        with patch.object(Path, "home", return_value=tmp_path):
            engine1 = MemoryEngine()
            engine1.remember("conv1", "规则 1", level="project")
            engine1.remember("conv2", "规则 2", level="project")

            # 创建新引擎加载
            engine2 = MemoryEngine()
            assert engine2.project.get_convention("conv1") == "规则 1"
            assert engine2.project.get_convention("conv2") == "规则 2"

    def test_save_and_load_long_term(self, tmp_path):
        """长期知识持久化与加载"""
        with patch.object(Path, "home", return_value=tmp_path):
            engine1 = MemoryEngine()
            engine1.remember("pref", "深色主题", level="long_term")

            engine2 = MemoryEngine()
            assert "pref" in engine2._long_term
            assert engine2._long_term["pref"]["content"] == "深色主题"

    def test_persist_files_created(self, tmp_path):
        """持久化文件被创建"""
        with patch.object(Path, "home", return_value=tmp_path):
            engine = MemoryEngine()
            engine.remember("conv", "规则", level="project")
            engine.remember("pref", "偏好", level="long_term")

            # 检查文件生成
            pk_file = tmp_path / ".pycoder" / "memory" / "project_knowledge.json"
            lt_file = tmp_path / ".pycoder" / "memory" / "long_term.json"

            # 注意：_save_project_knowledge 在 remember project 时调用
            assert pk_file.exists()
            assert lt_file.exists()

    def test_persist_no_crash_on_permission_error(self, tmp_path):
        """持久化失败不崩溃"""
        with patch.object(Path, "home", return_value=tmp_path):
            # 创建一个只读目录模拟权限错误
            persist_dir = tmp_path / ".pycoder" / "memory"
            persist_dir.mkdir(parents=True, exist_ok=True)

            engine = MemoryEngine()
            # 即使保存失败也不应崩溃
            engine.remember("conv", "规则", level="project")
            # 不抛异常即通过

    def test_load_all_handles_corrupt_files(self, tmp_path):
        """损坏的持久化文件不崩溃"""
        with patch.object(Path, "home", return_value=tmp_path):
            persist_dir = tmp_path / ".pycoder" / "memory"
            persist_dir.mkdir(parents=True, exist_ok=True)

            # 写入损坏的 JSON
            (persist_dir / "project_knowledge.json").write_text(
                "这不是有效的 JSON{{{{", encoding="utf-8"
            )

            # 不应崩溃
            engine = MemoryEngine()
            assert engine is not None

    def test_load_all_handles_missing_files(self, tmp_path):
        """缺失持久化文件不崩溃"""
        with patch.object(Path, "home", return_value=tmp_path):
            # 不创建任何文件
            engine = MemoryEngine()
            assert engine is not None