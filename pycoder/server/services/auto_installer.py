"""
AutoInstaller — 全自动依赖/工具/技能安装器

能力:
  1. 自动检测并安装 Python 缺失包 (pip)
  2. 自动检测并安装 npm 包
  3. 自动检测系统工具是否存在，缺失则安装 (choco/scoop/apt-get)
  4. 搜索 PyPI/npm/GitHub 寻找需要的包
  5. 执行 Python 代码前自动安装全部缺失依赖
  6. 提供 Agent 工具接口 (install_package / search_package / ensure_tool)

用法:
    installer = AutoInstaller()

    # Agent 工具接口
    await installer.install_package("requests", source="pip")
    await installer.search_package("pandas", source="pypi")
    await installer.ensure_tool("docker")

    # 自动检测
    installer.detect_missing_imports(source_code)
    await installer.install_missing_imports(source_code)
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

from pycoder.server.log import log

# ── 标准库白名单（不尝试安装）──
_STDLIB_MODULES = {
    "os",
    "sys",
    "re",
    "json",
    "math",
    "time",
    "datetime",
    "collections",
    "itertools",
    "functools",
    "pathlib",
    "typing",
    "abc",
    "enum",
    "dataclasses",
    "uuid",
    "hashlib",
    "base64",
    "io",
    "textwrap",
    "random",
    "statistics",
    "decimal",
    "fractions",
    "string",
    "logging",
    "argparse",
    "configparser",
    "asyncio",
    "threading",
    "multiprocessing",
    "subprocess",
    "socket",
    "http",
    "urllib",
    "xml",
    "html",
    "csv",
    "sqlite3",
    "copy",
    "pprint",
    "tempfile",
    "shutil",
    "glob",
    "fnmatch",
    "unittest",
    "doctest",
    "pdb",
    "traceback",
    "warnings",
    "contextlib",
    "weakref",
    "numbers",
    "operator",
    "bisect",
    "array",
    "struct",
    "pickle",
    "shelve",
    "dbm",
    "zipfile",
    "tarfile",
    "gzip",
    "bz2",
    "lzma",
    "secrets",
    "ssl",
    "email",
    "mimetypes",
    "inspect",
    "dis",
    "ast",
    "compileall",
    "py_compile",
    "platform",
    "errno",
    "ctypes",
    "codecs",
    "locale",
    "gettext",
    "optparse",
    "fileinput",
    "linecache",
    "tokenize",
    "token",
    "symbol",
    "symtable",
    "tabnanny",
    "pyclbr",
    "pyparsing",
}

# ── 已知包名映射（import 名 → pip 包名）──
_IMPORT_TO_PACKAGE = {
    "yaml": "pyyaml",
    "PIL": "pillow",
    "cv2": "opencv-python",
    "bs4": "beautifulsoup4",
    "sklearn": "scikit-learn",
    "scipy": "scipy",
    "matplotlib": "matplotlib",
    "numpy": "numpy",
    "pandas": "pandas",
    "requests": "requests",
    "flask": "flask",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "jinja2": "jinja2",
    "docx": "python-docx",
    "openpyxl": "openpyxl",
    "selenium": "selenium",
    "playwright": "playwright",
    "lxml": "lxml",
    "cryptography": "cryptography",
    "paramiko": "paramiko",
    "asyncssh": "asyncssh",
    "httpx": "httpx",
    "aiohttp": "aiohttp",
    "websockets": "websockets",
    "sse_starlette": "sse-starlette",
    "pydantic": "pydantic",
    "sqlalchemy": "sqlalchemy",
    "alembic": "alembic",
    "redis": "redis",
    "pymongo": "pymongo",
    "psycopg2": "psycopg2-binary",
    "mysql": "mysql-connector-python",
    "kafka": "kafka-python",
    "celery": "celery",
    "gunicorn": "gunicorn",
    "streamlit": "streamlit",
    "gradio": "gradio",
    "tqdm": "tqdm",
    "rich": "rich",
    "click": "click",
    "typer": "typer",
    "pytest": "pytest",
    "coverage": "coverage",
    "mypy": "mypy",
    "ruff": "ruff",
    "black": "black",
    "isort": "isort",
    "pre_commit": "pre-commit",
    "structlog": "structlog",
    "orjson": "orjson",
    "ujson": "ujson",
    "toml": "toml",
    "dotenv": "python-dotenv",
    "dateutil": "python-dateutil",
    "tzlocal": "tzlocal",
    "pdfplumber": "pdfplumber",
    "camelot": "camelot-py",
    "tabula": "tabula-py",
    "pypdf2": "pypdf2",
    "fitz": "pymupdf",
    "markdown": "markdown",
}


class AutoInstaller:
    """全自动依赖/工具安装器"""

    PIP_TIMEOUT = 120
    NPM_TIMEOUT = 120
    CHOCOTIME_TIMEOUT = 180

    # ── 公开接口: Agent 工具 ────────────────────────────

    async def install_package(
        self,
        name: str,
        source: str = "auto",
        version: str = "",
    ) -> dict:
        """
        安装包/软件（Agent 工具接口）

        Args:
            name: 包名（pip包 / npm包 / 系统工具名）
            source: "pip" | "npm" | "system" | "auto"
            version: 版本号（可选）

        Returns:
            {"success": bool, "message": "...", "source": "pip/npm/system"}
        """
        source = self._detect_source(name) if source == "auto" else source

        if source == "pip":
            return await self._install_pip(name, version)
        elif source == "npm":
            return await self._install_npm(name)
        elif source == "system":
            return await self._install_system(name)
        else:
            return {"success": False, "message": f"未知安装源: {source}"}

    async def search_package(self, query: str, source: str = "all") -> dict:
        """
        搜索包（Agent 工具接口）

        Args:
            query: 搜索关键词
            source: "pypi" | "npm" | "github" | "all"

        Returns:
            {"results": [{"name": ..., "description": ..., "source": ...}]}
        """
        results = []

        if source in ("pypi", "all"):
            try:
                pypi = await self._search_pypi(query)
                results.extend(pypi)
            except (ConnectionError, TimeoutError, OSError) as e:
                log.debug("search_pypi_failed", error=str(e))

        if source in ("npm", "all"):
            try:
                npm = await self._search_npm(query)
                results.extend(npm)
            except (ConnectionError, TimeoutError, OSError) as e:
                log.debug("search_npm_failed", error=str(e))

        if source in ("github", "all"):
            try:
                gh = await self._search_github(query)
                results.extend(gh)
            except (ConnectionError, TimeoutError, OSError) as e:
                log.debug("search_github_failed", error=str(e))

        return {
            "results": results[:20],
            "total": len(results),
            "query": query,
        }

    async def ensure_tool(self, tool_name: str) -> dict:
        """
        确保工具可用（Agent 工具接口）

        检查工具是否存在，缺失则自动安装

        Args:
            tool_name: 工具名（python/node/git/docker/ruff 等）

        Returns:
            {"success": bool, "message": "...", "action": "already_exists/installed/failed"}
        """
        # 检查是否已存在
        if shutil.which(tool_name):
            return {
                "success": True,
                "message": f"✅ {tool_name} 已可用",
                "action": "already_exists",
            }

        # pip 包回退检查
        try:
            importlib.import_module(tool_name)
            return {
                "success": True,
                "message": f"✅ {tool_name} (Python模块) 已可用",
                "action": "already_exists",
            }
        except ImportError:
            pass

        # 尝试安装
        result = await self.install_package(tool_name, source="auto")
        if result["success"]:
            return {
                "success": True,
                "message": f"✅ {tool_name} 已安装",
                "action": "installed",
            }

        # 检查是否现在可用
        if shutil.which(tool_name):
            return {
                "success": True,
                "message": f"✅ {tool_name} 安装后可用",
                "action": "installed",
            }

        return {
            "success": False,
            "message": f"❌ 无法安装 {tool_name}: {result.get('message', '')}",
            "action": "failed",
        }

    async def search_skill(self, query: str) -> dict:
        """搜索技能（Agent 工具接口）

        Args:
            query: 搜索关键词

        Returns:
            {"results": [...]}
        """
        from pycoder.skills import get_marketplace

        try:
            marketplace = get_marketplace()
            results = marketplace.search(query, limit=10)
            return {
                "results": [
                    {
                        "name": getattr(s, "name", s.get("name", "")),
                        "description": getattr(s, "description", s.get("description", "")),
                        "installed": getattr(s, "installed", s.get("installed", False)),
                    }
                    for s in results
                ],
                "total": len(results),
                "query": query,
            }
        except Exception as e:
            return {"results": [], "total": 0, "query": query, "error": str(e)}

    async def install_skill(self, skill_name: str) -> dict:
        """安装技能（Agent 工具接口）

        Args:
            skill_name: 技能名称

        Returns:
            {"success": bool, "message": "..."}
        """
        from pycoder.skills import get_marketplace

        try:
            marketplace = get_marketplace()
            installed = marketplace.get_installed_skills()
            if any(s.name.lower() == skill_name.lower() for s in installed):
                return {"success": True, "message": f"技能 '{skill_name}' 已安装"}

            success = marketplace.install(skill_name)
            if success:
                return {"success": True, "message": f"技能 '{skill_name}' 安装成功"}
            return {"success": False, "message": f"技能 '{skill_name}' 安装失败"}
        except Exception as e:
            return {"success": False, "message": f"安装失败: {e}"}

    # ── 自动检测 ────────────────────────────────────────

    def detect_missing_imports(self, code: str) -> list[str]:
        """从代码中提取缺失的 import 包名"""
        imports = set()
        for m in re.finditer(
            r"^(?:import|from)\s+(\S+)",
            code,
            re.MULTILINE,
        ):
            mod = m.group(1).strip()
            base = mod.split(".")[0].split(" ")[0].split(",")[0].strip()
            if base and base not in _STDLIB_MODULES:
                imports.add(base)

        # 排除已安装的
        missing = []
        for mod in sorted(imports):
            try:
                importlib.import_module(mod.replace("-", "_"))
            except ImportError:
                missing.append(mod)

        return missing

    async def install_missing_imports(self, code: str) -> list[dict]:
        """从代码自动检测并安装所有缺失包"""
        missing = self.detect_missing_imports(code)
        if not missing:
            return []

        results = []
        for mod in missing:
            pkg = _IMPORT_TO_PACKAGE.get(mod, mod)
            result = await self.install_package(pkg, source="pip")
            results.append({"module": mod, "package": pkg, **result})

        return results

    def detect_requirements_file(self, project_dir: str | Path) -> list[str]:
        """读取 requirements.txt 检测需要安装的包"""
        req_file = Path(project_dir) / "requirements.txt"
        if not req_file.exists():
            return []

        missing = []
        for line in req_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            pkg_name = re.split(r"[<>=!~@]", line)[0].strip().lower()
            try:
                importlib.import_module(pkg_name.replace("-", "_"))
            except ImportError:
                missing.append(line)
        return missing

    # ── 内部实现 ────────────────────────────────────────

    def _detect_source(self, name: str) -> str:
        """自动检测安装源"""
        # npm 包检测
        npm_like = {
            "react",
            "vue",
            "express",
            "lodash",
            "axios",
            "typescript",
            "webpack",
            "vite",
            "next",
            "nuxt",
            "tailwindcss",
            "babel",
            "eslint",
            "prettier",
            "jest",
            "mocha",
        }
        if name in npm_like or not name.startswith("python-"):
            if name in npm_like:
                return "npm"

        # 在 pip 包名映射中
        if name in _IMPORT_TO_PACKAGE.values() or name in _IMPORT_TO_PACKAGE:
            return "pip"

        # 检测本地是否有 pip 包
        try:
            importlib.import_module(name.replace("-", "_"))
            return "pip"
        except ImportError:
            pass

        # 系统工具检测
        sys_tools = {
            "docker",
            "git",
            "node",
            "npm",
            "yarn",
            "curl",
            "wget",
            "python3",
            "java",
            "javac",
            "go",
            "rustc",
            "cargo",
            "make",
            "cmake",
            "gcc",
            "g++",
            "clang",
        }
        if name in sys_tools:
            return "system"

        return "pip"  # 默认用 pip

    async def _install_pip(self, name: str, version: str = "") -> dict:
        """安装 pip 包"""
        if version:
            spec = f"{name}{version}"
        else:
            spec = name

        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    spec,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=self.PIP_TIMEOUT,
            )
            stdout, stderr = await proc.communicate()
            stdout.decode("utf-8", errors="replace")

            if proc.returncode == 0:
                log.info("pip_install_ok", package=name)
                return {
                    "success": True,
                    "message": f"✅ pip install {spec} 成功",
                    "source": "pip",
                }
            else:
                # 尝试使用 --user 安装
                proc2 = await asyncio.wait_for(
                    asyncio.create_subprocess_exec(
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "--user",
                        spec,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    ),
                    timeout=self.PIP_TIMEOUT,
                )
                stdout2, _ = await proc2.communicate()
                if proc2.returncode == 0:
                    log.info("pip_install_user_ok", package=name)
                    return {
                        "success": True,
                        "message": f"✅ pip install --user {spec} 成功",
                        "source": "pip",
                    }

                return {
                    "success": False,
                    "message": f"❌ pip install {spec} 失败:\n{stderr.decode('utf-8', errors='replace')[:500]}",
                    "source": "pip",
                }
        except TimeoutError:
            return {
                "success": False,
                "message": f"⏱ pip install {spec} 超时 ({self.PIP_TIMEOUT}s)",
                "source": "pip",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"❌ pip install 异常: {e}",
                "source": "pip",
            }

    async def _install_npm(self, name: str) -> dict:
        """安装 npm 包"""
        npm_path = shutil.which("npm") or shutil.which("npm.cmd")
        if not npm_path:
            return {
                "success": False,
                "message": "❌ npm 未安装，请先安装 Node.js",
                "source": "npm",
            }

        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    npm_path,
                    "install",
                    name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=self.NPM_TIMEOUT,
            )
            await proc.communicate()
            if proc.returncode == 0:
                log.info("npm_install_ok", package=name)
                return {
                    "success": True,
                    "message": f"✅ npm install {name} 成功",
                    "source": "npm",
                }
            return {
                "success": False,
                "message": f"❌ npm install {name} 失败 (exit {proc.returncode})",
                "source": "npm",
            }
        except TimeoutError:
            return {
                "success": False,
                "message": f"⏱ npm install {name} 超时 ({self.NPM_TIMEOUT}s)",
                "source": "npm",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"❌ npm 安装异常: {e}",
                "source": "npm",
            }

    async def _install_system(self, name: str) -> dict:
        """安装系统工具"""
        if os.name == "nt":
            # Windows: 尝试用 winget, 然后 choco
            for mgr in ["winget", "choco", "scoop"]:
                mgr_path = shutil.which(mgr) or shutil.which(f"{mgr}.exe")
                if mgr_path:
                    try:
                        proc = await asyncio.wait_for(
                            asyncio.create_subprocess_exec(
                                mgr_path,
                                "install",
                                name,
                                "-y",
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                            ),
                            timeout=self.CHOCOTIME_TIMEOUT,
                        )
                        await proc.communicate()
                        if proc.returncode == 0:
                            log.info("system_install_ok", tool=name, manager=mgr)
                            return {
                                "success": True,
                                "message": f"✅ {mgr} install {name} 成功",
                                "source": "system",
                            }
                    except (TimeoutError, Exception):
                        continue
        else:
            # Linux/Mac: apt-get/brew
            for mgr, install_cmd in [
                ("apt-get", ["apt-get", "install", "-y", name]),
                ("brew", ["brew", "install", name]),
            ]:
                mgr_path = shutil.which(mgr)
                if mgr_path:
                    try:
                        proc = await asyncio.wait_for(
                            asyncio.create_subprocess_exec(
                                *install_cmd,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                            ),
                            timeout=self.CHOCOTIME_TIMEOUT,
                        )
                        await proc.communicate()
                        if proc.returncode == 0:
                            log.info("system_install_ok", tool=name, manager=mgr)
                            return {
                                "success": True,
                                "message": f"✅ {mgr} install {name} 成功",
                                "source": "system",
                            }
                    except (TimeoutError, Exception):
                        continue

        return {
            "success": False,
            "message": f"❌ 未能安装系统工具 {name}（无可用包管理器）",
            "source": "system",
        }

    async def _search_pypi(self, query: str) -> list[dict]:
        """搜索 PyPI (使用 JSON API)"""
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            # 使用 PyPI JSON API
            resp = await client.get(
                f"https://pypi.org/pypi/{query}/json",
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                info = data.get("info", {})
                return [
                    {
                        "name": info.get("name", query),
                        "description": (info.get("summary") or "")[:200],
                        "version": info.get("version", ""),
                        "source": "pypi",
                    }
                ]

            # 回退: 搜索 PyPI JSON search API
            resp = await client.get(
                "https://pypi.org/search/",
                params={"q": query, "page": 1},
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    results = []
                    for hit in data.get("results", [])[:10]:
                        results.append(
                            {
                                "name": hit.get("name", ""),
                                "description": (hit.get("description") or "")[:200],
                                "version": hit.get("version", ""),
                                "source": "pypi",
                            }
                        )
                    return results
                except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
                    log.debug("pypi_parse_failed", error=str(e))

            # 最终回退: 把 query 本身当结果返回
            return [{"name": query, "description": f"PyPI 包 {query}", "source": "pypi"}]

    async def _search_npm(self, query: str) -> list[dict]:
        """搜索 npm"""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://registry.npmjs.org/-/v1/search",
                    params={"text": query, "size": 10},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return [
                        {
                            "name": obj.get("package", {}).get("name", ""),
                            "description": obj.get("package", {}).get("description", "")[:200],
                            "version": obj.get("package", {}).get("version", ""),
                            "source": "npm",
                        }
                        for obj in data.get("objects", [])
                    ]
        except (ConnectionError, TimeoutError, OSError) as e:
            log.debug("npm_search_failed", error=str(e))
        return []

    async def _search_github(self, query: str) -> list[dict]:
        """搜索 GitHub"""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://api.github.com/search/repositories",
                    params={"q": query, "per_page": 5, "sort": "stars"},
                    headers={"Accept": "application/vnd.github.v3+json"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return [
                        {
                            "name": item.get("full_name", ""),
                            "description": (item.get("description") or "")[:200],
                            "url": item.get("html_url", ""),
                            "stars": item.get("stargazers_count", 0),
                            "source": "github",
                        }
                        for item in data.get("items", [])
                    ]
        except (ConnectionError, TimeoutError, OSError) as e:
            log.debug("github_search_failed", error=str(e))
        return []

    async def install_requirements(self, project_dir: str | Path) -> dict:
        """从 requirements.txt 安装全部依赖"""
        missing = self.detect_requirements_file(project_dir)
        if not missing:
            return {
                "success": True,
                "message": "所有依赖已安装",
                "count": 0,
            }

        results = []
        for spec in missing:
            name = re.split(r"[<>=!~@\[]", spec)[0].strip()
            r = await self.install_package(name, source="pip")
            results.append({"spec": spec, **r})

        ok = sum(1 for r in results if r["success"])
        fail = sum(1 for r in results if not r["success"])
        return {
            "success": fail == 0,
            "message": f"已安装 {ok}/{len(results)}，失败 {fail}",
            "count": len(results),
            "results": results,
        }


# ══════════════════════════════════════════════════════════
# Agent 工具适配器
# ══════════════════════════════════════════════════════════

_INSTALLER: AutoInstaller | None = None


def get_installer() -> AutoInstaller:
    """获取全局单例"""
    global _INSTALLER
    if _INSTALLER is None:
        _INSTALLER = AutoInstaller()
    return _INSTALLER


# Agent 可调用的工具函数（字符串接口）


async def agent_install_package(args: dict) -> str:
    """Agent 工具: 安装包"""
    installer = get_installer()
    result = await installer.install_package(
        args.get("name", ""),
        source=args.get("source", "auto"),
    )
    return result.get("message", "未知结果")


async def agent_search_package(args: dict) -> str:
    """Agent 工具: 搜索包"""
    installer = get_installer()
    result = await installer.search_package(
        args.get("query", ""),
        source=args.get("source", "all"),
    )
    results = result.get("results", [])
    if not results:
        return "未找到匹配结果"
    lines = [f"   找到 {result['total']} 个结果:", f"   {'=' * 50}"]
    for r in results[:10]:
        name = r.get("name", "")
        desc = r.get("description", "")[:100]
        src = r.get("source", "")
        stars = r.get("stars", "")
        ver = r.get("version", "")
        info = f"⭐ {stars}" if stars else f"v{ver}" if ver else ""
        lines.append(f"   📦 [{src}] {name}  {info}")
        if desc:
            lines.append(f"      {desc}")
    return "\n".join(lines)


async def agent_ensure_tool(args: dict) -> str:
    """Agent 工具: 确保工具可用"""
    installer = get_installer()
    result = await installer.ensure_tool(args.get("name", ""))
    return result.get("message", "未知结果")


async def agent_install_deps(args: dict) -> str:
    """Agent 工具: 从代码文件自动安装缺失依赖"""
    filepath = args.get("file", "")
    try:
        code = Path(filepath).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, PermissionError) as e:
        log.warning("read_file_failed", path=filepath, error=str(e))
        return f"❌ 无法读取文件: {filepath}"

    installer = get_installer()
    results = await installer.install_missing_imports(code)
    if not results:
        return "没有缺失的依赖"
    ok = sum(1 for r in results if r.get("success"))
    total = len(results)
    lines = [f"安装 {ok}/{total} 个依赖:"]
    for r in results:
        status = "✅" if r.get("success") else "❌"
        lines.append(f"  {status} {r['module']} ({r['package']})")
    return "\n".join(lines)
