"""
V2 REST API — 自我进化与架构管理端点

提供:
- POST /api/v2/evolution/scan    — 扫描代码库
- POST /api/v2/evolution/fix     — 修复指定问题
- POST /api/v2/evolution/apply   — 应用修复方案
- GET  /api/v2/evolution/history — 进化历史
- GET  /api/v2/capabilities      — 能力列表
- GET  /api/v2/health            — 系统健康
- POST /api/v2/trust/escalate    — 提升信任级别
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["v2"])


# ── 请求模型 ──────────────────────────────


class ScanRequest(BaseModel):
    path: str = Field(default="pycoder", description="扫描路径")
    use_llm: bool = Field(default=True, description="是否使用 LLM 深度分析")


class FixRequest(BaseModel):
    file: str = Field(..., description="文件路径")
    line: int = Field(..., description="行号")
    severity: str = Field(default="high", description="严重度")
    issue_type: str = Field(default="bug", description="问题类型")
    title: str = Field(..., description="问题标题")
    description: str = Field(default="")
    suggestion: str = Field(default="")


class ApplyRequest(BaseModel):
    issue_index: int = Field(..., description="扫描报告中的问题序号")
    confirm: bool = Field(default=False, description="人工确认")


class EscalateRequest(BaseModel):
    reason: str = Field(default="", description="提升原因")


# ── 辅助函数 ──────────────────────────────


def _get_engine(request: Request):
    """从 app.state 获取 V2 引擎"""
    engine = getattr(request.app.state, "v2_engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="V2 引擎未初始化")
    return engine


# ── 进化端点 ──────────────────────────────


@router.post("/evolution/scan")
async def scan_code(request: Request, body: ScanRequest):
    """扫描代码库，识别问题"""
    engine = _get_engine(request)

    if engine.evolution is None:
        raise HTTPException(status_code=503, detail="自我进化引擎未就绪")

    try:
        report = await engine.evolution.scan(body.path, use_llm=body.use_llm)
        return {
            "path": report.path,
            "files_scanned": report.files_scanned,
            "total_issues": report.total_issues,
            "duration_seconds": round(report.duration_seconds, 2),
            "issues": [
                {
                    "index": i,
                    "file": issue.file,
                    "line": issue.line,
                    "severity": issue.severity,
                    "type": issue.issue_type,
                    "title": issue.title,
                    "suggestion": issue.suggestion,
                }
                for i, issue in enumerate(report.issues)
            ],
            "summary": report.summary,
            "severity_counts": _count_severity(report.issues),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/evolution/fix")
async def generate_fix(request: Request, body: FixRequest):
    """为指定问题生成修复方案"""
    engine = _get_engine(request)

    if engine.evolution is None:
        raise HTTPException(status_code=503, detail="自我进化引擎未就绪")

    from pycoder.capabilities.self_evo.engine import CodeIssue

    issue = CodeIssue(
        file=body.file,
        line=body.line,
        severity=body.severity,
        issue_type=body.issue_type,
        title=body.title,
        description=body.description,
        suggestion=body.suggestion,
    )

    try:
        proposal = await engine.evolution.generate_fix(issue)
        return {
            "file": proposal.file_path,
            "action": proposal.action,
            "old_code": proposal.old_code,
            "new_code": proposal.new_code,
            "line_start": proposal.line_start,
            "reasoning": proposal.reasoning,
            "risk_level": proposal.risk_level,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/evolution/apply")
async def apply_fix(request: Request, body: ApplyRequest):
    """应用修复方案（需要人工确认）"""
    engine = _get_engine(request)

    if not body.confirm:
        return {
            "status": "waiting_confirmation",
            "message": "请设置 confirm=true 来确认应用修复",
        }

    if engine.evolution is None:
        raise HTTPException(status_code=503, detail="自我进化引擎未就绪")

    # 从内存中获取之前的扫描结果
    if not hasattr(engine.evolution, "_last_issues"):
        raise HTTPException(status_code=400, detail="请先运行 /api/v2/evolution/scan")

    issues = engine.evolution._last_issues
    if body.issue_index >= len(issues):
        raise HTTPException(status_code=400, detail=f"问题序号超出范围 (0-{len(issues)-1})")

    issue = issues[body.issue_index]
    try:
        proposal = await engine.evolution.generate_fix(issue)
        result = await engine.evolution.apply_fix(proposal)

        # 记录进化
        from pycoder.capabilities.self_evo.engine import EvolutionRecord
        engine.evolution.record_evolution(EvolutionRecord(
            action="apply_fix",
            issue_type=issue.issue_type,
            file=issue.file,
            success=result.success,
            fix_description=proposal.reasoning[:200],
            test_result="passed" if result.test_passed else "failed",
            lessons=f"{'成功' if result.success else '失败'}: {result.error or ''}",
        ))

        return {
            "success": result.success,
            "test_passed": result.test_passed,
            "git_branch": result.git_branch,
            "git_commit": result.git_commit[:50],
            "error": result.error,
            "rollback_needed": result.rollback_needed,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/evolution/history")
async def evolution_history(request: Request, limit: int = 50):
    """获取进化历史"""
    engine = _get_engine(request)

    if engine.evolution is None:
        return {"history": []}

    return {
        "history": engine.evolution.get_evolution_history(limit),
    }


# ── 能力端点 ──────────────────────────────


@router.get("/capabilities")
async def list_capabilities(request: Request, category: str = "", search: str = ""):
    """列出所有已注册的能力"""
    engine = _get_engine(request)

    if search:
        caps = engine.registry.search(search)
    elif category:
        from pycoder.bus.protocol import CapabilityCategory
        try:
            cat = CapabilityCategory(category)
            caps = engine.registry.list_by_category(cat)
        except ValueError:
            caps = engine.registry.list_all()
    else:
        caps = engine.registry.list_all()

    return {
        "total": len(caps),
        "capabilities": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "category": c.category.value,
                "permission": c.permission.name,
                "version": c.version,
            }
            for c in caps
        ],
    }


# ── 健康端点 ──────────────────────────────


@router.get("/health")
async def v2_health(request: Request):
    """V2 系统健康检查"""
    engine = _get_engine(request)

    return {
        "status": "healthy",
        "engine": {
            "capabilities": engine.registry.count,
            "trust_level": engine.permission.current_trust.name,
            "audit_records": engine.audit.record_count,
            "consciousness_mode": engine.consciousness.mode.value,
        },
        "evolution": engine.evolution.get_stats() if engine.evolution else {"status": "disabled"},
        "monitor": engine.monitor.get_stats(),
    }


# ── 信任管理 ──────────────────────────────


@router.post("/trust/escalate")
async def escalate_trust(request: Request, body: EscalateRequest):
    """申请提升 AI 信任级别"""
    engine = _get_engine(request)

    ok, message = engine.permission.escalate_trust(body.reason)
    if not ok:
        raise HTTPException(status_code=400, detail=message)

    return {
        "new_level": engine.permission.current_trust.name,
        "new_level_value": engine.permission.current_trust.value,
        "message": message,
    }


@router.get("/trust/status")
async def trust_status(request: Request):
    """获取信任状态"""
    engine = _get_engine(request)

    return engine.permission.get_trust_report()


# ── 统计端点 ──────────────────────────────


@router.get("/stats")
async def v2_stats(request: Request):
    """获取 V2 引擎完整统计"""
    engine = _get_engine(request)
    return engine.get_stats()


# ── 工具 ──────────────────────────────────


def _count_severity(issues: list) -> dict[str, int]:
    """统计各严重度的问题数"""
    from collections import Counter
    return dict(Counter(i.severity for i in issues))
