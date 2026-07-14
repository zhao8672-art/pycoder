"""
统一 Agent 执行循环 — 一个循环驱动所有策略

特性:
  - 读并行/写串行（来自 AgentOrchestrator）
  - 反思机制每3轮（来自 ReActLoop）
  - 内联代码块自动写入（来自 AutonomousPipeline）
  - 完成信号自动检测（来自 AutonomousPipeline）
  - 统一格式解析（JSON/FILE/ReAct/代码块）
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from pycoder.server.services.agent_parser import parse_response, validate_tool_call
from pycoder.server.services.agent_strategies import AgentStrategy
from pycoder.server.services.agent_tools import execute_agent_tool

logger = logging.getLogger(__name__)

# 写操作工具集合
WRITE_SAFE_TOOLS = {"write_file", "patch_file", "create_file", "overwrite_file"}
WORKSPACE = Path(
    __import__("os").environ.get(
        "PYCODER_WORKSPACE",
        str(Path(__file__).resolve().parents[3]),
    )
)


class UnifiedAgentLoop:
    """统一 Agent 执行循环"""

    def __init__(
        self,
        strategy: AgentStrategy,
        workspace: Path = WORKSPACE,
    ):
        self.strategy = strategy
        self.workspace = workspace
        self._rumination_count = 0

    async def chat_stream(
        self,
        message: str,
        bridge,  # LLMProvider (BridgeLLMProvider) — 提供 stream()/add_message()/configure()
        context: str = "",
    ) -> AsyncIterator[dict]:
        """
        统一执行流

        Yields:
            {"type": "status", "status": "analyzing"|"executing"|"thinking"}
            {"type": "tool_result", "tool_name": str, "result": str}
            {"type": "agent_result", "status": "done", "summary": str, ...}
            {"type": "error", "message": str}
        """
        strategy = self.strategy
        max_iterations = strategy.max_iterations
        timeout = strategy.tool_timeout
        all_tool_calls: list[dict] = []
        all_results: list[str] = []
        written_files: list[str] = []

        # 构建系统提示词（注入缓存优化规则）
        system_prompt = strategy.system_prompt
        from pycoder.prompts.cache_rules import inject_cache_rules
        system_prompt = inject_cache_rules(system_prompt, lang="zh")
        if context:
            system_prompt += f"\n\n## 上下文\n{context}"

        bridge.configure(system_prompt=system_prompt, max_tokens=16384)

        yield {"type": "status", "status": "analyzing", "iteration": 0}

        # 构建分析 prompt
        analysis_prompt = f"请分析并完成以下任务:\n\n{message}"
        if strategy.enable_rumination:
            analysis_prompt += "\n\n请先分析需求，再逐步执行。每3步进行一次反思复盘。"

        response_text = ""

        for iteration in range(1, max_iterations + 1):
            yield {
                "type": "status",
                "status": "thinking",
                "iteration": iteration,
                "max": max_iterations,
            }

            # 1. LLM 调用
            prompt = (
                analysis_prompt
                if iteration == 1
                else "以上是工具执行结果。如需继续请输出 JSON 工具调用。" "已完成请直接输出总结。"
            )
            # 每3步添加反思提示
            if strategy.enable_rumination and iteration > 1 and iteration % 3 == 0:
                self._rumination_count += 1
                prompt += (
                    f"\n\n---\n### 反思复盘（第{self._rumination_count}次）\n"
                    "1. 当前进展是否对齐原始目标？\n"
                    "2. 最近几步是否有冗余或错误？\n"
                    "3. 有没有更简单的替代方案？\n"
                    "请基于以上反思继续执行或调整策略。"
                )

            response_text = ""
            try:
                async for event in bridge.stream(prompt):
                    if event.event_type == "token":
                        response_text += event.content
                    elif event.event_type == "error":
                        yield {"type": "error", "message": event.content}
                        return
                    elif event.event_type == "done":
                        response_text = event.content or response_text
            except Exception as e:
                yield {"type": "error", "message": f"LLM 调用失败: {e}"}
                return

            if not response_text:
                # LLM 返回空响应 — 向桥接注入提示，避免下一轮再次空返回
                bridge.add_message(
                    "assistant",
                    "（注意：上一轮 LLM 返回了空响应，请尝试用不同方式完成任务或确认是否已完成。）",
                )
                logger.warning(
                    "agent_loop_empty_response iteration=%d/%d",
                    iteration,
                    max_iterations,
                )
                continue

            # 2. 统一解析
            parsed = parse_response(response_text)

            # 3. 完成信号检测
            if parsed.completion:
                yield {
                    "type": "agent_result",
                    "status": "done",
                    "summary": parsed.summary or response_text[:500],
                    "iterations": iteration,
                    "tool_count": len(all_tool_calls),
                    "files_written": written_files,
                }
                return

            # 4. 处理代码块（自动写入文件）
            for fblock in parsed.file_blocks:
                try:
                    target = (self.workspace / fblock["path"]).resolve()
                    if target.is_relative_to(self.workspace):
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(fblock["content"], encoding="utf-8")
                        written_files.append(fblock["path"])
                        logger.info(
                            "agent_wrote_file path=%s size=%d",
                            fblock["path"],
                            len(fblock["content"]),
                        )
                except (OSError, ValueError) as e:
                    logger.warning(
                        "agent_write_failed path=%s error=%s",
                        fblock["path"],
                        e,
                    )

            # 5. 处理工具调用
            if not parsed.tool_calls:
                # 没有工具调用也没有代码块，检查是否应继续
                if parsed.file_blocks:
                    # 写了文件但没有工具调用，继续下一轮
                    continue
                # 既没有工具也没有代码块，视为完成
                yield {
                    "type": "agent_result",
                    "status": "done",
                    "summary": response_text[:500],
                    "iterations": iteration,
                    "tool_count": len(all_tool_calls),
                    "files_written": written_files,
                }
                return

            # 6. 执行工具
            yield {
                "type": "status",
                "status": "executing",
                "iteration": iteration,
                "tool_calls": [tc["name"] for tc in parsed.tool_calls],
            }

            # 区分读写操作
            writers = [tc for tc in parsed.tool_calls if tc["name"] in WRITE_SAFE_TOOLS]
            readers = [tc for tc in parsed.tool_calls if tc["name"] not in WRITE_SAFE_TOOLS]

            # 写操作：严格串行
            for tc in writers:
                ok, err = validate_tool_call(tc)
                if not ok:
                    yield {"type": "tool_result", "tool_name": tc["name"], "result": f"❌ {err}"}
                    continue

                all_tool_calls.append(tc)
                try:
                    result = await execute_agent_tool(
                        tc["name"],
                        tc.get("params", {}),
                        self.workspace,
                        timeout=timeout,
                    )
                    all_results.append(str(result))
                    yield {
                        "type": "tool_result",
                        "tool_name": tc["name"],
                        "result": str(result)[:500],
                    }
                    # 更新桥接消息上下文
                    bridge.add_message(
                        "assistant",
                        f"工具 {tc['name']} 结果:\n{str(result)[:1000]}",
                    )
                except Exception as e:
                    err_msg = f"❌ 工具执行失败: {e}"
                    yield {"type": "tool_result", "tool_name": tc["name"], "result": err_msg}
                    bridge.add_message("assistant", err_msg)

            # 读操作：并行执行
            if readers:

                async def _execute_one(tc: dict) -> tuple[str, str | None]:
                    ok, err = validate_tool_call(tc)
                    if not ok:
                        return tc["name"], f"❌ {err}"
                    try:
                        r = await execute_agent_tool(
                            tc["name"],
                            tc.get("params", {}),
                            self.workspace,
                            timeout=timeout,
                        )
                        return tc["name"], str(r)
                    except Exception as e:
                        return tc["name"], f"❌ 工具执行失败: {e}"

                read_tasks = [_execute_one(tc) for tc in readers]
                for coro in asyncio.as_completed(read_tasks):
                    tool_name, result = await coro
                    all_tool_calls.append({"name": tool_name, "params": {}})
                    all_results.append(result or "")
                    # M9: list_agent_configs 等大型列表需要更大的截断上限
                    result_str = result or ""
                    max_preview = 2000 if tool_name == "list_agent_configs" else 500
                    max_context = 5000 if tool_name == "list_agent_configs" else 1000
                    yield {
                        "type": "tool_result",
                        "tool_name": tool_name,
                        "result": result_str[:max_preview],
                    }
                    bridge.add_message(
                        "assistant",
                        f"工具 {tool_name} 结果:\n{result_str[:max_context]}",
                    )

        # 达到最大迭代次数
        yield {
            "type": "agent_result",
            "status": "completed",
            "summary": response_text[:500] if response_text else "达到最大迭代次数",
            "iterations": max_iterations,
            "tool_count": len(all_tool_calls),
            "files_written": written_files,
        }
