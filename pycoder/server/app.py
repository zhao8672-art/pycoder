"""PyCoder App Server - FastAPI + WebSocket service for Electron Desktop."""

from __future__ import annotations

import logging as _logging
import os

# ── API 密钥认证中间件（P0-4 强制模式） ───────────────────
#
# 策略：
#   - 显式 PYCODER_API_KEY=disabled  → 关闭认证（仅开发用，启动时告警）
#   - PYCODER_API_KEY=<key>          → 强制认证
#   - 未设置                          → 自动生成临时 key 并打印日志
#                                       （生产应显式设置，避免每次重启变化）
#
# 此修改避免生产环境因运维忘记设置环境变量而完全暴露 API。
import secrets as _secrets
from contextlib import asynccontextmanager
from pathlib import Path as _Path

from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from pycoder import __version__
from pycoder.server.app_lifecycle import run_server
from pycoder.server.permission_policy import get_permission_policy
from pycoder.server.routers.advanced_api import (
    collab_ws_router,
    debug_router,
    rules_router,
    scheduler_router,
)
from pycoder.server.routers.autonomous_api import router as autonomous_router
from pycoder.server.routers.autonomous_api import ws_router as autonomous_ws_router
from pycoder.server.routers.browser_ai import router as browser_ai_router
from pycoder.server.routers.chat_routes import router as chat_router
from pycoder.server.routers.cloud_api import router as cloud_api_router
from pycoder.server.routers.code_exec import router as code_exec_router
from pycoder.server.routers.config import router as config_router
from pycoder.server.routers.context import router as context_router
from pycoder.server.routers.diff import router as diff_router
from pycoder.server.routers.diff_list import router as diff_list_router
from pycoder.server.routers.v2.evolution import router as v2_evolution_router
from pycoder.server.routers.v2.evolution import ws_router as v2_evolution_ws_router
from pycoder.server.routers.extensions import router as extensions_router
from pycoder.server.routers.file_transfer import router as file_transfer_router
from pycoder.server.routers.files import router as files_router
from pycoder.server.routers.format_api import router as format_router
from pycoder.server.routers.git import router as git_router
from pycoder.server.routers.github import router as github_router
from pycoder.server.routers.health import router as health_router
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
from pycoder.server.routers.rest_routes import router as rest_router
from pycoder.server.routers.scaffold_api import router as scaffold_router
from pycoder.server.routers.search import router as search_router
from pycoder.server.routers.skills_api_v2 import router as skills_api_v2_router
from pycoder.server.routers.team_api import router as team_router
from pycoder.server.routers.terminal import router as terminal_router
from pycoder.server.routers.visualize import router as visualize_router
from pycoder.server.routers.v2 import router as v2_router
from pycoder.server.ws_handler import websocket_chat
from pycoder.server.ws_handler_v2 import websocket_chat_v2

# Phase 2+3: New API routers
from pycoder.server.routers.session_search import router as session_search_router
from pycoder.server.routers.dep_api import router as dep_api_router

_logger = _logging.getLogger("pycoder.server.app")

_API_KEY_ENV = os.environ.get("PYCODER_API_KEY", "").strip()
_DEVMODE_DISABLED = _API_KEY_ENV.lower() == "disabled"


def _sync_api_key_to_file(key: str):
    """将 API Key 同步到 ~/.pycoder/.api_key，供 Electron 读取。"""
    try:
        _key_path = _Path.home() / ".pycoder" / ".api_key"
        _key_path.parent.mkdir(parents=True, exist_ok=True)
        _key_path.write_text(key, encoding="utf-8")
    except OSError:
        pass


if _DEVMODE_DISABLED:
    _logger.warning("API 认证已显式关闭（PYCODER_API_KEY=disabled），" "切勿用于生产环境！")
    _API_KEY = ""
elif _API_KEY_ENV:
    _API_KEY = _API_KEY_ENV
    _logger.info("API 认证已启用（来自 PYCODER_API_KEY 环境变量）")
    # 同步到 .api_key 文件，确保 Electron/前端始终读取正确 Key
    _sync_api_key_to_file(_API_KEY)
else:
    # 未设置：优先复用已有文件中的 key，避免每次重启生成新 key 导致前端 401
    _existing_key_file = _Path.home() / ".pycoder" / ".api_key"
    if _existing_key_file.is_file():
        try:
            _existing = _existing_key_file.read_text(encoding="utf-8").strip()
            if len(_existing) >= 16:
                _API_KEY = _existing
                _logger.info("API 认证已启用（复用 ~/.pycoder/.api_key 中的 Key）")
            else:
                raise ValueError("key too short")
        except (OSError, ValueError):
            _API_KEY = ""
    else:
        _API_KEY = ""

    if not _API_KEY:
        # 自动生成临时 key
        _API_KEY = _secrets.token_urlsafe(32)
        _masked = _API_KEY[:4] + "***" if _API_KEY else "***"
        _logger.warning(
            "PYCODER_API_KEY 未设置，已自动生成临时 API Key: %s "
            "（完整密钥请从 ~/.pycoder/.api_key 读取；生产环境请显式设置环境变量）",
            _masked,
        )
    _sync_api_key_to_file(_API_KEY)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """API 密钥验证中间件

    策略：
        - /api/health、/docs、/openapi.json、/ws/* 路径免认证
        - 其他所有 REST 请求必须携带 X-API-Key 头
        - _API_KEY 为空时跳过（仅当显式 PYCODER_API_KEY=disabled 时）

    安全说明：
        - 使用 secrets.compare_digest 防止时序攻击
        - 默认强制开启，避免运维疏忽导致 API 暴露
    """

    async def dispatch(self, request: Request, call_next):
        if not _API_KEY:
            return await call_next(request)

        path = request.url.path
        # 跳过 health、文档和 WebSocket 升级请求
        if path in ("/api/health", "/docs", "/openapi.json") or path.startswith("/ws/"):
            return await call_next(request)

        # 允许 file:// 来源的请求免认证（VSCode 内置浏览器 / Electron 开发模式）
        origin = request.headers.get("Origin", "")
        if not origin or origin == "null" or origin.startswith("file://"):
            return await call_next(request)

        api_key = request.headers.get("X-API-Key", "")
        if not _secrets.compare_digest(api_key, _API_KEY):
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
                headers={"WWW-Authenticate": "X-API-Key"},
            )
        response = await call_next(request)
        return response


async def verify_ws_auth(ws: WebSocket) -> bool:
    """WebSocket 认证校验 — 在 ws.accept() 前调用。

    检查 query 参数 ?api_key= 或 X-API-Key 头。
    认证关闭时（PYCODER_API_KEY=disabled）直接放行。
    file:// 来源免认证（VSCode 内置浏览器 / Electron 开发模式）。

    返回 True 表示通过，False 表示已拒绝（连接已关闭）。
    """
    if not _API_KEY:
        return True
    # file:// 来源免认证
    origin = ws.headers.get("origin", "")
    if not origin or origin == "null" or origin.startswith("file://"):
        return True
    token = ws.query_params.get("api_key") or ws.headers.get("x-api-key", "")
    if _secrets.compare_digest(token, _API_KEY):
        return True
    await ws.close(code=1008, reason="未授权：缺少或错误的 API Key")
    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期 — 启动时初始化 V2 引擎、推荐数据库、DI 容器和调度器"""
    await _init_recommendation_db()
    _init_di_container()

    # ── V2 引擎初始化 ──
    v2_engine = await _init_v2_engine()
    app.state.v2_engine = v2_engine

    # ── 插件注册表初始化 ──
    try:
        from pycoder.plugins.base import PluginRegistry
        from pycoder.plugins.hermes_plugin import HermesPlugin
        reg = PluginRegistry()
        reg.register(HermesPlugin())
        global _plugin_registry
        _plugin_registry = reg
        _logger.info("plugin_registry_initialized: plugins=1")
    except Exception as e:
        _logger.warning("plugin_registry_init_failed: %s", e)
        _plugin_registry = None

    # ── 自动升级检查：恢复中断的升级 ──
    try:
        from pycoder.capabilities.self_evo.upgrade import check_pending_on_startup
        result = check_pending_on_startup()
        if result and result.get("status") == "pending":
            _logger.info("auto_upgrade_pending: %s", result)
    except ImportError:
        pass

    await _start_scheduler()
    yield
    # 关闭 V2 引擎
    if v2_engine:
        try:
            await v2_engine.shutdown()
        except Exception as e:
            _logger.warning("v2_shutdown_failed: %s", e)
    # 关闭时停止调度器
    try:
        from pycoder.server.scheduler import get_scheduler

        scheduler = get_scheduler()
        if scheduler.is_running:
            await scheduler.stop()
    except (OSError, RuntimeError, ImportError) as e:
        _logger.warning("scheduler_shutdown_failed: %s", e)


def _init_di_container() -> None:
    """初始化依赖注入容器 — 注册所有核心端口实现。

    在服务器启动时调用，确保所有核心模块可通过 registry.resolve() 获取依赖。
    """
    from pathlib import Path as _Path2

    from pycoder.adapters.local_file_system import LocalFileSystem
    from pycoder.core.di import registry
    from pycoder.core.ports.code_sandbox import CodeSandbox
    from pycoder.core.ports.file_system import FileSystem
    from pycoder.server.routers.code_exec import (
        _run_in_subprocess,
        _sandbox_config,
    )
    from pycoder.server.routers.files import get_workspace_root

    workspace = _Path2(get_workspace_root())

    # FileSystem — 工作区文件操作
    registry.register(FileSystem, LocalFileSystem(workspace=workspace))

    # CodeSandbox — Docker 优先，子进程回退
    _sandbox = _create_sandbox(_run_in_subprocess, _sandbox_config)
    registry.register(CodeSandbox, _sandbox)

    # Memory Bank — 初始化项目持久记忆
    try:
        from pycoder.server.memory_bank import get_memory_bank

        mb = get_memory_bank(workspace=workspace)
        if not mb.has_memory():
            _logger.info("memory_bank_initialized empty=true")
        else:
            _logger.info(
                "memory_bank_initialized memories=%d",
                len(mb.list_memories()),
            )
    except (ImportError, OSError) as e:
        _logger.debug("memory_bank_skip reason=%s", e)

    # LLMProvider — 由 ChatBridge 适配（工厂延迟初始化）
    from pycoder.adapters.bridge_llm_provider import BridgeLLMProvider
    from pycoder.core.ports.llm_provider import LLMProvider
    from pycoder.server.chat_bridge import ChatBridge

    registry.register(LLMProvider, factory=lambda: BridgeLLMProvider(ChatBridge()))

    _logger.info(
        "di_container_initialized: %s",
        registry.list_registered(),
    )


async def _init_v2_engine():
    """初始化 V2 引擎 — 注册所有能力、启动 AI 大脑和安全体系"""
    try:
        from pycoder.v2 import V2Engine, V2EngineConfig
        from pycoder.bus.protocol import TrustLevel

        config = V2EngineConfig(
            workspace_root=os.getcwd(),
            initial_trust=TrustLevel.WORKSPACE_WRITE,
            enable_consciousness=True,
            enable_self_evo=True,
        )
        engine = V2Engine(config)
        await engine.initialize()
        _logger.info(
            "v2_engine_initialized: capabilities=%d trust=%s",
            engine.registry.count,
            engine.permission.current_trust.name,
        )
        return engine
    except ImportError as e:
        _logger.warning("v2_engine_skip: import_failed=%s", e)
        return None
    except Exception as e:
        _logger.error("v2_engine_init_failed: %s", e)
        return None


def get_v2_engine(app: FastAPI | None = None):
    """获取 V2 引擎实例（从 app.state 或模块级 app 引用）"""
    if app is not None:
        return getattr(app.state, "v2_engine", None)
    # 使用模块级 app 引用，避免依赖 fastapi._compat 私有 API
    try:
        return getattr(app.state, "v2_engine", None)
    except (AttributeError, NameError):
        pass
    return None


# ── 插件注册表（模块级单例）──
_plugin_registry = None  # PluginRegistry 实例


def get_plugin_registry():
    """获取全局插件注册表（PluginRegistry）

    在 lifespan 中初始化，供 PluginExecutor 后台调用。
    若尚未初始化，自动创建默认注册表并注册 HermesPlugin。
    """
    global _plugin_registry
    if _plugin_registry is not None:
        return _plugin_registry
    # 自动初始化
    try:
        from pycoder.plugins.base import PluginRegistry
        from pycoder.plugins.hermes_plugin import HermesPlugin
        _plugin_registry = PluginRegistry()
        _plugin_registry.register(HermesPlugin())
        _logger.info("plugin_registry_auto_init: registered=hermes")
    except Exception as e:
        _logger.warning("plugin_registry_auto_init_failed: %s", e)
        _plugin_registry = None
    return _plugin_registry


def _create_sandbox(run_fn, sandbox_config):
    """创建沙箱 — Docker 优先，不可用时回退子进程"""
    from pycoder.adapters.subprocess_sandbox import SubprocessSandbox

    # 尝试 Docker
    try:
        import shutil as _shutil

        if _shutil.which("docker"):
            from pycoder.adapters.docker_sandbox import DockerSandbox

            _logger.info("sandbox_docker_selected")
            return DockerSandbox(
                default_timeout=30,
                max_memory="512m",
            )
    except (ImportError, OSError) as e:
        _logger.info("sandbox_docker_unavailable reason=%s", e)

    # 回退子进程
    _logger.info("sandbox_subprocess_selected")
    return SubprocessSandbox(
        run_fn=run_fn,
        max_timeout_fn=lambda: sandbox_config.max_timeout,
        default_timeout=30,
        max_timeout=120,
    )


app = FastAPI(
    title="PyCoder API",
    description="Python AI Coding Agent",
    version=__version__,
    lifespan=lifespan,
)

# 加载权限策略并在启动时缓存
_permission_policy = get_permission_policy()

# 始终注册 API 认证中间件（内部根据 _API_KEY 是否为空决定是否生效）
app.add_middleware(APIKeyMiddleware)


# ── 速率限制中间件（防止滥用 /api/code/exec、LLM 调用等）──
def _create_rate_limit_middleware():
    """简单内存速率限制：每 IP 每分钟最多 60 次请求"""
    import time as _time
    from collections import defaultdict

    _limits: dict = defaultdict(list)
    _RATE = 60
    _WINDOW = 60

    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # 只限制敏感端点
            path = request.url.path
            if not any(p in path for p in ["/api/code/", "/api/chat", "/api/skills"]):
                return await call_next(request)
            client_ip = request.client.host if request.client else "unknown"
            now = _time.time()
            _limits[client_ip] = [t for t in _limits[client_ip] if now - t < _WINDOW]
            if len(_limits[client_ip]) >= _RATE:
                from fastapi import status
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "请求过于频繁，请稍后重试", "retry_after": _WINDOW},
                )
            _limits[client_ip].append(now)
            return await call_next(request)

    return RateLimitMiddleware


app.add_middleware(_create_rate_limit_middleware())

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8420",
        "http://127.0.0.1:8420",
        "http://localhost:8423",
        "http://127.0.0.1:8423",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Request-ID"],
)

# ── 路由注册 ──
# 健康检查直接挂载（无版本前缀）
app.include_router(health_router)

# 工具类路由（各 router 已在自身定义 /api/* 路径前缀）
app.include_router(files_router)
app.include_router(terminal_router)
app.include_router(diff_router)
app.include_router(diff_list_router)
app.include_router(git_router)
app.include_router(search_router)
app.include_router(code_exec_router, prefix="/api/code")
app.include_router(visualize_router)

# 核心服务
app.include_router(config_router)
app.include_router(chat_router)
app.include_router(rest_router)
app.include_router(context_router)
app.include_router(extensions_router)

# AI/进化
app.include_router(browser_ai_router)

# 业务模块
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
app.include_router(scheduler_router)
app.include_router(rules_router)
app.include_router(debug_router)
app.include_router(format_router)  # 代码格式化 (Ctrl+S)
app.include_router(autonomous_router)  # 全自主开发流水线 API
app.include_router(v2_router)  # V2 API (进化/能力/健康)
app.include_router(v2_evolution_router)  # V2 进化 API (完整端点)
app.include_router(v2_evolution_ws_router)  # V2 进化 WebSocket

# Phase 2+3: 新 API 路由
app.include_router(session_search_router)
app.include_router(dep_api_router)

# WebSocket（独立挂载）
app.include_router(collab_ws_router)
app.include_router(autonomous_ws_router)

# ── Skills Market REST API ──


@app.get("/api/skills/v1")
async def list_skills(q: str = "", limit: int = 50):
    import json
    from pathlib import Path

    reg = Path(__file__).resolve().parents[2] / ".skills-registry.json"
    try:
        if reg.exists():
            raw = reg.read_text(encoding="utf-8")
            data = json.loads(raw)
            skills = data.get("skills", [])
            if q:
                skills = [s for s in skills if q.lower() in s.get("name", "").lower()]
            return {"skills": skills[:limit], "total": len(skills)}
        return {"skills": [], "total": 0, "error": "not found"}
    except (json.JSONDecodeError, OSError, ValueError) as e:
        return {"skills": [], "total": 0, "error": str(e)}


@app.websocket("/ws/chat")
async def websocket_endpoint(ws: WebSocket):
    if not await verify_ws_auth(ws):
        return
    await websocket_chat(ws)


@app.websocket("/ws/chat/v2")
async def websocket_v2_endpoint(ws: WebSocket):
    """V2 AI-Centric WebSocket 端点 — 消息流经 V2 引擎的能力总线和审计追踪"""
    if not await verify_ws_auth(ws):
        return
    await websocket_chat_v2(ws)


@app.get("/api/v2/status")
async def v2_engine_status():
    """获取 V2 引擎运行状态和能力概览"""
    engine = get_v2_engine()
    if not engine:
        return {"initialized": False, "error": "V2 engine not available"}
    return {
        "initialized": getattr(engine, "_initialized", False),
        "capabilities": engine.registry.count,
        "by_category": engine.registry.count_by_category(),
        "trust_level": engine.permission.current_trust.name,
        "consciousness_mode": (
            engine.consciousness.mode.value
            if engine.config.enable_consciousness
            else "disabled"
        ),
        "self_evo_enabled": engine.config.enable_self_evo,
        "modules_loaded": len(engine.modules._loaded) if hasattr(engine.modules, "_loaded") else 0,
    }


# ── 启动调度器 + 注册定时任务 ──────────────────────────
async def _start_scheduler():
    """应用启动时初始化调度器并注册 4 个定时同步任务。"""
    from pycoder.server.scheduler import ScheduledTask, get_scheduler

    scheduler = get_scheduler()

    # 仅当调度器尚未运行时初始化
    if scheduler.is_running:
        return

    # 注册 Skills 自动刷新（每日 09:00 和 21:00）
    scheduler.add_task(
        ScheduledTask(
            id="skills-refresh-09",
            name="Skills Market 自动刷新 (09:00)",
            trigger="cron",
            config={"cron": "0 9 * * *"},
            action="mcp:skills_sync_v2",
            action_args={},
        )
    )
    scheduler.add_task(
        ScheduledTask(
            id="skills-refresh-21",
            name="Skills Market 自动刷新 (21:00)",
            trigger="cron",
            config={"cron": "0 21 * * *"},
            action="mcp:skills_sync_v2",
            action_args={},
        )
    )

    # 注册 Extensions 自动刷新（每日 03:00 和 15:00 — 错峰）
    scheduler.add_task(
        ScheduledTask(
            id="extensions-refresh-03",
            name="Extensions 市场自动刷新 (03:00)",
            trigger="cron",
            config={"cron": "0 3 * * *"},
            action="python:pycoder.server.mcp_tools._handle_refresh_extensions",
            action_args={},
        )
    )
    scheduler.add_task(
        ScheduledTask(
            id="extensions-refresh-15",
            name="Extensions 市场自动刷新 (15:00)",
            trigger="cron",
            config={"cron": "0 15 * * *"},
            action="python:pycoder.server.mcp_tools._handle_refresh_extensions",
            action_args={},
        )
    )

    # ── V2: 注册自进化定时扫描（每日 04:00）──
    scheduler.add_task(
        ScheduledTask(
            id="self-evo-scan-daily",
            name="V2 自进化每日扫描 (04:00)",
            trigger="cron",
            config={"cron": "0 4 * * *"},
            action="python:pycoder.server.app._scheduled_self_scan",
            action_args={},
        )
    )

    await scheduler.start()
    import logging

    logging.getLogger("pycoder.server.app").info(
        "scheduler_started: 4 tasks registered (skills×2, extensions×2)"
    )


async def _scheduled_self_scan():
    """定时自扫描任务 — V2 自进化每日检查"""
    try:
        engine = get_v2_engine()
        if engine is None or engine.evolution is None:
            return
        report = await engine.evolution.scan("pycoder", use_llm=False)
        if report.total_issues > 0:
            _logger.warning(
                "self_scan_daily: found=%d critical=%d",
                report.total_issues,
                sum(1 for i in report.issues if i.severity == "critical"),
            )
        else:
            _logger.info("self_scan_daily: clean (0 issues)")
    except Exception as e:
        _logger.debug("self_scan_skip: %s", e)


async def _init_recommendation_db():
    """启动时创建推荐系统数据库表（如不存则自动创建）"""
    import logging

    try:
        # 统一使用 session_store 数据库（已存在 pycoder.db）
        import os as _os

        from sqlalchemy import create_engine

        from pycoder.server.models.behavior_models import Base

        db_path = _os.path.expanduser("~/.pycoder/pycoder.db")
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)
        engine.dispose()
        logging.getLogger("pycoder.server.app").info(
            "recommendation_db_tables_created at %s", db_path
        )
    except (OSError, ImportError) as e:
        logging.getLogger("pycoder.server.app").warning("recommendation_db_init_failed: %s", e)


__all__ = ["app", "run_server", "verify_ws_auth", "get_v2_engine"]
