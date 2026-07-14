"""
扩展管理器 — 安装/启用/禁用/卸载/更新
种子扩展安装时会生成实际的功能代码包
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

EXTENSIONS_DIR = Path.home() / ".pycoder" / "extensions"


def _safe_extract_archive(archive, target: Path, fmt: str = "tar"):
    """安全解压归档文件，拒绝路径穿越攻击

    Args:
        archive: tarfile.TarFile 或 zipfile.ZipFile 实例
        target: 解压目标目录
        fmt: 归档格式 "tar" 或 "zip"

    Raises:
        ValueError: 检测到路径穿越攻击时抛出
    """
    target_real = os.path.realpath(str(target))
    if fmt == "tar":
        for member in archive.getmembers():
            member_path = os.path.realpath(str(target / member.name))
            if not member_path.startswith(target_real):
                raise ValueError(f"检测到路径穿越攻击: {member.name}")
            archive.extract(member, str(target))
    else:
        for info in archive.infolist():
            member_path = os.path.realpath(str(target / info.filename))
            if not member_path.startswith(target_real):
                raise ValueError(f"检测到路径穿越攻击: {info.filename}")
            archive.extract(info, str(target))


# ── 种子扩展源代码 ──────────────────────────────────

_SEED_PACKAGES: dict[str, dict] = {
    "pycoder.gitlens": {
        "manifest": {
            "id": "pycoder.gitlens",
            "name": "GitLens for PyCoder",
            "version": "1.0.0",
            "description": "Git 超级增强：行内 blame、历史对比、分支可视化",
            "author": "PyCoder Team",
            "publisher": "PyCoder Team",
            "category": "git",
            "license": "MIT",
            "engines": {"pycoder": ">=0.5.0"},
            "activationEvents": ["onStartupFinished"],
            "contributes": {
                "commands": [
                    {
                        "command": "pycoder.gitlens.blame",
                        "title": "Git: 查看 Blame 信息",
                        "category": "Git",
                    },
                    {
                        "command": "pycoder.gitlens.history",
                        "title": "Git: 查看提交历史",
                        "category": "Git",
                    },
                ],
                "settings": [
                    {
                        "id": "pycoder.gitlens.enabled",
                        "title": "启用 GitLens",
                        "type": "boolean",
                        "default": True,
                        "description": "启用/禁用 GitLens 扩展",
                    },
                    {
                        "id": "pycoder.gitlens.maxCommits",
                        "title": "最大提交数",
                        "type": "number",
                        "default": 20,
                        "description": "历史查询的最大提交数",
                    },
                ],
                "keybindings": [
                    {
                        "key": "ctrl+shift+g",
                        "command": "pycoder.gitlens.blame",
                        "when": "editorFocus",
                    },
                ],
            },
        },
        "code": {
            "extension.py": '''"""GitLens — Git blame & history integration."""
from __future__ import annotations

name = "GitLens for PyCoder"
version = "1.0.0"

def get_blame_info(file_path: str, line_range: str = "") -> dict:
    """Get git blame for a file."""
    import subprocess
    try:
        cmd = ["git", "blame", file_path, "--date=short"]
        if line_range:
            cmd.extend(["-L", line_range])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return {"success": True, "blame": r.stdout.strip(), "file": file_path}
    except Exception as e:
        return {"success": False, "error": str(e)}

def get_commit_history(limit: int = 20) -> dict:
    """Get recent commit history."""
    import subprocess
    try:
        r = subprocess.run(["git", "log", f"--oneline", f"-{limit}"],
                          capture_output=True, text=True, timeout=10)
        return {"success": True, "log": r.stdout.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}

__all__ = ["name", "version", "get_blame_info", "get_commit_history"]
''',
        },
    },
    "pycoder.docker": {
        "manifest": {
            "id": "pycoder.docker",
            "name": "Docker Manager",
            "version": "1.0.0",
            "description": "Docker 容器和镜像管理",
            "author": "PyCoder Team",
            "publisher": "PyCoder Team",
            "category": "devops",
            "license": "MIT",
            "engines": {"pycoder": ">=0.5.0"},
            "activationEvents": ["onCommand:pycoder.docker.containers"],
            "contributes": {
                "commands": [
                    {
                        "command": "pycoder.docker.containers",
                        "title": "Docker: 列出容器",
                        "category": "DevOps",
                    },
                    {
                        "command": "pycoder.docker.images",
                        "title": "Docker: 列出镜像",
                        "category": "DevOps",
                    },
                ],
                "settings": [
                    {
                        "id": "pycoder.docker.showAll",
                        "title": "显示所有容器",
                        "type": "boolean",
                        "default": False,
                        "description": "包括已停止的容器",
                    },
                ],
            },
        },
        "code": {
            "extension.py": '''"""Docker Manager — container & image management."""
from __future__ import annotations

name = "Docker Manager"
version = "1.0.0"

def list_containers(all: bool = False) -> dict:
    """List Docker containers."""
    import subprocess
    try:
        cmd = ["docker", "ps", "--format", "{{json .}}"]
        if all:
            cmd.insert(2, "-a")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        lines = [ln for ln in r.stdout.strip().split("\\n") if ln]
        return {"success": True, "containers": lines}
    except FileNotFoundError:
        return {"success": False, "error": "Docker not installed"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def list_images() -> dict:
    """List Docker images."""
    import subprocess
    try:
        r = subprocess.run(["docker", "images", "--format", "{{json .}}"],
                          capture_output=True, text=True, timeout=15)
        lines = [ln for ln in r.stdout.strip().split("\\n") if ln]
        return {"success": True, "images": lines}
    except Exception as e:
        return {"success": False, "error": str(e)}

__all__ = ["name", "version", "list_containers", "list_images"]
''',
        },
    },
    "pycoder.rest-client": {
        "manifest": {
            "id": "pycoder.rest-client",
            "name": "REST Client",
            "version": "1.0.0",
            "description": "HTTP API 测试客户端，支持 .http 文件",
            "author": "PyCoder Team",
            "publisher": "PyCoder Team",
            "category": "tools",
            "license": "MIT",
            "engines": {"pycoder": ">=0.5.0"},
            "activationEvents": ["onCommand:pycoder.rest.send"],
            "contributes": {
                "commands": [
                    {
                        "command": "pycoder.rest.send",
                        "title": "REST: 发送请求",
                        "category": "Tools",
                    },
                    {
                        "command": "pycoder.rest.history",
                        "title": "REST: 请求历史",
                        "category": "Tools",
                    },
                ],
                "settings": [
                    {
                        "id": "pycoder.rest.defaultTimeout",
                        "title": "默认超时(秒)",
                        "type": "number",
                        "default": 30,
                        "description": "HTTP 请求超时时间",
                    },
                ],
            },
        },
        "code": {
            "extension.py": '''"""REST Client — HTTP request tester."""
from __future__ import annotations

name = "REST Client"
version = "1.0.0"

def send_request(method: str, url: str, headers: dict = None,
                 body: str = None, timeout: int = 30) -> dict:
    """Send an HTTP request."""
    import urllib.request, json
    try:
        data = body.encode() if body else None
        req = urllib.request.Request(url, data=data, method=method.upper())
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = resp.read().decode()
            return {"success": True, "status": resp.status,
                    "body": result[:5000], "headers": dict(resp.headers)}
    except Exception as e:
        return {"success": False, "error": str(e)}

__all__ = ["name", "version", "send_request"]
''',
        },
    },
    "pycoder.todo-tree": {
        "manifest": {
            "id": "pycoder.todo-tree",
            "name": "TODO Tree",
            "version": "1.0.0",
            "description": "代码中 TODO/FIXME/HACK 高亮和树视图",
            "author": "PyCoder Team",
            "publisher": "PyCoder Team",
            "category": "code-quality",
            "license": "MIT",
            "engines": {"pycoder": ">=0.5.0"},
            "activationEvents": ["onCommand:pycoder.todo.scan"],
            "contributes": {
                "commands": [
                    {
                        "command": "pycoder.todo.scan",
                        "title": "TODO: 扫描代码注释",
                        "category": "Code Quality",
                    },
                ],
                "settings": [
                    {
                        "id": "pycoder.todo.patterns",
                        "title": "扫描标签",
                        "type": "array",
                        "default": ["TODO", "FIXME", "HACK"],
                        "description": "要扫描的注释标签列表",
                    },
                    {
                        "id": "pycoder.todo.ignoreDirs",
                        "title": "忽略目录",
                        "type": "array",
                        "default": [".git", "node_modules", "__pycache__"],
                        "description": "扫描时忽略的目录",
                    },
                ],
            },
        },
        "code": {
            "extension.py": '''"""TODO Tree — scan code for TODOs and annotations."""
from __future__ import annotations
import logging
import os, re

logger = logging.getLogger(__name__)

name = "TODO Tree"
version = "1.0.0"

_PATTERNS = {
    "TODO": r"TODO[:\\s]",
    "FIXME": r"FIXME[:\\s]",
    "HACK": r"HACK[:\\s]",
    "NOTE": r"NOTE[:\\s]",
    "OPTIMIZE": r"OPTIMIZE[:\\s]",
}

def scan_directory(root_path: str = ".", patterns: list = None) -> dict:
    """Scan a directory for TODO/FIXME annotations."""
    results = []
    keys = patterns or list(_PATTERNS.keys())
    IGNORE = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in IGNORE]
        for fname in filenames:
            if not fname.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs",
                                   ".java", ".css", ".html", ".md", ".yml", ".yaml")):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        for tag in keys:
                            if tag in _PATTERNS and re.search(_PATTERNS[tag], line):
                                results.append({
                                    "file": fpath.replace("\\\\", "/"),
                                    "line": i, "tag": tag,
                                    "text": line.strip()[:200],
                                })
            except (OSError, UnicodeDecodeError, PermissionError) as e:
                logger.debug("todo_scan_file_failed fpath=%s error=%s", fpath, e)
    return {"count": len(results), "items": results}

__all__ = ["name", "version", "scan_directory"]
''',
        },
    },
    "pycoder.bookmarks": {
        "manifest": {
            "id": "pycoder.bookmarks",
            "name": "Code Bookmarks",
            "version": "1.0.0",
            "description": "代码书签导航",
            "author": "PyCoder Team",
            "publisher": "PyCoder Team",
            "category": "navigation",
            "license": "MIT",
            "engines": {"pycoder": ">=0.5.0"},
            "activationEvents": ["onCommand:pycoder.bookmarks.list"],
            "contributes": {
                "commands": [
                    {
                        "command": "pycoder.bookmarks.add",
                        "title": "书签: 添加书签",
                        "category": "Navigation",
                    },
                    {
                        "command": "pycoder.bookmarks.list",
                        "title": "书签: 列出书签",
                        "category": "Navigation",
                    },
                ],
            },
        },
        "code": {
            "extension.py": '''"""Code Bookmarks — navigate saved code positions."""
from __future__ import annotations
import json, logging, os
from pathlib import Path

logger = logging.getLogger(__name__)

name = "Code Bookmarks"
version = "1.0.0"

_BOOKMARKS_FILE = Path.home() / ".pycoder" / "bookmarks.json"

def add(file_path: str, line: int, label: str = "") -> dict:
    """Add a bookmark at a file:line position."""
    bm = {"file": file_path, "line": line, "label": label}
    bookmarks = _load()
    bookmarks.append(bm)
    _save(bookmarks)
    return {"success": True, "bookmarks": bookmarks}

def remove(index: int) -> dict:
    """Remove a bookmark by index."""
    bookmarks = _load()
    if 0 <= index < len(bookmarks):
        bookmarks.pop(index)
        _save(bookmarks)
        return {"success": True, "bookmarks": bookmarks}
    return {"success": False, "error": "Invalid index"}

def list_all() -> dict:
    """List all bookmarks."""
    return {"bookmarks": _load()}

def _load() -> list:
    try:
        return json.loads(_BOOKMARKS_FILE.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("bookmarks_load_failed error=%s", e)
        return []

def _save(data: list):
    _BOOKMARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _BOOKMARKS_FILE.write_text(json.dumps(data, indent=2))

__all__ = ["name", "version", "add", "remove", "list_all"]
''',
        },
    },
    "pycoder.project-manager": {
        "manifest": {
            "id": "pycoder.project-manager",
            "name": "Project Manager",
            "version": "1.0.0",
            "description": "多项目管理，快速切换工作区",
            "author": "PyCoder Team",
            "publisher": "PyCoder Team",
            "category": "tools",
            "license": "MIT",
            "engines": {"pycoder": ">=0.5.0"},
            "activationEvents": ["onCommand:pycoder.project.list"],
            "contributes": {
                "commands": [
                    {
                        "command": "pycoder.project.add",
                        "title": "项目: 添加项目",
                        "category": "Project",
                    },
                    {
                        "command": "pycoder.project.list",
                        "title": "项目: 列出项目",
                        "category": "Project",
                    },
                    {
                        "command": "pycoder.project.remove",
                        "title": "项目: 删除项目",
                        "category": "Project",
                    },
                ],
            },
        },
        "code": {
            "extension.py": '''"""Project Manager — multi-project switching."""
from __future__ import annotations
import json, logging, os
from pathlib import Path

logger = logging.getLogger(__name__)

name = "Project Manager"
version = "1.0.0"

_PROJECTS_FILE = Path.home() / ".pycoder" / "projects.json"

def add_project(name: str, path: str) -> dict:
    """Register a new project."""
    projects = _load()
    projects[name] = {"name": name, "path": path, "added": __import__("time").time()}
    _save(projects)
    return {"success": True, "projects": list(projects.values())}

def remove_project(name: str) -> dict:
    """Remove a registered project."""
    projects = _load()
    if name in projects:
        del projects[name]
        _save(projects)
    return {"success": True, "projects": list(projects.values())}

def list_projects() -> dict:
    """List all registered projects."""
    projects = _load()
    return {"projects": list(projects.values())}

def switch_to(name: str) -> dict:
    """Get project path for switching."""
    projects = _load()
    if name in projects:
        p = projects[name]
        if os.path.isdir(p["path"]):
            return {"success": True, "path": p["path"], "name": p["name"]}
        return {"success": False, "error": f"Path not found: {p['path']}"}
    return {"success": False, "error": f"Project '{name}' not found"}

def _load() -> dict:
    try:
        return json.loads(_PROJECTS_FILE.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("projects_load_failed error=%s", e)
        return {}

def _save(data: dict):
    _PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PROJECTS_FILE.write_text(json.dumps(data, indent=2))

__all__ = ["name", "version", "add_project", "remove_project", "list_projects", "switch_to"]
''',
        },
    },
}


class ExtensionManager:
    """管理已安装的扩展"""

    def __init__(self):
        EXTENSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self._installed: dict[str, dict] = {}
        self._load_installed()

    async def install(self, ext_id: str, ext_data: dict) -> bool:
        """安装扩展 — 含来源安全校验

        支持来源:
            - 种子扩展: 直接写入代码包
            - GitHub/GitLab: git clone（异步）
            - npm: npm pack 下载 + 解压
            - PyPI: pip download --no-deps + 解压
            - Open VSX: 下载 .vsix 并解压
        """
        if ext_id in self._installed:
            return False

        # ── 来源安全校验 ──
        url = ext_data.get("url", "")
        source = ext_data.get("source", "")
        if url:
            allowed_domains = [
                "github.com",
                "raw.githubusercontent.com",
                "gitlab.com",
                "registry.npmjs.org",
                "pypi.org",
                "open-vsx.org",
            ]
            if not any(d in url for d in allowed_domains):
                raise PermissionError(
                    f"扩展来源不安全: {url}。仅允许已知代码仓库。"
                    f"允许域名: {', '.join(allowed_domains)}",
                )

        # 种子扩展：写入真实的代码包
        if ext_id in _SEED_PACKAGES:
            return self._install_seed(ext_id, ext_data)

        # 元数据种子扩展：不在 _SEED_PACKAGES 但标记为种子
        # 写入 manifest + 占位 extension.py（无实际代码）
        is_seed = ext_data.get("is_seed", False) or ext_data.get("source", "") == "seed"
        if is_seed:
            return self._install_seed_metadata(ext_id, ext_data)

        # GitHub/GitLab 扩展：git clone（异步）
        if url and ("github.com" in url or "gitlab.com" in url):
            return await self._install_git(ext_id, ext_data, url)

        # npm 扩展：npm pack 下载 + 解压
        if source == "npm" or ext_id.startswith("npm."):
            return await self._install_npm(ext_id, ext_data)

        # PyPI 扩展：pip download --no-deps + 解压
        if source == "pypi" or ext_id.startswith("pypi."):
            return await self._install_pypi(ext_id, ext_data)

        # Open VSX 扩展：下载 .vsix 并解压
        if source == "open-vsx" or ext_id.startswith("ovsx."):
            return await self._install_vsix(ext_id, ext_data)

        return False

    def _install_seed_metadata(self, ext_id: str, ext_data: dict) -> bool:
        """安装元数据种子扩展 — 写入 manifest + 占位代码（无实际功能）"""
        target = EXTENSIONS_DIR / ext_id.replace("/", "_")
        target.mkdir(parents=True, exist_ok=True)

        manifest = {
            "id": ext_id,
            "name": ext_data.get("name", ext_id),
            "version": ext_data.get("version", "1.0.0"),
            "description": ext_data.get("description", ""),
            "author": ext_data.get("author", ""),
            "category": ext_data.get("category", "unknown"),
            "is_seed": True,
        }
        (target / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (target / "extension.py").write_text(
            f'"""{ext_data.get("name", ext_id)} — 元数据占位扩展"""\n' f"\n" f"__all__ = []\n",
            encoding="utf-8",
        )

        ext_data["path"] = str(target)
        ext_data["installed"] = True
        ext_data["enabled"] = True
        ext_data["installed_at"] = __import__("time").time()
        self._installed[ext_id] = ext_data
        self._save()
        return True

    def _install_seed(self, ext_id: str, ext_data: dict) -> bool:
        """安装种子扩展 — 写入真实代码包"""
        pkg = _SEED_PACKAGES[ext_id]
        target = EXTENSIONS_DIR / ext_id.replace("/", "_")
        target.mkdir(parents=True, exist_ok=True)

        (target / "manifest.json").write_text(
            json.dumps(pkg["manifest"], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        for filename, code in pkg.get("code", {}).items():
            (target / filename).write_text(code, encoding="utf-8")

        ext_data["path"] = str(target)
        ext_data["installed"] = True
        ext_data["enabled"] = True
        ext_data["installed_at"] = __import__("time").time()
        self._installed[ext_id] = ext_data
        self._save()
        return True

    async def _install_git(self, ext_id: str, ext_data: dict, url: str) -> bool:
        """GitHub/GitLab 扩展 — 异步 git clone"""
        target = EXTENSIONS_DIR / ext_id.replace("/", "_")
        if not target.exists():
            proc = await asyncio.create_subprocess_exec(
                "git",
                "clone",
                "--depth=1",
                url,
                str(target),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc.wait(), timeout=60)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                logger.warning("extension_git_clone_timeout ext_id=%s", ext_id)
                return False
        if target.exists():
            ext_data["path"] = str(target)
            ext_data["installed"] = True
            ext_data["enabled"] = True
            ext_data["installed_at"] = __import__("time").time()
            self._installed[ext_id] = ext_data
            self._save()
            return True
        return False

    async def _install_npm(self, ext_id: str, ext_data: dict) -> bool:
        """npm 扩展 — npm pack 下载 + 解压"""
        pkg_name = ext_data.get("name", ext_id.replace("npm.", "", 1))
        target = EXTENSIONS_DIR / ext_id.replace("/", "_")
        target.mkdir(parents=True, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            "npm",
            "pack",
            pkg_name,
            cwd=str(target),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=60)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("extension_npm_pack_timeout ext_id=%s", ext_id)
            return False

        if proc.returncode != 0:
            logger.warning("extension_npm_pack_failed ext_id=%s rc=%s", ext_id, proc.returncode)
            return False

        # 找到下载的 tarball 并解压
        tarballs = list(target.glob("*.tgz"))
        if not tarballs:
            return False
        try:
            with tarfile.open(tarballs[0], "r:gz") as tf:
                _safe_extract_archive(tf, target, fmt="tar")
            tarballs[0].unlink()
        except (tarfile.TarError, OSError, ValueError) as e:
            logger.warning("extension_npm_extract_failed ext_id=%s error=%s", ext_id, e)
            return False

        ext_data["path"] = str(target)
        ext_data["installed"] = True
        ext_data["enabled"] = True
        ext_data["installed_at"] = __import__("time").time()
        self._installed[ext_id] = ext_data
        self._save()
        return True

    async def _install_pypi(self, ext_id: str, ext_data: dict) -> bool:
        """PyPI 扩展 — pip download --no-deps + 解压"""
        pkg_name = ext_data.get("name", ext_id.replace("pypi.", "", 1))
        target = EXTENSIONS_DIR / ext_id.replace("/", "_")
        target.mkdir(parents=True, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            "pip",
            "download",
            "--no-deps",
            "--dest",
            str(target),
            pkg_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=60)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("extension_pypi_download_timeout ext_id=%s", ext_id)
            return False

        if proc.returncode != 0:
            logger.warning(
                "extension_pypi_download_failed ext_id=%s rc=%s", ext_id, proc.returncode
            )
            return False

        # 找到下载的包并解压
        archives = list(target.glob("*.whl")) or list(target.glob("*.tar.gz"))
        if not archives:
            return False
        try:
            archive = archives[0]
            if archive.suffix == ".whl":
                with zipfile.ZipFile(archive) as zf:
                    _safe_extract_archive(zf, target, fmt="zip")
            else:
                with tarfile.open(archive, "r:gz") as tf:
                    _safe_extract_archive(tf, target, fmt="tar")
            archive.unlink()
        except (zipfile.BadZipFile, tarfile.TarError, OSError, ValueError) as e:
            logger.warning("extension_pypi_extract_failed ext_id=%s error=%s", ext_id, e)
            return False

        ext_data["path"] = str(target)
        ext_data["installed"] = True
        ext_data["enabled"] = True
        ext_data["installed_at"] = __import__("time").time()
        self._installed[ext_id] = ext_data
        self._save()
        return True

    async def _install_vsix(self, ext_id: str, ext_data: dict) -> bool:
        """Open VSX 扩展 — 下载 .vsix 并解压"""
        import httpx

        url = ext_data.get("url", "")
        if not url:
            # 构造下载 URL
            name = ext_data.get("name", "")
            ns = ext_data.get("author", "")
            version = ext_data.get("version", "latest")
            if name and ns:
                url = f"https://open-vsx.org/api/{ns}/{name}/{version}/file/{ns}.{name}-{version}.vsix"
        if not url:
            return False

        target = EXTENSIONS_DIR / ext_id.replace("/", "_")
        target.mkdir(parents=True, exist_ok=True)
        vsix_path = target / "extension.vsix"

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(
                        "extension_vsix_download_failed ext_id=%s status=%s",
                        ext_id,
                        resp.status_code,
                    )
                    return False
                vsix_path.write_bytes(resp.content)
        except (httpx.HTTPError, OSError) as e:
            logger.warning("extension_vsix_download_error ext_id=%s error=%s", ext_id, e)
            return False

        # .vsix 是 zip 格式
        try:
            with zipfile.ZipFile(vsix_path) as zf:
                _safe_extract_archive(zf, target, fmt="zip")
            vsix_path.unlink()
        except (zipfile.BadZipFile, OSError, ValueError) as e:
            logger.warning("extension_vsix_extract_failed ext_id=%s error=%s", ext_id, e)
            return False

        ext_data["path"] = str(target)
        ext_data["installed"] = True
        ext_data["enabled"] = True
        ext_data["installed_at"] = __import__("time").time()
        self._installed[ext_id] = ext_data
        self._save()
        return True

    def enable(self, ext_id: str) -> bool:
        """启用扩展"""
        if ext_id not in self._installed:
            return False
        self._installed[ext_id]["enabled"] = True
        self._save()
        return True

    def disable(self, ext_id: str) -> bool:
        """禁用扩展"""
        if ext_id not in self._installed:
            return False
        self._installed[ext_id]["enabled"] = False
        self._save()
        return True

    def is_enabled(self, ext_id: str) -> bool:
        """检查扩展是否已启用（默认启用）"""
        return self._installed.get(ext_id, {}).get("enabled", True)

    def update(self, ext_id: str) -> bool:
        """更新扩展到最新版本 — 使用 git pull 增量更新"""
        if ext_id not in self._installed:
            return False
        ext = self._installed[ext_id]
        target = Path(ext.get("path", ""))
        # 种子扩展：重新写入代码
        if ext_id in _SEED_PACKAGES:
            pkg = _SEED_PACKAGES[ext_id]
            (target / "manifest.json").write_text(
                json.dumps(pkg["manifest"], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            for filename, code in pkg.get("code", {}).items():
                (target / filename).write_text(code, encoding="utf-8")
            ext["updated_at"] = __import__("time").time()
            self._save()
            return True
        # GitHub 扩展：git pull
        if target.exists() and (target / ".git").exists():
            try:
                r = subprocess.run(
                    ["git", "pull", "--ff-only"],
                    cwd=str(target),
                    capture_output=True,
                    text=True,
                    timeout=60,
                    encoding="utf-8",
                )
                if r.returncode == 0:
                    ext["updated_at"] = __import__("time").time()
                    self._save()
                    return True
            except (subprocess.SubprocessError, OSError) as e:
                logger.warning("extension_update_failed ext_id=%s error=%s", ext_id, e)
                return False
        return False

    def get_config(self, ext_id: str, key: str = None, default=None):
        """获取扩展配置"""
        if ext_id not in self._installed:
            return default
        config_file = EXTENSIONS_DIR / ext_id.replace("/", "_") / "config.json"
        if config_file.exists():
            try:
                data = json.loads(config_file.read_text(encoding="utf-8"))
                return data.get(key, default) if key else data
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("extension_config_load_failed ext_id=%s error=%s", ext_id, e)
                return default
        return default

    def set_config(self, ext_id: str, key: str, value) -> bool:
        """设置扩展配置"""
        if ext_id not in self._installed:
            return False
        config_file = EXTENSIONS_DIR / ext_id.replace("/", "_") / "config.json"
        data = {}
        if config_file.exists():
            try:
                data = json.loads(config_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("extension_config_read_failed ext_id=%s error=%s", ext_id, e)
                data = {}
        data[key] = value
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True

    def uninstall(self, ext_id: str) -> bool:
        """卸载扩展"""
        if ext_id not in self._installed:
            return False
        path_str = self._installed[ext_id].get("path", "")
        if path_str:
            target = Path(path_str)
            if target.exists() and target.is_relative_to(EXTENSIONS_DIR):
                shutil.rmtree(target)
        del self._installed[ext_id]
        self._save()
        return True

    def get_installed(self) -> list[dict]:
        return list(self._installed.values())

    def is_installed(self, ext_id: str) -> bool:
        return ext_id in self._installed

    def _load_installed(self):
        config_file = EXTENSIONS_DIR / "installed.json"
        if config_file.exists():
            try:
                self._installed = json.loads(config_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("installed_extensions_load_failed error=%s", e)
                self._installed = {}

    def _save(self):
        (EXTENSIONS_DIR / "installed.json").write_text(
            json.dumps(self._installed, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── 扩展主机集成 ──

    async def activate_all(self) -> dict[str, bool]:
        """激活所有已启用的扩展（async，通过 ExtensionHostManager）"""
        from pycoder.extensions.host import get_extension_host

        host = get_extension_host()
        installed = self.get_installed()
        return await host.activate_all(installed)

    async def activate_extension(self, ext_id: str) -> bool:
        """激活单个扩展（async）"""
        from pycoder.extensions.host import get_extension_host

        host = get_extension_host()
        return await host.activate_extension(ext_id)

    def deactivate_extension(self, ext_id: str) -> bool:
        """停用单个扩展"""
        from pycoder.extensions.host import get_extension_host

        host = get_extension_host()
        return host.deactivate_extension(ext_id)

    async def execute_extension_function(
        self,
        ext_id: str,
        func_name: str,
        args: dict | None = None,
        timeout: float = 30.0,
    ) -> dict:
        """在扩展沙箱中执行函数（async，避免 FastAPI 死锁）"""
        from pycoder.extensions.host import get_extension_host

        host = get_extension_host()
        return await host.execute(ext_id, func_name, args, timeout)

    # ── 扩展脚手架 ──

    def scaffold_extension(
        self,
        ext_id: str,
        name: str = "",
        description: str = "",
        author: str = "",
    ) -> str:
        """创建扩展脚手架"""
        from pycoder.extensions.packaging import scaffold

        return scaffold(ext_id, name or ext_id.split(".")[-1], description, author)

    # ── 扩展详情 ──

    def get_extension_details(self, ext_id: str) -> dict | None:
        """获取扩展完整详情（含贡献点）"""
        if ext_id not in self._installed:
            return None

        ext = dict(self._installed[ext_id])
        target = EXTENSIONS_DIR / ext_id.replace("/", "_")

        # 读取 manifest
        manifest_file = target / "manifest.json"
        manifest = {}
        if manifest_file.exists():
            try:
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                import logging as _lg

                _lg.getLogger(__name__).warning(
                    "extensions_config_load_failed error=%s",
                    e,
                )

        # 解析贡献点
        from pycoder.extensions.contributions import parse_contributions_from_manifest

        contribs = parse_contributions_from_manifest(manifest)

        # 其他文件信息
        has_readme = (target / "README.md").exists()
        has_changelog = (target / "CHANGELOG.md").exists()
        code_path = target / "extension.py"
        code_size = code_path.stat().st_size if code_path.exists() else 0

        ext["manifest"] = manifest
        ext["contributions"] = {
            "commands": [
                {"id": c.id, "title": c.title, "category": c.category} for c in contribs.commands
            ],
            "settings": [
                {"id": s.id, "title": s.title, "type": s.type, "default": s.default}
                for s in contribs.settings
            ],
            "keybindings": [{"key": k.key, "command": k.command} for k in contribs.keybindings],
            "views": [{"id": v.id, "name": v.name} for v in contribs.views],
            "menus": [{"command": m.command, "group": m.group} for m in contribs.menus],
        }
        ext["has_readme"] = has_readme
        ext["has_changelog"] = has_changelog
        ext["code_size"] = code_size

        # 沙箱状态
        from pycoder.extensions.host import get_extension_host

        host = get_extension_host()
        ext["activated"] = host.is_activated(ext_id)
        ext["available_functions"] = []
        sandbox = host.get_sandbox(ext_id)
        if sandbox:
            ext["available_functions"] = sandbox.get_available_functions()

        return ext

    # ── 统计 ──

    def get_stats(self) -> dict:
        """获取扩展系统统计"""
        installed = self._installed
        total = len(installed)
        enabled = sum(1 for e in installed.values() if e.get("enabled", True))
        disabled = total - enabled

        from pycoder.extensions.host import get_extension_host

        host = get_extension_host()

        from pycoder.extensions.contributions import get_command_registry, get_settings_registry

        cmd_reg = get_command_registry()
        set_reg = get_settings_registry()

        return {
            "total_installed": total,
            "enabled": enabled,
            "disabled": disabled,
            "activated": host.count_activated(),
            "commands_registered": cmd_reg.count(),
            "settings_registered": len(set_reg.list_settings()),
            "categories": list({e.get("category", "Other") for e in installed.values()}),
        }
