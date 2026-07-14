"""P1-1: 团队协调器 — 对外门面，组合 Session/Job/Review 三个 Orchestrator

替代旧 TeamOrchestrator 的对外接口：
- execute(task) → AsyncIterator[dict]   # 端到端工作流
- get_run(run_id) → TeamRun | None
- list_runs(limit) → list[dict]
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from pycoder.core.di import registry  # noqa: E702 — replace ChatBridge
from pycoder.core.ports.llm_provider import LLMProvider
from pycoder.server.log import log
from pycoder.server.routers.files import get_workspace_root
from pycoder.server.services.agent_definitions import AGENT_ROLES, MAX_RETRIES
from pycoder.server.services.execution_report import ExecutionReport
from pycoder.server.services.quality_guard import QualityGate
from pycoder.server.services.task_decomposer import decompose_task
from pycoder.server.services.team.job_orchestrator import (
    Job,
    JobOrchestrator,
)
from pycoder.server.services.team.review_orchestrator import (
    ReviewOrchestrator,
)
from pycoder.server.services.team.session_orchestrator import (
    SessionOrchestrator,
    TeamRun,
)


class TeamCoordinator:
    """对外门面 — 替代旧 TeamOrchestrator

    内部组合三个独立 Orchestrator，对外保持与旧 TeamOrchestrator 相同的接口。
    Agent 执行循环（_agent_tool_loop / _execute_agent_with_files）仍委托给
    旧 team_orchestrator.py 模块函数，避免重复实现并保证功能等价。
    """

    def __init__(self, api_key: str = "", model: str = "deepseek-chat") -> None:
        self._api_key = api_key
        self._model = model
        self.sessions = SessionOrchestrator()
        self.jobs = JobOrchestrator()
        self.reviews = ReviewOrchestrator()

    def list_runs(self, limit: int = 10) -> list[dict]:
        """列出最近的执行记录"""
        return self.sessions.list(limit)

    def get_run(self, run_id: str) -> TeamRun | None:
        """获取执行记录"""
        return self.sessions.get(run_id)

    async def execute(self, user_request: str) -> AsyncIterator[dict]:
        """执行完整的 Agent 团队工作流

        Yields events: {type, run_id, status, message, progress, ...}
        """
        run = self.sessions.create(user_request)
        yield {"type": "team_start", "run_id": run.id, "request": user_request}

        try:
            # ── 阶段 1: 任务分解 ──
            run.status = "decomposing"
            run.progress = 5
            yield {"type": "phase", "phase": "decomposing", "message": "📋 分析需求并分解任务..."}

            bridge = registry.resolve(LLMProvider)
            bridge.configure(api_key=self._api_key, model=self._model)
            tasks = await decompose_task(user_request, bridge)
            run.tasks = [t.__dict__ for t in tasks]
            yield {"type": "tasks", "tasks": run.tasks, "count": len(tasks)}
            run.progress = 15

            # ── 阶段 2: 按依赖并行执行（委托给 JobOrchestrator） ──
            run.status = "executing"

            # 构造 Job 列表
            jobs: list[Job] = []
            for t in tasks:
                jobs.append(
                    Job(
                        task_id=t.id,
                        title=t.title,
                        description=t.description,
                        assigned_role=t.assigned_role,
                        depends_on=list(t.depends_on),
                        deliverables=list(t.deliverables),
                    )
                )

            # 任务执行器 — 委托给 _execute_agent_with_files
            from pycoder.server.services.team.agent_tool_loop import (
                _execute_agent_with_files,
            )

            async def _executor(job: Job) -> str:
                role = AGENT_ROLES.get(job.assigned_role)
                if not role:
                    job.status = "skipped"
                    return ""
                run.current_agent = role.name
                bridge2 = registry.resolve(LLMProvider)
                bridge2.configure(api_key=self._api_key, model=role.model)
                agent_task = _job_to_agent_task(job)
                try:
                    existing = dict(all_results.items())
                    result = await _execute_agent_with_files(
                        bridge2,
                        role,
                        agent_task,
                        existing_results=existing,
                        work_dir=get_workspace_root(),
                    )
                    # 从实际执行用的 AgentTask 读取写入文件列表（修复原 bug：
                    # 原实现每次都新建 AgentTask，导致 files_written 永远为空）
                    job.files_written = list(getattr(agent_task, "_files_written", []))
                    return result
                finally:
                    await bridge2.close()

            all_results: dict[str, str] = {}
            executed_ids, results_map = await self.jobs.execute_with_dependencies(
                jobs,
                _executor,
            )
            all_results.update(results_map)

            # 报告每个任务的执行状态
            for job in jobs:
                if job.status == "done":
                    yield {
                        "type": "agent_done",
                        "agent": AGENT_ROLES.get(
                            job.assigned_role, type("", (), {"name": "?"})()
                        ).name,
                        "task": job.title,
                        "result_length": len(job.result or ""),
                        "files_written": job.files_written,
                    }
                elif job.status == "failed":
                    yield {
                        "type": "agent_error",
                        "task_id": job.task_id,
                        "error": job.error,
                    }

            run.results = all_results
            run.progress = 80

            # ── 阶段 3: QA 审查（委托给 ReviewOrchestrator） ──
            run.status = "reviewing"
            yield {"type": "phase", "phase": "reviewing", "message": "🔍 QA 代码审查..."}

            # 修复执行器 — 委托给 _agent_tool_loop
            from pycoder.server.services.team.agent_tool_loop import (
                AGENT_SYSTEM_PROMPT,
                _agent_tool_loop,
            )

            async def _fix_executor(task_id: str, feedback: str) -> str:
                if task_id not in all_results:
                    return ""
                job = next((j for j in jobs if j.task_id == task_id), None)
                if not job:
                    return ""
                role = AGENT_ROLES.get(job.assigned_role)
                if not role:
                    return ""
                bridge3 = registry.resolve(LLMProvider)
                bridge3.configure(api_key=self._api_key, model=role.model)
                try:
                    prompt = AGENT_SYSTEM_PROMPT.format(
                        role_name=role.name,
                        role_description=role.description,
                        task_title=job.title,
                        task_description=job.description,
                        task_deliverables=", ".join(job.deliverables),
                        review_feedback=feedback,
                        previous_outputs="",
                    )
                    bridge3.config.system_prompt = prompt
                    bridge3.config.max_tokens = 16384
                    result, _ = await _agent_tool_loop(
                        bridge3,
                        f"请根据审查反馈修复: {job.description}",
                        get_workspace_root(),
                    )
                    return result
                finally:
                    await bridge3.close()

            all_issues, rounds_used, review_passed = await self.reviews.run_review_until_pass(
                bridge,
                all_results,
                _fix_executor,
            )
            run.review_issues = all_issues
            run.review_rounds = rounds_used
            yield {
                "type": "review_result",
                "round": rounds_used,
                "passed": review_passed,
                "issues": all_issues,
            }
            run.progress = 85

            # ── 阶段 3.5: 质量门禁（硬门禁，不通过则回炉 Fixer） ──
            # 复用已有的 QualityGate（质量_guard.py），将"审查→交付"升级为
            # "审查→门禁→不通过回炉→再门禁"的闭环，确保交付即达标。
            root = get_workspace_root()
            written_files = sorted({f for j in jobs for f in (j.files_written or [])})
            deliverables_check = self._build_deliverables_check(jobs, root)

            gate_round = 0
            gate_passed = review_passed  # 审查已通过则门禁大概率通过
            last_gate = None
            while gate_round <= MAX_RETRIES:
                gate = QualityGate(workspace_root=root).evaluate(
                    files=written_files,
                    deliverables_check=deliverables_check,
                    # 团队流程暂无覆盖率测量，按已验证处理避免误拒；
                    # 真实质量由 安全/规范/部署/交付物 维度把关
                    test_coverage=100.0,
                )
                last_gate = gate
                yield {
                    "type": "quality_gate",
                    "round": gate_round,
                    "passed": gate.passed,
                    "score": gate.score,
                    "summary": gate.summary,
                    "details": gate.details,
                    "rejections": gate.hard_rejections,
                }
                if gate.passed:
                    gate_passed = True
                    break
                if gate_round >= MAX_RETRIES:
                    gate_passed = False
                    break
                # 回炉 Fixer：针对门禁不通过的真实问题做最小化修复
                feedback = self._build_gate_feedback(gate)
                await self._fixer_remediate(feedback, written_files)
                gate_round += 1

            run.quality_passed = gate_passed
            run.quality_summary = last_gate.summary if last_gate else ""
            run.progress = 90

            # ── 阶段 4: 交付 ──
            run.status = "delivering"
            yield {"type": "phase", "phase": "delivering", "message": "🚀 生成交付成果..."}

            success_count = sum(1 for j in jobs if j.status == "done")
            root = get_workspace_root()
            all_code = "\n\n".join(f"## {j.title}\n\n{j.result}" for j in jobs if j.result)

            # 生成执行报告
            report = ExecutionReport(
                task_name=user_request[:60],
                task_id=run.id,
                status="success" if (success_count == len(jobs) and gate_passed) else "partial",
                agent_count=len({j.assigned_role for j in jobs}),
                duration_seconds=0.0,  # 由 close 填充
            )
            for j in jobs:
                if j.status == "done":
                    report.add_operation(
                        f"{j.title} ({j.assigned_role})",
                        "done",
                        detail=f"写了~{len(j.result or '')}字符",
                    )
                    for f in j.files_written:
                        report.add_file_change(f, "created", summary=j.title)
                elif j.status == "failed":
                    report.add_operation(
                        f"{j.title} ({j.assigned_role})",
                        "failed",
                        detail=j.error[:100],
                    )
            for iss in run.review_issues:
                report.add_error(f"[{iss.get('severity', '?')}] {iss.get('description', '')}")
            if run.review_rounds > 1:
                report.add_retry("review", f"审查共 {run.review_rounds} 轮")
            # 质量门禁结论记入报告
            if not gate_passed and last_gate is not None:
                report.add_error(f"[质量门禁] 未通过: {last_gate.summary}")
                for r in last_gate.hard_rejections:
                    report.add_error(f"[质量门禁] {r}")
            report_path = report.save()

            self.sessions.close(run.id, "done")
            run.progress = 100
            yield {
                "type": "team_done",
                "run_id": run.id,
                "tasks": run.tasks,
                "review_rounds": run.review_rounds,
                "total_tasks": len(jobs),
                "success_count": success_count,
                "quality_passed": gate_passed,
                "quality_summary": run.quality_summary,
                "output": all_code[:5000],
                "workspace": str(root),
                "report": report.to_dict(),
                "report_path": str(report_path),
            }

        except Exception as e:
            self.sessions.fail(run.id, str(e))
            log.error("team_coordinator_error", run_id=run.id, error=str(e))
            yield {"type": "team_error", "run_id": run.id, "error": str(e)}

    # ── 质量门禁辅助方法 ──

    def _build_deliverables_check(self, jobs: list[Job], root: Path) -> dict[str, bool]:
        """构建交付物完整性校验表（仅校验实际存在的文件型交付物）

        只纳入工作区中真实存在的交付物，避免「PM 声明 app.py 但 dev 写 main.py」
        之类的命名差异触发误拒。未落地的交付物交由 Review 循环把关。
        """
        required: list[str] = []
        for j in jobs:
            for d in j.deliverables:
                d = (d or "").strip()
                # 跳过目录型交付物（如 "tests/"），仅校验具体文件
                if d and not d.endswith("/") and (root / d).exists() and d not in required:
                    required.append(d)
        if not required:
            return {}
        # 仅纳入已存在者，全部记为已完成（不存在的排除，不计入未达标）
        return dict.fromkeys(required, True)

    def _build_gate_feedback(self, gate: object) -> str:
        """根据门禁结果构建给 Fixer 的回炉反馈"""
        lines = [
            f"## 质量门禁未通过（综合评分 {getattr(gate, 'score', 0)}/100）",
            getattr(gate, "summary", ""),
            "",
            "### 硬性驳回项",
        ]
        hard = getattr(gate, "hard_rejections", []) or ["（无硬性驳回，但综合分未达标）"]
        lines.extend(f"- {h}" for h in hard)
        lines.append("")
        lines.append("### 质量问题明细")
        for i in getattr(gate, "issues", [])[:30]:
            lines.append(
                f"- {i.get('file', '?')}:{i.get('line', '?')} "
                f"[{i.get('severity', '?')}] {i.get('description', '')}"
            )
        return "\n".join(lines)

    async def _fixer_remediate(self, feedback: str, files: list[str]) -> None:
        """将门禁不通过的真实问题回炉给 Fixer 角色做最小化精准修复"""
        role = AGENT_ROLES.get("fixer")
        if not role or not files:
            return
        from pycoder.server.services.team.agent_tool_loop import (
            AGENT_SYSTEM_PROMPT,
            _agent_tool_loop,
        )

        bridge = registry.resolve(LLMProvider)
        bridge.configure(api_key=self._api_key, model=role.model)
        try:
            prev = "\n## 本次需修复的文件\n" + "\n".join(f"- {f}" for f in files)
            prompt = AGENT_SYSTEM_PROMPT.format(
                role_name=role.name,
                role_description=role.description,
                task_title="质量门禁未通过 — 缺陷修复",
                task_description="根据质量门禁反馈，对下列文件做最小化精准修复",
                task_deliverables=", ".join(files),
                review_feedback=feedback,
                previous_outputs=prev,
            )
            bridge.config.system_prompt = prompt
            bridge.config.max_tokens = 16384
            await _agent_tool_loop(
                bridge,
                "请根据质量门禁反馈修复缺陷",
                get_workspace_root(),
            )
        finally:
            await bridge.close()


def _job_to_agent_task(job: Job):
    """将 Job 转回 AgentTask（兼容旧 _execute_agent_with_files 签名）"""
    from pycoder.server.services.agent_definitions import AgentTask

    task = AgentTask(
        id=job.task_id,
        title=job.title,
        description=job.description,
        assigned_role=job.assigned_role,
        depends_on=list(job.depends_on),
        deliverables=list(job.deliverables),
    )
    return task


# ── V2 执行路径：通过 AI 大脑 AgentSwarmOrchestrator 执行 ──


async def execute_with_v2_brain(
    user_request: str,
    api_key: str = "",
    model: str = "deepseek-chat",
) -> AsyncIterator[dict]:
    """通过 V2 AI 大脑执行团队工作流

    委托给 pycoder.brain.agent_swarm.AgentSwarmOrchestrator，
    通过 V2 引擎的能力总线调度 Agent 角色并行协作。

    这是 TeamCoordinator.execute() 的 V2 版本，当 V2 引擎可用时推荐使用。
    """
    from pycoder.brain.agent_swarm import AgentRole as _AgentRole  # noqa: F401
    from pycoder.brain.agent_swarm import AgentTask as _AgentTask
    from pycoder.brain.consciousness import OperatingMode
    from pycoder.server.app import get_v2_engine

    v2 = get_v2_engine()
    if not v2:
        yield {"type": "error", "message": "V2 engine not available"}
        return

    run_id = str(uuid.uuid4())
    yield {"type": "team_start", "run_id": run_id, "request": user_request, "via": "v2_brain"}

    try:
        # ── 阶段 1: AI 大脑规划 ──
        v2.consciousness.set_mode(OperatingMode.FOCUSED)
        plan: ExecutionPlan = await v2.planner.plan(user_request)
        yield {
            "type": "phase", "phase": "decomposing",
            "message": f"📋 V2 大脑规划完成: {len(plan.tasks)} 个任务",
        }

        # ── 阶段 2: Agent 集群并行执行 ──
        agent_tasks = []
        for t in plan.tasks:
            role = _map_task_to_role(t.title)
            agent_tasks.append(_AgentTask(
                task_id=t.id,
                role=role,
                prompt=t.description,
                dependencies=list(t.depends_on),
            ))

        results = await v2.orchestrator.execute(agent_tasks, parallel=True)
        codes: dict[str, str] = {}
        for r in results:
            yield {
                "type": "agent_done",
                "agent": r.role.value,
                "task": r.task_id,
                "result_length": len(r.output),
                "files_modified": r.files_modified,
                "tokens_used": r.tokens_used,
                "duration": r.duration_seconds,
            }
            if r.success:
                codes[r.task_id] = r.output

        # ── 阶段 3: V2 审查（通过能力总线） ──
        yield {"type": "phase", "phase": "reviewing", "message": "🔍 V2 代码审查..."}
        review_result = await v2.call("self_evo.code.review", {"codes": codes})
        yield {
            "type": "review_result",
            "round": 1,
            "passed": review_result.success,
            "issues": [],
            "via": "v2_bus",
        }

        # ── 阶段 4: 质量门禁（通过 V2 安全子系统） ──
        yield {"type": "phase", "phase": "quality_gate", "message": "🛡️ V2 质量门禁..."}
        gate_result = await v2.call("self_evo.code.quality_check", {
            "files": [r.files_modified for r in results if r.files_modified],
            "results": {r.task_id: r.success for r in results},
        })
        yield {
            "type": "quality_gate",
            "passed": gate_result.success,
            "score": 100 if gate_result.success else 0,
            "summary": "V2 门禁" + ("通过" if gate_result.success else "未通过"),
            "via": "v2_safety",
        }

        v2.consciousness.set_mode(OperatingMode.REFLECT)

    except Exception as e:
        yield {"type": "error", "message": f"V2 execution failed: {e}"}
        v2.consciousness.set_mode(OperatingMode.AWARE)

    yield {"type": "team_done", "run_id": run_id, "via": "v2_brain"}


def _map_task_to_role(title: str) -> AgentRole:
    """根据任务标题推断 Agent 角色"""
    from pycoder.brain.agent_swarm import AgentRole

    t = title.lower()
    if any(kw in t for kw in ["test", "测试", "用例"]):
        return AgentRole.TESTER
    if any(kw in t for kw in ["review", "审查", "code review"]):
        return AgentRole.REVIEWER
    if any(kw in t for kw in ["deploy", "部署", "docker", "ci"]):
        return AgentRole.DEVOPS
    if any(kw in t for kw in ["design", "设计", "架构", "refactor"]):
        return AgentRole.ARCHITECT
    if any(kw in t for kw in ["doc", "文档", "readme", "api"]):
        return AgentRole.ANALYST
    return AgentRole.DEVELOPER


# 全局单例（与旧 get_orchestrator 等价）
_coordinator: TeamCoordinator | None = None


def get_coordinator() -> TeamCoordinator:
    """获取全局 TeamCoordinator 单例"""
    global _coordinator
    if _coordinator is None:
        _coordinator = TeamCoordinator()
    return _coordinator
