"""
扩展主机 — 隔离执行扩展代码

功能类似 VS Code 的 Extension Host 进程:
  - 在独立进程中加载扩展
  - 提供受限的 Extension API
  - 管理扩展生命周期（激活/停用）
  - 事件/激活条件系统

扩展不直接与 PyCoder 交互，而是通过 ExtensionAPI 桥接。
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import logging
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── 扩展目录 ──

EXTENSIONS_DIR = Path.home() / ".pycoder" / "extensions"

# ── 扩展 API 版本 ──

EXTENSION_API_VERSION = "1.0.0"

# ──────────────────────────────────────────────
# ExtensionAPI — 供给扩展使用的沙箱 API
# ──────────────────────────────────────────────


class ExtensionAPI:
    """
    扩展 API — 扩展可以使用的受限能力集合。

    扩展通过 `__extension_api__` 全局变量访问此 API。
    类似 VS Code 的 `vscode` 模块。
    """

    def __init__(self, ext_id: str, manifest: dict):
        self._ext_id = ext_id
        self._manifest = manifest
        self._subscriptions: list[Callable] = []
        self._context: dict = {}

    # ── 基础信息 ──

    @property
    def id(self) -> str:
        return self._ext_id

    @property
    def version(self) -> str:
        return self._manifest.get("version", "0.0.0")

    @property
    def extension_path(self) -> str:
        """扩展在磁盘上的路径"""
        p = EXTENSIONS_DIR / self._ext_id.replace("/", "_")
        return str(p)

    # ── 上下文存储 ──

    def set_context(self, key: str, value: Any) -> None:
        self._context[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        return self._context.get(key, default)

    # ── 订阅（清理用） ──

    def subscribe(self, callback: Callable) -> None:
        """注册一个在扩展停用时清理的回调"""
        self._subscriptions.append(callback)

    def dispose(self) -> None:
        """停用扩展 — 调用所有清理回调"""
        for cb in self._subscriptions:
            try:
                cb()
            except Exception as e:
                logger.debug("extension_dispose_callback_failed ext=%s error=%s", self._ext_id, e)
        self._subscriptions.clear()

    # ── 日志 ──

    def log(self, level: str, msg: str) -> None:
        level = level.upper()
        log_fn = getattr(logger, level.lower(), logger.info)
        log_fn("[%s] %s", self._ext_id, msg)

    def info(self, msg: str) -> None:
        logger.info("[%s] %s", self._ext_id, msg)

    def warn(self, msg: str) -> None:
        logger.warning("[%s] %s", self._ext_id, msg)

    def error(self, msg: str) -> None:
        logger.error("[%s] %s", self._ext_id, msg)

    # ── 文件系统（沙箱内） ──

    def read_file(self, rel_path: str) -> str | None:
        """读取扩展包内的文件"""
        full = Path(self.extension_path) / rel_path
        if full.exists() and full.is_relative_to(self.extension_path):
            try:
                return full.read_text(encoding="utf-8")
            except OSError as e:
                logger.warning(
                    "extension_read_file_error ext=%s path=%s error=%s", self._ext_id, rel_path, e
                )
                return None
        return None

    def list_files(self, rel_path: str = "") -> list[str]:
        """列出扩展包内的文件"""
        full = Path(self.extension_path) / rel_path
        if full.exists() and full.is_relative_to(self.extension_path):
            return [str(p.relative_to(self.extension_path)) for p in full.rglob("*") if p.is_file()]
        return []


# ──────────────────────────────────────────────
# 扩展沙箱 — 在隔离环境中加载扩展
# ──────────────────────────────────────────────


class ExtensionSandbox:
    """
    扩展沙箱 — 加载、激活、执行扩展代码。

    不使用子进程（当前设计），但提供函数级隔离：
      1. 每次执行通过 importlib 重新加载模块（避免状态污染）
      2. 注入受限的 ExtensionAPI
      3. 超时保护（默认 30s）
      4. 所有异常被捕获并包装
    """

    def __init__(self, ext_id: str):
        self.ext_id = ext_id
        self._ext_path = EXTENSIONS_DIR / ext_id.replace("/", "_")
        self._manifest: dict = {}
        self._module = None
        self._api: ExtensionAPI | None = None
        self._execution_lock = asyncio.Lock()

    @property
    def manifest_path(self) -> Path:
        return self._ext_path / "manifest.json"

    @property
    def code_path(self) -> Path:
        return self._ext_path / "extension.py"

    def is_installed(self) -> bool:
        return self._ext_path.exists() and self.code_path.exists()

    def load_manifest(self) -> dict | None:
        """加载扩展的 manifest.json"""
        if not self.manifest_path.exists():
            return None
        try:
            self._manifest = json.loads(
                self.manifest_path.read_text(encoding="utf-8"),
            )
            return self._manifest
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("extension_manifest_load_error ext=%s error=%s", self.ext_id, e)
            return None

    async def activate(self) -> bool:
        """
        激活扩展 — 加载模块并注入 ExtensionAPI。

        扩展中的 `activate(api)` 函数将在加载后被调用（支持 async）。
        """
        if not self.is_installed():
            logger.warning("extension_not_installed ext=%s", self.ext_id)
            return False

        manifest = self.load_manifest()
        if not manifest:
            return False

        # 创建 API 实例
        self._api = ExtensionAPI(self.ext_id, manifest)

        try:
            # 动态加载模块
            spec = importlib.util.spec_from_file_location(
                f"_ext_{self.ext_id.replace('.', '_')}",
                str(self.code_path),
            )
            if not spec or not spec.loader:
                logger.error("extension_spec_load_failed ext=%s", self.ext_id)
                return False

            mod = importlib.util.module_from_spec(spec)
            self._module = mod

            # 注入 ExtensionAPI
            mod.__extension_api__ = self._api

            spec.loader.exec_module(mod)

            # 如果扩展有 activate 函数，调用之（支持 async）
            if hasattr(mod, "activate") and callable(mod.activate):
                try:
                    result = mod.activate(self._api)
                    if inspect.iscoroutine(result):
                        await result
                except Exception as e:
                    logger.warning("extension_activate_error ext=%s error=%s", self.ext_id, e)
                    return False

            logger.info("extension_activated ext=%s", self.ext_id)
            return True

        except Exception as e:
            logger.error(
                "extension_load_error ext=%s error=%s trace=%s",
                self.ext_id,
                e,
                traceback.format_exc(),
            )
            return False

    def deactivate(self) -> bool:
        """
        停用扩展 — 清理资源。
        扩展中的 `deactivate()` 函数将被调用。
        """
        if self._api:
            self._api.dispose()

        if self._module and hasattr(self._module, "deactivate"):
            try:
                self._module.deactivate()
            except Exception as e:
                logger.warning("extension_deactivate_error ext=%s error=%s", self.ext_id, e)

        self._module = None
        self._api = None
        logger.info("extension_deactivated ext=%s", self.ext_id)
        return True

    async def execute_function(
        self,
        func_name: str,
        args: dict | None = None,
        timeout: float = 30.0,
    ) -> dict:
        """
        执行扩展中的函数（带超时保护）。

        返回:
            {"success": True, "result": ...}  或
            {"success": False, "error": ...}
        """
        if not self._module:
            activate_ok = await self.activate()
            if not activate_ok:
                return {"success": False, "error": "激活扩展失败"}

        async with self._execution_lock:
            try:
                func = getattr(self._module, func_name, None)
                if func is None:
                    available = [
                        n
                        for n in dir(self._module)
                        if not n.startswith("_")
                        and n not in ("activate", "deactivate", "__extension_api__")
                    ]
                    return {
                        "success": False,
                        "error": f"函数 '{func_name}' 不存在",
                        "available_functions": available,
                    }

                # 不可调用的属性直接返回值
                if not callable(func):
                    return {"success": True, "result": str(func)}

                # 执行（支持 sync 和 async）
                if inspect.iscoroutinefunction(func):
                    result = await asyncio.wait_for(
                        func(**(args or {})),
                        timeout=timeout,
                    )
                else:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(func, **(args or {})),
                        timeout=timeout,
                    )

                return {"success": True, "result": result}

            except TimeoutError:
                return {"success": False, "error": f"执行超时 ({timeout}s)"}
            except Exception as e:
                return {"success": False, "error": str(e), "trace": traceback.format_exc()}

    def get_available_functions(self) -> list[str]:
        """获取扩展的所有公开函数"""
        if not self._module:
            return []
        return [
            n
            for n in dir(self._module)
            if not n.startswith("_")
            and n not in ("activate", "deactivate", "__extension_api__")
            and callable(getattr(self._module, n))
        ]


# ──────────────────────────────────────────────
# 扩展主机管理器
# ──────────────────────────────────────────────


class ExtensionHostManager:
    """
    扩展主机管理器 — 管理所有已安装扩展的沙箱生命周期。

    类似 VS Code 的 Extension Host 进程管理器：
      - 启动时激活所有启用的扩展
      - 按依赖顺序激活
      - 管理每个扩展的沙箱
      - 事件广播（未来：extension.onDidActivate 等）
    """

    def __init__(self):
        self._sandboxes: dict[str, ExtensionSandbox] = {}
        self._activated: set[str] = set()
        self._load_order: list[str] = []
        self._import_hook_installed = False

    # ── 生命周期 ──

    async def activate_extension(self, ext_id: str) -> bool:
        """激活单个扩展（async）"""
        if ext_id in self._activated:
            return True

        sandbox = self._sandboxes.get(ext_id)
        if not sandbox:
            sandbox = ExtensionSandbox(ext_id)
            self._sandboxes[ext_id] = sandbox

        ok = await sandbox.activate()
        if ok:
            self._activated.add(ext_id)
        return ok

    def deactivate_extension(self, ext_id: str) -> bool:
        """停用单个扩展"""
        sandbox = self._sandboxes.get(ext_id)
        if not sandbox:
            return False
        ok = sandbox.deactivate()
        self._activated.discard(ext_id)
        return ok

    async def activate_all(self, installed_exts: list[dict]) -> dict[str, bool]:
        """
        激活所有已启用的扩展（async）。

        返回: {ext_id: success}
        """
        results = {}
        enabled = [e for e in installed_exts if e.get("enabled", True)]
        for ext in enabled:
            ext_id = ext.get("id", "")
            if not ext_id:
                continue
            results[ext_id] = await self.activate_extension(ext_id)

        self._load_order = list(results.keys())
        return results

    def deactivate_all(self) -> dict[str, bool]:
        """停用所有扩展"""
        results = {}
        for ext_id in list(self._activated):
            results[ext_id] = self.deactivate_extension(ext_id)
        return results

    async def reload_extension(self, ext_id: str) -> bool:
        """重新加载扩展（停用后重新激活，async）"""
        self.deactivate_extension(ext_id)
        return await self.activate_extension(ext_id)

    # ── 执行 ──

    async def execute(
        self,
        ext_id: str,
        func_name: str,
        args: dict | None = None,
        timeout: float = 30.0,
    ) -> dict:
        """在扩展沙箱中执行函数"""
        sandbox = self._sandboxes.get(ext_id)
        if not sandbox:
            return {"success": False, "error": f"扩展未激活: {ext_id}"}
        return await sandbox.execute_function(func_name, args, timeout)

    def get_sandbox(self, ext_id: str) -> ExtensionSandbox | None:
        return self._sandboxes.get(ext_id)

    # ── 查询 ──

    def is_activated(self, ext_id: str) -> bool:
        return ext_id in self._activated

    def list_activated(self) -> list[str]:
        return list(self._activated)

    def count_activated(self) -> int:
        return len(self._activated)


# ── 全局单例 ──

_host_manager = ExtensionHostManager()


def get_extension_host() -> ExtensionHostManager:
    return _host_manager
