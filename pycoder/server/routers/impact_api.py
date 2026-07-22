"""P1-2: 影响分析 REST API

端点:
- POST /api/impact/build       - 构建/重建引用图
- GET  /api/impact/stats       - 统计信息
- GET  /api/impact/symbols     - 列出所有符号
- POST /api/impact/callers     - 查询调用者
- POST /api/impact/callees     - 查询被调用者
- POST /api/impact/impact      - 影响分析（修改此符号会影响谁）
- GET  /api/impact/export/dot  - 导出 Graphviz DOT
- GET  /api/impact/export/json - 导出 JSON
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/impact", tags=["impact-analysis"])

# ── 单例分析器 ──────────────────────────────────────────
_analyzer = None
_analyzer_lock = threading.Lock()
_workspace_root: Path | None = None


def get_analyzer():
    """获取或创建 ImpactAnalyzer 单例"""
    global _analyzer, _workspace_root
    if _analyzer is None:
        with _analyzer_lock:
            if _analyzer is None:
                from pycoder.python.impact_analyzer import ImpactAnalyzer

                _workspace_root = Path.cwd()
                _analyzer = ImpactAnalyzer(workspace=_workspace_root)
                _analyzer.build()
                logger.info("impact_analyzer_initialized workspace=%s", _workspace_root)
    return _analyzer


def reset_analyzer(workspace: Path | None = None) -> None:
    """重置分析器（用于工作区变更后重建）"""
    global _analyzer, _workspace_root
    with _analyzer_lock:
        _analyzer = None
        if workspace is not None:
            _workspace_root = workspace


# ── Pydantic 模型 ──────────────────────────────────────


class BuildRequest(BaseModel):
    workspace: str | None = None
    force: bool = False


class BuildResponse(BaseModel):
    success: bool
    workspace: str
    stats: dict


class SymbolQueryRequest(BaseModel):
    name: str
    file: str = ""
    qualname: str = ""
    max_depth: int = Field(default=3, ge=1, le=10)


class CallerResponse(BaseModel):
    target: str
    file: str
    count: int
    references: list[dict]


class ImpactResponse(BaseModel):
    target_file: str
    target_symbol: str
    total_count: int
    max_depth: int
    affected: list[dict]


# ── 端点 ──────────────────────────────────────────────


@router.post("/build", response_model=BuildResponse)
async def build_graph(req: BuildRequest) -> BuildResponse:
    """构建/重建项目引用图"""
    global _workspace_root

    if req.workspace:
        new_root = Path(req.workspace).resolve()
        if not new_root.exists():
            raise HTTPException(status_code=400, detail=f"工作区不存在: {req.workspace}")
        if new_root != _workspace_root or req.force:
            reset_analyzer(workspace=new_root)

    analyzer = get_analyzer()
    if req.force:
        analyzer.build()

    return BuildResponse(
        success=True,
        workspace=str(analyzer.workspace),
        stats=analyzer.stats(),
    )


@router.get("/stats")
async def get_stats() -> dict:
    """获取当前引用图统计信息"""
    analyzer = get_analyzer()
    return {
        "workspace": str(analyzer.workspace),
        "stats": analyzer.stats(),
    }


@router.get("/symbols")
async def list_symbols(file: str = "") -> dict:
    """列出所有符号（或指定文件内）"""
    analyzer = get_analyzer()
    syms = analyzer.list_symbols(file=file)
    return {
        "count": len(syms),
        "symbols": [
            {
                "file": s.file,
                "name": s.name,
                "kind": s.kind,
                "line": s.line,
                "qualname": s.qualname,
                "args": s.args,
                "docstring": s.docstring,
            }
            for s in syms
        ],
    }


@router.post("/callers", response_model=CallerResponse)
async def find_callers(req: SymbolQueryRequest) -> CallerResponse:
    """查询调用指定符号的所有引用点"""
    analyzer = get_analyzer()
    refs = analyzer.find_callers(
        name=req.name, file=req.file, qualname=req.qualname
    )
    return CallerResponse(
        target=req.qualname or req.name,
        file=req.file,
        count=len(refs),
        references=[r.to_dict() for r in refs],
    )


@router.post("/callees", response_model=CallerResponse)
async def find_callees(req: SymbolQueryRequest) -> CallerResponse:
    """查询指定符号内部调用的下游符号"""
    analyzer = get_analyzer()
    refs = analyzer.find_callees(
        name=req.name, file=req.file, qualname=req.qualname
    )
    return CallerResponse(
        target=req.qualname or req.name,
        file=req.file,
        count=len(refs),
        references=[r.to_dict() for r in refs],
    )


@router.post("/impact", response_model=ImpactResponse)
async def find_impact(req: SymbolQueryRequest) -> ImpactResponse:
    """影响分析：修改此符号会影响哪些调用方？"""
    analyzer = get_analyzer()
    result = analyzer.find_impact(
        name=req.name,
        file=req.file,
        qualname=req.qualname,
        max_depth=req.max_depth,
    )
    return ImpactResponse(**result.to_dict())


@router.get("/export/dot")
async def export_dot(max_nodes: int = 200) -> dict:
    """导出引用图为 Graphviz DOT 格式"""
    analyzer = get_analyzer()
    dot = analyzer.export_dot(max_nodes=max_nodes)
    return {
        "format": "dot",
        "content": dot,
        "size": len(dot),
    }


@router.get("/export/json")
async def export_json() -> dict:
    """导出引用图为 JSON"""
    analyzer = get_analyzer()
    return {
        "format": "json",
        "content": analyzer.export_json(),
    }


@router.get("/context")
async def get_prompt_context(focus_files: str = "") -> dict:
    """生成注入到 system prompt 的引用图上下文"""
    analyzer = get_analyzer()
    files = [f.strip() for f in focus_files.split(",") if f.strip()]
    ctx = analyzer.generate_prompt_context(focus_files=files or None)
    return {
        "context": ctx,
        "workspace": str(analyzer.workspace),
    }
