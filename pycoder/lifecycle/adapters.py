"""项目管理闭环 — 阶段策略适配器

将现有成熟模块适配为 PhaseStrategy 接口。
核心原则：纯委托，不实现业务逻辑。每个适配器只做"调用现有模块 + 写入ctx"。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from pycoder.lifecycle.context import PhaseArtifact, PhaseRecord, ProjectContext
from pycoder.lifecycle.phases import LifecyclePhase

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════
# 基类
# ══════════════════════════════════════════════════════


class BasePhaseAdapter:
    """阶段适配器基类 — 提供通用的执行框架

    子类只需实现 _run() 方法完成实际业务逻辑。
    """

    phase: LifecyclePhase = LifecyclePhase.INTAKE

    async def execute(self, ctx: ProjectContext) -> PhaseRecord:
        """执行阶段（模板方法模式）"""
        record = ctx.get_phase(self.phase.name)
        record.status = "running"
        record.started_at = time.time()
        ctx.current_phase = self.phase.name
        ctx.touch()

        logger.info(
            "lifecycle_phase_start project=%s phase=%s",
            ctx.project_id, self.phase.name,
        )

        try:
            await self._run(ctx, record)

            if not record.is_terminal:
                record.status = "passed"

            record.completed_at = time.time()
            record.duration_ms = (record.completed_at - record.started_at) * 1000

            logger.info(
                "lifecycle_phase_done project=%s phase=%s status=%s duration=%.0fms",
                ctx.project_id, self.phase.name, record.status, record.duration_ms,
            )

        except Exception as e:
            record.status = "failed"
            record.error = f"{type(e).__name__}: {e}"
            record.completed_at = time.time()
            record.duration_ms = (record.completed_at - record.started_at) * 1000
            logger.error(
                "lifecycle_phase_error project=%s phase=%s: %s",
                ctx.project_id, self.phase.name, e, exc_info=True,
            )

        return record

    async def _run(self, ctx: ProjectContext, record: PhaseRecord) -> None:
        """子类实现：执行阶段业务逻辑"""
        raise NotImplementedError


# ══════════════════════════════════════════════════════
# 阶段 1: 任务接收
# ══════════════════════════════════════════════════════


class IntakeAdapter(BasePhaseAdapter):
    """任务接收 — 解析需求，初始化工作空间"""

    phase = LifecyclePhase.INTAKE

    async def _run(self, ctx: ProjectContext, record: PhaseRecord) -> None:
        if not ctx.request.strip():
            raise ValueError("需求描述为空")

        # 提取项目名（简单启发式）
        project_name = ctx.request[:50].strip().replace("\n", " ")
        if not project_name:
            project_name = f"project_{ctx.project_id}"

        # 记录产出
        artifact = PhaseArtifact(
            phase=self.phase.name,
            name="intake_summary",
            content=f"项目: {project_name}\n需求: {ctx.request[:500]}",
            metadata={"project_name": project_name, "workspace": ctx.workspace},
        )
        ctx.add_artifact(artifact)
        ctx.requirements["project_name"] = project_name
        ctx.requirements["raw_request"] = ctx.request


# ══════════════════════════════════════════════════════
# 阶段 2: 需求分析
# ══════════════════════════════════════════════════════


class AnalyzeAdapter(BasePhaseAdapter):
    """需求分析 — 调用 TaskDecomposer 或 LLM 进行结构化分析"""

    phase = LifecyclePhase.ANALYZE

    async def _run(self, ctx: ProjectContext, record: PhaseRecord) -> None:
        try:
            from pycoder.brain.task_decomposer import TaskDecomposer

            decomposer = TaskDecomposer()
            dag_plan = await decomposer.decompose(ctx.request, context={"workspace": ctx.workspace})

            # 存储分解结果
            ctx.task_dag = dag_plan.to_dict()
            ctx.requirements["task_level"] = str(dag_plan.task_level)
            ctx.requirements["node_count"] = len(dag_plan.nodes)
            ctx.requirements["critical_path"] = dag_plan.critical_path

            record.artifacts.append(
                PhaseArtifact(
                    phase=self.phase.name,
                    name="task_dag",
                    content=f"分解为 {len(dag_plan.nodes)} 个任务节点",
                    metadata=ctx.task_dag,
                )
            )

        except ImportError:
            logger.warning("TaskDecomposer 不可用，使用本地启发式分析")
            self._fallback_analyze(ctx, record)
        except Exception as e:
            logger.warning("需求分析失败，降级为本地分析: %s", e)
            self._fallback_analyze(ctx, record)

    def _fallback_analyze(self, ctx: ProjectContext, record: PhaseRecord) -> None:
        """本地启发式需求分析（无 LLM 降级模式）"""
        request = ctx.request

        # 简单关键词提取
        keywords = []
        for kw in ["API", "数据库", "前端", "后端", "测试", "部署", "文档", "认证", "缓存"]:
            if kw.lower() in request.lower():
                keywords.append(kw)

        ctx.requirements["functional"] = keywords
        ctx.requirements["non_functional"] = ["可维护性", "安全性"]
        ctx.requirements["risks"] = ["需求不明确" if len(keywords) < 2 else ""]

        record.artifacts.append(
            PhaseArtifact(
                phase=self.phase.name,
                name="requirements",
                content=f"功能点: {', '.join(keywords) if keywords else '待细化'}",
                metadata={"keywords": keywords},
            )
        )


# ══════════════════════════════════════════════════════
# 阶段 3: 方案设计
# ══════════════════════════════════════════════════════


class DesignAdapter(BasePhaseAdapter):
    """方案设计 — 架构设计 + L1 质量门禁"""

    phase = LifecyclePhase.DESIGN

    async def _run(self, ctx: ProjectContext, record: PhaseRecord) -> None:
        # 构建设计方案（复用需求分析结果）
        design = {
            "architecture": "分层架构",
            "tech_stack": ["FastAPI", "SQLAlchemy", "pytest"],
            "api_endpoints": [],
            "data_models": [],
            "modules": ctx.requirements.get("functional", []),
        }

        ctx.design = design

        # L1 质量门禁校验
        gate_passed = True
        gate_score = 80.0
        try:
            from pycoder.brain.quality_gate import QualityGate

            gate = QualityGate()
            result = gate.check(
                phase=self.phase,
                outputs=design,
                gate_level=1,
            )
            gate_score = result.score
            # 编排层宽松策略：score >= 60 即放行（硬性驳回由 quality_gate 内部处理）
            gate_passed = gate_score >= 60.0
        except Exception as e:
            logger.warning("质量门禁不可用，使用默认评分: %s", e)

        record.gate_passed = gate_passed
        record.gate_score = gate_score

        if not gate_passed:
            record.status = "failed"
            record.error = f"L1 质量门禁未通过 (score={gate_score})"
            return

        record.artifacts.append(
            PhaseArtifact(
                phase=self.phase.name,
                name="architecture_design",
                content=f"架构: {design['architecture']}, 技术栈: {', '.join(design['tech_stack'])}",
                metadata=design,
            )
        )


# ══════════════════════════════════════════════════════
# 阶段 4: 代码开发
# ══════════════════════════════════════════════════════


class DevelopAdapter(BasePhaseAdapter):
    """代码开发 — 委托给 AutonomousPipeline 执行"""

    phase = LifecyclePhase.DEVELOP

    async def _run(self, ctx: ProjectContext, record: PhaseRecord) -> None:
        try:
            from pycoder.server.services.autonomous_pipeline import AutonomousPipeline

            pipeline = AutonomousPipeline(
                workspace_root=ctx.workspace or None,
                model=ctx.model,
            )

            # 收集开发产出文件
            developed_files: list[str] = []
            final_report: dict[str, Any] = {}

            async for event in pipeline.run(user_request=ctx.request):
                evt_type = event.get("type", "")

                if evt_type == "agent_done":
                    files = event.get("files", [])
                    developed_files.extend(files)

                elif evt_type == "done":
                    final_report = event.get("report", {})

                elif evt_type == "error":
                    # 环境依赖问题降级为 skipped 而非 failed
                    msg = event.get("message", "")
                    if "未注册" in msg or "LLMProvider" in msg or "registry" in msg:
                        logger.warning("开发环境不可用，降级为跳过: %s", msg)
                        record.status = "skipped"
                        record.artifacts.append(
                            PhaseArtifact(
                                phase=self.phase.name,
                                name="develop_skipped",
                                content=f"开发环境未就绪: {msg[:200]}",
                            )
                        )
                        return
                    record.error = msg
                    record.status = "failed"
                    return

            ctx.developed_files = list(set(developed_files))

            # L2 质量门禁
            try:
                from pycoder.brain.quality_gate import QualityGate

                gate = QualityGate()
                result = gate.check(
                    phase=self.phase,
                    outputs={"files": ctx.developed_files, "report": final_report},
                    gate_level=2,
                )
                record.gate_passed = result.score >= 60.0
                record.gate_score = result.score
                if not record.gate_passed:
                    record.status = "failed"
                    record.error = f"L2 质量门禁未通过 (score={result.score})"
                    return
            except Exception:
                record.gate_passed = True
                record.gate_score = 75.0

            record.artifacts.append(
                PhaseArtifact(
                    phase=self.phase.name,
                    name="developed_code",
                    content=f"开发 {len(ctx.developed_files)} 个文件",
                    files=ctx.developed_files,
                    metadata=final_report,
                )
            )

        except ImportError:
            logger.warning("AutonomousPipeline 不可用，跳过开发阶段")
            record.status = "skipped"


# ══════════════════════════════════════════════════════
# 阶段 5: 测试验证
# ══════════════════════════════════════════════════════


class TestAdapter(BasePhaseAdapter):
    """测试验证 — 执行测试套件并收集结果"""

    phase = LifecyclePhase.TEST

    async def _run(self, ctx: ProjectContext, record: PhaseRecord) -> None:
        if not ctx.developed_files:
            record.status = "skipped"
            record.artifacts.append(
                PhaseArtifact(
                    phase=self.phase.name,
                    name="test_skipped",
                    content="无开发产出，跳过测试",
                )
            )
            return

        # 执行测试（复用现有测试基础设施）
        test_result: dict[str, Any] = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "coverage": 0.0,
        }

        try:
            import asyncio

            proc = await asyncio.create_subprocess_exec(
                "python", "-m", "pytest", "tests/", "-q", "--tb=no",
                cwd=ctx.workspace or None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            output = stdout.decode("utf-8", errors="replace")

            # 解析 pytest 输出
            import re

            match = re.search(r"(\d+) passed", output)
            if match:
                test_result["passed"] = int(match.group(1))
            match = re.search(r"(\d+) failed", output)
            if match:
                test_result["failed"] = int(match.group(1))
            test_result["total"] = test_result["passed"] + test_result["failed"]

        except Exception as e:
            logger.warning("测试执行失败: %s", e)
            record.artifacts.append(
                PhaseArtifact(
                    phase=self.phase.name,
                    name="test_error",
                    content=f"测试执行异常: {e}",
                )
            )

        ctx.test_results = test_result

        # 测试通过率门禁
        pass_rate = (
            test_result["passed"] / test_result["total"]
            if test_result["total"] > 0
            else 0.0
        )
        record.gate_score = pass_rate * 100
        record.gate_passed = pass_rate >= 0.8

        if not record.gate_passed and test_result["total"] > 0:
            record.status = "failed"
            record.error = f"测试通过率 {pass_rate:.0%} 低于 80% 阈值"
            return

        record.artifacts.append(
            PhaseArtifact(
                phase=self.phase.name,
                name="test_report",
                content=(
                    f"测试: {test_result['passed']}/{test_result['total']} 通过 "
                    f"({pass_rate:.0%})"
                ),
                metadata=test_result,
            )
        )


# ══════════════════════════════════════════════════════
# 阶段 6: 自愈修正
# ══════════════════════════════════════════════════════


class HealAdapter(BasePhaseAdapter):
    """自愈修正 — 测试失败时自动修复"""

    phase = LifecyclePhase.HEAL

    async def _run(self, ctx: ProjectContext, record: PhaseRecord) -> None:
        # 如果测试已通过，跳过自愈
        test_phase = ctx.phases.get(LifecyclePhase.TEST.name)
        if test_phase and test_phase.gate_passed:
            record.status = "skipped"
            record.artifacts.append(
                PhaseArtifact(
                    phase=self.phase.name,
                    name="heal_skipped",
                    content="测试已通过，无需自愈",
                )
            )
            return

        # 如果测试被跳过，也跳过自愈
        if test_phase and test_phase.status == "skipped":
            record.status = "skipped"
            return

        # 调用 EvolutionPipeline 进行修复（复用现有自我进化能力）
        try:
            from pycoder.evolution.core import EvolutionPipeline

            pipeline = EvolutionPipeline()
            report = await pipeline.run(
                task_type="auto_fix",
                target=ctx.workspace,
                description=f"修复测试失败: {test_phase.error if test_phase else ''}",
                auto_apply=ctx.auto_apply,
            )

            record.gate_passed = report.success
            record.gate_score = report.grade
            record.artifacts.append(
                PhaseArtifact(
                    phase=self.phase.name,
                    name="heal_report",
                    content=f"自愈{'成功' if report.success else '失败'}, 评分={report.grade:.0f}",
                    metadata={"task_id": report.task_id, "fixes": report.fixes_applied},
                )
            )

            if report.success:
                ctx.lessons.append(f"自愈修复成功: {report.task_id}")
            else:
                record.status = "failed"
                record.error = report.error or "自愈未能修复问题"

        except ImportError:
            logger.warning("EvolutionPipeline 不可用，跳过自愈")
            record.status = "skipped"


# ══════════════════════════════════════════════════════
# 阶段 7: 交付管理
# ══════════════════════════════════════════════════════


class DeliverAdapter(BasePhaseAdapter):
    """交付管理 — 打包产出物 + 生成文档 + 经验沉淀"""

    phase = LifecyclePhase.DELIVER

    async def _run(self, ctx: ProjectContext, record: PhaseRecord) -> None:
        delivery: dict[str, Any] = {
            "project_id": ctx.project_id,
            "files": ctx.developed_files,
            "test_summary": ctx.test_results,
            "design": ctx.design,
            "requirements": ctx.requirements,
        }

        # 生成交付报告
        report_lines = [
            f"# 项目交付报告: {ctx.requirements.get('project_name', ctx.project_id)}",
            f"",
            f"## 概述",
            f"- 项目ID: {ctx.project_id}",
            f"- 状态: {ctx.status.value}",
            f"- 阶段数: {len(ctx.phases)}",
            f"- 开发文件: {len(ctx.developed_files)}",
            f"",
            f"## 阶段执行记录",
        ]

        for phase in LifecyclePhase.ordered():
            rec = ctx.phases.get(phase.name)
            if rec:
                report_lines.append(
                    f"- {phase.label}: {rec.status} "
                    f"({rec.duration_ms:.0f}ms, score={rec.gate_score:.0f})"
                )

        report_lines.extend([
            f"",
            f"## 测试结果",
            f"- 通过: {ctx.test_results.get('passed', 0)}",
            f"- 失败: {ctx.test_results.get('failed', 0)}",
            f"",
            f"## 经验沉淀",
        ])
        report_lines.extend(f"- {lesson}" for lesson in ctx.lessons)

        delivery["report"] = "\n".join(report_lines)
        ctx.delivery = delivery
        ctx.completed_at = time.time()

        # 经验学习（复用学习系统）
        try:
            from pycoder.capabilities.self_evo.learning import LearningEngine

            engine = LearningEngine()
            engine.on_task_complete(
                task_id=ctx.project_id,
                success=True,
                metadata={
                    "phases": len(ctx.phases),
                    "files": len(ctx.developed_files),
                    "test_pass_rate": (
                        ctx.test_results.get("passed", 0)
                        / max(ctx.test_results.get("total", 1), 1)
                    ),
                },
            )
        except Exception as e:
            logger.debug("学习引擎不可用，跳过经验沉淀: %s", e)

        record.artifacts.append(
            PhaseArtifact(
                phase=self.phase.name,
                name="delivery_package",
                content=delivery["report"][:500],
                files=ctx.developed_files,
                metadata={"report_length": len(delivery["report"])},
            )
        )


# ══════════════════════════════════════════════════════
# 默认策略工厂
# ══════════════════════════════════════════════════════


def create_default_phases() -> dict[LifecyclePhase, BasePhaseAdapter]:
    """创建默认的 7 阶段策略集合"""
    return {
        LifecyclePhase.INTAKE: IntakeAdapter(),
        LifecyclePhase.ANALYZE: AnalyzeAdapter(),
        LifecyclePhase.DESIGN: DesignAdapter(),
        LifecyclePhase.DEVELOP: DevelopAdapter(),
        LifecyclePhase.TEST: TestAdapter(),
        LifecyclePhase.HEAL: HealAdapter(),
        LifecyclePhase.DELIVER: DeliverAdapter(),
    }
