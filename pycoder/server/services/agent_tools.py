"""
共享 Agent 工具执行器 — 消除 agent_orchestrator / team_orchestrator / autonomous_pipeline 的三处重复实现。

提供统一的工具执行入口，所有 Agent 系统共享同一份代码。

用法:
    from pycoder.server.services.agent_tools import execute_agent_tool, UNIFIED_ALLOWED_COMMANDS

    result = await execute_agent_tool("read_file", {"path": "app.py"}, workspace=Path("."))
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 统一命令白名单（合并三处白名单，取并集）
# ══════════════════════════════════════════════════════════

UNIFIED_ALLOWED_COMMANDS: list[str] = [
    # 语言运行时
    "python",
    "python3",
    "node",
    "npm",
    "npx",
    "go",
    "rustc",
    "cargo",
    "java",
    "javac",
    # 包管理
    "pip",
    "pip3",
    "uv",
    "uvx",
    "poetry",
    "conda",
    # 版本控制
    "git",
    # 测试
    "pytest",
    "coverage",
    "tox",
    "nox",
    # 代码质量
    "ruff",
    "black",
    "isort",
    "mypy",
    "pylint",
    "flake8",
    # Web 框架
    "uvicorn",
    "fastapi",
    "flask",
    "gunicorn",
    "streamlit",
    # 容器
    "docker",
    "docker-compose",
    # 系统工具
    "ls",
    "dir",
    "echo",
    "cat",
    "type",
    "pwd",
    "cd",
    "mkdir",
    "cp",
    "copy",
    "mv",
    "move",
    "rm",
    "del",
    "curl",
    "wget",
    "ping",
    "nslookup",
    # 打包
    "zip",
    "tar",
    "gzip",
    # Windows
    "where",
    "findstr",
    "tasklist",
    "netstat",
]

# 默认超时 (秒)
DEFAULT_TOOL_TIMEOUT = 60

# 搜索忽略目录
_SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    ".pytest_cache",
    ".pycoder_backups",
    ".pycoder_delivery",
    ".pycoder_tests",
}
_SKIP_SUFFIXES = {".pyc", ".pyo", ".so", ".dll", ".exe", ".pyd"}


# ══════════════════════════════════════════════════════════
# 角色权限映射
# ══════════════════════════════════════════════════════════


def _map_tool_to_action(tool_name: str, params: dict) -> str:
    """将工具调用映射为操作分类，用于权限检查

    返回操作名，与 AgentRole.forbid_actions 中的值对应。
    """
    # write_file → code_write
    if tool_name == "write_file":
        return "code_write"

    # patch_file → code_modify (比 write_file 限制更轻，允许局部修改)
    if tool_name == "patch_file":
        return "code_modify"

    # run_command → 细分
    if tool_name == "run_command":
        cmd = params.get("command", "")
        cmd_lower = cmd.lower()

        # deploy 相关
        if any(
            kw in cmd_lower
            for kw in (
                "docker push",
                "docker build",
                "kubectl",
                "helm",
                "deploy",
                "aws ",
                "gcloud",
                "terraform",
                "ansible",
            )
        ):
            return "deploy"

        # shell 执行
        if any(
            kw in cmd_lower
            for kw in (
                "pip install",
                "npm install",
                "pip3 install",
                "uv install",
                "conda install",
                "poetry add",
            )
        ):
            return "shell_install"

        if any(kw in cmd_lower for kw in ("rm -rf", "del /f", "rd /s", "format", "mkfs", "dd ")):
            return "shell_destructive"

        return "shell_exec"

    # install_package/ensure_tool/install_deps → shell_install
    if tool_name in ("install_package", "ensure_tool", "install_deps"):
        return "shell_install"

    # 搜索类操作
    if tool_name in ("search_code", "search_package"):
        return "code_search"

    # 其余视为 code_read
    return "code_read"


async def execute_agent_tool(
    tool_name: str,
    params: dict,
    workspace: Path,
    *,
    timeout: int = DEFAULT_TOOL_TIMEOUT,
    allowed_commands: list[str] | None = None,
    agent_role: str = "",  # 当前 Agent 角色 ID（用于权限拦截）
    agent_forbid_actions: list[str] | None = None,  # 禁止操作列表
) -> str:
    """
    执行单个 Agent 工具并返回结果字符串。

    Args:
        tool_name: 工具名称 (read_file/write_file/search_code/run_command/list_files/git_diff)
        params: 工具参数字典
        workspace: 工作区根目录
        timeout: 命令执行超时 (秒)，默认 60
        allowed_commands: 允许执行的命令白名单，默认使用 UNIFIED_ALLOWED_COMMANDS
        agent_role: 当前 Agent 角色 ID（为空则不进行权限检查）
        agent_forbid_actions: 该 Agent 禁止的操作列表（为空则不进行权限检查）

    Returns:
        工具执行结果字符串
    """
    cmds = allowed_commands or UNIFIED_ALLOWED_COMMANDS

    # ── 运行时权限拦截 ──
    if agent_role and agent_forbid_actions:
        action = _map_tool_to_action(tool_name, params)
        if action in agent_forbid_actions:
            return (
                f"⛔ 权限拒绝: {agent_role} 不允许执行 「{action}」操作"
                f" (工具: {tool_name}, 参数: {params})"
            )

    try:
        if tool_name == "read_file":
            return _tool_read_file(params, workspace)

        elif tool_name == "write_file":
            return _tool_write_file(params, workspace)

        elif tool_name == "search_code":
            return _tool_search_code(params, workspace)

        elif tool_name == "run_command":
            return _tool_run_command(params, workspace, cmds, timeout)

        elif tool_name == "list_files":
            return _tool_list_files(params, workspace)

        elif tool_name == "git_diff":
            return _tool_git_diff(params, workspace)

        elif tool_name == "patch_file":
            return _tool_patch_file(params, workspace)

        elif tool_name == "install_package":
            import pycoder.server.services.auto_installer as ai

            return await ai.agent_install_package(params)

        elif tool_name == "search_package":
            import pycoder.server.services.auto_installer as ai

            return await ai.agent_search_package(params)

        elif tool_name == "ensure_tool":
            import pycoder.server.services.auto_installer as ai

            return await ai.agent_ensure_tool(params)

        elif tool_name == "install_deps":
            import pycoder.server.services.auto_installer as ai

            return await ai.agent_install_deps(params)

        elif tool_name == "create_file":
            return _tool_write_file(params, workspace)

        elif tool_name == "overwrite_file":
            return _tool_write_file(params, workspace)

        elif tool_name == "run_terminal":
            return _tool_run_command(params, workspace, cmds, timeout)

        elif tool_name == "execute_python":
            return _tool_execute_python(params, workspace, timeout)

        elif tool_name == "git_add":
            return _tool_git_simple(["git", "add", params.get("path", ".")], workspace)

        elif tool_name == "git_commit":
            return _tool_git_commit(params, workspace)

        elif tool_name == "git_push":
            return _tool_git_simple(["git", "push"], workspace)

        elif tool_name == "git_status":
            return _tool_git_simple(["git", "status"], workspace)

        elif tool_name == "git_branch":
            return _tool_git_simple(["git", "branch"], workspace)

        elif tool_name == "git_log":
            return _tool_git_simple(["git", "log", "--oneline", "-20"], workspace)

        elif tool_name == "list_agent_configs":
            return _tool_list_agent_configs(params)

        else:
            return f"❌ 未知工具: {tool_name}"

    except subprocess.TimeoutExpired:
        return f"❌ 工具 {tool_name} 执行超时 ({timeout}s)"
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        TypeError,
        AttributeError,
        PermissionError,
        FileNotFoundError,
        NotImplementedError,
    ) as e:
        return f"❌ 工具执行失败: {e}"


# ══════════════════════════════════════════════════════════
# 各工具实现
# ══════════════════════════════════════════════════════════


def _tool_read_file(params: dict, workspace: Path) -> str:
    """读取工作区内的文件"""
    p = (workspace / params["path"]).resolve()
    # M8: 用 is_relative_to 替代字符串前缀匹配
    if not p.is_relative_to(workspace):
        return "❌ 路径越界"
    if not p.exists():
        return f"❌ 文件不存在: {params['path']}"
    return p.read_text(encoding="utf-8", errors="replace")


def _tool_write_file(params: dict, workspace: Path) -> str:
    """写入文件到工作区"""
    p = (workspace / params["path"]).resolve()
    # M8: 用 is_relative_to 替代字符串前缀匹配
    if not p.is_relative_to(workspace):
        return "❌ 路径越界"
    p.parent.mkdir(parents=True, exist_ok=True)
    content = params.get("content", "")
    if not isinstance(content, str):
        content = str(content)
    p.write_text(content, encoding="utf-8")
    return f"✅ 已写入: {params['path']} ({len(content)} 字符)"


def _tool_search_code(params: dict, workspace: Path) -> str:
    """在工作区内搜索代码"""
    query = params["query"].lower()
    ft = params.get("file_type", "")
    results: list[str] = []
    for f in workspace.rglob("*"):
        if f.suffix in _SKIP_SUFFIXES:
            continue
        if ft and f.suffix != ft:
            continue
        if any(p in str(f) for p in _SKIP_DIRS):
            continue
        try:
            for i, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
                if query in line.lower():
                    results.append(f"  {f.relative_to(workspace)}:{i}: {line.strip()[:120]}")
                    if len(results) >= 20:
                        break
        except (OSError, UnicodeDecodeError) as e:
            logger.debug("search_file_read_failed path=%s error=%s", f, e)
        if len(results) >= 20:
            break
    return "\n".join(results) if results else "未找到匹配"


def _tool_run_command(
    params: dict,
    workspace: Path,
    allowed_commands: list[str],
    timeout: int,
) -> str:
    """执行白名单内的 shell 命令"""
    cmd_str: str = params["command"]
    parts = cmd_str.split()
    base_cmd = os.path.basename(parts[0]) if parts else ""
    if base_cmd not in allowed_commands:
        return f"❌ 命令 '{base_cmd}' 不在白名单中。" f"允许: {', '.join(sorted(allowed_commands))}"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    r = subprocess.run(
        parts if len(parts) > 1 else [parts[0]],
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(workspace),
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    output = r.stdout
    if r.stderr:
        output += "\n--- stderr ---\n" + r.stderr
    return output[:4000] if output else "(无输出)"


def _tool_list_files(params: dict, workspace: Path) -> str:
    """列出目录内容"""
    p = workspace / params.get("path", ".")
    try:
        depth = int(params.get("depth", 2))
    except (ValueError, TypeError):
        depth = 2
    lines: list[str] = []
    for item in sorted(p.iterdir()):
        icon = "📁" if item.is_dir() else "📄"
        lines.append(f"{icon} {item.name}")
        if item.is_dir() and depth > 1:
            for sub in sorted(item.iterdir()):
                sub_icon = "📁" if sub.is_dir() else "📄"
                lines.append(f"  {sub_icon} {sub.name}")
    return "\n".join(lines[:100])


def _tool_git_diff(params: dict, workspace: Path) -> str:
    """查看 Git 变更"""
    f = params.get("file", "")
    cmd = ["git", "diff", "--stat"] if not f else ["git", "diff", f]
    r = subprocess.run(
        cmd,
        shell=False,
        capture_output=True,
        text=True,
        cwd=str(workspace),
        encoding="utf-8",
        errors="replace",
    )
    return r.stdout[:3000] or "无变更"


# ══════════════════════════════════════════════════════════
# git_simple — 通用 Git 命令执行器
# ══════════════════════════════════════════════════════════


def _tool_git_simple(cmd: list[str], workspace: Path) -> str:
    """执行简单的 git 命令并返回输出"""
    try:
        r = subprocess.run(
            cmd,
            shell=False,
            capture_output=True,
            text=True,
            cwd=str(workspace),
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        output = r.stdout.strip()
        if r.stderr:
            stderr = r.stderr.strip()
            if stderr:
                output += "\n--- stderr ---\n" + stderr
        return output[:3000] if output else f"✅ 命令执行成功: {' '.join(cmd)}"
    except subprocess.TimeoutExpired:
        return "❌ Git 命令执行超时 (30s)"
    except (OSError, ValueError, PermissionError) as e:
        return f"❌ Git 命令失败: {e}"


def _tool_git_commit(params: dict, workspace: Path) -> str:
    """Git 提交"""
    message = params.get("message", "update")
    path = params.get("path", ".")
    # 先 add
    add_r = subprocess.run(
        ["git", "add", path],
        shell=False,
        capture_output=True,
        text=True,
        cwd=str(workspace),
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if add_r.returncode != 0:
        return f"❌ git add 失败: {add_r.stderr.strip()[:500]}"
    # 再 commit
    commit_r = subprocess.run(
        ["git", "commit", "-m", message],
        shell=False,
        capture_output=True,
        text=True,
        cwd=str(workspace),
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    output = commit_r.stdout.strip()
    if commit_r.stderr:
        output += "\n" + commit_r.stderr.strip()
    if commit_r.returncode != 0:
        return f"❌ git commit 失败: {output[:1000]}"
    return output[:1000] or "✅ 提交成功"


# ══════════════════════════════════════════════════════════
# execute_python — 沙箱执行 Python 代码
# ══════════════════════════════════════════════════════════


def _tool_execute_python(params: dict, workspace: Path, timeout: int) -> str:
    """执行 Python 代码片段并返回输出"""
    code = params.get("code", "")
    if not code:
        return "❌ 请提供 code 参数"
    import tempfile

    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        delete=False,
        dir=str(workspace),
        encoding="utf-8",
    )
    try:
        tmp.write(code)
        tmp.close()
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        r = subprocess.run(
            [sys.executable, tmp.name],
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(workspace),
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        output = r.stdout
        if r.stderr:
            output += "\n--- stderr ---\n" + r.stderr
        return output[:4000] if output else "(无输出)"
    finally:
        try:
            os.unlink(tmp.name)
        except (OSError, PermissionError):
            pass


# ══════════════════════════════════════════════════════════
# patch_file — 最小改动补丁工具
# ══════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════
# list_agent_configs — 列出系统 Agent 角色配置
# ══════════════════════════════════════════════════════════


def _tool_list_agent_configs(params: dict) -> str:
    """列出系统 Agent 角色详细配置列表

    无需参数。返回所有注册 Agent 的 ID、名称、描述、
    可用工具、模型分层、并发限制、禁止操作等信息。
    """
    from pycoder.server.services.agent_definitions import AGENT_ROLES as roles
    from pycoder.server.services.agent_definitions import (
        CONCURRENCY_LIMITS,
        MODEL_TIERS,
    )

    if not roles:
        return "❌ 未找到任何系统 Agent 配置"

    lines: list[str] = []
    lines.append(f"📋 系统 Agent 配置列表（共 {len(roles)} 个角色）")
    lines.append("=" * 55)

    for role_id, role in roles.items():
        lines.append("")
        lines.append(f"🆔 {role_id} — {role.name}")
        lines.append(f"   描述: {role.description}")
        lines.append(f"   模型: {role.model} (分层: {role.model_tier})")
        lines.append(f"   可用工具: {', '.join(role.tools)}")
        lines.append(f"   并发上限: {role.max_concurrent}")
        lines.append(f"   最大重试: {role.max_retries}")
        lines.append(f"   超时: {role.timeout}s")
        parallel_str = "是" if role.parallel else "否"
        lines.append(f"   并行执行: {parallel_str}")
        skills_str = ", ".join(role.skills) if role.skills else "无"
        lines.append(f"   绑定技能: {skills_str}")
        forbid = role.forbid_actions
        forbid_str = ", ".join(forbid) if forbid else "无"
        lines.append(f"   禁止操作: {forbid_str}")
        hb = (
            f"   心跳间隔: {role.heartbeat_interval}s"
            if role.heartbeat_interval
            else "   心跳: 不需要"
        )
        lines.append(hb)

    lines.append("")
    lines.append("=" * 55)
    lines.append("📊 并发限制")
    for k, v in CONCURRENCY_LIMITS.items():
        lines.append(f"   {k}: {v}")

    lines.append("")
    lines.append("📦 模型分层")
    for tier_name, tier_info in MODEL_TIERS.items():
        models_str = ", ".join(tier_info["models"]) if tier_info["models"] else "(运行时检测)"
        lines.append(f"   {tier_name} ({tier_info['label']}): {models_str}")
        lines.append(f"     用途: {tier_info['purpose']}")

    return "\n".join(lines)


def _tool_patch_file(params: dict, workspace: Path) -> str:
    """精准替换文件中的指定代码片段（最小改动模式）

    用法:
        {"path": "src/app.py", "search": "要替换的原始代码", "replace": "替换后的代码"}

    与 write_file 的区别:
        - write_file: 完整覆盖整个文件
        - patch_file: 仅替换指定的 search 代码段，其余部分保持不变
    """
    file_path = params.get("path", "")
    search = params.get("search", "")
    replace = params.get("replace", "")

    if not file_path or not search:
        return "❌ patch_file 需要 path 和 search 参数"

    target = (workspace / file_path).resolve()
    if not target.is_relative_to(workspace):
        return "❌ 路径越界"

    if not target.exists():
        return f"❌ 文件不存在: {file_path}"

    try:
        content = target.read_text(encoding="utf-8")
    except Exception as e:
        return f"❌ 读取文件失败: {e}"

    # 精确匹配 search
    if search not in content:
        return (
            f"❌ 未找到匹配的代码段 (search 必须精确匹配)\n"
            f"  文件: {file_path}\n"
            f"  搜索文本前 80 字符: {search[:80]}"
        )

    # 统计匹配次数
    match_count = content.count(search)
    if match_count > 1:
        return (
            f"❌ search 文本在文件中出现 {match_count} 次，不唯一\n"
            f"  请提供更多上下文以确保唯一匹配\n"
            f"  文件: {file_path}"
        )

    # 执行替换
    new_content = content.replace(search, replace, 1)
    try:
        target.write_text(new_content, encoding="utf-8")
    except OSError as e:
        return f"❌ 写入文件失败: {e}"

    original_lines = search.count("\n") + 1
    replace_lines = replace.count("\n") + 1
    return (
        f"✅ patch_file 成功: {file_path}\n"
        f"  原代码: {original_lines} 行 → 替换后: {replace_lines} 行\n"
        f"  文件总字符: {len(new_content)}"
    )


# ══════════════════════════════════════════════════════════
# 工具调用解析（LLM 响应 → 工具调用列表）
# ══════════════════════════════════════════════════════════


def parse_tool_calls(response_text: str) -> list[dict]:
    """解析 LLM 响应中的工具调用

    策略（按优先级）：
        1. Markdown ```json ... ``` 代码块 → json.loads + JSON Schema 校验
        2. 裸 JSON 对象（含 tool_calls 字段）
        3. 兼容：LLM 直接返回单个工具调用 ``{"name": "...", "params": {...}}``
        4. 失败：返回空列表

    .. deprecated:: P1-2
        XML 标签解析路径已移除（脆弱，且与 JSON Schema 约束冲突）。
        如需向后兼容旧 LLM 输出，请显式调用 ``parse_tool_calls_legacy_xml``。
    """
    import json as _json

    if not response_text or not response_text.strip():
        return []

    # 策略 1: Markdown JSON 代码块
    json_block_pattern = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)
    for match in json_block_pattern.finditer(response_text):
        json_str = match.group(1).strip()
        calls = _try_parse_json_calls(json_str, _json)
        if calls:
            return calls

    # 策略 2: 裸 JSON 对象
    first_brace = response_text.find("{")
    last_brace = response_text.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        json_str = response_text[first_brace : last_brace + 1]
        calls = _try_parse_json_calls(json_str, _json)
        if calls:
            return calls

    logger.debug("no_tool_calls_parsed", extra={"text_preview": response_text[:200]})
    return []


def _try_parse_json_calls(json_str: str, _json) -> list[dict]:
    """尝试解析 JSON 并通过 Schema 校验

    Args:
        json_str: 待解析的 JSON 字符串
        _json: json 模块（避免重复 import）

    Returns:
        校验通过的 tool_calls 列表，失败返回空列表
    """
    try:
        data = _json.loads(json_str)
    except _json.JSONDecodeError:
        return []

    if not isinstance(data, dict):
        return []

    # 兼容：LLM 可能直接返回单个工具调用 {"name": "...", "params": {...}}
    if "name" in data and "params" in data and "tool_calls" not in data:
        data = {"tool_calls": [data]}

    try:
        from pycoder.server.services.tool_schema import validate_tool_calls

        return validate_tool_calls(data)
    except ValueError as e:
        logger.warning("tool_calls_validation_failed", extra={"error": str(e)})
        return []


def parse_tool_calls_legacy_xml(response_text: str) -> list[dict]:
    """[已废弃] XML 标签解析路径

    仅为向后兼容保留，新代码不应使用。
    将在 v2.0 移除。

    .. deprecated:: P1-2
        请改用 JSON 格式调用工具。
    """
    import warnings

    warnings.warn(
        "XML 工具调用解析已废弃，请使用 JSON 格式",
        DeprecationWarning,
        stacklevel=2,
    )

    tool_pattern = re.compile(r'<tool\s+name="(\w+)">(.*?)</tool>', re.DOTALL)
    matches = tool_pattern.findall(response_text)
    if matches:
        result: list[dict] = []
        param_pattern = re.compile(r'<parameter\s+name="(\w+)">(.*?)</parameter>', re.DOTALL)
        for tool_name, params_text in matches:
            params: dict = {}
            for pm in param_pattern.finditer(params_text):
                params[pm.group(1)] = pm.group(2).strip()
            result.append({"name": tool_name, "params": params})
        return result

    return []
