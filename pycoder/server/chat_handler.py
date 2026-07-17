"""聊天处理器：请求/响应模型、模型路由、流式聊天。"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from pathlib import Path

from pydantic import BaseModel, Field

from pycoder.providers.auth import get_model_manager
from pycoder.providers.setup_wizard import get_api_key
from pycoder.server.chat_bridge import ChatBridge
from pycoder.server.session_store import get_session_store

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str = Field(..., description="User message", min_length=1)
    session_id: str | None = Field(None)
    model: str = Field("auto")
    stream: bool = Field(False)
    files: list[str] = Field(default_factory=list)
    system_prompt: str | None = Field(None)
    hermes: bool = Field(False, description="Enable Hermes structured task mode")
    agent_mode: bool = Field(False, description="Enable Agent team orchestration mode")


class ChatResponse(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    role: str = "assistant"
    content: str
    model: str
    usage: dict = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)


def _resolve_model(requested: str) -> str:
    """Resolve model name from user input."""
    if requested and requested != "auto":
        return requested
    return _get_effective_model(requested)


def _get_effective_model(requested: str | None = None) -> str:
    """Get the effective model to use."""
    if requested and requested != "auto":
        return requested
    try:
        mgr = get_model_manager()
        try:
            model, _ = mgr.recommend(task_type="coding")
        except TypeError:
            model, _ = mgr.recommend()
        return model or "deepseek-chat"
    except (ValueError, RuntimeError, AttributeError) as e:
        logger.warning("model_recommend_failed", extra={"error": str(e)})
        return "deepseek-chat"


def _get_api_key_for_model(model: str) -> str:
    """获取模型对应的 API Key（支持所有模型，无硬编码前缀限制）"""
    try:
        from pycoder.server.chat_bridge import _detect_provider

        mgr = get_model_manager()
        provider = _detect_provider(model)
        key = mgr.get_key(provider) or get_api_key(provider) or ""
        if key:
            return key
        # 兜底: 从任何已检测到的 Key 中取第一个
        all_keys = mgr.get_all_keys()
        if all_keys:
            return next(iter(all_keys.values()))
        return os.environ.get("DEEPSEEK_API_KEY", "")
    except (ValueError, KeyError, AttributeError, ImportError) as e:
        logger.warning("api_key_lookup_failed", extra={"model": model, "error": str(e)})
        return os.environ.get("DEEPSEEK_API_KEY", "")


def _read_file_head(path: str, max_chars: int = 2000) -> str:
    """读取文件头部 — max_chars=0 时完整读取，>0 时分块 + 元数据"""
    try:
        with open(path, encoding="utf-8") as f:
            if max_chars == 0:
                return f.read()
            content = f.read(max_chars)
            peek = f.read(100)
            if peek:
                total_size = f.tell()
                content += (
                    f"\n\n...(文件过大，仅显示前 {len(content)} 字符。"
                    f" 总大小约 {total_size} 字符。"
                    f" 使用 max_chars=0 读取完整文件)"
                )
            return content
    except (OSError, UnicodeDecodeError):
        return ""


def _build_context_prompt(files: list[str]) -> str:
    """从 files 参数构建上下文提示。"""
    if not files:
        return ""
    context_lines = ["## 当前上下文"]
    for fpath in files[:3]:
        p = Path(fpath)
        content = _read_file_head(fpath, 2000)
        if content:
            context_lines.append(f"### {p.name}")
            context_lines.append(f"```\n{content}\n```")
    return "\n\n".join(context_lines) if len(context_lines) > 1 else ""


def _try_write_code_files(content: str):
    """
    FIX #3: 从 AI 输出中解析代码块并写入工作区磁盘

    支持格式:
    1. ```python:path/to/file.py\ncode\n```
    2. ```FILE:path/to/file.py\ncode\n```END
    3. ```python\ncode\n``` (无路径，不写入)
    4. [WRITE path/to/file.py] 标记 + 紧跟代码块
    5. 自然格式: 文件路径注释 + 代码块 (如 # file: app.py)
    """
    if not content:
        return

    from pycoder.server.routers.files import get_workspace_root

    work_dir = get_workspace_root()
    wrote_any = False

    # 模式1: ```FILE:path```END 块
    for m in re.finditer(r"```FILE:(.+?)\n(.*?)```END", content, re.DOTALL):
        path = m.group(1).strip()
        code = m.group(2)
        _write_file_safe(work_dir, path, code)
        wrote_any = True

    # 模式2: ```语言:路径\ncode\n``` (如 ```python:app.py)
    for m in re.finditer(r"```(\w+):(\S+?\.\w+)\n(.*?)```", content, re.DOTALL):
        path = m.group(2).strip()
        code = m.group(3)
        _write_file_safe(work_dir, path, code)
        wrote_any = True

    # 模式3: 单行文件创建标记: `[WRITE path/to/file.py]`
    for m in re.finditer(r"\[WRITE\s+(\S+?\.\w+)\]", content):
        path = m.group(1).strip()
        next_block = re.search(
            r"\[WRITE\s+" + re.escape(path) + r"\]\s*\n\s*```.*?\n(.*?)```",
            content,
            re.DOTALL,
        )
        if next_block:
            _write_file_safe(work_dir, path, next_block.group(1))
            wrote_any = True

    # 模式4: 自然格式 — 文件名注释行 + 紧跟的代码块
    # 如: # === app.py === 或 // main.ts 或 # file: models/user.py
    for m in re.finditer(
        r"(?:#\s*(?:file|FILE)?[=: ]*\s*(\S+\.\w+)|//\s*(\S+\.\w+))\s*\n\s*```(\w+)?\n(.*?)```",
        content,
        re.DOTALL,
    ):
        path = m.group(1) or m.group(2)
        code = m.group(4)
        if path and code:
            _write_file_safe(work_dir, path.strip(), code)
            wrote_any = True

    # 模式5: 自然格式 — markdown 标题行含文件名
    for m in re.finditer(
        r"#{2,4}\s+[创建|生成|文件].*?[：:]\s*`?(\S+\.\w+)`?\s*\n\s*```(\w+)?\n(.*?)```",
        content,
        re.DOTALL,
    ):
        path = m.group(1)
        code = m.group(3)
        if path and code:
            _write_file_safe(work_dir, path.strip(), code)
            wrote_any = True

    if wrote_any:
        from pycoder.server.log import log

        log.info("auto_write_files_complete", workspace=str(work_dir))


async def _execute_xml_tool_calls(content: str) -> tuple[str, list[dict]]:
    """解析 AI 回复中的 XML 格式工具调用并执行（向后兼容回退）

    对于不支持 OpenAI function calling 的模型，AI 可能输出 XML 标签：
        <read_file>
        <path>.gitignore</path>
        </read_file>

    本函数检测 <工具名>...</工具名> 标签，执行工具，并从内容中剥离标签。
    工具结果以格式化文本追加到回复末尾，供用户查看。

    Returns:
        (cleaned_content, tool_results): 清理后的内容和工具结果列表
    """
    from pycoder.server.log import log

    pattern = re.compile(r"<(\w+)>\s*(.*?)\s*</\1>", re.DOTALL)
    cleaned = content
    tool_results: list[dict] = []

    for m in pattern.finditer(content):
        tool_name = m.group(1)
        inner = m.group(2).strip()

        # 跳过非工具标签
        if tool_name in (
            "code",
            "thinking",
            "reasoning",
            "thought",
            "file",
            "summary",
            "result",
            "output",
            "response",
            "answer",
            "WRITE",
            "write",
            "python",
            "bash",
            "json",
            "xml",
            "html",
        ):
            continue

        # 提取子标签参数
        args: dict = {}
        param_pattern = re.compile(r"<(\w+)>\s*(.*?)\s*</\1>", re.DOTALL)
        for pm in param_pattern.finditer(inner):
            key = pm.group(1)
            val = pm.group(2).strip()
            try:
                args[key] = json.loads(val)
            except (json.JSONDecodeError, ValueError):
                args[key] = val

        if not args:
            try:
                parsed = json.loads(inner)
                if isinstance(parsed, dict):
                    args = parsed
            except (json.JSONDecodeError, ValueError):
                args = {"content": inner}

        log.info("xml_tool_call_detected", tool=tool_name, args=str(args)[:200])

        # 异步执行工具
        try:
            from pycoder.server.mcp_tools import call_builtin_tool

            result = await call_builtin_tool(tool_name, args)

            tool_results.append(
                {
                    "tool": tool_name,
                    "args": args,
                    "success": result.success,
                    "output": result.output if result.success else result.error,
                }
            )

            # 从内容中剥离 XML 标签
            cleaned = cleaned.replace(m.group(0), "")

            log.info(
                "xml_tool_call_result",
                tool=tool_name,
                success=result.success,
                output_preview=str(result.output)[:200] if result.success else result.error[:200],
            )
        except Exception as e:
            log.warning("xml_tool_call_failed", tool=tool_name, error=str(e)[:200])
            cleaned = cleaned.replace(m.group(0), f"[{tool_name} 调用失败: {str(e)[:100]}]")

    # 清理多余空行
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    return cleaned, tool_results


def _write_file_safe(work_dir: Path, rel_path: str, code: str):
    """安全写入文件（路径越界检查）"""
    target = (work_dir / rel_path).resolve()
    # M8: 用 is_relative_to 替代字符串前缀匹配
    if target.is_relative_to(work_dir):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(code, encoding="utf-8")
        from pycoder.server.log import log

        log.info("auto_write_file", path=rel_path, size=len(code))


async def _run_chat_stream(
    session_id: str | None,
    message: str,
    model: str,
    system_prompt: str | None = None,
    files: list[str] | None = None,
    hermes: bool = False,
    ws: object | None = None,
    reasoning_effort: str = "medium",
    enable_cache: bool = True,
    agent_mode: bool = False,
):
    """通过 ChatBridge 流式聊天，支持可选的 Hermes 结构化模式。"""
    api_key = _get_api_key_for_model(model)
    if not api_key:
        yield {"type": "error", "message": "No API Key configured"}
        return

    # H4: 入口成本熔断预检 — 覆盖 agent/hermes 路径，避免历史/上下文加载后才发现超限
    try:
        from pycoder.server.services.cost_control import get_cost_controller

        estimated = len(message) // 3 + 500  # 粗估：每 3 字符约 1 token + 系统开销
        ok, reason = get_cost_controller().check_before_call(estimated)
        if not ok:
            yield {"type": "error", "message": f"成本超限: {reason}"}
            return
    except (ImportError, RuntimeError, ValueError, TypeError) as e:
        logger.warning("cost_precheck_failed", extra={"error": str(e)})

    # ── V2: 安全审计追踪（记录每条聊天请求）──
    audit_trace_id = str(uuid.uuid4())
    try:
        from pycoder.server.app import get_v2_engine

        v2_engine = get_v2_engine()
        if v2_engine:
            from pycoder.safety.audit import AuditRecord

            v2_engine.audit.log(
                AuditRecord(
                    trace_id=audit_trace_id,
                    capability_id="chat.send_message",
                    params_summary=message[:200],
                    permission_level=0,
                    decision="auto_allow",
                    user_confirmed=False,
                    success=True,
                    session_id=session_id or "",
                    caller="user",
                )
            )
    except (ImportError, AttributeError, TypeError, ValueError) as e:
        logger.debug("audit_log_failed", extra={"error": str(e)})

    bridge = ChatBridge()
    bridge.configure(model=model, api_key=api_key)
    if system_prompt:
        bridge.config.system_prompt = system_prompt
    else:
        # ReAct 模式默认系统提示词（含报告铁律）
        bridge.config.system_prompt = (
            "你是 PyCoder，一个专业的 AI 编程助手。\n\n"
            "## 核心原则\n"
            "1. **先理解再行动**: 仔细分析用户需求后再决定如何回应\n"
            "2. **按需使用工具**: 简单对话无需工具，直接回复；需要操作代码/文件时才调用工具\n"
            "3. **简洁高效**: 每轮工具调用后检查结果，确认足够即停止，不重复无用操作\n"
            "4. **ReAct 工作流**: 思考(分析需求)→ 行动(调用工具)→ 观察(检查结果)→ 反思(是否需要继续)\n\n"
            "## 🔴 铁律：必须输出报告（违反即为失败）\n"
            "**每次回复必须包含完整的报告**，格式如下：\n"
            "```\n"
            "📋 任务报告\n"
            "├─ 用户需求: （一句话概括）\n"
            "├─ 执行步骤: （列出做了什么）\n"
            "├─ 完成状态: ✅已完成 / 🔄进行中\n"
            "├─ 产出物: （创建/修改了哪些文件，路径列表）\n"
            "└─ 后续建议: （如有）\n"
            "```\n"
            "**长任务阶段报告铁律**：\n"
            "- 如果任务需要多步操作，**每完成一步立即输出一份阶段报告**\n"
            "- 阶段报告格式：`📌 阶段 N/N: [步骤名称] — ✅ 完成 (简要描述)`\n"
            "- 所有步骤完成后，输出最终完整报告\n"
            "- **绝对不允许**：做完所有操作后才一次性输出结果\n\n"
            "## 何时使用工具\n"
            "- 需要读取/写入/搜索项目文件\n"
            "- 需要运行代码或命令\n"
            "- 需要查询 Git 状态\n"
            "- 需要搜索网页获取最新信息\n\n"
            "## 何时直接回复\n"
            "- 解释概念、技术问题\n"
            "- 代码审查建议（不需读取文件时）\n"
            "- 最佳实践讨论\n"
            "- 一般性聊天和帮助请求\n"
        )
    bridge.config.reasoning_effort = reasoning_effort
    bridge.config.enable_thinking = True
    bridge.config.enable_cache = enable_cache

    # ── P2-2: 自进化经验注入（加载历史成功模式）──
    try:
        from pycoder.capabilities.self_evo.live import get_live_learner
        _learner = get_live_learner()
        _feedback = await getattr(_learner, "apply_feedback", lambda: "")()
        if _feedback:
            if bridge.config.system_prompt:
                bridge.config.system_prompt += "\n\n" + _feedback
            else:
                bridge.config.system_prompt = _feedback
    except (ImportError, RuntimeError, ValueError, TypeError):
        pass

    store = get_session_store()

    # FIX #2: 加载最近几十条消息作为跨会话上下文
    all_history_msgs = []
    if session_id and store.get_session(session_id):
        try:
            for msg in store.get_messages(session_id, limit=100):
                bridge.add_message(msg.role, msg.content)
                all_history_msgs.append(msg)
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning("history_load_failed", extra={"session_id": session_id, "error": str(e)})

    # FIX #4: 自动生成会话标题（从第一条用户消息）
    session = store.get_session(session_id) if session_id else None
    if session and not session.title and all_history_msgs:
        first_user = next((m for m in all_history_msgs if m.role == "user"), None)
        if first_user:
            title = first_user.content[:60].replace("\n", " ").strip()
            store.update_session(session_id, title=title)

    # FIX #5: 注入工作区上下文（项目结构快照）
    context_prompt = _build_context_prompt(files or [])
    if not files:
        try:
            from pycoder.server.routers.files import get_workspace_root

            work_dir = get_workspace_root()
            key_files = [
                ".gitignore",
                "pyproject.toml",
                "package.json",
                "README.md",
                "requirements.txt",
            ]
            found = []
            for kf in key_files:
                p = work_dir / kf
                if p.exists():
                    found.append(kf)
            if found:
                context_prompt = (
                    "\n\n当前项目工作区关键文件: " + ", ".join(found) + "\n" + context_prompt
                )
        except (OSError, ValueError) as e:
            logger.warning("workspace_files_lookup_failed", extra={"error": str(e)})

    if context_prompt:
        bridge.add_message(
            "user", f"参考以下文件内容回答问题：\n\n{context_prompt}\n\n用户问题: {message}"
        )

    # 保存用户消息（所有模式通用）
    try:
        store.add_message(session_id, "user", message)
    except (OSError, ValueError, RuntimeError) as e:
        logger.warning(
            "save_user_message_failed", extra={"session_id": session_id, "error": str(e)}
        )

    # FIX #3: 为 agent/hermes 模式注入代码写入指令
    if hermes or agent_mode:
        yield {"type": "agent_status", "message": "🤖 Agent 模式已激活"}

        from pycoder.server.services.agent_orchestrator import agent_chat_stream as agent_stream

        # 构建历史上下文传递给 agent
        history_context = ""
        if all_history_msgs:
            context_lines = []
            for m in all_history_msgs[-20:]:
                role_label = "用户" if m.role == "user" else "助手"
                context_lines.append(f"{role_label}: {str(m.content)[:500]}")
            history_context = "\n".join(context_lines)

        agent_has_result = False
        async for event in agent_stream(
            message,
            model=model,
            system_prompt=system_prompt,
            api_key=api_key,
            context=history_context,
        ):
            if event.get("type") == "agent_result" or event.get("type") == "done":
                agent_has_result = True
                content = event.get("content") or event.get("summary", "")
                if content:
                    _try_write_code_files(content)
                # 保存 AI 回复
                try:
                    store.add_message(session_id, "assistant", content or message)
                except (OSError, ValueError, RuntimeError) as e:
                    logger.warning(
                        "save_assistant_message_failed",
                        extra={"session_id": session_id, "error": str(e)},
                    )
                yield {"type": "done", "content": content}
                return
            elif event.get("type") == "error":
                yield event
                return
            elif event.get("type") == "strategy":
                continue
            yield event

        # Agent 结束但没有结果事件（超时/中断）
        if not agent_has_result:
            yield {"type": "done", "content": ""}
        return

    # Normal chat mode (with smart intent routing)
    chunk_index = 0
    final_content = ""
    try:
        async for event in bridge.chat_stream(message, mode="auto"):
            if event.event_type == "token":
                chunk_index += 1
                final_content += event.content
                yield {
                    "type": "token",
                    "data": event.content,
                    "content": event.content,
                    "index": chunk_index,
                }
            elif event.event_type == "reasoning":
                yield {"type": "reasoning", "data": event.content, "content": event.content}
            elif event.event_type == "done":
                # FIX #3: 对话结束时尝试解析并写入代码文件
                final = event.content or final_content
                _try_write_code_files(final)
                # XML 工具调用回退（对于不支持 function calling 的模型）
                final, tool_results = await _execute_xml_tool_calls(final)
                if tool_results:
                    for tr in tool_results:
                        status = "✅" if tr["success"] else "❌"
                        result_str = json.dumps(tr["output"], ensure_ascii=False, indent=2)[:2000]
                        final += f"\n\n---\n{status} **{tr['tool']}** 执行结果:\n```json\n{result_str}\n```"
                # 保存 AI 回复
                try:
                    store.add_message(session_id, "assistant", final)
                except (OSError, ValueError, RuntimeError) as e:
                    logger.warning(
                        "save_assistant_message_failed",
                        extra={"session_id": session_id, "error": str(e)},
                    )
                yield {"type": "done", "content": final, "usage": event.usage}
            elif event.event_type == "error":
                yield {"type": "error", "message": event.content}
                return
    finally:
        await bridge.close()
