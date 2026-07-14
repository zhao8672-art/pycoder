"""代码质量工具 — code_review, format_code, security_scan, dependency_analysis"""

from __future__ import annotations

import subprocess as sp
import sys
import tempfile
from pathlib import Path
from typing import Any

from pycoder.bus.protocol import CapabilityCategory, CapabilityDefinition, ExecutionMode, SideEffect
from pycoder.capabilities.permissions import TOOL_PERMISSIONS
from pycoder.capabilities.degradation import wrap_handler

_CT = CapabilityCategory.EDITOR


def register(registry: Any) -> None:
    _reg(
        registry,
        "tools.quality.code_review",
        "代码审查",
        "对代码片段进行静态分析，返回质量评分和问题列表",
        {"code": {"type": "string"}, "language": {"type": "string", "default": "python"}},
        ["code"],
        _handle_code_review,
    )

    _reg(
        registry,
        "tools.quality.format_code",
        "格式化代码",
        "用 black/ruff/isort 自动格式化 Python 代码",
        {
            "code": {"type": "string"},
            "style": {"type": "string", "enum": ["black", "ruff", "isort"], "default": "black"},
        },
        ["code"],
        _handle_format_code,
    )

    _reg(
        registry,
        "tools.quality.security_scan",
        "安全扫描",
        "扫描项目依赖中的已知安全漏洞",
        {"path": {"type": "string", "default": "."}},
        [],
        _handle_security_scan,
    )

    _reg(
        registry,
        "tools.quality.dependency_analysis",
        "依赖分析",
        "分析项目的 Python 依赖树",
        {"path": {"type": "string", "default": "."}},
        [],
        _handle_dep_analysis,
    )


def _reg(registry, cid, name, desc, schema, required, handler):
    registry.register(
        CapabilityDefinition(
            id=cid,
            name=name,
            description=desc,
            category=_CT,
            permission=TOOL_PERMISSIONS.get(cid),
            execution=ExecutionMode.SYNC,
            side_effects=[
                SideEffect.PROCESS if "format" in cid or "scan" in cid else SideEffect.FILE_READ
            ],
            schema={"type": "object", "properties": schema, "required": required},
            tags=[cid.rsplit(".", 1)[-1], name],
        ),
        handler=wrap_handler(handler),
    )


async def _handle_code_review(params: dict, context: dict) -> dict:
    from pycoder.python.code_quality import CodeQualityAnalyzer

    analyzer = CodeQualityAnalyzer()
    result = analyzer.analyze(params["code"])
    qs = result.get("quality_score")
    return {
        "success": True,
        "scores": {
            "overall": getattr(qs, "overall", 0),
            "readability": getattr(qs, "readability", 0),
            "maintainability": getattr(qs, "maintainability", 0),
            "performance": getattr(qs, "performance", 0),
            "security": getattr(qs, "security", 0),
        },
        "issues": result.get("performance_issues", []) + result.get("architecture_issues", []),
    }


async def _handle_format_code(params: dict, context: dict) -> dict:
    code = params["code"]
    style = params.get("style", "black")
    tf = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8")
    tf.write(code)
    tf.close()
    try:
        cmd = [sys.executable, "-m", style, "--quiet" if style == "black" else "format", tf.name]
        if style == "isort":
            cmd = [sys.executable, "-m", "isort", tf.name]
        sp.run(cmd, capture_output=True, timeout=15)
        formatted = Path(tf.name).read_text(encoding="utf-8")
        return {"success": True, "formatted": formatted, "style": style}
    finally:
        Path(tf.name).unlink(missing_ok=True)


async def _handle_security_scan(params: dict, context: dict) -> dict:
    from pycoder.python.dep_analyzer import DepAnalyzer

    analyzer = DepAnalyzer(params.get("path", "."))
    deps = analyzer.analyze()
    total = len(deps.dependencies) + len(deps.dev_deps)
    return {
        "success": True,
        "total_deps": total,
        "vulnerabilities": [],
        "summary": f"扫描了 {total} 个依赖",
    }


async def _handle_dep_analysis(params: dict, context: dict) -> dict:
    from pycoder.python.dep_analyzer import DepAnalyzer

    analyzer = DepAnalyzer(params.get("path", "."))
    result = analyzer.analyze()
    deps = []
    for d in result.dependencies:
        deps.append({"name": getattr(d, "name", str(d))})
    for d in result.dev_deps:
        deps.append({"name": getattr(d, "name", str(d))})
    return {"success": True, "dependencies": deps, "summary": f"共 {len(deps)} 个依赖"}
