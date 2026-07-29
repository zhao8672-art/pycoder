"""任务持久化服务 - 注册所有任务持久化能力"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# 常量定义
# ══════════════════════════════════════════════════════════

VALID_STATUSES: set[str] = {"pending", "running", "paused", "completed", "failed", "cancelled"}
VALID_GRADES: set[str] = {"LIGHT", "MEDIUM", "HEAVY"}

# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class TaskState:
    """任务状态数据模型"""

    task_id: str
    description: str = ""
    status: str = "pending"
    grade: str = "MEDIUM"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    steps_completed: int = 0
    current_step: str = ""
    checkpoint_data: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""

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
            created_at=data.get("created_at", 0.0),
            updated_at=data.get("updated_at", 0.0),
            completed_at=data.get("completed_at"),
            steps_completed=data.get("steps_completed", 0),
            current_step=data.get("current_step", ""),
            checkpoint_data=data.get("checkpoint_data", {}),
            result=data.get("result", {}),
            error=data.get("error", ""),
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> TaskState:
        """从 SQLite Row 构造"""
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
            checkpoint_data=json.loads(row["checkpoint_data"]) if row["checkpoint_data"] else {},
            result=json.loads(row["result"]) if row["result"] else {},
            error=row["error"],
        )


# ══════════════════════════════════════════════════════════
# 任务持久化管理器
# ══════════════════════════════════════════════════════════


class TaskPersistence:
    """任务持久化管理器 — 基于 SQLite 的任务状态存储"""

    def __init__(self, db_path: str | Path = "data/tasks.db"):
        self._db_path = Path(db_path)
        self._initialized = False
        self._lock = asyncio.Lock()

    async def _ensure_initialized(self) -> None:
        """确保数据库已初始化"""
        if self._initialized:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_states (
                task_id TEXT PRIMARY KEY,
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                grade TEXT DEFAULT 'MEDIUM',
                created_at REAL DEFAULT 0.0,
                updated_at REAL DEFAULT 0.0,
                completed_at REAL,
                steps_completed INTEGER DEFAULT 0,
                current_step TEXT DEFAULT '',
                checkpoint_data TEXT DEFAULT '{}',
                result TEXT DEFAULT '{}',
                error TEXT DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_task_status ON task_states(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_task_grade ON task_states(grade)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_task_updated ON task_states(updated_at)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_status_grade ON task_states(status, grade)"
        )
        conn.commit()
        conn.close()
        self._initialized = True

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    async def save_task(self, task: TaskState) -> TaskState:
        """保存或更新任务"""
        await self._ensure_initialized()
        task.updated_at = time.time()
        async with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO task_states
                       (task_id, description, status, grade, created_at, updated_at,
                        completed_at, steps_completed, current_step, checkpoint_data,
                        result, error)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        return task

    async def load_task(self, task_id: str) -> TaskState | None:
        """加载任务"""
        await self._ensure_initialized()
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM task_states WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                return None
            return TaskState.from_row(row)
        finally:
            conn.close()

    async def list_tasks(
        self,
        status_filter: str | None = None,
        grade_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskState]:
        """列出任务"""
        await self._ensure_initialized()
        conn = self._get_conn()
        try:
            conditions: list[str] = []
            params: list[Any] = []
            if status_filter and status_filter in VALID_STATUSES:
                conditions.append("status = ?")
                params.append(status_filter)
            if grade_filter and grade_filter in VALID_GRADES:
                conditions.append("grade = ?")
                params.append(grade_filter)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            query = f"SELECT * FROM task_states {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(query, params).fetchall()
            return [TaskState.from_row(r) for r in rows]
        finally:
            conn.close()

    async def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        await self._ensure_initialized()
        async with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute("DELETE FROM task_states WHERE task_id = ?", (task_id,))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    async def create_checkpoint(
        self, task_id: str, data: dict[str, Any], current_step: str = ""
    ) -> TaskState | None:
        """创建断点"""
        task = await self.load_task(task_id)
        if task is None:
            return None
        task.status = "paused"
        task.checkpoint_data = data
        task.current_step = current_step
        return await self.save_task(task)

    async def resume_from_checkpoint(self, task_id: str) -> TaskState | None:
        """从断点恢复"""
        task = await self.load_task(task_id)
        if task is None:
            return None
        if not task.checkpoint_data:
            return None
        task.status = "running"
        return await self.save_task(task)

    async def get_running_tasks(self) -> list[TaskState]:
        """获取运行中的任务"""
        return await self.list_tasks(status_filter="running", limit=1000)

    async def cleanup_expired(self, max_age_days: int = 30) -> int:
        """清理过期任务（仅清理 completed/failed 状态）"""
        await self._ensure_initialized()
        cutoff = time.time() - max_age_days * 86400
        async with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "DELETE FROM task_states WHERE status IN ('completed', 'failed') AND updated_at < ?",
                    (cutoff,),
                )
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息（同步）"""
        if not self._initialized:
            return {"total": 0, "by_status": {}, "by_grade": {}, "avg_steps_completed": 0.0}
        conn = self._get_conn()
        try:
            total = conn.execute("SELECT COUNT(*) FROM task_states").fetchone()[0]
            by_status_rows = conn.execute(
                "SELECT status, COUNT(*) FROM task_states GROUP BY status"
            ).fetchall()
            by_grade_rows = conn.execute(
                "SELECT grade, COUNT(*) FROM task_states GROUP BY grade"
            ).fetchall()
            avg_steps = (
                conn.execute("SELECT AVG(steps_completed) FROM task_states").fetchone()[0] or 0.0
            )
            return {
                "total": total,
                "by_status": {r[0]: r[1] for r in by_status_rows},
                "by_grade": {r[0]: r[1] for r in by_grade_rows},
                "avg_steps_completed": round(avg_steps, 2),
            }
        finally:
            conn.close()

    async def get_stats_async(self) -> dict[str, Any]:
        """获取统计信息（异步）"""
        await self._ensure_initialized()
        return await asyncio.to_thread(self.get_stats)


# ══════════════════════════════════════════════════════════
# 单例管理
# ══════════════════════════════════════════════════════════

_persistence_instance: TaskPersistence | None = None


def get_task_persistence(db_path: str | Path | None = None) -> TaskPersistence:
    """获取 TaskPersistence 单例"""
    global _persistence_instance
    if _persistence_instance is None:
        _persistence_instance = TaskPersistence(db_path=db_path or "data/tasks.db")
    return _persistence_instance


# ══════════════════════════════════════════════════════════
# 能力注册（保留原有代码）
# ══════════════════════════════════════════════════════════


def register_capabilities(registry: Any) -> None:
    """注册所有任务持久化能力"""
    _register_task_crud(registry)
    _register_task_query(registry)
    _register_task_lifecycle(registry)
    _register_task_scheduling(registry)
    _register_task_dependencies(registry)


def _register_task_crud(registry: Any) -> None:
    """注册任务 CRUD 能力"""
    registry.register(
        name="task.create",
        description="创建新任务",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "任务标题"},
                "description": {"type": "string", "description": "任务描述"},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "assignee": {"type": "string", "description": "负责人"},
                "due_date": {"type": "string", "description": "截止日期"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title"],
        },
        handler=_handle_task_create,
    )

    registry.register(
        name="task.update",
        description="更新任务信息",
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务 ID"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "assignee": {"type": "string"},
                "due_date": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["task_id"],
        },
        handler=_handle_task_update,
    )

    registry.register(
        name="task.delete",
        description="删除任务",
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务 ID"},
                "force": {"type": "boolean", "description": "强制删除（含子任务）"},
            },
            "required": ["task_id"],
        },
        handler=_handle_task_delete,
    )


def _register_task_query(registry: Any) -> None:
    """注册任务查询能力"""
    registry.register(
        name="task.get",
        description="获取任务详情",
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务 ID"},
            },
            "required": ["task_id"],
        },
        handler=_handle_task_get,
    )

    registry.register(
        name="task.list",
        description="列出任务",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "按状态过滤"},
                "priority": {"type": "string", "description": "按优先级过滤"},
                "assignee": {"type": "string", "description": "按负责人过滤"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "page": {"type": "integer", "description": "页码"},
                "page_size": {"type": "integer", "description": "每页数量"},
                "sort_by": {"type": "string", "description": "排序字段"},
                "sort_order": {"type": "string", "enum": ["asc", "desc"]},
            },
        },
        handler=_handle_task_list,
    )

    registry.register(
        name="task.search",
        description="搜索任务",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "fields": {"type": "array", "items": {"type": "string"}},
                "page": {"type": "integer"},
                "page_size": {"type": "integer"},
            },
            "required": ["query"],
        },
        handler=_handle_task_search,
    )


def _register_task_lifecycle(registry: Any) -> None:
    """注册任务生命周期能力"""
    registry.register(
        name="task.start",
        description="开始执行任务",
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务 ID"},
            },
            "required": ["task_id"],
        },
        handler=_handle_task_start,
    )

    registry.register(
        name="task.complete",
        description="完成任务",
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务 ID"},
                "result": {"type": "string", "description": "任务结果"},
                "notes": {"type": "string", "description": "完成备注"},
            },
            "required": ["task_id"],
        },
        handler=_handle_task_complete,
    )

    registry.register(
        name="task.cancel",
        description="取消任务",
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务 ID"},
                "reason": {"type": "string", "description": "取消原因"},
            },
            "required": ["task_id"],
        },
        handler=_handle_task_cancel,
    )

    registry.register(
        name="task.pause",
        description="暂停任务",
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务 ID"},
            },
            "required": ["task_id"],
        },
        handler=_handle_task_pause,
    )

    registry.register(
        name="task.resume",
        description="恢复暂停的任务",
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务 ID"},
            },
            "required": ["task_id"],
        },
        handler=_handle_task_resume,
    )


def _register_task_scheduling(registry: Any) -> None:
    """注册任务调度能力"""
    registry.register(
        name="task.schedule",
        description="设置任务调度计划",
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务 ID"},
                "cron_expression": {"type": "string", "description": "Cron 表达式"},
                "timezone": {"type": "string", "description": "时区"},
                "max_runs": {"type": "integer", "description": "最大执行次数"},
            },
            "required": ["task_id", "cron_expression"],
        },
        handler=_handle_task_schedule,
    )

    registry.register(
        name="task.unschedule",
        description="取消任务调度",
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务 ID"},
            },
            "required": ["task_id"],
        },
        handler=_handle_task_unschedule,
    )


def _register_task_dependencies(registry: Any) -> None:
    """注册任务依赖能力"""
    registry.register(
        name="task.add_dependency",
        description="添加任务依赖",
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务 ID"},
                "depends_on": {"type": "string", "description": "依赖的任务 ID"},
                "dependency_type": {
                    "type": "string",
                    "enum": ["finish_to_start", "start_to_start", "finish_to_finish"],
                },
            },
            "required": ["task_id", "depends_on"],
        },
        handler=_handle_task_add_dependency,
    )

    registry.register(
        name="task.remove_dependency",
        description="移除任务依赖",
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务 ID"},
                "depends_on": {"type": "string", "description": "依赖的任务 ID"},
            },
            "required": ["task_id", "depends_on"],
        },
        handler=_handle_task_remove_dependency,
    )


# ── 处理器实现 ──


async def _handle_task_create(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理任务创建"""
    from pycoder.server.services.task_store import TaskStore

    store = TaskStore()
    task = await store.create_task(
        title=params["title"],
        description=params.get("description", ""),
        priority=params.get("priority", "medium"),
        assignee=params.get("assignee"),
        due_date=params.get("due_date"),
        tags=params.get("tags", []),
    )
    return {"success": True, "task": task.to_dict()}


async def _handle_task_update(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理任务更新"""
    from pycoder.server.services.task_store import TaskStore

    store = TaskStore()
    task = await store.update_task(
        task_id=params["task_id"],
        updates={k: v for k, v in params.items() if k != "task_id"},
    )
    return {"success": True, "task": task.to_dict()}


async def _handle_task_delete(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理任务删除"""
    from pycoder.server.services.task_store import TaskStore

    store = TaskStore()
    await store.delete_task(
        task_id=params["task_id"],
        force=params.get("force", False),
    )
    return {"success": True}


async def _handle_task_get(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理任务查询"""
    from pycoder.server.services.task_store import TaskStore

    store = TaskStore()
    task = await store.get_task(task_id=params["task_id"])
    if task:
        return {"success": True, "task": task.to_dict()}
    return {"success": False, "error": f"任务不存在: {params['task_id']}"}


async def _handle_task_list(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理任务列表"""
    from pycoder.server.services.task_store import TaskStore

    store = TaskStore()
    result = await store.list_tasks(
        status=params.get("status"),
        priority=params.get("priority"),
        assignee=params.get("assignee"),
        tags=params.get("tags"),
        page=params.get("page", 1),
        page_size=params.get("page_size", 20),
        sort_by=params.get("sort_by", "created_at"),
        sort_order=params.get("sort_order", "desc"),
    )
    return {"success": True, **result}


async def _handle_task_search(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理任务搜索"""
    from pycoder.server.services.task_store import TaskStore

    store = TaskStore()
    result = await store.search_tasks(
        query=params["query"],
        fields=params.get("fields"),
        page=params.get("page", 1),
        page_size=params.get("page_size", 20),
    )
    return {"success": True, **result}


async def _handle_task_start(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理任务开始"""
    from pycoder.server.services.task_store import TaskStore

    store = TaskStore()
    task = await store.start_task(task_id=params["task_id"])
    return {"success": True, "task": task.to_dict()}


async def _handle_task_complete(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理任务完成"""
    from pycoder.server.services.task_store import TaskStore

    store = TaskStore()
    task = await store.complete_task(
        task_id=params["task_id"],
        result=params.get("result"),
        notes=params.get("notes"),
    )
    return {"success": True, "task": task.to_dict()}


async def _handle_task_cancel(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理任务取消"""
    from pycoder.server.services.task_store import TaskStore

    store = TaskStore()
    task = await store.cancel_task(
        task_id=params["task_id"],
        reason=params.get("reason"),
    )
    return {"success": True, "task": task.to_dict()}


async def _handle_task_pause(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理任务暂停"""
    from pycoder.server.services.task_store import TaskStore

    store = TaskStore()
    task = await store.pause_task(task_id=params["task_id"])
    return {"success": True, "task": task.to_dict()}


async def _handle_task_resume(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理任务恢复"""
    from pycoder.server.services.task_store import TaskStore

    store = TaskStore()
    task = await store.resume_task(task_id=params["task_id"])
    return {"success": True, "task": task.to_dict()}


async def _handle_task_schedule(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """处理任务调度设置"""
    from pycoder.server.services.task_store import TaskStore

    store = TaskStore()
    task = await store.schedule_task(
        task_id=params["task_id"],
        cron_expression=params["cron_expression"],
        timezone=params.get("timezone", "UTC"),
        max_runs=params.get("max_runs"),
    )
    return {"success": True, "task": task.to_dict()}


async def _handle_task_unschedule(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """处理任务调度取消"""
    from pycoder.server.services.task_store import TaskStore

    store = TaskStore()
    task = await store.unschedule_task(task_id=params["task_id"])
    return {"success": True, "task": task.to_dict()}


async def _handle_task_add_dependency(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """处理任务依赖添加"""
    from pycoder.server.services.task_store import TaskStore

    store = TaskStore()
    task = await store.add_dependency(
        task_id=params["task_id"],
        depends_on=params["depends_on"],
        dependency_type=params.get("dependency_type", "finish_to_start"),
    )
    return {"success": True, "task": task.to_dict()}


async def _handle_task_remove_dependency(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """处理任务依赖移除"""
    from pycoder.server.services.task_store import TaskStore

    store = TaskStore()
    task = await store.remove_dependency(
        task_id=params["task_id"],
        depends_on=params["depends_on"],
    )
    return {"success": True, "task": task.to_dict()}
