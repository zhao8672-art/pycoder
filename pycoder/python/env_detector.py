"""
Python 开发环境自动检测

检测当前项目使用的 Python 工具链:
- 虚拟环境: venv, virtualenv, conda
- 包管理器: pip, poetry, pdm, pipenv, uv
- 项目类型: Flask, Django, FastAPI, pandas, scientific
"""

import json
import logging
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)
# Windows 隐藏控制台窗口的标志
if os.name == "nt":
    _SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW
else:
    _SUBPROCESS_FLAGS = 0


@dataclass
class EnvironmentInfo:
    python_version: str = ""
    venv_type: str = "none"  # venv, conda, poetry, pdm, pipenv, none
    venv_path: str | None = None
    package_manager: str = "pip"  # pip, poetry, pdm, pipenv, uv
    project_type: str = "unknown"  # web, data_science, library, script
    frameworks: list[str] = field(default_factory=list)
    has_requirements: bool = False
    has_pyproject: bool = False
    has_setup: bool = False
    has_jupyter: bool = False
    dependencies: list[str] = field(default_factory=list)
    # 新增：依赖分析
    direct_deps: list[dict] = field(
        default_factory=list
    )  # [{"name": str, "version": str, "kind": str}]
    dev_deps: list[str] = field(default_factory=list)
    outdated_packages: list[dict] = field(default_factory=list)
    # 新增：项目结构分析
    project_structure: dict = field(default_factory=dict)
    git_info: dict = field(default_factory=dict)


def detect_environment(project_path: str | None = None) -> EnvironmentInfo:
    """检测项目所在环境的 Python 工具链"""
    info = EnvironmentInfo()
    info.python_version = sys.version.split()[0]

    if project_path:
        project_dir = Path(project_path).resolve()
    else:
        project_dir = Path.cwd().resolve()

    # 检测虚拟环境
    _detect_venv(info)

    # 检测包管理器
    _detect_package_manager(info, project_dir)

    # 检测项目类型和框架
    _detect_project_type(info, project_dir)

    return info


def _detect_venv(info: EnvironmentInfo):
    """检测虚拟环境"""
    venv = os.environ.get("VIRTUAL_ENV")
    conda = os.environ.get("CONDA_DEFAULT_ENV")
    poetry = os.environ.get("POETRY_ACTIVE")

    if venv:
        info.venv_type = "venv"
        info.venv_path = venv
    elif conda:
        info.venv_type = "conda"
        info.venv_path = conda
    elif poetry:
        info.venv_type = "poetry"
    else:
        # 检查当前目录下是否有 .venv
        if (Path.cwd() / ".venv").exists():
            info.venv_type = "venv"
            info.venv_path = str(Path.cwd() / ".venv")
        elif (Path.cwd() / "venv").exists():
            info.venv_type = "venv"
            info.venv_path = str(Path.cwd() / "venv")


def _detect_package_manager(info: EnvironmentInfo, project_dir: Path):
    """检测包管理器"""
    if (project_dir / "poetry.lock").exists():
        info.package_manager = "poetry"
    elif (project_dir / "Pipfile.lock").exists():
        info.package_manager = "pipenv"
    elif (project_dir / "pdm.lock").exists():
        info.package_manager = "pdm"
    elif (project_dir / "uv.lock").exists():
        info.package_manager = "uv"
    elif (project_dir / "requirements.txt").exists():
        info.has_requirements = True
        info.package_manager = "pip"


def _detect_project_type(info: EnvironmentInfo, project_dir: Path):
    """检测项目类型和使用的框架"""
    info.has_pyproject = (project_dir / "pyproject.toml").exists()
    info.has_setup = (project_dir / "setup.py").exists() or (project_dir / "setup.cfg").exists()
    info.has_jupyter = _has_ipynb_files(project_dir)

    # 检测框架
    try:
        from importlib import metadata as importlib_metadata

        installed = {pkg.metadata["Name"].lower() for pkg in importlib_metadata.distributions()}

        framework_map = {
            "django": "Django",
            "flask": "Flask",
            "fastapi": "FastAPI",
            "pandas": "pandas",
            "numpy": "NumPy",
            "matplotlib": "Matplotlib",
            # 修复: pip 包名是 torch 而非 pytorch
            "torch": "PyTorch",
            "tensorflow": "TensorFlow",
            "scikit-learn": "scikit-learn",
            "jupyter": "Jupyter",
            "streamlit": "Streamlit",
            "pytest": "pytest",
            "textual": "Textual",
            "rich": "Rich",
            "click": "Click",
            "sqlalchemy": "SQLAlchemy",
            "pydantic": "Pydantic",
        }

        for pkg_key, name in framework_map.items():
            if pkg_key in installed:
                info.frameworks.append(name)

        # 判断项目类型
        if {"Django", "Flask", "FastAPI"} & set(info.frameworks):
            info.project_type = "web"
        elif {"pandas", "NumPy", "PyTorch", "TensorFlow", "scikit-learn"} & set(info.frameworks):
            info.project_type = "data_science"
        elif info.has_pyproject or info.has_setup:
            info.project_type = "library"
        else:
            info.project_type = "script"
    except Exception as e:
        logger.debug("Failed to detect project type: %s", e)

    # 分析项目结构
    info.project_structure = _analyze_project_structure(project_dir)

    # 分析 git 信息
    info.git_info = _analyze_git_info(project_dir)


def _has_ipynb_files(directory: Path) -> bool:
    """检查目录是否包含 .ipynb 文件"""
    try:
        return any(directory.rglob("*.ipynb"))
    except (OSError, PermissionError) as e:
        logger.debug("has_ipynb_files_failed dir=%s error=%s", directory, e)
        return False


def _analyze_project_structure(project_dir: Path) -> dict:
    """分析项目文件结构"""
    structure = {
        "root": str(project_dir),
        "total_files": 0,
        "total_dirs": 0,
        "python_files": 0,
        "test_files": 0,
        "notebook_files": 0,
        "config_files": 0,
        "max_depth": 0,
        "top_dirs": [],
        "package_dirs": [],
    }

    try:
        for root, dirs, files in os.walk(project_dir):
            # 跳过虚拟环境和缓存
            dirs[:] = [
                d
                for d in dirs
                if d
                not in (
                    ".venv",
                    "venv",
                    "__pycache__",
                    ".git",
                    "node_modules",
                    ".tox",
                    ".eggs",
                    "build",
                    "dist",
                    ".mypy_cache",
                    ".pytest_cache",
                )
            ]

            depth = len(Path(root).relative_to(project_dir).parts)
            structure["max_depth"] = max(structure["max_depth"], depth)
            structure["total_dirs"] += len(dirs)

            rel = str(Path(root).relative_to(project_dir))
            if depth == 1:
                structure["top_dirs"].append(rel)

            # 检测 Python package 目录（包含 __init__.py）
            if "__init__.py" in files and depth > 0:
                structure["package_dirs"].append(rel.replace(os.sep, "."))

            for f in files:
                structure["total_files"] += 1
                if f.endswith(".py"):
                    structure["python_files"] += 1
                if f.startswith("test_") or f.endswith("_test.py"):
                    structure["test_files"] += 1
                if f.endswith(".ipynb"):
                    structure["notebook_files"] += 1
                if f in (
                    "pyproject.toml",
                    "setup.py",
                    "setup.cfg",
                    "tox.ini",
                    ".pre-commit-config.yaml",
                    "Makefile",
                    "Dockerfile",
                    "docker-compose.yml",
                    ".github",
                ):
                    structure["config_files"] += 1
    except Exception as e:
        logger.debug("Failed to analyze project structure: %s", e)

    return structure


def _analyze_git_info(project_dir: Path) -> dict:
    """分析 Git 仓库信息"""
    git_info = {"is_repo": False, "branch": "", "remotes": [], "last_commit": ""}

    git_dir = project_dir / ".git"
    if not git_dir.exists():
        return git_info

    git_info["is_repo"] = True

    try:
        # 分支
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
            timeout=5,
            creationflags=_SUBPROCESS_FLAGS,
        )
        if r.returncode == 0:
            git_info["branch"] = r.stdout.strip()

        # 远程仓库
        r = subprocess.run(
            ["git", "remote", "-v"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
            timeout=5,
            creationflags=_SUBPROCESS_FLAGS,
        )
        if r.returncode == 0:
            for line in r.stdout.strip().split("\n"):
                if "(fetch)" in line:
                    git_info["remotes"].append(line.split()[1] if len(line.split()) > 1 else "")

        # 最近提交
        r = subprocess.run(
            ["git", "log", "-1", "--format=%h %s (%ar)"],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
            timeout=5,
            creationflags=_SUBPROCESS_FLAGS,
        )
        if r.returncode == 0:
            git_info["last_commit"] = r.stdout.strip()
    except Exception as e:
        logger.debug("Failed to walk project directory: %s", e)

    return git_info


def analyze_dependencies(project_dir: Path | None = None) -> list[dict]:
    """
    分析 pip 依赖树，返回直接依赖列表。

    返回格式: [{"name": str, "version": str, "kind": "direct"|"dev"|"transitive"}]
    """
    if project_dir is None:
        project_dir = Path.cwd()

    deps = []

    try:
        from importlib import metadata as importlib_metadata

        for dist in importlib_metadata.distributions():
            name = dist.metadata.get("Name", "")
            version = dist.version
            if name:
                deps.append(
                    {
                        "name": name,
                        "version": version,
                        "kind": "direct",  # 简化：不区分直接/传递
                    }
                )
    except Exception as e:
        logger.debug("Failed to analyze git info: %s", e)

    return deps


def check_outdated() -> list[dict]:
    """
    检查可升级的 pip 包（使用 pip list --outdated）
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--outdated", "--format=json"],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=_SUBPROCESS_FLAGS,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception as e:
        logger.debug("Failed to analyze dependencies: %s", e)
    return []


def print_env_info(info: EnvironmentInfo) -> str:
    """格式化输出环境信息（中文）"""
    lines = [
        f"🐍 Python {info.python_version}",
        f"📦 虚拟环境: {info.venv_type} ({info.venv_path or '系统'})",
        f"🔧 包管理器: {info.package_manager}",
        f"📁 项目类型: {info.project_type}",
    ]
    if info.frameworks:
        lines.append(f"🏗️  框架: {', '.join(info.frameworks[:5])}")
    if info.project_structure:
        ps = info.project_structure
        lines.append(
            f"📊 项目: {ps.get('python_files', 0)} 个.py / {ps.get('test_files', 0)} 个测试 / {ps.get('notebook_files', 0)} 个.ipynb"
        )
    if info.git_info and info.git_info.get("is_repo"):
        lines.append(
            f"🔀 Git: {info.git_info.get('branch', '?')} | {info.git_info.get('last_commit', '')}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    info = detect_environment()
    print(json.dumps(asdict(info), ensure_ascii=False, indent=2))
    print()
    print(print_env_info(info))
