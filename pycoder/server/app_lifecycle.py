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


def run_server(host: str = "127.0.0.1", port: int = 8423, reload: bool = False, quick_start: bool = False):
    """Start the FastAPI server via uvicorn.

    Args:
        host: 绑定地址
        port: 端口
        reload: 是否开启热重载
        quick_start: 快速启动模式，跳过非必要初始化（V2引擎、环境检测等）
    """
    # 将 quick_start 标志注入环境变量，供 lifespan 读取
    if quick_start:
        os.environ["PYCODER_QUICK_START"] = "1"
        print("   ⚡ 快速启动模式：跳过 V2 引擎、环境工具检测等非必要初始化")

    # ── 启动时断点续传检测 ──
    if not quick_start:
        _check_upgrade_on_startup()

    import uvicorn

    # BUG-007 修复：限制 Header 大小，防止大 header 攻击
    # 单个 header 最大 8KB，总 header 限制 64KB
    uvicorn.run(
        "pycoder.server.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
        # h11 协议层限制（uvicorn 基于 h11）
        h11_max_incomplete_event_size=64 * 1024,  # 64KB
        # 限制请求体大小（防止大 payload DoS）
        limit_max_requests=10000,  # 单进程最大请求数（触发优雅重启）
        timeout_keep_alive=30,
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
