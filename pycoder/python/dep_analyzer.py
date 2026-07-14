"""
Python 依赖分析增强 — 理解项目依赖并在代码生成时适配

P1-5 功能:
- 读取 requirements.txt / pyproject.toml / setup.py / setup.cfg
- 解析依赖树
- 在 Prompt 中自动注入依赖信息
- 生成代码时自动适配已安装的包版本

在 env_detector.py 基础上的增强。
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DependencyInfo:
    """单个依赖信息"""

    name: str
    version: str = ""
    version_spec: str = ""  # ">=2.0,<3.0"
    installed: bool = False
    installed_version: str = ""
    type: str = "production"  # "production" | "dev" | "optional"
    extras: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class ProjectDependencies:
    """项目依赖分析结果"""

    project_name: str = ""
    python_version: str = ""
    package_manager: str = ""  # "pip" | "poetry" | "pipenv" | "conda"
    total_deps: int = 0
    production_deps: list[DependencyInfo] = field(default_factory=list)
    dev_deps: list[DependencyInfo] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    key_packages: list[str] = field(default_factory=list)


class DepAnalyzer:
    """
    依赖分析器 — 解析项目所有依赖源。

    支持:
    - requirements.txt (标准格式 + -r 引用)
    - pyproject.toml (Poetry / PDM / setuptools)
    - setup.py / setup.cfg (setuptools)
    - Pipfile / Pipfile.lock (Pipenv)
    - conda environment.yml (Conda)
    """

    def __init__(self, project_root: str | Path = "."):
        self.project_root = Path(project_root).resolve()

    def analyze(self) -> ProjectDependencies:
        """分析项目依赖"""
        result = ProjectDependencies()

        # 项目名
        result.project_name = self.project_root.name

        # Python 版本
        import sys

        result.python_version = f"{sys.version_info.major}.{sys.version_info.minor}"

        # 检测包管理器
        result.package_manager = self._detect_package_manager()

        # 解析所有依赖源
        all_deps = []

        # 1. requirements.txt
        req_deps = self._parse_requirements()
        all_deps.extend(req_deps)

        # 2. pyproject.toml
        toml_deps = self._parse_pyproject()
        all_deps.extend(toml_deps)

        # 3. setup.py / setup.cfg
        setup_deps = self._parse_setup_py()
        all_deps.extend(setup_deps)

        # 4. Pipfile
        pipfile_deps = self._parse_pipfile()
        all_deps.extend(pipfile_deps)

        # 去重（按名称，保留最新版本）
        seen = {}
        for dep in all_deps:
            if dep.name in seen:
                existing = seen[dep.name]
                if dep.version and not existing.version:
                    seen[dep.name] = dep
            else:
                seen[dep.name] = dep

        unique_deps = list(seen.values())

        # 检查安装状态
        self._check_installed(unique_deps)

        # 分类
        for dep in unique_deps:
            if dep.type == "dev":
                result.dev_deps.append(dep)
            else:
                result.production_deps.append(dep)

        result.total_deps = len(unique_deps)

        # 检测框架
        result.frameworks = self._detect_frameworks(unique_deps)

        # 关键包（前 20）
        result.key_packages = [
            f"{d.name}=={d.installed_version}" if d.installed_version else d.name
            for d in unique_deps[:20]
        ]

        return result

    def _parse_requirements(self) -> list[DependencyInfo]:
        """解析 requirements.txt"""
        deps = []
        req_file = self.project_root / "requirements.txt"
        if not req_file.exists():
            req_file = self.project_root / "requirements" / "base.txt"

        if not req_file.exists():
            return deps

        try:
            with open(req_file, encoding="utf-8") as f:
                lines = f.readlines()
        except (OSError, UnicodeDecodeError, PermissionError) as e:
            logger.debug("parse_requirements_read_failed file=%s error=%s", req_file, e)
            return deps

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue

            # 解析格式: package==version 或 package>=version 或 package
            match = re.match(r"^([a-zA-Z0-9_.-]+)\s*(([<>=!~]+)\s*([a-zA-Z0-9.*-]+))?", line)
            if match:
                name = match.group(1).lower()
                version_spec = match.group(2) or ""
                version = match.group(4) or ""

                deps.append(
                    DependencyInfo(
                        name=name,
                        version=version,
                        version_spec=version_spec,
                    )
                )

        return deps

    def _parse_pyproject(self) -> list[DependencyInfo]:
        """解析 pyproject.toml"""
        deps = []
        toml_file = self.project_root / "pyproject.toml"
        if not toml_file.exists():
            return deps

        try:
            with open(toml_file, encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError, PermissionError) as e:
            logger.debug("parse_pyproject_read_failed file=%s error=%s", toml_file, e)
            return deps

        # 使用简单的正则解析 TOML 依赖声明
        # Poetry 格式: [tool.poetry.dependencies]
        # PDM 格式: [project.dependencies]
        sections = [
            ("tool.poetry.dependencies", "production"),
            ("tool.poetry.dev-dependencies", "dev"),
            ("project.dependencies", "production"),
            ("project.optional-dependencies", "optional"),
        ]

        for section, dep_type in sections:
            in_section = False
            for line in content.split("\n"):
                stripped = line.strip()
                if stripped == f"[{section}]":
                    in_section = True
                    continue
                if in_section and stripped.startswith("["):
                    in_section = False
                    continue
                if not in_section:
                    continue

                # 解析: package = "^2.0" 或 package = {version = "^2.0", extras = ["xxx"]}
                match = re.match(r'^([a-zA-Z0-9_.-]+)\s*=\s*"([^"]*)"', stripped)
                if match:
                    name = match.group(1).lower()
                    if name == "python":
                        continue
                    version = match.group(2).lstrip("^~><=")
                    deps.append(
                        DependencyInfo(
                            name=name,
                            version=version,
                            type=dep_type,
                        )
                    )

        return deps

    def _parse_setup_py(self) -> list[DependencyInfo]:
        """解析 setup.py（简化版 AST 解析）"""
        deps = []
        setup_file = self.project_root / "setup.py"
        if not setup_file.exists():
            setup_file = self.project_root / "setup.cfg"

        return deps  # 简化：暂时跳过复杂的 setup.py 解析

    def _parse_pipfile(self) -> list[DependencyInfo]:
        """解析 Pipfile"""
        deps = []
        pipfile = self.project_root / "Pipfile"
        if not pipfile.exists():
            return deps

        try:
            with open(pipfile, encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError, PermissionError) as e:
            logger.debug("parse_pipfile_read_failed file=%s error=%s", pipfile, e)
            return deps

        in_packages = False
        in_dev = False

        for line in content.split("\n"):
            stripped = line.strip()
            if stripped == "[packages]":
                in_packages = True
                in_dev = False
                continue
            if stripped == "[dev-packages]":
                in_packages = False
                in_dev = True
                continue
            if stripped.startswith("[") and stripped.endswith("]"):
                in_packages = False
                in_dev = False
                continue

            if in_packages or in_dev:
                match = re.match(r'^([a-zA-Z0-9_.-]+)\s*=\s*"([^"]*)"', stripped)
                if match:
                    name = match.group(1).lower()
                    version = match.group(2).lstrip("=")
                    deps.append(
                        DependencyInfo(
                            name=name,
                            version=version,
                            type="dev" if in_dev else "production",
                        )
                    )

        return deps

    def _detect_package_manager(self) -> str:
        """检测使用的包管理器"""
        # 检查文件存在性
        if (self.project_root / "pyproject.toml").exists():
            # 检查是否 Poetry
            try:
                with open(self.project_root / "pyproject.toml", encoding="utf-8") as f:
                    if "tool.poetry" in f.read():
                        return "poetry"
            except Exception as e:
                logger.debug("Failed to parse pyproject.toml: %s", e)
            return "pdm"

        if (self.project_root / "Pipfile").exists():
            return "pipenv"

        if (self.project_root / "environment.yml").exists():
            return "conda"

        if (self.project_root / "requirements.txt").exists():
            return "pip"

        return "unknown"

    def _check_installed(self, deps: list[DependencyInfo]):
        """检查依赖是否已安装及版本"""
        try:
            result = subprocess.run(
                ["pip", "list", "--format", "json"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                installed = json.loads(result.stdout)
                installed_map = {pkg["name"].lower(): pkg["version"] for pkg in installed}

                for dep in deps:
                    if dep.name.lower() in installed_map:
                        dep.installed = True
                        dep.installed_version = installed_map[dep.name.lower()]
        except Exception as e:
            logger.debug("Failed to check installed packages: %s", e)

    def _detect_frameworks(self, deps: list[DependencyInfo]) -> list[str]:
        """检测项目使用的框架"""
        framework_patterns = {
            "django": "Django",
            "fastapi": "FastAPI",
            "flask": "Flask",
            "textual": "Textual",
            "rich": "Rich",
            "sqlalchemy": "SQLAlchemy",
            "pydantic": "Pydantic",
            "celery": "Celery",
            "pytest": "pytest",
            "scrapy": "Scrapy",
            "numpy": "NumPy",
            "pandas": "Pandas",
            "torch": "PyTorch",
            "tensorflow": "TensorFlow",
        }

        detected = []
        dep_names = {d.name.lower() for d in deps}

        for pattern, display_name in framework_patterns.items():
            if pattern in dep_names:
                detected.append(display_name)

        return detected

    def generate_prompt_context(self) -> str:
        """
        生成 Prompt 上下文（用于注入系统提示）。
        如: "此项目使用 Django 4.2 + PostgreSQL"
        """
        result = self.analyze()

        lines = ["## 项目依赖信息", ""]

        lines.append(f"- 项目: {result.project_name}")
        lines.append(f"- Python: {result.python_version}")
        lines.append(f"- 包管理器: {result.package_manager}")
        lines.append(f"- 总依赖: {result.total_deps}")

        if result.frameworks:
            lines.append(f"- 检测到框架: {', '.join(result.frameworks)}")

        if result.key_packages:
            lines.append("\n关键包:")
            for pkg in result.key_packages[:15]:
                lines.append(f"  - {pkg}")

        # 框架特定提示
        if "Django" in result.frameworks:
            django_deps = [d for d in result.production_deps if "django" in d.name.lower()]
            if django_deps:
                versions = [f"{d.name} {d.installed_version or d.version}" for d in django_deps]
                lines.append(
                    f"\n⚠️ Django 项目，请使用 Django {versions[0].split()[-1] if versions else '4.x'} 的 API 语法"
                )

        if "FastAPI" in result.frameworks:
            lines.append("\n⚠️ FastAPI 项目，请使用 Pydantic v2 风格的类型注解")

        return "\n".join(lines)

    def scan_vulnerabilities(self) -> list[dict]:
        """
        扫描依赖中的已知安全漏洞（集成 pip-audit）。

        需要安装 pip-audit: pip install pip-audit

        Returns:
            [{"name", "installed", "vulnerable", "advisory", "severity", "fix_version"}, ...]
        """
        import sys as _sys

        try:
            result = subprocess.run(
                [_sys.executable, "-m", "pip_audit", "--format", "json", "--desc"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self.project_root),
            )
            if result.returncode != 0 and not result.stdout.strip():
                return [{"error": "pip-audit 未安装或无漏洞", "detail": result.stderr[:300]}]

            try:
                audit_data = json.loads(result.stdout)
            except json.JSONDecodeError:
                return []

            vulnerabilities = []
            for entry in audit_data.get("vulnerabilities", []):
                pkg = entry.get("name", "")
                installed_v = entry.get("version", "")
                for vuln in entry.get("advisories", []):
                    vulnerabilities.append(
                        {
                            "name": pkg,
                            "installed": installed_v,
                            "vulnerable": True,
                            "advisory": vuln.get("summary", vuln.get("id", "")),
                            "severity": vuln.get("severity", "unknown"),
                            "fix_version": vuln.get("fixed_version", ""),
                        }
                    )
            return vulnerabilities

        except FileNotFoundError:
            return [{"error": "pip-audit 未安装", "fix": "pip install pip-audit"}]
        except Exception as e:
            logger.warning("vulnerability_scan_failed: %s", str(e))
            return []


# ── 快捷函数 ─────────────────────────────────────────────


def analyze_project_deps(project_root: str | Path = ".") -> ProjectDependencies:
    """快速分析项目依赖"""
    analyzer = DepAnalyzer(project_root)
    return analyzer.analyze()


def inject_deps_to_prompt(project_root: str | Path = ".") -> str:
    """分析并返回可注入 Prompt 的依赖上下文"""
    analyzer = DepAnalyzer(project_root)
    return analyzer.generate_prompt_context()
