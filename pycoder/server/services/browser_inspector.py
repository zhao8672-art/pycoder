"""
浏览器检查器 — AI 可调用工具，读取内置浏览器中的信息和调试数据

提供 5 个 AI 工具:
  1. browser_inspect    — 获取页面摘要（标题/URL/可见文本/Console错误/Network错误）
  2. browser_console    — 获取完整 Console 日志
  3. browser_exec_js    — 在页面中执行 JS 并返回结果
  4. browser_get_html   — 获取页面 HTML 源码（截断）
  5. browser_network    — 获取 Network 请求列表（状态码/URL/耗时）

集成到 AgentOrchestrator 和 ChatBridge 中，
AI 可以通过 @browser 触发浏览器分析模式。

用法:
  from pycoder.server.services.browser_inspector import BrowserInspector
  bi = BrowserInspector()
  bi.set_page_data(data)  # 从前端接收最新页面数据
  result = bi.inspect()    # AI 调用 inspect 工具
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class BrowserPageData:
    """从前端传来的页面数据快照"""

    url: str = ""
    title: str = ""
    html: str = ""  # HTML 源码（截断到 5000 字符）
    visible_text: str = ""  # 页面可见文本
    console_logs: list[dict] = field(default_factory=list)
    network_requests: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    js_result: str = ""  # 最近一次 executeJavaScript 结果
    timestamp: float = 0.0
    page_size_bytes: int = 0


class BrowserInspector:
    """浏览器信息提取工具 — AI 可通过工具调用读取页面状态"""

    def __init__(self):
        self._page_data: BrowserPageData = BrowserPageData()
        self._last_extraction: float = 0.0

    def set_page_data(self, raw_data: dict) -> None:
        """从前端 JSON 更新页面数据"""
        self._page_data = BrowserPageData(
            url=raw_data.get("url", ""),
            title=raw_data.get("title", ""),
            html=raw_data.get("html", "")[:10000],
            visible_text=raw_data.get("visibleText", ""),
            console_logs=raw_data.get("consoleLogs", []),
            network_requests=raw_data.get("networkRequests", []),
            errors=raw_data.get("errors", []),
            js_result=raw_data.get("jsResult", ""),
            timestamp=time.time(),
            page_size_bytes=raw_data.get("pageSizeBytes", 0),
        )
        self._last_extraction = time.time()

    # ══════════════════════════════════════════════════════
    # AI 工具方法（被 AgentOrchestrator 调用）
    # ══════════════════════════════════════════════════════

    def inspect(self) -> dict:
        """browser_inspect: 获取页面综合摘要"""
        pd = self._page_data
        console_errors = [line for line in pd.console_logs if line.get("level") == "error"]
        network_failures = [
            r for r in pd.network_requests if r.get("status", 0) >= 400 or r.get("failed")
        ]

        return {
            "tool": "browser_inspect",
            "url": pd.url,
            "title": pd.title,
            "pageSizeBytes": pd.page_size_bytes,
            "visibleTextPreview": pd.visible_text[:1000],
            "visibleTextLength": len(pd.visible_text),
            "consoleErrorCount": len(console_errors),
            "consoleErrorPreview": [
                {
                    "message": e.get("message", "")[:200],
                    "source": e.get("source", ""),
                    "line": e.get("lineNumber", 0),
                }
                for e in console_errors[:10]
            ],
            "networkErrorCount": len(network_failures),
            "networkErrorPreview": [
                {
                    "url": r.get("url", "")[:200],
                    "status": r.get("status", 0),
                    "method": r.get("method", "GET"),
                    "duration": r.get("duration", 0),
                }
                for r in network_failures[:10]
            ],
            "totalConsoleLogs": len(pd.console_logs),
            "totalNetworkRequests": len(pd.network_requests),
            "timestamp": pd.timestamp,
        }

    def get_console(self, level: str = "all", limit: int = 50) -> dict:
        """browser_console: 获取 Console 日志"""
        pd = self._page_data
        logs = pd.console_logs
        if level != "all":
            logs = [line for line in logs if line.get("level") == level]
        return {
            "tool": "browser_console",
            "url": pd.url,
            "total": len(pd.console_logs),
            "filtered": len(logs),
            "level": level,
            "logs": [
                {
                    "level": line.get("level", "log"),
                    "message": line.get("message", "")[:500],
                    "source": line.get("source", ""),
                    "line": line.get("lineNumber", 0),
                    "timestamp": line.get("timestamp", 0),
                }
                for line in logs[-limit:]
            ],
        }

    def get_network(self, status_filter: str = "all", limit: int = 30) -> dict:
        """browser_network: 获取网络请求列表"""
        pd = self._page_data
        reqs = pd.network_requests
        if status_filter == "errors":
            reqs = [r for r in reqs if r.get("status", 0) >= 400]
        elif status_filter == "success":
            reqs = [r for r in reqs if 200 <= r.get("status", 0) < 400]
        return {
            "tool": "browser_network",
            "url": pd.url,
            "total": len(pd.network_requests),
            "filtered": len(reqs),
            "filter": status_filter,
            "requests": [
                {
                    "url": r.get("url", "")[:300],
                    "method": r.get("method", "GET"),
                    "status": r.get("status", 0),
                    "type": r.get("type", ""),
                    "duration": r.get("duration", 0),
                    "size": r.get("size", 0),
                }
                for r in reqs[-limit:]
            ],
        }

    def get_html(self, selector: str = "", max_length: int = 5000) -> dict:
        """browser_get_html: 获取页面 HTML"""
        pd = self._page_data
        html = pd.html
        if selector and pd.html:
            import re as _re

            pattern = _re.compile(
                rf"<{selector}[^>]*>.*?</{selector}>",
                _re.DOTALL | _re.IGNORECASE,
            )
            matches = pattern.findall(pd.html)
            html = "\n".join(matches[:10]) if matches else f"(未找到: {selector})"

        return {
            "tool": "browser_get_html",
            "url": pd.url,
            "selector": selector or "(全部)",
            "htmlLength": len(html),
            "truncated": len(pd.html) > max_length,
            "html": html[:max_length],
        }

    def get_js_result(self) -> dict:
        """返回最近一次 executeJavaScript 的结果"""
        pd = self._page_data
        return {
            "tool": "browser_exec_js",
            "url": pd.url,
            "result": pd.js_result[:5000] if pd.js_result else "(无结果)",
            "resultLength": len(pd.js_result),
        }

    # ══════════════════════════════════════════════════════
    # 格式化输出（供 AI 理解）
    # ══════════════════════════════════════════════════════

    def get_context_for_ai(self) -> str:
        """生成适合注入到 AI 系统提示词的浏览器上下文"""
        pd = self._page_data
        if not pd.url:
            return ""

        console_errors = [line for line in pd.console_logs if line.get("level") == "error"]
        parts = [
            "## 🌐 浏览器页面信息",
            f"- URL: {pd.url}",
            f"- 标题: {pd.title}",
            f"- 页面大小: {pd.page_size_bytes} bytes",
        ]

        if console_errors:
            parts.append(f"\n### 🔴 Console 错误 ({len(console_errors)}个)")
            for e in console_errors[:5]:
                parts.append(f"- {e.get('message', '')[:200]}")

        net_errors = [r for r in pd.network_requests if r.get("status", 0) >= 400]
        if net_errors:
            parts.append(f"\n### 🌐 网络错误 ({len(net_errors)}个)")
            for r in net_errors[:5]:
                parts.append(
                    f"- [{r.get('status', 0)}] {r.get('method', 'GET')} "
                    f"{r.get('url', '')[:150]}"
                )

        if pd.visible_text:
            parts.append(
                f"\n### 📄 页面可见文本 (前500字符)\n" f"```\n{pd.visible_text[:500]}\n```"
            )

        return "\n".join(parts)

    def analyze_and_suggest(self) -> dict:
        """分析页面问题并生成修复建议（供 AI 参考）"""
        pd = self._page_data
        issues: list[dict] = []
        suggestions: list[str] = []

        # 1. Console 错误分析
        console_errors = [line for line in pd.console_logs if line.get("level") == "error"]
        for e in console_errors:
            msg = e.get("message", "")
            if "404" in msg or "Not Found" in msg:
                issues.append(
                    {
                        "type": "resource_404",
                        "severity": "medium",
                        "detail": msg[:200],
                        "suggestion": "检查资源路径是否正确，或资源是否已部署",
                    }
                )
            elif "CORS" in msg or "cross-origin" in msg.lower():
                issues.append(
                    {
                        "type": "cors",
                        "severity": "high",
                        "detail": msg[:200],
                        "suggestion": "需要在服务端添加 CORS 头: Access-Control-Allow-Origin",
                    }
                )
            elif "SyntaxError" in msg:
                issues.append(
                    {
                        "type": "js_syntax",
                        "severity": "high",
                        "detail": msg[:200],
                        "suggestion": "JavaScript 语法错误，检查对应行代码",
                    }
                )
            elif "ReferenceError" in msg or "is not defined" in msg:
                issues.append(
                    {
                        "type": "js_reference",
                        "severity": "high",
                        "detail": msg[:200],
                        "suggestion": "变量/函数未定义，检查是否缺少导入或定义顺序错误",
                    }
                )
            elif "TypeError" in msg:
                issues.append(
                    {
                        "type": "js_type",
                        "severity": "high",
                        "detail": msg[:200],
                        "suggestion": "类型错误，检查变量类型是否正确",
                    }
                )
            elif "NetworkError" in msg or "Failed to fetch" in msg:
                issues.append(
                    {
                        "type": "network",
                        "severity": "high",
                        "detail": msg[:200],
                        "suggestion": "网络请求失败，检查 API 端点是否可访问",
                    }
                )
            else:
                issues.append(
                    {
                        "type": "console_error",
                        "severity": "medium",
                        "detail": msg[:200],
                        "suggestion": "查看 Console 面板获取完整错误堆栈",
                    }
                )

        # 2. Network 错误分析
        for r in pd.network_requests:
            status = r.get("status", 0)
            if status == 404:
                suggestions.append(
                    f"[404] {r.get('method', 'GET')} {r.get('url', '')[:100]} — "
                    "资源不存在，检查路径"
                )
            elif status == 500:
                suggestions.append(
                    f"[500] {r.get('method', 'GET')} {r.get('url', '')[:100]} — "
                    "服务端错误，检查后端日志"
                )
            elif status == 403:
                suggestions.append(
                    f"[403] {r.get('method', 'GET')} {r.get('url', '')[:100]} — "
                    "权限不足，检查认证信息"
                )
            elif status == 0 and r.get("failed"):
                suggestions.append(
                    f"[FAILED] {r.get('method', 'GET')} {r.get('url', '')[:100]} — "
                    "请求失败，检查网络连接或 CORS"
                )

        # 3. 页面内容分析
        if pd.visible_text:
            text_lower = pd.visible_text.lower()
            if "error" in text_lower or "exception" in text_lower:
                suggestions.append("页面内容包含错误信息，检查后端是否返回异常")
            if "not found" in text_lower or "404" in text_lower:
                suggestions.append("页面显示 404 内容，检查路由配置")

        return {
            "url": pd.url,
            "title": pd.title,
            "issueCount": len(issues),
            "issues": issues[:20],
            "suggestions": suggestions[:10],
            "hasConsoleErrors": len(console_errors) > 0,
            "hasNetworkErrors": any(
                r.get("status", 0) >= 400 or r.get("failed") for r in pd.network_requests
            ),
        }


# 全局单例
_inspector: BrowserInspector | None = None


def get_browser_inspector() -> BrowserInspector:
    global _inspector
    if _inspector is None:
        _inspector = BrowserInspector()
    return _inspector


__all__ = [
    "BrowserInspector",
    "BrowserPageData",
    "get_browser_inspector",
]
