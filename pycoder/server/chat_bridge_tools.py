"""ChatBridge 子模块 — 工具调用分发

从 chat_bridge.py 拆分而来，负责：
- 工具 payload 构建（V1 + V2 能力合并）
- 按任务类别智能裁剪工具
- 工具执行（Docker 沙箱优先 → V2 能力总线 → V1 mcp_tools）
- 文件读取缓存
"""

from __future__ import annotations

import json
import logging
import re

# P2-C: 链路追踪集成
from pycoder.observability.tracing import traced

logger = logging.getLogger(__name__)

# 跳过的工具（不暴露给 LLM）
SKIP_TOOLS: set[str] = {"refresh_extensions", "skills_sync_v2", "system_upgrade"}

# 任务类别 → 允许的工具集（使用 V2 工具名，与 list_builtin_tools 返回一致）
# P2-14: 工具名映射表 — V1 → V2 转换，避免 CATEGORY_TOOL_MAP 中的 V1 名
# 与 V2 引擎返回的实际工具名不匹配导致过滤失败。
_V1_TO_V2_TOOL_NAMES: dict[str, str] = {
    "read_file": "file_read",
    "write_file": "file_write",
    "create_file": "file_write",
    "list_files": "file_list",
    "shell_exec": "shell_run",
    "search_code": "search_code",  # 无变化
    "execute_python": "execute_python",  # 无变化
    "patch_file": "patch_file",
    "install_package": "install_package",
    "file_read": "file_read",
    "file_write": "file_write",
    "file_list": "file_list",
    "shell_run": "shell_run",
    "git_status": "git_status",
    "git_add": "git_add",
    "git_commit": "git_commit",
    "git_diff": "git_diff",
    "git_log": "git_log",
    "git_push": "git_push",
    "git_branch": "git_branch",
    "lsp_diagnostics": "lsp_diagnostics",
}

CATEGORY_TOOL_MAP: dict[str, set[str]] = {
    "code_generation": {
        "file_read",
        "file_write",
        "search_code",
        "execute_python",
        "file_list",
        "shell_run",
    },
    "debugging": {
        "file_read",
        "execute_python",
        "search_code",
        "shell_run",
        "git_diff",
        "git_log",
        "lsp_diagnostics",
    },
    "refactoring": {
        "file_read",
        "file_write",
        "patch_file",
        "search_code",
        "shell_run",
        "git_diff",
    },
    "code_review": {
        "file_read",
        "search_code",
        "git_diff",
        "shell_run",
    },
    "testing": {
        "file_read",
        "file_write",
        "execute_python",
        "shell_run",
        "install_package",
    },
    "git_operations": {
        "git_status",
        "git_add",
        "git_commit",
        "git_diff",
        "git_log",
        "git_push",
        "git_branch",
        "file_read",
    },
}


def _filter_tools_by_category(
    all_tools: list[dict],
    nlu_category: str,
    effective_mode: str,
) -> tuple[list[dict], set[str] | None]:
    """按 NLU 类别智能裁剪工具列表

    Args:
        all_tools: 全部工具列表
        nlu_category: NLU 识别的任务类别
        effective_mode: 当前模式

    Returns:
        (裁剪后工具列表, 允许的工具集 or None)
    """
    allowed: set[str] | None = None
    for cat, tools in CATEGORY_TOOL_MAP.items():
        if cat in nlu_category or cat in effective_mode:
            allowed = tools
            break
    if not allowed:
        return all_tools, None

    full_count = len(all_tools)
    filtered = [t for t in all_tools if t.get("name", "") in allowed]
    logger.debug(
        "tool_selection_filtered before=%d after=%d",
        full_count,
        len(filtered),
    )
    return filtered, allowed


def _build_v1_tools_payload(all_tools: list[dict]) -> list[dict]:
    """将 V1 工具列表转换为 OpenAI 函数调用格式

    Args:
        all_tools: V1 工具列表

    Returns:
        OpenAI 兼容的 tools payload
    """
    payload: list[dict] = []
    for t in all_tools:
        name = t.get("name", "")
        if name in SKIP_TOOLS:
            continue
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        schema = t.get("input_schema", {"type": "object", "properties": {}})
        payload.append(
            {
                "type": "function",
                "function": {
                    "name": safe_name,
                    "description": t.get("description", ""),
                    "parameters": schema,
                },
            }
        )
    return payload


def _build_v2_tools_payload(
    tool_names_set: set[str] | None,
    allowed: set[str] | None,
) -> list[dict]:
    """合并 V2 能力到工具 payload

    Args:
        tool_names_set: 用户指定的工具名集合（None 表示全部）
        allowed: 类别允许的工具集（None 表示不限制）

    Returns:
        V2 能力转换后的 tools payload
    """
    payload: list[dict] = []
    try:
        from pycoder.server.app import get_v2_engine

        v2_engine = get_v2_engine()
        if not v2_engine:
            return payload
        for cap in v2_engine.registry.list_all():
            cap_short = cap.id.split(".")[-1]
            if tool_names_set is not None and cap_short not in tool_names_set:
                continue
            # 按类别过滤 V2 能力
            if allowed:
                if not any(t in cap.id for t in allowed):
                    continue
            payload.append(
                {
                    "type": "function",
                    "function": {
                        "name": cap.id.replace(".", "_"),
                        "description": f"[V2] {cap.description}",
                        "parameters": cap.schema or {"type": "object", "properties": {}},
                    },
                }
            )
    except (ImportError, AttributeError, TypeError, ValueError):
        pass
    return payload


def build_tools_payload(
    *,
    tool_names: list[str] | None = None,
    nlu_cache: dict | None = None,
    task_grade_reasoning: list[str] | None = None,
    effective_mode: str = "tool",
) -> list[dict]:
    """构建工具 payload — V1 + V2 合并，按类别智能裁剪

    Args:
        tool_names: 用户指定的工具名白名单（None=全部）
        nlu_cache: NLU 缓存结果（包含 category）
        task_grade_reasoning: 任务分级 reasoning 列表
        effective_mode: 当前模式

    Returns:
        OpenAI 兼容的 tools payload
    """
    tools_payload: list[dict] = []
    try:
        from pycoder.server.mcp_tools import list_builtin_tools

        all_tools = list_builtin_tools()
        name_set = set(tool_names) if tool_names is not None else None

        # 类别智能裁剪（仅在未指定白名单时启用）
        allowed: set[str] | None = None
        if name_set is not None:
            all_tools = [t for t in all_tools if t.get("name", "") in name_set]
        else:
            nlu_cat = ""
            if nlu_cache:
                nlu_cat = str(nlu_cache.get("category", ""))
            elif task_grade_reasoning:
                nlu_cat = task_grade_reasoning[0] if task_grade_reasoning else ""
            all_tools, allowed = _filter_tools_by_category(
                all_tools,
                nlu_cat,
                effective_mode,
            )

        # V2 能力（按白名单/类别过滤）
        tools_payload.extend(_build_v2_tools_payload(name_set, allowed))
        # V1 工具
        tools_payload.extend(_build_v1_tools_payload(all_tools))
    except (ImportError, RuntimeError) as e:
        logger.warning("tools_injection_failed error=%s", e)

    # 规范化 tools 序列顺序（提升缓存命中率）
    try:
        from pycoder.prompts.cache_rules import canonicalize_tools

        tools_payload = canonicalize_tools(tools_payload)
    except (ImportError, AttributeError):
        pass

    return tools_payload


async def execute_tool_with_sandbox(
    tool_name: str,
    tool_args: dict,
) -> str | None:
    """优先用 Docker 沙箱执行 shell/code 工具

    Args:
        tool_name: 工具名
        tool_args: 工具参数

    Returns:
        成功则返回 JSON 结果字符串，失败返回 None
    """
    if tool_name not in ("shell_exec", "run_command", "execute_python"):
        return None

    code = tool_args.get("command", "") or tool_args.get("code", "")

    # 尝试 Docker 沙箱
    try:
        from pycoder.adapters.docker_sandbox import DockerSandbox

        sandbox = DockerSandbox()
        result = await sandbox.execute(code, timeout=30)
        if result.success:
            return json.dumps(
                {
                    "stdout": result.stdout[:2000],
                    "stderr": result.stderr[:500],
                    "sandbox": "docker",
                    "exit_code": result.exit_code,
                },
                ensure_ascii=False,
                indent=2,
            )
    except (ImportError, RuntimeError, ValueError, TypeError, OSError):
        pass

    # 降级到子进程沙箱
    try:
        from pycoder.adapters.subprocess_sandbox import SubprocessSandbox

        sandbox = SubprocessSandbox()
        result = await sandbox.execute(code, timeout=30)
        if result.success:
            return json.dumps(
                {
                    "stdout": result.stdout[:2000],
                    "stderr": result.stderr[:500],
                    "sandbox": "subprocess",
                    "exit_code": result.exit_code,
                },
                ensure_ascii=False,
                indent=2,
            )
    except (ImportError, RuntimeError, ValueError, TypeError, OSError):
        pass

    return None


async def execute_tool_via_v2(tool_name: str, tool_args: dict) -> str | None:
    """通过 V2 能力总线执行工具

    Args:
        tool_name: 工具名
        tool_args: 工具参数

    Returns:
        成功返回 JSON 结果字符串，能力未找到返回 None
    """
    try:
        from pycoder.server.app import get_v2_engine

        v2_engine = get_v2_engine()
        if not v2_engine:
            return None

        cap_id = tool_name.replace("_", ".")
        cap_result = await v2_engine.call(cap_id, tool_args, caller="chatbridge")
        if cap_result.success:
            result_str = json.dumps(
                cap_result.data if cap_result.data else {"ok": True},
                ensure_ascii=False,
                indent=2,
            )
            max_result_len = 8000 if tool_name == "list_agent_configs" else 3000
            return result_str[:max_result_len]
        if cap_result.error_code != "NOT_FOUND":
            return json.dumps({"error": cap_result.error}, ensure_ascii=False)
    except (AttributeError, TypeError, ValueError):
        pass
    return None


async def execute_tool_via_v1(tool_name: str, tool_args: dict) -> str:
    """通过 V1 mcp_tools 执行工具

    Args:
        tool_name: 工具名
        tool_args: 工具参数

    Returns:
        JSON 结果字符串（成功或失败）
    """
    from pycoder.server.mcp_tools import call_builtin_tool

    result = await call_builtin_tool(tool_name, tool_args)
    if result.success:
        result_str = json.dumps(result.output, ensure_ascii=False, indent=2)
        max_result_len = 8000 if tool_name == "list_agent_configs" else 3000
        return result_str[:max_result_len]
    return json.dumps({"error": result.error}, ensure_ascii=False)


@traced("tool.execute_call")
async def execute_tool_call(tool_name: str, tool_args: dict) -> str:
    """工具调用分发主入口 — Docker沙箱 → V2 能力总线 → V1 mcp_tools

    Args:
        tool_name: 工具名
        tool_args: 工具参数

    Returns:
        JSON 结果字符串
    """
    # 1. Docker/Subprocess 沙箱优先（shell_exec/execute_python）
    result = await execute_tool_with_sandbox(tool_name, tool_args)
    if result is not None:
        return result

    # 2. V2 能力总线
    result = await execute_tool_via_v2(tool_name, tool_args)
    if result is not None:
        return result

    # 3. V1 mcp_tools 兜底
    try:
        return await execute_tool_via_v1(tool_name, tool_args)
    except Exception as e:
        return json.dumps({"error": str(e)[:500]}, ensure_ascii=False)


def cache_file_read(
    read_file_cache: dict[str, str],
    tool_name: str,
    tool_args: dict,
    result_str: str,
) -> None:
    """成功读取文件后缓存内容（避免重复读取）

    Args:
        read_file_cache: 文件读取缓存 dict（会就地修改）
        tool_name: 工具名
        tool_args: 工具参数
        result_str: 工具返回结果字符串
    """
    if tool_name != "file_read":
        return
    try:
        parsed = json.loads(result_str)
        content = parsed.get("content", "") or parsed.get("data", {}).get("content", "")
        file_path = parsed.get("path", "") or tool_args.get("path", "")
        if content and file_path:
            read_file_cache[file_path] = content[:3000]
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
        pass


def get_cached_file_read(
    read_file_cache: dict[str, str],
    tool_name: str,
    tool_args: dict,
) -> str | None:
    """获取缓存的文件读取结果

    Returns:
        缓存的 JSON 结果字符串，未命中返回 None
    """
    if tool_name != "file_read":
        return None
    file_path = tool_args.get("path", "")
    if not file_path or file_path not in read_file_cache:
        return None
    return json.dumps(
        {
            "content": read_file_cache[file_path][:2000],
            "(已缓存)": True,
            "path": file_path,
        },
        ensure_ascii=False,
        indent=2,
    )


__all__ = [
    "SKIP_TOOLS",
    "CATEGORY_TOOL_MAP",
    "build_tools_payload",
    "execute_tool_call",
    "execute_tool_with_sandbox",
    "execute_tool_via_v2",
    "execute_tool_via_v1",
    "cache_file_read",
    "get_cached_file_read",
]
