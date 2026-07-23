"""
进化报告 API 路由 — 生成、列表和获取进化变更报告

路由前缀: /api/report
支持: 闭环验证报告生成、Git diff 报告生成、报告列表与详情

示例:
  POST /api/report/generate  {"mode": "closed_loop", "task_id": "EVO-xxx"}
  POST /api/report/generate  {"mode": "git_diff", "base_branch": "master"}
  GET  /api/report/list?limit=20
  GET  /api/report/EVO-20250101000000-abc12345
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from pycoder.server.log import log
from pycoder.server.services.evolution_report import ReportGenerator

# ═══════════════════════════════════════════════════════════
# Pydantic 模型
# ═══════════════════════════════════════════════════════════


class GenerateReportRequest(BaseModel):
    """生成进化报告请求"""

    mode: str = Field(
        default="closed_loop",
        description="报告生成模式: closed_loop | git_diff",
    )
    task_id: str = Field(default="", description="任务 ID（closed_loop 模式下使用）")
    base_branch: str = Field(
        default="master", description="基准分支（git_diff 模式下使用）"
    )


class GenerateReportResponse(BaseModel):
    """生成报告响应"""

    success: bool
    task_id: str
    summary: str
    total_files_changed: int
    net_lines: int
    highest_risk: str
    message: str


class ReportListItem(BaseModel):
    """报告列表项"""

    file_name: str
    path: str
    size_bytes: int
    modified_at: str
    format: str


class ReportListResponse(BaseModel):
    """报告列表响应"""

    success: bool
    total: int
    reports: list[dict]


class ReportDetailResponse(BaseModel):
    """报告详情响应"""

    success: bool
    report: dict | None = None
    error: str | None = None


# ═══════════════════════════════════════════════════════════
# 创建路由器
# ═══════════════════════════════════════════════════════════

router = APIRouter(prefix="/api/report", tags=["report"])

# ── 全局报告生成器单例 ───────────────────────────────

_generator: ReportGenerator | None = None


def _get_generator() -> ReportGenerator:
    """获取或创建报告生成器单例"""
    global _generator
    if _generator is None:
        _generator = ReportGenerator(workspace=Path.cwd())
    return _generator


# ─────────────────────────────────────────────────────────
# 生成报告
# ─────────────────────────────────────────────────────────


@router.post(
    "/generate",
    response_model=GenerateReportResponse,
    summary="📊 生成进化报告",
    description="根据闭环验证结果或 Git diff 生成 Codex 风格的进化变更报告",
)
async def generate_report(
    payload: GenerateReportRequest = Body(...),
) -> dict:
    """
    生成进化变更报告

    支持两种模式:
      - closed_loop: 从闭环验证结果生成报告
      - git_diff: 从 Git diff 对比生成报告

    Args:
        payload: 包含 mode, task_id, base_branch 的请求体

    Returns:
        生成的报告摘要信息
    """
    generator = _get_generator()

    if payload.mode not in ("closed_loop", "git_diff"):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的模式: {payload.mode}，可选值: closed_loop, git_diff",
        )

    try:
        if payload.mode == "git_diff":
            report = await generator.generate_from_git_diff(
                base_branch=payload.base_branch
            )
        else:
            # closed_loop 模式 — 从 task_id 获取报告（如果已存在闭环结果）
            # 此处使用简化的报告生成，实际闭环结果由外部注入
            report = await generator.generate_from_closed_loop(
                type(
                    "ClosedLoopResult",
                    (),
                    {
                        "task_id": payload.task_id or "EVO-UNKNOWN",
                        "success": True,
                        "steps_completed": 0,
                        "changes": [],
                        "test_results": [],
                        "risk_analysis": [],
                        "rollback_plan": {},
                        "lessons_learned": [],
                        "duration": 0.0,
                        "self_heal_attempts": 0,
                        "final_status": "no_data",
                    },
                )()
            )

        # 保存报告到持久化存储
        await generator.save_report(report)

        return {
            "success": True,
            "task_id": report.report_id,
            "summary": report.executive_summary or f"任务「{report.task}」报告",
            "total_files_changed": len(report.file_changes),
            "net_lines": report.total_lines_added - report.total_lines_removed,
            "highest_risk": max(
                (r.severity for r in report.risk_analysis),
                key=lambda s: {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(s, 0),
                default="low",
            ),
            "message": f"✓ 报告已生成并保存: {report.report_id}",
        }

    except Exception as e:
        log.error("report_generate_error", mode=payload.mode, error=str(e))
        raise HTTPException(
            status_code=500, detail=f"报告生成失败: {e}"
        ) from e


# ─────────────────────────────────────────────────────────
# 列出报告
# ─────────────────────────────────────────────────────────


@router.get(
    "/list",
    response_model=ReportListResponse,
    summary="📋 列出进化报告",
    description="获取最近的进化变更报告列表，按修改时间降序排列",
)
async def list_reports(
    limit: int = Query(default=20, ge=1, le=100, description="最大返回数量"),
) -> dict:
    """
    列出最近的进化报告

    Args:
        limit: 返回的最大报告数量（1-100）

    Returns:
        报告列表和总数
    """
    generator = _get_generator()

    try:
        reports = await generator.list_reports(limit=limit)
        return {
            "success": True,
            "total": len(reports),
            "reports": reports,
        }
    except Exception as e:
        log.error("report_list_error", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"获取报告列表失败: {e}"
        ) from e


# ─────────────────────────────────────────────────────────
# 获取指定报告
# ─────────────────────────────────────────────────────────


@router.get(
    "/{task_id}",
    response_model=ReportDetailResponse,
    summary="📖 获取进化报告",
    description="根据 task_id 获取指定的进化变更报告详情",
)
async def get_report(
    task_id: str,
) -> dict:
    """
    获取指定 task_id 的进化报告

    Args:
        task_id: 报告的任务 ID（如 EVO-20250101000000-abc12345）

    Returns:
        报告详情或错误信息
    """
    generator = _get_generator()

    try:
        report = await generator.get_report(task_id=task_id)

        if report is None:
            return {
                "success": False,
                "report": None,
                "error": f"未找到报告: {task_id}",
            }

        return {
            "success": True,
            "report": report.to_dict(),
        }

    except Exception as e:
        log.error("report_get_error", task_id=task_id, error=str(e))
        raise HTTPException(
            status_code=500, detail=f"获取报告失败: {e}"
        ) from e


__all__ = ["router"]