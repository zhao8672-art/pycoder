from __future__ import annotations

import json
import os
import sys
import time
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════
# 1. memory_bank.py 测试
# ═══════════════════════════════════════════════════════════════


class TestMemoryBank:
    """MemoryBank 持久记忆管理器测试"""

    @pytest.fixture
    def memory_bank(self, tmp_path: Path):
        """创建基于临时目录的 MemoryBank 实例"""
        from pycoder.server.memory_bank import MemoryBank, reset_memory_bank

        reset_memory_bank()
        mb = MemoryBank(workspace=tmp_path)
        return mb

    @pytest.fixture
    def populated_bank(self, memory_bank):
        """预填充的 MemoryBank 实例"""
        memory_bank.update_project_brief("这是一个测试项目")
        memory_bank.record_architecture_decision(
            "使用 FastAPI",
            "选择 FastAPI 作为 Web 框架",
            "高性能、异步支持、类型安全",
        )
        memory_bank.update_tech_context("Python 3.14", "FastAPI, pytest")
        memory_bank.set_active_context("正在实现用户认证模块", ["src/auth.py", "src/models.py"])
        memory_bank.update_progress("IN_PROGRESS", "用户认证 API 开发中")
        return memory_bank

    # ── 初始化 ──

    def test_init_creates_memory_directory(self, tmp_path: Path):
        """初始化时应创建 .pycoder/memory 目录"""
        from pycoder.server.memory_bank import MemoryBank, reset_memory_bank

        reset_memory_bank()
        MemoryBank(workspace=tmp_path)
        assert (tmp_path / ".pycoder" / "memory").exists()
        assert (tmp_path / ".pycoder" / "memory").is_dir()

    def test_memory_files_dict_has_expected_keys(self):
        """MEMORY_FILES 应包含预期的记忆文件键"""
        from pycoder.server.memory_bank import MemoryBank

        expected_keys = ["project_brief", "architecture", "tech_context", "active_context", "progress"]
        for key in expected_keys:
            assert key in MemoryBank.MEMORY_FILES

    def test_load_order_has_correct_priority(self):
        """LOAD_ORDER 应按正确的优先级排序"""
        from pycoder.server.memory_bank import MemoryBank

        assert MemoryBank.LOAD_ORDER == ["project_brief", "architecture", "tech_context", "active_context"]

    # ── 上下文加载 ──

    def test_load_context_empty_bank_returns_empty(self, memory_bank):
        """空记忆库加载上下文应返回空字符串"""
        result = memory_bank.load_context_for_prompt()
        assert result == ""

    def test_load_context_returns_header_and_content(self, populated_bank):
        """加载上下文应包含 header 和记忆内容"""
        result = populated_bank.load_context_for_prompt(max_tokens=5000)
        assert "<!-- Memory Bank" in result
        assert "测试项目" in result
        assert "FastAPI" in result
        assert "Python 3.14" in result

    def test_load_context_respects_max_tokens_and_truncates(self, populated_bank):
        """加载上下文应在超过 max_tokens 时截断"""
        result = populated_bank.load_context_for_prompt(max_tokens=20)
        # 20 tokens 只能容纳很少的内容
        assert len(result) < 500

    def test_load_context_skips_missing_files(self, memory_bank):
        """缺失的文件不应影响加载"""
        memory_bank.update_project_brief("只有项目概述")
        result = memory_bank.load_context_for_prompt(max_tokens=5000)
        assert "只有项目概述" in result
        assert "<!-- Memory Bank" in result

    # ── getter 方法 ──

    def test_get_project_brief(self, memory_bank):
        """get_project_brief 应返回项目概述"""
        memory_bank.update_project_brief("我的项目")
        result = memory_bank.get_project_brief()
        assert "我的项目" in result

    def test_get_project_brief_empty(self, memory_bank):
        """空项目概述应返回空字符串"""
        assert memory_bank.get_project_brief() == ""

    def test_get_architecture(self, memory_bank):
        """get_architecture 应返回架构文档"""
        memory_bank.record_architecture_decision("测试", "决策", "理由")
        result = memory_bank.get_architecture()
        assert "测试" in result
        assert "决策" in result

    def test_get_architecture_empty(self, memory_bank):
        """空架构文档应返回空字符串"""
        assert memory_bank.get_architecture() == ""

    def test_get_progress(self, memory_bank):
        """get_progress 应返回进度日志"""
        memory_bank.update_progress("DONE", "完成测试")
        result = memory_bank.get_progress()
        assert "DONE" in result
        assert "完成测试" in result

    def test_get_progress_empty(self, memory_bank):
        """空进度日志应返回空字符串"""
        assert memory_bank.get_progress() == ""

    # ── 更新方法 ──

    def test_update_project_brief(self, memory_bank):
        """更新项目概述应写入文件"""
        memory_bank.update_project_brief("全新的项目概述")
        content = memory_bank.get_project_brief()
        assert "全新的项目概述" in content
        assert "Project Brief" in content

    def test_update_project_brief_overwrites(self, memory_bank):
        """重复更新项目概述应覆盖旧内容"""
        memory_bank.update_project_brief("旧内容")
        memory_bank.update_project_brief("新内容")
        content = memory_bank.get_project_brief()
        assert "新内容" in content
        assert "旧内容" not in content

    def test_record_architecture_decision_appends(self, memory_bank):
        """记录架构决策应追加到现有文档"""
        memory_bank.record_architecture_decision("决策1", "使用 SQLite", "简单")
        memory_bank.record_architecture_decision("决策2", "使用 FastAPI", "异步")
        content = memory_bank.get_architecture()
        assert "决策1" in content
        assert "决策2" in content

    def test_record_architecture_decision_includes_fields(self, memory_bank):
        """架构决策记录应包含决策、理由、日期"""
        memory_bank.record_architecture_decision("测试决策", "选择方案A", "因为方案A更好")
        content = memory_bank.get_architecture()
        assert "测试决策" in content
        assert "选择方案A" in content
        assert "因为方案A更好" in content
        assert "日期:" in content

    def test_update_tech_context_with_dependencies(self, memory_bank):
        """更新技术栈上下文应包含依赖"""
        memory_bank.update_tech_context("Python 3.14", "pytest, fastapi")
        content = memory_bank._read("tech_context.md")
        assert "Python 3.14" in content
        assert "pytest, fastapi" in content

    def test_update_tech_context_without_dependencies(self, memory_bank):
        """更新技术栈上下文（无依赖）应正常"""
        memory_bank.update_tech_context("Python 3.14")
        content = memory_bank._read("tech_context.md")
        assert "Python 3.14" in content
        assert "## 依赖" not in content

    def test_set_active_context_with_files(self, memory_bank):
        """设置活跃上下文（含文件列表）应包含文件"""
        memory_bank.set_active_context("正在开发", ["a.py", "b.py"])
        content = memory_bank._read("active_context.md")
        assert "正在开发" in content
        assert "a.py" in content
        assert "b.py" in content

    def test_set_active_context_without_files(self, memory_bank):
        """设置活跃上下文（无文件列表）应正常"""
        memory_bank.set_active_context("正在开发")
        content = memory_bank._read("active_context.md")
        assert "正在开发" in content
        assert "## 相关文件" not in content

    def test_update_progress_appends(self, memory_bank):
        """更新进度应追加到日志"""
        memory_bank.update_progress("START", "开始任务")
        memory_bank.update_progress("DONE", "完成任务")
        content = memory_bank.get_progress()
        assert "START" in content
        assert "DONE" in content
        assert "开始任务" in content
        assert "完成任务" in content

    def test_mark_completed(self, memory_bank):
        """mark_completed 应标记任务为 COMPLETED"""
        memory_bank.mark_completed("用户认证")
        content = memory_bank.get_progress()
        assert "COMPLETED" in content

    def test_clear_active_context(self, memory_bank):
        """clear_active_context 应清除活跃上下文"""
        memory_bank.set_active_context("正在开发", ["a.py"])
        memory_bank.clear_active_context()
        content = memory_bank._read("active_context.md")
        assert content == "" or content == "\n" or content == ""

    # ── 查询方法 ──

    def test_has_memory_false_when_empty(self, memory_bank):
        """空记忆库时 has_memory 应返回 False"""
        assert memory_bank.has_memory() is False

    def test_has_memory_true_when_has_content(self, populated_bank):
        """有记忆内容时 has_memory 应返回 True"""
        assert populated_bank.has_memory() is True

    def test_list_memories_empty(self, memory_bank):
        """空记忆库时 list_memories 应返回空列表"""
        assert memory_bank.list_memories() == []

    def test_list_memories_with_content(self, populated_bank):
        """有记忆内容时 list_memories 应返回文件信息"""
        memories = populated_bank.list_memories()
        assert len(memories) >= 1
        for m in memories:
            assert "key" in m
            assert "file" in m
            assert "size" in m

    def test_list_memories_skips_missing_files(self, memory_bank):
        """list_memories 应只返回存在的文件"""
        memory_bank.update_project_brief("测试")
        memories = memory_bank.list_memories()
        # 只有 project_brief 文件存在
        brief_memories = [m for m in memories if m["key"] == "project_brief"]
        assert len(brief_memories) == 1


class TestNowHelper:
    """_now() 辅助函数测试"""

    def test_now_returns_valid_format(self):
        """_now 应返回 UTC 格式的时间字符串"""
        from pycoder.server.memory_bank import _now

        result = _now()
        assert "UTC" in result
        # 格式: YYYY-MM-DD HH:MM UTC
        assert len(result) > 10


class TestMemoryBankSingleton:
    """MemoryBank 单例管理测试"""

    def test_get_memory_bank_returns_singleton(self, tmp_path: Path):
        """get_memory_bank 应返回单例"""
        from pycoder.server.memory_bank import get_memory_bank, reset_memory_bank

        reset_memory_bank()
        mb1 = get_memory_bank(workspace=tmp_path)
        mb2 = get_memory_bank(workspace=tmp_path)
        assert mb1 is mb2

    def test_reset_memory_bank_clears_singleton(self, tmp_path: Path):
        """reset_memory_bank 应清除单例"""
        from pycoder.server.memory_bank import get_memory_bank, reset_memory_bank

        reset_memory_bank()
        mb1 = get_memory_bank(workspace=tmp_path)
        reset_memory_bank()
        mb2 = get_memory_bank(workspace=tmp_path)
        assert mb1 is not mb2


