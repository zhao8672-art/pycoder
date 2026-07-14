"""
项目工具集 — 提供自动依赖管理、测试运行和项目脚手架功能。

功能模块:
1. 自动依赖管理: 检测import并安装缺失包
2. 一键测试运行: 生成并执行pytest测试用例
3. 项目脚手架: 快速生成FastAPI/Streamlit项目骨架
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ── 数据模型 ──────────────────────────────────────────────


@dataclass
class DependencyCheckResult:
    """依赖检查结果"""

    success: bool
    missing_packages: list[str] = field(default_factory=list)
    installed_packages: list[str] = field(default_factory=list)
    failed_packages: list[str] = field(default_factory=list)
    output: str = ""
    error: str = ""


@dataclass
class DependencyAnalysisResult:
    """依赖分析结果（增强版）"""

    success: bool
    missing_packages: list[dict[str, str]] = field(default_factory=list)
    outdated_packages: list[dict[str, str]] = field(default_factory=list)
    unused_packages: list[dict[str, str]] = field(default_factory=list)
    installed_packages: list[dict[str, str]] = field(default_factory=list)
    requirements_status: str = ""
    summary: str = ""


@dataclass
class TestResult:
    """测试结果"""

    success: bool
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    total: int = 0
    duration: float = 0.0
    output: str = ""
    error: str = ""


@dataclass
class ScaffoldResult:
    """脚手架生成结果"""

    success: bool
    project_name: str = ""
    project_type: str = ""
    files_created: list[str] = field(default_factory=list)
    directories_created: list[str] = field(default_factory=list)
    error: str = ""


# ── 自动依赖管理 ──────────────────────────────────────────


class DependencyManager:
    """
    依赖管理器 — 检测项目中的import语句并自动安装缺失包。

    支持:
    - 从Python文件解析import语句
    - 识别标准库vs第三方包
    - 自动安装缺失的第三方包
    - 生成requirements.txt
    """

    # 常见的包名映射（import名与pip包名不一致的情况）
    PACKAGE_NAME_MAP = {
        "PIL": "Pillow",
        "sklearn": "scikit-learn",
        "cv2": "opencv-python",
        "tensorflow": "tensorflow",
        "torch": "torch",
        "bs4": "beautifulsoup4",
        "yaml": "pyyaml",
        "jinja2": "Jinja2",
        "flask": "Flask",
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "pydantic": "pydantic",
        "requests": "requests",
        "numpy": "numpy",
        "pandas": "pandas",
        "matplotlib": "matplotlib",
        "seaborn": "seaborn",
        "scipy": "scipy",
        "pytest": "pytest",
        "black": "black",
        "ruff": "ruff",
        "mypy": "mypy",
        "sqlalchemy": "SQLAlchemy",
        "alembic": "alembic",
        "celery": "celery",
        "redis": "redis",
        "kafka": "kafka-python",
        "gunicorn": "gunicorn",
        "streamlit": "streamlit",
        "plotly": "plotly",
        "dash": "dash",
        "networkx": "networkx",
        "nltk": "nltk",
        "spacy": "spacy",
        "transformers": "transformers",
        "datasets": "datasets",
        "accelerate": "accelerate",
        "diffusers": "diffusers",
        "gradio": "gradio",
        "langchain": "langchain",
        "openai": "openai",
        "anthropic": "anthropic",
        "cohere": "cohere",
        "pinecone": "pinecone-client",
        "chromadb": "chromadb",
        "weaviate": "weaviate-client",
        "faiss": "faiss-cpu",
        "xgboost": "xgboost",
        "lightgbm": "lightgbm",
        "catboost": "catboost",
        "optuna": "optuna",
        "mlflow": "mlflow",
        "airflow": "apache-airflow",
        "prefect": "prefect",
        "dbt": "dbt-core",
        "great-expectations": "great-expectations",
        "evidently": "evidently",
        "dagster": "dagster",
        "polars": "polars",
        "duckdb": "duckdb",
        "duckdb-engine": "duckdb-engine",
        "pydantic-settings": "pydantic-settings",
        "python-multipart": "python-multipart",
        "aiofiles": "aiofiles",
        "httpx": "httpx",
        "pytest-asyncio": "pytest-asyncio",
        "pytest-cov": "pytest-cov",
        "pytest-mock": "pytest-mock",
        "types-requests": "types-requests",
        "types-pyyaml": "types-pyyaml",
    }

    # 标准库模块（不需要安装）
    STANDARD_LIBRARY = {
        "os",
        "sys",
        "time",
        "datetime",
        "json",
        "csv",
        "xml",
        "re",
        "math",
        "random",
        "collections",
        "itertools",
        "functools",
        "logging",
        "unittest",
        "abc",
        "pathlib",
        "dataclasses",
        "typing",
        "enum",
        "asyncio",
        "concurrent",
        "threading",
        "multiprocessing",
        "subprocess",
        "socket",
        "http",
        "urllib",
        "hashlib",
        "hmac",
        "base64",
        "pickle",
        "io",
        "gzip",
        "zipfile",
        "tarfile",
        "tempfile",
        "shutil",
        "glob",
        "fnmatch",
        "getpass",
        "argparse",
        "configparser",
        "warnings",
        "traceback",
        "debug",
        "inspect",
        "dis",
        "ast",
        "tokenize",
        "code",
        "codecs",
        "encodings",
        "locale",
        "calendar",
        "numbers",
        "decimal",
        "fractions",
        "statistics",
        "array",
        "bisect",
        "heapq",
        "queue",
        "deque",
        "defaultdict",
        "OrderedDict",
        "Counter",
        "ChainMap",
        "UserDict",
        "UserList",
        "UserString",
        "namedtuple",
        "Callable",
        "Iterator",
        "Iterable",
        "List",
        "Dict",
        "Set",
        "Tuple",
        "Optional",
        "Union",
        "Any",
        "Type",
        "Generic",
        "NewType",
        "Protocol",
        "Literal",
        "Final",
        "overload",
        "cast",
        "get_type_hints",
        "TypedDict",
        "dataclass",
        "field",
        "asdict",
        "astuple",
        "make_dataclass",
        "replace",
        "is_dataclass",
        "fields",
        "MISSING",
    }

    def __init__(self, project_root: str | Path = "."):
        self.project_root = Path(project_root).resolve()

    def _get_installed_packages(self) -> set:
        """获取已安装的包名集合"""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--format", "json"],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return {pkg["name"].lower() for pkg in data}
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError, KeyError) as e:
            logger.debug("get_installed_packages_failed error=%s", e)
        return set()

    def _parse_imports_from_file(self, file_path: Path) -> list[str]:
        """从单个Python文件解析import语句"""
        imports = []
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name.split(".")[0]
                        if module_name not in self.STANDARD_LIBRARY:
                            imports.append(module_name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        module_name = node.module.split(".")[0]
                        if module_name not in self.STANDARD_LIBRARY:
                            imports.append(module_name)
        except (OSError, UnicodeDecodeError, SyntaxError, ValueError) as e:
            logger.debug("parse_imports_from_file_failed file=%s error=%s", file_path, e)
        return imports

    def _scan_project_imports(self) -> set[str]:
        """扫描项目中所有Python文件的import语句"""
        all_imports = set()
        for py_file in self.project_root.rglob("*.py"):
            # 跳过常见的排除目录
            if any(
                exclude in str(py_file)
                for exclude in [
                    "__pycache__",
                    ".git",
                    ".venv",
                    "venv",
                    "node_modules",
                    ".tox",
                    ".eggs",
                    "dist",
                    "build",
                ]
            ):
                continue
            imports = self._parse_imports_from_file(py_file)
            all_imports.update(imports)
        return all_imports

    def _resolve_package_name(self, import_name: str) -> str:
        """将import名称解析为pip包名"""
        return self.PACKAGE_NAME_MAP.get(import_name, import_name)

    def check_missing_packages(self) -> list[str]:
        """
        检查项目中缺失的第三方包。

        Returns:
            缺失包名列表
        """
        project_imports = self._scan_project_imports()
        installed = self._get_installed_packages()

        missing = []
        for import_name in project_imports:
            pkg_name = self._resolve_package_name(import_name)
            if pkg_name.lower() not in installed:
                missing.append(pkg_name)
        return sorted(missing)

    def install_missing_packages(self, packages: list[str] = None) -> DependencyCheckResult:
        """
        安装缺失的包。

        Args:
            packages: 要安装的包列表（默认检查项目并安装所有缺失包）

        Returns:
            DependencyCheckResult
        """
        if packages is None:
            packages = self.check_missing_packages()

        if not packages:
            return DependencyCheckResult(success=True, output="所有依赖已安装")

        installed = []
        failed = []
        outputs = []

        for pkg in packages:
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", pkg],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if result.returncode == 0:
                    installed.append(pkg)
                    outputs.append(f"✅ {pkg} 安装成功")
                else:
                    failed.append(pkg)
                    outputs.append(f"❌ {pkg} 安装失败: {result.stderr[:200]}")
            except Exception as e:
                failed.append(pkg)
                outputs.append(f"❌ {pkg} 安装异常: {str(e)}")

        return DependencyCheckResult(
            success=len(failed) == 0,
            missing_packages=packages,
            installed_packages=installed,
            failed_packages=failed,
            output="\n".join(outputs),
        )

    def generate_requirements(self, output_file: str | Path = None) -> str:
        """
        生成requirements.txt文件。

        Args:
            output_file: 输出文件路径（默认 project_root/requirements.txt）

        Returns:
            生成的内容
        """
        if output_file is None:
            output_file = self.project_root / "requirements.txt"

        project_imports = self._scan_project_imports()
        packages = sorted({self._resolve_package_name(imp) for imp in project_imports})

        content = "\n".join(packages)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content + "\n")

        return content

    def _get_installed_packages_with_versions(self) -> dict:
        """获取已安装包及其版本"""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--format", "json"],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return {pkg["name"].lower(): pkg["version"] for pkg in data}
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError, KeyError) as e:
            logger.debug("get_installed_packages_with_versions_failed error=%s", e)
        return {}

    def _check_outdated_packages(self) -> list[dict]:
        """检查过期包"""
        outdated = []
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--outdated", "--format", "json"],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for pkg in data:
                    outdated.append(
                        {
                            "name": pkg["name"],
                            "installed_version": pkg["version"],
                            "latest_version": pkg["latest_version"],
                        }
                    )
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError, KeyError) as e:
            logger.debug("check_outdated_packages_failed error=%s", e)
        return outdated

    def _parse_requirements(self) -> dict:
        """解析requirements.txt文件"""
        requirements = {}
        req_file = self.project_root / "requirements.txt"
        if req_file.exists():
            with open(req_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        if "==" in line:
                            pkg, ver = line.split("==", 1)
                            requirements[pkg.strip().lower()] = ver.strip()
                        elif ">=" in line:
                            pkg, ver = line.split(">=", 1)
                            requirements[pkg.strip().lower()] = ">=" + ver.strip()
                        else:
                            requirements[line.lower()] = "*"
        return requirements

    def _parse_pyproject(self) -> dict:
        """解析pyproject.toml中的依赖"""
        requirements = {}
        pyproject_file = self.project_root / "pyproject.toml"
        if pyproject_file.exists():
            with open(pyproject_file, encoding="utf-8") as f:
                content = f.read()
            import re

            deps_match = re.search(r"\[project\.dependencies\]\s*\n([\s\S]*?)(?=\[|\Z)", content)
            if deps_match:
                deps_section = deps_match.group(1)
                for line in deps_section.strip().split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        line = line.strip('"').strip("'")
                        if "==" in line:
                            pkg, ver = line.split("==", 1)
                            requirements[pkg.strip().lower()] = ver.strip()
                        elif ">=" in line:
                            pkg, ver = line.split(">=", 1)
                            requirements[pkg.strip().lower()] = ">=" + ver.strip()
                        else:
                            requirements[line.lower()] = "*"
        return requirements

    def find_unused_packages(self) -> list[dict]:
        """
        查找已安装但项目中未使用的包。

        Returns:
            未使用包列表，包含名称和版本
        """
        project_imports = self._scan_project_imports()
        project_packages = {self._resolve_package_name(imp).lower() for imp in project_imports}
        installed = self._get_installed_packages_with_versions()

        unused = []
        for pkg_name, version in installed.items():
            if pkg_name not in project_packages:
                unused.append({"name": pkg_name, "version": version})

        return sorted(unused, key=lambda x: x["name"])

    def analyze_dependencies(self) -> DependencyAnalysisResult:
        """
        全面分析项目依赖。

        Returns:
            DependencyAnalysisResult - 包含缺失、过期、未使用包的详细信息
        """
        project_imports = self._scan_project_imports()
        installed = self._get_installed_packages_with_versions()
        project_packages = {self._resolve_package_name(imp).lower(): imp for imp in project_imports}

        missing = []
        installed_info = []

        for import_name, pkg_name in project_packages.items():
            pkg_name_lower = pkg_name.lower()
            if pkg_name_lower in installed:
                installed_info.append(
                    {
                        "name": pkg_name,
                        "version": installed[pkg_name_lower],
                        "import_name": import_name,
                    }
                )
            else:
                missing.append(
                    {
                        "name": pkg_name,
                        "import_name": import_name,
                    }
                )

        outdated = self._check_outdated_packages()
        unused = self.find_unused_packages()

        requirements = self._parse_requirements()
        pyproject = self._parse_pyproject()

        req_status = ""
        if requirements:
            req_status += f"requirements.txt 包含 {len(requirements)} 个依赖\n"
        if pyproject:
            req_status += f"pyproject.toml 包含 {len(pyproject)} 个依赖\n"
        if not requirements and not pyproject:
            req_status = "未找到 requirements.txt 或 pyproject.toml"

        summary_lines = []
        summary_lines.append(f"项目使用 {len(project_packages)} 个第三方包")
        summary_lines.append(f"已安装 {len(installed_info)} 个包")
        if missing:
            summary_lines.append(f"⚠️ 缺失 {len(missing)} 个包")
        if outdated:
            summary_lines.append(f"🔄 {len(outdated)} 个包有更新版本")
        if unused:
            summary_lines.append(f"🗑️ {len(unused)} 个包未被项目使用")

        return DependencyAnalysisResult(
            success=True,
            missing_packages=missing,
            outdated_packages=outdated,
            unused_packages=unused,
            installed_packages=installed_info,
            requirements_status=req_status,
            summary="\n".join(summary_lines),
        )


# ── 一键测试运行 ──────────────────────────────────────────


class TestRunner:
    """
    测试运行器 — 生成并执行pytest测试用例。

    功能:
    - 自动检测项目中的测试文件
    - 生成基础测试用例模板
    - 执行pytest并返回结果
    - 生成覆盖率报告
    """

    def __init__(self, project_root: str | Path = "."):
        self.project_root = Path(project_root).resolve()

    def _find_test_files(self) -> list[Path]:
        """查找项目中的测试文件"""
        test_files = []
        for pattern in ["test_*.py", "*_test.py"]:
            for file in self.project_root.rglob(pattern):
                if "__pycache__" not in str(file):
                    test_files.append(file)
        return sorted(test_files)

    def _find_source_files(self) -> list[Path]:
        """查找项目中的源文件（排除测试文件）"""
        source_files = []
        for file in self.project_root.rglob("*.py"):
            if "__pycache__" in str(file):
                continue
            if file.name.startswith("test_") or file.name.endswith("_test.py"):
                continue
            if "/tests/" in str(file):
                continue
            source_files.append(file)
        return sorted(source_files)

    def generate_test_template(self, source_file: Path) -> str:
        """为源文件生成测试模板"""
        module_name = source_file.stem
        test_lines = [
            f'"""测试用例 - {module_name}"""',
            "",
            "import pytest",
            f"from {module_name} import *",
            "",
            "",
            f"class Test{module_name.capitalize()}:",
            f'    """{module_name} 模块测试"""',
            "",
            f"    def test_{module_name}_basic(self):",
            '        """基础功能测试"""',
            "        # TODO: 添加测试逻辑",
            "        assert True",
            "",
        ]
        return "\n".join(test_lines)

    def generate_tests(self, overwrite: bool = False) -> dict:
        """
        为项目中的源文件生成测试文件。

        Args:
            overwrite: 是否覆盖已存在的测试文件

        Returns:
            {"created": list, "skipped": list, "error": str}
        """
        source_files = self._find_source_files()
        created = []
        skipped = []

        for source_file in source_files:
            # 跳过__init__.py
            if source_file.name == "__init__.py":
                continue

            # 构建测试文件路径
            test_dir = self.project_root / "tests"
            test_dir.mkdir(exist_ok=True)

            test_file = test_dir / f"test_{source_file.stem}.py"

            if test_file.exists() and not overwrite:
                skipped.append(str(test_file))
                continue

            content = self.generate_test_template(source_file)
            test_file.write_text(content, encoding="utf-8")
            created.append(str(test_file))

        return {"created": created, "skipped": skipped}

    async def run_pytest(self, coverage: bool = False) -> TestResult:
        """
        运行pytest测试。

        Args:
            coverage: 是否生成覆盖率报告

        Returns:
            TestResult
        """
        try:
            cmd = [sys.executable, "-m", "pytest"]

            if coverage:
                cmd.extend(["--cov=", "--cov-report=term-missing"])

            cmd.extend(["-v", "--tb=short"])

            def _run():
                return subprocess.run(
                    cmd,
                    cwd=str(self.project_root),
                    capture_output=True,
                    text=True,
                    timeout=300,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )

            result = await asyncio.to_thread(_run)

            output = result.stdout + result.stderr

            passed = failed = errors = skipped = total = 0
            duration = 0.0

            for line in result.stdout.split("\n"):
                if "passed" in line and "failed" in line:
                    parts = line.split()
                    for part in parts:
                        if part.endswith("passed"):
                            passed = int(part[:-6])
                        elif part.endswith("failed"):
                            failed = int(part[:-6])
                        elif part.endswith("errors"):
                            errors = int(part[:-6])
                        elif part.endswith("skipped"):
                            skipped = int(part[:-7])
                if "in " in line and line.endswith("s"):
                    try:
                        duration = float(line.split("in ")[1].replace("s", ""))
                    except ValueError:
                        pass

            total = passed + failed + errors

            return TestResult(
                success=result.returncode == 0,
                passed=passed,
                failed=failed,
                errors=errors,
                skipped=skipped,
                total=total,
                duration=duration,
                output=output[:5000],
            )

        except FileNotFoundError:
            return TestResult(
                success=False,
                error="pytest 未安装。请运行: pip install pytest",
            )
        except Exception as e:
            return TestResult(
                success=False,
                error=str(e),
            )


# ── 项目脚手架 ────────────────────────────────────────────


class ProjectScaffold:
    """
    项目脚手架 — 快速生成标准项目骨架。

    支持模板:
    - fastapi: FastAPI Web应用
    - streamlit: Streamlit数据可视化应用
    - cli: 命令行工具
    - library: Python库
    """

    FASTAPI_TEMPLATE = {
        "app": {
            "__init__.py": "",
            "main.py": '''"""FastAPI 应用入口"""

from fastapi import FastAPI

app = FastAPI(title="My FastAPI App", version="1.0.0")


@app.get("/")
async def root():
    return {"message": "Hello, World!"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
''',
            "api": {
                "__init__.py": "",
                "v1": {
                    "__init__.py": "",
                    "routes.py": '''"""API v1 路由"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1")


@router.get("/items")
async def get_items():
    return {"items": []}


@router.get("/items/{item_id}")
async def get_item(item_id: int):
    return {"item_id": item_id}
''',
                },
            },
            "schemas": {
                "__init__.py": "",
                "base.py": '''"""Pydantic 数据模型"""

from pydantic import BaseModel


class Item(BaseModel):
    id: int
    name: str
    description: str | None = None
''',
            },
            "services": {
                "__init__.py": "",
                "item_service.py": '''"""业务逻辑服务"""

from app.schemas.base import Item


class ItemService:
    """物品服务"""

    def get_items(self) -> list[Item]:
        return []

    def get_item(self, item_id: int) -> Item | None:
        return None
''',
            },
        },
        "tests": {
            "__init__.py": "",
            "test_api.py": '''"""API 测试"""

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello, World!"}


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
''',
        },
        "requirements.txt": """fastapi==0.115.0
uvicorn==0.31.0
pydantic==2.9.0
pytest==8.0.0
httpx==0.27.0
""",
        "pyproject.toml": """[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "my-fastapi-app"
version = "0.1.0"
description = "A FastAPI application"
requires-python = ">=3.8"
dependencies = [
    "fastapi>=0.100.0",
    "uvicorn>=0.20.0",
    "pydantic>=2.0.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
""",
        ".gitignore": """# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
env/
venv/
.venv/
.tox/
.eggs/
*.egg-info/
dist/
build/
.idea/
.vscode/

# Environment
.env
.env.local
.env.*.local
""",
    }

    STREAMLIT_TEMPLATE = {
        "app.py": '''"""Streamlit 应用"""

import streamlit as st

st.set_page_config(page_title="My Streamlit App", layout="wide")

st.title("Welcome to My Streamlit App")

with st.sidebar:
    st.header("Settings")
    option = st.selectbox("Select an option", ["Option 1", "Option 2", "Option 3"])

st.subheader("Main Content")
st.write(f"You selected: {option}")

if st.button("Click Me"):
    st.success("Button clicked!")

import pandas as pd
import numpy as np

df = pd.DataFrame(
    np.random.randn(10, 3),
    columns=["A", "B", "C"],
)

st.subheader("Data Display")
st.dataframe(df)

st.subheader("Chart")
st.line_chart(df)
''',
        "utils": {
            "__init__.py": "",
            "helpers.py": '''"""工具函数"""

def process_data(data):
    """处理数据"""
    return data
''',
        },
        "requirements.txt": """streamlit==1.30.0
pandas==2.2.0
numpy==1.26.0
""",
        ".streamlit": {
            "config.toml": """[theme]
primaryColor="#6366f1"
backgroundColor="#0f172a"
secondaryBackgroundColor="#1e293b"
textColor="#f1f5f9"
font="sans serif"
""",
        },
        ".gitignore": """# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
env/
venv/
.venv/

# Streamlit
.streamlit/secrets.toml
.streamlit/credentials.toml

# IDE
.idea/
.vscode/
""",
    }

    CLI_TEMPLATE = {
        "my_cli": {
            "__init__.py": '__version__ = "0.1.0"',
            "cli.py": '''"""命令行工具入口"""

import argparse

from my_cli.commands import hello, process


def main():
    parser = argparse.ArgumentParser(description="My CLI Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # hello 命令
    hello_parser = subparsers.add_parser("hello", help="Say hello")
    hello_parser.add_argument("name", help="Your name")

    # process 命令
    process_parser = subparsers.add_parser("process", help="Process data")
    process_parser.add_argument("input", help="Input file")
    process_parser.add_argument("-o", "--output", help="Output file")

    args = parser.parse_args()

    if args.command == "hello":
        hello(args.name)
    elif args.command == "process":
        process(args.input, args.output)


if __name__ == "__main__":
    main()
''',
            "commands": {
                "__init__.py": "",
                "hello.py": '''"""hello 命令"""

def hello(name: str):
    """Say hello to someone"""
    print(f"Hello, {name}!")
''',
                "process.py": '''"""process 命令"""

def process(input_file: str, output_file: str | None = None):
    """Process data from input file"""
    print(f"Processing: {input_file}")
    if output_file:
        print(f"Output: {output_file}")
''',
            },
        },
        "tests": {
            "__init__.py": "",
            "test_commands.py": '''"""命令测试"""

import pytest
from my_cli.commands import hello


def test_hello(capsys):
    hello("World")
    captured = capsys.readouterr()
    assert captured.out.strip() == "Hello, World!"
''',
        },
        "requirements.txt": """click==8.0.0
pytest==8.0.0
""",
        "pyproject.toml": """[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "my-cli"
version = "0.1.0"
description = "A CLI tool"
requires-python = ">=3.8"
dependencies = ["click>=8.0.0"]
entry-points = {
    "console_scripts": [
        "my-cli=my_cli.cli:main",
    ],
}

[tool.pytest.ini_options]
testpaths = ["tests"]
""",
        ".gitignore": """# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
env/
venv/
.venv/
.tox/
.eggs/
*.egg-info/
dist/
build/
.idea/
.vscode/

# Environment
.env
""",
    }

    LIBRARY_TEMPLATE = {
        "my_library": {
            "__init__.py": '__version__ = "0.1.0"',
            "core.py": '''"""核心功能"""

def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b


def multiply(a: int, b: int) -> int:
    """Multiply two numbers"""
    return a * b
''',
            "utils.py": '''"""工具函数"""

def format_result(value):
    """格式化结果"""
    return f"Result: {value}"
''',
        },
        "tests": {
            "__init__.py": "",
            "test_core.py": '''"""核心功能测试"""

import pytest
from my_library.core import add, multiply


def test_add():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0


def test_multiply():
    assert multiply(2, 3) == 6
    assert multiply(0, 5) == 0
''',
        },
        "requirements.txt": """pytest==8.0.0
""",
        "pyproject.toml": """[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "my-library"
version = "0.1.0"
description = "A Python library"
requires-python = ">=3.8"
dependencies = []

[tool.pytest.ini_options]
testpaths = ["tests"]
""",
        "README.md": """# My Library

A Python library.

## Installation

```bash
pip install my-library
```

## Usage

```python
from my_library.core import add, multiply

result = add(2, 3)
print(result)
```

## Development

```bash
# Install dependencies
pip install -e .

# Run tests
pytest
```
""",
        ".gitignore": """# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
env/
venv/
.venv/
.tox/
.eggs/
*.egg-info/
dist/
build/
.idea/
.vscode/

# Environment
.env
""",
    }

    TEMPLATES = {
        "fastapi": FASTAPI_TEMPLATE,
        "streamlit": STREAMLIT_TEMPLATE,
        "cli": CLI_TEMPLATE,
        "library": LIBRARY_TEMPLATE,
    }

    def __init__(self, project_root: str | Path = "."):
        self.project_root = Path(project_root).resolve()

    def create_project(self, project_name: str, project_type: str) -> ScaffoldResult:
        """
        创建项目骨架。

        Args:
            project_name: 项目名称
            project_type: 项目类型 (fastapi/streamlit/cli/library)

        Returns:
            ScaffoldResult
        """
        if project_type not in self.TEMPLATES:
            return ScaffoldResult(
                success=False,
                error=f"不支持的项目类型: {project_type}。支持的类型: {', '.join(self.TEMPLATES.keys())}",
            )

        template = self.TEMPLATES[project_type]
        project_path = self.project_root / project_name

        # 检查项目目录是否已存在
        if project_path.exists():
            return ScaffoldResult(
                success=False,
                error=f"项目目录已存在: {project_path}",
            )

        files_created = []
        dirs_created = []

        try:
            project_path.mkdir(parents=True, exist_ok=True)
            dirs_created.append(str(project_path))

            self._create_files(project_path, template, files_created, dirs_created)

            return ScaffoldResult(
                success=True,
                project_name=project_name,
                project_type=project_type,
                files_created=files_created,
                directories_created=dirs_created,
            )

        except Exception as e:
            return ScaffoldResult(
                success=False,
                error=f"创建项目失败: {str(e)}",
            )

    def _create_files(self, base_path: Path, template: dict, files: list, dirs: list):
        """递归创建文件和目录"""
        for name, content in template.items():
            path = base_path / name

            if isinstance(content, dict):
                # 目录
                path.mkdir(exist_ok=True)
                dirs.append(str(path))
                self._create_files(path, content, files, dirs)
            else:
                # 文件
                path.write_text(content, encoding="utf-8")
                files.append(str(path))


# ── 快捷函数 ─────────────────────────────────────────────


def check_and_install_deps(project_root: str | Path = ".") -> DependencyCheckResult:
    """检查并安装缺失依赖"""
    dm = DependencyManager(project_root)
    return dm.install_missing_packages()


def run_tests(project_root: str | Path = ".", coverage: bool = False) -> TestResult:
    """运行测试"""
    tr = TestRunner(project_root)
    return tr.run_pytest(coverage=coverage)


def scaffold_project(
    project_name: str, project_type: str, project_root: str | Path = "."
) -> ScaffoldResult:
    """创建项目骨架"""
    ps = ProjectScaffold(project_root)
    return ps.create_project(project_name, project_type)


# ══════════════════════════════════════════════════════════
# 依赖智能体 — 自动检测 import → 安装缺失包
# ══════════════════════════════════════════════════════════


async def auto_dep_agent(code: str, ws_send: callable = None) -> dict:
    """
    依赖智能体 — 从代码中提取所有 import → 检查安装状态 → 自动安装缺失包。

    Args:
        code: Python 代码字符串
        ws_send: 可选的 WebSocket 发送函数，用于推送实时状态

    Returns:
        {"installed": ["loguru"], "already_had": ["httpx"],
        "failed": [{"package": "xxx", "error": "..."}]}
    """
    imports = _extract_imports_from_code(code)
    installed_list = []
    already_list = []
    failed_list = []

    # 获取已安装包集合
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode == 0:
            installed_pkgs = {pkg["name"].lower() for pkg in json.loads(result.stdout)}
        else:
            installed_pkgs = set()
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError, KeyError) as e:
        logger.debug("fetch_installed_pkgs_failed error=%s", e)
        installed_pkgs = set()

    for mod_name, pip_name in imports.items():
        pkg_lower = pip_name.lower()

        # 跳过标准库
        if mod_name in DependencyManager.STANDARD_LIBRARY:
            continue
        if pkg_lower in installed_pkgs:
            already_list.append(pip_name)
            continue

        # 尝试安装
        try:
            if ws_send:
                try:
                    await ws_send(
                        json.dumps(
                            {
                                "type": "dep_agent_step",
                                "package": pip_name,
                                "status": "installing",
                            }
                        )
                    )
                except Exception as e:
                    logger.debug("ws_send_installing_failed pkg=%s error=%s", pip_name, e)

            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "pip",
                "install",
                pip_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

            if proc.returncode == 0:
                installed_list.append(pip_name)
            else:
                err_text = stderr.decode("utf-8", errors="replace")[:200]
                failed_list.append({"package": pip_name, "error": err_text})

            if ws_send:
                try:
                    await ws_send(
                        json.dumps(
                            {
                                "type": "dep_agent_step",
                                "package": pip_name,
                                "status": "done" if proc.returncode == 0 else "failed",
                            }
                        )
                    )
                except Exception as e:
                    logger.debug("ws_send_done_failed pkg=%s error=%s", pip_name, e)

        except TimeoutError:
            failed_list.append({"package": pip_name, "error": "安装超时 (60s)"})
        except Exception as e:
            failed_list.append({"package": pip_name, "error": str(e)[:200]})

    return {
        "installed": installed_list,
        "already_had": already_list,
        "failed": failed_list,
    }


def _extract_imports_from_code(code: str) -> dict[str, str]:
    """
    从代码字符串中提取所有 import，返回 {模块名: pip包名} 映射。

    支持:
        import requests
        from fastapi import FastAPI
        import numpy as np
        from PIL import Image
    """
    imports = {}

    try:
        tree = ast.parse(code)
    except SyntaxError:
        # 语法错误时用正则回退
        for line in code.splitlines():
            line = line.strip()
            if line.startswith("import "):
                parts = line[7:].split(",")
                for p in parts:
                    mod = p.strip().split()[0]
                    imports[mod] = DependencyManager.PACKAGE_NAME_MAP.get(mod, mod)
            elif line.startswith("from "):
                parts = line.split()
                if len(parts) >= 2:
                    mod = parts[1].split(".")[0]
                    if mod not in ("__future__", "typing", "abc"):
                        imports[mod] = DependencyManager.PACKAGE_NAME_MAP.get(mod, mod)
        return imports

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                imports[mod] = DependencyManager.PACKAGE_NAME_MAP.get(mod, mod)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level is None:
                mod = node.module.split(".")[0]
                if mod not in ("__future__", "typing", "abc"):
                    imports[mod] = DependencyManager.PACKAGE_NAME_MAP.get(mod, mod)

    return imports
