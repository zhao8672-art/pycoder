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
# 模块 2: closed_loop.py — 数据模型
# ═══════════════════════════════════════════════════════════════


class TestLearningObservation:
    """LearningObservation 数据类测试"""

    def test_creation(self):
        """创建观察对象"""
        from pycoder.capabilities.self_evo.learning.closed_loop import LearningObservation

        obs = LearningObservation(task_id="T001")
        assert obs.task_id == "T001"
        assert obs.success is False
        assert obs.steps_taken == 0
        assert obs.errors_encountered == []
        assert obs.patterns_used == []
        assert obs.patterns_failed == []

    def test_full_fields(self):
        """完整字段"""
        from pycoder.capabilities.self_evo.learning.closed_loop import LearningObservation

        obs = LearningObservation(
            task_id="T002", task_description="测试任务", success=True, steps_taken=5,
            errors_encountered=["err1"], patterns_used=["pat1"], patterns_failed=["pat2"],
            metadata={"key": "val"},
        )
        assert obs.success is True
        assert obs.steps_taken == 5
        assert obs.errors_encountered == ["err1"]
        assert obs.metadata == {"key": "val"}


class TestLearnedSkill:
    """LearnedSkill 数据类测试"""

    def test_creation(self):
        """创建技能对象"""
        from pycoder.capabilities.self_evo.learning.closed_loop import LearnedSkill

        skill = LearnedSkill(name="test_skill", pattern="test_pattern")
        assert skill.name == "test_skill"
        assert skill.pattern == "test_pattern"
        assert skill.success_rate == 0.0
        assert skill.usage_count == 0
        assert skill.pruned is False

    def test_pruned_flag(self):
        """已淘汰标记"""
        from pycoder.capabilities.self_evo.learning.closed_loop import LearnedSkill

        skill = LearnedSkill(pruned=True)
        assert skill.pruned is True


# ═══════════════════════════════════════════════════════════════
# 模块 2: closed_loop.py — ClosedLearningLoop
# ═══════════════════════════════════════════════════════════════


class TestClosedLearningLoopInit:
    """ClosedLearningLoop 初始化测试"""

    def test_init_with_tmp_db(self, tmp_path):
        """用临时数据库初始化"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "test.db"
        loop = ClosedLearningLoop(db_path=db_path)
        assert Path(loop._db_path) == db_path
        assert db_path.exists()

    def test_ensure_list_static(self):
        """_ensure_list 静态方法"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        assert ClosedLearningLoop._ensure_list(["a", "b"]) == ["a", "b"]
        assert ClosedLearningLoop._ensure_list("hello") == ["hello"]
        assert ClosedLearningLoop._ensure_list(123) == []

    def test_extract_keywords(self):
        """_extract_keywords 静态方法"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        keywords = ClosedLearningLoop._extract_keywords("fix the python bug in server")
        assert "python" in keywords
        assert "bug" in keywords
        assert "server" in keywords
        # 停用词应被过滤
        assert "the" not in keywords
        assert "in" not in keywords

    def test_extract_keywords_empty(self):
        """空字符串提取关键词"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        assert ClosedLearningLoop._extract_keywords("") == []

    def test_derive_skill_name(self):
        """_derive_skill_name 静态方法"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        name = ClosedLearningLoop._derive_skill_name("type:my_pattern", {})
        assert name == "my_pattern"

    def test_derive_skill_name_long(self):
        """长模式截断"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        long_pattern = "x" * 100
        name = ClosedLearningLoop._derive_skill_name(long_pattern, {})
        assert len(name) <= 83  # 80 + "..."

    def test_row_to_skill(self):
        """_row_to_skill 静态方法"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        row = {
            "id": "s1", "name": "test", "description": "", "pattern": "", "strategy": "",
            "success_rate": 0.8, "usage_count": 5, "created_at": 0.0, "updated_at": 0.0,
            "source_task_id": "", "pruned": 0,
        }
        skill = ClosedLearningLoop._row_to_skill(row)
        assert skill.id == "s1"
        assert skill.success_rate == 0.8
        assert skill.pruned is False


class TestClosedLearningLoopObserve:
    """观察方法测试"""

    @pytest.mark.asyncio
    async def test_observe_success(self, tmp_path):
        """记录成功观察"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "obs.db"
        loop = ClosedLearningLoop(db_path=db_path)
        obs = await loop.observe("T001", {
            "description": "测试", "success": True, "steps": 3,
            "errors": [], "patterns_used": ["pat1"], "patterns_failed": [],
        })
        assert obs.task_id == "T001"
        assert obs.success is True
        assert obs.steps_taken == 3

    @pytest.mark.asyncio
    async def test_observe_failure(self, tmp_path):
        """记录失败观察"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "obs2.db"
        loop = ClosedLearningLoop(db_path=db_path)
        obs = await loop.observe("T002", {
            "success": False, "errors": ["NameError"],
        })
        assert obs.success is False
        assert obs.errors_encountered == ["NameError"]


class TestClosedLearningLoopReflect:
    """反思方法测试"""

    @pytest.mark.asyncio
    async def test_reflect_success(self, tmp_path):
        """反思成功任务"""
        from pycoder.capabilities.self_evo.learning.closed_loop import (
            ClosedLearningLoop, LearningObservation,
        )

        db_path = tmp_path / "reflect.db"
        loop = ClosedLearningLoop(db_path=db_path)
        obs = LearningObservation(
            task_id="T001", success=True, steps_taken=2,
            patterns_used=["pattern_a"], patterns_failed=[],
        )
        reflection = await loop.reflect(obs)
        assert reflection["task_id"] == "T001"
        assert reflection["success"] is True
        assert "confidence" in reflection
        assert "recommendations" in reflection

    @pytest.mark.asyncio
    async def test_reflect_failure(self, tmp_path):
        """反思失败任务"""
        from pycoder.capabilities.self_evo.learning.closed_loop import (
            ClosedLearningLoop, LearningObservation,
        )

        db_path = tmp_path / "reflect2.db"
        loop = ClosedLearningLoop(db_path=db_path)
        obs = LearningObservation(
            task_id="T002", success=False, errors_encountered=["TypeError"],
        )
        reflection = await loop.reflect(obs)
        assert reflection["success"] is False
        assert len(reflection["patterns_avoid"]) >= 0


class TestClosedLearningLoopGenerateSkill:
    """技能生成测试"""

    @pytest.mark.asyncio
    async def test_generate_skill_from_reflection(self, tmp_path):
        """从反思生成技能"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "skill.db"
        loop = ClosedLearningLoop(db_path=db_path)
        reflection = {
            "task_id": "T001",
            "patterns_found": [
                {"pattern": "fix_bare_except", "confidence": 0.9,
                 "suggestion": "使用 except Exception"},
            ],
            "patterns_avoid": [],
        }
        skills = await loop.generate_skill(reflection)
        assert len(skills) >= 1
        assert skills[0].success_rate == 0.9

    @pytest.mark.asyncio
    async def test_generate_skill_empty_patterns(self, tmp_path):
        """空模式不生成技能"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "skill2.db"
        loop = ClosedLearningLoop(db_path=db_path)
        reflection = {"task_id": "T001", "patterns_found": [], "patterns_avoid": []}
        skills = await loop.generate_skill(reflection)
        assert len(skills) == 0


class TestClosedLearningLoopApplyFeedback:
    """反馈应用测试"""

    @pytest.mark.asyncio
    async def test_apply_feedback(self, tmp_path):
        """应用反馈"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "feedback.db"
        loop = ClosedLearningLoop(db_path=db_path)
        result = await loop.apply_feedback("fix python import error")
        assert "matched_skills" in result
        assert "context_hints" in result
        assert "keywords" in result


class TestClosedLearningLoopRefineSkills:
    """技能精炼测试"""

    @pytest.mark.asyncio
    async def test_refine_skipped(self, tmp_path):
        """精炼间隔未到应跳过"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "refine.db"
        loop = ClosedLearningLoop(db_path=db_path)
        loop._last_refine_time = time.time()  # 刚刚精炼过
        result = await loop.refine_skills()
        assert result["skipped"] is True

    @pytest.mark.asyncio
    async def test_refine_triggered(self, tmp_path):
        """精炼可触发"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "refine2.db"
        loop = ClosedLearningLoop(db_path=db_path)
        loop._last_refine_time = 0  # 很久以前
        result = await loop.refine_skills()
        assert "total_skills" in result
        assert "pruned" in result


class TestClosedLearningLoopRunCycle:
    """完整闭环测试"""

    @pytest.mark.asyncio
    async def test_run_cycle(self, tmp_path):
        """运行完整闭环"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "cycle.db"
        loop = ClosedLearningLoop(db_path=db_path)
        result = await loop.run_cycle("T001", {
            "description": "测试任务", "success": True, "steps": 2,
            "patterns_used": ["pattern_a"],
        })
        assert result["task_id"] == "T001"
        assert "cycle_duration_ms" in result
        assert result["observation"]["success"] is True


class TestClosedLearningLoopGetStats:
    """统计查询测试"""

    def test_get_stats_empty(self, tmp_path):
        """空数据库统计"""
        from pycoder.capabilities.self_evo.learning.closed_loop import ClosedLearningLoop

        db_path = tmp_path / "stats.db"
        loop = ClosedLearningLoop(db_path=db_path)
        stats = loop.get_stats()
        assert stats["total_observations"] == 0
        assert stats["total_skills"] == 0


class TestGetClosedLoop:
    """全局单例测试"""

    def test_singleton(self):
        """单例模式"""
        from pycoder.capabilities.self_evo.learning.closed_loop import get_closed_loop

        loop1 = get_closed_loop()
        loop2 = get_closed_loop()
        assert loop1 is loop2


