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
    """归集整合所有模式结果，按用户要求的固定结构输出。

    Args:
        raw_input: 原始用户输入
        surface_text: 表层文字内容
        core_need: 核心真实需求
        ambiguity: 信息缺失/歧义说明
        beautified: 标准化指令
        results: 各模式执行结果

    Returns:
        按固定格式整合的完整回复
    """
    sections: list[str] = []

    # 1. 原始用户输入
    sections.append(f"【原始用户输入】\n{raw_input}")

    # 2. 分层意图解析
    sections.append(
        f"【分层意图解析】\n"
        f"  1. 表层文字内容：{surface_text}\n"
        f"  2. 核心真实需求：{core_need}\n"
        f"  3. 信息缺失/歧义说明：{ambiguity or '无'}"
    )

    # 3. 美化后标准化任务指令
    sections.append(f"【美化后标准化任务指令】\n{beautified or raw_input}")

    # 4. 自动调度的模式列表
    modes_desc_parts = []
    for r in results:
        status = "✅ 成功" if r.success else "❌ 失败"
        line = f"- 模式: {r.mode} | 状态: {status} | 耗时: {r.duration_ms}ms"
        if r.retries > 0:
            line += f" | 重试: {r.retries}次"
        modes_desc_parts.append(line)
    modes_header = "【本次自动调度的PyCoder工作模式列表+对应子任务】"
    sections.append(modes_header + "\n" + "\n".join(modes_desc_parts))

    # 5. 执行整合输出
    success_results = [r for r in results if r.success]
    if success_results:
        sections.append(
            f"【多模式执行整合输出结果】\n{success_results[0].content}"
        )
    elif results:
        sections.append(
            f"【多模式执行整合输出结果】\n"
            f"执行失败。错误: {results[0].error}"
        )
    else:
        sections.append("【多模式执行整合输出结果】\n无可用结果。")

    # 6. 故障处理（有异常时）
    failed = [r for r in results if not r.success]
    if failed:
        issues_lines = [f"- {r.mode}: {r.error} (耗时{r.duration_ms}ms)" for r in failed]
        sections.append(
            "【模式/系统故障处理方案】\n"
            + "\n".join(issues_lines) + "\n\n"
            "建议操作:\n"
            "1. 检查网络连接是否正常\n"
            "2. 验证 API Key 是否有效\n"
            "3. 查看后端日志 ~/.pycoder/*.log\n"
            "4. 重试或切换到其他模型"
        )

    return "\n\n".join(sections)


# 便捷导出
__all__ = ["merge_results", "ModeResult"]
