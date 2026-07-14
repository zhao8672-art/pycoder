"""
MCP Tool 注册表 — 将 pycode 内部工具函数包装为 MCP 标准 Tool

两类角色:
  1. Tool Provider — 将内部能力（代码执行、Git、文件、分析等）注册为 MCP Tool
  2. MCP Client — 连接外部 MCP Server（GitHub、浏览器、数据库等）

前端通过 WebSocket 的 "mcp_call" 消息类型调用 /mcp 命令查看工具列表。
"""

from __future__ import annotations

import ast
import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pycoder.server.log import log

# 加载从 mcp_tools.py 拆分的模块（自动注册数据库/K8s/监控工具）
try:
    import pycoder.server.mcp_tools_db  # noqa: F401
except ImportError:
    pass


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


@dataclass
class MCPToolDef:
    """单个 MCP Tool 定义"""

    name: str
    description: str
    input_schema: dict
    handler: callable = None  # 注册时绑定


@dataclass
class MCPCallResult:
    """MCP 调用结果"""

    success: bool
    output: Any = None
    error: str = ""
    tool: str = ""


# ══════════════════════════════════════════════════════════
# 内置 Tool 注册表
# ══════════════════════════════════════════════════════════

_builtin_tools: dict[str, MCPToolDef] = {}
_v2_registry: Any = None  # V2 CapabilityRegistry 引用


def _register(name: str, description: str, input_schema: dict, handler: callable):
    """注册一个内置 Tool，同时注册到 V2 能力总线"""
    _builtin_tools[name] = MCPToolDef(
        name=name,
        description=description,
        input_schema=input_schema,
        handler=handler,
    )

    # ── V2: 同步注册到 V2 能力总线 ──
    _sync_to_v2_bus(name, description, input_schema, handler)


def _sync_to_v2_bus(name: str, description: str, input_schema: dict, handler: callable):
    """将 V1 工具同步注册到 V2 能力总线"""
    global _v2_registry
    try:
        if _v2_registry is None:
            from pycoder.server.app import get_v2_engine
            engine = get_v2_engine()
            if engine:
                _v2_registry = engine.registry

        if _v2_registry is None:
            return

        from pycoder.bus.protocol import (
            CapabilityCategory, CapabilityDefinition,
            ExecutionMode, SideEffect, TrustLevel,
        )

        # 自动推断能力类别和权限
        category = _infer_category(name, description)
        permission = _infer_permission(name, description)

        cap_def = CapabilityDefinition(
            id=f"v1.{name}",  # v1. 前缀区分来源
            name=name,
            description=description,
            category=category,
            permission=permission,
            execution=ExecutionMode.SYNC,
            side_effects=_infer_side_effects(name),
            schema=input_schema,
            tags=["v1_migrated", name],
        )

        # 创建适配器处理器
        async def _v2_handler(params: dict, context: dict) -> Any:
            result = await handler(params) if hasattr(handler, '__call__') else handler(params)
            return result

        _v2_registry.register(cap_def, handler=_v2_handler)

    except (ImportError, AttributeError, TypeError, ValueError):
        pass  # V2 未初始化时静默跳过


def _infer_category(name: str, description: str) -> "CapabilityCategory":
    from pycoder.bus.protocol import CapabilityCategory
    name_lower = (name + description).lower()
    if any(kw in name_lower for kw in ["read", "write", "file", "edit", "format", "debug"]):
        return CapabilityCategory.EDITOR
    if any(kw in name_lower for kw in ["git", "shell", "terminal", "execute", "docker", "env"]):
        return CapabilityCategory.SYSTEM
    if any(kw in name_lower for kw in ["scan", "fix", "test", "deploy", "evolv", "learn"]):
        return CapabilityCategory.SELF_EVO
    return CapabilityCategory.SYSTEM


def _infer_permission(name: str, description: str) -> "TrustLevel":
    from pycoder.bus.protocol import TrustLevel
    name_lower = (name + description).lower()
    if any(kw in name_lower for kw in ["delete", "remove", "push", "deploy", "evolv", "restart"]):
        return TrustLevel.PROJECT_WRITE
    if any(kw in name_lower for kw in ["install", "uninstall", "docker", "network"]):
        return TrustLevel.SYSTEM_ACCESS
    if any(kw in name_lower for kw in ["read", "list", "search", "status", "log", "diff"]):
        return TrustLevel.READ_ONLY
    return TrustLevel.WORKSPACE_WRITE


def _infer_side_effects(name: str) -> list:
    from pycoder.bus.protocol import SideEffect
    name_lower = name.lower()
    effects = []
    if "write" in name_lower or "create" in name_lower or "delete" in name_lower:
        effects.append(SideEffect.FILE_WRITE)
    if "execute" in name_lower or "run" in name_lower:
        effects.append(SideEffect.PROCESS)
    if "network" in name_lower or "http" in name_lower or "fetch" in name_lower:
        effects.append(SideEffect.NETWORK)
    if not effects:
        effects.append(SideEffect.NONE)
    return effects


# 加载文件操作工具（read_file / write_file / list_files / delete_file / create_directory / run_terminal）
try:
    from pycoder.server.mcp import file_tools

    file_tools.register_all(_register)
except ImportError:
    pass

# 加载多语言执行工具（execute_multilang / list_languages）
try:
    from pycoder.server.mcp import multilang_tools

    multilang_tools.register_all(_register)
except ImportError:
    pass


# ── 工具: 执行 Python 代码 ─────────────────────────────


async def _handle_execute_python(args: dict) -> dict:
    """在沙箱中安全执行 Python 代码"""
    from pycoder.server.routers.code_exec import _run_in_subprocess

    code = args.get("code", "")
    timeout = args.get("timeout", 30)
    try:
        result = await asyncio.to_thread(_run_in_subprocess, code, timeout)
        return {
            "success": result.success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "error": result.error_message if not result.success else "",
            "error_type": result.error_type,
            "execution_time": result.execution_time,
        }
    except (OSError, ValueError, RuntimeError, TimeoutError) as e:
        return {"success": False, "error": str(e)}


_register(
    name="execute_python",
    description="在沙箱中安全执行 Python 代码并返回结果",
    input_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "要执行的 Python 代码"},
            "timeout": {"type": "number", "description": "超时秒数", "default": 30},
        },
        "required": ["code"],
    },
    handler=_handle_execute_python,
)


# ── 工具: 多语言代码执行 ────────────────────────────────


async def _handle_multilang(args: dict) -> dict:
    """在临时沙箱中编译并运行 Java/Go/Rust/C/C++/JS/TS 代码"""
    from pycoder.python.multilang_executor import execute_multilang

    language = args.get("language", "python")
    code = args.get("code", "")
    timeout = args.get("timeout", 30)
    return await execute_multilang(language, code, timeout)


_register(
    name="execute_multilang",
    description="在沙箱中编译并运行多语言代码（Java/Go/Rust/C/C++/JavaScript/TypeScript/Bash）。自动检测已安装的运行时",
    input_schema={
        "type": "object",
        "properties": {
            "language": {
                "type": "string",
                "description": "编程语言（java/go/rust/c/cpp/javascript/typescript/python/bash）",
            },
            "code": {"type": "string", "description": "完整的源代码"},
            "timeout": {"type": "number", "description": "超时秒数", "default": 30},
        },
        "required": ["language", "code"],
    },
    handler=_handle_multilang,
)


async def _handle_list_languages(args: dict) -> dict:
    """列出所有可用的多语言运行时"""
    from pycoder.python.multilang_executor import list_available

    available = list_available()
    return {"success": True, "languages": available, "count": len(available)}


_register(
    name="list_languages",
    description="列出系统中所有可用的编程语言运行时（Java/Go/Rust/C/C++/JS/TS等）",
    input_schema={"type": "object", "properties": {}},
    handler=_handle_list_languages,
)


# ── 工具: 代码质量分析（改进版 — 含置信度评级） ────────


async def _handle_code_review(args: dict) -> dict:
    """对代码片段进行静态分析评分

    改进说明:
    - 每个问题附带置信度评级 (high/medium/low)
    - 区分误报风险等级
    - 明确标注检测模式（正则 / AST / 启发式）
    - 提供缓解建议而非仅告警
    """
    from pycoder.python.code_quality import CodeQualityAnalyzer, QualityScore

    analyzer = CodeQualityAnalyzer()
    code = args.get("code", "")
    result = analyzer.analyze(code)  # dict: {quality_score, performance_issues, ...}
    qs = result.get("quality_score", QualityScore(0, 0, 0, 0, 0, 0))

    # 收集所有类别的问题
    scored_issues = []
    all_issues = []
    for key in ("performance_issues", "architecture_issues", "refactoring_suggestions"):
        all_issues.extend(result.get(key, []))
    for issue in all_issues:
        severity = issue.get("severity", "medium") if isinstance(issue, dict) else "medium"
        confidence_map = {"critical": "high", "high": "high", "medium": "medium", "low": "low"}
        scored_issues.append(
            {
                **(issue if isinstance(issue, dict) else {"message": str(issue)}),
                "confidence": confidence_map.get(severity, "medium"),
                "detection_method": ("AST" if isinstance(issue, dict) and issue.get("line") else "pattern"),
                "mitigation_hint": _get_mitigation_hint(issue if isinstance(issue, dict) else {}),
                "false_positive_risk": (
                    "低 (AST 精确匹配)" if isinstance(issue, dict) and issue.get("line") else "中 (模式匹配可能误报)"
                ),
            }
        )

    return {
        "success": True,
        "scores": {
            "overall": qs.overall,
            "readability": qs.readability,
            "maintainability": qs.maintainability,
            "performance": qs.performance,
            "security": qs.security,
        },
        "issues": scored_issues,
        "summary": f"发现 {len(scored_issues)} 个问题，综合评分 {qs.overall}/100",
        "limitations": "静态分析仅检测模式匹配问题，无法理解业务语义。请结合人工审查使用。",
    }


def _get_mitigation_hint(issue: dict) -> str:
    """为常见问题类型提供缓解建议"""
    issue_type = issue.get("type", "")
    hints = {
        "security": "考虑输入验证和最小权限原则",
        "performance": "考虑缓存、延迟加载或算法优化",
        "maintainability": "考虑拆分为更小函数或使用设计模式",
        "readability": "添加中文注释、改进变量命名",
        "bug": "添加边界条件检查和单元测试",
    }
    return hints.get(issue_type, "根据实际业务逻辑评估必要性")


_register(
    name="code_review",
    description="对代码片段进行静态分析，返回质量评分和问题列表（含置信度评级）",
    input_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "要审查的代码"},
            "language": {"type": "string", "description": "代码语言", "default": "python"},
        },
        "required": ["code"],
    },
    handler=_handle_code_review,
)


# ── 工具: 依赖分析 ──────────────────────────────────────


async def _handle_dep_analysis(args: dict) -> dict:
    """分析项目依赖"""
    from pycoder.python.dep_analyzer import DependencyAnalyzer

    analyzer = DependencyAnalyzer()
    path = args.get("path", ".")
    result = analyzer.analyze(Path(path))
    return {
        "success": True,
        "dependencies": [
            d.to_dict() if hasattr(d, "to_dict") else {"name": d.name}
            for d in result.get("dependencies", [])
        ],
        "summary": result.get("summary", ""),
    }


_register(
    name="dependency_analysis",
    description="分析项目的 Python 依赖树",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "项目路径", "default": "."},
        },
    },
    handler=_handle_dep_analysis,
)


# ── 工具: Git 状态 ─────────────────────────────────────


async def _handle_git_status(args: dict) -> dict:
    """获取 Git 仓库状态"""
    path = args.get("path", os.getcwd())
    try:
        from git import Repo

        repo = Repo(path)
        branch = repo.active_branch.name if repo.active_branch else None
        status = repo.git.status("--porcelain")
        lines = [line.strip() for line in status.split("\n") if line.strip()]
        return {
            "success": True,
            "branch": branch,
            "changed_files": len(lines),
            "changes": lines[:50],  # 最多 50 条
            "is_dirty": bool(lines),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="git_status",
    description="获取 Git 仓库状态概览（分支、变更文件等）",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "仓库路径", "default": "."},
        },
    },
    handler=_handle_git_status,
)


# ── 工具: 文件操作 ────────────────────────────────────


async def _handle_file_read(args: dict) -> dict:
    """读取文件内容"""
    path = args.get("path", "")
    max_length = args.get("max_length", 10000)
    try:
        target = Path(path)
        if not target.exists():
            return {"success": False, "error": f"文件不存在: {path}"}
        content = target.read_text(encoding="utf-8")
        truncated = len(content) > max_length
        return {
            "success": True,
            "content": content[:max_length],
            "truncated": truncated,
            "total_length": len(content),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="file_read",
    description="读取文件内容（安全截断）",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "max_length": {"type": "number", "description": "最大读取字符数", "default": 10000},
        },
        "required": ["path"],
    },
    handler=_handle_file_read,
)


async def _handle_file_list(args: dict) -> dict:
    """列出目录内容"""
    path = args.get("path", ".")
    max_depth = args.get("max_depth", 2)
    try:
        from pycoder.server.project_helpers import _get_project_tree

        tree = await _get_project_tree(path, max_depth)
        return {"success": True, "tree": tree}
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="file_list",
    description="列出目录结构和文件",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目录路径", "default": "."},
            "max_depth": {"type": "number", "description": "最大深度", "default": 2},
        },
    },
    handler=_handle_file_list,
)


# ── 工具: 搜索 ─────────────────────────────────────────


async def _handle_search(args: dict) -> dict:
    """在项目中搜索文本"""
    query = args.get("query", "")
    include_pattern = args.get("include_pattern", "**/*.py")
    max_results = args.get("max_results", 20)
    try:
        results = []
        root = Path(os.getcwd())
        files = list(root.rglob(include_pattern))
        for f in files[:100]:  # 最多扫描 100 个文件
            if "__pycache__" in str(f) or "node_modules" in str(f):
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                for i, line in enumerate(content.split("\n"), 1):
                    if query.lower() in line.lower():
                        results.append(
                            {
                                "file": str(f.relative_to(root)),
                                "line": i,
                                "text": line.strip()[:200],
                            }
                        )
                        if len(results) >= max_results:
                            break
            except (OSError, UnicodeDecodeError, PermissionError) as e:
                log.debug("search_in_files_read_failed", path=str(f), error=str(e))
                continue
            if len(results) >= max_results:
                break
        return {"success": True, "results": results, "total": len(results)}
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="search",
    description="在项目中搜索文本内容",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "include_pattern": {
                "type": "string",
                "description": "文件匹配模式",
                "default": "**/*.py",
            },
            "max_results": {"type": "number", "description": "最大结果数", "default": 20},
        },
        "required": ["query"],
    },
    handler=_handle_search,
)


# ── 工具: 代码自动格式化 ─────────────────────────────


async def _handle_format_code(args: dict) -> dict:
    """用 black/ruff/isort 自动格式化 Python 代码"""
    code = args.get("code", "")
    style = args.get("style", "black")
    if not code:
        return {"success": False, "error": "缺少 code 参数"}
    try:
        import subprocess
        import sys
        import tempfile

        tf = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8")
        with tf as f:
            f.write(code)
            tmp_path = f.name
        try:
            if style == "isort":
                subprocess.run(
                    [sys.executable, "-m", "isort", tmp_path],
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
            elif style == "ruff":
                subprocess.run(
                    [sys.executable, "-m", "ruff", "format", tmp_path],
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
            else:
                subprocess.run(
                    [sys.executable, "-m", "black", "--quiet", tmp_path],
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
            formatted = Path(tmp_path).read_text(encoding="utf-8")
            return {"success": True, "formatted": formatted, "style": style}
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    except FileNotFoundError:
        return {"success": False, "error": f"{style} 未安装，请运行 pip install {style}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="format_code",
    description="用 black/ruff/isort 自动格式化 Python 代码",
    input_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "要格式化的 Python 代码"},
            "style": {
                "type": "string",
                "description": "格式化工具",
                "enum": ["black", "ruff", "isort"],
                "default": "black",
            },
        },
        "required": ["code"],
    },
    handler=_handle_format_code,
)


# ── 工具: 调试执行 Python ────────────────────────────


async def _handle_debug_python(args: dict) -> dict:
    """带断点调试的执行"""
    code = args.get("code", "")
    breakpoints = args.get("breakpoints", [])
    timeout = args.get("timeout", 30)
    try:
        # 在代码中注入断点
        if breakpoints:
            lines = code.split("\n")
            for bp in sorted(breakpoints, reverse=True):
                idx = bp - 1
                if 0 <= idx < len(lines):
                    indent = " " * (len(lines[idx]) - len(lines[idx].lstrip()))
                    lines.insert(idx, f"{indent}import pdb; pdb.set_trace()  # MCP breakpoint")
            code = "\n".join(lines)

        from pycoder.server.routers.code_exec import _run_in_subprocess

        result = await asyncio.to_thread(_run_in_subprocess, code, timeout)
        # traceback 字符串按换行切分为列表，兼容旧 stack_trace 接口
        stack_frames = (
            [line for line in result.traceback.split("\n") if line.strip()]
            if result.traceback
            else []
        )
        return {
            "success": result.success,
            "output": result.stdout,
            "error": result.error_message if not result.success else "",
            "stderr": result.stderr,
            "duration_ms": int(result.execution_time * 1000),
            "stack_trace": stack_frames,
        }
    except (OSError, ValueError, RuntimeError, TimeoutError) as e:
        return {"success": False, "error": str(e)}


_register(
    name="debug_python",
    description="带断点支持的 Python 代码执行和调试",
    input_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python 代码"},
            "breakpoints": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "断点行号列表",
                "default": [],
            },
            "timeout": {"type": "number", "description": "超时秒数", "default": 30},
        },
        "required": ["code"],
    },
    handler=_handle_debug_python,
)


# ── 工具: 依赖安全扫描 ────────────────────────────────


async def _handle_security_scan(args: dict) -> dict:
    """扫描项目依赖中的已知漏洞"""
    path = args.get("path", ".")
    try:
        from pycoder.python.dep_analyzer import DepAnalyzer

        analyzer = DepAnalyzer(path)
        deps = analyzer.analyze()
        scan = getattr(analyzer, "scan_vulnerabilities", None)
        vulnerabilities = scan() if scan else []
        return {
            "success": True,
            "total_deps": deps.total_deps,
            "vulnerabilities": vulnerabilities,
            "summary": f"扫描了 {deps.total_deps} 个依赖，发现 {len(vulnerabilities)} 个漏洞",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="security_scan",
    description="扫描项目依赖中的已知安全漏洞（集成 pip-audit）",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "项目路径", "default": "."},
        },
    },
    handler=_handle_security_scan,
)


# ── 工具: 生成测试骨架 ───────────────────────────────


async def _handle_generate_tests(args: dict) -> dict:
    """为 Python 文件生成 pytest 测试（含智能断言骨架）

    改进说明:
    - 分析函数签名自动推导参数类型
    - 为有返回类型的函数生成 assert 断言
    - 为 FastAPI 路由生成 HTTP 测试
    - 标注每个测试需要补充的断言逻辑
    """
    file_path = args.get("file", "")
    framework = args.get("framework", "pytest")
    try:
        target = Path(file_path)
        if not target.exists():
            return {"success": False, "error": f"文件不存在: {file_path}"}

        code = target.read_text(encoding="utf-8")
        import ast

        tree = ast.parse(code)
        func_types = (ast.FunctionDef, ast.AsyncFunctionDef)
        functions = [n for n in ast.walk(tree) if isinstance(n, func_types)]
        classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]

        # 检测是否是 FastAPI 路由文件
        is_router = any(
            isinstance(n, ast.Call) and hasattr(n.func, "attr") and n.func.attr == "APIRouter"
            for n in ast.walk(tree)
        )
        is_fastapi = is_router or any(
            isinstance(n, ast.Call) and hasattr(n.func, "attr") and n.func.attr == "FastAPI"
            for n in ast.walk(tree)
        )

        test_lines = [
            f'"""自动生成的 {framework} 测试 — {target.name}',
            "",
            "注意: 此测试骨架由静态分析生成，部分断言需要补充实际预期值。",
            '标记为 "TODO" 的行需要你手动填充具体断言逻辑。',
            '"""',
            "import pytest",
        ]

        if is_fastapi:
            test_lines.append("from httpx import AsyncClient, ASGITransport")
        test_lines.append(f"from {target.stem} import *")
        test_lines.append(f"from {target.stem} import (")
        # 导入所有函数/类
        imports = [f.name for f in functions[:20]] + [c.name for c in classes[:10]]
        for name in imports:
            test_lines.append(f"    {name},")
        test_lines.append(")")
        test_lines.append("")

        # 为每个类生成测试
        for cls in classes:
            test_lines.append("")
            test_lines.append(f"class Test{cls.name}:")
            ft = (ast.FunctionDef, ast.AsyncFunctionDef)
            methods = [n for n in cls.body if isinstance(n, ft)]
            for m in methods:
                params = [a.arg for a in m.args.args if a.arg != "self"]
                uses_async = isinstance(m, ast.AsyncFunctionDef)
                prefix = "async " if uses_async else ""

                test_lines.append("")
                test_lines.append(f"    {prefix}def test_{m.name}(self):")
                if uses_async:
                    test_lines.append("        # 测试异步方法")
                docstring = ast.get_docstring(m)
                if docstring:
                    test_lines.append(f"        # {docstring[:60]}")
                test_lines.append("        # TODO: 准备测试数据")
                for p in params:
                    test_lines.append(f"        {p} = None  # TODO: 设置参数")
                test_lines.append("        # TODO: 调用方法并验证结果")

                # 如果有返回注解，生成合理的断言
                if m.returns and isinstance(m.returns, ast.Name):
                    ret_type = m.returns.id
                    test_lines.append(
                        f"        result = self._create_instance().{m.name}({', '.join(params)})"
                    )
                    if ret_type in ("str", "int", "float", "bool", "list", "dict", "set"):
                        test_lines.append(
                            f"        assert isinstance(result, {ret_type}), "
                            f'"预期返回类型 {ret_type}"'
                        )
                        test_lines.append("        # TODO: 补充具体断言")
                    else:
                        test_lines.append("        assert result is not None")
                    test_lines.append("")
                else:
                    test_lines.append(
                        f"        assert True  # TODO: 实现 {cls.name}.{m.name} 的测试"
                    )
                    test_lines.append("")

            # 辅助方法
            test_lines.append("    def _create_instance(self):")
            test_lines.append(f"        # TODO: 创建 {cls.name} 实例")
            test_lines.append(f"        return {cls.name}()")
            test_lines.append("")

        # 为独立函数生成测试
        for fn in functions:
            if any(
                hasattr(b, "name") and b.name == fn.name
                for cls in classes
                for b in cls.body
                if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))
            ):
                continue
            test_lines.append("")
            params = [a.arg for a in fn.args.args]
            uses_async = isinstance(fn, ast.AsyncFunctionDef)
            prefix = "async " if uses_async else ""

            test_lines.append(f"    {prefix}def test_{fn.name}():")
            docstring = ast.get_docstring(fn)
            if docstring:
                test_lines.append(f"    # {docstring[:60]}")
            if params:
                test_lines.append("    # 测试参数")
                for p in params:
                    default_val = "None"
                    # 尝试从类型注解推断默认值
                    if p in fn.args.annotations and isinstance(fn.args.annotations, dict):
                        ann = fn.args.annotations.get(p)
                        if isinstance(ann, ast.Name):
                            type_hints = {
                                "str": '"test"',
                                "int": "0",
                                "float": "0.0",
                                "bool": "True",
                                "list": "[]",
                                "dict": "{}",
                            }
                            default_val = type_hints.get(ann.id, "None")
                    test_lines.append(f"    {p} = {default_val}  # TODO: 设置参数")
                test_lines.append(f"    result = {fn.name}({', '.join(params)})")
            else:
                test_lines.append(f"    result = {fn.name}()")

            # 根据返回类型生成断言
            if fn.returns and isinstance(fn.returns, ast.Name):
                ret_type = fn.returns.id
                test_lines.append(
                    f"    assert isinstance(result, {ret_type}), " f'"预期返回类型 {ret_type}"'
                )
                test_lines.append("    # TODO: 补充具体断言逻辑")
            else:
                test_lines.append("    # TODO: 补充断言逻辑")
                test_lines.append("    assert True")
            test_lines.append("")

        # 如果检测到 FastAPI，生成 API 测试
        if is_fastapi:
            test_lines.extend(_gen_fastapi_tests(tree, target))

        test_content = "\n".join(test_lines)
        test_file = target.parent / f"test_{target.name}"
        test_file.write_text(test_content, encoding="utf-8")

        test_count = len(functions) + sum(
            len([mb for mb in c.body if isinstance(mb, func_types)]) for c in classes
        )
        return {
            "success": True,
            "test_file": str(test_file),
            "test_count": test_count,
            "test_content": test_content,
            "assertion_coverage": f"生成了 {test_count} 个测试用例的基本断言骨架",
            "note": "部分 TODO 断言需要你补充实际预期值",
        }
    except SyntaxError as e:
        return {"success": False, "error": f"文件语法错误: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _gen_fastapi_tests(tree: ast.AST, target: Path) -> list[str]:
    """为 FastAPI 路由生成 HTTP 测试"""
    lines = []
    routes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and hasattr(node.func, "attr"):
            method = node.func.attr
            if method in ("get", "post", "put", "delete", "patch"):
                if node.args:
                    path = (
                        ast.literal_eval(node.args[0])
                        if isinstance(node.args[0], ast.Constant)
                        else ""
                    )
                    routes.append((method, path))

    if routes:
        lines.append("")
        lines.append("# ── FastAPI 路由测试 ──")
        lines.append("")
        for method, path in routes[:10]:
            test_fn_name = f"test_{method}_{path.strip('/').replace('/', '_') or 'root'}"
            lines.append("")
            lines.append(f"async def {test_fn_name}():")
            lines.append("    # 启动测试客户端")
            lines.append(f"    transport = ASGITransport(app={target.stem}.app)")
            lines.append(
                "    async with AsyncClient(transport=transport, base_url='http://test') as client:"
            )
            if method == "get":
                lines.append(f'        response = await client.get("{path}")')
            elif method == "post":
                lines.append(
                    f'        response = await client.post("{path}", json={{"key": "value"}})'
                )
                lines.append("        # TODO: 填充实际请求体")
            elif method == "put":
                lines.append(
                    f'        response = await client.put("{path}", json={{"key": "value"}})'
                )
                lines.append("        # TODO: 填充实际请求体")
            elif method == "delete":
                lines.append(f'        response = await client.delete("{path}")')
            elif method == "patch":
                lines.append(
                    f'        response = await client.patch("{path}", json={{"key": "value"}})'
                )
                lines.append("        # TODO: 填充实际请求体")
            lines.append("    assert response.status_code in (200, 201, 204)")
            lines.append("    # TODO: 验证响应体")
            if method != "delete":
                lines.append('    # assert "key" in response.json()')
            lines.append("")
    return lines


_register(
    name="generate_tests",
    description="为指定 Python 文件自动生成 pytest 测试骨架",
    input_schema={
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "Python 文件路径"},
            "framework": {
                "type": "string",
                "description": "测试框架",
                "enum": ["pytest", "unittest"],
                "default": "pytest",
            },
        },
        "required": ["file"],
    },
    handler=_handle_generate_tests,
)


# ── 工具: CI/CD 管道生成 ────────────────────────────


async def _handle_generate_pipeline(args: dict) -> dict:
    """生成 CI/CD 管道配置文件"""
    project_type = args.get("project_type", "python-app")
    platform = args.get("platform", "github-actions")

    templates = {
        "github-actions": {
            "python-app": {
                "path": ".github/workflows/ci.yml",
                "content": """name: PyCoder CI
on:
  push: { branches: [main] }
  pull_request: { branches: [main] }

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "${{ matrix.python-version }}" }
      - run: pip install -e ".[dev]"
      - run: pytest --cov --cov-report=xml
      - uses: codecov/codecov-action@v4
""",
            },
            "fastapi": {
                "path": ".github/workflows/deploy.yml",
                "content": """name: Deploy FastAPI
on:
  push: { branches: [main] }

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install -r requirements.txt
      - run: pytest -v
      - name: Build & Push Docker
        run: |
          docker build -t app .
          echo "部署脚本待补充"
""",
            },
        },
    }

    tmpl = templates.get(platform, {}).get(project_type)
    if not tmpl:
        return {"success": False, "error": f"不支持的组合: {platform}/{project_type}"}

    try:
        target = Path(os.getcwd()) / tmpl["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(tmpl["content"], encoding="utf-8")
        return {"success": True, "file": tmpl["path"], "content": tmpl["content"]}
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="generate_pipeline",
    description="生成 CI/CD 管道配置文件（GitHub Actions 等）",
    input_schema={
        "type": "object",
        "properties": {
            "project_type": {
                "type": "string",
                "description": "项目类型",
                "enum": ["python-app", "fastapi", "flask", "cli"],
                "default": "python-app",
            },
            "platform": {
                "type": "string",
                "description": "CI 平台",
                "enum": ["github-actions", "gitlab-ci"],
                "default": "github-actions",
            },
        },
    },
    handler=_handle_generate_pipeline,
)


# ── 工具: Docker 后端状态 ──────────────────────────


async def _handle_docker_status(args: dict) -> dict:
    """检查 Docker 执行后端状态"""
    from pycoder.server.docker_backend import get_docker_backend

    backend = get_docker_backend()
    return await backend.get_status()


_register(
    name="docker_status",
    description="检查 Docker 执行后端的可用性和状态",
    input_schema={
        "type": "object",
        "properties": {},
    },
    handler=_handle_docker_status,
)


async def _handle_docker_execute(args: dict) -> dict:
    """在 Docker 容器中执行 Python 代码"""
    code = args.get("code", "")
    timeout = args.get("timeout", 30)
    from pycoder.server.docker_backend import get_docker_backend

    backend = get_docker_backend()
    if not backend.is_available:
        return {"success": False, "error": "Docker 不可用，请先安装 Docker"}
    try:
        result = await backend.execute(code, timeout=timeout)
        return {
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "duration_ms": result.duration_ms,
            "container_id": result.container_id[:12] if result.container_id else "",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="docker_execute",
    description="在隔离的 Docker 容器中安全执行 Python 代码",
    input_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "要执行的 Python 代码"},
            "timeout": {"type": "number", "description": "超时秒数", "default": 30},
        },
        "required": ["code"],
    },
    handler=_handle_docker_execute,
)


# ── 工具: 性能分析 ─────────────────────────────────


async def _handle_profile_python(args: dict) -> dict:
    """用 cProfile 分析 Python 代码性能"""
    code = args.get("code", "")
    timeout = args.get("timeout", 30)
    sort_by = args.get("sort_by", "cumtime")

    import subprocess as _sp
    import sys as _sys
    import tempfile

    profile_script = f"""import cProfile, pstats, io
pr = cProfile.Profile()
pr.enable()
try:
{chr(10).join('    ' + line for line in code.split(chr(10)))}
except Exception as e:
    print(f"ERROR: {{e}}")
pr.disable()
s = io.StringIO()
ps = pstats.Stats(pr, stream=s).sort_stats("{sort_by}")
ps.print_stats(20)
print(s.getvalue())
print("---CALLERS---")
ps.print_callers(10)
print(s.getvalue().split("---CALLERS---")[1] if "---CALLERS---" in s.getvalue() else "")
"""
    tf = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8")
    with tf as f:
        f.write(profile_script)
        tmp_path = f.name
    try:
        r = _sp.run([_sys.executable, tmp_path], capture_output=True, text=True, timeout=timeout)
        Path(tmp_path).unlink(missing_ok=True)
        if r.returncode != 0:
            return {"success": False, "error": r.stderr[:1000]}
        return {"success": True, "profile": r.stdout[:3000], "sort_by": sort_by}
    except _sp.TimeoutExpired:
        Path(tmp_path).unlink(missing_ok=True)
        return {"success": False, "error": f"分析超时 ({timeout}s)"}
    except Exception as e:
        Path(tmp_path).unlink(missing_ok=True)
        return {"success": False, "error": str(e)}


_register(
    name="profile_python",
    description="用 cProfile 分析 Python 代码性能，返回热点函数和调用链",
    input_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "要分析的 Python 代码"},
            "sort_by": {
                "type": "string",
                "description": "排序方式",
                "enum": ["cumtime", "tottime", "ncalls"],
                "default": "cumtime",
            },
            "timeout": {"type": "number", "description": "超时秒数", "default": 30},
        },
        "required": ["code"],
    },
    handler=_handle_profile_python,
)


# ── 工具: 多语言代码执行 ────────────────────────────


async def _handle_execute_code(args: dict) -> dict:
    """安全执行多语言代码（自动检测语言）"""
    code = args.get("code", "")
    language = args.get("language", "")
    timeout = args.get("timeout", 30)

    if not language:
        # 自动检测
        lines = code.strip().split("\n")
        shebang = lines[0] if lines else ""
        if shebang.startswith("#!/"):
            lang_map = {"python": "python", "node": "javascript", "bash": "shell", "sh": "shell"}
            for key, val in lang_map.items():
                if key in shebang:
                    language = val
                    break
        if not language:
            language = "python"

    import subprocess as _sp
    import tempfile

    if language in ("python",):
        try:
            r = _sp.run(["python", "-c", code], capture_output=True, text=True, timeout=timeout)

            def _mkres(success, output="", error=""):
                return {
                    "success": success,
                    "output": output[:2000],
                    "error": error[:1000],
                    "language": language,
                }

            return _mkres(r.returncode == 0, r.stdout, r.stderr)
        except _sp.TimeoutExpired:

            return _mkres(False, error=f"超时 ({timeout}s)")
        except FileNotFoundError:
            return _mkres(False, error=f"运行时未找到: {language}")

    if language == "javascript":
        try:
            r = _sp.run(["node", "-e", code], capture_output=True, text=True, timeout=timeout)
            return _mkres(r.returncode == 0, r.stdout, r.stderr)
        except _sp.TimeoutExpired:
            return {"success": False, "error": f"超时 ({timeout}s)", "language": language}
        except FileNotFoundError:
            return {"success": False, "error": "Node.js 未安装", "language": language}

    if language == "shell":
        tf = tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False, encoding="utf-8")
        with tf as f:
            f.write(code)
            tmp_path = f.name
        try:
            r = _sp.run(["bash", tmp_path], capture_output=True, text=True, timeout=timeout)
            return _mkres(r.returncode == 0, r.stdout, r.stderr)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    return {"success": False, "error": f"不支持的语言: {language}", "language": language}


_register(
    name="execute_code",
    description="安全执行多语言代码（Python/JavaScript/Shell，自动检测语言）",
    input_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "要执行的代码"},
            "language": {
                "type": "string",
                "description": "语言",
                "enum": ["python", "javascript", "shell"],
                "default": "",
            },
            "timeout": {"type": "number", "description": "超时秒数", "default": 30},
        },
        "required": ["code"],
    },
    handler=_handle_execute_code,
)


# ── 工具: Git 冲突智能解决 ───────────────────────────


async def _handle_resolve_conflict(args: dict) -> dict:
    """分析 Git 合并冲突文件并生成智能解决建议"""
    file_path = args.get("file", "")
    try:
        target = Path(file_path)
        if not target.exists():
            return {"success": False, "error": f"文件不存在: {file_path}"}

        content = target.read_text(encoding="utf-8")
        # 检测冲突标记
        import re

        conflict_count = len(re.findall(r"^<<<<<<< ", content, re.MULTILINE))
        if conflict_count == 0:
            return {
                "success": True,
                "conflict_count": 0,
                "message": "未发现冲突标记",
                "resolved": content,
            }

        # 提取每个冲突
        conflicts = []
        resolved = content
        pattern = re.compile(
            r"<<<<<<< [^\n]*\n(.*?)\n=======\n(.*?)>>>>>>> [^\n]*",
            re.DOTALL,
        )
        for i, m in enumerate(pattern.finditer(content)):
            ours = m.group(1).strip()
            theirs = m.group(2).strip()
            # 简单的智能合并：如果 ours 和 theirs 相同，直接取
            if ours == theirs:
                resolution = ours
                strategy = "identical"
            # 如果 ours 是 theirs 的扩展
            elif ours.startswith(theirs) or theirs.startswith(ours):
                resolution = ours if len(ours) > len(theirs) else theirs
                strategy = "superset"
            else:
                resolution = ours + "\n# TODO: 审查合并\n" + theirs
                strategy = "needs_review"

            conflicts.append(
                {
                    "index": i + 1,
                    "ours_length": len(ours),
                    "theirs_length": len(theirs),
                    "strategy": strategy,
                    "suggestion": resolution[:200],
                }
            )

        # 自动应用 identical/superset 策略
        def auto_resolve(m):
            ours = m.group(1).strip()
            theirs = m.group(2).strip()
            if ours == theirs:
                return ours
            if ours.startswith(theirs) or theirs.startswith(ours):
                return ours if len(ours) > len(theirs) else theirs
            return m.group(0)  # 保留，人工处理

        resolved = pattern.sub(auto_resolve, content)

        return {
            "success": True,
            "conflict_count": conflict_count,
            "conflicts": conflicts,
            "auto_resolved": content != resolved,
            "resolved": resolved,
            "needs_review": [c for c in conflicts if c["strategy"] == "needs_review"],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="resolve_conflict",
    description="分析 Git 合并冲突文件，自动解决简单冲突并生成复杂冲突的解决建议",
    input_schema={
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "含冲突标记的文件路径"},
        },
        "required": ["file"],
    },
    handler=_handle_resolve_conflict,
)


# ══════════════════════════════════════════════════════════
# B — 测试增强
# ══════════════════════════════════════════════════════════


async def _handle_test_integration(args: dict) -> dict:
    """根据 FastAPI 路由自动生成集成测试"""
    app_file = args.get("app_file", "")
    output_dir = args.get("output_dir", "tests")
    try:
        target = Path(app_file)
        if not target.exists():
            return {"success": False, "error": f"文件不存在: {app_file}"}

        code = target.read_text(encoding="utf-8")
        import ast

        tree = ast.parse(code)
        test_lines = [
            '"""自动生成的集成测试"""',
            "import pytest",
            "from httpx import AsyncClient, ASGITransport",
            f"from {target.stem} import app",
            "",
            "",
            "@pytest.fixture",
            "async def client():",
            "    transport = ASGITransport(app=app)",
            "    async with AsyncClient(transport=transport, base_url='http://test') as ac:",
            "        yield ac",
            "",
        ]

        # 检测路由装饰器
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call) and hasattr(decorator.func, "attr"):
                        route = decorator.func.attr.lower()
                        method = "GET"
                        if route in ("get", "post", "put", "delete", "patch"):
                            method = route.upper()
                            # 提取路径
                            path = ""
                            for arg in decorator.args:
                                if isinstance(arg, ast.Constant):
                                    path = arg.value
                                    break
                            if not path:
                                continue

                            test_fn_name = f"test_{method.lower()}_{path.strip('/').replace('/', '_').replace('-', '_') or 'root'}"
                            test_lines.append("")
                            test_lines.append(f"async def {test_fn_name}(client):")
                            test_lines.append(f'    """集成测试: {method} {path}"""')
                            if method == "GET":
                                test_lines.append(f'    response = await client.get("{path}")')
                            elif method == "POST":
                                test_lines.append(
                                    f'    response = await client.post("{path}", json={{"key": "value"}})  # TODO: 填充实际参数'
                                )
                            elif method == "PUT":
                                test_lines.append(
                                    f'    response = await client.put("{path}", json={{"key": "value"}})  # TODO'
                                )
                            elif method == "DELETE":
                                test_lines.append(f'    response = await client.delete("{path}")')
                            elif method == "PATCH":
                                test_lines.append(
                                    f'    response = await client.patch("{path}", json={{"key": "value"}})  # TODO'
                                )
                            test_lines.append(
                                '    assert response.status_code in (200, 201, 204), f"预期成功, 实际 {response.status_code}: {response.text}"'
                            )
                            test_lines.append("")

        test_content = "\n".join(test_lines)
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        test_file = out / f"test_{target.stem}_api.py"
        test_file.write_text(test_content, encoding="utf-8")

        route_count = test_content.count("async def test_")
        return {
            "success": True,
            "test_file": str(test_file),
            "route_count": route_count,
            "test_content": test_content,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="test_integration",
    description="自动扫描 FastAPI 路由，生成 httpx 集成测试脚本",
    input_schema={
        "type": "object",
        "properties": {
            "app_file": {"type": "string", "description": "FastAPI app 文件路径"},
            "output_dir": {"type": "string", "description": "输出目录", "default": "tests"},
        },
        "required": ["app_file"],
    },
    handler=_handle_test_integration,
)


async def _handle_test_e2e(args: dict) -> dict:
    """生成 Playwright 端到端测试"""
    app_url = args.get("app_url", "http://localhost:8423")
    pages = args.get("pages", ["/"])

    test_lines = [
        '"""自动生成的 Playwright 端到端测试"""',
        "import re",
        "from playwright.sync_api import Page, expect",
        "",
        "",
        "def test_page_loads(page: Page):",
        f'    page.goto("{app_url}")',
        '    expect(page).to_have_title(re.compile(r".*"))',
        '    print(f"[OK] 页面加载成功: {page.url}")',
        "",
    ]

    for p in pages:
        name = p.strip("/").replace("/", "_") or "root"
        test_lines.append("")
        test_lines.append(f"def test_page_{name}(page: Page):")
        test_lines.append(f'    page.goto("{app_url}{p}")')
        test_lines.append("    page.wait_for_load_state('networkidle')")
        test_lines.append(f'    print(f"[OK] {p} 页面加载完成")')
        test_lines.append("")

    test_content = "\n".join(test_lines)
    return {
        "success": True,
        "test_content": test_content,
        "page_count": len(pages),
        "instructions": "安装: pip install pytest-playwright; playwright install chromium",
    }


_register(
    name="test_e2e",
    description="生成 Playwright 端到端浏览器测试脚本",
    input_schema={
        "type": "object",
        "properties": {
            "app_url": {
                "type": "string",
                "description": "应用 URL",
                "default": "http://localhost:8423",
            },
            "pages": {
                "type": "array",
                "items": {"type": "string"},
                "description": "要测试的页面路径列表",
                "default": ["/"],
            },
        },
    },
    handler=_handle_test_e2e,
)


async def _handle_test_performance(args: dict) -> dict:
    """生成 Locust 性能测试脚本"""
    target_url = args.get("target_url", "http://localhost:8423")
    users = args.get("users", 100)
    spawn_rate = args.get("spawn_rate", 10)

    test_lines = [
        '"""自动生成的 Locust 性能测试"""',
        "from locust import HttpUser, task, between",
        "",
        "",
        "class WebsiteUser(HttpUser):",
        "    wait_time = between(1, 5)",
        f'    host = "{target_url}"',
        "",
        "    @task(3)",
        "    def index(self):",
        '        self.client.get("/")',
        "",
        "    @task(2)",
        "    def health_check(self):",
        '        self.client.get("/api/health")',
        "",
        "    @task(1)",
        "    def heavy_query(self):",
        "        # 模拟慢查询",
        '        self.client.get("/api/search?q=test")',
        "",
        "",
        'if __name__ == "__main__":',
        "    import subprocess, sys",
        f'    cmd = [sys.executable, "-m", "locust", "-f", __file__, "--headless",'
        f'           "-u", "{users}", "-r", "{spawn_rate}", "--run-time", "1m"]',
        "    subprocess.run(cmd)",
        "",
    ]

    test_content = "\n".join(test_lines)
    run_cmd = f"locust -f locustfile.py --headless -u {users} -r {spawn_rate}"
    return {
        "success": True,
        "test_content": test_content,
        "instructions": f"安装: pip install locust\n运行: {run_cmd}",
    }


_register(
    name="test_performance",
    description="生成 Locust 性能/压力测试脚本，可配置并发数和 spawn 速率",
    input_schema={
        "type": "object",
        "properties": {
            "target_url": {
                "type": "string",
                "description": "目标 URL",
                "default": "http://localhost:8423",
            },
            "users": {"type": "number", "description": "模拟用户数", "default": 100},
            "spawn_rate": {"type": "number", "description": "用户生成速率/秒", "default": 10},
        },
    },
    handler=_handle_test_performance,
)


# ══════════════════════════════════════════════════════════
# E — 产品化补全（环境管理 / 快捷搜索 / Git 历史 / 代码片段）
# ══════════════════════════════════════════════════════════


async def _handle_python_env(args: dict) -> dict:
    """扫描和管理 Python 虚拟环境"""
    import subprocess as _sp
    import sys as _sys

    envs = []

    # 检测当前 venv
    venv = os.environ.get("VIRTUAL_ENV", "")
    if venv:
        envs.append({"name": "current", "path": venv, "type": "venv", "active": True})

    # 检测 .venv / venv 目录
    cwd = Path(os.getcwd())
    for name in (".venv", "venv", "env"):
        p = cwd / name
        if p.exists() and (p / "Scripts" / "python.exe").exists():
            envs.append({"name": name, "path": str(p), "type": "venv", "active": venv == str(p)})

    # 检测 conda
    conda = os.environ.get("CONDA_PREFIX", "")
    if conda:
        envs.append(
            {
                "name": os.environ.get("CONDA_DEFAULT_ENV", "conda"),
                "path": conda,
                "type": "conda",
                "active": True,
            }
        )

    # Python 版本
    python_path = _sys.executable
    try:
        v = _sp.run([python_path, "--version"], capture_output=True, text=True, timeout=5)
        version = v.stdout.strip() or v.stderr.strip()
    except (_sp.SubprocessError, OSError) as e:
        log.debug("detect_python_version_failed", error=str(e))
        version = f"{_sys.version_info.major}.{_sys.version_info.minor}"

    return {
        "success": True,
        "environments": envs,
        "python_path": python_path,
        "python_version": version,
        "packages_count": len(list(Path(python_path).parent.glob("*/__init__.py"))),
    }


_register(
    name="python_env",
    description="扫描并列出所有可用的 Python 虚拟环境（venv/conda）和版本信息",
    input_schema={"type": "object", "properties": {}},
    handler=_handle_python_env,
)


async def _handle_quick_open(args: dict) -> dict:
    """快捷文件搜索（类似 Ctrl+P）"""
    query = args.get("query", "").lower()
    max_results = args.get("max_results", 15)
    cwd = Path(os.getcwd())
    results = []
    for f in list(cwd.rglob("*"))[:500]:
        if "__pycache__" in str(f) or "node_modules" in str(f) or ".git" in str(f):
            continue
        if f.is_file() and f.suffix in (
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".md",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
        ):
            rel = str(f.relative_to(cwd))
            if not query or query in rel.lower():
                results.append(
                    {
                        "path": rel,
                        "name": f.name,
                        "size": f.stat().st_size,
                        "modified_at": f.stat().st_mtime,
                    }
                )
                if len(results) >= max_results:
                    break
    return {
        "success": True,
        "results": results,
        "total": len(results),
        "query": args.get("query", ""),
    }


_register(
    name="quick_open",
    description="快捷文件搜索（类似 VS Code Ctrl+P），按文件名模糊匹配",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "文件名模糊搜索", "default": ""},
            "max_results": {"type": "number", "description": "最大结果数", "default": 15},
        },
    },
    handler=_handle_quick_open,
)


async def _handle_git_log(args: dict) -> dict:
    """Git 提交历史"""
    limit = args.get("limit", 20)
    cwd = Path(os.getcwd())
    try:
        import subprocess as _sp

        r = _sp.run(
            ["git", "log", f"-{limit}", "--oneline", "--decorate", "--graph", "--all"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(cwd),
        )
        lines = [line.strip() for line in r.stdout.split("\n") if line.strip()]
        return {"success": True, "commits": lines, "count": len(lines)}
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="git_log",
    description="查看 Git 提交历史和分支图（类似 git log --graph）",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "number", "description": "显示最近 N 条", "default": 20},
        },
    },
    handler=_handle_git_log,
)


async def _handle_git_diff_branch(args: dict) -> dict:
    """对比两个分支的差异"""
    branch1 = args.get("branch1", "")
    branch2 = args.get("branch2", "HEAD")
    cwd = Path(os.getcwd())
    try:
        import subprocess as _sp

        # 文件列表
        r = _sp.run(
            ["git", "diff", "--name-only", f"{branch1}..{branch2}"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(cwd),
        )
        files = [line.strip() for line in r.stdout.split("\n") if line.strip()]
        # 改动统计
        r2 = _sp.run(
            ["git", "diff", "--stat", f"{branch1}..{branch2}"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(cwd),
        )
        return {
            "success": True,
            "branch1": branch1,
            "branch2": branch2,
            "changed_files": len(files),
            "files": files[:30],
            "stat": r2.stdout.strip(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="git_diff_branch",
    description="对比两个 Git 分支的差异（文件列表 + 改动统计）",
    input_schema={
        "type": "object",
        "properties": {
            "branch1": {"type": "string", "description": "源分支名"},
            "branch2": {"type": "string", "description": "目标分支名", "default": "HEAD"},
        },
        "required": ["branch1"],
    },
    handler=_handle_git_diff_branch,
)


async def _handle_snippets(args: dict) -> dict:
    """列出或获取代码片段"""
    subcmd = args.get("subcommand", "list")
    language = args.get("language", "python")
    prefix = args.get("prefix", "")

    from pycoder.prompts.snippets_loader import get_snippet, list_snippets

    if subcmd == "get" and prefix:
        s = get_snippet(language, prefix)
        if s:
            return {"success": True, "snippet": s}
        return {"success": False, "error": f"Snippet '{prefix}' not found"}

    snippets = list_snippets(language)
    return {"success": True, "snippets": snippets, "language": language, "total": len(snippets)}


_register(
    name="snippets",
    description="查看或插入代码片段（Python 模板/快捷词）",
    input_schema={
        "type": "object",
        "properties": {
            "subcommand": {"type": "string", "description": "list 或 get", "default": "list"},
            "language": {"type": "string", "description": "语言", "default": "python"},
            "prefix": {
                "type": "string",
                "description": "片段快捷词（get 子命令时需要）",
                "default": "",
            },
        },
    },
    handler=_handle_snippets,
)


# ── 工具: 写入文件（AI 完整写权限）───────────────────────


async def _handle_write_file(args: dict) -> dict:
    """向工作区写入文件（覆盖或新建），支持自动创建目录"""
    from pycoder.server.routers.files import get_workspace_root

    work_dir = get_workspace_root()
    file_path = args.get("path", "")
    content = args.get("content", "")
    if not file_path:
        return {"success": False, "error": "path 不能为空"}
    if not content:
        return {"success": False, "error": "content 不能为空"}

    try:
        target = (work_dir / file_path).resolve()
        # 路径穿越保护
        if not target.is_relative_to(work_dir):
            return {"success": False, "error": "路径穿越拒绝"}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {
            "success": True,
            "path": file_path,
            "size": len(content.encode("utf-8")),
            "message": f"文件已写入: {file_path} ({len(content.encode('utf-8'))} 字节)",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="write_file",
    description="向当前工作区写入文件（覆盖或新建），自动创建父目录。可用此工具创建源代码、配置文件、文档等任意文件。path 是相对于工作区的路径，如 src/main.py",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件路径（相对于工作区根目录），如 src/main.py",
            },
            "content": {"type": "string", "description": "文件内容"},
        },
        "required": ["path", "content"],
    },
    handler=_handle_write_file,
)


# ── 工具: 创建目录 ──────────────────────────────────────


async def _handle_create_directory(args: dict) -> dict:
    """在工作区创建目录"""
    from pycoder.server.routers.files import get_workspace_root

    work_dir = get_workspace_root()
    dir_path = args.get("path", "")
    if not dir_path:
        return {"success": False, "error": "path 不能为空"}

    try:
        target = (work_dir / dir_path).resolve()
        if not target.is_relative_to(work_dir):
            return {"success": False, "error": "路径穿越拒绝"}
        target.mkdir(parents=True, exist_ok=True)
        return {"success": True, "path": dir_path, "message": f"目录已创建: {dir_path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="create_directory",
    description="在当前工作区创建目录（可递归创建多层目录），如 src/components",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "目录路径（相对于工作区根目录），如 src/components",
            },
        },
        "required": ["path"],
    },
    handler=_handle_create_directory,
)


# ── 工具: 读取文件 ───────────────────────────────────────


async def _handle_read_file(args: dict) -> dict:
    """从工作区读取文件内容"""
    from pycoder.server.routers.files import get_workspace_root

    work_dir = get_workspace_root()
    file_path = args.get("path", "")
    if not file_path:
        return {"success": False, "error": "path 不能为空"}

    try:
        target = (work_dir / file_path).resolve()
        if not target.is_relative_to(work_dir):
            return {"success": False, "error": "路径穿越拒绝"}
        if not target.exists():
            return {"success": False, "error": f"文件不存在: {file_path}"}
        if target.is_dir():
            return {"success": False, "error": f"是目录不是文件: {file_path}"}
        content = target.read_text(encoding="utf-8")
        return {
            "success": True,
            "path": file_path,
            "content": content,
            "size": len(content.encode("utf-8")),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="read_file",
    description="从当前工作区读取文件内容。可用于读取源代码、配置文件等。path 是相对于工作区的路径",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对于工作区根目录）"},
        },
        "required": ["path"],
    },
    handler=_handle_read_file,
)


# ── 工具: 文件列表 ──────────────────────────────────────


async def _handle_list_files(args: dict) -> dict:
    """列出工作区目录内容"""
    from pycoder.server.routers.files import get_workspace_root

    work_dir = get_workspace_root()
    dir_path = args.get("path", ".")
    try:
        target = (work_dir / dir_path).resolve()
        if not target.is_relative_to(work_dir):
            return {"success": False, "error": "路径穿越拒绝"}
        if not target.exists():
            return {"success": False, "error": f"路径不存在: {dir_path}"}
        if not target.is_dir():
            return {"success": False, "error": f"不是目录: {dir_path}"}

        items = []
        for entry in sorted(target.iterdir()):
            items.append(
                {
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": entry.stat().st_size if entry.is_file() else 0,
                }
            )
        return {"success": True, "path": dir_path, "items": items, "count": len(items)}
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="list_files",
    description="列出工作区指定目录下的文件和子目录。path 相对于工作区根目录，默认为根目录",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "目录路径（相对于工作区根目录）",
                "default": ".",
            },
        },
    },
    handler=_handle_list_files,
)


# ── 工具: 终端命令执行 ──────────────────────────────────


async def _handle_run_terminal(args: dict) -> dict:
    """在终端中执行命令，返回输出、退出码"""
    cmd = args.get("command", "")
    timeout = args.get("timeout", 30)
    cwd = args.get("cwd", None)
    if not cmd:
        return {"success": False, "error": "command 不能为空"}

    try:
        from pycoder.server.routers.files import get_workspace_root

        work_dir = cwd or str(get_workspace_root())
        import subprocess as _sp

        if sys.platform == "win32":
            proc = _sp.run(
                ["powershell.exe", "-Command", cmd],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=work_dir,
            )
        else:
            proc = _sp.run(
                ["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout, cwd=work_dir
            )

        output = proc.stdout[:8000]
        stderr = proc.stderr[:4000]
        return {
            "success": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": output,
            "stderr": stderr,
            "cwd": work_dir,
        }
    except _sp.TimeoutExpired:
        return {"success": False, "error": f"命令超时 ({timeout}s)", "exit_code": -1}
    except Exception as e:
        return {"success": False, "error": str(e), "exit_code": -1}


_register(
    name="run_terminal",
    description="在终端中执行 shell 命令并获取输出和退出码。支持 pip install, git push, npm install 等所有 shell 命令。命令在用户的工作区目录中执行",
    input_schema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的 shell 命令，如 pip install requests",
            },
            "timeout": {"type": "number", "description": "超时秒数", "default": 30},
            "cwd": {
                "type": "string",
                "description": "工作目录(可选，默认用户工作区)",
                "default": "",
            },
        },
        "required": ["command"],
    },
    handler=_handle_run_terminal,
)


# ── 工具: 删除文件 ──────────────────────────────────────


async def _handle_delete_file(args: dict) -> dict:
    """删除工作区中的文件或目录"""
    from pycoder.server.routers.files import get_workspace_root

    work_dir = get_workspace_root()
    file_path = args.get("path", "")
    if not file_path:
        return {"success": False, "error": "path 不能为空"}
    try:
        import shutil

        target = (work_dir / file_path).resolve()
        if not target.is_relative_to(work_dir):
            return {"success": False, "error": "路径穿越拒绝"}
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"success": True, "path": file_path, "message": f"已删除: {file_path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="delete_file",
    description="删除工作区中的文件或目录（递归删除）。path 相对于工作区根目录",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件或目录路径（相对于工作区）"},
        },
        "required": ["path"],
    },
    handler=_handle_delete_file,
)


# ── 工具: 列出系统 Agent 配置 ───────────────────────────


async def _handle_list_agent_configs(args: dict) -> dict:
    """列出系统 Agent 角色详细配置"""
    from pycoder.server.services.agent_definitions import AGENT_ROLES as roles
    from pycoder.server.services.agent_definitions import (
        CONCURRENCY_LIMITS,
        MODEL_TIERS,
    )

    if not roles:
        return {"success": True, "agents": [], "message": "未找到任何系统 Agent 配置"}
    agent_list = []
    for role_id, role in roles.items():
        agent_list.append(
            {
                "id": role_id,
                "name": role.name,
                "description": role.description,
                "model": role.model,
                "model_tier": role.model_tier,
                "tools": role.tools,
                "max_concurrent": role.max_concurrent,
                "max_retries": role.max_retries,
                "timeout": role.timeout,
                "parallel": role.parallel,
                "skills": role.skills,
                "forbid_actions": role.forbid_actions,
                "heartbeat_interval": role.heartbeat_interval,
            }
        )
    result = {
        "success": True,
        "count": len(agent_list),
        "agents": agent_list,
        "concurrency_limits": dict(CONCURRENCY_LIMITS),
        "model_tiers": {
            tier: {"label": info["label"], "purpose": info["purpose"], "models": info["models"]}
            for tier, info in MODEL_TIERS.items()
        },
    }
    return result


_register(
    name="list_agent_configs",
    description="列出 PyCoder 系统 Agent 角色的详细配置，包含所有角色的 ID、名称、描述、模型、可用工具列表、并发限制、禁止操作、绑定的Skills。返回结构化 JSON 数据",
    input_schema={"type": "object", "properties": {}},
    handler=_handle_list_agent_configs,
)


# ══════════════════════════════════════════════════════════
# MCP 本地回退策略
# ══════════════════════════════════════════════════════════

MCP_FALLBACK_ENABLED = True
MCP_REMOTE_TIMEOUT_SECONDS = 5


async def call_tool_with_fallback(name: str, args: dict) -> MCPCallResult:
    """
    智能 MCP 工具调用 — 优先远程，失败时自动降级为本地执行。

    策略:
      1. 先查内置 Tool，直接本地执行（零网络依赖）
      2. 远程 Tool 失败（网络波动/超时）→ 自动降级为本地替代 Tool
      3. 无替代 Tool → 返回错误 + 建议
    """
    # 内置工具直接本地执行
    if name in _builtin_tools:
        return await call_builtin_tool(name, args)

    # 外部 MCP Server 工具 — 尝试远程调用，失败则降级
    if name.startswith("mcp:"):
        from pycoder.server.mcp_tools import get_mcp_client_manager

        parts = name[4:].split("/", 1)
        if len(parts) == 2:
            server_name, remote_tool = parts
            mgr = get_mcp_client_manager()
            # 尝试远程
            try:
                async with asyncio.timeout(MCP_REMOTE_TIMEOUT_SECONDS):
                    result = await mgr.call_remote_tool(server_name, remote_tool, args)
                    if result.success:
                        return result
            except (TimeoutError, Exception):
                pass
            # 降级: 尝试本地替代
            fallback_map = {
                "mcp:filesystem/list_directory": "file_list",
                "mcp:filesystem/read_file": "file_read",
                "mcp:github/search_repositories": "search",
                "mcp:playwright/navigate": None,
            }
            local_tool = fallback_map.get(name)
            if local_tool and local_tool in _builtin_tools:
                log.info("mcp_fallback", remote=name, local=local_tool)
                return await call_builtin_tool(local_tool, args)
            return MCPCallResult(
                success=False,
                error=f"远程工具 {name} 不可用（网络波动或服务离线），且无本地替代。请稍后重试或检查 MCP Server 状态。",
                tool=name,
            )

    return MCPCallResult(success=False, error=f"未知 Tool: {name}", tool=name)


# ── 工具: Skills 市场 v2 ─────────────────────────────


async def _handle_skills_search_v2(args: dict) -> dict:
    """高级搜索：关键词 + 分类 + 标签 + 排序 + 分页"""
    from pycoder.server.skills_market_v2 import get_enhanced_market

    market = get_enhanced_market()
    query = args.get("query", "")
    category = args.get("category", "")
    tags = args.get("tags", [])
    sort_by = args.get("sort_by", "quality")
    limit = args.get("limit", 20)
    offset = args.get("offset", 0)

    try:
        results = market.search(
            query=query,
            category=category,
            tags=tags,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
        )
        return {
            "success": True,
            "query": query,
            "total": results.get("total", 0),
            "results": results.get("skills", []),
            "sort_by": sort_by,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="skills_search_v2",
    description="🔍 高级搜索: 关键词+分类+标签+排序 (支持quality/stars/downloads/rating/name)",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "category": {"type": "string", "description": "按分类筛选"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "按标签筛选"},
            "sort_by": {
                "type": "string",
                "enum": ["quality", "stars", "downloads", "rating", "name"],
                "default": "quality",
                "description": "排序方式",
            },
            "limit": {"type": "number", "default": 20, "description": "返回数量"},
            "offset": {"type": "number", "default": 0, "description": "分页偏移"},
        },
    },
    handler=_handle_skills_search_v2,
)


async def _handle_skills_recommendations_v2(args: dict) -> dict:
    """获取推荐列表"""
    from pycoder.server.skills_market_v2 import get_enhanced_market

    market = get_enhanced_market()
    category = args.get("category", "")
    limit = args.get("limit", 10)

    try:
        recommendations = market.get_recommendations(category=category or None, limit=limit)
        return {
            "success": True,
            "recommendations": recommendations,
            "count": len(recommendations),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="skills_recommendations_v2",
    description="⭐ 智能推荐: 基于质量评分的个性化推荐",
    input_schema={
        "type": "object",
        "properties": {
            "category": {"type": "string", "description": "限定分类"},
            "limit": {"type": "number", "default": 10, "description": "返回数量"},
        },
    },
    handler=_handle_skills_recommendations_v2,
)


async def _handle_skills_trending_v2(args: dict) -> dict:
    """获取热门排行"""
    from pycoder.server.skills_market_v2 import get_enhanced_market

    market = get_enhanced_market()
    limit = args.get("limit", 20)

    try:
        trending = market.get_trending(limit=limit)
        return {
            "success": True,
            "trending": trending,
            "count": len(trending),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="skills_trending_v2",
    description="🔥 热门排行: 实时热门技能榜单",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "number", "default": 20, "description": "返回数量"},
        },
    },
    handler=_handle_skills_trending_v2,
)


async def _handle_skills_stats_v2(args: dict) -> dict:
    """获取统计信息"""
    from pycoder.server.skills_market_v2 import get_enhanced_market

    market = get_enhanced_market()

    try:
        stats = market.get_stats()
        return {
            "success": True,
            "stats": stats,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="skills_stats_v2",
    description="📊 统计仪表板: 市场统计数据",
    input_schema={
        "type": "object",
        "properties": {},
    },
    handler=_handle_skills_stats_v2,
)


async def _handle_skills_sync_v2(args: dict) -> dict:
    """同步所有数据源"""
    from pycoder.server.skills_market_v2 import get_enhanced_market

    market = get_enhanced_market()

    try:
        result = await market.sync_from_all_sources()
        return {
            "success": True,
            "total_skills": result.get("total_skills", 0),
            "sources": result.get("sources", {}),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="skills_sync_v2",
    description="🔄 数据同步: 从所有源同步最新技能 (异步)",
    input_schema={
        "type": "object",
        "properties": {},
    },
    handler=_handle_skills_sync_v2,
)


# ── 工具: Skills 自动更新 ──────────────────────────


async def _handle_skills_update(args: dict) -> dict:
    """从 GitHub 多数据源实时拉取最新社区 skills"""
    from pycoder.server.skills_updater import get_skills_fetcher

    fetcher = get_skills_fetcher()
    result = await fetcher.fetch_all_sources()
    return {
        "success": result["success"],
        "total_skills": result["total_skills"],
        "sources": result["sources"],
        "message": f"Fetched {result['total_skills']} skills from {len(result['sources'])} sources",
    }


_register(
    name="skills_update",
    description="Auto-fetch latest community skills from GitHub (12h auto-sync)",
    input_schema={
        "type": "object",
        "properties": {},
    },
    handler=_handle_skills_update,
)


async def _handle_skills_market(args: dict) -> dict:
    subcmd = args.get("subcommand", "list")
    sort_by = args.get("sort_by", "stars")
    search = args.get("search", "")
    category = args.get("category", "")
    skill_id = args.get("skill_id", "")

    from pycoder.server.skills_market import get_skills_market

    market = get_skills_market()

    if subcmd == "sync":
        return await market.sync_from_remote()

    if subcmd == "install" and skill_id:
        return market.install_skill(skill_id)

    if subcmd == "uninstall" and skill_id:
        return market.uninstall_skill(skill_id)

    if subcmd == "update_all":
        return market.update_all_skills()

    if subcmd == "rate" and skill_id:
        rating = args.get("rating", 5)
        review = args.get("review", "")
        return market.rate_skill(skill_id, rating, review)

    if subcmd == "detail" and skill_id:
        return market.get_skill_detail(skill_id)

    if subcmd == "publish":
        skill_data = args.get("skill_data", {})
        return market.publish_skill(skill_data)

    if subcmd == "categories":
        return {"success": True, "categories": market.get_categories()}

    result = market.list_skills(
        sort_by=sort_by,
        category=category,
        search=search,
        limit=args.get("limit", 50),
        offset=args.get("offset", 0),
    )
    return {
        "success": True,
        **result,
        "sort_by": sort_by,
        "search": search or "(all)",
    }


_register(
    name="skills_market",
    description="Skills Market: browse/search/install/uninstall/rate/publish community skills",
    input_schema={
        "type": "object",
        "properties": {
            "subcommand": {
                "type": "string",
                "enum": [
                    "list",
                    "install",
                    "uninstall",
                    "update_all",
                    "sync",
                    "categories",
                    "rate",
                    "detail",
                    "publish",
                ],
                "description": "操作类型",
            },
            "sort_by": {
                "type": "string",
                "enum": ["stars", "downloads", "name"],
                "description": "Sort by stars/downloads/name",
            },
            "search": {"type": "string", "description": "Keyword search"},
            "category": {"type": "string", "description": "Category filter"},
            "skill_id": {"type": "string", "description": "Skill ID (for install)"},
        },
    },
    handler=_handle_skills_market,
)


# ── 工具: 系统升级 ─────────────────────────────────────


async def _handle_system_upgrade(args: dict) -> dict:
    """系统升级管理：检查更新、执行升级、健康检查、查看状态"""
    from pycoder.server.auto_upgrade import (
        check_version,
        get_snapshot_diff,
        get_upgrade_status,
        health_check,
        run_upgrade,
    )

    action = args.get("action", "check")

    if action == "check":
        info = check_version()
        return {
            "success": True,
            "current_version": info.current,
            "latest_version": info.latest,
            "has_update": info.has_update,
            "release_notes": info.release_notes,
        }

    if action == "upgrade":
        target = args.get("target_version", "")
        dry_run = args.get("dry_run", False)
        result = run_upgrade(to_version=target or None, dry_run=dry_run)
        return {
            "success": result.success,
            "from_version": result.from_version,
            "to_version": result.to_version,
            "steps": result.steps,
            "error": result.error,
            "duration_ms": result.duration_ms,
        }

    if action == "health":
        hc = health_check()
        return {
            "success": hc.passed,
            "checks": hc.checks,
            "warnings": hc.warnings,
            "errors": hc.errors,
        }

    if action == "status":
        return get_upgrade_status()

    if action == "diff":
        snapshot_id = args.get("snapshot_id", "")
        return get_snapshot_diff(snapshot_id)

    return {"success": False, "error": f"未知操作: {action}"}


_register(
    name="system_upgrade",
    description="🔄 系统升级: 检查更新、执行升级、健康检查、查看状态。支持断点续传",
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["check", "upgrade", "health", "status", "diff"],
                "description": "操作类型: check(检查更新) / upgrade(执行升级) / health(健康检查) / status(查看状态) / diff(快照对比)",
            },
            "target_version": {
                "type": "string",
                "description": "目标版本号（upgrade 操作可选，留空则升级到最新）",
            },
            "dry_run": {
                "type": "boolean",
                "description": "仅模拟升级，不实际执行（upgrade 操作可选）",
                "default": False,
            },
            "snapshot_id": {
                "type": "string",
                "description": "快照 ID（diff 操作需要）",
            },
        },
        "required": ["action"],
    },
    handler=_handle_system_upgrade,
)

# ── Skills Market V2 MCP 工具注册 ────────────────────────
# 将 skills_market_mcp_v2.py 的 8 个工具注册到系统
# 使调度器 cron 任务能通过 "mcp:skills_sync_v2" 自动调用


async def _handle_skills_search_v2_wrapper(args: dict) -> dict:
    from pycoder.server.skills_market_mcp_v2 import handle_skills_search_v2

    return await handle_skills_search_v2(args)


async def _handle_skills_recommendations_v2_wrapper(args: dict) -> dict:
    from pycoder.server.skills_market_mcp_v2 import handle_skills_recommendations_v2

    return await handle_skills_recommendations_v2(args)


async def _handle_skills_trending_v2_wrapper(args: dict) -> dict:
    from pycoder.server.skills_market_mcp_v2 import handle_skills_trending_v2

    return await handle_skills_trending_v2(args)


async def _handle_skills_detail_v2_wrapper(args: dict) -> dict:
    from pycoder.server.skills_market_mcp_v2 import handle_skills_detail_v2

    return await handle_skills_detail_v2(args)


async def _handle_skills_rate_v2_wrapper(args: dict) -> dict:
    from pycoder.server.skills_market_mcp_v2 import handle_skills_rate_v2

    return await handle_skills_rate_v2(args)


async def _handle_skills_stats_v2_wrapper(args: dict) -> dict:
    from pycoder.server.skills_market_mcp_v2 import handle_skills_stats_v2

    return await handle_skills_stats_v2(args)


async def _handle_skills_sync_v2_wrapper(args: dict) -> dict:
    from pycoder.server.skills_market_mcp_v2 import handle_skills_sync_v2

    return await handle_skills_sync_v2(args)


async def _handle_skills_categories_v2_wrapper(args: dict) -> dict:
    from pycoder.server.skills_market_mcp_v2 import handle_skills_categories_v2

    return await handle_skills_categories_v2(args)


_register(
    name="skills_search_v2",
    description="Skills 市场高级搜索：关键词 + 分类 + 标签 + 排序",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "category": {"type": "string", "description": "分类筛选"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "标签筛选"},
            "sort_by": {
                "type": "string",
                "description": "排序: quality/stars/downloads/rating/name",
                "default": "quality",
            },
            "limit": {"type": "integer", "default": 20},
            "offset": {"type": "integer", "default": 0},
        },
    },
    handler=_handle_skills_search_v2_wrapper,
)
_register(
    name="skills_recommendations_v2",
    description="Skills 智能推荐：基于质量评分和用户偏好",
    input_schema={
        "type": "object",
        "properties": {
            "category": {"type": "string", "description": "分类筛选"},
            "limit": {"type": "integer", "default": 10},
        },
    },
    handler=_handle_skills_recommendations_v2_wrapper,
)
_register(
    name="skills_trending_v2",
    description="Skills 热门排行：stars + 下载量 + 评分综合排序",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "default": 20},
        },
    },
    handler=_handle_skills_trending_v2_wrapper,
)
_register(
    name="skills_detail_v2",
    description="获取 Skills 技能详情",
    input_schema={
        "type": "object",
        "properties": {
            "skill_id": {"type": "string", "description": "技能 ID"},
        },
        "required": ["skill_id"],
    },
    handler=_handle_skills_detail_v2_wrapper,
)
_register(
    name="skills_rate_v2",
    description="Skills 评分 (1-5)",
    input_schema={
        "type": "object",
        "properties": {
            "skill_id": {"type": "string"},
            "rating": {"type": "integer", "minimum": 1, "maximum": 5},
            "review": {"type": "string"},
        },
        "required": ["skill_id", "rating"],
    },
    handler=_handle_skills_rate_v2_wrapper,
)
_register(
    name="skills_stats_v2",
    description="Skills 市场统计仪表板",
    input_schema={"type": "object", "properties": {}},
    handler=_handle_skills_stats_v2_wrapper,
)
_register(
    name="skills_sync_v2",
    description="Skills 市场数据同步（从所有数据源重新拉取）",
    input_schema={"type": "object", "properties": {}},
    handler=_handle_skills_sync_v2_wrapper,
)
_register(
    name="skills_categories_v2",
    description="列出 Skills 所有分类",
    input_schema={"type": "object", "properties": {}},
    handler=_handle_skills_categories_v2_wrapper,
)


# ── Extensions 市场自动刷新工具（供调度器使用） ──────────


async def _handle_refresh_extensions(args: dict) -> dict:
    """强制刷新扩展市场缓存（供调度器 cron 调用）"""
    from pycoder.server.log import log as _log

    try:
        from pycoder.extensions.marketplace import search_extensions

        # 传空 query 触发全量并行拉取
        result = await search_extensions(query="", limit=1)
        _log.info(
            "extensions_auto_refresh_done",
            total=result.get("total_all", 0),
            cached=result.get("sources", {}).get("used_cache", False),
        )
        return {"success": True, "total": result.get("total_all", 0)}
    except Exception as e:
        _log.warning("extensions_auto_refresh_failed", error=str(e)[:100])
        return {"success": False, "error": str(e)}


_register(
    name="refresh_extensions",
    description="强制刷新扩展市场缓存（调度器定时任务使用）",
    input_schema={"type": "object", "properties": {}},
    handler=_handle_refresh_extensions,
)


# ── Extensions 管理 MCP 工具（供 AI 对话调用） ──────────


async def _handle_extensions_search(args: dict) -> dict:
    """搜索可用扩展"""
    try:
        from pycoder.extensions.marketplace import search_extensions as se

        q = args.get("query", "")
        category = args.get("category", "")
        limit = args.get("limit", 20)
        result = await se(query=q, category=category, limit=limit)
        # 简化返回结果
        exts = []
        for e in result.get("extensions", [])[:limit]:
            exts.append(
                {
                    "id": e.get("id"),
                    "name": e.get("name"),
                    "description": (e.get("description") or "")[:200],
                    "author": e.get("author"),
                    "stars": e.get("stars", 0),
                    "category": e.get("category"),
                    "tags": e.get("tags", [])[:3],
                    "installed": e.get("installed", False),
                }
            )
        return {"success": True, "extensions": exts, "total": result.get("total", 0)}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


async def _handle_extensions_install(args: dict) -> dict:
    """安装一个扩展"""
    ext_id = args.get("id", "")
    if not ext_id:
        return {"success": False, "error": "id 不能为空"}
    try:
        from pycoder.extensions.manager import ExtensionManager

        mgr = ExtensionManager()
        if mgr.is_installed(ext_id):
            return {"success": True, "id": ext_id, "already_installed": True}
        ext_data = {"id": ext_id}
        ok = await mgr.install(ext_id, ext_data)
        return {"success": ok, "id": ext_id}
    except PermissionError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


async def _handle_extensions_uninstall(args: dict) -> dict:
    """卸载扩展"""
    ext_id = args.get("id", "")
    if not ext_id:
        return {"success": False, "error": "id 不能为空"}
    try:
        from pycoder.extensions.manager import ExtensionManager

        mgr = ExtensionManager()
        ok = mgr.uninstall(ext_id)
        return {"success": ok, "id": ext_id}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


async def _handle_extensions_installed(args: dict) -> dict:
    """列出已安装的扩展"""
    try:
        from pycoder.extensions.manager import ExtensionManager

        mgr = ExtensionManager()
        installed = mgr.get_installed()
        exts = [
            {
                "id": e.get("id"),
                "name": e.get("name"),
                "version": e.get("version"),
                "enabled": e.get("enabled", True),
            }
            for e in installed
        ]
        return {"success": True, "extensions": exts, "count": len(exts)}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


_register(
    name="extensions_search",
    description="搜索可用扩展市场。返回扩展名称、描述、作者、评星数。",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "category": {
                "type": "string",
                "description": "分类筛选(git/devops/tools/code-quality等)",
            },
            "limit": {"type": "integer", "description": "返回数量", "default": 20},
        },
    },
    handler=_handle_extensions_search,
)
_register(
    name="extensions_install",
    description="安装一个扩展。需要提供扩展的 id。",
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "扩展 ID，如 pycoder.gitlens"},
        },
        "required": ["id"],
    },
    handler=_handle_extensions_install,
)
_register(
    name="extensions_uninstall",
    description="卸载一个已安装的扩展。",
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "扩展 ID"},
        },
        "required": ["id"],
    },
    handler=_handle_extensions_uninstall,
)
_register(
    name="extensions_installed",
    description="列出所有已安装的扩展及其状态。",
    input_schema={"type": "object", "properties": {}},
    handler=_handle_extensions_installed,
)


def list_builtin_tools() -> list[dict]:
    """列出所有内置 MCP Tool"""
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
            "source": "builtin",
        }
        for t in _builtin_tools.values()
    ]


async def call_builtin_tool(name: str, args: dict) -> MCPCallResult:
    """调用内置 MCP Tool"""
    tool = _builtin_tools.get(name)
    if not tool or not tool.handler:
        return MCPCallResult(success=False, error=f"未知 Tool: {name}", tool=name)
    try:
        result = await tool.handler(args)
        return MCPCallResult(success=True, output=result, tool=name)
    except Exception as e:
        log.error("mcp_tool_error", tool=name, error=str(e))
        return MCPCallResult(success=False, error=str(e), tool=name)


# ══════════════════════════════════════════════════════════
# 外部 MCP Server 管理器
# ══════════════════════════════════════════════════════════


class MCPClientManager:
    """
    管理外部 MCP Server 连接。

    让 pycode 能连接 filesystem、playwright、github 等标准 MCP Server。
    依赖 `mcp` 包 (pip install mcp)。
    """

    def __init__(self):
        self._servers: dict[str, Any] = {}  # name -> MCPClient

    @property
    def connected_servers(self) -> list[str]:
        return list(self._servers.keys())

    async def connect_stdio(self, name: str, command: str, *args: str) -> bool:
        """通过 stdio 连接一个 MCP Server（本地）"""
        try:
            from mcp import ClientSession
            from mcp.client.stdio import StdioServerParameters, stdio_client

            params = StdioServerParameters(command=command, args=list(args))
            read, write = await stdio_client(params)
            session = await ClientSession(read, write).__aenter__()
            await session.initialize()

            self._servers[name] = {
                "session": session,
                "read": read,
                "write": write,
                "params": params,
            }
            log.info("mcp_connected", server=name, command=command)
            return True
        except ImportError:
            log.warning("mcp_not_installed", server=name)
            return False
        except Exception as e:
            log.error("mcp_connect_failed", server=name, error=str(e))
            return False

    async def list_remote_tools(self, server: str) -> list[dict]:
        """列出某外部 Server 提供的 Tool"""
        entry = self._servers.get(server)
        if not entry:
            return []
        try:
            result = await entry["session"].list_tools()
            return [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.inputSchema,
                    "source": f"mcp:{server}",
                }
                for t in result.tools
            ]
        except Exception as e:
            log.error("mcp_list_tools_failed", server=server, error=str(e))
            return []

    async def call_remote_tool(self, server: str, tool: str, args: dict) -> MCPCallResult:
        """调用外部 Server 的 Tool"""
        entry = self._servers.get(server)
        if not entry:
            return MCPCallResult(success=False, error=f"未连接 Server: {server}", tool=tool)
        try:
            result = await entry["session"].call_tool(tool, args)
            return MCPCallResult(success=True, output=result.content, tool=tool)
        except Exception as e:
            return MCPCallResult(success=False, error=str(e), tool=tool)

    async def disconnect(self, name: str):
        """断开一个外部 Server"""
        entry = self._servers.pop(name, None)
        if entry:
            try:
                await entry["session"].__aexit__(None, None, None)
            except Exception as e:
                # 外部 MCP Server 关闭失败不应阻断主流程
                log.debug("mcp_session_close_failed", server=name, error=str(e))
            log.info("mcp_disconnected", server=name)

    async def disconnect_all(self):
        """断开所有外部 Server"""
        for name in list(self._servers.keys()):
            await self.disconnect(name)


# 全局单例
_client_manager: MCPClientManager | None = None


def get_mcp_client_manager() -> MCPClientManager:
    global _client_manager
    if _client_manager is None:
        _client_manager = MCPClientManager()
    return _client_manager
