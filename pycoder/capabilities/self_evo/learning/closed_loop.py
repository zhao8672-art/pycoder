"""
Hermes 风格封闭学习循环 — 观察→反思→生成→应用的完整闭环

核心流程:
  ┌──────────────────────────────────────────────────────────┐
  │                   ClosedLearningLoop                     │
  ├──────────────────────────────────────────────────────────┤
  │  observe()       → 收集执行轨迹 (LearningObservation)     │
  │  reflect()       → 分析成功/失败模式                      │
  │  generate_skill()→ 将成功模式编码为可复用技能              │
  │  refine_skills() → 周期性评估和优化技能库                  │
  │  apply_feedback()→ 将相关经验注入新任务上下文              │
  │  run_cycle()     → 一键运行完整闭环                       │
  └──────────────────────────────────────────────────────────┘

技能存储: SQLite + FTS5 全文搜索
自动优化: 基于成功率定期修剪低效技能

用法:
  from pycoder.capabilities.self_evo.learning.closed_loop import (
      ClosedLearningLoop,
      get_closed_loop,
      register_capabilities,
  )

  loop = ClosedLearningLoop()
  result = await loop.run_cycle(task_id="T-001", execution_result={...})
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pycoder.bus.protocol import (
    CapabilityCategory,
    CapabilityDefinition,
    ExecutionMode,
    SideEffect,
    TrustLevel,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 数据库路径
# ──────────────────────────────────────────────

CLOSED_LOOP_DB = Path(
    os.environ.get(
        "PYCODER_CLOSED_LOOP_DB",
        str(Path.home() / ".pycoder" / "learning" / "closed_loop.db"),
    )
)

# ──────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────

# 技能自动淘汰阈值 — 成功率低于此值的技能将被标记为待优化
SKILL_PRUNE_SUCCESS_RATE = 0.3
# 技能最少使用次数 — 低于此次数的技能不参与淘汰
SKILL_MIN_USAGE = 3
# 反射分析时回溯的最近观察数
REFLECT_WINDOW_SIZE = 20
# 技能精炼间隔（秒）
REFINE_INTERVAL_SECONDS = 3600


# ──────────────────────────────────────────────
# SQL 表定义
# ──────────────────────────────────────────────

SCHEMA = """
-- 学习观察记录表
CREATE TABLE IF NOT EXISTS learning_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    task_description TEXT DEFAULT '',
    success INTEGER DEFAULT 0,
    steps_taken INTEGER DEFAULT 0,
    errors_encountered TEXT DEFAULT '[]',
    patterns_used TEXT DEFAULT '[]',
    patterns_failed TEXT DEFAULT '[]',
    timestamp REAL DEFAULT 0,
    metadata TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_obs_task_id ON learning_observations(task_id);
CREATE INDEX IF NOT EXISTS idx_obs_success ON learning_observations(success);
CREATE INDEX IF NOT EXISTS idx_obs_timestamp ON learning_observations(timestamp);

-- 学习技能表
CREATE TABLE IF NOT EXISTS learned_skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    pattern TEXT DEFAULT '',
    strategy TEXT DEFAULT '',
    success_rate REAL DEFAULT 0.0,
    usage_count INTEGER DEFAULT 0,
    created_at REAL DEFAULT 0,
    updated_at REAL DEFAULT 0,
    source_task_id TEXT DEFAULT '',
    pruned INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_skill_name ON learned_skills(name);
CREATE INDEX IF NOT EXISTS idx_skill_success_rate ON learned_skills(success_rate);
CREATE INDEX IF NOT EXISTS idx_skill_usage ON learned_skills(usage_count);

-- FTS5 全文搜索虚拟表
CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
    name,
    description,
    pattern,
    strategy,
    content='learned_skills',
    content_rowid='rowid'
);

-- FTS5 同步触发器
CREATE TRIGGER IF NOT EXISTS skills_ai AFTER INSERT ON learned_skills BEGIN
    INSERT INTO skills_fts(rowid, name, description, pattern, strategy)
    VALUES (new.rowid, new.name, new.description, new.pattern, new.strategy);
END;

CREATE TRIGGER IF NOT EXISTS skills_ad AFTER DELETE ON learned_skills BEGIN
    INSERT INTO skills_fts(skills_fts, rowid, name, description, pattern, strategy)
    VALUES ('delete', old.rowid, old.name, old.description, old.pattern, old.strategy);
END;

CREATE TRIGGER IF NOT EXISTS skills_au AFTER UPDATE ON learned_skills BEGIN
    INSERT INTO skills_fts(skills_fts, rowid, name, description, pattern, strategy)
    VALUES ('delete', old.rowid, old.name, old.description, old.pattern, old.strategy);
    INSERT INTO skills_fts(rowid, name, description, pattern, strategy)
    VALUES (new.rowid, new.name, new.description, new.pattern, new.strategy);
END;
"""


# ──────────────────────────────────────────────
# 数据类
# ──────────────────────────────────────────────


@dataclass
class LearningObservation:
    """学习观察 — 单次任务执行的完整跟踪记录

    记录每次任务执行的步骤、错误、使用的模式等，
    供后续反思分析使用。
    """

    task_id: str
    task_description: str = ""
    success: bool = False
    steps_taken: int = 0
    errors_encountered: list[str] = field(default_factory=list)
    patterns_used: list[str] = field(default_factory=list)
    patterns_failed: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LearnedSkill:
    """习得技能 — 从成功模式中提炼的可复用技能

    每个技能包含匹配模式（正则/关键词）、执行策略、
    成功率和使用统计，支持 FTS5 全文检索。
    """

    id: str = ""
    name: str = ""
    description: str = ""
    pattern: str = ""  # 正则表达式或关键词
    strategy: str = ""  # 执行策略描述
    success_rate: float = 0.0
    usage_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    source_task_id: str = ""
    pruned: bool = False  # 是否已被淘汰


# ──────────────────────────────────────────────
# ClosedLearningLoop 核心类
# ──────────────────────────────────────────────


class ClosedLearningLoop:
    """Hermes 风格封闭学习循环

    实现完整的 observe → reflect → generate → apply 闭环：
    1. 观察：记录每次任务执行的完整跟踪
    2. 反思：分析成功/失败模式，发现可复用规律
    3. 生成：将成功模式编码为可检索的技能
    4. 应用：将相关经验注入新任务上下文
    5. 精炼：周期性评估技能库，淘汰低效技能
    """

    def __init__(self, db_path: str | Path | None = None):
        self._db_path = str(db_path or CLOSED_LOOP_DB)
        self._db_dir = Path(self._db_path).parent
        self._db_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

        # 技能缓存（热数据）
        self._skill_cache: dict[str, LearnedSkill] = {}
        # 最后精炼时间
        self._last_refine_time: float = 0.0

    # ─── 数据库初始化 ───

    def _init_db(self) -> None:
        """初始化 SQLite 数据库和 FTS5 索引"""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.executescript(SCHEMA)
                conn.commit()
            logger.info("封闭学习循环数据库已初始化: %s", self._db_path)
        except sqlite3.OperationalError as e:
            # FTS5 可能未编译，降级运行
            logger.warning("FTS5 初始化失败，全文搜索降级: %s", e)
            self._init_db_no_fts()

    def _init_db_no_fts(self) -> None:
        """无 FTS5 的降级初始化"""
        fallback_schema = """
        CREATE TABLE IF NOT EXISTS learning_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            task_description TEXT DEFAULT '',
            success INTEGER DEFAULT 0,
            steps_taken INTEGER DEFAULT 0,
            errors_encountered TEXT DEFAULT '[]',
            patterns_used TEXT DEFAULT '[]',
            patterns_failed TEXT DEFAULT '[]',
            timestamp REAL DEFAULT 0,
            metadata TEXT DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_obs_task_id ON learning_observations(task_id);
        CREATE INDEX IF NOT EXISTS idx_obs_success ON learning_observations(success);
        CREATE INDEX IF NOT EXISTS idx_obs_timestamp ON learning_observations(timestamp);

        CREATE TABLE IF NOT EXISTS learned_skills (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            pattern TEXT DEFAULT '',
            strategy TEXT DEFAULT '',
            success_rate REAL DEFAULT 0.0,
            usage_count INTEGER DEFAULT 0,
            created_at REAL DEFAULT 0,
            updated_at REAL DEFAULT 0,
            source_task_id TEXT DEFAULT '',
            pruned INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_skill_name ON learned_skills(name);
        CREATE INDEX IF NOT EXISTS idx_skill_success_rate ON learned_skills(success_rate);
        CREATE INDEX IF NOT EXISTS idx_skill_usage ON learned_skills(usage_count);
        """
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript(fallback_schema)
            conn.commit()
        self._fts_available = False

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ══════════════════════════════════════════════════════
    # 核心方法：观察
    # ══════════════════════════════════════════════════════

    async def observe(
        self,
        task_id: str,
        execution_result: dict[str, Any],
    ) -> LearningObservation:
        """收集执行跟踪 — 将任务执行结果记录为结构化观察

        Args:
            task_id: 任务唯一标识
            execution_result: 执行结果字典，可包含:
                - description: 任务描述
                - success: 是否成功
                - steps: 执行步骤数
                - errors: 错误列表
                - patterns_used: 使用的模式列表
                - patterns_failed: 失败的模式列表
                - metadata: 额外元数据

        Returns:
            创建的学习观察对象
        """
        observation = LearningObservation(
            task_id=task_id,
            task_description=str(execution_result.get("description", "")),
            success=bool(execution_result.get("success", False)),
            steps_taken=int(execution_result.get("steps", 0)),
            errors_encountered=self._ensure_list(execution_result.get("errors", [])),
            patterns_used=self._ensure_list(execution_result.get("patterns_used", [])),
            patterns_failed=self._ensure_list(execution_result.get("patterns_failed", [])),
            timestamp=time.time(),
            metadata=execution_result.get("metadata", {}),
        )

        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO learning_observations
                   (task_id, task_description, success, steps_taken,
                    errors_encountered, patterns_used, patterns_failed,
                    timestamp, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    observation.task_id,
                    observation.task_description,
                    1 if observation.success else 0,
                    observation.steps_taken,
                    json.dumps(observation.errors_encountered, ensure_ascii=False),
                    json.dumps(observation.patterns_used, ensure_ascii=False),
                    json.dumps(observation.patterns_failed, ensure_ascii=False),
                    observation.timestamp,
                    json.dumps(observation.metadata, ensure_ascii=False),
                ),
            )
            conn.commit()

        logger.debug(
            "观察已记录: task=%s success=%s steps=%d errors=%d",
            task_id,
            observation.success,
            observation.steps_taken,
            len(observation.errors_encountered),
        )
        return observation

    # ══════════════════════════════════════════════════════
    # 核心方法：反思
    # ══════════════════════════════════════════════════════

    async def reflect(
        self,
        observation: LearningObservation,
    ) -> dict[str, Any]:
        """分析成功/失败模式 — 从观察中提取可学习的规律

        Args:
            observation: 学习观察对象

        Returns:
            反思结果字典，包含:
            - patterns_found: 发现的成功模式列表
            - patterns_avoid: 应避免的失败模式列表
            - confidence: 信心评分
            - recommendations: 改进建议列表
        """
        # 1. 加载最近的观察记录作为上下文
        recent_obs = self._get_recent_observations(limit=REFLECT_WINDOW_SIZE)

        # 2. 分析当前观察中的成功模式
        patterns_found: list[dict[str, Any]] = []
        patterns_avoid: list[dict[str, Any]] = []

        if observation.success and observation.patterns_used:
            # 成功的模式 — 检查是否在历史中也有效
            for pattern in observation.patterns_used:
                hist_success = self._count_pattern_success(pattern, recent_obs)
                patterns_found.append(
                    {
                        "pattern": pattern,
                        "source": "current_task",
                        "historical_success_count": hist_success,
                        "confidence": min(0.95, 0.5 + hist_success * 0.1),
                    }
                )

        if observation.patterns_failed:
            for pattern in observation.patterns_failed:
                patterns_avoid.append(
                    {
                        "pattern": pattern,
                        "reason": "当前任务中失败",
                        "suggestion": f"考虑替换或优化 '{pattern}' 模式",
                    }
                )

        if observation.errors_encountered:
            for error in observation.errors_encountered:
                # 检查是否有已知的成功模式可以处理此错误
                existing_skills = self._search_skills_by_error(error)
                if existing_skills:
                    for skill in existing_skills:
                        patterns_found.append(
                            {
                                "pattern": skill.pattern,
                                "source": f"skill:{skill.id}",
                                "skill_name": skill.name,
                                "success_rate": skill.success_rate,
                                "confidence": skill.success_rate,
                            }
                        )
                else:
                    patterns_avoid.append(
                        {
                            "pattern": f"error:{error[:80]}",
                            "reason": "无已知修复技能",
                            "suggestion": "记录此错误模式，等待后续成功修复后生成技能",
                        }
                    )

        # 3. 计算整体信心评分
        confidence = self._calculate_confidence(observation, patterns_found, patterns_avoid)

        # 4. 生成改进建议
        recommendations = self._generate_recommendations(
            observation, patterns_found, patterns_avoid
        )

        reflection = {
            "task_id": observation.task_id,
            "success": observation.success,
            "patterns_found": patterns_found,
            "patterns_avoid": patterns_avoid,
            "confidence": confidence,
            "recommendations": recommendations,
            "context_observations": len(recent_obs),
            "timestamp": time.time(),
        }

        logger.info(
            "反思完成: task=%s success=%s patterns_found=%d confidence=%.2f",
            observation.task_id,
            observation.success,
            len(patterns_found),
            confidence,
        )
        return reflection

    # ══════════════════════════════════════════════════════
    # 核心方法：生成技能
    # ══════════════════════════════════════════════════════

    async def generate_skill(
        self,
        reflection: dict[str, Any],
    ) -> list[LearnedSkill]:
        """将成功模式编码为可复用的技能

        Args:
            reflection: 反思结果字典

        Returns:
            新生成/更新的技能列表
        """
        generated: list[LearnedSkill] = []

        for pattern_info in reflection.get("patterns_found", []):
            pattern = pattern_info.get("pattern", "")
            if not pattern:
                continue

            # 检查是否已有相似技能
            existing = self._find_similar_skill(pattern)
            if existing and existing.success_rate > pattern_info.get("confidence", 0.5):
                # 更新已有技能的使用计数
                existing.usage_count += 1
                existing.updated_at = time.time()
                self._update_skill(existing)
                self._skill_cache[existing.id] = existing
                logger.debug("技能已更新: %s (usage=%d)", existing.name, existing.usage_count)
                continue

            # 创建新技能
            skill_id = f"skill_{uuid.uuid4().hex[:12]}"
            skill_name = self._derive_skill_name(pattern, reflection)
            skill = LearnedSkill(
                id=skill_id,
                name=skill_name,
                description=(
                    f"从任务 {reflection.get('task_id', 'unknown')} "
                    f"习得的模式: {pattern[:200]}"
                ),
                pattern=pattern,
                strategy=pattern_info.get("suggestion", f"应用模式: {pattern}"),
                success_rate=pattern_info.get("confidence", 0.7),
                usage_count=1,
                created_at=time.time(),
                updated_at=time.time(),
                source_task_id=str(reflection.get("task_id", "")),
            )

            self._save_skill(skill)
            self._skill_cache[skill_id] = skill
            generated.append(skill)
            logger.info(
                "新技能已生成: %s (id=%s, rate=%.2f)",
                skill_name, skill_id, skill.success_rate,
            )

        # 也从 patterns_avoid 中生成"反面教材"技能（低成功率标记）
        for avoid_info in reflection.get("patterns_avoid", []):
            pattern = avoid_info.get("pattern", "")
            if not pattern or pattern.startswith("error:"):
                continue

            existing = self._find_similar_skill(pattern)
            if existing:
                # 降低成功率
                total = existing.usage_count + 1
                existing.success_rate = (existing.success_rate * existing.usage_count) / total
                existing.usage_count = total
                existing.updated_at = time.time()
                self._update_skill(existing)
                self._skill_cache[existing.id] = existing
                logger.debug("技能成功率已降低: %s → %.2f", existing.name, existing.success_rate)

        return generated

    # ══════════════════════════════════════════════════════
    # 核心方法：应用反馈
    # ══════════════════════════════════════════════════════

    async def apply_feedback(
        self,
        task_description: str,
    ) -> dict[str, Any]:
        """将相关经验注入新任务上下文

        根据任务描述搜索最匹配的技能，生成增强上下文。

        Args:
            task_description: 新任务描述

        Returns:
            增强上下文字典，包含:
            - matched_skills: 匹配的技能列表
            - context_hints: 上下文提示列表
            - relevant_observations: 相关历史观察
        """
        # 1. 关键词提取
        keywords = self._extract_keywords(task_description)

        # 2. FTS5 全文搜索匹配技能
        matched_skills = self._search_skills(task_description, keywords, limit=5)

        # 3. 查找相关历史观察
        relevant_obs = self._search_observations(task_description, limit=3)

        # 4. 生成上下文提示
        context_hints: list[str] = []
        for skill in matched_skills:
            if skill.success_rate >= 0.7:
                context_hints.append(
                    f"[高置信度] {skill.name}: {skill.strategy} "
                    f"(成功率 {skill.success_rate:.0%}, 使用 {skill.usage_count} 次)"
                )
            elif skill.success_rate >= 0.4:
                context_hints.append(
                    f"[中置信度] {skill.name}: {skill.strategy} "
                    f"(成功率 {skill.success_rate:.0%})"
                )
            else:
                context_hints.append(
                    f"[低置信度] {skill.name}: 谨慎使用，成功率仅 {skill.success_rate:.0%}"
                )

        # 5. 从历史观察中提取相关错误警示
        for obs in relevant_obs:
            if obs.errors_encountered:
                for err in obs.errors_encountered[:2]:
                    context_hints.append(f"[历史警示] 类似任务曾遇到: {err[:150]}")

        result = {
            "task_description": task_description,
            "keywords": keywords,
            "matched_skills": [
                {
                    "id": s.id,
                    "name": s.name,
                    "pattern": s.pattern,
                    "strategy": s.strategy,
                    "success_rate": s.success_rate,
                    "usage_count": s.usage_count,
                }
                for s in matched_skills
            ],
            "context_hints": context_hints,
            "relevant_observations_count": len(relevant_obs),
            "timestamp": time.time(),
        }

        logger.info(
            "反馈应用: skills=%d hints=%d obs=%d",
            len(matched_skills),
            len(context_hints),
            len(relevant_obs),
        )
        return result

    # ══════════════════════════════════════════════════════
    # 核心方法：精炼技能
    # ══════════════════════════════════════════════════════

    async def refine_skills(self) -> dict[str, Any]:
        """周期性评估和优化技能库

        自动淘汰低成功率技能，提升高成功率技能的权重。
        """
        now = time.time()
        # 防止频繁调用
        if now - self._last_refine_time < REFINE_INTERVAL_SECONDS:
            logger.debug("精炼间隔未到，跳过（上次: %s 前）", int(now - self._last_refine_time))
            return {"skipped": True, "reason": "精炼间隔未到"}

        self._last_refine_time = now

        all_skills = self._load_all_skills(exclude_pruned=True)
        pruned: list[str] = []
        boosted: list[str] = []

        for skill in all_skills:
            # 淘汰低成功率且使用次数足够的技能
            if (
                skill.usage_count >= SKILL_MIN_USAGE
                and skill.success_rate < SKILL_PRUNE_SUCCESS_RATE
            ):
                self._prune_skill(skill.id)
                pruned.append(skill.name)
                if skill.id in self._skill_cache:
                    del self._skill_cache[skill.id]
                logger.info(
                    "技能已淘汰: %s (rate=%.2f, usage=%d)",
                    skill.name, skill.success_rate, skill.usage_count,
                )

            # 提升高成功率技能的权重（记录精炼时间）
            elif skill.success_rate >= 0.8 and skill.usage_count >= SKILL_MIN_USAGE:
                skill.updated_at = now
                self._update_skill(skill)
                self._skill_cache[skill.id] = skill
                boosted.append(skill.name)

        # 清理过期观察记录（保留最近 90 天）
        cleaned = self._cleanup_old_observations(max_age_days=90)

        result = {
            "total_skills": len(all_skills),
            "pruned": len(pruned),
            "pruned_names": pruned,
            "boosted": len(boosted),
            "boosted_names": boosted,
            "cleaned_observations": cleaned,
            "timestamp": now,
        }

        logger.info(
            "技能精炼完成: total=%d pruned=%d boosted=%d cleaned=%d",
            len(all_skills),
            len(pruned),
            len(boosted),
            cleaned,
        )
        return result

    # ══════════════════════════════════════════════════════
    # 核心方法：完整闭环
    # ══════════════════════════════════════════════════════

    async def run_cycle(
        self,
        task_id: str,
        execution_result: dict[str, Any],
    ) -> dict[str, Any]:
        """运行完整闭环 — observe → reflect → generate → apply

        一键运行 Hermes 风格封闭学习循环的四个阶段。
        P1-5 优化: 每阶段最多重试 2 次，失败后降级继续。

        Args:
            task_id: 任务唯一标识
            execution_result: 执行结果字典

        Returns:
            完整闭环结果字典
        """
        cycle_start = time.time()

        # P1-5: 带重试的阶段执行器
        async def _run_stage_with_retry(stage_name: str, coro_factory, max_retries: int = 2):
            """执行单个阶段，失败时重试"""
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    return await coro_factory(), None
                except (RuntimeError, ValueError, TypeError, OSError) as e:
                    last_error = e
                    logger.warning(
                        "closed_loop_stage_retry: stage=%s attempt=%d/%d error=%s",
                        stage_name, attempt + 1, max_retries + 1, str(e)[:200],
                    )
            return None, last_error

        # 阶段 1: 观察
        observation, err = await _run_stage_with_retry(
            "observe", lambda: self.observe(task_id, execution_result)
        )
        if err:
            logger.error("closed_loop_observe_failed task=%s: %s", task_id, err)
            return {
                "task_id": task_id,
                "error": f"observe_failed: {err}",
                "success": False,
                "timestamp": cycle_start,
            }

        # 阶段 2: 反思
        reflection, err = await _run_stage_with_retry(
            "reflect", lambda: self.reflect(observation)
        )
        if err or not reflection:
            reflection = {"patterns_found": [], "patterns_avoid": [], "confidence": 0, "recommendations": []}
            logger.warning("closed_loop_reflect_degraded task=%s", task_id)

        # 阶段 3: 生成技能
        new_skills, err = await _run_stage_with_retry(
            "generate_skill", lambda: self.generate_skill(reflection)
        )
        if err:
            new_skills = []
            logger.warning("closed_loop_generate_skill_degraded task=%s", task_id)

        # 阶段 4: 应用反馈
        feedback, err = await _run_stage_with_retry(
            "apply_feedback", lambda: self.apply_feedback(observation.task_description)
        )
        if err or not feedback:
            feedback = {"matched_skills": [], "context_hints": []}
            logger.warning("closed_loop_apply_feedback_degraded task=%s", task_id)

        # 定期精炼（非阻塞，仅在需要时触发）
        try:
            refine_result = await self.refine_skills()
        except (RuntimeError, ValueError, TypeError) as e:
            refine_result = {"status": "skipped", "error": str(e)[:200]}
            logger.warning("closed_loop_refine_skipped task=%s: %s", task_id, e)

        cycle_duration = time.time() - cycle_start

        result = {
            "task_id": task_id,
            "cycle_duration_ms": round(cycle_duration * 1000, 1),
            "observation": {
                "success": observation.success,
                "steps": observation.steps_taken,
                "errors": len(observation.errors_encountered),
            },
            "reflection": {
                "patterns_found": len(reflection.get("patterns_found", [])),
                "patterns_avoid": len(reflection.get("patterns_avoid", [])),
                "confidence": reflection.get("confidence", 0),
                "recommendations": reflection.get("recommendations", []),
            },
            "skills_generated": len(new_skills),
            "new_skill_ids": [s.id for s in new_skills],
            "feedback": {
                "matched_skills": len(feedback.get("matched_skills", [])),
                "context_hints": feedback.get("context_hints", []),
            },
            "refine": refine_result,
            "timestamp": cycle_start,
        }

        logger.info(
            "闭环完成: task=%s duration=%.0fms success=%s skills=%d",
            task_id,
            cycle_duration * 1000,
            observation.success,
            len(new_skills),
        )
        return result

    # ══════════════════════════════════════════════════════
    # 统计查询
    # ══════════════════════════════════════════════════════

    def get_stats(self) -> dict[str, Any]:
        """获取学习统计信息

        Returns:
            统计字典，包含观察数、技能数、成功率等
        """
        with self._get_conn() as conn:
            total_obs = conn.execute(
                "SELECT COUNT(*) FROM learning_observations"
            ).fetchone()[0]
            success_obs = conn.execute(
                "SELECT COUNT(*) FROM learning_observations WHERE success = 1"
            ).fetchone()[0]
            total_skills = conn.execute(
                "SELECT COUNT(*) FROM learned_skills WHERE pruned = 0"
            ).fetchone()[0]
            active_skills = conn.execute(
                "SELECT COUNT(*) FROM learned_skills WHERE pruned = 0 AND usage_count >= ?",
                (SKILL_MIN_USAGE,),
            ).fetchone()[0]
            avg_success_rate = conn.execute(
                "SELECT COALESCE(AVG(success_rate), 0) FROM learned_skills WHERE pruned = 0"
            ).fetchone()[0]
            total_skill_usage = conn.execute(
                "SELECT COALESCE(SUM(usage_count), 0) FROM learned_skills WHERE pruned = 0"
            ).fetchone()[0]
            pruned_count = conn.execute(
                "SELECT COUNT(*) FROM learned_skills WHERE pruned = 1"
            ).fetchone()[0]

            # 最近 24 小时观察
            cutoff = time.time() - 86400
            recent_obs = conn.execute(
                "SELECT COUNT(*) FROM learning_observations WHERE timestamp > ?",
                (cutoff,),
            ).fetchone()[0]
            recent_success = conn.execute(
                "SELECT COUNT(*) FROM learning_observations WHERE timestamp > ? AND success = 1",
                (cutoff,),
            ).fetchone()[0]

            # 高频错误
            rows = conn.execute(
                "SELECT errors_encountered FROM learning_observations "
                "WHERE success = 0 ORDER BY timestamp DESC LIMIT 100"
            ).fetchall()
            error_counter: dict[str, int] = {}
            for row in rows:
                try:
                    errors = json.loads(row["errors_encountered"])
                    for err in errors:
                        key = err[:60]
                        error_counter[key] = error_counter.get(key, 0) + 1
                except (json.JSONDecodeError, TypeError):
                    pass
            top_errors = sorted(error_counter.items(), key=lambda x: -x[1])[:10]

        return {
            "total_observations": total_obs,
            "successful_observations": success_obs,
            "observation_success_rate": (
                success_obs / total_obs if total_obs > 0 else 0.0
            ),
            "total_skills": total_skills,
            "active_skills": active_skills,
            "pruned_skills": pruned_count,
            "avg_skill_success_rate": round(avg_success_rate, 3),
            "total_skill_usage": total_skill_usage,
            "recent_24h": {
                "observations": recent_obs,
                "success_rate": recent_success / recent_obs if recent_obs > 0 else 0.0,
            },
            "top_errors": [{"error": e, "count": c} for e, c in top_errors],
            "last_refine": self._last_refine_time,
            "skill_cache_size": len(self._skill_cache),
        }

    # ══════════════════════════════════════════════════════
    # 内部辅助方法
    # ══════════════════════════════════════════════════════

    @staticmethod
    def _ensure_list(value: Any) -> list[str]:
        """确保值为字符串列表"""
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, str):
            return [value]
        return []

    def _get_recent_observations(self, limit: int = 20) -> list[dict[str, Any]]:
        """获取最近的观察记录"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM learning_observations ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def _count_pattern_success(
        self, pattern: str, observations: list[dict[str, Any]]
    ) -> int:
        """统计某模式在历史观察中的成功次数"""
        count = 0
        for obs in observations:
            if obs.get("success"):
                try:
                    patterns = json.loads(obs.get("patterns_used", "[]"))
                except (json.JSONDecodeError, TypeError):
                    patterns = []
                if pattern in patterns:
                    count += 1
        return count

    def _search_skills_by_error(self, error: str) -> list[LearnedSkill]:
        """根据错误信息搜索相关技能"""
        keywords = self._extract_keywords(error)
        return self._search_skills(error, keywords, limit=3)

    def _search_skills(
        self,
        query: str,
        keywords: list[str] | None = None,
        limit: int = 5,
    ) -> list[LearnedSkill]:
        """搜索技能 — 优先 FTS5，降级为 LIKE 匹配"""
        keywords = keywords or self._extract_keywords(query)

        try:
            return self._search_skills_fts(query, limit)
        except sqlite3.OperationalError:
            return self._search_skills_like(keywords, limit)

    def _search_skills_fts(self, query: str, limit: int = 5) -> list[LearnedSkill]:
        """FTS5 全文搜索"""
        with self._get_conn() as conn:
            # 使用 FTS5 的简单查询语法
            fts_query = " OR ".join(f'"{w}"' for w in query.split() if len(w) > 1)
            if not fts_query:
                fts_query = query
            try:
                rows = conn.execute(
                    """SELECT l.* FROM learned_skills l
                       INNER JOIN skills_fts f ON l.rowid = f.rowid
                       WHERE skills_fts MATCH ? AND l.pruned = 0
                       ORDER BY l.success_rate DESC, l.usage_count DESC
                       LIMIT ?""",
                    (fts_query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                # FTS5 查询语法错误时回退
                rows = conn.execute(
                    """SELECT * FROM learned_skills
                       WHERE pruned = 0
                       ORDER BY success_rate DESC, usage_count DESC
                       LIMIT ?""",
                    (limit,),
                ).fetchall()

            return [self._row_to_skill(r) for r in rows]

    def _search_skills_like(
        self, keywords: list[str], limit: int = 5
    ) -> list[LearnedSkill]:
        """LIKE 降级搜索"""
        if not keywords:
            return []

        with self._get_conn() as conn:
            conditions = " OR ".join(
                ["(name LIKE ? OR description LIKE ? OR pattern LIKE ?)"] * len(keywords)
            )
            params = []
            for kw in keywords:
                like_pat = f"%{kw}%"
                params.extend([like_pat, like_pat, like_pat])

            rows = conn.execute(
                f"""SELECT * FROM learned_skills
                    WHERE pruned = 0 AND ({conditions})
                    ORDER BY success_rate DESC, usage_count DESC
                    LIMIT ?""",  # nosec B608
                (*params, limit),
            ).fetchall()

            return [self._row_to_skill(r) for r in rows]

    def _search_observations(
        self, task_description: str, limit: int = 3
    ) -> list[LearningObservation]:
        """搜索相关历史观察"""
        keywords = self._extract_keywords(task_description)
        if not keywords:
            return []

        with self._get_conn() as conn:
            conditions = " OR ".join(
                ["task_description LIKE ?"] * len(keywords)
            )
            params = [f"%{kw}%" for kw in keywords]

            rows = conn.execute(
                f"""SELECT * FROM learning_observations
                    WHERE {conditions}
                    ORDER BY timestamp DESC
                    LIMIT ?""",  # nosec B608
                (*params, limit),
            ).fetchall()

            return [self._row_to_observation(r) for r in rows]

    def _find_similar_skill(self, pattern: str) -> LearnedSkill | None:
        """查找相似技能（先查缓存，再查数据库）"""
        # 缓存查找
        for skill in self._skill_cache.values():
            if skill.pattern == pattern and not skill.pruned:
                return skill

        # 数据库查找
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM learned_skills WHERE pattern = ? AND pruned = 0 LIMIT 1",
                (pattern,),
            ).fetchone()
            if row:
                skill = self._row_to_skill(row)
                self._skill_cache[skill.id] = skill
                return skill
        return None

    def _load_all_skills(self, exclude_pruned: bool = True) -> list[LearnedSkill]:
        """加载所有技能"""
        with self._get_conn() as conn:
            if exclude_pruned:
                rows = conn.execute(
                    "SELECT * FROM learned_skills WHERE pruned = 0"
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM learned_skills").fetchall()
            return [self._row_to_skill(r) for r in rows]

    def _save_skill(self, skill: LearnedSkill) -> None:
        """保存技能到数据库"""
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO learned_skills
                   (id, name, description, pattern, strategy,
                    success_rate, usage_count, created_at, updated_at,
                    source_task_id, pruned)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    skill.id,
                    skill.name,
                    skill.description,
                    skill.pattern,
                    skill.strategy,
                    skill.success_rate,
                    skill.usage_count,
                    skill.created_at,
                    skill.updated_at,
                    skill.source_task_id,
                    1 if skill.pruned else 0,
                ),
            )
            conn.commit()

    def _update_skill(self, skill: LearnedSkill) -> None:
        """更新已有技能"""
        self._save_skill(skill)

    def _prune_skill(self, skill_id: str) -> None:
        """标记技能为已淘汰"""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE learned_skills SET pruned = 1, updated_at = ? WHERE id = ?",
                (time.time(), skill_id),
            )
            conn.commit()

    def _cleanup_old_observations(self, max_age_days: int = 90) -> int:
        """清理过期观察记录"""
        cutoff = time.time() - max_age_days * 86400
        with self._get_conn() as conn:
            deleted = conn.execute(
                "DELETE FROM learning_observations WHERE timestamp < ?",
                (cutoff,),
            ).rowcount
            conn.commit()
        return deleted

    def _calculate_confidence(
        self,
        observation: LearningObservation,
        patterns_found: list[dict[str, Any]],
        patterns_avoid: list[dict[str, Any]],
    ) -> float:
        """计算整体信心评分"""
        if observation.success and not observation.errors_encountered:
            base = 0.9
        elif observation.success:
            base = 0.7
        else:
            base = 0.3

        # 发现模式加分
        if patterns_found:
            avg_conf = sum(p.get("confidence", 0.5) for p in patterns_found) / len(patterns_found)
            base = (base + avg_conf) / 2

        # 待避免模式减分
        if patterns_avoid:
            base *= 0.8

        return round(min(1.0, max(0.0, base)), 3)

    def _generate_recommendations(
        self,
        observation: LearningObservation,
        patterns_found: list[dict[str, Any]],
        patterns_avoid: list[dict[str, Any]],
    ) -> list[str]:
        """生成改进建议"""
        recommendations: list[str] = []

        if observation.errors_encountered:
            recommendations.append(
                f"任务遇到 {len(observation.errors_encountered)} 个错误，建议审查错误模式"
            )

        if patterns_found:
            high_conf = [p for p in patterns_found if p.get("confidence", 0) >= 0.8]
            if high_conf:
                recommendations.append(
                    f"发现 {len(high_conf)} 个高置信度模式，建议编码为可复用技能"
                )

        if patterns_avoid:
            recommendations.append(
                f"识别 {len(patterns_avoid)} 个应避免的模式，将在后续任务中标记"
            )

        if not observation.success and not patterns_found:
            recommendations.append("任务失败且未发现可复用模式，建议人工审查")

        if observation.steps_taken > 10:
            recommendations.append(
                f"任务步骤较多 ({observation.steps_taken}步)，考虑拆分为子任务"
            )

        return recommendations

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        """从文本中提取关键词"""
        if not text:
            return []
        # 简单分词：按空格、标点分割，过滤短词
        words = re.split(r"[\s,;:.!?()\[\]{}]+", text.lower())
        keywords = [w for w in words if len(w) > 2 and w not in STOP_WORDS]
        # 去重并限制数量
        seen: set[str] = set()
        unique: list[str] = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique.append(kw)
        return unique[:10]

    @staticmethod
    def _derive_skill_name(pattern: str, reflection: dict[str, Any]) -> str:
        """从模式中派生技能名称"""
        # 尝试从模式中提取有意义的名称
        if ":" in pattern:
            parts = pattern.split(":")
            if len(parts) >= 2:
                return parts[1].strip()[:80]
        # 截取模式前 80 字符
        name = pattern.strip()[:80]
        if len(pattern) > 80:
            name += "..."
        return name

    @staticmethod
    def _row_to_skill(row: sqlite3.Row) -> LearnedSkill:
        """将数据库行转换为 LearnedSkill"""
        return LearnedSkill(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            pattern=row["pattern"],
            strategy=row["strategy"],
            success_rate=row["success_rate"],
            usage_count=row["usage_count"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            source_task_id=row["source_task_id"],
            pruned=bool(row["pruned"]),
        )

    @staticmethod
    def _row_to_observation(row: sqlite3.Row) -> LearningObservation:
        """将数据库行转换为 LearningObservation"""
        try:
            errors = json.loads(row["errors_encountered"])
        except (json.JSONDecodeError, TypeError):
            errors = []
        try:
            patterns_used = json.loads(row["patterns_used"])
        except (json.JSONDecodeError, TypeError):
            patterns_used = []
        try:
            patterns_failed = json.loads(row["patterns_failed"])
        except (json.JSONDecodeError, TypeError):
            patterns_failed = []
        try:
            metadata = json.loads(row["metadata"])
        except (json.JSONDecodeError, TypeError):
            metadata = {}

        return LearningObservation(
            task_id=row["task_id"],
            task_description=row["task_description"],
            success=bool(row["success"]),
            steps_taken=row["steps_taken"],
            errors_encountered=errors,
            patterns_used=patterns_used,
            patterns_failed=patterns_failed,
            timestamp=row["timestamp"],
            metadata=metadata,
        )


# ──────────────────────────────────────────────
# 停用词表（英文关键词提取用）
# ──────────────────────────────────────────────

STOP_WORDS: set[str] = {
    "the", "is", "at", "which", "on", "and", "or", "not", "but",
    "for", "with", "this", "that", "from", "are", "was", "were",
    "has", "have", "had", "been", "can", "will", "would", "could",
    "should", "may", "might", "shall", "did", "does", "doing",
    "its", "his", "her", "our", "their", "these", "those",
    "what", "when", "where", "who", "how", "all", "each", "every",
    "both", "few", "more", "most", "some", "any", "such", "only",
    "other", "than", "too", "very", "just", "also", "now", "then",
    "here", "there", "into", "over", "about", "after",
    "before", "between", "under", "again", "further", "once",
}


# ──────────────────────────────────────────────
# 全局单例
# ──────────────────────────────────────────────

_closed_loop_instance: ClosedLearningLoop | None = None


def get_closed_loop() -> ClosedLearningLoop:
    """获取 ClosedLearningLoop 全局单例"""
    global _closed_loop_instance
    if _closed_loop_instance is None:
        _closed_loop_instance = ClosedLearningLoop()
    return _closed_loop_instance


# ──────────────────────────────────────────────
# 能力注册
# ──────────────────────────────────────────────


def register_capabilities(registry: Any) -> None:
    """向总线注册封闭学习循环能力

    注册五个能力:
      - learning.observe        — 观察执行
      - learning.reflect        — 反思模式
      - learning.generate_skill — 生成技能
      - learning.apply_feedback — 应用反馈
      - learning.stats          — 获取统计
    """
    loop = get_closed_loop()

    # ── learning.observe ──
    registry.register(
        CapabilityDefinition(
            id="learning.observe",
            name="观察执行",
            description="记录任务执行跟踪，收集步骤、错误、模式等结构化观察数据",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.PROJECT_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_WRITE],
            schema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "任务唯一标识",
                    },
                    "execution_result": {
                        "type": "object",
                        "description": "执行结果，包含 description, success, steps, errors 等字段",
                    },
                },
                "required": ["task_id", "execution_result"],
            },
            tags=["learning", "observe", "观察", "学习"],
        ),
        handler=lambda params, ctx: _handle_observe(loop, params, ctx),
    )

    # ── learning.reflect ──
    registry.register(
        CapabilityDefinition(
            id="learning.reflect",
            name="反思模式",
            description="分析观察数据中的成功/失败模式，提取可学习规律",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_READ],
            schema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "要反思的任务 ID",
                    },
                    "observation": {
                        "type": "object",
                        "description": "学习观察对象（可选，不提供则查询最近一次）",
                    },
                },
                "required": ["task_id"],
            },
            tags=["learning", "reflect", "反思", "分析"],
        ),
        handler=lambda params, ctx: _handle_reflect(loop, params, ctx),
    )

    # ── learning.generate_skill ──
    registry.register(
        CapabilityDefinition(
            id="learning.generate_skill",
            name="生成技能",
            description="从反思结果中将成功模式编码为可复用的技能",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.PROJECT_WRITE,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_WRITE],
            schema={
                "type": "object",
                "properties": {
                    "reflection": {
                        "type": "object",
                        "description": "反思结果，包含 patterns_found 和 patterns_avoid",
                    },
                },
                "required": ["reflection"],
            },
            tags=["learning", "skill", "技能", "生成"],
        ),
        handler=lambda params, ctx: _handle_generate_skill(loop, params, ctx),
    )

    # ── learning.apply_feedback ──
    registry.register(
        CapabilityDefinition(
            id="learning.apply_feedback",
            name="应用反馈",
            description="根据任务描述搜索匹配技能，生成增强上下文",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_READ],
            schema={
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "新任务描述",
                    },
                },
                "required": ["task_description"],
            },
            tags=["learning", "feedback", "反馈", "上下文"],
        ),
        handler=lambda params, ctx: _handle_apply_feedback(loop, params, ctx),
    )

    # ── learning.stats ──
    registry.register(
        CapabilityDefinition(
            id="learning.stats",
            name="学习统计",
            description="获取封闭学习循环的统计信息，包括观察数、技能数、成功率等",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_READ],
            tags=["learning", "stats", "统计", "学习"],
        ),
        handler=lambda params, ctx: _handle_stats(loop, params, ctx),
    )

    logger.info("封闭学习循环能力已注册: 5 个能力")


# ──────────────────────────────────────────────
# 处理器实现
# ──────────────────────────────────────────────


async def _handle_observe(
    loop: ClosedLearningLoop,
    params: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """处理 learning.observe 调用"""
    task_id = params.get("task_id", "")
    execution_result = params.get("execution_result", {})

    if not task_id:
        return {"success": False, "error": "缺少 task_id 参数"}

    try:
        observation = await loop.observe(task_id, execution_result)
        return {
            "success": True,
            "task_id": observation.task_id,
            "recorded": True,
            "steps": observation.steps_taken,
            "errors_count": len(observation.errors_encountered),
        }
    except Exception as e:
        logger.exception("观察记录失败: %s", e)
        return {"success": False, "error": str(e)}


async def _handle_reflect(
    loop: ClosedLearningLoop,
    params: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """处理 learning.reflect 调用"""
    task_id = params.get("task_id", "")

    if not task_id:
        return {"success": False, "error": "缺少 task_id 参数"}

    try:
        # 如果提供了 observation 参数，直接使用
        obs_data = params.get("observation")
        if obs_data:
            observation = LearningObservation(
                task_id=task_id,
                task_description=str(obs_data.get("task_description", "")),
                success=bool(obs_data.get("success", False)),
                steps_taken=int(obs_data.get("steps_taken", 0)),
                errors_encountered=ClosedLearningLoop._ensure_list(
                    obs_data.get("errors_encountered", [])
                ),
                patterns_used=ClosedLearningLoop._ensure_list(
                    obs_data.get("patterns_used", [])
                ),
                patterns_failed=ClosedLearningLoop._ensure_list(
                    obs_data.get("patterns_failed", [])
                ),
                metadata=obs_data.get("metadata", {}),
            )
        else:
            # 查询数据库中最近一次观察
            recent = loop._get_recent_observations(limit=1)
            if not recent or recent[0].get("task_id") != task_id:
                return {
                    "success": False,
                    "error": f"未找到任务 {task_id} 的观察记录",
                }
            obs = recent[0]
            observation = LearningObservation(
                task_id=obs["task_id"],
                task_description=obs.get("task_description", ""),
                success=bool(obs.get("success", False)),
                steps_taken=obs.get("steps_taken", 0),
                errors_encountered=json.loads(obs.get("errors_encountered", "[]")),
                patterns_used=json.loads(obs.get("patterns_used", "[]")),
                patterns_failed=json.loads(obs.get("patterns_failed", "[]")),
                metadata=json.loads(obs.get("metadata", "{}")),
            )

        reflection = await loop.reflect(observation)
        return {"success": True, "reflection": reflection}
    except Exception as e:
        logger.exception("反思分析失败: %s", e)
        return {"success": False, "error": str(e)}


async def _handle_generate_skill(
    loop: ClosedLearningLoop,
    params: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """处理 learning.generate_skill 调用"""
    reflection = params.get("reflection", {})

    if not reflection:
        return {"success": False, "error": "缺少 reflection 参数"}

    try:
        skills = await loop.generate_skill(reflection)
        return {
            "success": True,
            "skills_generated": len(skills),
            "skill_ids": [s.id for s in skills],
            "skill_names": [s.name for s in skills],
        }
    except Exception as e:
        logger.exception("技能生成失败: %s", e)
        return {"success": False, "error": str(e)}


async def _handle_apply_feedback(
    loop: ClosedLearningLoop,
    params: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """处理 learning.apply_feedback 调用"""
    task_description = params.get("task_description", "")

    if not task_description:
        return {"success": False, "error": "缺少 task_description 参数"}

    try:
        feedback = await loop.apply_feedback(task_description)
        return {"success": True, "feedback": feedback}
    except Exception as e:
        logger.exception("反馈应用失败: %s", e)
        return {"success": False, "error": str(e)}


async def _handle_stats(
    loop: ClosedLearningLoop,
    params: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """处理 learning.stats 调用"""
    try:
        stats = loop.get_stats()
        return {"success": True, "stats": stats}
    except Exception as e:
        logger.exception("统计获取失败: %s", e)
        return {"success": False, "error": str(e)}


# ──────────────────────────────────────────────
# 导出
# ──────────────────────────────────────────────

__all__ = [
    "ClosedLearningLoop",
    "LearningObservation",
    "LearnedSkill",
    "get_closed_loop",
    "register_capabilities",
    "CLOSED_LOOP_DB",
]