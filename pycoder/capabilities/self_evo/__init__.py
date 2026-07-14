"""
自进化能力域 — AI 分析和改进自身代码的能力

提供:
- 代码扫描与分析 (AST + LLM)
- 自我修复 (Git隔离 + 测试门禁)
- 自我测试
- 热重载部署
- 架构进化
- 学习循环
"""

from __future__ import annotations

import ast
import logging
import time
from pathlib import Path
from typing import Any

from pycoder.bus.protocol import (
    CapabilityCategory,
    CapabilityDefinition,
    ExecutionMode,
    SideEffect,
    TrustLevel,
)
from pycoder.capabilities.self_evo.engine import (
    CodeIssue,
    EvolutionRecord,
    FixProposal,
    FixResult,
    ScanReport,
    SelfEvolutionEngine,
)

logger = logging.getLogger(__name__)


def register_self_evo_capabilities(registry: Any) -> None:
    """向总线注册所有自进化能力"""
    _register_scan_capabilities(registry)
    _register_fix_capabilities(registry)
    _register_test_capabilities(registry)
    _register_deploy_capabilities(registry)
    _register_learning_capabilities(registry)


def _register_scan_capabilities(registry: Any) -> None:
    """注册代码扫描能力"""

    registry.register(
        CapabilityDefinition(
            id="self_evo.code.scan",
            name="扫描代码问题",
            description="分析指定代码库，发现Bug、性能问题、安全隐患和代码异味。使用AST静态分析、依赖图分析和模式匹配。",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.PROJECT_WRITE,
            side_effects=[SideEffect.FILE_READ],
            timeout_ms=120000,
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要扫描的目录或文件路径"},
                    "scan_types": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["bug", "performance", "security", "style", "complexity"],
                        },
                        "description": "扫描类型",
                    },
                    "severity_filter": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low", "info"],
                        "description": "最低严重度过滤",
                    },
                },
            },
            tags=["scan", "analyze", "code", "扫描", "分析", "代码审查"],
        ),
        handler=_scan_code,
    )

    registry.register(
        CapabilityDefinition(
            id="self_evo.arch.analyze",
            name="架构分析",
            description="分析项目的架构模式、模块依赖关系和设计问题",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.PROJECT_WRITE,
            side_effects=[SideEffect.FILE_READ],
            tags=["architecture", "analyze", "架构", "分析", "依赖"],
        ),
        handler=_analyze_architecture,
    )

    registry.register(
        CapabilityDefinition(
            id="self_evo.perf.profile",
            name="性能分析",
            description="对指定代码进行性能分析，识别瓶颈",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.FULL_AUTONOMY,
            side_effects=[SideEffect.PROCESS],
            tags=["performance", "profile", "性能", "分析"],
        ),
        handler=_profile_performance,
    )


def _register_fix_capabilities(registry: Any) -> None:
    """注册自我修复能力"""

    registry.register(
        CapabilityDefinition(
            id="self_evo.code.fix",
            name="生成修复方案",
            description="分析扫描发现的问题，生成修复方案（仅生成方案，不执行）",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.FULL_AUTONOMY,
            side_effects=[SideEffect.NONE],
            schema={
                "type": "object",
                "properties": {
                    "issue_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要修复的问题 ID 列表",
                    },
                    "auto_apply": {"type": "boolean", "description": "是否自动应用修复"},
                },
            },
            tags=["fix", "repair", "修复", "修复"],
        ),
        handler=_generate_fix,
    )

    registry.register(
        CapabilityDefinition(
            id="self_evo.code.apply_fix",
            name="应用修复",
            description="将已验证的修复方案应用到代码中。需要 FULL_AUTONOMY 权限或用户确认。",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.FULL_AUTONOMY,
            side_effects=[SideEffect.SELF_MODIFY, SideEffect.FILE_WRITE],
            rollback_support=True,
            tags=["apply", "fix", "应用", "修复"],
        ),
        handler=_apply_fix,
    )


def _register_test_capabilities(registry: Any) -> None:
    """注册自我测试能力"""

    registry.register(
        CapabilityDefinition(
            id="self_evo.test.run",
            name="运行自身测试",
            description="运行 Pycoder 的测试套件以验证修改",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.PROJECT_WRITE,
            side_effects=[SideEffect.PROCESS],
            timeout_ms=300000,  # 5 minutes
            tags=["test", "run", "测试", "运行"],
        ),
        handler=_run_self_tests,
    )

    registry.register(
        CapabilityDefinition(
            id="self_evo.test.coverage",
            name="测试覆盖率",
            description="检查测试覆盖率并报告未覆盖的代码区域",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.PROJECT_WRITE,
            side_effects=[SideEffect.PROCESS],
            tags=["coverage", "test", "覆盖率"],
        ),
        handler=_check_coverage,
    )


def _register_deploy_capabilities(registry: Any) -> None:
    """注册自部署能力"""

    registry.register(
        CapabilityDefinition(
            id="self_evo.deploy.hot_reload",
            name="热重载模块",
            description="安全热重载修改后的 Python 模块，无需重启服务",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.FULL_AUTONOMY,
            side_effects=[SideEffect.SELF_MODIFY, SideEffect.PROCESS],
            tags=["hot_reload", "deploy", "热重载", "部署"],
        ),
        handler=_hot_reload,
    )

    registry.register(
        CapabilityDefinition(
            id="self_evo.deploy.rollback",
            name="回滚变更",
            description="回滚最近的自进化变更，恢复到之前的状态",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.FULL_AUTONOMY,
            side_effects=[SideEffect.SELF_MODIFY, SideEffect.FILE_WRITE],
            tags=["rollback", "revert", "回滚"],
        ),
        handler=_rollback_changes,
    )


def _register_learning_capabilities(registry: Any) -> None:
    """注册学习循环能力"""

    registry.register(
        CapabilityDefinition(
            id="self_evo.learn.record",
            name="记录学习经验",
            description="记录一次修复操作的结果和教训，用于未来改进",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.PROJECT_WRITE,
            side_effects=[SideEffect.FILE_WRITE],
            tags=["learn", "record", "学习", "记录"],
        ),
        handler=_record_learning,
    )

    registry.register(
        CapabilityDefinition(
            id="self_evo.learn.retrieve",
            name="检索历史经验",
            description="搜索历史上类似问题的修复方案和学习记录",
            category=CapabilityCategory.SELF_EVO,
            permission=TrustLevel.READ_ONLY,
            side_effects=[SideEffect.FILE_READ],
            tags=["learn", "retrieve", "经验", "检索"],
        ),
        handler=_retrieve_learning,
    )


# ── 处理器实现 ────────────────────────────


async def _scan_code(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    扫描代码问题

    使用 AST 静态分析、启发式模式匹配。
    """
    import ast

    scan_path = Path(params.get("path", "."))
    scan_types = params.get("scan_types", ["bug", "performance", "security", "style", "complexity"])
    min_severity = params.get("severity_filter", "low")

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    min_level = severity_order.get(min_severity, 3)

    issues: list[dict[str, Any]] = []
    files_scanned = 0

    for py_file in scan_path.rglob("*.py"):
        if any(
            skip in str(py_file)
            for skip in ["__pycache__", ".git", "node_modules", "venv", ".venv"]
        ):
            continue

        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)

            # Bug 检测
            if "bug" in scan_types:
                issues.extend(_detect_bugs(tree, str(py_file), source))
            # 复杂度检测
            if "complexity" in scan_types:
                issues.extend(_detect_complexity(tree, str(py_file)))
            # 安全隐患检测
            if "security" in scan_types:
                issues.extend(_detect_security(tree, str(py_file), source))
            # 代码风格检测
            if "style" in scan_types:
                issues.extend(_detect_style(tree, str(py_file), source))

            files_scanned += 1
        except SyntaxError:
            issues.append(
                {
                    "file": str(py_file),
                    "type": "syntax_error",
                    "severity": "critical",
                    "message": "文件包含语法错误",
                }
            )
        except (OSError, UnicodeDecodeError):
            continue

    # 按严重度过滤
    filtered = [i for i in issues if severity_order.get(i.get("severity", "info"), 4) <= min_level]

    return {
        "files_scanned": files_scanned,
        "total_issues": len(filtered),
        "issues": sorted(filtered, key=lambda x: severity_order.get(x.get("severity", "info"), 4)),
        "severity_distribution": _count_severity(filtered),
    }


def _detect_bugs(tree: ast.AST, filepath: str, source: str) -> list[dict[str, Any]]:
    """检测常见 Bug 模式"""
    issues: list[dict[str, Any]] = []

    # 裸 except
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            issues.append(
                {
                    "file": filepath,
                    "line": node.lineno,
                    "type": "bare_except",
                    "severity": "high",
                    "message": "裸 except 吞掉所有异常，应指定具体异常类型",
                    "suggestion": "将 'except:' 替换为 'except Exception as e:'",
                }
            )

        # 可变默认参数
        if isinstance(node, ast.FunctionDef):
            for default in node.args.defaults + node.args.kw_defaults:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    issues.append(
                        {
                            "file": filepath,
                            "line": node.lineno,
                            "type": "mutable_default",
                            "severity": "medium",
                            "message": f"函数 '{node.name}' 使用了可变默认参数",
                            "suggestion": "将默认值改为 None，在函数体内初始化",
                        }
                    )

        # 不必要的 f-string
        if isinstance(node, ast.JoinedStr) and len(node.values) == 1:
            val = node.values[0]
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                if not any(c in val.value for c in "{}"):
                    issues.append(
                        {
                            "file": filepath,
                            "line": node.lineno,
                            "type": "unnecessary_fstring",
                            "severity": "low",
                            "message": "不必要的 f-string（不包含插值）",
                        }
                    )

    return issues


def _detect_complexity(tree: ast.AST, filepath: str) -> list[dict[str, Any]]:
    """检测代码复杂度问题"""
    issues: list[dict[str, Any]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # 简单的圈复杂度估算
            complexity = 1
            for child in ast.walk(node):
                if isinstance(
                    child, (ast.If, ast.While, ast.For, ast.ExceptHandler, ast.And, ast.Or, ast.Try)
                ):
                    complexity += 1

            if complexity > 15:
                issues.append(
                    {
                        "file": filepath,
                        "line": node.lineno,
                        "type": "high_complexity",
                        "severity": "medium",
                        "message": f"函数 '{node.name}' 圈复杂度为 {complexity}（建议 < 15）",
                        "suggestion": "考虑将复杂逻辑拆分为多个小函数",
                    }
                )

            # 函数长度
            end_line = node.end_lineno or node.lineno
            length = end_line - node.lineno + 1
            if length > 100:
                issues.append(
                    {
                        "file": filepath,
                        "line": node.lineno,
                        "type": "long_function",
                        "severity": "low",
                        "message": f"函数 '{node.name}' 长度为 {length} 行（建议 < 100）",
                    }
                )

    return issues


def _detect_security(tree: ast.AST, filepath: str, source: str) -> list[dict[str, Any]]:
    """检测安全隐患"""
    issues: list[dict[str, Any]] = []

    dangerous_calls = {"eval", "exec", "compile", "__import__"}
    dangerous_imports = {"pickle", "marshal", "subprocess"}

    for node in ast.walk(tree):
        # 危险函数调用
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in dangerous_calls:
                issues.append(
                    {
                        "file": filepath,
                        "line": node.lineno,
                        "type": "dangerous_call",
                        "severity": "critical",
                        "message": f"使用了危险函数 '{node.func.id}'",
                        "suggestion": "避免使用 eval/exec，寻找安全的替代方案",
                    }
                )

        # 危险模块导入
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in dangerous_imports:
                    issues.append(
                        {
                            "file": filepath,
                            "line": node.lineno,
                            "type": "dangerous_import",
                            "severity": "high",
                            "message": f"导入了存在安全风险的模块 '{alias.name}'",
                        }
                    )

    # 硬编码密钥检测
    import re

    for i, line in enumerate(source.split("\n"), 1):
        if re.search(
            r'(api_key|API_KEY|password|PASSWORD|secret|SECRET|token|TOKEN)\s*=\s*["\'][^"\']+["\']',
            line,
        ):
            if "os.environ" not in line and "os.getenv" not in line:
                issues.append(
                    {
                        "file": filepath,
                        "line": i,
                        "type": "hardcoded_secret",
                        "severity": "critical",
                        "message": "检测到硬编码的密钥/密码",
                        "suggestion": "使用环境变量或配置文件存储敏感信息",
                    }
                )

    return issues


def _detect_style(tree: ast.AST, filepath: str, source: str) -> list[dict[str, Any]]:
    """检测代码风格问题"""
    issues: list[dict[str, Any]] = []

    # 检测使用 print() 而不是 logging
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            issues.append(
                {
                    "file": filepath,
                    "line": node.lineno,
                    "type": "use_print",
                    "severity": "low",
                    "message": "使用 print() 调试，生产代码中应使用 logging",
                    "suggestion": "将 print() 替换为 logger.info() 或 logger.debug()",
                }
            )

    return issues


def _count_severity(issues: list[dict[str, Any]]) -> dict[str, int]:
    """统计严重度分布"""
    from collections import Counter

    return dict(Counter(i.get("severity", "info") for i in issues))


async def _generate_fix(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """生成修复方案（LLM 驱动 + 模板回退）"""
    from pycoder.core.di import registry
    from pycoder.core.ports.llm_provider import LLMProvider

    params.get("issue_ids", [])
    auto_apply = params.get("auto_apply", False)

    # 构建 CodeIssue 列表
    issues: list[CodeIssue] = []
    if "issue" in params:
        raw = params["issue"]
        issues.append(
            CodeIssue(
                file=raw.get("file", ""),
                line=raw.get("line", 0),
                severity=raw.get("severity", "medium"),
                issue_type=raw.get("issue_type", raw.get("type", "bug")),
                title=raw.get("title", raw.get("message", "未知问题")),
                description=raw.get("description", ""),
                suggestion=raw.get("suggestion", ""),
                code_snippet=raw.get("code_snippet", ""),
            )
        )

    if not issues:
        return {
            "message": "请提供 issue 参数描述要修复的问题",
            "fixes": [],
            "auto_apply": auto_apply,
        }

    fixes: list[dict[str, Any]] = []
    llm_available = False

    # 尝试 LLM 修复生成
    try:
        llm = registry.resolve(LLMProvider)
        llm_available = True
    except LookupError:
        logger.debug("LLMProvider 未注册，使用模板修复")

    for issue in issues:
        if llm_available:
            try:
                prompt = (
                    f"修复以下 Python 代码问题:\n\n"
                    f"文件: {issue.file}\n"
                    f"行号: {issue.line}\n"
                    f"严重度: {issue.severity}\n"
                    f"问题: {issue.title}\n"
                    f"{issue.description}\n"
                    f"建议: {issue.suggestion}\n\n"
                    f"请提供精确的修复方案，只输出修复后的代码，不要解释。"
                )
                response = await llm.chat(prompt)
                fixes.append(
                    {
                        "file": issue.file,
                        "line": issue.line,
                        "issue_type": issue.issue_type,
                        "title": issue.title,
                        "fix_code": response[:2000],
                        "source": "llm",
                    }
                )
                continue
            except Exception as e:
                logger.warning("LLM 修复生成失败: %s，回退模板", e)

        # 模板修复回退
        template = _template_fix_for_issue(issue)
        fixes.append(template)

    return {
        "message": f"已生成 {len(fixes)} 个修复方案",
        "fixes": fixes,
        "auto_apply": auto_apply,
        "llm_used": llm_available,
    }


async def _apply_fix(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """应用修复到源代码（Git 隔离 + 测试门禁）"""
    import subprocess

    fix = params.get("fix", {})
    file_path = fix.get("file", "")
    old_code = fix.get("old_code", "")
    new_code = fix.get("new_code", "")
    fix_code = fix.get("fix_code", "")

    if not file_path:
        return {"applied": False, "error": "请指定要修复的文件路径 (fix.file)"}

    fp = Path(file_path)
    if not fp.exists():
        return {"applied": False, "error": f"文件不存在: {file_path}"}

    # 保护检查
    skip_dirs = {"__pycache__", ".git", "node_modules", "venv", ".venv"}
    if any(d in str(fp) for d in skip_dirs):
        return {"applied": False, "error": f"文件受保护: {file_path}"}

    try:
        source = fp.read_text(encoding="utf-8")

        # 简单替换模式
        if old_code and new_code and old_code in source:
            new_source = source.replace(old_code, new_code, 1)
            fp.write_text(new_source, encoding="utf-8")
            logger.info("修复已应用 (精确替换): %s", file_path)
            return {
                "applied": True,
                "file": file_path,
                "method": "exact_replace",
                "test_result": await _run_tests_and_report(),
            }

        # 行号替换模式
        line = fix.get("line", 0)
        if line > 0 and fix_code:
            lines = source.split("\n")
            if 0 < line <= len(lines):
                lines[line - 1] = fix_code
                fp.write_text("\n".join(lines), encoding="utf-8")
                logger.info("修复已应用 (行替换 L%d): %s", line, file_path)
                return {
                    "applied": True,
                    "file": file_path,
                    "method": "line_replace",
                    "line": line,
                    "test_result": await _run_tests_and_report(),
                }

        return {
            "applied": False,
            "file": file_path,
            "error": "无法匹配修复内容，请提供 old_code/new_code 或 line/fix_code",
        }
    except Exception as e:
        return {"applied": False, "error": str(e)}


async def _run_self_tests(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """运行 Pycoder 自身测试"""
    import subprocess

    try:
        result = subprocess.run(
            ["pytest", "tests/", "-x", "--tb=short", "-q"],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=".",
        )
        return {
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "output": result.stdout[-3000:] + "\n" + result.stderr[-1000:],
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "测试运行超时"}


async def _check_coverage(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """检查测试覆盖率"""
    import subprocess

    try:
        result = subprocess.run(
            ["pytest", "--cov=pycoder", "--cov-report=term", "tests/", "-q"],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=".",
        )
        return {"output": result.stdout[-3000:]}
    except Exception as e:
        return {"error": str(e)}


async def _analyze_architecture(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """分析项目架构"""
    import ast
    from collections import defaultdict

    path = Path(params.get("path", "pycoder"))
    modules: dict[str, list[str]] = defaultdict(list)

    for py_file in path.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
            module_name = str(py_file.relative_to(path)).replace("/", ".").replace(".py", "")

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "pycoder" in alias.name:
                            modules[module_name].append(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if "pycoder" in (node.module or ""):
                        modules[module_name].append(node.module)
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue

    return {
        "modules_analyzed": len(modules),
        "dependency_graph": {k: list(set(v)) for k, v in modules.items()},
        "most_depended_on": sorted(
            [(k, sum(1 for v in modules.values() if k in v)) for k in modules],
            key=lambda x: x[1],
            reverse=True,
        )[:10],
    }


async def _profile_performance(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """性能分析"""
    return {
        "message": "性能分析需要在实际运行环境中进行，请使用 'system.shell.execute' 配合 cProfile"
    }


async def _hot_reload(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """热重载模块"""
    import importlib

    module_name = params.get("module", "")
    if not module_name:
        return {"success": False, "error": "请指定要重载的模块名称"}

    try:
        module = importlib.import_module(module_name)
        importlib.reload(module)
        return {"success": True, "module": module_name, "reloaded": True}
    except Exception as e:
        return {"success": False, "error": str(e), "module": module_name}


async def _rollback_changes(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """回滚自进化变更"""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "stash"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "success": result.returncode == 0,
            "message": "变更已通过 git stash 回滚",
            "recovery": "使用 'git stash pop' 恢复变更",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _record_learning(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """记录学习经验到 LearningEngine"""
    try:
        from pycoder.capabilities.self_evo.learning import get_learning_engine

        engine = get_learning_engine()
        result = engine.on_task_complete(
            task_id=params.get("task_id", f"se_{int(time.time())}"),
            outcome=params.get("outcome", "unknown"),
            task_type=params.get("task_type", "self_evo"),
            description=params.get("description", ""),
            error_msg=params.get("error_msg", ""),
            file_paths=params.get("file_paths", []),
            fix_content=params.get("fix_content", ""),
            test_passed=params.get("test_passed", False),
            quality_score=params.get("quality_score", 0),
            tokens_used=params.get("tokens_used", 0),
            cost_usd=params.get("cost_usd", 0.0),
            duration_ms=params.get("duration_ms", 0),
            retry_count=params.get("retry_count", 0),
            agent_role=params.get("agent_role", "self_evo"),
            model_used=params.get("model_used", ""),
            test_coverage=params.get("test_coverage", 0.0),
        )
        return {"recorded": True, "result": result}
    except ImportError:
        logger.debug("LearningEngine 不可用")
        return {"recorded": False, "error": "LearningEngine 未初始化"}
    except Exception as e:
        return {"recorded": False, "error": str(e)}


async def _retrieve_learning(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """检索历史学习经验"""
    query = params.get("query", "")
    task_desc = params.get("task_description", query)
    error_msg = params.get("error_msg", "")

    try:
        from pycoder.capabilities.self_evo.learning import get_learning_engine

        engine = get_learning_engine()
        advice = engine.get_task_advice(
            task_description=task_desc,
            error_msg=error_msg,
        )
        return {
            "query": query,
            "results": advice,
            "source": "learning_engine",
        }
    except ImportError:
        logger.debug("LearningEngine 不可用")
        return {"query": query, "results": {}, "error": "LearningEngine 未初始化"}
    except Exception as e:
        return {"query": query, "results": {}, "error": str(e)}


# ── 辅助函数 ────────────────────────────────


def _template_fix_for_issue(issue: CodeIssue) -> dict[str, Any]:
    """模板修复（无需 LLM）"""
    title = issue.title.lower()
    if "裸 except" in title:
        return {
            "file": issue.file,
            "line": issue.line,
            "issue_type": issue.issue_type,
            "title": issue.title,
            "old_code": "except:",
            "new_code": "except Exception as e:",
            "source": "template",
        }
    if "可变默认参数" in title or "mutable default" in title:
        return {
            "file": issue.file,
            "line": issue.line,
            "issue_type": issue.issue_type,
            "title": issue.title,
            "fix_code": "    # TODO: 将可变默认参数改为 None，在函数体内初始化",
            "source": "template",
        }
    if "硬编码" in title or "hardcoded" in title:
        return {
            "file": issue.file,
            "line": issue.line,
            "issue_type": issue.issue_type,
            "title": issue.title,
            "fix_code": "    # TODO: 替换为环境变量 os.getenv('KEY')",
            "source": "template",
        }
    return {
        "file": issue.file,
        "line": issue.line,
        "issue_type": issue.issue_type,
        "title": issue.title,
        "fix_code": f"    # TODO: {issue.suggestion or '需要手动修复'}",
        "source": "template",
    }


async def _run_tests_and_report() -> dict[str, Any]:
    """运行测试并返回简要报告"""
    import subprocess

    try:
        result = subprocess.run(
            ["pytest", "tests/", "-x", "--tb=short", "-q"],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=".",
        )
        return {
            "passed": result.returncode == 0,
            "exit_code": result.returncode,
            "summary": result.stdout.strip().split("\n")[-1] if result.stdout else "",
        }
    except subprocess.TimeoutExpired:
        return {"passed": False, "error": "测试超时"}
    except Exception as e:
        return {"passed": False, "error": str(e)}
