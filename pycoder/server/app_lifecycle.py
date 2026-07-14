"""Application lifecycle: startup, shutdown, health check, run_server."""

from __future__ import annotations

import os  # ← 新增导入
import time

from pycoder import __version__

_server_start = time.time()


def get_uptime() -> float:
    """Return server uptime in seconds."""
    return time.time() - _server_start


def get_health_info(python_version: str) -> dict:
    """Return health check payload."""
    return {
        "status": "ok",
        "version": __version__,
        "python": python_version,
        "server_uptime_seconds": round(get_uptime(), 1),
        "pid": os.getpid(),  # 现在 os 已定义
    }


def run_server(host: str = "127.0.0.1", port: int = 8423, reload: bool = False):
    """Start the FastAPI server via uvicorn."""
    # ── 启动时断点续传检测 ──
    _check_upgrade_on_startup()

    import uvicorn

    uvicorn.run(
        "pycoder.server.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


def _check_upgrade_on_startup() -> None:
    """启动时检测是否有未完成的升级任务，自动恢复或回滚。"""
    try:
        from pycoder.server.auto_upgrade import check_pending_on_startup

        result = check_pending_on_startup()
        if result:
            status = result.get("status", "")
            if status == "failed":
                print("   ⚠️ 升级恢复失败，继续以当前版本启动...")
            elif status == "resumed_and_completed":
                print("   ✅ 升级已恢复并完成！")
    except Exception as e:
        # 静默失败——升级检测不应阻止启动
        print(f"   ⚠️ 升级检测跳过: {e}")
