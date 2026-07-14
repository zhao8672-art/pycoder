"""H2: Agent 工具执行循环 — 从 team_orchestrator.py 迁移

本模块承载 TeamCoordinator 委托使用的 Agent 执行原语：
  - ``_agent_tool_loop`` — LLM ↔ 工具调用循环
  - ``_execute_agent_with_files`` — 带上下文的 Agent 任务执行
  - ``AGENT_SYSTEM_PROMPT`` — Agent 系统提示词
  - ``review_code`` — QA 审查代码

迁移原因：旧 ``TeamOrchestrator`` 上帝对象被拆分后，这些纯函数式工具不应继续
依附于已废弃的类，独立模块使依赖方向清晰、便于复用与测试。
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pycoder.server.chat_bridge import ChatBridge  # noqa: F401

from pycoder.server.log import log
from pycoder.server.routers.files import get_workspace_root
from pycoder.server.services.agent_definitions import AgentRole, AgentTask

# ══════════════════════════════════════════════════════════
# 系统提示词
# ══════════════════════════════════════════════════════════

AGENT_SYSTEM_PROMPT = """你是 PyCoder Agent 执行器。

你的角色: {role_name}
你的职责: {role_description}

## 可用工具
- read_file(path) — 读取文件
- write_file(path, content) — 写入文件
- patch_file(path, search, replace) — 精准替换代码段
- create_file(path, content) — 创建文件
- search_code(query) — 搜索代码
- run_command(command) — 运行命令（白名单内）
- run_terminal(command) — 执行终端命令
- execute_python(code) — 沙箱执行 Python 代码
- list_files(path) — 列出目录
- git_diff(file?) — 查看 Git 差异
- git_status() — 查看 Git 状态
- git_add(path) — Git 暂存文件
- git_commit(message) — Git 提交
- git_push() — Git 推送
- git_branch() — 查看分支
- git_log() — 查看提交历史
- list_agent_configs() — 列出系统 Agent 配置
- install_package(package) — 安装 Python 包
- search_package(query) — 搜索 Python 包
- ensure_tool(tool) — 确保工具已安装
- install_deps(deps) — 批量安装依赖

## 输出格式
调用工具时输出 JSON（禁止使用 XML 标签如 <tool>）:
```json
{{"name": "工具名", "params": {{...}}}}
```

## 示例
读取 main.py 文件:
```json
{{"name": "read_file", "params": {{"path": "main.py"}}}}
```

## 工作流程
1. 分析任务，确定需要调用的工具
2. 一次只调用一个工具，等待结果反馈
3. 根据工具结果决定下一步操作
4. 完成后输出总结（不要 JSON）

## 约束
1. 禁止使用 XML 标签输出（如 <tool>...</tool>）
2. 一次只调用一个工具
3. 工具结果会自动反馈给你
4. 完成后输出总结
5. 写代码时用 ```FILE:path\\ncode```END 格式

## 当前任务
- 标题: {task_title}
- 描述: {task_description}
- 交付物: {task_deliverables}

## 审查反馈
{review_feedback}

## 前面完成的工作
{previous_outputs}
"""


REVIEW_SYSTEM_PROMPT = """你是 PyCoder 代码审查 Agent。

请审查以下代码，输出 JSON 格式的审查结果:
{{"passed":true,"issues":[{{"severity":"high","description":"问题描述","suggestion":"修复建议"}}],"score":85,"summary":"审查总结"}}

评分规则: 满分100，high扣15分/个，medium扣8分/个，low扣3分/个
"""


# ══════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════


def _parse_files_from_response(text: str) -> list[dict]:
    """从 LLM 响应中解析 FILE:...```END 块"""
    files: list[dict] = []
    pattern = re.compile(r"```FILE:(.+?)\n(.*?)```END", re.DOTALL)
    for m in pattern.finditer(text):
        path = m.group(1).strip()
        content = m.group(2)
        files.append({"path": path, "content": content})
    return files


# ══════════════════════════════════════════════════════════
# Agent 工具执行（v2: 真实工具循环）
# ══════════════════════════════════════════════════════════

_TEAM_ALLOWED_COMMANDS = [
    "python",
    "python3",
    "pip",
    "pip3",
    "uv",
    "uvx",
    "git",
    "npm",
    "node",
    "npx",
    "pytest",
    "coverage",
    "ruff",
    "black",
    "isort",
    "mypy",
    "uvicorn",
    "fastapi",
    "flask",
    "streamlit",
    "docker",
    "docker-compose",
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
]

_TEAM_TOOL_TIMEOUT = 60
_MAX_TOOL_ITERATIONS = 10


async def _team_execute_tool(tool_name: str, params: dict, workspace: Path) -> str:
    """团队Agent工具执行 — async，避免 FastAPI 事件循环死锁"""
    from pycoder.server.services.agent_tools import execute_agent_tool

    try:
        return await execute_agent_tool(
            tool_name,
            params,
            workspace,
            timeout=_TEAM_TOOL_TIMEOUT,
            allowed_commands=_TEAM_ALLOWED_COMMANDS,
        )
    except Exception as e:
        return f"❌ 工具执行失败: {e}"


def _team_parse_tool_calls(text: str) -> list[dict]:
    """解析 LLM 响应中的工具调用 — 委托到共享 agent_tools"""
    from pycoder.server.services.agent_tools import parse_tool_calls

    return parse_tool_calls(text)


# ══════════════════════════════════════════════════════════
# Agent 工具循环
# ══════════════════════════════════════════════════════════


async def _agent_tool_loop(
    bridge: ChatBridge,
    task_prompt: str,
    workspace: Path,
    max_iterations: int = _MAX_TOOL_ITERATIONS,
) -> tuple[str, list[str]]:
    """Agent 工具执行循环: LLM ↔ 工具调用"""
    all_files: list[str] = []
    response_text = ""
    prompt = task_prompt

    for _ in range(max_iterations):
        response_text = ""
        async for event in bridge.chat_stream(prompt):
            if event.event_type == "token":
                response_text += event.content
            elif event.event_type == "done":
                response_text = event.content or response_text
                break
            elif event.event_type == "error":
                return f"Agent 错误: {event.content}", all_files

        # 解析工具调用
        tool_calls = _team_parse_tool_calls(response_text)
        if not tool_calls:
            # 检查并提取 FILE:...END 代码块
            files = _parse_files_from_response(response_text)
            for f in files:
                target = (workspace / f["path"]).resolve()
                # M8: 用 is_relative_to 替代字符串前缀匹配
                if target.is_relative_to(workspace):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(f["content"], encoding="utf-8")
                    all_files.append(f["path"])
            break  # 无工具调用 = 任务完成

        # 执行工具 — P2: 并行执行独立工具调用（asyncio.gather 保证返回顺序）
        results: list[str] = []

        async def _exec_one(tc: dict) -> tuple[str, str | None]:
            """执行单个工具调用，返回 (结果文本, 写入文件路径或 None)

            单工具异常被捕获，不影响其他并行工具。
            """
            written = None
            try:
                r = await _team_execute_tool(
                    tc["name"],
                    tc.get("params", {}),
                    workspace,
                )
            except (OSError, ValueError, KeyError, RuntimeError, TypeError, AttributeError) as e:
                r = f"❌ 工具执行失败: {e}"
            if tc["name"] == "write_file":
                written = tc["params"].get("path", "unknown")
            return f"🔧 {tc['name']}: {r[:1500]}", written

        # 多工具并行；单工具时直接 await 避免 gather 开销
        if len(tool_calls) == 1:
            result_text, written = await _exec_one(tool_calls[0])
            results.append(result_text)
            if written:
                all_files.append(written)
        else:
            gathered = await asyncio.gather(
                *(_exec_one(tc) for tc in tool_calls),
                return_exceptions=False,
            )
            for result_text, written in gathered:
                results.append(result_text)
                if written:
                    all_files.append(written)

        # 下一轮: 把工具结果反馈给 LLM
        prompt = (
            "工具执行结果:\n\n"
            + "\n\n".join(results)
            + "\n\n如需继续请用 JSON 调用工具。已完成请输出总结。"
        )

    # 最终再检查一次代码块
    files = _parse_files_from_response(response_text)
    for f in files:
        target = (workspace / f["path"]).resolve()
        # M8: 用 is_relative_to 替代字符串前缀匹配
        if target.is_relative_to(workspace):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f["content"], encoding="utf-8")
            if f["path"] not in all_files:
                all_files.append(f["path"])

    return response_text, all_files


async def _execute_agent_with_files(
    bridge: ChatBridge,
    role: AgentRole,
    task: AgentTask,
    existing_results: dict | None = None,
    work_dir: Path | None = None,
) -> str:
    """带上下文的 Agent 任务执行（构建 prompt → 工具循环 → 写文件）"""
    existing_results = existing_results or {}
    work_dir = work_dir or get_workspace_root()

    # 构建上下文 — 包含前面 Agent 的产出
    prev_outputs = ""
    if existing_results:
        prev_lines = ["\n## 前面完成的产出\n"]
        for tid, code in existing_results.items():
            files = _parse_files_from_response(code)
            if files:
                prev_lines.append(
                    f"\n- 任务 {tid[:8]} 已生成文件: " + ", ".join(f["path"] for f in files)
                )
            else:
                prev_lines.append(f"\n- 任务 {tid[:8]} 产出: {code[:200]}...")
        prev_outputs = "\n".join(prev_lines)

    prompt = AGENT_SYSTEM_PROMPT.format(
        role_name=role.name,
        role_description=role.description,
        task_title=task.title,
        task_description=task.description,
        task_deliverables=", ".join(task.deliverables),
        review_feedback="",
        previous_outputs=prev_outputs,
    )
    bridge.configure(model=role.model)
    bridge.config.system_prompt = prompt
    bridge.config.max_tokens = 16384
    bridge.config.reasoning_effort = "max" if role.model == "deepseek-reasoner" else "medium"

    result, written_files = await _agent_tool_loop(
        bridge,
        f"请完成: {task.description}",
        work_dir,
    )

    if written_files:
        task._files_written = written_files  # type: ignore[attr-defined]
        log.info(
            "agent_wrote_files",
            count=len(written_files),
            task=task.title,
        )

    return result


async def review_code(bridge: ChatBridge, code: str) -> dict:
    """QA Agent 审查代码 — 异常返回有意义的失败"""
    bridge.configure(model="deepseek-chat")
    bridge.config.system_prompt = REVIEW_SYSTEM_PROMPT
    bridge.config.max_tokens = 4096

    result = ""
    async for event in bridge.chat_stream(f"请审查以下代码:\n\n```\n{code[:8000]}\n```"):
        if event.event_type in ("token", "done"):
            result += event.content
        elif event.event_type == "error":
            return {
                "passed": False,
                "issues": [],
                "score": 0,
                "summary": f"审查失败: {event.content}",
            }

    try:
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            cleaned = cleaned.rsplit("```", 1)[0]
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError) as e:
        return {
            "passed": False,
            "issues": [],
            "score": 0,
            "summary": f"解析失败: {e}",
            "raw": result[:500],
        }


__all__ = [
    "AGENT_SYSTEM_PROMPT",
    "REVIEW_SYSTEM_PROMPT",
    "_parse_files_from_response",
    "_team_execute_tool",
    "_team_parse_tool_calls",
    "_agent_tool_loop",
    "_execute_agent_with_files",
    "review_code",
]
