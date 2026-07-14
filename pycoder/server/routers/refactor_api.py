"""
代码重构 API — 批量重命名/提取函数/移动模块
"""

from __future__ import annotations

from fastapi import APIRouter

from pycoder.python.code_refactor import get_refactor_engine

router = APIRouter(prefix="/api/refactor")


@router.post("/rename")
async def rename_symbol(req: dict):
    engine = get_refactor_engine()
    result = engine.rename_symbol(
        req["file"],
        req["old_name"],
        req["new_name"],
    )
    return {
        "success": result.success,
        "operation": result.operation,
        "changes": result.changes,
        "error": result.error,
    }


@router.post("/extract")
async def extract_function(req: dict):
    engine = get_refactor_engine()
    result = engine.extract_function(
        req["file"],
        req["start_line"],
        req["end_line"],
        req["new_name"],
    )
    return {
        "success": result.success,
        "operation": result.operation,
        "changes": result.changes,
        "error": result.error,
    }


@router.post("/move")
async def move_module(req: dict):
    engine = get_refactor_engine()
    result = engine.move_module(req["source_path"], req["dest_dir"])
    return {
        "success": result.success,
        "operation": result.operation,
        "changes": result.changes,
        "error": result.error,
    }


@router.post("/add-types")
async def add_type_annotations(req: dict):
    engine = get_refactor_engine()
    result = engine.add_type_annotations(req["file"])
    return {
        "success": result.success,
        "operation": result.operation,
        "changes": result.changes,
        "error": result.error,
    }


@router.post("/analyze")
async def refactor_analyze(req: dict):
    """代码质量问题分析"""
    from pycoder.python.refactor_analyzer import RefactoringAnalyzer

    code = req.get("code", "")
    analyzer = RefactoringAnalyzer()
    result = analyzer.analyze_code(code)
    return {
        "success": result.success,
        "issues": [
            {"type": i.type, "severity": i.severity, "message": i.message} for i in result.issues
        ],
        "summary": result.summary,
    }


@router.post("/suggest")
async def refactor_suggest(req: dict):
    """获取重构建议"""
    from pycoder.python.refactor_analyzer import RefactoringAnalyzer

    code = req.get("code", "")
    analyzer = RefactoringAnalyzer()
    result = analyzer.analyze_code(code)
    suggestions = [i.suggestion for i in result.issues]
    return {"success": True, "suggestions": suggestions}


@router.post("/quality")
async def refactor_quality(req: dict):
    """代码质量评分"""
    from pycoder.python.code_quality import CodeQualityAnalyzer

    code = req.get("code", "")
    analyzer = CodeQualityAnalyzer()
    result = analyzer.analyze(code)
    score = result.get("quality_score", {})
    return {"success": True, "score": score, "summary": result.get("summary", "")}
