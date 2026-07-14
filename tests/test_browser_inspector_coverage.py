"""BrowserInspector 单元测试 — 覆盖 pycoder.server.services.browser_inspector

覆盖:
- BrowserPageData 默认值
- set_page_data 各字段映射
- inspect() 综合摘要
- get_console(level/limit)
- get_network(status_filter/limit)
- get_html(selector/max_length)
- get_js_result
- get_context_for_ai
- analyze_and_suggest 各类错误
- get_browser_inspector 单例
"""
from __future__ import annotations

from pycoder.server.services.browser_inspector import (
    BrowserInspector,
    BrowserPageData,
    get_browser_inspector,
)


# ── BrowserPageData ──────────────────────────────────────


class TestBrowserPageData:
    def test_defaults(self):
        d = BrowserPageData()
        assert d.url == ""
        assert d.title == ""
        assert d.html == ""
        assert d.visible_text == ""
        assert d.console_logs == []
        assert d.network_requests == []
        assert d.errors == []
        assert d.js_result == ""
        assert d.timestamp == 0.0
        assert d.page_size_bytes == 0


# ── set_page_data ─────────────────────────────────────────


class TestSetPageData:
    def test_maps_all_fields(self):
        bi = BrowserInspector()
        raw = {
            "url": "https://example.com",
            "title": "Example",
            "html": "<div>x</div>",
            "visibleText": "hello world",
            "consoleLogs": [{"level": "error", "message": "boom"}],
            "networkRequests": [{"url": "/api", "status": 200}],
            "errors": ["err1"],
            "jsResult": "result",
            "pageSizeBytes": 123,
        }
        bi.set_page_data(raw)
        pd = bi._page_data
        assert pd.url == "https://example.com"
        assert pd.title == "Example"
        assert pd.html == "<div>x</div>"
        assert pd.visible_text == "hello world"
        assert pd.console_logs == [{"level": "error", "message": "boom"}]
        assert pd.network_requests == [{"url": "/api", "status": 200}]
        assert pd.errors == ["err1"]
        assert pd.js_result == "result"
        assert pd.page_size_bytes == 123
        assert pd.timestamp > 0
        assert bi._last_extraction > 0

    def test_html_truncated_to_10000(self):
        bi = BrowserInspector()
        long_html = "x" * 20000
        bi.set_page_data({"html": long_html})
        assert len(bi._page_data.html) == 10000

    def test_missing_keys_default(self):
        bi = BrowserInspector()
        bi.set_page_data({})
        assert bi._page_data.url == ""
        assert bi._page_data.html == ""
        assert bi._page_data.console_logs == []
        assert bi._page_data.page_size_bytes == 0


# ── inspect ───────────────────────────────────────────────


class TestInspect:
    def test_empty_page(self):
        bi = BrowserInspector()
        result = bi.inspect()
        assert result["tool"] == "browser_inspect"
        assert result["url"] == ""
        assert result["consoleErrorCount"] == 0
        assert result["networkErrorCount"] == 0
        assert result["totalConsoleLogs"] == 0

    def test_with_errors(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "url": "http://x",
            "title": "T",
            "visibleText": "vtext",
            "consoleLogs": [
                {"level": "error", "message": "m1", "source": "s", "lineNumber": 10},
                {"level": "info", "message": "m2"},
            ],
            "networkRequests": [
                {"url": "/a", "status": 404, "method": "GET", "duration": 5},
                {"url": "/b", "status": 200, "method": "POST"},
                {"url": "/c", "failed": True, "method": "GET"},
            ],
            "pageSizeBytes": 999,
        })
        r = bi.inspect()
        assert r["url"] == "http://x"
        assert r["title"] == "T"
        assert r["pageSizeBytes"] == 999
        assert r["visibleTextLength"] == 5
        assert r["visibleTextPreview"] == "vtext"
        assert r["consoleErrorCount"] == 1
        assert r["consoleErrorPreview"][0]["message"] == "m1"
        assert r["consoleErrorPreview"][0]["source"] == "s"
        assert r["consoleErrorPreview"][0]["line"] == 10
        assert r["networkErrorCount"] == 2  # 404 + failed
        assert r["totalConsoleLogs"] == 2
        assert r["totalNetworkRequests"] == 3


# ── get_console ──────────────────────────────────────────


class TestGetConsole:
    def test_all_level(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "url": "http://x",
            "consoleLogs": [
                {"level": "error", "message": "e1"},
                {"level": "warn", "message": "w1"},
                {"level": "log", "message": "l1"},
            ],
        })
        r = bi.get_console()
        assert r["tool"] == "browser_console"
        assert r["total"] == 3
        assert r["filtered"] == 3
        assert r["level"] == "all"
        assert len(r["logs"]) == 3

    def test_filtered_level(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "consoleLogs": [
                {"level": "error", "message": "e1"},
                {"level": "warn", "message": "w1"},
            ],
        })
        r = bi.get_console(level="error")
        assert r["filtered"] == 1
        assert r["logs"][0]["message"] == "e1"

    def test_limit(self):
        bi = BrowserInspector()
        logs = [{"level": "log", "message": f"m{i}"} for i in range(10)]
        bi.set_page_data({"consoleLogs": logs})
        r = bi.get_console(limit=3)
        assert len(r["logs"]) == 3

    def test_log_defaults(self):
        bi = BrowserInspector()
        bi.set_page_data({"consoleLogs": [{"message": "no-level"}]})
        r = bi.get_console()
        assert r["logs"][0]["level"] == "log"
        assert r["logs"][0]["line"] == 0
        assert r["logs"][0]["timestamp"] == 0


# ── get_network ──────────────────────────────────────────


class TestGetNetwork:
    def test_all(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "url": "http://x",
            "networkRequests": [
                {"url": "/a", "status": 200, "method": "GET"},
                {"url": "/b", "status": 404, "method": "POST"},
            ],
        })
        r = bi.get_network()
        assert r["tool"] == "browser_network"
        assert r["total"] == 2
        assert r["filtered"] == 2
        assert r["filter"] == "all"
        assert len(r["requests"]) == 2

    def test_errors_filter(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "networkRequests": [
                {"url": "/a", "status": 200},
                {"url": "/b", "status": 500},
                {"url": "/c", "status": 404},
            ],
        })
        r = bi.get_network(status_filter="errors")
        assert r["filtered"] == 2

    def test_success_filter(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "networkRequests": [
                {"url": "/a", "status": 200},
                {"url": "/b", "status": 301},
                {"url": "/c", "status": 500},
            ],
        })
        r = bi.get_network(status_filter="success")
        assert r["filtered"] == 2

    def test_request_defaults(self):
        bi = BrowserInspector()
        bi.set_page_data({"networkRequests": [{"url": "/a"}]})
        r = bi.get_network()
        assert r["requests"][0]["method"] == "GET"
        assert r["requests"][0]["status"] == 0
        assert r["requests"][0]["type"] == ""
        assert r["requests"][0]["duration"] == 0
        assert r["requests"][0]["size"] == 0


# ── get_html ─────────────────────────────────────────────


class TestGetHtml:
    def test_full_html(self):
        bi = BrowserInspector()
        bi.set_page_data({"url": "http://x", "html": "<html><body>hi</body></html>"})
        r = bi.get_html()
        assert r["tool"] == "browser_get_html"
        assert r["selector"] == "(全部)"
        assert r["html"] == "<html><body>hi</body></html>"
        assert r["htmlLength"] > 0
        assert r["truncated"] is False

    def test_with_selector(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "html": "<div><p>one</p><p>two</p></div>"
        })
        r = bi.get_html(selector="p")
        assert "one" in r["html"]
        assert "two" in r["html"]

    def test_selector_no_match(self):
        bi = BrowserInspector()
        bi.set_page_data({"html": "<div>nope</div>"})
        r = bi.get_html(selector="span")
        assert "未找到" in r["html"]

    def test_truncation(self):
        bi = BrowserInspector()
        bi.set_page_data({"html": "x" * 10000})
        r = bi.get_html(max_length=100)
        assert len(r["html"]) == 100
        assert r["truncated"] is True


# ── get_js_result ────────────────────────────────────────


class TestGetJsResult:
    def test_empty(self):
        bi = BrowserInspector()
        r = bi.get_js_result()
        assert r["tool"] == "browser_exec_js"
        assert r["result"] == "(无结果)"
        assert r["resultLength"] == 0

    def test_with_content(self):
        bi = BrowserInspector()
        bi.set_page_data({"jsResult": "console output"})
        r = bi.get_js_result()
        assert r["result"] == "console output"
        assert r["resultLength"] == 14


# ── get_context_for_ai ───────────────────────────────────


class TestGetContextForAi:
    def test_empty_url(self):
        bi = BrowserInspector()
        assert bi.get_context_for_ai() == ""

    def test_basic_context(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "url": "http://x",
            "title": "T",
            "pageSizeBytes": 100,
            "visibleText": "hello",
        })
        ctx = bi.get_context_for_ai()
        assert "http://x" in ctx
        assert "T" in ctx
        assert "100" in ctx
        assert "hello" in ctx

    def test_with_console_errors(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "url": "http://x",
            "consoleLogs": [{"level": "error", "message": "SyntaxError: boom"}],
        })
        ctx = bi.get_context_for_ai()
        assert "Console 错误" in ctx
        assert "SyntaxError: boom" in ctx

    def test_with_network_errors(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "url": "http://x",
            "networkRequests": [{"status": 500, "method": "GET", "url": "/api"}],
        })
        ctx = bi.get_context_for_ai()
        assert "网络错误" in ctx
        assert "500" in ctx
        assert "/api" in ctx


# ── analyze_and_suggest ──────────────────────────────────


class TestAnalyzeAndSuggest:
    def test_clean_page(self):
        bi = BrowserInspector()
        r = bi.analyze_and_suggest()
        assert r["issueCount"] == 0
        assert r["suggestions"] == []
        assert r["hasConsoleErrors"] is False
        assert r["hasNetworkErrors"] is False

    def test_404_console_error(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "url": "http://x",
            "consoleLogs": [{"level": "error", "message": "404 Not Found"}],
        })
        r = bi.analyze_and_suggest()
        assert r["issues"][0]["type"] == "resource_404"
        assert r["issues"][0]["severity"] == "medium"

    def test_cors_console_error(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "consoleLogs": [{"level": "error", "message": "CORS blocked"}],
        })
        r = bi.analyze_and_suggest()
        assert r["issues"][0]["type"] == "cors"
        assert r["issues"][0]["severity"] == "high"

    def test_syntax_error(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "consoleLogs": [{"level": "error", "message": "SyntaxError: unexpected"}],
        })
        r = bi.analyze_and_suggest()
        assert r["issues"][0]["type"] == "js_syntax"

    def test_reference_error(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "consoleLogs": [{"level": "error", "message": "ReferenceError: x is not defined"}],
        })
        r = bi.analyze_and_suggest()
        assert r["issues"][0]["type"] == "js_reference"

    def test_type_error(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "consoleLogs": [{"level": "error", "message": "TypeError: cannot read"}],
        })
        r = bi.analyze_and_suggest()
        assert r["issues"][0]["type"] == "js_type"

    def test_network_error_console(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "consoleLogs": [{"level": "error", "message": "NetworkError: Failed to fetch"}],
        })
        r = bi.analyze_and_suggest()
        assert r["issues"][0]["type"] == "network"

    def test_generic_console_error(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "consoleLogs": [{"level": "error", "message": "something weird"}],
        })
        r = bi.analyze_and_suggest()
        assert r["issues"][0]["type"] == "console_error"

    def test_network_status_404(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "networkRequests": [{"status": 404, "method": "GET", "url": "/missing"}],
        })
        r = bi.analyze_and_suggest()
        assert any("404" in s for s in r["suggestions"])

    def test_network_status_500(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "networkRequests": [{"status": 500, "method": "POST", "url": "/api"}],
        })
        r = bi.analyze_and_suggest()
        assert any("500" in s for s in r["suggestions"])

    def test_network_status_403(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "networkRequests": [{"status": 403, "method": "GET", "url": "/secret"}],
        })
        r = bi.analyze_and_suggest()
        assert any("403" in s for s in r["suggestions"])

    def test_network_failed(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "networkRequests": [{"status": 0, "failed": True, "method": "GET", "url": "/x"}],
        })
        r = bi.analyze_and_suggest()
        assert any("FAILED" in s for s in r["suggestions"])

    def test_visible_text_error(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "visibleText": "An error occurred while processing",
        })
        r = bi.analyze_and_suggest()
        assert any("错误信息" in s for s in r["suggestions"])

    def test_visible_text_404(self):
        bi = BrowserInspector()
        bi.set_page_data({
            "visibleText": "Page not found 404",
        })
        r = bi.analyze_and_suggest()
        assert any("404" in s for s in r["suggestions"])


# ── 单例 ─────────────────────────────────────────────────


class TestSingleton:
    def test_get_browser_inspector_returns_same_instance(self):
        a = get_browser_inspector()
        b = get_browser_inspector()
        assert a is b
        assert isinstance(a, BrowserInspector)
