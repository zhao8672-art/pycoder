"""P1-1/H2 测试：验证 TeamOrchestrator 拆分为 SessionOrchestrator / JobOrchestrator /
ReviewOrchestrator / TeamCoordinator，且旧 TeamOrchestrator 类已删除（H2）

测试目标：
- 三个独立 Orchestrator 各自可独立工作
- TeamCoordinator 作为门面正确组合三者
- 旧 TeamOrchestrator 类已删除（H2），不可再导入
- Agent 执行原语已迁移到 team.agent_tool_loop 子模块
- team_api.py 路由层使用新的 get_coordinator
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


# ══════════════════════════════════════════════════════════
# SessionOrchestrator 测试
# ══════════════════════════════════════════════════════════


class TestSessionOrchestrator:
    def test_create_returns_team_run_with_id(self):
        from pycoder.server.services.team.session_orchestrator import (
            SessionOrchestrator, TeamRun,
        )
        sess = SessionOrchestrator()
        run = sess.create("test request")
        assert isinstance(run, TeamRun)
        assert run.id.startswith("team-")
        assert run.request == "test request"
        assert run.status == "pending"
        assert run.progress == 0

    def test_get_returns_existing_run(self):
        from pycoder.server.services.team.session_orchestrator import (
            SessionOrchestrator,
        )
        sess = SessionOrchestrator()
        run = sess.create("test")
        fetched = sess.get(run.id)
        assert fetched is run

    def test_get_returns_none_for_missing(self):
        from pycoder.server.services.team.session_orchestrator import (
            SessionOrchestrator,
        )
        sess = SessionOrchestrator()
        assert sess.get("nonexistent") is None

    def test_list_returns_recent_runs_limited(self):
        from pycoder.server.services.team.session_orchestrator import (
            SessionOrchestrator,
        )
        sess = SessionOrchestrator()
        for i in range(5):
            sess.create(f"task-{i}")
        runs = sess.list(limit=3)
        assert len(runs) == 3
        assert all("id" in r for r in runs)

    def test_close_sets_status_and_completed_at(self):
        from pycoder.server.services.team.session_orchestrator import (
            SessionOrchestrator,
        )
        sess = SessionOrchestrator()
        run = sess.create("test")
        assert sess.close(run.id, "done") is True
        assert run.status == "done"
        assert run.completed_at > 0

    def test_fail_sets_failed_status(self):
        from pycoder.server.services.team.session_orchestrator import (
            SessionOrchestrator,
        )
        sess = SessionOrchestrator()
        run = sess.create("test")
        assert sess.fail(run.id, "boom") is True
        assert run.status == "failed"


# ══════════════════════════════════════════════════════════
# JobOrchestrator 测试
# ══════════════════════════════════════════════════════════


class TestJobOrchestrator:
    @pytest.mark.asyncio
    async def test_parallel_execution_no_dependencies(self):
        from pycoder.server.services.team.job_orchestrator import (
            JobOrchestrator, Job,
        )
        jobs = [
            Job(task_id=f"t-{i}", title=f"task-{i}", description="d")
            for i in range(3)
        ]

        async def executor(job: Job) -> str:
            return f"result-{job.task_id}"

        orch = JobOrchestrator()
        executed, results = await orch.execute_with_dependencies(jobs, executor)

        assert executed == {"t-0", "t-1", "t-2"}
        assert results["t-0"] == "result-t-0"
        assert all(j.status == "done" for j in jobs)

    @pytest.mark.asyncio
    async def test_dependency_order_respected(self):
        """有依赖时，必须先完成依赖任务再执行下游"""
        from pycoder.server.services.team.job_orchestrator import (
            JobOrchestrator, Job,
        )
        jobs = [
            Job(task_id="t-1", title="task1", description="d"),
            Job(task_id="t-2", title="task2", description="d", depends_on=["t-1"]),
        ]
        execution_order: list[str] = []

        async def executor(job: Job) -> str:
            execution_order.append(job.task_id)
            return f"done-{job.task_id}"

        orch = JobOrchestrator()
        await orch.execute_with_dependencies(jobs, executor)

        assert execution_order.index("t-1") < execution_order.index("t-2")

    @pytest.mark.asyncio
    async def test_failed_job_does_not_block_others(self):
        """单个任务失败不应阻塞其他无依赖任务"""
        from pycoder.server.services.team.job_orchestrator import (
            JobOrchestrator, Job,
        )
        jobs = [
            Job(task_id="fail", title="failing", description="d"),
            Job(task_id="ok", title="ok", description="d"),
        ]

        async def executor(job: Job) -> str:
            if job.task_id == "fail":
                raise RuntimeError("boom")
            return "ok-result"

        orch = JobOrchestrator()
        executed, results = await orch.execute_with_dependencies(jobs, executor)

        assert "fail" in executed
        assert "ok" in executed
        # 失败任务不应有结果
        assert "fail" not in results
        # 成功任务应有结果
        assert results["ok"] == "ok-result"

    @pytest.mark.asyncio
    async def test_max_rounds_prevents_infinite_loop(self):
        """无可用任务时不应死循环"""
        from pycoder.server.services.team.job_orchestrator import (
            JobOrchestrator, Job,
        )
        # 互相依赖形成死锁
        jobs = [
            Job(task_id="a", title="a", description="d", depends_on=["b"]),
            Job(task_id="b", title="b", description="d", depends_on=["a"]),
        ]

        async def executor(job: Job) -> str:
            return "should not be called"

        orch = JobOrchestrator()
        executed, results = await orch.execute_with_dependencies(jobs, executor)

        # 无任务被执行
        assert executed == set()
        assert results == {}


# ══════════════════════════════════════════════════════════
# ReviewOrchestrator 测试
# ══════════════════════════════════════════════════════════


class TestReviewOrchestrator:
    @pytest.mark.asyncio
    async def test_review_code_returns_valid_result_on_success(self):
        from pycoder.server.services.team.review_orchestrator import (
            ReviewOrchestrator, ReviewResult,
        )
        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()

        # Mock chat_stream 返回有效 JSON
        async def fake_stream(_prompt):
            yield MagicMock(event_type="token",
                            content='{"passed": true, "issues": [], "score": 90, "summary": "ok"}')
        bridge.chat_stream = fake_stream

        orch = ReviewOrchestrator()
        result = await orch.review_code(bridge, "x = 1\n", "task-1")
        assert isinstance(result, ReviewResult)
        assert result.passed is True
        assert result.score == 90
        assert result.task_id == "task-1"

    @pytest.mark.asyncio
    async def test_review_code_handles_invalid_json_gracefully(self):
        from pycoder.server.services.team.review_orchestrator import (
            ReviewOrchestrator,
        )
        bridge = MagicMock()
        bridge.configure = MagicMock()
        bridge.config = MagicMock()

        async def fake_stream(_prompt):
            yield MagicMock(event_type="token", content="not json at all")
        bridge.chat_stream = fake_stream

        orch = ReviewOrchestrator()
        result = await orch.review_code(bridge, "x = 1\n", "task-1")
        assert result.passed is False
        assert result.score == 0
        assert len(result.issues) == 1
        assert "审查解析失败" in result.issues[0]["description"]

    @pytest.mark.asyncio
    async def test_review_loop_terminates_on_pass(self, monkeypatch):
        from pycoder.server.services.team.review_orchestrator import (
            ReviewOrchestrator, ReviewResult,
        )
        orch = ReviewOrchestrator()

        async def fake_review(self, bridge, code, task_id=""):
            return ReviewResult(task_id=task_id, passed=True, score=95,
                                issues=[], summary="ok")
        monkeypatch.setattr(ReviewOrchestrator, "review_code", fake_review)

        fix_executor = AsyncMock()
        results = {"task-1": "code-1"}

        all_issues, rounds = await orch.run_review_loop(
            MagicMock(), results, fix_executor, max_rounds=3,
        )

        assert rounds == 1  # 通过后立即终止
        assert all_issues == []
        # 不应调用修复执行器
        fix_executor.assert_not_called()

    @pytest.mark.asyncio
    async def test_review_loop_runs_fix_then_re_review(self, monkeypatch):
        from pycoder.server.services.team.review_orchestrator import (
            ReviewOrchestrator, ReviewResult,
        )
        orch = ReviewOrchestrator()

        # 第 1 轮失败，第 2 轮通过
        call_count = {"n": 0}

        async def fake_review(self, bridge, code, task_id=""):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return ReviewResult(
                    task_id=task_id, passed=False, score=40,
                    issues=[{"severity": "high",
                             "description": "bug",
                             "suggestion": "fix it"}],
                    summary="bad",
                )
            return ReviewResult(task_id=task_id, passed=True, score=90,
                                issues=[], summary="ok")
        monkeypatch.setattr(ReviewOrchestrator, "review_code", fake_review)

        async def fix_executor(task_id, feedback):
            return "fixed-code"

        results = {"task-1": "original-code"}
        all_issues, rounds = await orch.run_review_loop(
            MagicMock(), results, fix_executor, max_rounds=3,
        )

        assert rounds == 2  # 修复后再次审查通过
        # 第 1 轮有 1 个 issue
        assert len(all_issues) == 1
        # 修复后的代码已写入 results
        assert results["task-1"] == "fixed-code"


# ══════════════════════════════════════════════════════════
# TeamCoordinator 门面测试
# ══════════════════════════════════════════════════════════


class TestTeamCoordinatorFacade:
    def test_exposes_session_job_review_orchestrators(self):
        from pycoder.server.services.team import TeamCoordinator
        from pycoder.server.services.team.session_orchestrator import (
            SessionOrchestrator,
        )
        from pycoder.server.services.team.job_orchestrator import JobOrchestrator
        from pycoder.server.services.team.review_orchestrator import (
            ReviewOrchestrator,
        )
        coord = TeamCoordinator()
        assert isinstance(coord.sessions, SessionOrchestrator)
        assert isinstance(coord.jobs, JobOrchestrator)
        assert isinstance(coord.reviews, ReviewOrchestrator)

    def test_list_runs_delegates_to_sessions(self):
        from pycoder.server.services.team import TeamCoordinator
        coord = TeamCoordinator()
        coord.sessions.create("test-1")
        coord.sessions.create("test-2")
        runs = coord.list_runs(limit=10)
        assert len(runs) == 2

    def test_get_run_delegates_to_sessions(self):
        from pycoder.server.services.team import TeamCoordinator
        coord = TeamCoordinator()
        run = coord.sessions.create("test")
        assert coord.get_run(run.id) is run
        assert coord.get_run("nonexistent") is None

    def test_get_coordinator_returns_singleton(self):
        from pycoder.server.services.team import get_coordinator
        c1 = get_coordinator()
        c2 = get_coordinator()
        assert c1 is c2


# ══════════════════════════════════════════════════════════
# 旧 TeamOrchestrator 已删除测试（H2）
# ══════════════════════════════════════════════════════════


class TestTeamOrchestratorRemoved:
    """H2: 验证旧 TeamOrchestrator 类已被彻底删除"""

    def test_class_no_longer_importable(self):
        """TeamOrchestrator 类不应再可导入"""
        import pycoder.server.services.team_orchestrator as mod
        assert not hasattr(mod, "TeamOrchestrator"), (
            "TeamOrchestrator 类应已删除（H2），但仍可从 team_orchestrator 模块导入"
        )

    def test_get_orchestrator_removed(self):
        """get_orchestrator 单例函数应已删除"""
        import pycoder.server.services.team_orchestrator as mod
        assert not hasattr(mod, "get_orchestrator"), (
            "get_orchestrator 单例应已删除（H2）"
        )

    def test_team_api_uses_new_coordinator(self):
        """team_api.py 应改用新 TeamCoordinator，不再依赖旧 get_orchestrator"""
        import inspect
        from pycoder.server.routers import team_api
        source = inspect.getsource(team_api)
        assert "from pycoder.server.services.team import get_coordinator" in source
        assert "get_orchestrator" not in source, (
            "team_api.py 仍引用旧 get_orchestrator"
        )

    def test_agent_tool_loop_migrated(self):
        """H2: Agent 执行原语已迁移到 team.agent_tool_loop 子模块"""
        from pycoder.server.services.team.agent_tool_loop import (
            _agent_tool_loop,
            _execute_agent_with_files,
            AGENT_SYSTEM_PROMPT,
        )
        assert callable(_agent_tool_loop)
        assert callable(_execute_agent_with_files)
        assert isinstance(AGENT_SYSTEM_PROMPT, str)

    def test_backward_compat_reexports(self):
        """H2: 旧模块仍 re-export 迁移后的函数（向后兼容）"""
        # 旧脚本可能从 team_orchestrator 导入这些函数
        from pycoder.server.services.team_orchestrator import (
            _agent_tool_loop,
            _execute_agent_with_files,
            AGENT_SYSTEM_PROMPT,
            _team_execute_tool,
        )
        assert callable(_agent_tool_loop)
        assert callable(_execute_agent_with_files)
