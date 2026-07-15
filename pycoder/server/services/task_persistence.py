"""
任务持久化与断点续传 — Codex/Hermes 风格

提供基于 SQLite 的任务状态持久化存储，支持：
  - 任务状态保存/加载/列表
  - 断点创建与恢复
  - 过期任务清理
  - 任务统计

对标 Codex 的任务持久化层和 Hermes 的断点续传机制。

用法:
    from pycoder.server.services.task_persistence import (
        TaskPersistence, TaskState, register_capabilities,
    )

    persistence = TaskPersistence(db_path=Path("data/tasks.db"))
    await persistence.save_task(task_state)
    task = await persistence.load_task("task-123")
"""

from __future__ import annotations

import asyncio
import json
import logging
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

# ══════════════════════════════════════════════════════════
# 常量
# ══════════════════════════════════════════════════════════

# SQLite 表结构 SQL
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS task_states (
    task_id        TEXT PRIMARY KEY,
    description    TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'pending',
    grade          TEXT NOT NULL DEFAULT 'MEDIUM',
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL,
    completed_at   REAL,
    steps_completed INTEGER NOT NULL DEFAULT 0,
    current_step   TEXT NOT NULL DEFAULT '',
    checkpoint_data TEXT NOT NULL DEFAULT '{}',
    result         TEXT NOT NULL DEFAULT '{}',
    error          TEXT NOT NULL DEFAULT ''
);
"""

# 索引
CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_task_status ON task_states(status);",
    "CREATE INDEX IF NOT EXISTS idx_task_created ON task_states(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_task_updated ON task_states(updated_at);",
    "CREATE INDEX IF NOT EXISTS idx_task_grade ON task_states(grade);",
]

# 有效状态列表
VALID_STATUSES: set[str] = {
    "pending",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
}

# 有效级别列表
VALID_GRADES: set[str] = {"LIGHT", "MEDIUM", "HEAVY"}


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class TaskState:
    """任务状态数据模型

    包含任务的完整生命周期信息，支持序列化持久化。
    """

    task_id: str  # 任务唯一标识
    description: str  # 任务描述
    status: str = "pending"  # 状态: pending/running/paused/completed/failed/cancelled
    grade: str = "MEDIUM"  # 难度级别: LIGHT/MEDIUM/HEAVY
    created_at: float = field(default_factory=time.time)  # 创建时间戳
    updated_at: float = field(default_factory=time.time)  # 最后更新时间戳
    completed_at: float | None = None  # 完成时间戳
    steps_completed: int = 0  # 已完成步骤数
    current_step: str = ""  # 当前步骤描述
    checkpoint_data: dict[str, Any] = field(default_factory=dict)  # 断点数据
    result: dict[str, Any] = field(default_factory=dict)  # 执行结果
    error: str = ""  # 错误信息

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "task_id": self.task_id,
            "description": self.description,
            "status": self.status,
            "grade": self.grade,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "steps_completed": self.steps_completed,
            "current_step": self.current_step,
            "checkpoint_data": self.checkpoint_data,
            "result": self.result,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskState:
        """从字典反序列化"""
        return cls(
            task_id=data.get("task_id", ""),
            description=data.get("description", ""),
            status=data.get("status", "pending"),
            grade=data.get("grade", "MEDIUM"),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            completed_at=data.get("completed_at"),
            steps_completed=data.get("steps_completed", 0),
            current_step=data.get("current_step", ""),
            checkpoint_data=data.get("checkpoint_data", {}),
            result=data.get("result", {}),
            error=data.get("error", ""),
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> TaskState:
        """从 SQLite 行数据构造"""
        return cls(
            task_id=row["task_id"],
            description=row["description"],
            status=row["status"],
            grade=row["grade"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            steps_completed=row["steps_completed"],
            current_step=row["current_step"],
            checkpoint_data=json.loads(row["checkpoint_data"] or "{}"),
            result=json.loads(row["result"] or "{}"),
            error=row["error"] or "",
        )


# ══════════════════════════════════════════════════════════
# TaskPersistence — 任务持久化管理器
# ══════════════════════════════════════════════════════════


class TaskPersistence:
    """任务持久化管理器

    基于 SQLite 的任务状态持久存储，支持断点续传。
    对标 Codex 任务持久化层和 Hermes 断点恢复机制。

    用法:
        persistence = TaskPersistence()
        await persistence.save_task(task_state)
        task = await persistence.load_task("task-123")
    """

    def __init__(self, db_path: Path | None = None) -> None:
        """初始化持久化管理器

        Args:
            db_path: SQLite 数据库文件路径，默认存放在 pycoder/data/tasks.db
        """
        if db_path is None:
            base_dir = Path(__file__).resolve().parent.parent.parent.parent
            data_dir = base_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = data_dir / "tasks.db"

        self._db_path = db_path
        self._lock = asyncio.Lock()
        self._initialized = False

    # ── 初始化 ──────────────────────────────────────

    async def _ensure_initialized(self) -> None:
        """确保数据库已初始化"""
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            def _init_db() -> None:
                conn = sqlite3.connect(str(self._db_path))
                conn.row_factory = sqlite3.Row
                try:
                    conn.execute(CREATE_TABLE_SQL)
                    for idx_sql in CREATE_INDEXES_SQL:
                        conn.execute(idx_sql)
                    conn.commit()
                finally:
                    conn.close()

            await asyncio.to_thread(_init_db)
            self._initialized = True
            logger.info("任务持久化数据库已初始化: %s", self._db_path)

    # ── 内部数据库操作 ───────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接（同步）"""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # ── 保存任务 ────────────────────────────────────

    async def save_task(self, task: TaskState) -> TaskState:
        """保存任务状态

        如果任务已存在则更新，否则插入新记录。

        Args:
            task: 任务状态对象

        Returns:
            更新后的 TaskState（含更新的时间戳）
        """
        await self._ensure_initialized()

        task.updated_at = time.time()

        def _do_save() -> None:
            conn = self._get_conn()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO task_states
                        (task_id, description, status, grade, created_at, updated_at,
                         completed_at, steps_completed, current_step,
                         checkpoint_data, result, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task.task_id,
                        task.description,
                        task.status,
                        task.grade,
                        task.created_at,
                        task.updated_at,
                        task.completed_at,
                        task.steps_completed,
                        task.current_step,
                        json.dumps(task.checkpoint_data, ensure_ascii=False),
                        json.dumps(task.result, ensure_ascii=False),
                        task.error,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_do_save)
        logger.debug("任务已保存: %s (状态: %s)", task.task_id, task.status)
        return task

    # ── 加载任务 ────────────────────────────────────

    async def load_task(self, task_id: str) -> TaskState | None:
        """加载任务状态

        Args:
            task_id: 任务唯一标识

        Returns:
            TaskState 对象，不存在时返回 None
        """
        await self._ensure_initialized()

        def _do_load() -> sqlite3.Row | None:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT * FROM task_states WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                return row
            finally:
                conn.close()

        row = await asyncio.to_thread(_do_load)
        if row is None:
            logger.debug("任务不存在: %s", task_id)
            return None

        task = TaskState.from_row(row)
        logger.debug("任务已加载: %s (状态: %s)", task_id, task.status)
        return task

    # ── 列表任务 ────────────────────────────────────

    async def list_tasks(
        self,
        status_filter: str | None = None,
        grade_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskState]:
        """列出任务

        Args:
            status_filter: 按状态过滤，None 表示全部
            grade_filter: 按级别过滤，None 表示全部
            limit: 最大返回数量
            offset: 分页偏移

        Returns:
            TaskState 列表，按更新时间倒序
        """
        await self._ensure_initialized()

        # 构建查询
        conditions: list[str] = []
        params: list[Any] = []

        if status_filter and status_filter in VALID_STATUSES:
            conditions.append("status = ?")
            params.append(status_filter)

        if grade_filter and grade_filter in VALID_GRADES:
            conditions.append("grade = ?")
            params.append(grade_filter)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        sql = f"""
            SELECT * FROM task_states
            {where_clause}
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        def _do_list() -> list[sqlite3.Row]:
            conn = self._get_conn()
            try:
                rows = conn.execute(sql, params).fetchall()
                return rows
            finally:
                conn.close()

        rows = await asyncio.to_thread(_do_list)
        tasks = [TaskState.from_row(row) for row in rows]
        logger.debug("列出任务: %d 条 (状态过滤: %s)", len(tasks), status_filter or "全部")
        return tasks

    # ── 创建断点 ────────────────────────────────────

    async def create_checkpoint(
        self,
        task_id: str,
        data: dict[str, Any],
        current_step: str = "",
    ) -> TaskState | None:
        """创建任务断点

        保存当前任务状态和中间数据，支持后续断点恢复。

        Args:
            task_id: 任务唯一标识
            data: 断点数据（包含当前上下文、中间结果等）
            current_step: 当前步骤描述

        Returns:
            更新后的 TaskState，任务不存在时返回 None
        """
        await self._ensure_initialized()

        task = await self.load_task(task_id)
        if task is None:
            logger.warning("无法创建断点，任务不存在: %s", task_id)
            return None

        task.checkpoint_data = data
        task.current_step = current_step
        task.status = "paused"
        task.updated_at = time.time()

        await self.save_task(task)
        logger.info("断点已创建: %s (步骤: %s)", task_id, current_step)
        return task

    # ── 从断点恢复 ──────────────────────────────────

    async def resume_from_checkpoint(self, task_id: str) -> TaskState | None:
        """从上次断点恢复任务

        将任务状态从 paused 恢复为 running，并返回断点数据。

        Args:
            task_id: 任务唯一标识

        Returns:
            恢复后的 TaskState，断点不存在或任务不存在时返回 None
        """
        await self._ensure_initialized()

        task = await self.load_task(task_id)
        if task is None:
            logger.warning("无法恢复断点，任务不存在: %s", task_id)
            return None

        if not task.checkpoint_data:
            logger.warning("任务 %s 没有断点数据", task_id)
            return None

        task.status = "running"
        task.updated_at = time.time()
        await self.save_task(task)

        logger.info(
            "从断点恢复任务: %s (步骤: %s, 已完成: %d 步)",
            task_id,
            task.current_step,
            task.steps_completed,
        )
        return task

    # ── 删除任务 ────────────────────────────────────

    async def delete_task(self, task_id: str) -> bool:
        """删除任务

        Args:
            task_id: 任务唯一标识

        Returns:
            True 表示删除成功，False 表示任务不存在
        """
        await self._ensure_initialized()

        def _do_delete() -> bool:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "DELETE FROM task_states WHERE task_id = ?",
                    (task_id,),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

        deleted = await asyncio.to_thread(_do_delete)
        if deleted:
            logger.info("任务已删除: %s", task_id)
        else:
            logger.debug("删除失败，任务不存在: %s", task_id)
        return deleted

    # ── 清理过期任务 ────────────────────────────────

    async def cleanup_expired(self, days: int = 30) -> int:
        """清理过期任务

        删除 completed_at 超过指定天数的已完成/失败任务。

        Args:
            days: 保留天数，默认 30 天

        Returns:
            清理的任务数量
        """
        await self._ensure_initialized()

        cutoff = time.time() - (days * 86400)

        def _do_cleanup() -> int:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    """
                    DELETE FROM task_states
                    WHERE status IN ('completed', 'failed', 'cancelled')
                      AND completed_at IS NOT NULL
                      AND completed_at < ?
                    """,
                    (cutoff,),
                )
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()

        count = await asyncio.to_thread(_do_cleanup)
        logger.info("清理过期任务: %d 条 (超过 %d 天)", count, days)
        return count

    # ── 统计信息 ────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """获取任务统计信息

        Returns:
            包含总任务数、各状态数量、各级别数量等统计信息
        """
        if not self._initialized:
            return {
                "total": 0,
                "by_status": {},
                "by_grade": {},
                "avg_steps_completed": 0.0,
                "db_path": str(self._db_path),
            }

        def _do_stats() -> dict[str, Any]:
            conn = self._get_conn()
            try:
                total = conn.execute(
                    "SELECT COUNT(*) FROM task_states"
                ).fetchone()[0]

                status_rows = conn.execute(
                    "SELECT status, COUNT(*) as cnt FROM task_states GROUP BY status"
                ).fetchall()
                by_status = {row["status"]: row["cnt"] for row in status_rows}

                grade_rows = conn.execute(
                    "SELECT grade, COUNT(*) as cnt FROM task_states GROUP BY grade"
                ).fetchall()
                by_grade = {row["grade"]: row["cnt"] for row in grade_rows}

                avg_steps = conn.execute(
                    "SELECT AVG(steps_completed) FROM task_states"
                ).fetchone()[0] or 0.0

                return {
                    "total": total,
                    "by_status": by_status,
                    "by_grade": by_grade,
                    "avg_steps_completed": round(avg_steps, 1),
                    "db_path": str(self._db_path),
                }
            finally:
                conn.close()

        return _do_stats()

    async def get_stats_async(self) -> dict[str, Any]:
        """异步获取任务统计信息"""
        await self._ensure_initialized()
        return await asyncio.to_thread(self.get_stats)


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_persistence_instance: TaskPersistence | None = None


def get_task_persistence(db_path: Path | None = None) -> TaskPersistence:
    """获取 TaskPersistence 单例

    Args:
        db_path: 数据库路径（首次调用时设置）

    Returns:
        TaskPersistence 实例
    """
    global _persistence_instance
    if _persistence_instance is None:
        _persistence_instance = TaskPersistence(db_path=db_path)
    return _persistence_instance


# ══════════════════════════════════════════════════════════
# 能力注册
# ══════════════════════════════════════════════════════════


def register_capabilities(registry: Any) -> list[CapabilityDefinition]:
    """向 V2 能力总线注册任务持久化能力

    注册的能力:
      - task.save       — 保存任务状态
      - task.load       — 加载任务状态
      - task.list       — 列出任务
      - task.checkpoint — 创建断点
      - task.resume     — 从断点恢复

    Args:
        registry: CapabilityRegistry 实例

    Returns:
        已注册的能力定义列表
    """
    persistence = get_task_persistence()

    definitions: list[CapabilityDefinition] = []

    # ── task.save ──────────────────────────────────

    async def _handle_save(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """保存任务处理器"""
        task_data = params.get("task", {})
        task_id = task_data.get("task_id", "")
        if not task_id:
            task_id = str(uuid.uuid4())
            task_data["task_id"] = task_id

        task = TaskState.from_dict(task_data)
        saved = await persistence.save_task(task)
        logger.info("通过能力总线保存任务: %s", task_id)
        return saved.to_dict()

    def_save = CapabilityDefinition(
        id="task.save",
        name="保存任务状态",
        description="将任务状态持久化到 SQLite 数据库，支持插入和更新",
        category=CapabilityCategory.SYSTEM,
        permission=TrustLevel.WORKSPACE_WRITE,
        execution=ExecutionMode.SYNC,
        side_effects=[SideEffect.FILE_WRITE],
        version="2.0.0",
        timeout_ms=10000,
        tags=["task", "save", "persistence", "sqlite"],
    )
    definitions.append(def_save)
    registry.register(def_save, handler=_handle_save)

    # ── task.load ──────────────────────────────────

    async def _handle_load(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """加载任务处理器"""
        task_id = params.get("task_id", "")
        if not task_id:
            return {"error": "缺少 task_id 参数", "success": False}
        task = await persistence.load_task(task_id)
        if task is None:
            return {"error": f"任务不存在: {task_id}", "success": False}
        return task.to_dict()

    def_load = CapabilityDefinition(
        id="task.load",
        name="加载任务状态",
        description="从 SQLite 数据库加载指定任务的状态",
        category=CapabilityCategory.SYSTEM,
        permission=TrustLevel.READ_ONLY,
        execution=ExecutionMode.SYNC,
        side_effects=[SideEffect.FILE_READ],
        version="2.0.0",
        timeout_ms=5000,
        tags=["task", "load", "persistence", "sqlite"],
    )
    definitions.append(def_load)
    registry.register(def_load, handler=_handle_load)

    # ── task.list ──────────────────────────────────

    async def _handle_list(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """列出任务处理器"""
        status_filter = params.get("status")
        grade_filter = params.get("grade")
        limit = int(params.get("limit", 50))
        offset = int(params.get("offset", 0))
        tasks = await persistence.list_tasks(
            status_filter=status_filter,
            grade_filter=grade_filter,
            limit=limit,
            offset=offset,
        )
        return {
            "tasks": [t.to_dict() for t in tasks],
            "total": len(tasks),
            "limit": limit,
            "offset": offset,
        }

    def_list = CapabilityDefinition(
        id="task.list",
        name="列出任务",
        description="按状态/级别过滤列出任务，支持分页",
        category=CapabilityCategory.SYSTEM,
        permission=TrustLevel.READ_ONLY,
        execution=ExecutionMode.SYNC,
        side_effects=[SideEffect.FILE_READ],
        version="2.0.0",
        timeout_ms=10000,
        tags=["task", "list", "persistence", "query"],
    )
    definitions.append(def_list)
    registry.register(def_list, handler=_handle_list)

    # ── task.checkpoint ────────────────────────────

    async def _handle_checkpoint(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """创建断点处理器"""
        task_id = params.get("task_id", "")
        if not task_id:
            return {"error": "缺少 task_id 参数", "success": False}
        checkpoint_data = params.get("data", {})
        current_step = params.get("current_step", "")
        task = await persistence.create_checkpoint(task_id, checkpoint_data, current_step)
        if task is None:
            return {"error": f"任务不存在: {task_id}", "success": False}
        return task.to_dict()

    def_checkpoint = CapabilityDefinition(
        id="task.checkpoint",
        name="创建任务断点",
        description="保存当前任务状态和中间数据，将任务设为暂停状态以支持后续恢复",
        category=CapabilityCategory.SYSTEM,
        permission=TrustLevel.WORKSPACE_WRITE,
        execution=ExecutionMode.SYNC,
        side_effects=[SideEffect.FILE_WRITE],
        version="2.0.0",
        timeout_ms=10000,
        tags=["task", "checkpoint", "persistence", "resume"],
    )
    definitions.append(def_checkpoint)
    registry.register(def_checkpoint, handler=_handle_checkpoint)

    # ── task.resume ────────────────────────────────

    async def _handle_resume(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """从断点恢复处理器"""
        task_id = params.get("task_id", "")
        if not task_id:
            return {"error": "缺少 task_id 参数", "success": False}
        task = await persistence.resume_from_checkpoint(task_id)
        if task is None:
            return {"error": f"无法恢复任务: {task_id}，可能不存在或无断点", "success": False}
        return task.to_dict()

    def_resume = CapabilityDefinition(
        id="task.resume",
        name="从断点恢复任务",
        description="从上次保存的断点恢复任务，将状态从暂停恢复为运行中",
        category=CapabilityCategory.SYSTEM,
        permission=TrustLevel.WORKSPACE_WRITE,
        execution=ExecutionMode.SYNC,
        side_effects=[SideEffect.FILE_READ, SideEffect.FILE_WRITE],
        version="2.0.0",
        timeout_ms=10000,
        tags=["task", "resume", "checkpoint", "recovery"],
    )
    definitions.append(def_resume)
    registry.register(def_resume, handler=_handle_resume)

    logger.info("任务持久化能力已注册到 V2 总线: %d 个能力", len(definitions))
    return definitions


# ══════════════════════════════════════════════════════════
# 导出
# ══════════════════════════════════════════════════════════

__all__ = [
    "TaskState",
    "TaskPersistence",
    "register_capabilities",
    "get_task_persistence",
    "VALID_STATUSES",
    "VALID_GRADES",
]