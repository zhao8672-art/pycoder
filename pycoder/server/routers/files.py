"""
文件系统 API — Web IDE 文件浏览/读写

端点:
    GET  /api/files/list?path=.    — 列出目录内容
    GET  /api/files/read?path=...  — 读取文件内容
    POST /api/files/write          — 写入文件

安全:
    - 所有路径限定在 WORKSPACE_ROOT 内
    - 禁止 .. 路径穿越
    - 禁止符号链接指向工作区外
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/files")


# ── 工作目录（可动态切换）─────────────────────────────────
def _detect_workspace_root() -> Path:
    """检测项目根目录：优先 PYCODER_WORKSPACE 环境变量，其次 os.getcwd()，再 last_workspace.json。"""
    env_ws = os.environ.get("PYCODER_WORKSPACE", "")
    if env_ws:
        p = Path(env_ws).resolve()
        if p.is_dir() and (p / ".git").is_dir():
            return p
    # 优先检测当前工作目录（最可靠）
    try:
        cwd = Path.cwd().resolve()
        if cwd.is_dir():
            if (cwd / ".git").is_dir() and (cwd / "pycoder").is_dir():
                return cwd
            # 向上查找 pycoder 项目
            for parent in cwd.parents:
                if (parent / ".git").is_dir() and (parent / "pycoder").is_dir():
                    return parent
                if (parent / "pycoder").is_dir() and (parent / "pyproject.toml").is_file():
                    return parent
    except OSError:
        logger.debug("cwd_detection_failed", exc_info=True)
    # 再尝试从 last_workspace.json 恢复（验证更严格）
    try:
        lwf_std = Path.home() / ".pycoder" / "last_workspace.json"
        if lwf_std.is_file():
            import json as _json

            data = _json.loads(lwf_std.read_text(encoding="utf-8"))
            p = Path(data["path"]).resolve()
            if p.is_dir() and (p / ".git").is_dir() and (p / "pycoder").is_dir():
                return p
    except (OSError, ValueError, KeyError) as e:
        logger.debug("last_workspace_restore_failed error=%s", e)
    # 最后一招：从文件位置推断
    probe = Path(__file__).resolve().parents[3]
    if (probe / "pycoder").is_dir():
        return probe
    return probe


_WORKSPACE_ROOT: Path = _detect_workspace_root()

LAST_WORKSPACE_FILE = Path.home() / ".pycoder" / "last_workspace.json"
RECENT_WORKSPACES_FILE = Path.home() / ".pycoder" / "recent_workspaces.json"
MAX_HISTORY = 20


def get_workspace_root() -> Path:
    """获取当前工作区根目录

    尊重已显式设置的 _WORKSPACE_ROOT（如 switch_workspace 或测试 monkeypatch）。
    仅当缓存值为 None 或不存在时才重新检测。
    """
    global _WORKSPACE_ROOT
    if _WORKSPACE_ROOT is not None:
        try:
            if _WORKSPACE_ROOT.is_dir():
                return _WORKSPACE_ROOT
        except OSError:
            logger.debug("workspace_root_check_failed", exc_info=True)
    _WORKSPACE_ROOT = _detect_workspace_root()
    return _WORKSPACE_ROOT


# ── 工作区切换 API ─────────────────────────────────────


@router.post("/workspace/switch")
async def switch_workspace(req: dict):
    """切换工作区根目录（持久化）"""
    global _WORKSPACE_ROOT
    new_path = req.get("path", "")
    if not new_path:
        raise HTTPException(400, "path is required")
    target = Path(new_path).resolve()
    if not target.exists() or not target.is_dir():
        raise HTTPException(400, f"目录不存在: {new_path}")
    _WORKSPACE_ROOT = target
    os.environ["PYCODER_WORKSPACE"] = str(target)

    # 持久化到 last_workspace.json
    import json
    import time

    LAST_WORKSPACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_WORKSPACE_FILE.write_text(
        json.dumps({"path": str(target), "timestamp": time.time()}),
        encoding="utf-8",
    )

    # 追加到 recent_workspaces.json
    recent = []
    if RECENT_WORKSPACES_FILE.exists():
        try:
            recent = json.loads(RECENT_WORKSPACES_FILE.read_text(encoding="utf-8"))
        except Exception:
            recent = []
    # 去重
    recent = [r for r in recent if r.get("path") != str(target)]
    recent.insert(0, {"path": str(target), "timestamp": time.time()})
    recent = recent[:MAX_HISTORY]
    RECENT_WORKSPACES_FILE.write_text(json.dumps(recent, indent=2), encoding="utf-8")

    return {"workspace": str(target), "name": target.name}


@router.get("/workspace/current")
async def get_current_workspace():
    """获取当前工作区"""
    return {"workspace": str(_WORKSPACE_ROOT), "name": _WORKSPACE_ROOT.name}


@router.get("/workspace/recent")
async def get_recent_workspaces():
    """读取最近打开的项目列表"""
    import json

    if RECENT_WORKSPACES_FILE.exists():
        return {"recent": json.loads(RECENT_WORKSPACES_FILE.read_text(encoding="utf-8"))}
    return {"recent": []}


@router.get("/workspace/restore")
async def restore_workspace():
    """重启时自动恢复上次工作区"""
    if LAST_WORKSPACE_FILE.exists():
        import json

        try:
            data = json.loads(LAST_WORKSPACE_FILE.read_text(encoding="utf-8"))
            path = data.get("path", "")
            if path and Path(path).exists():
                global _WORKSPACE_ROOT
                _WORKSPACE_ROOT = Path(path).resolve()
                os.environ["PYCODER_WORKSPACE"] = str(_WORKSPACE_ROOT)
                return {"success": True, "path": str(_WORKSPACE_ROOT), "restored": True}
        except (json.JSONDecodeError, OSError, TypeError, KeyError) as e:
            logger.warning("workspace_restore_failed error=%s", e)
    return {"success": True, "path": str(_WORKSPACE_ROOT), "restored": False}


# ── 语言映射 ──────────────────────────────────────────────
_LANG_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".ps1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
    ".xml": "xml",
    ".svg": "xml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".txt": "plaintext",
    ".csv": "plaintext",
    ".log": "plaintext",
    ".env": "plaintext",
    ".dockerfile": "dockerfile",
    ".vue": "vue",
    ".svelte": "svelte",
}

# 文件夹图标类型
_DIR_ICON = "folder"
_FILE_ICON = "file"


# ── 安全工具 ──────────────────────────────────────────────


def _safe_path(rel_path: str) -> Path:
    """
    将相对路径解析为绝对路径并校验不逃出工作区。

    Raises:
        HTTPException 400 — 路径穿越
        HTTPException 400 — 路径无效
    """
    if not rel_path or rel_path == ".":
        return _WORKSPACE_ROOT

    # 规范化：先解析以消除 .. 段
    candidate = (_WORKSPACE_ROOT / rel_path).resolve()

    # 必须在工作区内（含自身）— 用 is_relative_to 替代字符串前缀匹配（M8 修复）
    if not candidate.is_relative_to(_WORKSPACE_ROOT):
        raise HTTPException(
            status_code=400,
            detail=f"路径穿越被拦截: {rel_path}",
        )

    return candidate


def _detect_language(file_path: Path) -> str:
    """根据扩展名返回 Monaco 语言 ID"""
    suffix = file_path.suffix.lower()
    return _LANG_MAP.get(suffix, "plaintext")


def _file_icon(is_dir: bool, file_path: Path) -> str:
    """返回文件/文件夹图标标识"""
    if is_dir:
        return _DIR_ICON
    suffix = file_path.suffix.lower().lstrip(".")
    return suffix or _FILE_ICON


# ── API 端点 ──────────────────────────────────────────────


class FileItem:
    """目录项"""

    def __init__(self, name: str, is_dir: bool, path: str, size: int = 0, icon: str = "file"):
        self.name = name
        self.is_dir = is_dir
        self.path = path
        self.size = size
        self.icon = icon

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "is_dir": self.is_dir,
            "path": self.path,
            "size": self.size,
            "icon": self.icon,
        }


@router.get("/list")
async def list_files(path: str = Query(default=".", description="目录路径")):
    """
    列出目录内容（文件+文件夹），含图标类型。

    返回:
        {
            "path": "当前路径",
            "workspace": "工作区根路径",
            "items": [...]
        }
    """
    target = _safe_path(path)

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"路径不存在: {path}")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"不是目录: {path}")

    items: list[FileItem] = []

    try:
        entries = sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"无权访问: {path}") from None

    for entry in entries:
        is_dir = entry.is_dir()
        icon = _file_icon(is_dir, entry)

        try:
            size = entry.stat().st_size if not is_dir else 0
        except OSError:
            size = 0

        # 计算相对于工作区的路径
        try:
            rel = str(entry.relative_to(_WORKSPACE_ROOT)).replace("\\", "/")
        except ValueError:
            rel = entry.name

        items.append(
            FileItem(
                name=entry.name,
                is_dir=is_dir,
                path=rel,
                size=size,
                icon=icon,
            ).to_dict()
        )

    # 返回的 path 也相对化
    try:
        display_path = str(target.relative_to(_WORKSPACE_ROOT)).replace("\\", "/")
    except ValueError:
        display_path = "."

    return {
        "path": display_path,
        "workspace": str(_WORKSPACE_ROOT),
        "items": items,
    }


@router.get("/read")
async def read_file(path: str = Query(..., description="文件路径")):
    """
    读取文件内容，返回 content + language。

    返回:
        {
            "path": "文件路径",
            "content": "文件内容",
            "language": "python",
            "size": 1234,
            "encoding": "utf-8"
        }
    """
    target = _safe_path(path)

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {path}")
    if target.is_dir():
        raise HTTPException(status_code=400, detail=f"是目录不是文件: {path}")

    # 安全读取：限制最大 1MB
    MAX_SIZE = 1 * 1024 * 1024
    try:
        file_size = target.stat().st_size
    except OSError:
        raise HTTPException(status_code=500, detail="无法获取文件信息") from None

    if file_size > MAX_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大 ({file_size} bytes)，最大允许 {MAX_SIZE} bytes",
        )

    # 尝试多种编码
    content = None
    encoding = "utf-8"
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            content = target.read_text(encoding=enc)
            encoding = enc
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    if content is None:
        # 二进制文件，返回 base64 提示
        raise HTTPException(
            status_code=415,
            detail="不支持的文件编码（可能是二进制文件）",
        )

    language = _detect_language(target)

    try:
        display_path = str(target.relative_to(_WORKSPACE_ROOT)).replace("\\", "/")
    except ValueError:
        display_path = target.name

    return {
        "path": display_path,
        "content": content,
        "language": language,
        "size": file_size,
        "encoding": encoding,
    }


class FileWriteRequest(BaseModel):
    """写入文件请求体"""

    path: str = Field(..., description="文件路径")
    content: str = Field(..., description="文件内容")


@router.post("/write")
async def write_file(req: FileWriteRequest):
    """
    写入文件（覆盖或新建）。接受 JSON body: {"path": "...", "content": "..."}

    返回:
        {
            "path": "文件路径",
            "size": 写入字节数,
            "success": true
        }
    """
    target = _safe_path(req.path)

    # 不允许写入目录
    if target.exists() and target.is_dir():
        raise HTTPException(status_code=400, detail=f"是目录不是文件: {req.path}")

    # 自动创建父目录
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"创建目录失败: {e}") from e

    try:
        target.write_text(req.content, encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"写入文件失败: {e}") from e

    try:
        display_path = str(target.relative_to(_WORKSPACE_ROOT)).replace("\\", "/")
    except ValueError:
        display_path = target.name

    return {
        "path": display_path,
        "size": len(req.content.encode("utf-8")),
        "success": True,
    }
