"""
PyCoder 进化引擎 — 自动化自我改进系统

整合 LLM 作为"进化大脑"，构建完整的进化闭环:
  ┌──────────────────────────────────────────────────────────────┐
  │                    EvolutionBrain (LLM 驱动)                  │
  ├──────────────────────────────────────────────────────────────┤
  │  observe()     → 从 memory/observability 采集错误和反馈       │
  │  analyze()     → LLM 深度分析问题根因和模式                   │
  │  generate()    → 生成修复方案 + 优化策略                      │
  │  validate()    → safety 沙箱验证 + 测试门禁                   │
  │  apply()       → Git 隔离 + 自动回滚 + 安全应用               │
  │  learn()       → 经验沉淀到 knowledge_base + experience_buffer │
  └──────────────────────────────────────────────────────────────┘

核心类:
  - EvolutionBrain: LLM 驱动的进化决策核心
  - EvolutionPipeline: 完整的进化闭环自动化执行器
  - EvolutionMetrics: 进化效果评估与趋势分析

用法:
  from pycoder.evolution import EvolutionBrain, EvolutionPipeline

  brain = EvolutionBrain()
  pipeline = EvolutionPipeline(brain)
  report = await pipeline.run(auto_apply=False)
"""

from __future__ import annotations

from .core import (
    EvolutionBrain,
    EvolutionPipeline,
    EvolutionPhase,
    EvolutionReport,
    EvolutionTask,
    EvolutionMetrics,
    EvolutionConfig,
    get_evolution_brain,
    get_evolution_pipeline,
    get_evolution_metrics,
)

__all__ = [
    "EvolutionBrain",
    "EvolutionPipeline",
    "EvolutionPhase",
    "EvolutionReport",
    "EvolutionTask",
    "EvolutionMetrics",
    "EvolutionConfig",
    "get_evolution_brain",
    "get_evolution_pipeline",
    "get_evolution_metrics",
    "register_capabilities",
]


def register_capabilities(registry: object) -> None:
    """向 V2 能力总线注册进化引擎核心能力"""
    import logging
    from pycoder.bus.protocol import (
        CapabilityCategory,
        CapabilityDefinition,
        ExecutionMode,
        SideEffect,
        TrustLevel,
    )

    logger = logging.getLogger(__name__)

    # ── evolution.pipeline.run ──
    registry.register(
        CapabilityDefinition(
            id="evolution.pipeline.run",
            name="运行进化管线",
            description="运行完整进化闭环：observe→analyze→generate→validate→apply→learn",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.FULL_AUTONOMY,
            execution=ExecutionMode.ASYNC,
            side_effects=[SideEffect.FILE_WRITE, SideEffect.LLM_CALL],
            schema={
                "type": "object",
                "properties": {
                    "task_type": {
                        "type": "string",
                        "enum": ["auto_fix", "policy_optimize", "knowledge_build"],
                        "description": "进化任务类型",
                    },
                    "target": {
                        "type": "string",
                        "description": "目标文件或模块路径",
                    },
                    "auto_apply": {
                        "type": "boolean",
                        "description": "是否自动应用修复",
                    },
                },
            },
            tags=["evolution", "pipeline", "自我进化", "进化", "auto-fix"],
        ),
        handler=_handle_pipeline_run,
    )

    # ── evolution.pipeline.status ──
    registry.register(
        CapabilityDefinition(
            id="evolution.pipeline.status",
            name="进化状态",
            description="获取进化引擎运行状态和统计信息",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["evolution", "status", "进化", "状态"],
        ),
        handler=_handle_pipeline_status,
    )

    # ── evolution.pipeline.report ──
    registry.register(
        CapabilityDefinition(
            id="evolution.pipeline.report",
            name="进化报告",
            description="获取最近进化任务的详细报告",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["evolution", "report", "进化", "报告"],
        ),
        handler=_handle_pipeline_report,
    )

    # ── evolution.pipeline.metrics ──
    registry.register(
        CapabilityDefinition(
            id="evolution.pipeline.metrics",
            name="进化指标",
            description="获取进化效果评估指标：成功率、覆盖率、回归率、趋势",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            tags=["evolution", "metrics", "进化", "指标"],
        ),
        handler=_handle_pipeline_metrics,
    )

    logger.info("进化引擎核心能力已注册（4 个能力）")


# ── 处理器实现 ──

async def _handle_pipeline_run(params: dict, context: dict) -> dict:
    """处理 evolution.pipeline.run"""
    from .core import get_evolution_pipeline

    pipeline = get_evolution_pipeline()
    report = await pipeline.run(
        task_type=params.get("task_type", "auto_fix"),
        target=params.get("target", ""),
        description=params.get("description", ""),
        auto_apply=params.get("auto_apply", False),
    )
    return {
        "success": report.success,
        "task_id": report.task_id,
        "phases": report.phases_completed,
        "issues_found": report.issues_found,
        "fixes_generated": report.fixes_generated,
        "fixes_applied": report.fixes_applied,
        "tests_passed": report.tests_passed,
        "grade": report.grade,
        "duration_ms": report.duration_ms,
        "recommendations": report.recommendations,
        "error": report.error,
    }


async def _handle_pipeline_status(params: dict, context: dict) -> dict:
    """处理 evolution.pipeline.status"""
    from .core import get_evolution_pipeline, get_evolution_metrics

    pipeline = get_evolution_pipeline()
    metrics = get_evolution_metrics()
    return {
        "pipeline_stats": pipeline.get_stats(),
        "metrics_summary": metrics.get_summary(),
        "trend": metrics.get_trend_data(days=7),
    }


async def _handle_pipeline_report(params: dict, context: dict) -> dict:
    """处理 evolution.pipeline.report"""
    from .core import get_evolution_pipeline, get_evolution_metrics

    pipeline = get_evolution_pipeline()
    metrics = get_evolution_metrics()
    return {
        "recent_reports": pipeline.get_reports(limit=10),
        "summary": metrics.get_summary(),
        "trend": metrics.get_trend_data(days=7),
    }


async def _handle_pipeline_metrics(params: dict, context: dict) -> dict:
    """处理 evolution.pipeline.metrics"""
    from .core import get_evolution_metrics

    metrics = get_evolution_metrics()
    return {
        "summary": metrics.get_summary(),
        "trend": metrics.get_trend_data(days=params.get("days", 7)),
    }