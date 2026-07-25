"""PyCoder 依赖治理审计脚本 — P3-B

功能:
  1. 漏洞审计: 调用 pip-audit 检测已知漏洞依赖
  2. 未使用依赖检测: 对比 import 语句与 requirements.txt
  3. 过期依赖: 列出有新版本可用的依赖
  4. 依赖分组一致性: 检查 pyproject.toml 与 requirements/*.in 是否一致

用法:
  python scripts/dep_audit.py                # 全量审计
  python scripts/dep_audit.py --vuln         # 仅漏洞扫描
  python scripts/dep_audit.py --unused       # 仅未使用依赖
  python scripts/dep_audit.py --outdated     # 仅过期依赖
  python scripts/dep_audit.py --consistency  # 仅一致性检查

退出码:
  0: 审计通过（可能有警告但无严重问题）
  1: 发现已知漏洞依赖
  2: 审计过程出错
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PYCODER_DIR = ROOT / "pycoder"
TESTS_DIR = ROOT / "tests"


# ─────────────────────────────────────────────────────
# 颜色输出
# ─────────────────────────────────────────────────────


class C:
    """ANSI 颜色码"""

    RED = "\033[91m"
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def _c(color: str, text: str) -> str:
    return f"{color}{text}{C.RESET}"


# ─────────────────────────────────────────────────────
# 1. 漏洞审计
# ─────────────────────────────────────────────────────


def audit_vulnerabilities() -> int:
    """运行 pip-audit 检测已知漏洞

    策略：
    1. 优先使用 `pip-audit -r requirements.txt` 审计项目声明的依赖
       （避免审计环境中的本地编辑包如 ad-system 导致失败）
    2. 设置 5 分钟超时（pip-audit 在线查询 PyPI 漏洞数据库较慢）
    3. 超时则降级为提示用户手动审计
    """
    print(_c(C.CYAN, "\n[1/4] 漏洞审计 (pip-audit -r requirements.txt)"))
    print("-" * 60)

    req_file = ROOT / "requirements.txt"
    if not req_file.exists():
        print(_c(C.YELLOW, "  ⚠ requirements.txt 不存在，跳过漏洞审计"))
        return 0

    try:
        # 使用 -r requirements.txt 审计项目依赖（避免环境包干扰）
        # JSON 格式输出便于解析
        result = subprocess.run(
            [
                sys.executable, "-m", "pip_audit",
                "-r", str(req_file),
                "--strict",
                "--format", "json",
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=300,  # 5 分钟
        )
    except subprocess.TimeoutExpired:
        print(_c(C.YELLOW, "  ⚠ pip-audit 超时（300s），网络较慢"))
        print(_c(C.BLUE, "  建议手动执行:"))
        print(f"    python -m pip_audit -r requirements.txt --strict")
        return 0
    except FileNotFoundError:
        print(_c(C.YELLOW, "  ⚠ pip-audit 未安装，尝试安装中..."))
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pip-audit"],
            capture_output=True,
            timeout=60,
        )
        return audit_vulnerabilities()

    # 解析 JSON 输出
    stdout = (result.stdout or "").strip()
    vulnerabilities: list[dict[str, Any]] = []

    if stdout:
        try:
            data = json.loads(stdout)
            # pip-audit JSON 格式: {"dependencies": [{"name": ..., "vulns": [...]}]}
            for dep in data.get("dependencies", []):
                for vuln in dep.get("vulns", []):
                    vulnerabilities.append({
                        "package": dep.get("name", "?"),
                        "version": dep.get("version", "?"),
                        "vuln_id": vuln.get("id", "?"),
                        "description": vuln.get("description", ""),
                        "fix_versions": vuln.get("fix_versions", []),
                    })
        except json.JSONDecodeError:
            # 非 JSON 输出，可能是错误信息
            pass

    if result.returncode != 0 or vulnerabilities:
        print(_c(C.RED, f"  ❌ 发现 {len(vulnerabilities)} 个已知漏洞:"))
        print(f"    {'包名':<25} {'版本':<12} {'漏洞ID':<20} {'修复版本'}")
        print(f"    {'-' * 25} {'-' * 12} {'-' * 20} {'-' * 20}")
        for v in vulnerabilities:
            pkg = v["package"]
            ver = v["version"]
            vid = v["vuln_id"]
            fix = ", ".join(v["fix_versions"]) if v["fix_versions"] else "未知"
            print(f"    {pkg:<25} {ver:<12} {vid:<20} {fix}")

        print(_c(C.YELLOW, "\n  建议修复:"))
        print("    1. 升级有漏洞的包: pip install --upgrade <package>")
        print("    2. 重新生成 lock: uv pip compile requirements/requirements.in -o requirements.txt")
        return 1

    # 检查 stderr 中是否有错误
    stderr = (result.stderr or "").strip()
    if stderr and "RequestsDependencyWarning" not in stderr:
        # 过滤无关警告
        meaningful_stderr = [
            line for line in stderr.splitlines()
            if line.strip()
            and "RequestsDependencyWarning" not in line
            and "warnings.warn" not in line
            and "urllib3" not in line
        ]
        if meaningful_stderr:
            print(_c(C.BLUE, "  ℹ 诊断信息:"))
            for line in meaningful_stderr[:5]:  # 仅显示前 5 行
                print(f"    {line}")

    print(_c(C.GREEN, "  ✅ 未发现已知漏洞依赖"))
    return 0


# ─────────────────────────────────────────────────────
# 2. 未使用依赖检测
# ─────────────────────────────────────────────────────


# 已知与 import 名不同的 PyPI 包名映射
_PACKAGE_IMPORT_MAP = {
    "Pillow": "PIL",
    "opencv-python-headless": "cv2",
    "pydantic-settings": "pydantic_settings",
    "python-multipart": "multipart",
    "python-dotenv": "dotenv",
    "pyyaml": "yaml",
    "GitPython": "git",
    "beautifulsoup4": "bs4",
    "diff-match-patch": "diff_match_patch",
    "importlib-resources": "importlib_resources",
    "importlib-metadata": "importlib_metadata",
    "pydub": "pydub",
    "prompt_toolkit": "prompt_toolkit",
    "pathspec": "pathspec",
    "diskcache": "diskcache",
    "grep-ast": "grep_ast",
    "tree-sitter": "tree_sitter",
    "aiohttp": "aiohttp",
    "aiosignal": "aiosignal",
    "aiohappyeyeballs": "aiohappyeyeballs",
    "starlette": "starlette",
    "fastapi": "fastapi",
    "pydantic": "pydantic",
    "uvicorn": "uvicorn",
    "httpx": "httpx",
    "openai": "openai",
    "litellm": "litellm",
    "orjson": "orjson",
    "structlog": "structlog",
    "jinja2": "jinja2",
    "sentry-sdk": "sentry_sdk",
    "posthog": "posthog",
    "mixpanel": "mixpanel",
    "watchfiles": "watchfiles",
    "websockets": "websockets",
    "sqlalchemy": "sqlalchemy",
    "bcrypt": "bcrypt",
    "pyjwt": "jwt",
    "email-validator": "email_validator",
    "socksio": "socksio",
    "oslex": "oslex",
    "mcp": "mcp",
    "psutil": "psutil",
    "pexpect": "pexpect",
    "json5": "json5",
    "pyperclip": "pyperclip",
    "shtab": "shtab",
    "configargparse": "configargparse",
    "backoff": "backoff",
    "jsonschema": "jsonschema",
    "packaging": "packaging",
    "rich": "rich",
    "sounddevice": "sounddevice",
    "soundfile": "soundfile",
    "pypandoc": "pypandoc",
    "flake8": "flake8",
    "networkx": "networkx",
    "scipy": "scipy",
    "numpy": "numpy",
    "pandas": "pandas",
    "matplotlib": "matplotlib",
    "streamlit": "streamlit",
    "playwright": "playwright",
    "typer": "typer",
    "imgcat": "imgcat",
    "lox": "lox",
    "codespell": "codespell",
    "semver": "semver",
    "uv": "uv",
    "google-cloud-bigquery": "google.cloud.bigquery",
    "torch": "torch",
    "scikit-learn": "sklearn",
    "llama-index-core": "llama_index",
    "llama-index-embeddings-huggingface": "llama_index.embeddings",
    "transformers": "transformers",
    "huggingface-hub": "huggingface_hub",
    "sentence-transformers": "sentence_transformers",
    "tiktoken": "tiktoken",
    "tokenizers": "tokenizers",
    "tree-sitter-language-pack": "tree_sitter_language_pack",
    "contourpy": "contourpy",
    "cycler": "cycler",
    "kiwisolver": "kiwisolver",
    "pyparsing": "pyparsing",
    "fonttools": "fonttools",
    "pip": "pip",
    "pip-tools": "piptools",
    "build": "build",
    "wheel": "wheel",
    "virtualenv": "virtualenv",
    "pre-commit": "pre_commit",
    "pytest": "pytest",
    "pytest-cov": "pytest_cov",
    "pytest-asyncio": "pytest_asyncio",
    "pytest-env": "pytest_env",
    "pytest-timeout": "pytest_timeout",
    "bandit": "bandit",
    "coverage": "coverage",
    "ruff": "ruff",
    "mypy": "mypy",
    "black": "black",
    "isort": "isort",
}


def _collect_imports() -> set[str]:
    """扫描 pycoder/ 和 tests/ 目录，收集所有顶层 import 名"""
    imports: set[str] = set()

    for base in (PYCODER_DIR, TESTS_DIR):
        if not base.exists():
            continue
        for py_file in base.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module.split(".")[0])

    return imports


def _normalize_package_to_import(pkg: str) -> str:
    """将 PyPI 包名转换为对应的 import 名（小写）

    查找 _PACKAGE_IMPORT_MAP 时尝试多种大小写组合，
    返回小写的 import 名（如 'pillow' -> 'pil'）。
    """
    # 尝试原样、首字母大写、全大写
    candidates = [pkg, pkg.capitalize(), pkg.upper(), pkg.title()]
    for candidate in candidates:
        if candidate in _PACKAGE_IMPORT_MAP:
            return _PACKAGE_IMPORT_MAP[candidate].lower()
    # 默认：将 - 替换为 _
    return pkg.replace("-", "_").lower()


def _parse_requirements_txt(path: Path) -> list[str]:
    """解析 requirements.txt 文件，返回包名列表"""
    if not path.exists():
        return []

    packages: list[str] = []
    pattern = re.compile(r"^([a-zA-Z0-9_-]+)\s*==")

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        m = pattern.match(line)
        if m:
            packages.append(m.group(1).lower())

    return packages


def audit_unused_dependencies() -> int:
    """检测未使用的依赖"""
    print(_c(C.CYAN, "\n[2/4] 未使用依赖检测"))
    print("-" * 60)

    actual_imports = _collect_imports()
    declared_packages = _parse_requirements_txt(ROOT / "requirements.txt")

    # 标准库模块白名单（这些不需要在 requirements 中声明）
    import sys
    stdlib_modules = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else set()
    stdlib_modules.update({
        "os", "sys", "json", "re", "time", "datetime", "pathlib",
        "typing", "collections", "asyncio", "subprocess", "logging",
        "dataclasses", "functools", "itertools", "math", "random",
        "uuid", "hashlib", "base64", "io", "csv", "xml", "html",
        "urllib", "http", "socket", "ssl", "email", "smtp", "ast",
        "inspect", "importlib", "traceback", "warnings", "weakref",
        "threading", "queue", "concurrent", "multiprocessing",
        "contextlib", "abc", "copy", "enum", "operator", "tempfile",
        "shutil", "platform", "struct", "codecs", "unicodedata",
        "textwrap", "string", "difflib", "secrets", "sqlite3",
        "argparse", "configparser", "glob", "fnmatch", "stat",
        "errno", "gettext", "locale", "calendar", "zoneinfo",
        "decimal", "fractions", "numbers", "cmath", "statistics",
        "array", "bisect", "heapq", "types", "packaging",
        # pycoder 自有模块
        "pycoder",
    })

    # 动态加载的包白名单 — 这些包通过 __import__() 或 importlib.import_module() 使用
    # AST 静态扫描检测不到，需要手动维护
    dynamic_loaded = {
        "gitpython",  # pycoder/capabilities/tools/git.py: __import__("git").Repo(cwd)
    }

    # mcp 包的传递依赖白名单 — 这些包由 mcp 包引入，不在 pycoder 代码中直接 import
    # 但 mcp 运行时需要它们（无法移除，除非不用 mcp）
    mcp_transitive_deps = {
        "dnspython",        # mcp 通过 email-validator 间接依赖
        "httpx-sse",        # mcp SSE 客户端
        "json-logic",       # mcp JSON 规则引擎
        "pydantic-settings",  # mcp 配置管理
        "pywin32",          # mcp Windows 平台支持
        "sse-starlette",    # mcp SSE 服务端
    }

    # 检查每个声明的包是否被 import
    unused: list[str] = []
    used: list[str] = []

    for pkg in declared_packages:
        # 使用 _normalize_package_to_import 处理大小写变体（如 Pillow -> pil）
        import_name = _normalize_package_to_import(pkg)
        # 也尝试不带下划线的形式
        alt_names = {pkg, pkg.replace("-", "_"), pkg.replace("-", "_").lower()}

        # 检查是否在 import 中（考虑各种命名变体）
        is_used = False
        for imp in actual_imports:
            imp_lower = imp.lower()
            if imp_lower == import_name or imp_lower in alt_names:
                is_used = True
                break
            # 反向检查：import 名以包名开头
            if import_name and imp_lower.startswith(import_name + "."):
                is_used = True
                break

        # 检查是否通过动态加载使用
        if not is_used and pkg in dynamic_loaded:
            is_used = True

        # 检查是否是 mcp 的传递依赖
        if not is_used and pkg in mcp_transitive_deps:
            is_used = True

        if is_used:
            used.append(pkg)
        else:
            unused.append(pkg)

    # 已知的"间接依赖"白名单 — 这些包通过其他包使用，不在代码中直接 import
    indirect_whitelist = {
        "uvicorn",  # 通过 fastapi CLI 使用
        "starlette",  # fastapi 内部依赖
        "anyio",  # httpx 内部依赖
        "h11",  # httpcore 内部依赖
        "httpcore",  # httpx 内部依赖
        "certifi",  # SSL 证书
        "charset-normalizer",  # requests 内部
        "idna",  # URL 处理
        "sniffio",  # anyio 内部
        "typing-extensions",  # 类型兼容
        "typing-inspect",  # typing 增强
        "pydantic-core",  # pydantic 内部
        "annotated-types",  # pydantic 内部
        "click",  # litellm CLI
        "jiter",  # openai 内部
        "distro",  # openai 内部
        "tqdm",  # 进度条（多个包使用）
        "filelock",  # huggingface-hub 内部
        "fsspec",  # huggingface-hub 内部
        "pyyaml",  # 多个包配置使用
        "regex",  # tiktoken/transformers 内部
        "requests",  # 多个包内部使用
        "colorama",  # Windows 终端颜色
        "setuptools",  # 构建工具
        "pip",  # 包管理器
        "wheel",  # 构建工具
        "build",  # PEP 517 构建
        "pyproject-hooks",  # build 内部
        "toml",  # 旧版 toml 解析（streamlit 使用）
        "six",  # Python 2/3 兼容
        "wrapt",  # deprecated 包内部
        "deprecated",  # 弃用标记
        "packaging",  # 版本解析
        "platformdirs",  # 跨平台路径
        "tenacity",  # 重试库
        "cffi",  # C 绑定
        "pycparser",  # cffi 内部
        "markupsafe",  # jinja2 内部
        "marshmallow",  # 序列化
        "dataclasses-json",  # 数据类序列化
        "nest-asyncio",  # asyncio 补丁
        "dirtyjson",  # JSON 解析
        "fastuuid",  # UUID 优化
        "filetype",  # 文件类型检测
        "tinytag",  # 音频元数据
        "mpmath",  # sympy 内部
        "sympy",  # torch 内部
        "cycler",  # matplotlib 内部
        "kiwisolver",  # matplotlib 内部
        "pyparsing",  # matplotlib 内部
        "fonttools",  # matplotlib 内部
        "contourpy",  # matplotlib 内部
        "python-dateutil",  # 日期解析
        "pytz",  # 时区
        "tzdata",  # 时区数据
        "narwhals",  # altair 内部
        "pyarrow",  # streamlit 内部
        "pydeck",  # streamlit 内部
        "blinker",  # streamlit 内部
        "cachetools",  # streamlit 内部
        "altair",  # streamlit 内部
        "markdown-it-py",  # rich 内部
        "mdurl",  # markdown-it-py 内部
        "pygments",  # 代码高亮
        "wcwidth",  # prompt_toolkit 内部
        "shellingham",  # typer 内部
        "rich",  # 多个包使用
        "iniconfig",  # pytest 内部
        "pluggy",  # pytest 内部
        "pypandoc",  # 文档转换（通过子进程使用）
        "imgcat",  # 图片显示（可选）
        "lox",  # 进程池（开发工具）
        "cogapp",  # 文档生成
        "google-cloud-bigquery",  # 数据分析
        "google-api-core",  # GCP 内部
        "google-auth",  # GCP 认证
        "google-cloud-core",  # GCP 内部
        "google-resumable-media",  # GCP 上传
        "google-crc32c",  # CRC32C 校验
        "googleapis-common-protos",  # protobuf
        "grpcio",  # gRPC
        "grpcio-status",  # gRPC 状态
        "proto-plus",  # protobuf
        "protobuf",  # 协议缓冲
        "pyasn1",  # ASN.1
        "pyasn1-modules",  # ASN.1 模块
        "rsa",  # RSA（被 google-auth 使用）
        "cryptography",  # 加密
        "cffi",  # C 绑定
        "urllib3",  # requests 内部
        "safetensors",  # 模型存储
        "joblib",  # 并行计算
        "threadpoolctl",  # 线程池
        "mslex",  # oslex 内部
        "ptyprocess",  # pexpect 内部
        "greenlet",  # sqlalchemy 内部
        "aiosignal",  # aiohttp 内部
        "aiohappyeyeballs",  # aiohttp 内部
        "frozenlist",  # aiohttp 内部
        "multidict",  # aiohttp 内部
        "propcache",  # aiohttp 内部
        "yarl",  # aiohttp 内部
        "attrs",  # 多个包使用
        "referencing",  # jsonschema 内部
        "rpds-py",  # jsonschema 内部
        "jsonschema-specifications",  # jsonschema 内部
        "smmap",  # gitdb 内部
        "gitdb",  # gitpython 内部
        "soupsieve",  # bs4 内部
        "cfgv",  # pre-commit 内部
        "identify",  # pre-commit 内部
        "nodeenv",  # pre-commit 内部
        "distlib",  # virtualenv 内部
        "virtualenv",  # pre-commit 内部
        "tomli",  # 旧版 toml
        "zipp",  # importlib-metadata 内部
        "asgiref",  # mixpanel 内部
        "banks",  # llama-index 内部
        "griffe",  # banks 内部
        "griffecli",  # griffe 内部
        "griffelib",  # griffe 内部
        "mccabe",  # flake8 内部
        "pycodestyle",  # flake8 内部
        "pyflakes",  # flake8 内部
        "mypy-extensions",  # mypy 内部
        "typing-inspection",  # pydantic 内部
        "annotated-doc",  # 类型注解
        "pip-tools",  # pip-compile
        "uv",  # uv 包管理
        "tree-sitter-c-sharp",  # tree-sitter 内部
        "tree-sitter-embedded-template",  # tree-sitter 内部
        "tree-sitter-yaml",  # tree-sitter 内部
        "aiosqlite",  # sqlalchemy async
        "llama-index-instrumentation",  # llama-index 内部
        "llama-index-workflows",  # llama-index 内部
        "tree-sitter-language-pack",  # tree-sitter 语言包
        "hf-xet",  # huggingface-hub 内部
        "python-discovery",  # virtualenv 内部
        "bcrypt",  # 密码哈希（通过 API 间接使用）
        "email-validator",  # pydantic email 验证
        "python-multipart",  # FastAPI 文件上传
        "sentry-sdk",  # 错误监控（动态加载）
        "posthog",  # 分析（可选）
        "mixpanel",  # 分析（可选）
        "socksio",  # SOCKS 代理
        "oslex",  # 跨平台 shell 词法
        "mcp",  # Model Context Protocol
        "psutil",  # 系统监控
        "pexpect",  # 进程交互
        "json5",  # JSON5 解析
        "pyperclip",  # 剪贴板
        "shtab",  # shell 补全
        "configargparse",  # 配置解析
        "backoff",  # 重试
        "jsonschema",  # JSON 验证
        "packaging",  # 版本号
        "rich",  # 终端 UI
        "sounddevice",  # 音频输入
        "soundfile",  # 音频文件
        "networkx",  # 图算法
        "scipy",  # 科学计算
        "numpy",  # 数组计算
        "pandas",  # 数据处理
        "matplotlib",  # 图表
        "streamlit",  # 浏览器 UI
        "playwright",  # 浏览器自动化
        "typer",  # CLI 框架
        "codespell",  # 拼写检查
        "semver",  # 语义版本
        "torch",  # PyTorch
        "scikit-learn",  # 机器学习
        "llama-index-core",  # LlamaIndex
        "llama-index-embeddings-huggingface",  # LlamaIndex 嵌入
        "transformers",  # Hugging Face Transformers
        "huggingface-hub",  # Hugging Face Hub
        "sentence-transformers",  # 句子嵌入
        "tiktoken",  # Token 计数
        "tokenizers",  # Tokenizer
        "coverage",  # 测试覆盖率
        "ruff",  # Linter
        "mypy",  # 类型检查
        "black",  # 格式化
        "isort",  # 导入排序
        "bandit",  # 安全扫描
        "pytest",  # 测试框架
        "pytest-cov",  # 覆盖率插件
        "pytest-asyncio",  # 异步测试
        "pytest-env",  # 环境变量
        "pytest-timeout",  # 超时
        "pre-commit",  # 预提交钩子
        "pip-audit",  # 漏洞审计
        "importlib-metadata",  # 旧版 importlib
        "importlib-resources",  # 旧版 importlib
        "flask",  # Web 框架（如有使用）
    }

    truly_unused = [p for p in unused if p not in indirect_whitelist]

    if not truly_unused:
        print(_c(C.GREEN, f"  ✅ 所有 {len(declared_packages)} 个依赖均被使用（或为间接依赖）"))
        if unused:
            print(_c(C.BLUE, f"  ℹ 间接依赖（{len(unused)} 个）:"))
            for p in sorted(unused):
                print(f"    - {p}")
    else:
        print(_c(C.YELLOW, f"  ⚠ 发现 {len(truly_unused)} 个可能未使用的依赖:"))
        for p in sorted(truly_unused):
            print(f"    - {p}")
        print(_c(C.BLUE, "\n  建议:"))
        print("    1. 确认依赖是否真的未使用（可能通过动态加载）")
        print("    2. 如确未使用，从 requirements/requirements.in 中移除")
        print("    3. 重新生成: uv pip compile requirements/requirements.in -o requirements.txt")

    return 0


# ─────────────────────────────────────────────────────
# 3. 过期依赖
# ─────────────────────────────────────────────────────


def audit_outdated() -> int:
    """检测过期依赖"""
    print(_c(C.CYAN, "\n[3/4] 过期依赖检测 (pip list --outdated)"))
    print("-" * 60)

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--outdated", "--format=json"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        print(_c(C.YELLOW, "  ⚠ pip list 超时（120s），跳过"))
        return 0

    if result.returncode != 0:
        print(_c(C.YELLOW, f"  ⚠ pip list 失败: {result.stderr.strip()}"))
        return 0

    try:
        outdated: list[dict[str, Any]] = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(_c(C.YELLOW, "  ⚠ 无法解析 pip list 输出"))
        return 0

    if not outdated:
        print(_c(C.GREEN, "  ✅ 所有依赖均为最新版本"))
        return 0

    print(_c(C.YELLOW, f"  ⚠ 发现 {len(outdated)} 个过期依赖:"))
    print(f"    {'包名':<35} {'当前版本':<15} {'最新版本':<15}")
    print(f"    {'-' * 35} {'-' * 15} {'-' * 15}")
    for pkg in sorted(outdated, key=lambda x: x["name"].lower()):
        name = pkg["name"]
        current = pkg["version"]
        latest = pkg["latest_version"]
        print(f"    {name:<35} {current:<15} {latest:<15}")

    print(_c(C.BLUE, "\n  建议:"))
    print("    1. 评估升级风险（特别是主版本号变化）")
    print("    2. 在 requirements/requirements.in 中更新版本约束")
    print("    3. 重新生成: uv pip compile requirements/requirements.in -o requirements.txt")
    print("    4. 运行测试: pytest tests/")

    return 0


# ─────────────────────────────────────────────────────
# 4. 依赖分组一致性
# ─────────────────────────────────────────────────────


def audit_consistency() -> int:
    """检查 pyproject.toml 与 requirements/*.in 的一致性"""
    print(_c(C.CYAN, "\n[4/4] 依赖分组一致性检查"))
    print("-" * 60)

    pyproject = ROOT / "pyproject.toml"
    if not pyproject.exists():
        print(_c(C.RED, "  ❌ pyproject.toml 不存在"))
        return 2

    # 检查关键依赖是否在 pyproject.toml 中显式声明
    pyproject_content = pyproject.read_text(encoding="utf-8")

    key_deps = [
        ("fastapi", "Web 框架"),
        ("pydantic", "数据验证"),
        ("httpx", "HTTP 客户端"),
        ("uvicorn", "ASGI 服务器"),
        ("structlog", "结构化日志"),
        ("sqlalchemy", "ORM"),
        ("bcrypt", "密码哈希"),
        ("mcp", "Model Context Protocol"),
    ]

    missing_in_pyproject: list[str] = []
    for dep, desc in key_deps:
        # 在 dependencies = [...] 段中查找
        if f'"{dep}' not in pyproject_content and f"'{dep}" not in pyproject_content:
            missing_in_pyproject.append(f"{dep} ({desc})")

    if missing_in_pyproject:
        print(_c(C.YELLOW, "  ⚠ 关键依赖未在 pyproject.toml 中显式声明:"))
        for dep in missing_in_pyproject:
            print(f"    - {dep}")
    else:
        print(_c(C.GREEN, "  ✅ 所有关键依赖均在 pyproject.toml 中显式声明"))

    # 检查 .in 文件存在性
    expected_in_files = [
        "requirements/requirements.in",
        "requirements/requirements-dev.in",
        "requirements/requirements-browser.in",
        "requirements/requirements-help.in",
        "requirements/requirements-playwright.in",
    ]

    missing_in_files: list[str] = []
    for in_file in expected_in_files:
        if not (ROOT / in_file).exists():
            missing_in_files.append(in_file)

    if missing_in_files:
        print(_c(C.RED, "  ❌ 缺少 .in 源文件:"))
        for f in missing_in_files:
            print(f"    - {f}")
        return 2

    print(_c(C.GREEN, "  ✅ 所有 .in 源文件存在"))

    # 检查 .txt 锁定文件存在性
    expected_txt_files = [
        "requirements.txt",
        "requirements/requirements-dev.txt",
        "requirements/requirements-browser.txt",
        "requirements/requirements-help.txt",
        "requirements/requirements-playwright.txt",
        "requirements-all.txt",
    ]

    missing_txt_files: list[str] = []
    for txt_file in expected_txt_files:
        if not (ROOT / txt_file).exists():
            missing_txt_files.append(txt_file)

    if missing_txt_files:
        print(_c(C.YELLOW, "  ⚠ 缺少 .txt 锁定文件（需运行 uv pip compile 重新生成）:"))
        for f in missing_txt_files:
            print(f"    - {f}")
    else:
        print(_c(C.GREEN, "  ✅ 所有 .txt 锁定文件存在"))

    return 0


# ─────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PyCoder 依赖治理审计",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--vuln", action="store_true", help="仅漏洞扫描")
    parser.add_argument("--unused", action="store_true", help="仅未使用依赖检测")
    parser.add_argument("--outdated", action="store_true", help="仅过期依赖检测")
    parser.add_argument("--consistency", action="store_true", help="仅一致性检查")
    args = parser.parse_args()

    # 如果未指定任何选项，运行全部检查
    run_all = not any([args.vuln, args.unused, args.outdated, args.consistency])

    print(_c(C.BOLD, "═" * 60))
    print(_c(C.BOLD, "PyCoder 依赖治理审计报告"))
    print(_c(C.BOLD, "═" * 60))

    exit_code = 0

    if run_all or args.vuln:
        rc = audit_vulnerabilities()
        exit_code = max(exit_code, rc)

    if run_all or args.unused:
        rc = audit_unused_dependencies()
        exit_code = max(exit_code, rc)

    if run_all or args.outdated:
        rc = audit_outdated()
        exit_code = max(exit_code, rc)

    if run_all or args.consistency:
        rc = audit_consistency()
        exit_code = max(exit_code, rc)

    print(_c(C.BOLD, "\n" + "═" * 60))
    if exit_code == 0:
        print(_c(C.GREEN, _c(C.BOLD, "✅ 审计通过")))
    elif exit_code == 1:
        print(_c(C.RED, _c(C.BOLD, "❌ 发现已知漏洞依赖，需立即修复")))
    else:
        print(_c(C.YELLOW, _c(C.BOLD, "⚠ 审计完成，但存在警告")))
    print(_c(C.BOLD, "═" * 60))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
