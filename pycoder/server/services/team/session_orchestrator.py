"""P1-1: 会话生命周期管理 — 创建、查询、关闭团队执行会话

从 team_orchestrator.py 抽取的职责：
- TeamRun 数据类定义
- runs 存储（dict[str, TeamRun]）
- create / get / list / close 操作
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from pycoder.server.log import log


@dataclass
class TeamRun:
    """一次团队执行会话"""

    id: str = field(default_factory=lambda: f"team-{uuid.uuid4().hex[:8]}")
    request: str = ""
    status: str = (
        "pending"  # pending | decomposing | executing | reviewing | delivering | done | failed
    )
    tasks: list[dict] = field(default_factory=list)
    results: dict[str, str] = field(default_factory=dict)
    review_issues: list[dict] = field(default_factory=list)
    review_rounds: int = 0
    quality_passed: bool = False  # 质量门禁是否通过（交付即达标）
    quality_summary: str = ""  # 质量门禁结论摘要
    current_agent: str = ""
    progress: int = 0  # 0-100
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0


class SessionOrchestrator:
    """会话生命周期管理 — 纯存储与查询，不含业务逻辑"""

    def __init__(self) -> None:
        self._runs: dict[str, TeamRun] = {}

    def create(self, request: str) -> TeamRun:
        """创建新的团队执行会话"""
        run = TeamRun(request=request)
        self._runs[run.id] = run
        log.info("team_session_created", run_id=run.id, request_preview=request[:80])
        return run

    def get(self, run_id: str) -> TeamRun | None:
        """获取会话，不存在返回 None"""
        return self._runs.get(run_id)

    def list(self, limit: int = 10) -> list[dict]:
        """列出最近的会话（按创建时间倒序）"""
        runs = sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True)
        return [r.__dict__ for r in runs[:limit]]

    def close(self, run_id: str, status: str = "done") -> bool:
        """关闭会话，设置最终状态"""
        run = self._runs.get(run_id)
        if not run:
            return False
        run.status = status
        run.completed_at = time.time()
        log.info("team_session_closed", run_id=run_id, status=status)
        return True

    def fail(self, run_id: str, error: str) -> bool:
        """标记会话失败"""
        run = self._runs.get(run_id)
        if not run:
            return False
        run.status = "failed"
        run.completed_at = time.time()
        log.error("team_session_failed", run_id=run_id, error=error)
        return True
