"""
项目路径自动识别引擎 — 智能检测用户当前工作的项目根目录

Multi-strategy detection with <1s latency, cross-platform support.
Edge cases: multi-project, temp dirs, no project, symlinks.

策略优先级（从高到低）：
1. 启动参数 / 环境变量显式指定
2. 用户配置的默认路径（.pycoder/config.json）
3. Electron 前端传入的路径（dialog.showOpenDialog）
4. 最近打开的工作区历史记录
5. Git 仓库根目录
6. 项目标识文件（pyproject.toml / package.json / Cargo.toml 等）
7. 文件系统监听器检测到的活跃目录
8. 当前工作目录 + 父目录启发式搜索
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── 项目标识文件（按优先级排序） ──
_PROJECT_INDICATORS: list[str] = [
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "CMakeLists.txt",
    "Makefile",
    "setup.py",
    "setup.cfg",
    ".git",
    ".pycoder",
    "AGENTS.md",
    "README.md",
]

# ── 需要排除的临时/系统目录名 ──
_TEMP_DIR_PATTERNS: frozenset[str] = frozenset({
    "tmp", "temp", "cache", ".cache", "__pycache__",
    "node_modules", ".npm", ".yarn",
    "AppData", "Application Data",
    "Downloads", "Desktop",
    "System32", "Windows", "Program Files", "Program Files (x86)",
    "usr", "bin", "sbin", "etc", "var", "opt",
    ".vscode", ".idea", ".git",
})


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class DetectionResult:
    """项目检测结果"""

    project_path: str = ""
    """检测到的项目根目录绝对路径"""

    confidence: float = 0.0
    """置信度 0.0 ~ 1.0"""

    method: str = "unknown"
    """检测方法: startup_arg | user_config | electron | history | git | indicator | heuristic | manual | fallback"""

    name: str = ""
    """项目名称（目录名）"""

    indicators: list[str] = field(default_factory=list)
    """检测到的项目标识文件列表"""

    is_temp: bool = False
    """是否在临时目录"""

    is_multi_project: bool = False
    """是否检测到多项目"""

    suggestions: list[str] = field(default_factory=list)
    """给用户的建议"""

    elapsed_ms: float = 0.0
    """检测耗时（毫秒）"""

    def to_dict(self) -> dict:
        return {
            "project_path": self.project_path,
            "confidence": round(self.confidence, 2),
            "method": self.method,
            "name": self.name,
            "indicators": self.indicators,
            "is_temp": self.is_temp,
            "is_multi_project": self.is_multi_project,
            "suggestions": self.suggestions,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "status": self._status(),
        }

    def _status(self) -> str:
        """返回状态字符串"""
        if self.confidence >= 0.8:
            return "detected"
        if self.confidence >= 0.4:
            return "uncertain"
        return "not_found"


# ══════════════════════════════════════════════════════════
# 检测引擎
# ══════════════════════════════════════════════════════════


class WorkspaceDetector:
    """项目路径自动识别引擎

    用法:
        detector = WorkspaceDetector()
        result = detector.detect(
            electron_path="/home/user/my-project",
            startup_args=["--workspace", "/path/to/project"],
        )
    """

    def __init__(self) -> None:
        self._history_file: Path = Path.home() / ".pycoder" / "workspace_history.json"
        self._config_file: Path = Path.home() / ".pycoder" / "config.json"

    # ── 主入口 ──────────────────────────────────────────

    def detect(
        self,
        electron_path: str | None = None,
        startup_args: list[str] | None = None,
        force_auto: bool = False,
    ) -> DetectionResult:
        """执行项目路径检测

        Args:
            electron_path: Electron 前端传入的路径（来自 dialog.showOpenDialog）
            startup_args: 启动参数列表
            force_auto: 强制自动检测（忽略用户配置的默认路径）

        Returns:
            DetectionResult 包含检测结果和建议
        """
        t0 = time.perf_counter()
        result = DetectionResult()

        # ── 策略 1: 启动参数 ──
        workspace_arg = self._parse_startup_arg(startup_args or [])
        if workspace_arg:
            path = Path(workspace_arg).resolve()
            if path.is_dir():
                result.project_path = str(path)
                result.confidence = 1.0
                result.method = "startup_arg"
                result.name = path.name
                result.indicators = self._find_indicators(path)
                result.suggestions = []
                result.elapsed_ms = (time.perf_counter() - t0) * 1000
                return result

        # ── 策略 2: 用户配置的默认路径 ──
        if not force_auto:
            config_path = self._load_config_default_path()
            if config_path:
                maybe = Path(config_path).resolve()
                if maybe.is_dir() and not self._is_temp_dir(maybe):
                    result.project_path = str(maybe)
                    result.confidence = 0.95
                    result.method = "user_config"
                    result.name = maybe.name
                    result.indicators = self._find_indicators(maybe)
                    result.elapsed_ms = (time.perf_counter() - t0) * 1000
                    return result

        # ── 策略 3: Electron 前端传入 ──
        if electron_path:
            maybe = Path(electron_path).resolve()
            if maybe.is_dir() and not self._is_temp_dir(maybe):
                result.project_path = str(maybe)
                result.confidence = 0.9
                result.method = "electron"
                result.name = maybe.name
                result.indicators = self._find_indicators(maybe)
                result.elapsed_ms = (time.perf_counter() - t0) * 1000
                return result

        # ── 策略 4: 历史记录 ──
        history = self._load_history()
        for hist_path in history[:3]:
            maybe = Path(hist_path).resolve()
            if maybe.is_dir() and not self._is_temp_dir(maybe):
                result.project_path = str(maybe)
                result.confidence = 0.7
                result.method = "history"
                result.name = maybe.name
                result.indicators = self._find_indicators(maybe)
                result.elapsed_ms = (time.perf_counter() - t0) * 1000
                return result

        # ── 策略 5: Git 仓库根目录 ──
        cwd = Path.cwd().resolve()
        git_root = self._find_git_root(cwd)
        if git_root and not self._is_temp_dir(git_root):
            result.project_path = str(git_root)
            result.confidence = 0.85
            result.method = "git"
            result.name = git_root.name
            result.indicators = self._find_indicators(git_root)
            result.elapsed_ms = (time.perf_counter() - t0) * 1000
            return result

        # ── 策略 6: 项目标识文件 ──
        indicator_root = self._find_indicator_root(cwd)
        if indicator_root and not self._is_temp_dir(indicator_root):
            result.project_path = str(indicator_root)
            result.confidence = 0.75
            result.method = "indicator"
            result.name = indicator_root.name
            result.indicators = self._find_indicators(indicator_root)
            result.elapsed_ms = (time.perf_counter() - t0) * 1000
            return result

        # ── 策略 7: 父目录启发式 ──
        heuristic = self._find_heuristic_root(cwd)
        if heuristic and not self._is_temp_dir(heuristic):
            result.project_path = str(heuristic)
            result.confidence = 0.4
            result.method = "heuristic"
            result.name = heuristic.name
            result.indicators = self._find_indicators(heuristic)
            result.is_temp = self._is_temp_dir(heuristic)
            result.suggestions = [
                "未检测到明确的项目标识文件（如 pyproject.toml / package.json / .git）",
                "建议在项目根目录创建 pyproject.toml 或初始化 Git 仓库",
                "或手动指定项目路径: 设置 → 工作区 → 默认项目路径",
            ]
            result.elapsed_ms = (time.perf_counter() - t0) * 1000
            return result

        # ── 策略 8: 兜底 ──
        result.project_path = str(cwd)
        result.confidence = 0.1
        result.method = "fallback"
        result.name = cwd.name
        result.is_temp = self._is_temp_dir(cwd)
        result.suggestions = [
            "无法自动识别项目路径，当前使用服务器工作目录",
            "请通过以下方式指定项目路径:",
            "  1. 在设置中配置默认项目路径",
            "  2. 使用 --workspace 参数启动: python -m pycoder --workspace /path/to/project",
            "  3. 在项目根目录创建 pyproject.toml 或初始化 Git 仓库",
        ]
        result.elapsed_ms = (time.perf_counter() - t0) * 1000
        return result

    # ── 检测策略 ─────────────────────────────────────────

    @staticmethod
    def _parse_startup_arg(args: list[str]) -> str | None:
        """解析 --workspace 或 -w 参数"""
        for i, arg in enumerate(args):
            if arg in ("--workspace", "-w"):
                if i + 1 < len(args):
                    return args[i + 1]
            if arg.startswith("--workspace="):
                return arg.split("=", 1)[1]
            if arg.startswith("-w="):
                return arg.split("=", 1)[1]
        return None

    def _load_config_default_path(self) -> str | None:
        """从 .pycoder/config.json 读取默认项目路径"""
        try:
            if self._config_file.exists():
                data = __import__("json").loads(
                    self._config_file.read_text(encoding="utf-8")
                )
                return data.get("default_project_path")
        except (OSError, ValueError, KeyError) as e:
            logger.debug("config_load_failed error=%s", e)
        return None

    def _load_history(self) -> list[str]:
        """加载最近工作区历史"""
        try:
            if self._history_file.exists():
                data = __import__("json").loads(
                    self._history_file.read_text(encoding="utf-8")
                )
                return data.get("workspaces", [])
        except (OSError, ValueError, KeyError) as e:
            logger.debug("history_load_failed error=%s", e)
        return []

    @staticmethod
    def _find_git_root(start: Path) -> Path | None:
        """向上查找 Git 仓库根目录"""
        current = start
        for _ in range(10):  # 最多向上 10 层
            if (current / ".git").is_dir():
                return current
            parent = current.parent
            if parent == current:
                break
            current = parent
        return None

    @staticmethod
    def _find_indicator_root(start: Path) -> Path | None:
        """向上查找包含项目标识文件的目录"""
        current = start
        for _ in range(8):
            for indicator in _PROJECT_INDICATORS:
                if (current / indicator).exists():
                    return current
            parent = current.parent
            if parent == current:
                break
            current = parent
        return None

    @staticmethod
    def _find_indicators(root: Path) -> list[str]:
        """列出目录中存在的项目标识文件"""
        found: list[str] = []
        for indicator in _PROJECT_INDICATORS:
            if (root / indicator).exists():
                found.append(indicator)
        return found

    @staticmethod
    def _find_heuristic_root(start: Path) -> Path | None:
        """启发式查找：向上找到第一个有多个子目录的层级"""
        current = start
        best: Path | None = None
        best_score = 0
        for _ in range(6):
            try:
                children = list(current.iterdir())
                subdirs = [c for c in children if c.is_dir()]
                files = [c for c in children if c.is_file() and not c.name.startswith(".")]
                score = len(subdirs) * 2 + len(files)
                if score > best_score and not any(
                    p.name.lower() in _TEMP_DIR_PATTERNS for p in [current]
                ):
                    best_score = score
                    best = current
            except (OSError, PermissionError):
                pass
            parent = current.parent
            if parent == current:
                break
            current = parent
        return best

    @staticmethod
    def _is_temp_dir(path: Path) -> bool:
        """检查是否为临时/系统目录"""
        name_lower = path.name.lower()
        if name_lower in _TEMP_DIR_PATTERNS:
            return True
        # 检查路径是否在系统临时目录下
        path_str = str(path).lower()
        temp_roots = [
            os.environ.get("TMP", "").lower(),
            os.environ.get("TEMP", "").lower(),
            os.environ.get("TMPDIR", "").lower(),
            "/tmp",
            "/var/tmp",
        ]
        return any(
            tr and path_str.startswith(tr)
            for tr in temp_roots
            if tr
        )

    # ── 配置持久化 ──────────────────────────────────────

    def save_default_path(self, path: str) -> bool:
        """保存默认项目路径到配置"""
        try:
            self._config_file.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if self._config_file.exists():
                try:
                    data = __import__("json").loads(
                        self._config_file.read_text(encoding="utf-8")
                    )
                except (OSError, ValueError):
                    pass
            data["default_project_path"] = path
            self._config_file.write_text(
                __import__("json").dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("default_project_path_saved path=%s", path)
            return True
        except OSError as e:
            logger.error("save_default_path_failed error=%s", e)
            return False

    def save_to_history(self, path: str) -> None:
        """保存路径到工作区历史"""
        try:
            self._history_file.parent.mkdir(parents=True, exist_ok=True)
            data = {"workspaces": []}
            if self._history_file.exists():
                try:
                    data = __import__("json").loads(
                        self._history_file.read_text(encoding="utf-8")
                    )
                except (OSError, ValueError):
                    pass
            workspaces: list[str] = data.get("workspaces", [])
            # 去重，最新放最前，最多保留 10 条
            if path in workspaces:
                workspaces.remove(path)
            workspaces.insert(0, path)
            data["workspaces"] = workspaces[:10]
            self._history_file.write_text(
                __import__("json").dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as e:
            logger.debug("history_save_failed error=%s", e)


# ══════════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════════

_detector: WorkspaceDetector | None = None


def get_workspace_detector() -> WorkspaceDetector:
    """获取检测引擎单例"""
    global _detector
    if _detector is None:
        _detector = WorkspaceDetector()
    return _detector