"""F7 实时预览管理 — dev-server 探测 / 静态 HTML / 文件变更监听 / 自动刷新广播

功能:
    - detect_dev_server: 解析 package.json scripts 推断框架与端口，并用 socket
      探测常见 dev-server 端口（5173/3000/8080 等）是否监听
    - detect_static_html: 对纯 HTML 项目定位入口文件（index.html 等）
    - PreviewManager: 基于 watchdog 的工作区文件监听（防抖合并），文件变更后
      通过 asyncio.Queue 向 WebSocket 订阅者广播 reload 事件

Windows 兼容:
    - watchdog 在 Windows 上基于 ReadDirectoryChangesW，observer.stop() 后需 join()
      确保线程清理，避免泄漏
    - 防抖定时器使用 daemon 线程，进程退出不阻塞
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── watchdog 可选依赖（缺失时 watcher 功能降级为报错提示） ──
try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    _WATCHDOG_AVAILABLE = True
except ImportError:  # pragma: no cover - 环境缺 watchdog 时
    FileSystemEventHandler = object  # type: ignore[assignment,misc]
    Observer = None  # type: ignore[assignment]
    _WATCHDOG_AVAILABLE = False

# 常见 dev-server 端口（按命中率排序）
COMMON_DEV_PORTS: tuple[int, ...] = (5173, 3000, 8080, 8000, 4200, 5000, 4321, 1234, 9000)

# package.json scripts 关键词 → (框架名, 默认端口)
_FRAMEWORK_HINTS: dict[str, tuple[str, int]] = {
    "vite": ("vite", 5173),
    "next": ("next", 3000),
    "nuxt": ("nuxt", 3000),
    "react-scripts": ("cra", 3000),
    "astro": ("astro", 4321),
    "ng serve": ("angular", 4200),
    "webpack-dev-server": ("webpack", 8080),
    "http-server": ("static", 8080),
    "live-server": ("static", 8080),
}

# 从 scripts 文本中提取显式端口，如 "vite --port 3001" / "next dev -p 3001"
_PORT_RE = re.compile(r"(?:--port|-p)[= ]+(\d{2,5})")


def is_port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    """用 socket 探测端口是否有进程监听

    Args:
        port: 目标端口
        host: 目标主机（默认本机回环）
        timeout: 连接超时秒数（保持短小，避免探测拖慢接口）

    Returns:
        True 表示端口处于监听状态
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((host, port)) == 0
    except OSError:
        return False


@dataclass
class DevServerInfo:
    """dev-server 探测结果"""

    url: str = ""
    port: int = 0
    framework: str = "unknown"
    running: bool = False
    mode: str = "none"  # dev-server | static-html | none
    entry: str = ""  # 静态 HTML 入口（相对工作区路径）

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "port": self.port,
            "framework": self.framework,
            "running": self.running,
            "mode": self.mode,
            "entry": self.entry,
        }


def _parse_package_json(workspace: Path) -> tuple[str, int] | None:
    """解析工作区 package.json 的 scripts，推断框架与期望端口

    Returns:
        (framework, port) 或 None（无 package.json / 无法识别）
    """
    pkg_file = workspace / "package.json"
    if not pkg_file.is_file():
        return None
    try:
        data = json.loads(pkg_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.debug("package_json_parse_failed path=%s", pkg_file)
        return None

    scripts = data.get("scripts") or {}
    if not isinstance(scripts, dict):
        return None
    # 优先 dev/serve/start 脚本，其次全部 scripts
    candidates = [
        str(scripts.get(key, "")) for key in ("dev", "serve", "start", "preview") if scripts.get(key)
    ]
    candidates.extend(str(v) for v in scripts.values())
    for text in candidates:
        if not text:
            continue
        for hint, (framework, default_port) in _FRAMEWORK_HINTS.items():
            if hint in text:
                match = _PORT_RE.search(text)
                port = int(match.group(1)) if match else default_port
                return framework, port
    return None


def detect_static_html(workspace: Path) -> str | None:
    """检测纯 HTML 项目的入口文件

    按常见位置依次查找 index.html，最后回退到根目录任意 .html 文件。

    Returns:
        相对工作区的入口路径，未找到返回 None
    """
    for name in ("index.html", "public/index.html", "www/index.html", "dist/index.html"):
        if (workspace / name).is_file():
            return name
    try:
        for entry in sorted(workspace.glob("*.html")):
            if entry.is_file():
                return entry.name
    except OSError:
        logger.debug("static_html_scan_failed path=%s", workspace)
    return None


def detect_dev_server(workspace: str | Path) -> DevServerInfo:
    """探测工作区的 dev-server 状态

    流程:
        1. 解析 package.json scripts → 推断框架与期望端口
        2. socket 探测期望端口，再探测常见端口列表
        3. 无监听端口时降级检测静态 HTML 入口

    Args:
        workspace: 工作区根目录

    Returns:
        DevServerInfo（含 url/port/framework/running/mode）
    """
    ws = Path(workspace)
    expected_port: int | None = None
    framework = "unknown"

    parsed = _parse_package_json(ws)
    if parsed is not None:
        framework, expected_port = parsed

    # 1) 优先探测 package.json 指定的端口
    if expected_port is not None and is_port_open(expected_port):
        return DevServerInfo(
            url=f"http://127.0.0.1:{expected_port}",
            port=expected_port,
            framework=framework,
            running=True,
            mode="dev-server",
        )

    # 2) 扫描常见端口
    for port in COMMON_DEV_PORTS:
        if port == expected_port:
            continue
        if is_port_open(port):
            return DevServerInfo(
                url=f"http://127.0.0.1:{port}",
                port=port,
                framework=framework,
                running=True,
                mode="dev-server",
            )

    # 3) 未运行：有 package.json 则给出期望地址，否则尝试静态 HTML
    if parsed is not None:
        return DevServerInfo(
            url=f"http://127.0.0.1:{expected_port}",
            port=expected_port or 0,
            framework=framework,
            running=False,
            mode="dev-server",
        )

    entry = detect_static_html(ws)
    if entry is not None:
        return DevServerInfo(
            framework="static-html",
            running=False,
            mode="static-html",
            entry=entry,
        )
    return DevServerInfo()


class _DebouncedFsHandler(FileSystemEventHandler):  # type: ignore[misc]
    """watchdog 事件处理器 — 仅收集文件事件，交由 PreviewManager 防抖合并"""

    def __init__(self, on_event: Any) -> None:
        super().__init__()
        self._on_event = on_event

    def on_any_event(self, event: Any) -> None:
        if getattr(event, "is_directory", False):
            return
        src = getattr(event, "src_path", "")
        if src:
            self._on_event(str(src))


class PreviewManager:
    """实时预览管理器 — watcher 生命周期 + reload 事件广播

    线程模型:
        - watchdog observer 在独立线程产生事件
        - 事件经 threading.Timer 防抖合并后，通过订阅时捕获的事件循环
          `loop.call_soon_threadsafe` 投递到各 asyncio.Queue
        - stop_watcher() 负责 observer.stop()/join() 与定时器取消，不泄漏线程
    """

    def __init__(self, debounce_sec: float = 0.3) -> None:
        self._debounce_sec = debounce_sec
        self._observer: Any = None
        self._watch_path: Path | None = None
        self._subscribers: dict[asyncio.Queue[dict[str, Any]], asyncio.AbstractEventLoop] = {}
        self._timer: threading.Timer | None = None
        self._changed: list[str] = []
        self._lock = threading.Lock()
        self._reload_count = 0

    # ── 订阅管理（WebSocket 端使用） ──────────────────────────
    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """注册一个 reload 事件订阅者，返回其接收队列"""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers[queue] = asyncio.get_running_loop()
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """移除订阅者"""
        self._subscribers.pop(queue, None)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def watching(self) -> bool:
        return self._observer is not None

    @property
    def watch_path(self) -> str:
        return str(self._watch_path) if self._watch_path else ""

    @property
    def reload_count(self) -> int:
        return self._reload_count

    # ── watcher 生命周期 ──────────────────────────────────────
    def start_watcher(self, path: str | Path) -> dict[str, Any]:
        """启动工作区文件监听（重复调用先停旧 watcher）

        Args:
            path: 监听目录（通常为工作区根）

        Returns:
            {"success": bool, "watching": str, ...}
        """
        if not _WATCHDOG_AVAILABLE:
            return {"success": False, "error": "watchdog 未安装，无法监听文件变更"}

        target = Path(path).resolve()
        if not target.is_dir():
            return {"success": False, "error": f"目录不存在: {path}"}

        self.stop_watcher()

        handler = _DebouncedFsHandler(self._on_fs_event)
        observer = Observer()
        observer.schedule(handler, str(target), recursive=True)
        observer.daemon = True
        observer.start()
        self._observer = observer
        self._watch_path = target
        logger.info("preview_watcher_started path=%s", target)
        return {"success": True, "watching": str(target)}

    def stop_watcher(self) -> dict[str, Any]:
        """停止监听并清理线程资源（幂等）"""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._changed.clear()

        was_watching = self._observer is not None
        if self._observer is not None:
            observer, self._observer = self._observer, None
            try:
                observer.stop()
                observer.join(timeout=5)
            except (RuntimeError, OSError) as e:
                logger.debug("preview_watcher_stop_error: %s", e)
        self._watch_path = None
        if was_watching:
            logger.info("preview_watcher_stopped")
        return {"success": True, "stopped": was_watching}

    # ── 事件防抖与广播 ────────────────────────────────────────
    def _on_fs_event(self, src_path: str) -> None:
        """watchdog 线程回调：累积变更并重启防抖定时器"""
        with self._lock:
            self._changed.append(src_path)
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce_sec, self._flush_changes)
            self._timer.daemon = True
            self._timer.start()

    def _flush_changes(self) -> None:
        """防抖窗口结束：合并变更并广播 reload"""
        with self._lock:
            changed, self._changed = self._changed, []
            self._timer = None
        if changed:
            self._notify_reload(changed)

    def _notify_reload(self, changed: list[str]) -> None:
        """向所有订阅者广播 reload 事件（线程安全）

        从 watchdog/Timer 线程调用，经各订阅者所属事件循环投递。
        """
        self._reload_count += 1
        msg: dict[str, Any] = {
            "type": "reload",
            "changed": sorted(set(changed))[-20:],  # 最多带 20 个路径，避免消息膨胀
            "count": self._reload_count,
            "ts": time.time(),
        }
        for queue, loop in list(self._subscribers.items()):
            try:
                loop.call_soon_threadsafe(self._safe_put, queue, msg)
            except RuntimeError:
                # 事件循环已关闭：移除失效订阅
                self._subscribers.pop(queue, None)

    @staticmethod
    def _safe_put(queue: asyncio.Queue[dict[str, Any]], msg: dict[str, Any]) -> None:
        """队列满时丢弃最旧消息，保证 reload 事件不阻塞"""
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(msg)

    def status(self) -> dict[str, Any]:
        """当前预览管理器状态"""
        return {
            "watching": self.watching,
            "path": self.watch_path,
            "subscribers": self.subscriber_count,
            "reload_count": self._reload_count,
            "watchdog_available": _WATCHDOG_AVAILABLE,
        }


# ── 单例 ──────────────────────────────────────────────────
_manager: PreviewManager | None = None


def get_preview_manager() -> PreviewManager:
    """获取全局 PreviewManager 单例"""
    global _manager
    if _manager is None:
        _manager = PreviewManager()
    return _manager
