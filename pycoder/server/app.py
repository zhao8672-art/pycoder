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
from pycoder.server.router_groups import register_router_groups
from pycoder.server.ws_handler import websocket_chat
from pycoder.server.ws_handler_v2 import websocket_chat_v2

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


# ── 启动时检测 LLM API Key，无则打印引导 ─────────────────
def _check_llm_keys_on_startup():
    """检查是否有任意 LLM API Key 已配置，无则打印引导。"""
    try:
        from pycoder.providers.auth import ModelManager

        mm = ModelManager()
        detected = mm.auto_detect()
        if detected:
            providers = ", ".join(detected.keys())
            _logger.info("llm_api_keys_detected: %s", providers)
            return

        _logger.warning(
            "\n"
            "╔══════════════════════════════════════════════════════╗\n"
            "║  ⚠️  未检测到任何 AI 模型 API Key                  ║\n"
            "║  请配置至少一个提供商才能使用 AI 功能               ║\n"
            "║                                                    ║\n"
            "║  快速开始 — 设置环境变量:                          ║\n"
            "║    set DEEPSEEK_API_KEY=sk-xxx                     ║\n"
            "║                                                    ║\n"
            "║  或打开 Settings 面板 → API Key 管理                ║\n"
            "║                                                    ║\n"
            "║  免费获取 Key:                                     ║\n"
            "║    https://platform.deepseek.com/api_keys          ║\n"
            "╚══════════════════════════════════════════════════════╝"
        )
    except (ImportError, RuntimeError, OSError) as e:
        _logger.debug("llm_key_check_skipped: %s", e)


# 在模块加载时执行检测
_check_llm_keys_on_startup()


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
        if (
            path == "/api/health"
            or path.startswith("/api/health/")
            or path in ("/docs", "/openapi.json")
            or path.startswith("/ws/")
        ):
            return await call_next(request)

        # 允许 file:// 来源的请求免认证（VSCode 内置浏览器 / Electron 开发模式）
        origin = request.headers.get("Origin", "")
        if origin.startswith("file://"):
            return await call_next(request)

        # BUG-003/004 修复：缺少 Origin 头时（如 curl/server-to-server 调用）
        # 必须强制验证 API Key，不能再以"无 Origin"为由放行
        api_key = request.headers.get("X-API-Key", "")
        if not api_key:
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=401,
                content={"detail": "Missing API key"},
                headers={"WWW-Authenticate": "X-API-Key"},
            )

        if not _secrets.compare_digest(api_key, _API_KEY):
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid API key"},
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
    # 阶段 0 架构升级：显式触发 subprocess 兼容补丁
    # （从 pycoder/__init__.py 的导入期副作用拆出，延迟到此处执行）
    try:
        from pycoder import _install_subprocess_compat

        _install_subprocess_compat()
    except ImportError:
        pass

    await _init_recommendation_db()
    _init_di_container()

    # ── 环境工具检测 ──
    _check_environment_tools()

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


def _check_environment_tools() -> None:
    """启动时检测环境工具（Docker, Git, Node 等），记录缺失或版本问题。

    仅记录日志，不阻塞启动。缺失的可选工具不会导致启动失败。
    """
    try:
        from pycoder.env.auto_installer import AutoInstaller
        from pycoder.env.tool_detector import ToolDetector

        detector = ToolDetector()
        report = detector.get_report()

        if report["all_ok"]:
            _logger.info("env_tools_check: 所有必需工具已就绪")
            return

        for tool in report["required_missing"]:
            _logger.warning(
                "env_tool_missing: name=%s, required=True, error=%s", tool.name, tool.error
            )

        for tool in report["version_issues"]:
            _logger.warning("env_tool_version_low: name=%s, version=%s", tool.name, tool.version)

        for tool in report["optional_missing"]:
            _logger.info("env_tool_optional_missing: name=%s", tool.name)

        # 生成安装指南并记录
        installer = AutoInstaller(detector)
        if report["required_missing"]:
            guide = installer.get_all_missing_guides()
            _logger.info("env_tool_install_guide:\n%s", guide)
    except Exception as e:
        _logger.warning("env_tools_check_failed: %s", e)


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
        from pycoder.bus.protocol import TrustLevel
        from pycoder.v2 import V2Engine, V2EngineConfig

        config = V2EngineConfig(
            workspace_root=os.getcwd(),
            initial_trust=TrustLevel.FULL_AUTONOMY,
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
        # 同时写入模块级变量，确保 get_v2_engine 可靠返回
        _set_v2_engine(engine)
        return engine
    except ImportError as e:
        _logger.warning("v2_engine_skip: import_failed=%s", e)
        return None
    except Exception as e:
        _logger.error("v2_engine_init_failed: %s", e)
        return None


# ── V2 引擎模块级单例（可靠获取方式）──
_v2_engine_instance = None


def _set_v2_engine(engine):
    global _v2_engine_instance
    _v2_engine_instance = engine


def get_v2_engine(app: FastAPI | None = None):
    """获取 V2 引擎实例

    优先级:
        1. 传入的 app.state.v2_engine
        2. 模块级 app.state.v2_engine
        3. 模块级 _v2_engine_instance 单例
    """
    if app is not None:
        return getattr(app.state, "v2_engine", None)
    try:
        engine = getattr(app.state, "v2_engine", None)
        if engine is not None:
            return engine
    except (AttributeError, NameError):
        pass
    return _v2_engine_instance


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

# ── 阶段 2 架构升级：统一错误处理中间件 ──
# 必须在最外层（add_middleware 后注册的最后执行最早）
from pycoder.server.middleware import (  # noqa: E402
    ErrorHandlingMiddleware,
    ETagCacheMiddleware,
    PerformanceMonitoringMiddleware,
    RateLimitMiddleware,
    RequestBodyScannerMiddleware,
    SecurityHeadersMiddleware,
)

# 中间件注册顺序（从外到内执行）：
# 1. ErrorHandling — 捕获所有未处理异常
# 2. SecurityHeaders — 添加 CSP/X-Frame-Options 等安全头
# 3. PerformanceMonitoring — 慢请求检测
# 4. ETagCache — 缓存优化
# 5. RateLimit — 速率限制（防止滥用）
# 6. RequestBodyScanner — 请求体 shell 注入扫描
# 7. APIKeyMiddleware — API 认证
# 8. CORSMiddleware — CORS 处理
app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(PerformanceMonitoringMiddleware)
app.add_middleware(ETagCacheMiddleware)
app.add_middleware(RateLimitMiddleware)  # BUG-008 修复：替换原简单限流
app.add_middleware(RequestBodyScannerMiddleware)  # BUG-005 修复

# 始终注册 API 认证中间件（内部根据 _API_KEY 是否为空决定是否生效）
app.add_middleware(APIKeyMiddleware)

app.add_middleware(
    CORSMiddleware,
    # BUG-010 修复：添加通配 regex 支持任意 127.0.0.1 / localhost 端口
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_origins=[
        "http://localhost:8420",
        "http://127.0.0.1:8420",
        "http://localhost:8423",
        "http://127.0.0.1:8423",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "app://.",  # Electron file:// schema
        "file://",
    ],
    allow_credentials=True,
    # BUG-009 修复：显式添加 HEAD/OPTIONS/PATCH 支持
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-API-Key",
        "X-Request-ID",
        "Accept",
        "Accept-Language",
        "Content-Language",
        "X-Requested-With",
    ],
    expose_headers=[
        "X-Request-ID",
        "X-Response-Time",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
        "ETag",
        "Cache-Control",
    ],
    max_age=600,  # 浏览器缓存预检结果 10 分钟
)

# ── 路由注册（阶段 1 架构升级：61 处 include_router 收敛为 1 处）──
# 详见 pycoder.server.router_groups
register_router_groups(app)

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
            engine.consciousness.mode.value if engine.config.enable_consciousness else "disabled"
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

    # ── V2: 注册自进化自动修复（每 6 小时）──
    scheduler.add_task(
        ScheduledTask(
            id="self-evo-auto-fix",
            name="V2 自进化自动修复 (每6小时)",
            trigger="cron",
            config={"cron": "0 */6 * * *"},
            action="python:pycoder.server.app._scheduled_evolution_run",
            action_args={},
        )
    )

    # ── Memory 自动清理（每日 03:30）──
    scheduler.add_task(
        ScheduledTask(
            id="memory-auto-cleanup",
            name="Memory 自动清理 (03:30)",
            trigger="cron",
            config={"cron": "30 3 * * *"},
            action="python:pycoder.server.app._scheduled_memory_cleanup",
            action_args={},
        )
    )

    # ── Security 自动扫描（每日 02:00）──
    scheduler.add_task(
        ScheduledTask(
            id="security-auto-scan",
            name="Security 自动扫描 (02:00)",
            trigger="cron",
            config={"cron": "0 2 * * *"},
            action="python:pycoder.server.app._scheduled_security_scan",
            action_args={},
        )
    )

    # ── Skills 健康检查（每 12 小时）──
    scheduler.add_task(
        ScheduledTask(
            id="skills-health-check",
            name="Skills 健康检查 (每12小时)",
            trigger="cron",
            config={"cron": "0 */12 * * *"},
            action="python:pycoder.server.app._scheduled_skills_health_check",
            action_args={},
        )
    )

    await scheduler.start()
    import logging

    logging.getLogger("pycoder.server.app").info(
        "scheduler_started: 9 tasks registered (skills×2, extensions×2, evo-scan, evo-fix, memory-cleanup, security-scan, skills-health)"
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


async def _scheduled_evolution_run():
    """定时自进化修复 — 每 6 小时自动运行进化闭环"""
    try:
        engine = get_v2_engine()
        if engine is None or engine.evolution is None:
            _logger.warning("evolution_run_skip: engine not available")
            return
        result = await engine.evolution.run(dry_run=False)
        _logger.info(
            "evolution_auto_fix: fixed=%d skipped=%d errors=%d",
            result.get("fixed", 0),
            result.get("skipped", 0),
            result.get("errors", 0),
        )
    except Exception as e:
        _logger.debug("evolution_auto_fix_skip: %s", e)


async def _scheduled_memory_cleanup():
    """定时 Memory 清理 — 每天清理过期会话"""
    try:
        from pycoder.memory.persistent_memory import PersistentMemoryStore

        store = PersistentMemoryStore()
        cleaned = await store.cleanup_expired(max_age_days=30)
        _logger.info("memory_cleanup: cleaned=%d sessions", cleaned)
    except Exception as e:
        _logger.debug("memory_cleanup_skip: %s", e)


async def _scheduled_security_scan():
    """定时 Security 扫描 — 每天自动安全扫描"""
    try:
        from pycoder.python.security_scanner import SecurityScanner

        scanner = SecurityScanner()
        report = await scanner.scan_project(".")
        issues = report.get("issues", [])
        if issues:
            _logger.warning("security_scan: found=%d issues", len(issues))
        else:
            _logger.info("security_scan: clean")
    except Exception as e:
        _logger.debug("security_scan_skip: %s", e)


async def _scheduled_skills_health_check():
    """定时 Skills 健康检查 — 检查已安装技能状态"""
    try:
        from pycoder.skills import get_marketplace

        marketplace = get_marketplace()
        installed = marketplace.get_installed_skills()
        _logger.info("skills_health: installed=%d skills", len(installed))
    except Exception as e:
        _logger.debug("skills_health_skip: %s", e)


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
