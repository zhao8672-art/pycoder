"""
V2 进化引擎核心 API 端点 — 基于 evolution/core.py 的新一代进化接口

提供:
  - POST /api/v2/evolution/core/run       — 运行完整进化闭环
  - POST /api/v2/evolution/core/run/async — 异步启动进化任务
  - GET  /api/v2/evolution/core/status    — 进化状态与统计
  - GET  /api/v2/evolution/core/report    — 进化报告
  - GET  /api/v2/evolution/core/history   — 进化历史
  - GET  /api/v2/evolution/core/metrics   — 进化指标
  - POST /api/v2/evolution/core/config    — 更新进化配置
  - GET  /api/v2/evolution/core/config    — 获取进化配置
  - GET  /api/v2/evolution/core/health    — 进化引擎健康检查
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v2/evolution/core", tags=["v2-evolution-core"])


# ══════════════════════════════════════════════════════════
# 进化闭环
# ══════════════════════════════════════════════════════════


@router.post("/run")
async def run_evolution(
    task_type: str = "auto_fix",
    target: str = "",
    description: str = "",
    auto_apply: bool = False,
):
    """运行一次完整进化闭环"""
    from pycoder.evolution import get_evolution_pipeline

    pipeline = get_evolution_pipeline()
    report = await pipeline.run(
        task_type=task_type,
        target=target,
        description=description,
        auto_apply=auto_apply,
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


@router.post("/run/async")
async def run_evolution_async(
    task_type: str = "auto_fix",
    target: str = "",
    description: str = "",
    auto_apply: bool = False,
):
    """异步启动进化任务（立即返回任务ID）"""
    import asyncio
    from pycoder.evolution import get_evolution_pipeline

    pipeline = get_evolution_pipeline()
    task = asyncio.create_task(
        pipeline.run(
            task_type=task_type,
            target=target,
            description=description,
            auto_apply=auto_apply,
        )
    )
    return {
        "success": True,
        "message": "进化任务已启动",
        "task_id": id(task),
    }


# ══════════════════════════════════════════════════════════
# 状态与统计
# ══════════════════════════════════════════════════════════


@router.get("/status")
async def get_evolution_status():
    """获取进化引擎状态"""
    from pycoder.evolution import get_evolution_pipeline, get_evolution_metrics

    pipeline = get_evolution_pipeline()
    metrics = get_evolution_metrics()

    stats = pipeline.get_stats()
    summary = metrics.get_summary()

    return {
        "success": True,
        "pipeline_stats": stats,
        "metrics_summary": summary,
        "trend": metrics.get_trend_data(days=7),
    }


@router.get("/report")
async def get_evolution_report():
    """获取进化报告"""
    from pycoder.evolution import get_evolution_pipeline, get_evolution_metrics

    pipeline = get_evolution_pipeline()
    metrics = get_evolution_metrics()

    return {
        "success": True,
        "recent_reports": pipeline.get_reports(limit=10),
        "summary": metrics.get_summary(),
        "trend": metrics.get_trend_data(days=7),
    }


@router.get("/history")
async def get_evolution_history(limit: int = 20):
    """获取进化历史"""
    from pycoder.evolution import get_evolution_brain

    brain = get_evolution_brain()
    return {
        "success": True,
        "history": brain.get_history(limit=limit),
        "total": len(brain.get_history(limit=1000)),
    }


@router.get("/metrics")
async def get_evolution_metrics(days: int = 7):
    """获取进化指标"""
    from pycoder.evolution import get_evolution_metrics

    metrics = get_evolution_metrics()
    return {
        "success": True,
        "summary": metrics.get_summary(),
        "trend": metrics.get_trend_data(days=days),
    }


# ══════════════════════════════════════════════════════════
# 配置管理
# ══════════════════════════════════════════════════════════


@router.get("/config")
async def get_evolution_config():
    """获取进化配置"""
    from pycoder.evolution import get_evolution_brain

    brain = get_evolution_brain()
    cfg = brain._config
    return {
        "success": True,
        "config": {
            "auto_apply": cfg.auto_apply,
            "max_files_per_run": cfg.max_files_per_run,
            "max_llm_tokens": cfg.max_llm_tokens,
            "llm_model": cfg.llm_model,
            "safety_strict": cfg.safety_strict,
            "test_timeout_seconds": cfg.test_timeout_seconds,
            "evolution_interval_seconds": cfg.evolution_interval_seconds,
            "cost_budget_daily_usd": cfg.cost_budget_daily_usd,
            "min_grade_threshold": cfg.min_grade_threshold,
            "max_retries": cfg.max_retries,
        },
    }


@router.post("/config")
async def update_evolution_config(config: dict):
    """更新进化配置"""
    from pycoder.evolution import get_evolution_brain

    brain = get_evolution_brain()
    allowed_keys = [
        "auto_apply", "max_files_per_run", "max_llm_tokens",
        "llm_model", "safety_strict", "test_timeout_seconds",
        "evolution_interval_seconds", "cost_budget_daily_usd",
        "min_grade_threshold", "max_retries",
    ]

    updated = {}
    for key, value in config.items():
        if key in allowed_keys:
            setattr(brain._config, key, value)
            updated[key] = value

    return {
        "success": True,
        "updated": updated,
        "message": f"已更新 {len(updated)} 个配置项",
    }


# ══════════════════════════════════════════════════════════
# 健康检查
# ══════════════════════════════════════════════════════════


@router.get("/health")
async def evolution_health():
    """进化引擎健康检查"""
    checks = {}

    # 检查 EvolutionBrain
    try:
        from pycoder.evolution import get_evolution_brain
        brain = get_evolution_brain()
        checks["brain"] = "healthy"
    except Exception as e:
        checks["brain"] = f"error: {e}"

    # 检查 EvolutionPipeline
    try:
        from pycoder.evolution import get_evolution_pipeline
        pipeline = get_evolution_pipeline()
        checks["pipeline"] = "healthy"
    except Exception as e:
        checks["pipeline"] = f"error: {e}"

    # 检查 EvolutionMetrics
    try:
        from pycoder.evolution import get_evolution_metrics
        metrics = get_evolution_metrics()
        checks["metrics"] = "healthy"
    except Exception as e:
        checks["metrics"] = f"error: {e}"

    # 检查依赖模块
    deps = {}
    for mod_name, mod_path in [
        ("memory", "pycoder.memory"),
        ("plugins", "pycoder.plugins"),
        ("observability", "pycoder.observability"),
        ("safety", "pycoder.safety"),
        ("learning", "pycoder.capabilities.self_evo.learning"),
    ]:
        try:
            __import__(mod_path)
            deps[mod_name] = "available"
        except ImportError:
            deps[mod_name] = "unavailable"

    all_healthy = all(v == "healthy" for v in checks.values())

    return {
        "success": True,
        "healthy": all_healthy,
        "components": checks,
        "dependencies": deps,
    }