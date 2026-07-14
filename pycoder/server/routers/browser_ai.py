"""
浏览器 AI 分析服务 — AI 读取/分析/操作内置浏览器

端点:
  POST /api/browser/analyze     — AI 分析浏览器页面内容
  POST /api/browser/diagnose    — AI 诊断页面错误并给出修复方案
  POST /api/browser/action      — AI 操作浏览器 (导航/执行JS/截图)
  GET  /api/browser/capabilities — 返回浏览器 AI 能力清单

集成:
  - BrowserPanel 点击 🤖按钮 → 发页面信息到后端 → AI分析 → 返回结果
  - AI Chat 可通过 /browser/action 直接操作浏览器
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from pycoder.server.chat_bridge import ChatBridge
from pycoder.server.log import log

router = APIRouter(prefix="/api/browser", tags=["browser-ai"])


# ══════════════════════════════════════════════════════════
# 请求/响应模型
# ══════════════════════════════════════════════════════════


class BrowserContext(BaseModel):
    """浏览器页面上下文"""

    url: str = ""
    title: str = ""
    body_text: str = ""  # 页面文本
    scripts: list[str] = []  # 外部脚本 URL
    errors: list[dict] = []  # JS 错误列表
    headings: list[dict] = []
    forms: int = 0
    images: int = 0
    links: int = 0
    body_size: int = 0
    viewport: str = ""
    inline_scripts: int = 0


class AnalyzeRequest(BaseModel):
    """AI 分析请求"""

    context: BrowserContext = BrowserContext()
    question: str = ""  # 用户额外提问
    model: str = "deepseek-chat"


class DiagnoseRequest(BaseModel):
    """诊断请求"""

    errors: list[dict] = []
    url: str = ""
    page_text: str = ""
    model: str = "deepseek-chat"


class BrowserAction(BaseModel):
    """浏览器操作命令"""

    action: str  # navigate | exec-js | reload | screenshot
    url: str = ""  # navigate 时使用
    code: str = ""  # exec-js 时使用


# ══════════════════════════════════════════════════════════
# AI 分析引擎
# ══════════════════════════════════════════════════════════

DIAGNOSE_PROMPT = """你是 PyCoder 内置浏览器的 AI 分析引擎。请分析以下网页信息并给出诊断。

## 分析维度
1. **错误诊断** — JS 错误、网络问题、安全警告
2. **性能分析** — 脚本数量、页面大小、加载性能
3. **SEO/结构** — 标题、描述、语义标签
4. **安全问题** — XSS 风险、硬编码信息、不安全脚本
5. **优化建议** — 可立即执行的改进方案

## 输出格式
请用 Markdown 输出，包含：
- 🔴 严重问题（必须修复）
- 🟡 警告（建议修复）
- 🟢 优化建议
- 📊 页面概览

每个问题请给出具体的修复代码或步骤。
"""


async def _call_ai(system_prompt: str, user_message: str, model: str = "deepseek-chat") -> str:
    """调用 AI 分析"""
    bridge = ChatBridge()
    try:
        api_key = _get_key(model)
        bridge.configure(model=model, api_key=api_key)
        bridge.config.system_prompt = system_prompt
        bridge.config.max_tokens = 4096

        result = ""
        async for event in bridge.chat_stream(user_message):
            if event.event_type == "token":
                result += event.content
            elif event.event_type == "done":
                result = event.content or result
                break
            elif event.event_type == "error":
                result = f"AI 分析错误: {event.content}"
                break
        return result
    finally:
        await bridge.close()


def _get_key(model: str) -> str:
    """获取模型 API Key"""
    from pycoder.server.chat_handler import _get_api_key_for_model

    return _get_api_key_for_model(model)


# ══════════════════════════════════════════════════════════
# API 端点
# ══════════════════════════════════════════════════════════


@router.post("/analyze")
async def analyze_page(req: AnalyzeRequest):
    """AI 分析浏览器页面"""
    ctx = req.context

    # 构建分析消息
    error_lines = ""
    if ctx.errors:
        error_lines = "\n## ⚠️ 检测到的 JS 错误\n"
        for e in ctx.errors[:15]:
            error_lines += (
                f"- [{e.get('type', 'error')}] {e.get('message', '')}"
                f" (行{e.get('line', '?')})\n"
            )

    script_lines = ""
    if ctx.scripts:
        script_lines = "\n## 📜 加载的外部脚本\n"
        for s in ctx.scripts[:15]:
            script_lines += f"- {s}\n"

    user_msg = f"""## 📄 页面: {ctx.title or '无标题'}
🌐 URL: {ctx.url}
📊 统计: {ctx.scripts.__len__()}个脚本 | {ctx.forms}个表单 | {ctx.images}个图片 | {ctx.links}个链接 | {round(ctx.body_size/1024)}KB

{script_lines}

{error_lines}

## 📝 页面文本内容
{ctx.body_text[:3000]}

{"## ❓ 用户问题: " + req.question if req.question else ""}

请全面分析这个页面。"""

    try:
        analysis = await _call_ai(DIAGNOSE_PROMPT, user_msg, req.model)
        return {"success": True, "analysis": analysis}
    except Exception as e:
        log.error("browser_analyze_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"分析失败: {e}") from e


@router.post("/diagnose")
async def diagnose_errors(req: DiagnoseRequest):
    """AI 诊断页面错误并给出修复代码"""
    if not req.errors:
        return {"success": True, "diagnosis": "✅ 未检测到 JS 错误，页面运行正常。"}

    error_text = "\n".join(
        f"- [{e.get('type','error')}] {e.get('message','')} (行{e.get('line','?')})"
        for e in req.errors[:20]
    )

    prompt = """你是浏览器错误诊断专家。请分析以下 JS 错误，给出每个错误的原因和具体修复代码。

## 输出格式
对每个错误输出:
1. **错误原因** — 为什么发生
2. **修复代码** — 可直接使用的修复代码
3. **预防措施** — 如何避免再次出现

请用 Markdown 格式输出，修复代码使用代码块。
"""

    user_msg = f"页面 URL: {req.url}\n\n检测到的错误:\n{error_text}"

    try:
        diagnosis = await _call_ai(prompt, user_msg, req.model)
        return {"success": True, "diagnosis": diagnosis}
    except Exception as e:
        log.error("browser_diagnose_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"诊断失败: {e}") from e


@router.post("/action")
async def browser_action(req: BrowserAction):
    """AI 操作浏览器（供 AI Agent 调用）"""
    if req.action == "navigate":
        return {
            "success": True,
            "action": "navigate",
            "url": req.url,
            "electron_ipc": "browser:navigate",
            "payload": {"url": req.url},
        }
    elif req.action == "exec-js":
        return {
            "success": True,
            "action": "exec-js",
            "electron_ipc": "browser:exec-js",
            "payload": {"code": req.code},
        }
    elif req.action == "reload":
        return {
            "success": True,
            "action": "reload",
            "electron_ipc": "browser:reload",
        }
    elif req.action == "screenshot":
        return {
            "success": True,
            "action": "screenshot",
            "electron_ipc": "browser:screenshot",
        }
    else:
        raise HTTPException(status_code=400, detail=f"未知操作: {req.action}")


@router.get("/capabilities")
async def browser_capabilities():
    """返回浏览器 AI 能力清单（注入到 AI system prompt）"""
    return {
        "capabilities": {
            "browser_inspect": {
                "description": "读取内置浏览器中的页面内容、DOM、JS错误、Console日志",
                "tools": [
                    "browser:get-context — 获取页面标题/URL/加载状态",
                    "browser:exec-js — 在页面中执行任意 JS 并获取结果",
                    "browser:analyze-page — 全面分析页面（标题/脚本/错误/表单/文本）",
                    "browser:screenshot — 截取当前页面的屏幕截图",
                ],
            },
            "browser_control": {
                "description": "控制内置浏览器导航和操作",
                "tools": [
                    "browser:navigate — 导航到指定 URL",
                    "browser:reload — 刷新页面",
                ],
            },
            "browser_ai_analyze": {
                "description": "AI 分析浏览器页面内容",
                "endpoints": [
                    "POST /api/browser/analyze — 全页面 AI 分析",
                    "POST /api/browser/diagnose — 错误诊断+修复方案",
                ],
            },
        }
    }


__all__ = ["router"]
