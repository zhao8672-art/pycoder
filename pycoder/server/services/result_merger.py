"""
结果归集器 — 去重整合多模式输出，按固定结构格式化
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ModeResult:
    mode: str
    success: bool
    content: str = ""
    error: str = ""
    duration_ms: int = 0
    retries: int = 0


def merge_results(
    raw_input: str,
    surface_text: str,
    core_need: str,
    ambiguity: str,
    beautified: str,
    results: list[ModeResult],
) -> str:
    """归集整合所有模式结果。

    修复：不再将内部调度标记（【原始用户输入】等）暴露给用户。
    这些标记仅用于内部日志，用户看到的是干净的 AI 回复内容。
    """
    import re

    # ── 提取 AI 实际回复内容（去除内部标记）──
    success_results = [r for r in results if r.success]
    if not success_results:
        if results:
            return f"执行失败。错误: {results[0].error}"
        return "无可用结果。"

    raw_content = success_results[0].content

    # 去除 LLM 输出中可能残留的【标记】块
    marker_patterns = [
        r"【原始用户输入】.*?(?=【|$)",
        r"【分层意图解析】.*?(?=【|$)",
        r"【美化后标准化任务指令】.*?(?=【|$)",
        r"【本次[^】]*调度[^】]*模式[^】]*】.*?(?=【|$)",
        r"【多模式执行整合输出结果】",
        r"【系统故障处理方案】.*?(?=【|$)",
        r"【高危操作风险提示】.*?(?=【|$)",
        r"\[原始用户输入\].*?(?=\[|$)",
        r"\[分层意图解析\].*?(?=\[|$)",
    ]
    clean = raw_content
    for pat in marker_patterns:
        clean = re.sub(pat, "", clean, flags=re.DOTALL)
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()

    # ── 附加执行摘要 ──
    modes_summary = "、".join(f"{r.mode}({'✅' if r.success else '❌'})" for r in results)

    # 故障处理
    failed = [r for r in results if not r.success]
    footer = f"\n\n---\n🔧 调度模式: {modes_summary}"
    if failed:
        issues_lines = [f"- {r.mode}: {r.error} (耗时{r.duration_ms}ms)" for r in failed]
        footer += (
            "\n\n⚠️ 故障处理:\n" + "\n".join(issues_lines) + "\n\n"
            "建议操作:\n"
            "1. 检查网络连接是否正常\n"
            "2. 验证 API Key 是否有效\n"
            "3. 查看后端日志 ~/.pycoder/*.log\n"
            "4. 重试或切换到其他模型"
        )

    return clean + footer


# 便捷导出
__all__ = ["merge_results", "ModeResult"]
