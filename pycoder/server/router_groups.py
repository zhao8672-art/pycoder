"""路由分组注册 — 阶段 1 架构升级

原 `app.py` 中 61 个 `include_router()` 散落在各处的「重复样板」收敛到这里，
按业务域分组声明，app.py 仅需 1 行 `register_router_groups(app)`。

设计要点：
- 每组是一个 dict：name -> (router, optional prefix) 或 list[router]
- `register_router_groups(app)` 遍历所有组并 include_router
- 与原行为完全等价（保持所有 prefix/不 prefix 顺序）
- 单测可单独调用任意 group 验证（无需启动整个 app）
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


# ── 1. 健康检查（无前缀） ─────────────────────────────────────────
def _register_health(app: "FastAPI") -> None:
    from pycoder.server.routers.health import router as health_router

    app.include_router(health_router)


# ── 2. 工具类（Filesystem / Shell / Git / Search） ─────────────────
def _register_tools(app: "FastAPI") -> None:
    from pycoder.server.routers.code_exec import router as code_exec_router
    from pycoder.server.routers.diff import router as diff_router
    from pycoder.server.routers.diff_list import router as diff_list_router
    from pycoder.server.routers.files import router as files_router
    from pycoder.server.routers.git import router as git_router
    from pycoder.server.routers.search import router as search_router
    from pycoder.server.routers.terminal import router as terminal_router
    from pycoder.server.routers.visualize import router as visualize_router

    app.include_router(files_router)
    app.include_router(terminal_router)
    app.include_router(diff_router)
    app.include_router(diff_list_router)
    app.include_router(git_router)
    app.include_router(search_router)
    app.include_router(code_exec_router, prefix="/api/code")
    app.include_router(visualize_router)


# ── 3. 核心服务（Config / Chat / REST / Context / Extensions） ─────
def _register_core(app: "FastAPI") -> None:
    from pycoder.server.routers.chat_routes import router as chat_router
    from pycoder.server.routers.config import router as config_router
    from pycoder.server.routers.context import router as context_router
    from pycoder.server.routers.extensions import router as extensions_router
    from pycoder.server.routers.rest_routes import router as rest_router

    app.include_router(config_router)
    app.include_router(chat_router)
    app.include_router(rest_router)
    app.include_router(context_router)
    app.include_router(extensions_router)


# ── 4. AI / 浏览器自进化 ──────────────────────────────────────────
def _register_ai(app: "FastAPI") -> None:
    from pycoder.server.routers.browser_ai import router as browser_ai_router

    app.include_router(browser_ai_router)


# ── 5. 业务模块（Skills / Cloud / Recommendation / GitHub 等） ────
def _register_business(app: "FastAPI") -> None:
    from pycoder.server.routers.autonomous_api import router as autonomous_router
    from pycoder.server.routers.cloud_api import router as cloud_api_router
    from pycoder.server.routers.file_transfer import router as file_transfer_router
    from pycoder.server.routers.format_api import router as format_router
    from pycoder.server.routers.github import router as github_router
    from pycoder.server.routers.integrations_api import (
        chart_router,
        dep_router,
        openapi_router,
        runtime_router,
        undo_router,
    )
    from pycoder.server.routers.pipeline import router as pipeline_router
    from pycoder.server.routers.recommendation_api import router as recommendation_router
    from pycoder.server.routers.refactor_api import router as refactor_router
    from pycoder.server.routers.scaffold_api import router as scaffold_router
    from pycoder.server.routers.skills_api_v2 import router as skills_api_v2_router
    from pycoder.server.routers.team_api import router as team_router

    app.include_router(skills_api_v2_router)
    app.include_router(cloud_api_router)
    app.include_router(recommendation_router)
    app.include_router(github_router)
    app.include_router(team_router)
    app.include_router(file_transfer_router)
    app.include_router(pipeline_router)
    app.include_router(scaffold_router)
    app.include_router(refactor_router)
    app.include_router(openapi_router)
    app.include_router(chart_router)
    app.include_router(runtime_router)
    app.include_router(dep_router)
    app.include_router(undo_router)
    app.include_router(format_router)
    app.include_router(autonomous_router)


# ── 6. 高级能力（Debug / Rules / Scheduler / Advanced） ────────────
def _register_advanced(app: "FastAPI") -> None:
    from pycoder.server.routers.advanced_api import (
        debug_router,
        rules_router,
        scheduler_router,
    )

    app.include_router(scheduler_router)
    app.include_router(rules_router)
    app.include_router(debug_router)


# ── 7. V2 引擎 API（核心 API + 进化 API + WebSocket） ─────────────
def _register_v2(app: "FastAPI") -> None:
    from pycoder.server.routers.v2 import router as v2_router
    from pycoder.server.routers.v2.evolution import router as v2_evolution_router
    from pycoder.server.routers.v2.evolution import ws_router as v2_evolution_ws_router

    app.include_router(v2_router)
    app.include_router(v2_evolution_router)
    app.include_router(v2_evolution_ws_router)


# ── 8. 系统能力（Workspace / Knowledge / Memory / Notify） ───────
def _register_system(app: "FastAPI") -> None:
    from pycoder.server.routers.knowledge_api import router as knowledge_api_router
    from pycoder.server.routers.memory_api import router as memory_api_router
    from pycoder.server.routers.notify_api import router as notify_api_router
    from pycoder.server.routers.notify_api import ws_router as notify_ws_router
    from pycoder.server.routers.session_search import router as session_search_router
    from pycoder.server.routers.workspace_api import router as workspace_api_router

    from pycoder.server.routers.dep_api import router as dep_api_router
    from pycoder.server.routers.env_api import router as env_api_router

    app.include_router(session_search_router)
    app.include_router(dep_api_router)
    app.include_router(env_api_router)
    app.include_router(workspace_api_router)
    app.include_router(knowledge_api_router)
    app.include_router(memory_api_router)
    app.include_router(notify_api_router)
    app.include_router(notify_ws_router)


# ── 9. Phase 1 升级（Gateway / Sandbox / DeepMemory / Guard） ─────
def _register_phase1(app: "FastAPI") -> None:
    from pycoder.server.routers.deep_memory_api import router as deep_memory_router
    from pycoder.server.routers.gateway_api import router as gateway_router
    from pycoder.server.routers.gateway_api import ws_router as gateway_ws_router
    from pycoder.server.routers.guard_api import router as guard_router
    from pycoder.server.routers.sandbox_api import router as sandbox_router

    app.include_router(gateway_router)
    app.include_router(gateway_ws_router)
    app.include_router(sandbox_router)
    app.include_router(deep_memory_router)
    app.include_router(guard_router)


# ── 10. Phase 2-3 升级（DAG / Task / Report / Marketplace / ...） ──
def _register_phase23(app: "FastAPI") -> None:
    from pycoder.server.routers.agents_api import router as agents_router
    from pycoder.server.routers.dag_api import router as dag_router
    from pycoder.server.routers.learning_api import router as learning_router
    from pycoder.server.routers.mcp_routes import router as mcp_router
    from pycoder.server.routers.media_routes import router as media_router
    from pycoder.server.routers.report_api import router as report_router
    from pycoder.server.routers.skills_marketplace_api import router as skills_marketplace_router
    from pycoder.server.routers.task_api import router as task_api_router
    from pycoder.server.routers.web_routes import router as web_router

    app.include_router(dag_router)
    app.include_router(task_api_router)
    app.include_router(report_router)
    app.include_router(skills_marketplace_router)
    app.include_router(agents_router)
    app.include_router(learning_router)
    app.include_router(web_router)
    app.include_router(media_router)
    app.include_router(mcp_router)


# ── 11. WebSocket（独立挂载） ─────────────────────────────────────
def _register_websocket(app: "FastAPI") -> None:
    from pycoder.server.routers.advanced_api import collab_ws_router
    from pycoder.server.routers.autonomous_api import ws_router as autonomous_ws_router

    app.include_router(collab_ws_router)
    app.include_router(autonomous_ws_router)


# ── 组装入口（app.py 仅需调用此函数） ─────────────────────────────
REGISTRY = [
    ("health", _register_health),
    ("tools", _register_tools),
    ("core", _register_core),
    ("ai", _register_ai),
    ("business", _register_business),
    ("advanced", _register_advanced),
    ("v2", _register_v2),
    ("system", _register_system),
    ("phase1", _register_phase1),
    ("phase23", _register_phase23),
    ("websocket", _register_websocket),
]


def register_router_groups(app: "FastAPI") -> None:
    """按业务域分组注册所有路由（替代 app.py 中 61 处 include_router）

    Returns:
        None — 副作用为向 app 注册路由

    Side Effects:
        - 修改 app._routes
    """
    for _name, _register in REGISTRY:
        _register(app)


# 可单测的子注册函数（暴露给 tests 使用）
__all__ = [
    "register_router_groups",
    "REGISTRY",
    "_register_health",
    "_register_tools",
    "_register_core",
    "_register_ai",
    "_register_business",
    "_register_advanced",
    "_register_v2",
    "_register_system",
    "_register_phase1",
    "_register_phase23",
    "_register_websocket",
]
