"""
封闭学习循环单元测试 — 覆盖 ClosedLearningLoop 核心功能

测试范围:
  - ClosedLearningLoop 初始化
  - observe 阶段（收集执行跟踪）
  - reflect 阶段（分析成功/失败模式）
  - generate_skill 阶段（编码模式为技能）
  - apply_feedback 阶段（为任务注入经验）
  - run_cycle 完整闭环
  - 经验持久化（保存/加载）
  - 统计追踪
  - 错误处理（畸形跟踪、缺失数据）
  - 技能验证
  - refine_skills 精炼
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pycoder.capabilities.self_evo.learning.closed_loop import (
    ClosedLearningLoop,
    LearnedSkill,
    LearningObservation,
    get_closed_loop,
)


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def loop(tmp_path: Path) -> ClosedLearningLoop:
    """创建使用临时目录的 ClosedLearningLoop 实例"""
    db_path = tmp_path / "test_closed_loop.db"
    return ClosedLearningLoop(db_path=str(db_path))


@pytest.fixture
def success_execution() -> dict:
    """成功的执行结果"""
    return {
        "description": "实现用户认证模块",
        "success": True,
        "steps": 5,
        "errors": [],
        "patterns_used": ["factory_pattern", "dependency_injection"],
        "patterns_failed": [],
        "metadata": {"language": "python", "framework": "fastapi"},
    }


@pytest.fixture
def failure_execution() -> dict:
    """失败的执行结果"""
    return {
        "description": "修复数据库连接池泄漏",
        "success": False,
        "steps": 8,
        "errors": [
            "ConnectionError: 连接池耗尽",
            "TimeoutError: 等待连接超时",
        ],
        "patterns_used": ["connection_pool"],
        "patterns_failed": ["lazy_initialization"],
        "metadata": {"db_type": "postgresql"},
    }


# ── 初始化测试 ────────────────────────────────────────────


class TestInitialization:
    """ClosedLearningLoop 初始化"""

    def test_create_with_custom_path(self, tmp_path: Path) -> None:
        """使用自定义路径创建实例"""
        custom_path = tmp_path / "custom" / "learning.db"
        instance = ClosedLearningLoop(db_path=custom_path)
        assert instance._db_path == str(custom_path)
        assert custom_path.parent.exists()

    def test_creates_db_directory(self, tmp_path: Path) -> None:
        """自动创建数据库目录"""
        nested = tmp_path / "deeply" / "nested" / "dir" / "test.db"
        instance = ClosedLearningLoop(db_path=nested)
        assert nested.parent.exists()
        assert nested.exists()

    def test_initial_skill_cache_empty(self, loop: ClosedLearningLoop) -> None:
        """初始技能缓存为空"""
        assert len(loop._skill_cache) == 0

    def test_initial_last_refine_time_zero(self, loop: ClosedLearningLoop) -> None:
        """初始精炼时间为零"""
        assert loop._last_refine_time == 0.0

    def test_fts_fallback_on_error(self, tmp_path: Path) -> None:
        """FTS5 初始化失败时降级运行"""
        db_path = tmp_path / "no_fts.db"
        instance = ClosedLearningLoop.__new__(ClosedLearningLoop)
        instance._db_path = str(db_path)
        instance._db_dir = db_path.parent
        instance._db_dir.mkdir(parents=True, exist_ok=True)
        instance._init_db_no_fts()
        # 验证表已创建
        with instance._get_conn() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = [t[0] for t in tables]
            assert "learning_observations" in table_names
            assert "learned_skills" in table_names

    def test_default_db_path_uses_env(self, tmp_path: Path) -> None:
        """自定义路径构造器可覆盖默认数据库路径"""
        custom = tmp_path / "env_override.db"
        instance = ClosedLearningLoop(db_path=str(custom))
        assert instance._db_path == str(custom)
        assert custom.parent.exists()


# ── Observe 阶段测试 ──────────────────────────────────────


class TestObserve:
    """observe 方法 — 收集执行跟踪"""

    @pytest.mark.asyncio
    async def test_observe_success(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """观察成功的执行"""
        obs = await loop.observe("T-001", success_execution)
        assert isinstance(obs, LearningObservation)
        assert obs.task_id == "T-001"
        assert obs.success is True
        assert obs.steps_taken == 5
        assert obs.task_description == "实现用户认证模块"
        assert len(obs.patterns_used) == 2
        assert len(obs.errors_encountered) == 0

    @pytest.mark.asyncio
    async def test_observe_failure(
        self, loop: ClosedLearningLoop, failure_execution: dict,
    ) -> None:
        """观察失败的执行"""
        obs = await loop.observe("T-002", failure_execution)
        assert obs.success is False
        assert len(obs.errors_encountered) == 2
        assert len(obs.patterns_failed) == 1
        assert obs.steps_taken == 8

    @pytest.mark.asyncio
    async def test_observe_persists_to_db(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """观察记录持久化到数据库"""
        await loop.observe("T-003", success_execution)
        with loop._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM learning_observations WHERE task_id = ?",
                ("T-003",),
            ).fetchone()
            assert row is not None
            assert row["task_id"] == "T-003"
            assert row["success"] == 1

    @pytest.mark.asyncio
    async def test_observe_with_empty_result(self, loop: ClosedLearningLoop) -> None:
        """观察空执行结果"""
        obs = await loop.observe("T-empty", {})
        assert obs.task_id == "T-empty"
        assert obs.success is False
        assert obs.steps_taken == 0
        assert obs.task_description == ""

    @pytest.mark.asyncio
    async def test_observe_with_metadata(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """观察结果包含元数据"""
        obs = await loop.observe("T-meta", success_execution)
        assert obs.metadata == {"language": "python", "framework": "fastapi"}

    @pytest.mark.asyncio
    async def test_observe_converts_non_list_patterns(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """非列表模式自动转换为列表"""
        result = {
            "description": "test",
            "success": True,
            "patterns_used": "single_pattern",
            "patterns_failed": None,
            "errors": "single_error",
        }
        obs = await loop.observe("T-convert", result)
        assert obs.patterns_used == ["single_pattern"]
        assert obs.patterns_failed == []
        assert obs.errors_encountered == ["single_error"]

    @pytest.mark.asyncio
    async def test_observe_multiple_tasks(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """多次观察独立记录"""
        await loop.observe("T-A", success_execution)
        await loop.observe("T-B", success_execution)
        with loop._get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM learning_observations"
            ).fetchone()[0]
            assert count == 2

    @pytest.mark.asyncio
    async def test_observe_timestamp_is_set(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """观察记录包含时间戳"""
        before = time.time()
        obs = await loop.observe("T-ts", success_execution)
        after = time.time()
        assert before <= obs.timestamp <= after


# ── Reflect 阶段测试 ──────────────────────────────────────


class TestReflect:
    """reflect 方法 — 分析成功/失败模式"""

    @pytest.mark.asyncio
    async def test_reflect_success_with_patterns(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """反思成功的执行并发现模式"""
        obs = await loop.observe("T-010", success_execution)
        reflection = await loop.reflect(obs)
        assert reflection["task_id"] == "T-010"
        assert reflection["success"] is True
        assert len(reflection["patterns_found"]) >= 2
        assert "confidence" in reflection
        assert 0 <= reflection["confidence"] <= 1

    @pytest.mark.asyncio
    async def test_reflect_failure_with_errors(
        self, loop: ClosedLearningLoop, failure_execution: dict,
    ) -> None:
        """反思失败的执行并记录应避免模式"""
        obs = await loop.observe("T-011", failure_execution)
        reflection = await loop.reflect(obs)
        assert reflection["success"] is False
        # 有 patterns_failed 和 errors
        assert len(reflection["patterns_avoid"]) >= 1
        assert len(reflection["recommendations"]) >= 1

    @pytest.mark.asyncio
    async def test_reflect_no_patterns(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """反思无模式的任务"""
        obs = await loop.observe("T-no-pattern", {
            "description": "简单任务",
            "success": True,
            "steps": 2,
        })
        reflection = await loop.reflect(obs)
        assert len(reflection["patterns_found"]) == 0
        assert len(reflection["patterns_avoid"]) == 0

    @pytest.mark.asyncio
    async def test_reflect_confidence_high_for_success(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """成功且无错误的信心评分较高"""
        obs = await loop.observe("T-conf", success_execution)
        reflection = await loop.reflect(obs)
        assert reflection["confidence"] >= 0.7

    @pytest.mark.asyncio
    async def test_reflect_confidence_low_for_failure(
        self, loop: ClosedLearningLoop, failure_execution: dict,
    ) -> None:
        """失败任务的信心评分较低"""
        obs = await loop.observe("T-low-conf", failure_execution)
        reflection = await loop.reflect(obs)
        assert reflection["confidence"] <= 0.5

    @pytest.mark.asyncio
    async def test_reflect_generates_recommendations(
        self, loop: ClosedLearningLoop, failure_execution: dict,
    ) -> None:
        """反思生成改进建议"""
        obs = await loop.observe("T-rec", failure_execution)
        reflection = await loop.reflect(obs)
        assert len(reflection["recommendations"]) >= 1

    @pytest.mark.asyncio
    async def test_reflect_many_steps_recommendation(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """步骤过多时建议拆分任务"""
        obs = await loop.observe("T-many", {
            "description": "大型任务",
            "success": True,
            "steps": 15,
            "patterns_used": ["monolith"],
        })
        reflection = await loop.reflect(obs)
        recs = reflection["recommendations"]
        assert any("拆分" in r for r in recs)

    @pytest.mark.asyncio
    async def test_reflect_empty_observation(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """反思空观察"""
        obs = LearningObservation(task_id="T-empty-obs")
        reflection = await loop.reflect(obs)
        assert reflection["task_id"] == "T-empty-obs"
        assert reflection["success"] is False
        assert len(reflection["patterns_found"]) == 0

    @pytest.mark.asyncio
    async def test_reflect_has_context_observations(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """反思包含上下文观察计数"""
        obs = await loop.observe("T-ctx", success_execution)
        reflection = await loop.reflect(obs)
        assert "context_observations" in reflection
        assert reflection["context_observations"] >= 0


# ── Generate Skill 阶段测试 ───────────────────────────────


class TestGenerateSkill:
    """generate_skill 方法 — 编码模式为技能"""

    @pytest.mark.asyncio
    async def test_generate_skill_from_success(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """从成功模式生成技能"""
        obs = await loop.observe("T-020", success_execution)
        reflection = await loop.reflect(obs)
        skills = await loop.generate_skill(reflection)
        assert len(skills) >= 1
        for skill in skills:
            assert isinstance(skill, LearnedSkill)
            assert skill.id.startswith("skill_")
            assert skill.name != ""
            assert skill.success_rate > 0

    @pytest.mark.asyncio
    async def test_generate_skill_deduplication(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """高成功率已有技能会阻止重复生成"""
        obs = await loop.observe("T-021", success_execution)
        reflection = await loop.reflect(obs)
        skills1 = await loop.generate_skill(reflection)
        assert len(skills1) >= 1
        # 手动提升已有技能的成功率
        for s in skills1:
            s.success_rate = 0.99
            loop._update_skill(s)
            loop._skill_cache[s.id] = s
        # 第二次调用时，已有技能成功率更高，应跳过生成
        skills2 = await loop.generate_skill(reflection)
        assert len(skills2) == 0

    @pytest.mark.asyncio
    async def test_generate_skill_empty_reflection(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """空反思结果不生成技能"""
        skills = await loop.generate_skill({
            "task_id": "T-empty",
            "patterns_found": [],
            "patterns_avoid": [],
        })
        assert len(skills) == 0

    @pytest.mark.asyncio
    async def test_generate_skill_persists(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """生成的技能持久化到数据库"""
        obs = await loop.observe("T-022", success_execution)
        reflection = await loop.reflect(obs)
        skills = await loop.generate_skill(reflection)
        # 查询数据库
        with loop._get_conn() as conn:
            for skill in skills:
                row = conn.execute(
                    "SELECT * FROM learned_skills WHERE id = ?",
                    (skill.id,),
                ).fetchone()
                assert row is not None
                assert row["name"] == skill.name

    @pytest.mark.asyncio
    async def test_generate_skill_source_task_id(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """技能记录来源任务 ID"""
        obs = await loop.observe("T-source", success_execution)
        reflection = await loop.reflect(obs)
        skills = await loop.generate_skill(reflection)
        for skill in skills:
            assert skill.source_task_id == "T-source"

    @pytest.mark.asyncio
    async def test_generate_skill_updates_existing(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """生成技能时更新已有技能的使用计数"""
        obs = await loop.observe("T-update", {
            "description": "更新测试",
            "success": True,
            "patterns_used": ["test_pattern"],
        })
        reflection = await loop.reflect(obs)
        # 第一次生成
        skills1 = await loop.generate_skill(reflection)
        assert len(skills1) == 1
        # 手动提升成功率，使第二次调用时触发"已有技能更好"的路径
        for s in skills1:
            s.success_rate = 0.99
            loop._update_skill(s)
            loop._skill_cache[s.id] = s
        # 第二次 — 已有技能成功率更高，应更新使用计数而非生成新技能
        skills2 = await loop.generate_skill(reflection)
        assert len(skills2) == 0
        # 检查缓存中的技能使用计数已增加
        cached = loop._skill_cache.get(skills1[0].id)
        assert cached is not None
        assert cached.usage_count >= 2

    @pytest.mark.asyncio
    async def test_generate_skill_from_failure_lowers_rate(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """失败模式降低已有技能成功率"""
        # 首先创建一个技能
        obs1 = await loop.observe("T-pre", {
            "description": "预备任务",
            "success": True,
            "patterns_used": ["some_pattern"],
        })
        ref1 = await loop.reflect(obs1)
        skills = await loop.generate_skill(ref1)
        original_rate = skills[0].success_rate

        # 现在让同一模式失败
        obs2 = await loop.observe("T-fail", {
            "description": "失败任务",
            "success": False,
            "patterns_failed": ["some_pattern"],
        })
        ref2 = await loop.reflect(obs2)
        await loop.generate_skill(ref2)

        # 检查成功率是否降低
        cached = loop._skill_cache.get(skills[0].id)
        assert cached is not None
        assert cached.success_rate < original_rate


# ── Apply Feedback 阶段测试 ───────────────────────────────


class TestApplyFeedback:
    """apply_feedback 方法 — 为任务注入经验"""

    @pytest.mark.asyncio
    async def test_apply_feedback_no_skills(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """无技能时应用反馈"""
        feedback = await loop.apply_feedback("实现用户认证")
        assert feedback["task_description"] == "实现用户认证"
        assert len(feedback["matched_skills"]) == 0
        assert len(feedback["context_hints"]) == 0

    @pytest.mark.asyncio
    async def test_apply_feedback_with_skills(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """有技能时应用反馈"""
        # 先创建技能
        obs = await loop.observe("T-030", success_execution)
        reflection = await loop.reflect(obs)
        await loop.generate_skill(reflection)

        feedback = await loop.apply_feedback("实现认证模块")
        assert "keywords" in feedback
        assert "context_hints" in feedback

    @pytest.mark.asyncio
    async def test_apply_feedback_high_confidence_skill(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """高置信度技能产生高置信度提示"""
        skill = LearnedSkill(
            id="skill_test_high",
            name="Authentication Pattern",
            description="Best practice for user authentication",
            pattern="auth_pattern",
            strategy="使用 JWT + OAuth2",
            success_rate=0.95,
            usage_count=10,
        )
        loop._save_skill(skill)
        loop._skill_cache[skill.id] = skill

        # 使用英文描述，使关键词能匹配到技能
        feedback = await loop.apply_feedback("implement user authentication module")
        hints = feedback["context_hints"]
        assert any("高置信度" in h for h in hints)

    @pytest.mark.asyncio
    async def test_apply_feedback_low_confidence_skill(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """低置信度技能产生警告提示"""
        skill = LearnedSkill(
            id="skill_test_low",
            name="危险模式",
            description="低成功率模式",
            pattern="risky_pattern",
            strategy="谨慎使用",
            success_rate=0.2,
            usage_count=5,
        )
        loop._save_skill(skill)
        loop._skill_cache[skill.id] = skill

        # 使用英文描述，使关键词能匹配到技能
        feedback = await loop.apply_feedback("handle risky operation carefully")
        hints = feedback["context_hints"]
        assert any("低置信度" in h for h in hints)

    @pytest.mark.asyncio
    async def test_apply_feedback_empty_task(self, loop: ClosedLearningLoop) -> None:
        """空任务描述"""
        feedback = await loop.apply_feedback("")
        assert feedback["task_description"] == ""
        assert len(feedback["keywords"]) == 0

    @pytest.mark.asyncio
    async def test_apply_feedback_with_historical_observations(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """应用反馈包含历史观察"""
        await loop.observe("T-hist", {
            "description": "数据库连接池修复",
            "success": False,
            "errors": ["ConnectionError: 连接池耗尽"],
            "patterns_used": ["connection_pool"],
        })
        feedback = await loop.apply_feedback("数据库连接池")
        assert "relevant_observations_count" in feedback


# ── 完整闭环测试 ──────────────────────────────────────────


class TestRunCycle:
    """run_cycle 方法 — 完整闭环"""

    @pytest.mark.asyncio
    async def test_run_cycle_success(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """成功执行完整闭环"""
        result = await loop.run_cycle("T-100", success_execution)
        assert result["task_id"] == "T-100"
        assert "cycle_duration_ms" in result
        assert result["cycle_duration_ms"] >= 0
        assert result["observation"]["success"] is True
        assert result["observation"]["steps"] == 5
        assert "reflection" in result
        assert "skills_generated" in result
        assert "feedback" in result
        assert "refine" in result

    @pytest.mark.asyncio
    async def test_run_cycle_failure(
        self, loop: ClosedLearningLoop, failure_execution: dict,
    ) -> None:
        """失败执行完整闭环"""
        result = await loop.run_cycle("T-101", failure_execution)
        assert result["observation"]["success"] is False
        assert result["observation"]["errors"] == 2

    @pytest.mark.asyncio
    async def test_run_cycle_generates_skills(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """成功闭环生成技能"""
        result = await loop.run_cycle("T-102", success_execution)
        assert result["skills_generated"] >= 1
        assert len(result["new_skill_ids"]) >= 1

    @pytest.mark.asyncio
    async def test_run_cycle_returns_refine_result(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """闭环返回精炼结果"""
        result = await loop.run_cycle("T-103", success_execution)
        assert "refine" in result
        # 第一次调用可能跳过精炼（间隔未到）
        is_valid = (
            "skipped" in result["refine"]
            or "total_skills" in result["refine"]
        )
        assert is_valid

    @pytest.mark.asyncio
    async def test_run_cycle_multiple_cycles(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """多轮闭环执行"""
        r1 = await loop.run_cycle("T-cycle-1", success_execution)
        r2 = await loop.run_cycle("T-cycle-2", {
            "description": "另一个任务",
            "success": True,
            "steps": 3,
            "patterns_used": ["observer_pattern"],
        })
        assert r1["task_id"] == "T-cycle-1"
        assert r2["task_id"] == "T-cycle-2"

    @pytest.mark.asyncio
    async def test_run_cycle_has_all_phases(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """闭环结果包含所有四个阶段"""
        result = await loop.run_cycle("T-phases", success_execution)
        assert "observation" in result
        assert "reflection" in result
        assert "skills_generated" in result
        assert "feedback" in result


# ── 经验持久化测试 ────────────────────────────────────────


class TestPersistence:
    """经验持久化 — 保存/加载"""

    @pytest.mark.asyncio
    async def test_save_and_load_observation(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """保存并加载观察记录"""
        await loop.observe("T-persist", success_execution)
        # 创建新实例连接同一数据库
        new_loop = ClosedLearningLoop(db_path=loop._db_path)
        with new_loop._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM learning_observations WHERE task_id = ?",
                ("T-persist",),
            ).fetchone()
            assert row is not None
            assert row["success"] == 1

    @pytest.mark.asyncio
    async def test_save_and_load_skill(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """保存并加载技能"""
        obs = await loop.observe("T-persist-skill", success_execution)
        reflection = await loop.reflect(obs)
        skills = await loop.generate_skill(reflection)
        assert len(skills) >= 1

        # 新实例加载
        new_loop = ClosedLearningLoop(db_path=loop._db_path)
        all_skills = new_loop._load_all_skills()
        assert len(all_skills) >= 1

    @pytest.mark.asyncio
    async def test_persistence_across_instances(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """跨实例持久化"""
        await loop.observe("T-cross", {
            "description": "跨实例测试",
            "success": True,
            "steps": 1,
        })
        stats1 = loop.get_stats()

        loop2 = ClosedLearningLoop(db_path=loop._db_path)
        stats2 = loop2.get_stats()
        assert stats2["total_observations"] == stats1["total_observations"]

    @pytest.mark.asyncio
    async def test_skill_cache_repopulated_on_load(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """新实例加载时技能缓存为空但数据库可查询"""
        obs = await loop.observe("T-cache", success_execution)
        reflection = await loop.reflect(obs)
        await loop.generate_skill(reflection)

        # 新实例应该有空的缓存，但 _load_all_skills 可以加载
        new_loop = ClosedLearningLoop(db_path=loop._db_path)
        assert len(new_loop._skill_cache) == 0
        skills = new_loop._load_all_skills()
        assert len(skills) >= 1


# ── 统计追踪测试 ──────────────────────────────────────────


class TestStatistics:
    """get_stats 方法 — 统计追踪"""

    def test_stats_empty(self, loop: ClosedLearningLoop) -> None:
        """空数据库统计"""
        stats = loop.get_stats()
        assert stats["total_observations"] == 0
        assert stats["total_skills"] == 0
        assert stats["observation_success_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_stats_after_observations(
        self, loop: ClosedLearningLoop, success_execution: dict,
        failure_execution: dict,
    ) -> None:
        """多次观察后统计"""
        await loop.observe("T-stats-1", success_execution)
        await loop.observe("T-stats-2", failure_execution)
        stats = loop.get_stats()
        assert stats["total_observations"] == 2
        assert stats["successful_observations"] == 1
        assert stats["observation_success_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_stats_after_skills_generated(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """生成技能后统计"""
        obs = await loop.observe("T-stats-skill", success_execution)
        reflection = await loop.reflect(obs)
        await loop.generate_skill(reflection)
        stats = loop.get_stats()
        assert stats["total_skills"] >= 1

    def test_stats_skill_cache_size(self, loop: ClosedLearningLoop) -> None:
        """统计包含技能缓存大小"""
        stats = loop.get_stats()
        assert "skill_cache_size" in stats
        assert stats["skill_cache_size"] == 0

    def test_stats_last_refine_time(self, loop: ClosedLearningLoop) -> None:
        """统计包含最后精炼时间"""
        stats = loop.get_stats()
        assert "last_refine" in stats
        assert stats["last_refine"] == 0.0

    @pytest.mark.asyncio
    async def test_stats_top_errors(
        self, loop: ClosedLearningLoop, failure_execution: dict,
    ) -> None:
        """统计包含高频错误"""
        await loop.observe("T-err", failure_execution)
        stats = loop.get_stats()
        assert "top_errors" in stats

    @pytest.mark.asyncio
    async def test_stats_recent_24h(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """统计包含最近24小时数据"""
        await loop.observe("T-recent", success_execution)
        stats = loop.get_stats()
        assert "recent_24h" in stats
        assert stats["recent_24h"]["observations"] >= 1

    @pytest.mark.asyncio
    async def test_stats_has_avg_skill_success_rate(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """统计包含平均技能成功率"""
        obs = await loop.observe("T-avg", success_execution)
        reflection = await loop.reflect(obs)
        await loop.generate_skill(reflection)
        stats = loop.get_stats()
        assert "avg_skill_success_rate" in stats
        assert "total_skill_usage" in stats


# ── 错误处理测试 ──────────────────────────────────────────


class TestErrorHandling:
    """错误处理 — 畸形跟踪、缺失数据"""

    @pytest.mark.asyncio
    async def test_observe_with_none_values(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """观察包含 None 值的执行结果（steps/errors/patterns 可为 None）"""
        obs = await loop.observe("T-none", {
            "description": None,
            "success": None,
            "steps": 0,
            "errors": None,
            "patterns_used": None,
            "patterns_failed": None,
            "metadata": None,
        })
        assert obs.success is False
        assert obs.steps_taken == 0
        assert obs.task_description == "None"

    @pytest.mark.asyncio
    async def test_observe_steps_as_float(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """步骤数为浮点数时强制转换"""
        obs = await loop.observe("T-steps", {
            "description": "test",
            "steps": 3.7,
        })
        assert obs.steps_taken == 3  # int(3.7) = 3

    @pytest.mark.asyncio
    async def test_apply_feedback_with_special_characters(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """反馈应用处理特殊字符"""
        feedback = await loop.apply_feedback(
            "修复 [BUG] 数据库连接 @#$% 异常!!!"
        )
        assert feedback["task_description"] is not None
        assert isinstance(feedback["keywords"], list)

    @pytest.mark.asyncio
    async def test_observe_very_long_task_description(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """超长任务描述"""
        long_desc = "测试" * 1000
        obs = await loop.observe("T-long", {
            "description": long_desc,
            "success": True,
        })
        assert obs.task_description == long_desc

    @pytest.mark.asyncio
    async def test_observe_with_complex_metadata(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """复杂嵌套元数据"""
        complex_meta = {
            "nested": {"a": [1, 2, 3], "b": {"c": "deep"}},
            "list": [{"x": 1}, {"y": 2}],
        }
        obs = await loop.observe("T-meta", {
            "description": "test",
            "metadata": complex_meta,
        })
        assert obs.metadata == complex_meta

    @pytest.mark.asyncio
    async def test_reflect_with_corrupted_db_observation(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """反思时数据库中有损坏的 JSON 数据"""
        # 直接插入损坏的 JSON
        with loop._get_conn() as conn:
            conn.execute(
                """INSERT INTO learning_observations
                   (task_id, task_description, success, steps_taken,
                    errors_encountered, patterns_used, patterns_failed,
                    timestamp, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "T-corrupt", "test", 1, 3,
                    "NOT_VALID_JSON", "NOT_VALID_JSON", "[]",
                    time.time(), "{}",
                ),
            )
            conn.commit()
        # 不应崩溃 — 正常观察和反思
        obs = await loop.observe("T-normal", {"description": "正常任务"})
        reflection = await loop.reflect(obs)
        assert isinstance(reflection, dict)

    @pytest.mark.asyncio
    async def test_observe_with_unicode_in_description(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """Unicode 任务描述"""
        obs = await loop.observe("T-unicode", {
            "description": "修复 🐛 编码问题 → 测试 ✓",
            "success": True,
        })
        assert "🐛" in obs.task_description

    @pytest.mark.asyncio
    async def test_observe_errors_with_non_string_items(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """错误列表包含非字符串项"""
        obs = await loop.observe("T-mixed", {
            "description": "test",
            "errors": [42, None, "real_error"],
        })
        # _ensure_list 将每个元素转为 str
        assert "42" in obs.errors_encountered
        assert "None" in obs.errors_encountered
        assert "real_error" in obs.errors_encountered


# ── 技能验证测试 ──────────────────────────────────────────


class TestSkillValidation:
    """技能验证"""

    @pytest.mark.asyncio
    async def test_skill_has_valid_id(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """技能 ID 格式正确"""
        obs = await loop.observe("T-valid", success_execution)
        reflection = await loop.reflect(obs)
        skills = await loop.generate_skill(reflection)
        for skill in skills:
            assert skill.id.startswith("skill_")
            assert len(skill.id) == 18  # "skill_" + 12 hex chars

    @pytest.mark.asyncio
    async def test_skill_success_rate_in_range(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """技能成功率在有效范围"""
        obs = await loop.observe("T-range", success_execution)
        reflection = await loop.reflect(obs)
        skills = await loop.generate_skill(reflection)
        for skill in skills:
            assert 0 <= skill.success_rate <= 1

    @pytest.mark.asyncio
    async def test_skill_not_pruned_by_default(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """新技能默认未被淘汰"""
        obs = await loop.observe("T-pruned", success_execution)
        reflection = await loop.reflect(obs)
        skills = await loop.generate_skill(reflection)
        for skill in skills:
            assert skill.pruned is False

    @pytest.mark.asyncio
    async def test_skill_usage_count_starts_at_one(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """新技能使用计数从 1 开始"""
        obs = await loop.observe("T-usage", success_execution)
        reflection = await loop.reflect(obs)
        skills = await loop.generate_skill(reflection)
        for skill in skills:
            assert skill.usage_count == 1

    @pytest.mark.asyncio
    async def test_find_similar_skill(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """查找相似技能"""
        skill = LearnedSkill(
            id="skill_find_test",
            name="测试技能",
            pattern="unique_pattern_xyz",
            strategy="测试策略",
            success_rate=0.8,
            usage_count=3,
        )
        loop._save_skill(skill)
        # 缓存中没有，但数据库中有
        found = loop._find_similar_skill("unique_pattern_xyz")
        assert found is not None
        assert found.id == "skill_find_test"

    @pytest.mark.asyncio
    async def test_find_similar_skill_not_found(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """查找不存在的技能返回 None"""
        found = loop._find_similar_skill("nonexistent_pattern")
        assert found is None

    @pytest.mark.asyncio
    async def test_find_similar_skill_from_cache(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """从缓存查找技能"""
        skill = LearnedSkill(
            id="skill_cache_test",
            name="缓存技能",
            pattern="cached_pattern",
        )
        loop._skill_cache[skill.id] = skill
        found = loop._find_similar_skill("cached_pattern")
        assert found is not None
        assert found.id == "skill_cache_test"

    @pytest.mark.asyncio
    async def test_find_similar_skill_skips_pruned(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """查找时跳过已淘汰技能"""
        skill = LearnedSkill(
            id="skill_pruned_test",
            name="已淘汰",
            pattern="pruned_pattern",
            pruned=True,
        )
        loop._save_skill(skill)
        loop._skill_cache[skill.id] = skill
        found = loop._find_similar_skill("pruned_pattern")
        assert found is None

    @pytest.mark.asyncio
    async def test_skill_has_description(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """技能包含描述信息"""
        obs = await loop.observe("T-desc", success_execution)
        reflection = await loop.reflect(obs)
        skills = await loop.generate_skill(reflection)
        for skill in skills:
            assert skill.description != ""

    @pytest.mark.asyncio
    async def test_skill_has_strategy(
        self, loop: ClosedLearningLoop, success_execution: dict,
    ) -> None:
        """技能包含执行策略"""
        obs = await loop.observe("T-strategy", success_execution)
        reflection = await loop.reflect(obs)
        skills = await loop.generate_skill(reflection)
        for skill in skills:
            assert skill.strategy != ""


# ── 精炼技能测试 ──────────────────────────────────────────


class TestRefineSkills:
    """refine_skills 方法 — 技能精炼"""

    @pytest.mark.asyncio
    async def test_refine_skills_skips_when_interval_not_reached(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """精炼间隔未到时跳过"""
        loop._last_refine_time = time.time()  # 刚精炼过
        result = await loop.refine_skills()
        assert result["skipped"] is True

    @pytest.mark.asyncio
    async def test_refine_skills_prunes_low_performance(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """淘汰低成功率技能"""
        skill = LearnedSkill(
            id="skill_low_perf",
            name="低效技能",
            pattern="slow_pattern",
            success_rate=0.1,
            usage_count=5,
            created_at=time.time() - 10000,
            updated_at=time.time() - 10000,
        )
        loop._save_skill(skill)
        loop._skill_cache[skill.id] = skill

        # 强制可以精炼
        loop._last_refine_time = 0
        result = await loop.refine_skills()
        assert "pruned" in result
        # 从缓存移除
        assert skill.id not in loop._skill_cache

    @pytest.mark.asyncio
    async def test_refine_skills_boosts_high_performance(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """提升高成功率技能"""
        skill = LearnedSkill(
            id="skill_high_perf",
            name="高效技能",
            pattern="fast_pattern",
            success_rate=0.9,
            usage_count=10,
            created_at=time.time() - 10000,
            updated_at=time.time() - 10000,
        )
        loop._save_skill(skill)
        loop._skill_cache[skill.id] = skill

        loop._last_refine_time = 0
        result = await loop.refine_skills()
        assert "boosted" in result
        # 技能应在缓存中
        assert skill.id in loop._skill_cache

    @pytest.mark.asyncio
    async def test_refine_skills_skips_low_usage(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """使用次数不足的低成功率技能不被淘汰"""
        skill = LearnedSkill(
            id="skill_low_usage",
            name="使用不足",
            pattern="rare_pattern",
            success_rate=0.1,
            usage_count=1,  # 低于 SKILL_MIN_USAGE (3)
            created_at=time.time() - 10000,
            updated_at=time.time() - 10000,
        )
        loop._save_skill(skill)
        loop._skill_cache[skill.id] = skill

        loop._last_refine_time = 0
        result = await loop.refine_skills()
        # 不应被淘汰
        assert skill.id in loop._skill_cache

    @pytest.mark.asyncio
    async def test_refine_skills_cleans_old_observations(
        self, loop: ClosedLearningLoop,
    ) -> None:
        """精炼时清理过期观察"""
        # 插入一个很旧的观察
        with loop._get_conn() as conn:
            conn.execute(
                """INSERT INTO learning_observations
                   (task_id, task_description, success, steps_taken,
                    errors_encountered, patterns_used, patterns_failed,
                    timestamp, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "T-old", "旧任务", 1, 1,
                    "[]", "[]", "[]",
                    time.time() - 100 * 86400,  # 100 天前
                    "{}",
                ),
            )
            conn.commit()

        loop._last_refine_time = 0
        result = await loop.refine_skills()
        assert "cleaned_observations" in result


# ── 静态辅助方法测试 ──────────────────────────────────────


class TestStaticHelpers:
    """静态辅助方法"""

    def test_ensure_list_with_list(self) -> None:
        """_ensure_list 处理列表"""
        result = ClosedLearningLoop._ensure_list(["a", "b", "c"])
        assert result == ["a", "b", "c"]

    def test_ensure_list_with_string(self) -> None:
        """_ensure_list 处理字符串"""
        result = ClosedLearningLoop._ensure_list("single")
        assert result == ["single"]

    def test_ensure_list_with_none(self) -> None:
        """_ensure_list 处理 None"""
        result = ClosedLearningLoop._ensure_list(None)
        assert result == []

    def test_ensure_list_with_int(self) -> None:
        """_ensure_list 处理非列表/字符串"""
        result = ClosedLearningLoop._ensure_list(42)
        assert result == []

    def test_extract_keywords_basic(self) -> None:
        """_extract_keywords 基本提取"""
        keywords = ClosedLearningLoop._extract_keywords(
            "implement user authentication module"
        )
        assert len(keywords) > 0
        assert "user" in keywords or "implement" in keywords

    def test_extract_keywords_empty(self) -> None:
        """_extract_keywords 空字符串"""
        assert ClosedLearningLoop._extract_keywords("") == []

    def test_extract_keywords_filters_stop_words(self) -> None:
        """_extract_keywords 过滤停用词"""
        keywords = ClosedLearningLoop._extract_keywords(
            "the and for with this is at"
        )
        assert all(
            kw not in keywords
            for kw in ["the", "and", "for", "with", "this", "is", "at"]
        )

    def test_extract_keywords_short_words_filtered(self) -> None:
        """_extract_keywords 过滤短词"""
        keywords = ClosedLearningLoop._extract_keywords("a b c de fg hij")
        assert "hij" in keywords
        assert "a" not in keywords
        assert "b" not in keywords

    def test_derive_skill_name_from_pattern(self) -> None:
        """_derive_skill_name 从模式派生名称"""
        name = ClosedLearningLoop._derive_skill_name(
            "skill:JWT认证模式", {}
        )
        assert name == "JWT认证模式"

    def test_derive_skill_name_no_colon(self) -> None:
        """_derive_skill_name 无冒号模式"""
        name = ClosedLearningLoop._derive_skill_name(
            "simple_pattern_name", {}
        )
        assert name == "simple_pattern_name"

    def test_derive_skill_name_long_pattern(self) -> None:
        """_derive_skill_name 超长模式"""
        long_pattern = "x" * 100
        name = ClosedLearningLoop._derive_skill_name(long_pattern, {})
        assert len(name) <= 83  # 80 + "..."

    def test_calculate_confidence_success(self, tmp_path: Path) -> None:
        """_calculate_confidence 成功任务"""
        loop = ClosedLearningLoop(db_path=str(tmp_path / "conf.db"))
        obs = LearningObservation(
            task_id="T", success=True, errors_encountered=[]
        )
        conf = loop._calculate_confidence(obs, [], [])
        assert conf == 0.9

    def test_calculate_confidence_failure(self, tmp_path: Path) -> None:
        """_calculate_confidence 失败任务"""
        loop = ClosedLearningLoop(db_path=str(tmp_path / "conf2.db"))
        obs = LearningObservation(
            task_id="T", success=False, errors_encountered=["error"]
        )
        conf = loop._calculate_confidence(obs, [], [])
        assert conf == 0.3

    def test_calculate_confidence_with_patterns(self, tmp_path: Path) -> None:
        """_calculate_confidence 有模式时调整"""
        loop = ClosedLearningLoop(db_path=str(tmp_path / "conf3.db"))
        obs = LearningObservation(
            task_id="T", success=True, errors_encountered=[]
        )
        patterns_found = [{"confidence": 0.9}]
        conf = loop._calculate_confidence(obs, patterns_found, [])
        # base=0.9, avg=0.9, result=(0.9+0.9)/2 = 0.9
        assert conf == 0.9

    def test_calculate_confidence_with_avoid_patterns(self, tmp_path: Path) -> None:
        """_calculate_confidence 有应避免模式时减分"""
        loop = ClosedLearningLoop(db_path=str(tmp_path / "conf4.db"))
        obs = LearningObservation(
            task_id="T", success=True, errors_encountered=[]
        )
        conf = loop._calculate_confidence(obs, [], [{"pattern": "bad"}])
        # base=0.9, *0.8 = 0.72
        assert conf == 0.72


# ── 全局单例测试 ──────────────────────────────────────────


class TestGlobalSingleton:
    """get_closed_loop 全局单例"""

    def test_get_closed_loop_returns_instance(
        self, tmp_path: Path,
    ) -> None:
        """获取全局单例"""
        import pycoder.capabilities.self_evo.learning.closed_loop as cl_mod

        cl_mod._closed_loop_instance = None
        instance = get_closed_loop()
        assert isinstance(instance, ClosedLearningLoop)

    def test_get_closed_loop_same_instance(
        self, tmp_path: Path,
    ) -> None:
        """多次调用返回同一实例"""
        import pycoder.capabilities.self_evo.learning.closed_loop as cl_mod

        cl_mod._closed_loop_instance = None
        i1 = get_closed_loop()
        i2 = get_closed_loop()
        assert i1 is i2


# ── 数据模型测试 ──────────────────────────────────────────


class TestDataModels:
    """LearningObservation 和 LearnedSkill 数据模型"""

    def test_learning_observation_defaults(self) -> None:
        """LearningObservation 默认值"""
        obs = LearningObservation(task_id="T-test")
        assert obs.task_id == "T-test"
        assert obs.success is False
        assert obs.steps_taken == 0
        assert obs.errors_encountered == []
        assert obs.patterns_used == []
        assert obs.patterns_failed == []
        assert obs.task_description == ""

    def test_learning_observation_full(self) -> None:
        """LearningObservation 完整构造"""
        obs = LearningObservation(
            task_id="T-full",
            task_description="测试任务",
            success=True,
            steps_taken=10,
            errors_encountered=["err1"],
            patterns_used=["pat1", "pat2"],
            patterns_failed=["pat3"],
            metadata={"key": "value"},
        )
        assert obs.success is True
        assert len(obs.patterns_used) == 2
        assert obs.metadata["key"] == "value"

    def test_learned_skill_defaults(self) -> None:
        """LearnedSkill 默认值"""
        skill = LearnedSkill()
        assert skill.id == ""
        assert skill.success_rate == 0.0
        assert skill.usage_count == 0
        assert skill.pruned is False

    def test_learned_skill_full(self) -> None:
        """LearnedSkill 完整构造"""
        skill = LearnedSkill(
            id="skill_001",
            name="测试技能",
            description="用于测试",
            pattern="test_.*",
            strategy="执行测试",
            success_rate=0.85,
            usage_count=42,
            source_task_id="T-001",
            pruned=False,
        )
        assert skill.name == "测试技能"
        assert skill.success_rate == 0.85
        assert skill.pruned is False

    def test_learned_skill_timestamps(self) -> None:
        """LearnedSkill 时间戳"""
        before = time.time()
        skill = LearnedSkill(id="skill_ts")
        after = time.time()
        assert before <= skill.created_at <= after
        assert before <= skill.updated_at <= after