"""
代码可视化 — 生成项目结构、依赖图、调用关系图

端点:
    GET  /api/visualize/structure  — 生成项目结构树
    GET  /api/visualize/imports   — 分析导入依赖关系
    GET  /api/visualize/calls     — 分析函数调用关系（支持 path query）
    POST /api/visualize/calls     — 同上（兼容旧版调用）
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/visualize")

WORKSPACE_ROOT = Path(
    os.environ.get("PYCODER_WORKSPACE", str(Path(__file__).resolve().parents[3]))
).resolve()


@dataclass
class StructureNode:
    """树节点"""

    name: str
    path: str
    type: str  # "dir" | "file" | "package"
    children: list = field(default_factory=list)
    depth: int = 0


@dataclass
class ImportEdge:
    """导入边"""

    from_module: str
    to_module: str
    line: int
    is_star: bool = False


@dataclass
class CallNode:
    """调用节点"""

    name: str
    module: str
    lineno: int
    calls: list = field(default_factory=list)


class StructureResponse(BaseModel):
    success: bool
    tree: dict | None = None
    stats: dict | None = None
    root: str | None = None


class ImportsResponse(BaseModel):
    success: bool
    edges: list = field(default_factory=list)
    modules: list = field(default_factory=list)
    stats: dict | None = None


class CallsResponse(BaseModel):
    success: bool
    functions: list = field(default_factory=list)
    stats: dict | None = None


# ── 工具函数 ──────────────────────────────────────────────
IGNORE_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".env",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    ".egg-info",
}
IGNORE_EXTS = {".pyc", ".pyo", ".so", ".dll", ".dylib", ".exe"}


def _scan_structure(root: Path, max_depth: int = 3, current_depth: int = 0) -> StructureNode | None:
    """递归扫描目录结构"""
    if current_depth > max_depth:
        return None

    try:
        entries = list(root.iterdir())
    except (PermissionError, OSError):
        return None

    node = StructureNode(
        name=root.name,
        path=str(root.relative_to(root.parent)) if root.parent != root else root.name,
        type="dir",
        depth=current_depth,
    )

    dirs = []
    files = []

    for entry in entries:
        if entry.name in IGNORE_DIRS or entry.name.startswith("."):
            continue
        if entry.suffix in IGNORE_EXTS:
            continue

        if entry.is_dir():
            dirs.append(entry)
        elif entry.is_file():
            files.append(entry)

    # 目录优先
    for d in sorted(dirs, key=lambda x: x.name):
        child = _scan_structure(d, max_depth, current_depth + 1)
        if child:
            node.children.append(child)
            node.type = "dir"

    # 然后是文件
    for f in sorted(files, key=lambda x: x.name):
        ext = f.suffix
        ftype = "file"
        if ext == ".py":
            ftype = "python"
        elif ext in [".md", ".txt", ".rst"]:
            ftype = "doc"
        elif ext in [".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"]:
            ftype = "config"
        elif ext in [".html", ".css", ".js", ".ts"]:
            ftype = "web"

        child = StructureNode(
            name=f.name,
            path=str(f.relative_to(root.parent)) if root.parent != root else str(f),
            type=ftype,
            depth=current_depth + 1,
        )
        node.children.append(child)

    if not node.children and node.type == "dir":
        return None

    return node


def _analyze_imports(file_path: Path) -> list[ImportEdge]:
    """分析单个文件的导入关系"""
    edges = []
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return edges

    module_name = str(file_path.relative_to(WORKSPACE_ROOT)).replace(os.sep, ".").replace("/", ".")
    if module_name.endswith(".py"):
        module_name = module_name[:-3]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                edges.append(
                    ImportEdge(
                        from_module=module_name,
                        to_module=alias.name,
                        line=node.lineno,
                        is_star=(alias.name == "*"),
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                for alias in node.names:
                    if alias.name == "*":
                        edges.append(
                            ImportEdge(
                                from_module=module_name,
                                to_module=node.module,
                                line=node.lineno,
                                is_star=True,
                            )
                        )
                    else:
                        edges.append(
                            ImportEdge(
                                from_module=module_name,
                                to_module=f"{node.module}.{alias.name}",
                                line=node.lineno,
                                is_star=False,
                            )
                        )

    return edges


def _analyze_calls(file_path: Path) -> list[CallNode]:
    """分析函数调用关系"""
    functions = []
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return functions

    module_name = str(file_path.relative_to(WORKSPACE_ROOT)).replace(os.sep, ".").replace("/", ".")
    if module_name.endswith(".py"):
        module_name = module_name[:-3]

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            func = CallNode(name=node.name, module=module_name, lineno=node.lineno, calls=[])

            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        func.calls.append(child.func.id)
                    elif isinstance(child.func, ast.Attribute):
                        func.calls.append(child.func.attr)

            functions.append(func)

    return functions


# ── 端点 ──────────────────────────────────────────────────
@router.get("/structure", response_model=StructureResponse)
async def get_project_structure(
    path: str | None = Query(None, description="项目路径，默认为工作区根目录"),
    max_depth: int = Query(3, ge=1, le=5, description="最大深度"),
):
    """生成项目结构树"""
    try:
        root = Path(path) if path else WORKSPACE_ROOT
        if not root.exists():
            return StructureResponse(success=False)

        tree = _scan_structure(root, max_depth)
        if not tree:
            return StructureResponse(success=False)

        # 统计信息
        stats = {
            "total_dirs": 0,
            "total_files": 0,
            "python_files": 0,
            "test_files": 0,
            "config_files": 0,
            "max_depth": 0,
        }

        def count_nodes(node: StructureNode):
            if node.type == "dir":
                stats["total_dirs"] += 1
            else:
                stats["total_files"] += 1
                if node.type == "python":
                    stats["python_files"] += 1
                    if "test" in node.name.lower():
                        stats["test_files"] += 1
                elif node.type == "config":
                    stats["config_files"] += 1
            stats["max_depth"] = max(stats["max_depth"], node.depth)
            for child in node.children:
                count_nodes(child)

        if tree:
            count_nodes(tree)

        return StructureResponse(
            success=True,
            tree={
                "name": tree.name,
                "path": tree.path,
                "type": tree.type,
                "children": tree.children,
                "depth": tree.depth,
            },
            stats=stats,
            root=str(root),
        )
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError):
        return StructureResponse(success=False)


@router.get("/imports", response_model=ImportsResponse)
async def analyze_imports(
    path: str | None = Query(None, description="项目路径，默认为工作区根目录")
):
    """分析项目导入依赖关系"""
    try:
        root = Path(path) if path else WORKSPACE_ROOT
        if not root.exists():
            return ImportsResponse(success=False, edges=[], modules=[])

        all_edges = []
        all_modules = set()

        for py_file in root.rglob("*.py"):
            if any(ignore in py_file.parts for ignore in IGNORE_DIRS):
                continue
            edges = _analyze_imports(py_file)
            all_edges.extend(edges)
            for edge in edges:
                all_modules.add(edge.from_module)
                all_modules.add(edge.to_module)

        # 统计
        stats = {
            "total_edges": len(all_edges),
            "total_modules": len(all_modules),
            "star_imports": sum(1 for e in all_edges if e.is_star),
            "internal_imports": sum(1 for e in all_edges if not e.to_module.startswith(".")),
        }

        return ImportsResponse(
            success=True,
            edges=[
                {"from": e.from_module, "to": e.to_module, "line": e.line, "star": e.is_star}
                for e in all_edges
            ],
            modules=sorted(all_modules),
            stats=stats,
        )
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError):
        return ImportsResponse(success=False, edges=[], modules=[])


@router.get("/calls", response_model=CallsResponse)
async def analyze_calls_get(path: str | None = Query(None, description="文件路径")):
    """GET 版本 — 通过 query 参数 path 指定文件。"""
    return await _analyze_calls_impl(path)


@router.post("/calls", response_model=CallsResponse)
async def analyze_calls(body: dict | None = None):
    """POST 版本 — 通过 body.path 指定文件，兼容旧版调用。"""
    path = None
    if body and isinstance(body, dict):
        path = body.get("path")
    return await _analyze_calls_impl(path)


async def _analyze_calls_impl(path: str | None) -> CallsResponse:
    """分析函数调用关系 — 共享实现"""
    try:
        if not path:
            return CallsResponse(success=False, functions=[])

        file_path = Path(path)
        if not file_path.exists() or not file_path.suffix == ".py":
            return CallsResponse(success=False, functions=[])

        functions = _analyze_calls(file_path)

        # 统计
        stats = {
            "total_functions": len(functions),
            "total_calls": sum(len(f.calls) for f in functions),
            "max_calls": max((len(f.calls) for f in functions), default=0),
            "avg_calls": sum(len(f.calls) for f in functions) / len(functions) if functions else 0,
        }

        return CallsResponse(
            success=True,
            functions=[
                {
                    "name": f.name,
                    "module": f.module,
                    "lineno": f.lineno,
                    "calls": f.calls,
                    "num_calls": len(f.calls),
                }
                for f in functions
            ],
            stats=stats,
        )
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError):
        return CallsResponse(success=False, functions=[])
