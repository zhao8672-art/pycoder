"""
经验回放缓冲区 — 跨任务经验存储与优先级采样

借鉴 DQN 经验回放思想，用于 Agent 学习:
  1. 存储每个任务的完整经验 (状态→动作→结果→奖励)
  2. 优先级采样: 高 TD-error (意外结果) 优先回放
  3. 经验回放用于 prompt 优化和模式提取

集成点:
  - AutonomousPipeline 完成时 → 存储完整流水线经验
  - SelfEvolutionEngine 修复后 → 存储修复经验
  - 定期触发 → 回放分析，生成学习报告

用法:
  from .experience_buffer import ExperienceBuffer
  buf = ExperienceBuffer(capacity=1000)
  buf.store(task_exp)
  batch = buf.sample(batch_size=10, strategy="priority")
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from pycoder.server.log import log

EXP_DIR = Path(
    os.environ.get(
        "PYCODER_EXPERIENCE_DIR",
        str(Path.home() / ".pycoder" / "learning" / "experiences"),
    )
)
DEFAULT_CAPACITY = 1000


@dataclass
class TaskExperience:
    """单次任务经验"""

    id: str = ""
    task_type: str = ""  # fix | generate | review | evolve | pipeline
    description: str = ""  # 任务描述
    # 状态
    error_signature: str = ""  # 标准化错误签名
    error_message: str = ""  # 原始错误消息
    file_paths: list[str] = field(default_factory=list)
    # 动作
    fix_content: str = ""  # 修复内容
    agent_role: str = ""  # 执行的 Agent
    model_used: str = ""  # 使用的模型
    # 结果
    outcome: str = ""  # success | failure | partial | rolled_back
    test_passed: bool = False
    quality_score: float = 0.0
    # 奖励信号
    reward: float = 0.0  # -1.0 ~ +1.0
    # 成本
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    # 元数据
    retry_count: int = 0
    tags: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    # 学习相关
    priority: float = 1.0  # 采样优先级 (越大越优先)
    novelty_score: float = 0.5  # 新颖度评分
    learned_at: float = 0.0  # 上次被学习的时间


@dataclass
class ExperienceStats:
    """经验统计"""

    total: int = 0
    success: int = 0
    failure: int = 0
    avg_reward: float = 0.0
    avg_quality: float = 0.0
    avg_tokens: float = 0.0
    top_error_types: list[tuple[str, int]] = field(default_factory=list)
    recent_success_rate: float = 0.0


# ══════════════════════════════════════════════════════════
# 奖励计算
# ══════════════════════════════════════════════════════════


def compute_reward(
    outcome: str,
    test_passed: bool,
    quality_score: float,
    retry_count: int,
    tokens_used: int,
    duration_ms: float,
    is_novel: bool = False,
) -> float:
    """计算任务经验奖励 (-1.0 ~ +1.0)

    奖励因素:
      + 测试通过 (+0.4)
      + 质量评分高 (+0.15 * score/100)
      - 重试次数多 (-0.08 * retry)
      - Token 消耗多 (-0.05 * tokens/5000)
      + 新颖经验 (+0.1)
      - 耗时过长 (-0.03 * duration/30000)
    """
    reward = 0.0

    if outcome == "success":
        reward += 0.3
    elif outcome == "partial":
        reward += 0.1
    elif outcome == "failure":
        reward -= 0.3
    elif outcome == "rolled_back":
        reward -= 0.5

    if test_passed:
        reward += 0.4

    reward += 0.15 * (quality_score / 100.0)

    reward -= 0.08 * min(retry_count, 10)

    reward -= 0.05 * min(tokens_used / 5000, 2.0)

    reward -= 0.03 * min(duration_ms / 30000, 2.0)

    if is_novel:
        reward += 0.1

    return max(-1.0, min(1.0, reward))


# ══════════════════════════════════════════════════════════
# ExperienceBuffer
# ══════════════════════════════════════════════════════════


class ExperienceBuffer:
    """经验回放缓冲区"""

    def __init__(self, capacity: int = DEFAULT_CAPACITY):
        EXP_DIR.mkdir(parents=True, exist_ok=True)
        self._capacity = capacity
        self._buffer: list[TaskExperience] = []
        self._total_stored: int = 0
        self._index_path = EXP_DIR / "index.json"
        self._load_index()

    def __len__(self) -> int:
        return len(self._buffer)

    @property
    def is_full(self) -> bool:
        return len(self._buffer) >= self._capacity

    # ─── 存储 ───

    def store(self, exp: TaskExperience) -> str:
        """存储经验到缓冲区"""
        # 计算奖励
        if exp.reward == 0.0:
            exp.reward = compute_reward(
                exp.outcome,
                exp.test_passed,
                exp.quality_score,
                exp.retry_count,
                exp.tokens_used,
                exp.duration_ms,
            )

        # 计算新颖度
        exp.novelty_score = self._compute_novelty(exp)

        # 初始优先级: 基于新颖度 + 奖励绝对值
        exp.priority = exp.novelty_score * 0.5 + abs(exp.reward) * 0.5

        # 存到磁盘
        if not exp.id:
            exp.id = f"EXP-{int(time.time() * 1000)}-{random.randint(0, 9999):04d}"

        self._save_to_disk(exp)

        # 加入内存缓冲区
        self._buffer.append(exp)
        self._total_stored += 1

        # 容量控制: 保留高优先级经验
        if len(self._buffer) > self._capacity:
            self._evict()

        # 定期刷新索引
        if self._total_stored % 50 == 0:
            self._save_index()

        return exp.id

    def _compute_novelty(self, exp: TaskExperience) -> float:
        """计算经验的新颖度（与已有经验的差异程度）"""
        if not self._buffer:
            return 1.0

        # 同类型错误的新颖度 = 1 - (已有同类数量 / 总数)
        same_type = sum(1 for e in self._buffer[-100:] if e.error_signature == exp.error_signature)
        type_novelty = 0.0 if same_type > 10 else 1.0 - same_type / 10

        # 同文件的新颖度
        exp_files = set(exp.file_paths)
        same_file = 0
        for e in self._buffer[-50:]:
            if exp_files & set(e.file_paths):
                same_file += 1
        file_novelty = 0.0 if same_file > 5 else 1.0 - same_file / 5

        return (type_novelty + file_novelty) / 2

    # ─── 采样 ───

    def sample(
        self,
        batch_size: int = 10,
        strategy: str = "priority",
    ) -> list[TaskExperience]:
        """从缓冲区采样经验

        策略:
          - priority: 优先级加权采样
          - recent: 最近的经验
          - diverse: 多样性采样（不同错误类型）
          - random: 均匀随机
        """
        if not self._buffer:
            return []

        if strategy == "priority":
            return self._priority_sample(batch_size)
        elif strategy == "recent":
            return sorted(
                self._buffer,
                key=lambda e: e.timestamp,
                reverse=True,
            )[:batch_size]
        elif strategy == "diverse":
            return self._diverse_sample(batch_size)
        else:  # random
            return random.sample(
                self._buffer,
                min(batch_size, len(self._buffer)),
            )

    def _priority_sample(self, n: int) -> list[TaskExperience]:
        """优先级加权采样"""
        priorities = [e.priority + 0.01 for e in self._buffer]
        total = sum(priorities)
        probs = [p / total for p in priorities]

        indices = random.choices(
            range(len(self._buffer)),
            weights=probs,
            k=min(n, len(self._buffer)),
        )
        return [self._buffer[i] for i in indices]

    def _diverse_sample(self, n: int) -> list[TaskExperience]:
        """多样性采样 — 尽量选不同错误类型 (Bug #3: 安全退出)"""
        by_type: dict[str, list[TaskExperience]] = {}
        for e in self._buffer:
            sig = e.error_signature or "unknown"
            by_type.setdefault(sig, []).append(e)

        result: list[TaskExperience] = []
        # 安全：每轮从每种类型取一条，避免无限循环
        type_keys = list(by_type.keys())
        max_rounds = len(by_type) * len(by_type)
        for _ in range(max_rounds):
            if len(result) >= n or not type_keys:
                break
            to_remove = []
            for t in type_keys:
                if by_type[t] and len(result) < n:
                    result.append(by_type[t].pop())
                if not by_type[t]:
                    to_remove.append(t)
            for t in to_remove:
                type_keys.remove(t)
        return result

    # ─── 查询 ───

    def get_failures(self, limit: int = 20) -> list[TaskExperience]:
        """获取最近的失败经验"""
        return sorted(
            [e for e in self._buffer if e.outcome in ("failure", "rolled_back")],
            key=lambda e: e.timestamp,
            reverse=True,
        )[:limit]

    def get_successes(self, limit: int = 20) -> list[TaskExperience]:
        """获取最近的成功经验"""
        return sorted(
            [e for e in self._buffer if e.outcome == "success"],
            key=lambda e: e.timestamp,
            reverse=True,
        )[:limit]

    def get_novel(self, limit: int = 10) -> list[TaskExperience]:
        """获取最高新颖度的经验"""
        return sorted(
            self._buffer,
            key=lambda e: e.novelty_score,
            reverse=True,
        )[:limit]

    def get_by_error_type(self, error_type: str, limit: int = 10) -> list[TaskExperience]:
        """按错误类型查询"""
        return [e for e in self._buffer if error_type.lower() in (e.error_signature or "").lower()][
            :limit
        ]

    # ─── 更新 ───

    def update_priority(self, exp_id: str, new_priority: float) -> bool:
        """更新经验优先级"""
        for e in self._buffer:
            if e.id == exp_id:
                e.priority = new_priority
                return True
        return False

    def mark_learned(self, exp_ids: list[str]) -> int:
        """标记经验已被学习"""
        count = 0
        now = time.time()
        for e in self._buffer:
            if e.id in exp_ids:
                e.learned_at = now
                e.priority *= 0.5  # 降低优先级
                count += 1
        return count

    # ─── 统计 ───

    def get_stats(self, window_hours: int = 72) -> ExperienceStats:
        """获取经验统计"""
        cutoff = time.time() - window_hours * 3600
        recent = [e for e in self._buffer if e.timestamp > cutoff]
        all_exps = recent if recent else self._buffer

        success_n = sum(1 for e in all_exps if e.outcome == "success")
        failure_n = sum(1 for e in all_exps if e.outcome in ("failure", "rolled_back"))

        # 错误类型统计
        type_counts: dict[str, int] = {}
        for e in all_exps:
            if e.error_signature:
                # 取错误类型第一段
                sig = e.error_signature
                t = sig.split(":")[0] if ":" in sig else sig[:30]
                type_counts[t] = type_counts.get(t, 0) + 1

        return ExperienceStats(
            total=len(all_exps),
            success=success_n,
            failure=failure_n,
            avg_reward=sum(e.reward for e in all_exps) / max(len(all_exps), 1),
            avg_quality=sum(e.quality_score for e in all_exps if e.quality_score > 0)
            / max(
                sum(1 for e in all_exps if e.quality_score > 0),
                1,
            ),
            avg_tokens=sum(e.tokens_used for e in all_exps) / max(len(all_exps), 1),
            top_error_types=sorted(type_counts.items(), key=lambda x: -x[1])[:10],
            recent_success_rate=success_n / max(len(all_exps), 1),
        )

    # ─── 持久化 ───

    def _save_to_disk(self, exp: TaskExperience) -> None:
        """保存经验到磁盘"""
        p = EXP_DIR / f"{exp.id}.json"
        p.write_text(
            json.dumps(
                {
                    "id": exp.id,
                    "task_type": exp.task_type,
                    "description": exp.description,
                    "error_signature": exp.error_signature,
                    "error_message": exp.error_message,
                    "file_paths": exp.file_paths,
                    "fix_content": exp.fix_content,
                    "agent_role": exp.agent_role,
                    "model_used": exp.model_used,
                    "outcome": exp.outcome,
                    "test_passed": exp.test_passed,
                    "quality_score": exp.quality_score,
                    "reward": exp.reward,
                    "tokens_used": exp.tokens_used,
                    "cost_usd": exp.cost_usd,
                    "duration_ms": exp.duration_ms,
                    "retry_count": exp.retry_count,
                    "tags": exp.tags,
                    "timestamp": exp.timestamp,
                    "priority": exp.priority,
                    "novelty_score": exp.novelty_score,
                    "learned_at": exp.learned_at,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _save_index(self) -> None:
        """保存缓冲区索引"""
        self._index_path.write_text(
            json.dumps(
                {
                    "total_stored": self._total_stored,
                    "buffer_size": len(self._buffer),
                    "last_saved": time.time(),
                }
            ),
            encoding="utf-8",
        )

    def _load_index(self) -> None:
        """加载索引，从磁盘恢复（Bug #7: 惰性加载+限速）"""
        if self._index_path.exists():
            try:
                data = json.loads(self._index_path.read_text(encoding="utf-8"))
                self._total_stored = data.get("total_stored", 0)
            except (json.JSONDecodeError, OSError, KeyError, ValueError) as e:
                log.debug("exp_index_load_failed", path=str(self._index_path), error=str(e))

        # 仅从磁盘恢复最近 100 条，其余在首次访问时惰性加载
        files = sorted(
            EXP_DIR.glob("EXP-*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        max_recover = min(self._capacity, 100)
        for f in files[:max_recover]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                self._buffer.append(self._dict_to_exp(data))
            except (json.JSONDecodeError, OSError, KeyError, ValueError, TypeError) as e:
                log.debug("exp_record_load_failed", path=str(f), error=str(e))

    @staticmethod
    def _dict_to_exp(data: dict) -> TaskExperience:
        return TaskExperience(
            id=data.get("id", ""),
            task_type=data.get("task_type", ""),
            description=data.get("description", ""),
            error_signature=data.get("error_signature", ""),
            error_message=data.get("error_message", ""),
            file_paths=data.get("file_paths", []),
            fix_content=data.get("fix_content", ""),
            agent_role=data.get("agent_role", ""),
            model_used=data.get("model_used", ""),
            outcome=data.get("outcome", ""),
            test_passed=data.get("test_passed", False),
            quality_score=data.get("quality_score", 0.0),
            reward=data.get("reward", 0.0),
            tokens_used=data.get("tokens_used", 0),
            cost_usd=data.get("cost_usd", 0.0),
            duration_ms=data.get("duration_ms", 0.0),
            retry_count=data.get("retry_count", 0),
            tags=data.get("tags", []),
            timestamp=data.get("timestamp", 0.0),
            priority=data.get("priority", 1.0),
            novelty_score=data.get("novelty_score", 0.5),
            learned_at=data.get("learned_at", 0.0),
        )

    def _evict(self) -> None:
        """淘汰低优先级经验"""
        # 保留高优先级的
        self._buffer.sort(key=lambda e: e.priority, reverse=True)
        # 删除被淘汰的经验文件
        for e in self._buffer[self._capacity :]:
            p = EXP_DIR / f"{e.id}.json"
            p.unlink(missing_ok=True)
        self._buffer = self._buffer[: self._capacity]


# 全局单例
_buffer: ExperienceBuffer | None = None


def get_experience_buffer() -> ExperienceBuffer:
    global _buffer
    if _buffer is None:
        _buffer = ExperienceBuffer()
    return _buffer


def iter_experiences(buffer: ExperienceBuffer) -> list[TaskExperience]:
    """安全迭代所有经验（比直接访问 _buffer 好）"""
    return list(buffer._buffer)


__all__ = [
    "ExperienceBuffer",
    "TaskExperience",
    "ExperienceStats",
    "IterationMemory",
    "IterationRecord",
    "EngineerProfile",
    "compute_reward",
    "get_experience_buffer",
    "EXP_DIR",
]


# ══════════════════════════════════════════════════════════
# P1-2: 迭代级记忆 — 单次 Feature 的完整修改链路
# ══════════════════════════════════════════════════════════

MEMORY_DIR = EXP_DIR.parent


@dataclass
class IterationRecord:
    """单次迭代的完整记录 — 对标 Codex"迭代记忆(单次Feature)"

    记录一次功能开发中产生的所有文件变更、命令执行、报错日志。
    """

    iteration_id: str = ""
    feature_name: str = ""
    created_at: float = field(default_factory=time.time)
    files_modified: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    errors_encountered: list[str] = field(default_factory=list)
    commits_made: list[str] = field(default_factory=list)
    test_results: list[dict] = field(default_factory=list)
    rollback_events: int = 0
    total_steps: int = 0
    memory_file: str = ""

    def to_dict(self) -> dict:
        return {
            "iteration_id": self.iteration_id,
            "feature_name": self.feature_name,
            "created_at": self.created_at,
            "files_modified": self.files_modified,
            "commands_run": self.commands_run[:10],
            "errors_encountered": self.errors_encountered[:10],
            "commits_made": self.commits_made,
            "test_results": self.test_results,
            "rollback_events": self.rollback_events,
            "total_steps": self.total_steps,
        }


class IterationMemory:
    """迭代级记忆管理器 — 每次 Feature 独立记录

    用途:
      - 跨会话延续 Feature 进度（Codex 长周期项目能力）
      - 回滚时精确恢复到最后正确状态
      - 复盘时按文件/命令/报错溯源
    """

    def __init__(self):
        self._dir = MEMORY_DIR / "iterations"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._active: IterationRecord | None = None

    def start_iteration(self, feature_name: str) -> IterationRecord:
        """开始一次新迭代记录"""
        import uuid

        record = IterationRecord(
            iteration_id=f"ITER-{uuid.uuid4().hex[:8]}",
            feature_name=feature_name,
        )
        record.memory_file = str(self._dir / f"{record.iteration_id}.json")
        self._active = record
        self._save(record)
        return record

    def record_file_change(self, file_path: str) -> None:
        """记录文件变更"""
        if self._active:
            self._active.files_modified.append(file_path)
            self._save(self._active)

    def record_command(self, command: str) -> None:
        """记录执行的命令"""
        if self._active:
            self._active.commands_run.append(command)
            self._save(self._active)

    def record_error(self, error: str) -> None:
        """记录遇到的错误"""
        if self._active:
            self._active.errors_encountered.append(error)
            self._save(self._active)

    def record_commit(self, commit_msg: str) -> None:
        """记录 Git 提交"""
        if self._active:
            self._active.commits_made.append(commit_msg)
            self._active.total_steps += 1
            self._save(self._active)

    def record_test(self, name: str, passed: bool, output: str = "") -> None:
        """记录测试结果"""
        if self._active:
            self._active.test_results.append(
                {
                    "name": name,
                    "passed": passed,
                    "output": output[:200],
                    "time": time.time(),
                }
            )
            self._active.total_steps += 1
            self._save(self._active)

    def record_rollback(self) -> None:
        """记录回滚事件"""
        if self._active:
            self._active.rollback_events += 1
            self._save(self._active)

    def finish_iteration(self) -> IterationRecord | None:
        """结束当前迭代，返回完整记录"""
        record = self._active
        self._active = None
        return record

    def load_iteration(self, iteration_id: str) -> IterationRecord | None:
        """加载历史迭代记录"""
        p = self._dir / f"{iteration_id}.json"
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return IterationRecord(
                iteration_id=data.get("iteration_id", iteration_id),
                feature_name=data.get("feature_name", ""),
                created_at=data.get("created_at", 0),
                files_modified=data.get("files_modified", []),
                commands_run=data.get("commands_run", []),
                errors_encountered=data.get("errors_encountered", []),
                commits_made=data.get("commits_made", []),
                test_results=data.get("test_results", []),
                rollback_events=data.get("rollback_events", 0),
                total_steps=data.get("total_steps", 0),
            )
        except (json.JSONDecodeError, OSError, KeyError):
            return None

    def list_iterations(self, limit: int = 20) -> list[dict]:
        """列出最近的迭代"""
        files = sorted(
            self._dir.glob("ITER-*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )[:limit]
        result = []
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                result.append(
                    {
                        "iteration_id": data.get("iteration_id", ""),
                        "feature_name": data.get("feature_name", ""),
                        "files": len(data.get("files_modified", [])),
                        "errors": len(data.get("errors_encountered", [])),
                        "steps": data.get("total_steps", 0),
                    }
                )
            except (json.JSONDecodeError, OSError):
                continue
        return result

    def get_active(self) -> IterationRecord | None:
        """获取当前活跃的迭代（跨进程恢复）"""
        if self._active:
            return self._active
        # 尝试恢复最近的活跃迭代
        return None

    def _save(self, record: IterationRecord) -> None:
        """持久化迭代记录"""
        if record.memory_file:
            Path(record.memory_file).write_text(
                json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


# ══════════════════════════════════════════════════════════
# P1-2: 工程师级记忆 — 对标 Codex"工程师全局记忆"
# ══════════════════════════════════════════════════════════


@dataclass
class EngineerProfile:
    """工程师记忆 — 用户的编码风格偏好与习惯

    跨会话持续积累，让 Agent 越用越了解用户习惯。
    """

    naming_convention: str = "snake_case"  # snake_case | camelCase | PascalCase
    preferred_import_style: str = "absolute"  # absolute | relative
    test_framework: str = "pytest"
    preferred_libraries: list[str] = field(default_factory=list)
    banned_patterns: list[str] = field(default_factory=list)
    commit_style: str = "conventional"  # conventional | simple
    doc_style: str = "google"  # google | numpy | sphinx
    common_errors: list[str] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "naming_convention": self.naming_convention,
            "preferred_import_style": self.preferred_import_style,
            "test_framework": self.test_framework,
            "preferred_libraries": self.preferred_libraries,
            "banned_patterns": self.banned_patterns,
            "commit_style": self.commit_style,
            "doc_style": self.doc_style,
            "common_errors": self.common_errors[:10],
            "last_updated": self.last_updated,
        }


_PROFILE_PATH = MEMORY_DIR / "engineer_profile.json"


def get_engineer_profile() -> EngineerProfile:
    """获取工程师记忆（自动加载/创建）"""
    if _PROFILE_PATH.exists():
        try:
            data = json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))
            return EngineerProfile(
                naming_convention=data.get("naming_convention", "snake_case"),
                preferred_import_style=data.get("preferred_import_style", "absolute"),
                test_framework=data.get("test_framework", "pytest"),
                preferred_libraries=data.get("preferred_libraries", []),
                banned_patterns=data.get("banned_patterns", []),
                commit_style=data.get("commit_style", "conventional"),
                doc_style=data.get("doc_style", "google"),
                common_errors=data.get("common_errors", []),
                last_updated=data.get("last_updated", time.time()),
            )
        except (json.JSONDecodeError, OSError):
            return EngineerProfile()
    return EngineerProfile()


def save_engineer_profile(profile: EngineerProfile) -> None:
    """持久化工程师记忆"""
    profile.last_updated = time.time()
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    _PROFILE_PATH.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def update_engineer_preferences(
    naming: str | None = None,
    test_framework: str | None = None,
    libraries: list[str] | None = None,
    banned: list[str] | None = None,
) -> EngineerProfile:
    """更新工程师偏好 — 跨会话持久化"""
    profile = get_engineer_profile()
    if naming:
        profile.naming_convention = naming
    if test_framework:
        profile.test_framework = test_framework
    if libraries:
        # 合并去重
        existing = set(profile.preferred_libraries)
        existing.update(libraries)
        profile.preferred_libraries = sorted(existing)
    if banned:
        existing = set(profile.banned_patterns)
        existing.update(banned)
        profile.banned_patterns = sorted(existing)
    save_engineer_profile(profile)
    return profile


def get_engineer_profile_context() -> str:
    """生成工程师记忆的上下文片段（可注入 prompt）

    返回 Markdown 格式的工程师偏好说明。
    """
    profile = get_engineer_profile()
    parts = ["## 🧑‍💻 工程师记忆（来自历史经验）"]
    parts.append(f"- 命名规范: {profile.naming_convention}")
    parts.append(f"- 测试框架: {profile.test_framework}")
    if profile.preferred_libraries:
        parts.append(f"- 常用库: {', '.join(profile.preferred_libraries)}")
    if profile.banned_patterns:
        parts.append(f"- 禁止写法: {', '.join(profile.banned_patterns)}")
    return "\n".join(parts)


_iteration_memory: IterationMemory | None = None


def get_iteration_memory() -> IterationMemory:
    global _iteration_memory
    if _iteration_memory is None:
        _iteration_memory = IterationMemory()
    return _iteration_memory
