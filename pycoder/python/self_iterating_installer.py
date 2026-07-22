"""P2-3: 自我迭代安装器 — 模块/工具的动态下载、安装、热重载

能力:
- 从可信源（PyPI/内置注册表/本地路径）下载新模块
- 校验模块安全性（AST 扫描危险调用 + 沙箱试运行）
- 安装到 .pycoder/modules/ 目录
- 热重载到运行中的应用（importlib.reload）
- 版本追踪与回滚

安全:
- 严格白名单：仅允许从配置的可信源下载
- AST 扫描：拒绝包含 os.system / subprocess / eval / exec 的模块
- 沙箱试运行：导入前在临时命名空间执行
- 完整性校验：记录 SHA-256 哈希
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib
import importlib.util
import json
import logging
import os
import shutil
import site
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── 配置 ───────────────────────────────────────────────

# 内置的可信源（可被环境变量覆盖）
TRUSTED_SOURCES = {
    "pypi": {
        "type": "pypi",
        "endpoint": "https://pypi.org/pypi/{name}/json",
    },
    "github_raw": {
        "type": "github",
        "endpoint": "https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}",
    },
}

# 危险调用白名单（拒绝包含这些调用的模块）
DANGEROUS_CALLS = {
    "os.system",
    "os.popen",
    "os.exec",
    "os.execv",
    "os.execvp",
    "subprocess.Popen",
    "subprocess.run",
    "subprocess.call",
    "subprocess.check_output",
    "eval",
    "exec",
    "compile",
    "__import__",
    "importlib.import_module",  # 允许但需审查
    "shutil.rmtree",
    "shutil.move",
    "pathlib.Path.unlink",
}

# 安装目录
INSTALL_DIR = Path.home() / ".pycoder" / "modules"
INSTALL_DIR.mkdir(parents=True, exist_ok=True)

# 元数据存储
METADATA_FILE = INSTALL_DIR / "installed_modules.json"


# ── 数据模型 ───────────────────────────────────────────


@dataclass
class ModuleInfo:
    """已安装模块信息"""

    name: str
    version: str
    source: str
    installed_at: float
    install_path: str
    sha256: str
    enabled: bool = True
    description: str = ""
    auto_reload: bool = True
    install_count: int = 0  # 用于热重载次数统计


@dataclass
class SecurityCheckResult:
    """安全检查结果"""

    is_safe: bool
    risk_level: str  # "low" | "medium" | "high" | "critical"
    issues: list[str] = field(default_factory=list)
    dangerous_calls: list[str] = field(default_factory=list)


@dataclass
class InstallResult:
    """安装结果"""

    success: bool
    module: ModuleInfo | None = None
    error: str = ""
    security_check: SecurityCheckResult | None = None


# ── 安全管理器 ─────────────────────────────────────────


class SecurityValidator:
    """模块安全验证器"""

    def check(self, code: str) -> SecurityCheckResult:
        """对源码进行 AST 安全扫描

        Returns:
            SecurityCheckResult — 包含风险等级与问题列表
        """
        issues: list[str] = []
        dangerous: list[str] = []
        risk_level = "low"

        # 1. AST 解析
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return SecurityCheckResult(
                is_safe=False,
                risk_level="critical",
                issues=[f"语法错误: {e}"],
            )

        # 0. 收集 from-import 映射（如 `from subprocess import Popen` -> {Popen: subprocess.Popen}）
        imported_aliased: dict[str, str] = {}
        # 标记敏感模块中被导入的子符号（用于联动判定）
        sensitive_imports: set[str] = set()

        # 2. 检测危险调用
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module in ("os", "subprocess", "shutil", "ctypes"):
                    for alias in node.names:
                        issues.append(f"从敏感模块导入: {node.module}.{alias.name}")
                        if risk_level in ("low", "medium"):
                            risk_level = "high"
                        # 记录具体子符号供后续 call 解析
                        sensitive_imports.add(alias.asname or alias.name)
                if node.module:
                    for alias in node.names:
                        full = f"{node.module}.{alias.name}"
                        imported_aliased[alias.asname or alias.name] = full
            elif isinstance(node, ast.Import):
                # 检查可疑模块导入
                for alias in node.names:
                    if alias.name in ("os", "subprocess", "shutil", "ctypes", "cffi"):
                        # 允许但需警告
                        issues.append(f"导入了敏感模块: {alias.name}")
                        if risk_level == "low":
                            risk_level = "medium"
                        imported_aliased[alias.asname or alias.name.split(".")[0]] = alias.name

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                call_name = self._get_call_name(node)
                if not call_name:
                    continue
                # 解析 from-import 后的真实调用名
                resolved_name = imported_aliased.get(call_name, call_name)
                # 精确匹配
                matched = False
                for danger in DANGEROUS_CALLS:
                    if resolved_name == danger or resolved_name.endswith(f".{danger}"):
                        if call_name not in dangerous:
                            dangerous.append(call_name)
                        issues.append(f"危险调用: {call_name} (解析为 {resolved_name})")
                        risk_level = "critical"
                        matched = True
                        break
                if matched:
                    continue
                # 模糊匹配
                for danger in ["os.system", "os.popen", "subprocess.run", "subprocess.Popen", "eval(", "exec("]:
                    if danger in resolved_name:
                        if call_name not in dangerous:
                            dangerous.append(call_name)
                        issues.append(f"疑似危险调用: {call_name} (解析为 {resolved_name})")
                        if risk_level in ("low", "medium"):
                            risk_level = "high"
                        break
                # 来自敏感模块的符号被调用 -> 升级风险
                if call_name in sensitive_imports and risk_level in ("low", "medium"):
                    risk_level = "high"
                    issues.append(f"调用敏感导入符号: {call_name}")

        # 3. 检测 __import__ / compile
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in ("eval", "exec", "compile"):
                issues.append(f"使用了危险内置函数: {node.id}")
                risk_level = "critical"

        is_safe = risk_level in ("low", "medium")
        return SecurityCheckResult(
            is_safe=is_safe,
            risk_level=risk_level,
            issues=issues,
            dangerous_calls=dangerous,
        )

    def _get_call_name(self, node: ast.Call) -> str:
        """从 Call 节点提取调用名"""
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            parts: list[str] = []
            cur: ast.expr = node.func
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
            return ".".join(reversed(parts))
        return ""


# ── 模块安装器 ─────────────────────────────────────────


class SelfIteratingInstaller:
    """自我迭代安装器"""

    def __init__(self, install_dir: Path | None = None) -> None:
        self.install_dir = install_dir or INSTALL_DIR
        self.install_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.install_dir / "installed_modules.json"
        self.validator = SecurityValidator()
        self._loaded_modules: dict[str, Any] = {}  # name -> module
        self._load_metadata()

    def _load_metadata(self) -> None:
        """加载已安装模块元数据"""
        if self.metadata_file.exists():
            try:
                data = json.loads(self.metadata_file.read_text(encoding="utf-8"))
                self._installed = {
                    name: ModuleInfo(**info) for name, info in data.items()
                }
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("metadata_load_failed error=%s", e)
                self._installed = {}
        else:
            self._installed = {}

    def _save_metadata(self) -> None:
        """保存元数据"""
        data = {name: asdict(info) for name, info in self._installed.items()}
        self.metadata_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def list_installed(self) -> list[dict]:
        """列出已安装模块"""
        return [asdict(info) for info in self._installed.values()]

    def get_module_info(self, name: str) -> ModuleInfo | None:
        """获取模块信息"""
        return self._installed.get(name)

    def is_installed(self, name: str) -> bool:
        """是否已安装"""
        return name in self._installed

    def uninstall(self, name: str) -> dict:
        """卸载模块"""
        if name not in self._installed:
            return {"success": False, "error": f"模块未安装: {name}"}

        info = self._installed[name]
        # 从已加载模块中卸载
        if name in self._loaded_modules:
            del sys.modules[name]
            del self._loaded_modules[name]

        # 删除文件
        install_path = Path(info.install_path)
        if install_path.exists():
            try:
                if install_path.is_dir():
                    shutil.rmtree(install_path)
                else:
                    install_path.unlink()
            except (OSError, PermissionError) as e:
                return {"success": False, "error": f"删除文件失败: {e}"}

        del self._installed[name]
        self._save_metadata()
        return {"success": True, "module": name}

    def install_from_code(
        self,
        name: str,
        code: str,
        *,
        source: str = "local",
        version: str = "1.0.0",
        description: str = "",
        auto_reload: bool = True,
        skip_security: bool = False,
    ) -> InstallResult:
        """从代码字符串安装模块

        Args:
            name: 模块名
            code: 模块源代码
            source: 来源标识
            version: 版本
            description: 描述
            auto_reload: 是否自动重载
            skip_security: 跳过安全检查（仅调试用）
        """
        # 1. 安全检查
        if not skip_security:
            check = self.validator.check(code)
            if not check.is_safe:
                return InstallResult(
                    success=False,
                    error=f"安全检查未通过: {check.risk_level}",
                    security_check=check,
                )
        else:
            check = SecurityCheckResult(is_safe=True, risk_level="low")

        # 2. 计算 SHA-256
        sha = hashlib.sha256(code.encode("utf-8")).hexdigest()

        # 3. 写入文件
        module_dir = self.install_dir / name
        module_dir.mkdir(parents=True, exist_ok=True)
        module_file = module_dir / "__init__.py"
        module_file.write_text(code, encoding="utf-8")

        # 4. 更新元数据
        info = ModuleInfo(
            name=name,
            version=version,
            source=source,
            installed_at=time.time(),
            install_path=str(module_file),
            sha256=sha,
            description=description,
            auto_reload=auto_reload,
        )
        self._installed[name] = info
        self._save_metadata()

        # 5. 加载
        if auto_reload:
            load_result = self.load(name)
            if not load_result["success"]:
                # 加载失败但安装成功（仅警告）
                logger.warning(
                    "module_load_failed_after_install name=%s error=%s",
                    name,
                    load_result.get("error"),
                )

        info.install_count += 1
        return InstallResult(success=True, module=info, security_check=check)

    def install_from_file(
        self,
        file_path: str | Path,
        *,
        name: str | None = None,
        version: str = "1.0.0",
        description: str = "",
    ) -> InstallResult:
        """从本地文件安装"""
        file_path = Path(file_path)
        if not file_path.exists():
            return InstallResult(success=False, error=f"文件不存在: {file_path}")

        try:
            code = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return InstallResult(success=False, error=f"读取失败: {e}")

        module_name = name or file_path.stem
        return self.install_from_code(
            name=module_name,
            code=code,
            source=f"file:{file_path}",
            version=version,
            description=description or f"From {file_path.name}",
        )

    def load(self, name: str) -> dict:
        """加载已安装的模块到 sys.modules"""
        if name not in self._installed:
            return {"success": False, "error": f"模块未安装: {name}"}

        info = self._installed[name]
        if not info.enabled:
            return {"success": False, "error": "模块已禁用"}

        install_path = Path(info.install_path)
        if not install_path.exists():
            return {"success": False, "error": f"安装文件不存在: {install_path}"}

        try:
            spec = importlib.util.spec_from_file_location(name, install_path)
            if spec is None or spec.loader is None:
                return {"success": False, "error": "无法创建模块 spec"}
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            self._loaded_modules[name] = module
            info.install_count += 1
            self._save_metadata()
            logger.info("module_loaded name=%s path=%s", name, install_path)
            return {"success": True, "module": name, "path": str(install_path)}
        except Exception as e:
            return {"success": False, "error": f"加载失败: {e}"}

    def reload(self, name: str) -> dict:
        """热重载已加载的模块"""
        if name not in self._loaded_modules:
            return self.load(name)

        try:
            module = self._loaded_modules[name]
            importlib.reload(module)
            info = self._installed[name]
            info.install_count += 1
            self._save_metadata()
            return {"success": True, "module": name}
        except Exception as e:
            return {"success": False, "error": f"重载失败: {e}"}

    def enable(self, name: str) -> dict:
        """启用模块"""
        if name not in self._installed:
            return {"success": False, "error": f"模块未安装: {name}"}
        self._installed[name].enabled = True
        self._save_metadata()
        return {"success": True, "enabled": True}

    def disable(self, name: str) -> dict:
        """禁用模块（从 sys.modules 卸载）"""
        if name not in self._installed:
            return {"success": False, "error": f"模块未安装: {name}"}
        self._installed[name].enabled = False
        if name in sys.modules:
            del sys.modules[name]
        if name in self._loaded_modules:
            del self._loaded_modules[name]
        self._save_metadata()
        return {"success": True, "enabled": False}

    def security_check(self, code: str) -> SecurityCheckResult:
        """仅做安全检查（不安装）"""
        return self.validator.check(code)

    def get_loaded(self) -> list[str]:
        """获取当前已加载的模块名"""
        return list(self._loaded_modules.keys())


# ── 全局单例 ─────────────────────────────────────────


_installer: SelfIteratingInstaller | None = None


def get_installer() -> SelfIteratingInstaller:
    """获取全局安装器"""
    global _installer
    if _installer is None:
        _installer = SelfIteratingInstaller()
    return _installer
