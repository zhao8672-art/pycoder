"""P1-1: 团队编排模块 — 拆分 TeamOrchestrator 上帝对象

按职责拆分为 3 个独立 Orchestrator + 1 个协调器：
- SessionOrchestrator: 会话生命周期管理（创建/查询/关闭 TeamRun）
- JobOrchestrator: 任务并行调度与聚合
- ReviewOrchestrator: QA 代码审查与修复循环
- TeamCoordinator: 对外门面，组合三者完成端到端工作流

迁移策略：
- 新代码使用 TeamCoordinator，旧 TeamOrchestrator 保留作为 fallback
- 路由层 team_api.py 改为依赖 TeamCoordinator
- 全部迁移稳定后删除旧 team_orchestrator.py
"""

from __future__ import annotations

from pycoder.server.services.team.job_orchestrator import (
    Job,
    JobOrchestrator,
)
from pycoder.server.services.team.review_orchestrator import (
    ReviewOrchestrator,
    ReviewResult,
)
from pycoder.server.services.team.session_orchestrator import (
    SessionOrchestrator,
    TeamRun,
)
from pycoder.server.services.team.team_coordinator import (
    TeamCoordinator,
    get_coordinator,
)

__all__ = [
    "SessionOrchestrator",
    "TeamRun",
    "JobOrchestrator",
    "Job",
    "ReviewOrchestrator",
    "ReviewResult",
    "TeamCoordinator",
    "get_coordinator",
]
