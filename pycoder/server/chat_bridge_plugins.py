"""ChatBridge 子模块 — 钩子与中间件

从 chat_bridge.py 拆分而来，负责集成各种"非主流程"的可选增强：
- RuminationEngine（反思引擎：事前/事中/事后）
- HallucinationGuard（幻觉抑制）
- LiveLearner（在线自进化）
- TaskGrader（任务难度分级）
- ProjectState（项目状态记录）
- CompositeAnalyzer（五层代码分析）
- AutoFixer（自动修复）
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════


@dataclass
class RuminationResult:
    """反思引擎返回结果"""

    deviation_score: float = 0.0
    correction_msg: str = ""
    should_continue: bool = True


@dataclass
class GuardResult:
    """幻觉抑制验证结果"""

    overall_score: float = 100.0
    recommendations: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.recommendations is None:
            self.recommendations = []


@dataclass
class TaskGrade:
    """任务难度分级结果"""

    level: Any = None
    score: float = 0.0
    max_iterations: int = 5
    temperature: float = 0.7
    reasoning: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.reasoning is None:
            self.reasoning = []


# ══════════════════════════════════════════════════════════
# 任务难度分级
# ══════════════════════════════════════════════════════════


def grade_task_difficulty(
    message: str,
    *,
    context: dict | None = None,
) -> TaskGrade | None:
    """评估任务难度，返回 TaskGrade 或 None（失败时）

    Args:
        message: 用户消息
        context: 项目上下文（files/dependencies/domain 等）

    Returns:
        TaskGrade 实例，或 None（模块不可用时）
    """
    try:
        from pycoder.server.services.task_grader import get_task_grader

        grader = get_task_grader()
        return grader.assess(message, context=context or {})
    except (ImportError, RuntimeError, ValueError, TypeError) as e:
        logger.debug("task_grader_failed error=%s", e)
        return None


# ══════════════════════════════════════════════════════════
# RuminationEngine 反思引擎
# ══════════════════════════════════════════════════════════


async def rumination_pre_execute(tool_name: str, tool_args: dict) -> bool:
    """反思引擎事前检查

    Returns:
        True 表示执行成功（不阻塞主流程），False 表示模块不可用
    """
    try:
        from pycoder.ai.rumination import get_rumination_engine

        engine = get_rumination_engine()
        await engine.pre_execute(tool_name, tool_args)
        return True
    except (ImportError, RuntimeError, ValueError, TypeError):
        return False


async def rumination_mid_execute(
    tool_name: str,
    actual_result: str,
    round_num: int,
) -> RuminationResult:
    """反思引擎事中检查

    Returns:
        RuminationResult（deviation_score=0 表示无需纠正）
    """
    try:
        from pycoder.ai.rumination import get_rumination_engine

        engine = get_rumination_engine()
        result = await engine.mid_execute(
            tool_name=tool_name,
            actual=actual_result,
            round_num=round_num,
        )
        # 严重偏离 → 触发回溯
        if result.deviation_score > 0.7:
            backtrack = await engine.backtrack()
            return RuminationResult(
                deviation_score=result.deviation_score,
                correction_msg=result.correction_msg + "\n" + backtrack.correction_msg,
                should_continue=backtrack.should_continue,
            )
        return RuminationResult(
            deviation_score=result.deviation_score,
            correction_msg=result.correction_msg,
            should_continue=True,
        )
    except (ImportError, RuntimeError, ValueError, TypeError):
        return RuminationResult(
            deviation_score=0.0,
            correction_msg=(
                "🔍 反思: 操作结果是否符合预期？"
                "如有偏差请纠正，如已完成请停止。"
            ),
            should_continue=True,
        )


async def rumination_post_execute(content: str, *, is_tool_mode: bool) -> tuple[str, dict]:
    """反思引擎事后总结

    Args:
        content: AI 最终输出
        is_tool_mode: 是否为工具模式

    Returns:
        (反思摘要字符串, 反思评分 dict)
    """
    try:
        from pycoder.ai.rumination import get_rumination_engine

        engine = get_rumination_engine()
        if is_tool_mode and content:
            await engine.post_execute(content)
        score = engine.score()
        summary = f"反思{score['rounds']}次 质量{score['status']} "
        return summary, score
    except (ImportError, RuntimeError, ValueError, TypeError):
        return "", {}


# ══════════════════════════════════════════════════════════
# HallucinationGuard 幻觉抑制
# ══════════════════════════════════════════════════════════


async def hallucination_validate(
    content: str,
    *,
    context: dict | None = None,
) -> GuardResult | None:
    """幻觉验证

    Args:
        content: 待验证内容
        context: 上下文信息（tool/round/mode 等）

    Returns:
        GuardResult 或 None（模块不可用）
    """
    if not content or len(content) <= 100:
        return None
    try:
        from pycoder.server.services.hallucination_guard import (
            get_hallucination_guard,
        )

        guard = get_hallucination_guard()
        v = await guard.validate(content, context=context or {})
        return GuardResult(
            overall_score=v.overall_score,
            recommendations=list(v.recommendations),
        )
    except (ImportError, RuntimeError, ValueError, TypeError):
        return None


def format_hallucination_warning(score: float, recommendations: list[str]) -> str:
    """格式化幻觉抑制警告"""
    recs = recommendations[:3] if recommendations else []
    return "\n\n⚠️ **可信度评级**: {}/100 | {}\n".format(
        int(score), ", ".join(recs),
    )


def maybe_annotate_tool_result(
    result_str: str,
    *,
    tool_name: str,
    round_num: int,
) -> str:
    """如果工具结果触发幻觉风险，注入警告到结果中

    Returns:
        原结果或带警告的结果字符串
    """
    if len(result_str) <= 100:
        return result_str
    try:
        from pycoder.server.services.hallucination_guard import (
            get_hallucination_guard,
        )
        import asyncio

        guard = get_hallucination_guard()
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 在同步上下文中无法直接 await，留给调用方处理
            return result_str
        v = loop.run_until_complete(
            guard.validate(
                result_str,
                context={"tool": tool_name, "round": round_num + 1},
            )
        )
        if v.overall_score < 50:
            return json.dumps(
                {
                    "data": json.loads(result_str) if result_str.startswith("{") else result_str,
                    "⚠️ 幻觉风险": f"可信度 {v.overall_score}/100",
                    "建议": v.recommendations[:2],
                },
                ensure_ascii=False,
                indent=2,
            )
    except (ImportError, RuntimeError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return result_str


# ══════════════════════════════════════════════════════════
# LiveLearner 在线自进化
# ══════════════════════════════════════════════════════════


async def live_learner_observe(
    task: str,
    *,
    success: bool,
    rounds: int,
    mode: str,
) -> bool:
    """记录任务经验到 LiveLearner

    Returns:
        True 表示记录成功，False 表示模块不可用
    """
    try:
        from pycoder.capabilities.self_evo.live import get_live_learner

        learner = get_live_learner()
        await learner.observe(
            task=task[:200],
            result=dict(success=success, rounds=rounds, mode=mode),
        )
        return True
    except (ImportError, RuntimeError, ValueError, TypeError):
        return False


# ══════════════════════════════════════════════════════════
# ProjectState 项目状态记录
# ══════════════════════════════════════════════════════════


def record_project_error(error_msg: str) -> None:
    """记录项目错误到 ProjectState（失败静默）"""
    try:
        from pycoder.server.services.project_state import get_project_state

        get_project_state().record_error(error_msg)
    except (ImportError, RuntimeError, ValueError, TypeError):
        pass


def record_project_fix_attempt(file_path: str) -> None:
    """记录修复尝试到 ProjectState（失败静默）"""
    try:
        from pycoder.server.services.project_state import get_project_state

        get_project_state().record_fix_attempt(file_path)
    except (ImportError, RuntimeError, ValueError, TypeError):
        pass


def record_project_file_modified(file_path: str) -> None:
    """记录文件修改到 ProjectState（失败静默）"""
    try:
        from pycoder.server.services.project_state import get_project_state

        get_project_state().record_file_modified(file_path)
    except (ImportError, RuntimeError, ValueError, TypeError):
        pass


# ══════════════════════════════════════════════════════════
# 自愈回滚：写入后语法检查 + 测试 + AutoFixer
# ══════════════════════════════════════════════════════════


async def self_heal_after_write(
    file_path: str,
    *,
    yield_event,
) -> None:
    """写入 .py 文件后触发自愈检查

    步骤：
    1. 语法检查（py_compile）
    2. 运行 pytest（如有对应测试文件）
    3. AutoFixer 验证

    Args:
        file_path: 写入的文件路径
        yield_event: 异步生成器的 yield 函数，用于推送 ChatEvent
    """
    if not file_path or not file_path.endswith(".py"):
        return

    # Step 1: 语法检查
    try:
        from pycoder.server.mcp_tools import call_builtin_tool

        exec_result = await call_builtin_tool(
            "execute_python",
            {
                "code": (
                    "import py_compile; "
                    f"py_compile.compile(r'{file_path}', doraise=True); "
                    "print('SYNTAX_OK')"
                ),
            },
        )
        if exec_result.success:
            await yield_event(f"✅ {file_path} 语法 OK\n")
        else:
            err = str(exec_result.output)[:300]
            logger.warning("syntax_error path=%s err=%s", file_path, err[:100])
            await yield_event(
                f"❌ {file_path} 语法错误:\n{err}\n🔧 请立即修复并重新写入\n"
            )
            record_project_error(f"语法错误 {file_path}: {err[:80]}")
            record_project_fix_attempt(file_path)
    except (ImportError, RuntimeError, ValueError, TypeError):
        pass

    # Step 2: 运行 pytest
    import os

    test_path = file_path.replace(".py", "_test.py")
    try:
        if os.path.exists(os.path.join(os.getcwd(), test_path)):
            test_cmd = f"pytest {test_path} -x -q"
        elif os.path.exists(os.path.join(os.getcwd(), "tests")):
            test_cmd = "pytest tests/ -x -q"
        else:
            test_cmd = ""

        if test_cmd:
            from pycoder.server.mcp_tools import call_builtin_tool

            test_result = await call_builtin_tool(
                "shell_run_terminal",
                {"command": test_cmd, "timeout": 30},
            )
            if test_result.success:
                await yield_event(f"✅ 测试通过: {test_cmd}\n")
            else:
                test_err = str(test_result.output)[:300]
                await yield_event(f"⚠️ 测试失败:\n{test_err[:200]}\n")

                # AutoFixer 验证（不自动 LLM 修复）
                try:
                    from pycoder.ai.auto_fixer import AutoFixer

                    fixer = AutoFixer(max_retries=1)
                    fix_result = await fixer.validate_and_fix(
                        file_path, auto_fix=False,
                    )
                    if fix_result.status == "verified":
                        await yield_event("🔧 AutoFixer 验证通过\n")
                    else:
                        await yield_event(
                            f"⚠️ AutoFixer: {fix_result.status}"
                            f" ({fix_result.error_type})\n"
                        )
                except (ImportError, RuntimeError, ValueError, TypeError) as e:
                    logger.debug("autofixer_skip error=%s", e)

            # 更新 ProjectState
            record_project_file_modified(file_path)
    except (ImportError, RuntimeError, ValueError, TypeError):
        pass


async def analyze_after_write(
    file_path: str,
    *,
    yield_event,
) -> None:
    """写入 .py/.js/.ts 文件后触发五层代码分析

    Args:
        file_path: 写入的文件路径
        yield_event: 异步生成器的 yield 函数
    """
    if not file_path or not file_path.endswith((".py", ".js", ".ts")):
        return

    try:
        from pycoder.ai.analysis.composite_analyzer import CompositeAnalyzer

        analyzer = CompositeAnalyzer()
        analysis = analyzer.analyze([file_path])
        if analysis and analysis.issues:
            issues = analysis.issues[:5]
            lines = []
            for issue in issues:
                if hasattr(issue, "line") and hasattr(issue, "message"):
                    lines.append(f"  L{issue.line}: {issue.message}")
            if lines:
                await yield_event(
                    f"🔍 分析 {file_path}: {len(issues)} 问题\n"
                    + "\n".join(lines[:3]) + "\n"
                )
    except (ImportError, RuntimeError, ValueError, TypeError, AttributeError):
        pass


# ══════════════════════════════════════════════════════════
# 可观测性埋点
# ══════════════════════════════════════════════════════════


def record_observability(
    *,
    elapsed_ms: float,
    model: str,
    usage: dict,
) -> None:
    """记录延迟和 token 消耗到可观测性系统（失败静默）"""
    try:
        from pycoder.server.services.observability import (
            get_metrics,
            track_tokens,
        )

        metrics = get_metrics()
        metrics.observe("chat_latency_ms", elapsed_ms, labels={"model": model})
        metrics.increment("chat_requests_total", labels={"model": model})
        if usage:
            track_tokens(
                model,
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
            )
    except (ImportError, RuntimeError, ValueError, TypeError):
        pass


def record_cost_usage(*, usage: dict, model: str) -> None:
    """记录 token 用量到成本控制器（失败静默）"""
    if not usage:
        return
    try:
        from pycoder.server.services.cost_control import get_cost_controller

        get_cost_controller().record_usage(
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            model=model,
        )
    except (ImportError, RuntimeError, ValueError, TypeError) as e:
        logger.warning("cost_record_failed error=%s", e)


def check_cost_budget(*, estimated_tokens: int) -> tuple[bool, str]:
    """成本熔断预检

    Returns:
        (ok, reason) — ok=False 时 reason 描述原因
    """
    try:
        from pycoder.server.services.cost_control import get_cost_controller

        return get_cost_controller().check_before_call(estimated_tokens)
    except (ImportError, RuntimeError, OSError, ValueError, TypeError) as e:
        logger.warning("cost_check_failed error=%s", e)
        return True, ""  # 失败时放行


def mark_provider_key_invalid(provider: str) -> None:
    """401 时标记 Provider Key 永久失效（失败静默）"""
    try:
        from pycoder.providers.auth import get_model_manager

        get_model_manager().mark_key_invalid(provider)
    except (ImportError, RuntimeError, ValueError, TypeError):
        pass


__all__ = [
    "RuminationResult",
    "GuardResult",
    "TaskGrade",
    "grade_task_difficulty",
    "rumination_pre_execute",
    "rumination_mid_execute",
    "rumination_post_execute",
    "hallucination_validate",
    "format_hallucination_warning",
    "maybe_annotate_tool_result",
    "live_learner_observe",
    "record_project_error",
    "record_project_fix_attempt",
    "record_project_file_modified",
    "self_heal_after_write",
    "analyze_after_write",
    "record_observability",
    "record_cost_usage",
    "check_cost_budget",
    "mark_provider_key_invalid",
]
