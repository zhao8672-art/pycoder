"""
OpenAPI 集成 API + 图表生成 + 运行时安装 + 依赖冲突 + 文件撤销
"""

from __future__ import annotations

from fastapi import APIRouter

from pycoder.python.chart_generator import get_chart_generator
from pycoder.python.dep_conflict_resolver import get_dep_resolver
from pycoder.python.file_undo import get_undo_manager
from pycoder.python.openapi_integrator import generate_from_openapi, generate_mock_server
from pycoder.python.runtime_installer import get_runtime_installer

openapi_router = APIRouter(prefix="/api/openapi")
chart_router = APIRouter(prefix="/api/charts")
runtime_router = APIRouter(prefix="/api/runtime")
dep_router = APIRouter(prefix="/api/deps")
undo_router = APIRouter(prefix="/api/undo")


@openapi_router.post("/generate")
async def openapi_generate(req: dict):
    return generate_from_openapi(
        spec_url=req.get("url", ""),
        spec_json=req.get("spec"),
        language=req.get("language", "python"),
        output_dir=req.get("output_dir", ""),
    )


@openapi_router.post("/mock")
async def openapi_mock(req: dict):
    return generate_mock_server(req.get("spec", {}))


@chart_router.post("/plotly")
async def plotly_chart(req: dict):
    g = get_chart_generator()
    return g.plotly_chart(
        req.get("type", "bar"),
        req.get("data", []),
        req.get("title", ""),
    )


@chart_router.post("/altair")
async def altair_chart(req: dict):
    g = get_chart_generator()
    return g.altair_chart(
        req.get("data", []),
        req.get("x_field", "x"),
        req.get("y_field", "y"),
        req.get("title", ""),
    )


@chart_router.post("/flame")
async def flame_graph(req: dict):
    g = get_chart_generator()
    return g.flame_graph_data(req)


@chart_router.post("/quick")
async def quick_charts(req: dict):
    g = get_chart_generator()
    return {"success": True, "charts": g.quick_charts(req.get("data", []))}


@runtime_router.get("/check/{language}")
async def check_runtime(language: str):
    return get_runtime_installer().check(language)


@runtime_router.get("/check-all")
async def check_all_runtimes():
    return {"success": True, "results": get_runtime_installer().check_all()}


@runtime_router.post("/install/{language}")
async def install_runtime(language: str):
    return get_runtime_installer().install(language)


@runtime_router.get("/scan-workspace")
async def scan_workspace_needs(project_dir: str = "."):
    return {
        "success": True,
        "needs": get_runtime_installer().scan_workspace_needs(project_dir),
    }


@dep_router.get("/conflicts")
async def dep_conflicts(project: str = "."):
    return get_dep_resolver().analyze(project)


@undo_router.post("/preview")
async def preview_diff(req: dict):
    return get_undo_manager().preview_diff(req["file"], req["content"])


@undo_router.post("/snapshot")
async def snapshot_file(req: dict):
    get_undo_manager().snapshot(req["file"], req.get("operation", "save"))
    return {"success": True}


@undo_router.post("/undo")
async def undo_file(req: dict):
    return get_undo_manager().undo(
        req["file"],
        req.get("steps", 1),
    )


@undo_router.get("/history")
async def file_history(file_path: str = ""):
    return {"success": True, "history": get_undo_manager().history(file_path)}


@undo_router.get("/diff-history")
async def diff_history(file_path: str = "", step: int = 1):
    return get_undo_manager().diff_history(file_path, step)
