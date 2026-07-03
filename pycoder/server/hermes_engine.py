"""
Hermes structured task engine.
Parses user requests into plan->execute->report pipeline.
"""

from __future__ import annotations

import re
from typing import Optional
from pycoder.prompts.loader import get_prompt

# ───── Hermes 规则引擎 ─────

HERMES_SYSTEM_PROMPT = get_prompt("hermes", "zh")

# Hermes 关键词：匹配开发任务场景
_HERMES_KEYWORDS = [
    "代码修改", "bug修复", "功能开发", "测试", "部署", "架构", "配置",
    "编写代码", "写代码", "修bug", "重构", "优化", "调试", "实现",
    "开发", "创建文件", "写文件", "修复", "添加功能", "改代码",
    "写一个", "写个", "帮我写", "请写", "生成代码", "修改代码",
]

def _is_hermes_task(message: str) -> bool:
    """检测消息是否为开发任务，需要 Hermes 模式处理"""
    for kw in _HERMES_KEYWORDS:
        if kw in message:
            return True
    return False

def _parse_hermes_output(full_text: str) -> dict:
    """从完整的 AI 回复中解析 Hermes 结构化输出"""
    result = {"plan": "", "changed_files": [], "summary": "", "raw": full_text}
    # 尝试解析计划
    plan = _extract_field(full_text, "计划")
    if plan:
        result["plan"] = plan
    # 尝试解析变更文件
    files = _extract_field(full_text, "修改文件")
    if files:
        result["changed_files"] = [f.strip() for f in files.split(",") if f.strip()]
    # 尝试解析总结
    summary = _extract_field(full_text, "总结")
    if summary:
        result["summary"] = summary
    return result

def _extract_field(section: str, field_name: str) -> str:
    """Extract field value from a structured section"""
    if not section:
        return ""
    for pat in [
        rf"\*\*{field_name}：\*\*(.+?)(?:\n|$)",
        rf"\*\*{field_name}:\*\*(.+?)(?:\n|$)",
        rf"{field_name}[:：](.+?)(?:\n|$)",
    ]:
        m = re.search(pat, section)
        if m:
            return m.group(1).strip()
    return ""

async def _execute_hermes_write(file_path: str, file_content: str) -> dict:
    """执行 Hermes 模式下的文件写入"""
    from pycoder.server.routers.files import WORKSPACE_ROOT, _safe_path, FileWriteRequest
    try:
        target = _safe_path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not file_content:
            if target.exists():
                file_content = target.read_text(encoding="utf-8")
            else:
                return {"path": file_path, "success": False, "error": "file_content为空且文件不存在"}
        target.write_text(file_content, encoding="utf-8")
        return {"path": file_path, "success": True, "size": len(file_content.encode("utf-8"))}
    except Exception as e:
        return {"path": file_path, "success": False, "error": str(e)}

# ───── _run_hermes_execute (kept for compatibility) ─────

async def _run_hermes_execute(session_id, plan_context, model):
    """执行 Hermes 计划阶段：根据用户确认的计划执行并输出报告"""
    from pycoder.server.chat_bridge import ChatBridge
    from pycoder.server.chat_handler import _get_api_key_for_model
    api_key = _get_api_key_for_model(model)
    if not api_key:
        yield {"type": "error", "message": "No API Key configured"}
        return
    bridge = ChatBridge()
    bridge.configure(model=model, api_key=api_key)
    yield {"type": "agent_status", "message": f"Executing plan on {model}..."}
    async for event in bridge.chat_stream(plan_context):
        if event.event_type == "token":
            yield {"type": "chunk", "content": event.content}
        elif event.event_type == "done":
            yield {"type": "done", "content": event.content}
        elif event.event_type == "error":
            yield {"type": "error", "message": event.content}
