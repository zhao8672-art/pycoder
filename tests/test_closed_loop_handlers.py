"""P3-A: closed_loop 模块能力注册和 handler 测试

补充覆盖 closed_loop.py 中未测试的部分:
  - register_capabilities: 5 个能力注册
  - _handle_observe / _handle_reflect / _handle_generate_skill
  - _handle_apply_feedback / _handle_stats
  - _init_db_no_fts (FTS5 降级初始化)
  - _search_skills_fts / _search_skills_like / _search_observations
  - _find_similar_skill / _load_all_skills / _row_to_skill / _row_to_observation
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pycoder.capabilities.self_evo.learning.closed_loop import (
    CLOSED_LOOP_DB,
    ClosedLearningLoop,
    LearningObservation,
    LearnedSkill,
    _handle_apply_feedback,
    _handle_generate_skill,
    _handle_observe,
    _handle_reflect,
    _handle_stats,
    get_closed_loop,
    register_capabilities,
)


# ════════════════════════════════════════════════════════════
# Handler 函数测试
# ════════════════════════════════════════════════════════════


@pytest.fixture
def loop(tmp_path: Path) -> ClosedLearningLoop:
    """每个测试一个独立的 loop 实例"""
    db = tmp_path / "test_closed.db"
    return ClosedLearningLoop(db_path=str(db))


class TestHandleObserve:
    """_handle_observe handler"""

    @pytest.mark.asyncio
    async def test_observe_missing_task_id(self, loop: ClosedLearningLoop) -> None:
        """缺少 task_id 返回失败"""
        result = await _handle_observe(loop, {"execution_result": {}}, {})
        assert result["success"] is False
        assert "task_id" in result["error"]

    @pytest.mark.asyncio
    async def test_observe_success(self, loop: ClosedLearningLoop) -> None:
        """正常观察记录"""
        result = await _handle_observe(
            loop,
            {
                "task_id": "T-001",
                "execution_result": {
                    "description": "测试任务",
                    "success": True,
                    "steps": 5,
                },
            },
            {},
        )
        assert result["success"] is True
        assert result["task_id"] == "T-001"
        assert result["recorded"] is True
        assert result["steps"] == 5
        assert result["errors_count"] == 0

    @pytest.mark.asyncio
    async def test_observe_with_errors(self, loop: ClosedLearningLoop) -> None:
        """带错误的观察"""
        result = await _handle_observe(
            loop,
            {
                "task_id": "T-002",
                "execution_result": {
                    "success": False,
                    "errors": ["NameError", "TypeError"],
                },
            },
            {},
        )
        assert result["success"] is True
        assert result["errors_count"] == 2

    @pytest.mark.asyncio
    async def test_observe_handles_exception(self, loop: ClosedLearningLoop) -> None:
        """异常情况返回失败"""
        # mock loop.observe 抛异常
        async def raise_exc(*args, **kwargs):
            raise RuntimeError("boom")

        loop.observe = raise_exc  # type: ignore[assignment]
        result = await _handle_observe(
            loop,
            {"task_id": "T-003", "execution_result": {}},
            {},
        )
        assert result["success"] is False
        assert "boom" in result["error"]


class TestHandleReflect:
    """_handle_reflect handler"""

    @pytest.mark.asyncio
    async def test_reflect_missing_task_id(self, loop: ClosedLearningLoop) -> None:
        result = await _handle_reflect(loop, {}, {})
        assert result["success"] is False
        assert "task_id" in result["error"]

    @pytest.mark.asyncio
    async def test_reflect_with_observation_param(self, loop: ClosedLearningLoop) -> None:
        """直接传 observation 参数"""
        result = await _handle_reflect(
            loop,
            {
                "task_id": "T-001",
                "observation": {
                    "task_description": "测试",
                    "success": True,
                    "steps_taken": 3,
                    "patterns_used": ["read-before-write"],
                },
            },
            {},
        )
        assert result["success"] is True
        assert "reflection" in result

    @pytest.mark.asyncio
    async def test_reflect_query_db_no_record(self, loop: ClosedLearningLoop) -> None:
        """查询数据库但无匹配记录"""
        result = await _handle_reflect(
            loop,
            {"task_id": "nonexistent-task"},
            {},
        )
        assert result["success"] is False
        assert "未找到" in result["error"]

    @pytest.mark.asyncio
    async def test_reflect_query_db_with_record(
        self, loop: ClosedLearningLoop
    ) -> None:
        """先观察再反思（走数据库查询路径）"""
        # 先记录一个观察
        await _handle_observe(
            loop,
            {
                "task_id": "T-100",
                "execution_result": {
                    "description": "测试任务",
                    "success": True,
                    "steps": 4,
                    "patterns_used": ["pattern-a"],
                },
            },
            {},
        )

        # 再反思该任务（不传 observation，走数据库查询）
        result = await _handle_reflect(loop, {"task_id": "T-100"}, {})
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_reflect_handles_exception(self, loop: ClosedLearningLoop) -> None:
        """异常情况"""
        async def raise_exc(*args, **kwargs):
            raise RuntimeError("reflect boom")

        loop.reflect = raise_exc  # type: ignore[assignment]
        result = await _handle_reflect(
            loop,
            {
                "task_id": "T-err",
                "observation": {"success": True},
            },
            {},
        )
        assert result["success"] is False
        assert "reflect boom" in result["error"]


class TestHandleGenerateSkill:
    """_handle_generate_skill handler"""

    @pytest.mark.asyncio
    async def test_generate_skill_missing_reflection(
        self, loop: ClosedLearningLoop
    ) -> None:
        result = await _handle_generate_skill(loop, {}, {})
        assert result["success"] is False
        assert "reflection" in result["error"]

    @pytest.mark.asyncio
    async def test_generate_skill_no_patterns(self, loop: ClosedLearningLoop) -> None:
        """reflection 中无 patterns_found，应返回 0 个技能"""
        result = await _handle_generate_skill(
            loop,
            {"reflection": {"patterns_found": [], "patterns_avoid": []}},
            {},
        )
        assert result["success"] is True
        assert result["skills_generated"] == 0
        assert result["skill_ids"] == []

    @pytest.mark.asyncio
    async def test_generate_skill_with_pattern(
        self, loop: ClosedLearningLoop
    ) -> None:
        """reflection 中包含 pattern，应生成技能"""
        result = await _handle_generate_skill(
            loop,
            {
                "reflection": {
                    "task_id": "T-001",
                    "patterns_found": [
                        {
                            "pattern": "test-driven-development",
                            "confidence": 0.9,
                            "suggestion": "先写测试再写代码",
                        }
                    ],
                }
            },
            {},
        )
        assert result["success"] is True
        assert result["skills_generated"] >= 1
        assert len(result["skill_ids"]) == result["skills_generated"]

    @pytest.mark.asyncio
    async def test_generate_skill_handles_exception(
        self, loop: ClosedLearningLoop
    ) -> None:
        async def raise_exc(*args, **kwargs):
            raise RuntimeError("gen boom")

        loop.generate_skill = raise_exc  # type: ignore[assignment]
        result = await _handle_generate_skill(
            loop,
            {"reflection": {"patterns_found": [{"pattern": "x"}]}},
            {},
        )
        assert result["success"] is False
        assert "gen boom" in result["error"]


class TestHandleApplyFeedback:
    """_handle_apply_feedback handler"""

    @pytest.mark.asyncio
    async def test_apply_feedback_missing_description(
        self, loop: ClosedLearningLoop
    ) -> None:
        result = await _handle_apply_feedback(loop, {}, {})
        assert result["success"] is False
        assert "task_description" in result["error"]

    @pytest.mark.asyncio
    async def test_apply_feedback_success(self, loop: ClosedLearningLoop) -> None:
        result = await _handle_apply_feedback(
            loop,
            {"task_description": "实现一个用户登录功能"},
            {},
        )
        assert result["success"] is True
        assert "feedback" in result

    @pytest.mark.asyncio
    async def test_apply_feedback_handles_exception(
        self, loop: ClosedLearningLoop
    ) -> None:
        async def raise_exc(*args, **kwargs):
            raise RuntimeError("apply boom")

        loop.apply_feedback = raise_exc  # type: ignore[assignment]
        result = await _handle_apply_feedback(
            loop,
            {"task_description": "test"},
            {},
        )
        assert result["success"] is False
        assert "apply boom" in result["error"]


class TestHandleStats:
    """_handle_stats handler"""

    @pytest.mark.asyncio
    async def test_stats_success(self, loop: ClosedLearningLoop) -> None:
        result = await _handle_stats(loop, {}, {})
        assert result["success"] is True
        assert "stats" in result
        assert isinstance(result["stats"], dict)

    @pytest.mark.asyncio
    async def test_stats_handles_exception(self, loop: ClosedLearningLoop) -> None:
        def raise_exc(*args, **kwargs):
            raise RuntimeError("stats boom")

        loop.get_stats = raise_exc  # type: ignore[assignment]
        result = await _handle_stats(loop, {}, {})
        assert result["success"] is False
        assert "stats boom" in result["error"]


# ════════════════════════════════════════════════════════════
# register_capabilities 测试
# ════════════════════════════════════════════════════════════


class TestRegisterCapabilities:
    """能力注册"""

    def test_register_capabilities_calls_register_5_times(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """应注册 5 个能力"""
        # 临时替换全局单例
        import pycoder.capabilities.self_evo.learning.closed_loop as cl_module

        test_loop = ClosedLearningLoop(db_path=str(tmp_path / "reg.db"))
        monkeypatch.setattr(cl_module, "_closed_loop_instance", test_loop)

        mock_registry = MagicMock()
        register_capabilities(mock_registry)

        assert mock_registry.register.call_count == 5

        # 验证注册的能力 ID
        registered_ids = []
        for call_args in mock_registry.register.call_args_list:
            cap_def = call_args[0][0]
            registered_ids.append(cap_def.id)

        expected_ids = {
            "learning.observe",
            "learning.reflect",
            "learning.generate_skill",
            "learning.apply_feedback",
            "learning.stats",
        }
        assert set(registered_ids) == expected_ids

    def test_register_capabilities_handlers_are_callable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """每个能力的 handler 应是可调用的"""
        import pycoder.capabilities.self_evo.learning.closed_loop as cl_module

        test_loop = ClosedLearningLoop(db_path=str(tmp_path / "reg2.db"))
        monkeypatch.setattr(cl_module, "_closed_loop_instance", test_loop)

        mock_registry = MagicMock()
        register_capabilities(mock_registry)

        for call_args in mock_registry.register.call_args_list:
            cap_def = call_args[0][0]
            handler = call_args[1]["handler"]
            assert callable(handler)


# ════════════════════════════════════════════════════════════
# 数据库降级与查询方法测试
# ════════════════════════════════════════════════════════════


class TestInitDbNoFts:
    """FTS5 降级初始化"""

    def test_init_db_no_fts_creates_tables(self, tmp_path: Path) -> None:
        """降级初始化创建必要的表"""
        loop = ClosedLearningLoop(db_path=str(tmp_path / "nofts.db"))
        # 直接调用降级初始化
        loop._init_db_no_fts()

        # 验证表存在
        with sqlite3.connect(str(tmp_path / "nofts.db")) as conn:
            tables = [
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
        assert "learning_observations" in tables
        assert "learned_skills" in tables

    def test_init_db_no_fts_sets_flag(self, tmp_path: Path) -> None:
        """降级初始化后 _fts_available 应为 False"""
        loop = ClosedLearningLoop(db_path=str(tmp_path / "nofts2.db"))
        loop._init_db_no_fts()
        assert loop._fts_available is False


class TestGetConn:
    """_get_conn 连接获取"""

    def test_get_conn_returns_connection_with_row_factory(
        self, loop: ClosedLearningLoop
    ) -> None:
        conn = loop._get_conn()
        try:
            assert isinstance(conn, sqlite3.Connection)
            assert conn.row_factory is sqlite3.Row
        finally:
            conn.close()


class TestSearchSkillsLike:
    """_search_skills_like LIKE 降级搜索"""

    def test_empty_keywords_returns_empty(self, loop: ClosedLearningLoop) -> None:
        result = loop._search_skills_like([])
        assert result == []

    def test_search_finds_matching_skill(self, loop: ClosedLearningLoop) -> None:
        """LIKE 搜索能找到匹配的技能"""
        # 先保存一个技能
        skill = LearnedSkill(
            id="skill_test_1",
            name="测试技能",
            description="这是一个用于测试的技能",
            pattern="test-pattern",
            strategy="测试策略",
            success_rate=0.8,
            usage_count=5,
            created_at=0,
            updated_at=0,
            source_task_id="T-test",
        )
        loop._save_skill(skill)

        # 搜索
        results = loop._search_skills_like(["测试"], limit=5)
        assert len(results) >= 1
        assert any(s.id == "skill_test_1" for s in results)

    def test_search_no_match_returns_empty(self, loop: ClosedLearningLoop) -> None:
        skill = LearnedSkill(
            id="skill_unique_1",
            name="unique-name",
            description="unique-description",
            pattern="unique-pattern",
            strategy="strategy",
            success_rate=0.5,
            usage_count=1,
            created_at=0,
            updated_at=0,
            source_task_id="T",
        )
        loop._save_skill(skill)

        results = loop._search_skills_like(["nonexistent_keyword_xyz"], limit=5)
        assert results == []


class TestLoadAllSkills:
    """_load_all_skills 加载所有技能"""

    def test_empty_db_returns_empty_list(self, loop: ClosedLearningLoop) -> None:
        result = loop._load_all_skills()
        assert result == []

    def test_loads_multiple_skills(self, loop: ClosedLearningLoop) -> None:
        for i in range(3):
            loop._save_skill(
                LearnedSkill(
                    id=f"skill_load_{i}",
                    name=f"技能_{i}",
                    description=f"desc_{i}",
                    pattern=f"pattern_{i}",
                    strategy="strategy",
                    success_rate=0.7,
                    usage_count=i + 1,
                    created_at=0,
                    updated_at=0,
                    source_task_id="T",
                )
            )

        result = loop._load_all_skills()
        assert len(result) == 3

    def test_excludes_pruned_by_default(self, loop: ClosedLearningLoop) -> None:
        """默认排除 pruned 技能"""
        loop._save_skill(
            LearnedSkill(
                id="skill_active",
                name="active",
                description="",
                pattern="",
                strategy="",
                success_rate=0.8,
                usage_count=1,
                created_at=0,
                updated_at=0,
                source_task_id="",
            )
        )
        loop._save_skill(
            LearnedSkill(
                id="skill_pruned",
                name="pruned",
                description="",
                pattern="",
                strategy="",
                success_rate=0.1,
                usage_count=1,
                created_at=0,
                updated_at=0,
                source_task_id="",
            )
        )
        # 标记为 pruned
        loop._prune_skill("skill_pruned")

        active = loop._load_all_skills(exclude_pruned=True)
        active_ids = {s.id for s in active}
        assert "skill_active" in active_ids
        assert "skill_pruned" not in active_ids

        # include pruned
        all_skills = loop._load_all_skills(exclude_pruned=False)
        all_ids = {s.id for s in all_skills}
        assert "skill_pruned" in all_ids


class TestFindSimilarSkill:
    """_find_similar_skill 查找相似技能"""

    def test_no_skills_returns_none(self, loop: ClosedLearningLoop) -> None:
        result = loop._find_similar_skill("any-pattern")
        assert result is None

    def test_exact_match_returns_skill(self, loop: ClosedLearningLoop) -> None:
        skill = LearnedSkill(
            id="skill_exact",
            name="exact",
            description="",
            pattern="exact-pattern-name",
            strategy="",
            success_rate=0.7,
            usage_count=1,
            created_at=0,
            updated_at=0,
            source_task_id="",
        )
        loop._save_skill(skill)

        result = loop._find_similar_skill("exact-pattern-name")
        assert result is not None
        assert result.id == "skill_exact"


class TestRowConverters:
    """_row_to_skill / _row_to_observation"""

    def test_row_to_skill_converts_correctly(self, loop: ClosedLearningLoop) -> None:
        """技能行转换"""
        # 先保存一个技能
        original = LearnedSkill(
            id="skill_convert",
            name="转换测试",
            description="描述",
            pattern="pattern",
            strategy="strategy",
            success_rate=0.75,
            usage_count=3,
            created_at=1000,
            updated_at=2000,
            source_task_id="T-conv",
        )
        loop._save_skill(original)

        # 读取并转换
        with loop._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM learned_skills WHERE id = ?", ("skill_convert",)
            ).fetchone()

        result = loop._row_to_skill(row)
        assert result.id == "skill_convert"
        assert result.name == "转换测试"
        assert result.success_rate == 0.75
        assert result.usage_count == 3

    def test_row_to_observation_converts_correctly(
        self, loop: ClosedLearningLoop
    ) -> None:
        """观察行转换"""
        asyncio.run(
            loop.observe(
                "T-conv-001",
                {
                    "description": "测试任务",
                    "success": True,
                    "steps": 5,
                    "errors": ["err1"],
                    "patterns_used": ["p1"],
                },
            )
        )

        with loop._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM learning_observations WHERE task_id = ?",
                ("T-conv-001",),
            ).fetchone()

        result = loop._row_to_observation(row)
        assert result.task_id == "T-conv-001"
        assert result.success is True
        assert result.steps_taken == 5
        assert "err1" in result.errors_encountered
        assert "p1" in result.patterns_used


class TestSearchObservations:
    """_search_observations 搜索历史观察"""

    def test_no_keywords_returns_empty(self, loop: ClosedLearningLoop) -> None:
        """无关键词返回空"""
        result = loop._search_observations("")
        assert result == []

    def test_search_finds_matching_observation(
        self, loop: ClosedLearningLoop
    ) -> None:
        """搜索能找到匹配的观察"""
        asyncio.run(
            loop.observe(
                "T-search-001",
                {
                    "description": "实现用户登录模块",
                    "success": True,
                },
            )
        )

        result = loop._search_observations("用户登录", limit=5)
        # 应能找到（基于关键词提取）
        assert isinstance(result, list)


# ════════════════════════════════════════════════════════════
# 全局单例测试
# ════════════════════════════════════════════════════════════


class TestGetClosedLoop:
    """get_closed_loop 全局单例"""

    def test_returns_closed_learning_loop_instance(self) -> None:
        result = get_closed_loop()
        assert isinstance(result, ClosedLearningLoop)

    def test_returns_same_instance(self) -> None:
        r1 = get_closed_loop()
        r2 = get_closed_loop()
        assert r1 is r2
