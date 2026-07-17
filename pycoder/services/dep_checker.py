"""
自动依赖检测与安装 — 分析代码中的 import 语句并自动安装缺失包

工作流程:
  1. 扫描代码 → AST 提取所有 import 语句
  2. 模块名 → pip 包名映射
  3. 检查当前环境是否已安装
  4. 自动 pip install 缺失包
"""

from __future__ import annotations

import ast
import asyncio
import logging
import sys

logger = logging.getLogger(__name__)

# 模块名 → pip 包名映射表
COMMON_MAP: dict[str, str] = {
    "pandas": "pandas",
    "numpy": "numpy",
    "matplotlib": "matplotlib",
    "PIL": "pillow",
    "cv2": "opencv-python",
    "requests": "requests",
    "flask": "flask",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "tensorflow": "tensorflow",
    "torch": "torch",
    "sklearn": "scikit-learn",
    "selenium": "selenium",
    "playwright": "playwright",
    "httpx": "httpx",
    "aiohttp": "aiohttp",
    "beautifulsoup4": "beautifulsoup4",
    "bs4": "beautifulsoup4",
    "lxml": "lxml",
    "Pillow": "pillow",
    "pytesseract": "pytesseract",
    "openpyxl": "openpyxl",
    "xlrd": "xlrd",
    "sqlalchemy": "sqlalchemy",
    "pymongo": "pymongo",
    "redis": "redis",
    "celery": "celery",
    "scrapy": "scrapy",
    "django": "django",
    "tqdm": "tqdm",
    "plotly": "plotly",
    "seaborn": "seaborn",
    "wordcloud": "wordcloud",
    "jieba": "jieba",
    "PIL": "pillow",
    "pyarrow": "pyarrow",
}


class DependencyChecker:
    """自动依赖检测与安装"""

    async def check_code(self, code: str) -> dict:
        """分析代码中的 import，返回缺失的包"""
        if not code.strip():
            return {"success": True, "all_installed": True, "missing": []}

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return {"success": False, "error": "代码语法错误，无法分析依赖"}

        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    base = alias.name.split(".")[0]
                    modules.add(base)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    base = node.module.split(".")[0]
                    modules.add(base)

        missing = []
        for mod in modules:
            pkg = self._resolve_package(mod)
            if pkg and not self._is_installed(pkg):
                missing.append(pkg)

        return {
            "success": True,
            "total_imports": len(modules),
            "all_installed": len(missing) == 0,
            "missing": missing,
        }

    async def auto_install(self, packages: list[str]) -> dict:
        """自动安装缺失依赖"""
        results = {}
        for pkg in packages:
            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "pip", "install", pkg,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                results[pkg] = {
                    "success": proc.returncode == 0,
                    "output": (stdout.decode() + stderr.decode())[:500],
                }
            except Exception as exc:
                results[pkg] = {"success": False, "error": str(exc)}
        return results

    def _resolve_package(self, module_name: str) -> str | None:
        """模块名 → pip 包名"""
        return COMMON_MAP.get(module_name)

    def _is_installed(self, package: str) -> bool:
        """检查包是否已安装"""
        try:
            import importlib.metadata
            importlib.metadata.distribution(package)
            return True
        except (importlib.metadata.PackageNotFoundError, ImportError):
            # 降级检查
            try:
                __import__(package.replace("-", "_"))
                return True
            except ImportError:
                return False


# ══════════════════════════════════════════════════════════
# 工具定义
# ══════════════════════════════════════════════════════════

DEP_TOOLS: list[dict] = [
    {
        "name": "check_deps",
        "description": "分析代码中的 import 语句，自动检测并安装缺失的 Python 包",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "要分析的代码"},
                "auto_install": {
                    "type": "boolean",
                    "description": "是否自动安装缺失包",
                    "default": True,
                },
            },
            "required": ["code"],
        },
    },
]


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════

_checker: DependencyChecker | None = None


def get_checker() -> DependencyChecker:
    global _checker
    if _checker is None:
        _checker = DependencyChecker()
    return _checker
