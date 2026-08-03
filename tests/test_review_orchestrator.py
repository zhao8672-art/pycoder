"""F5 代码审查编排器与 API 测试

覆盖:
    - parse_diff_files: diff 按文件切分
    - extract_json_payload: LLM 输出 JSON 容错解析
    - parse_llm_issues: 结构化意见字段容错
    - compute_stats / compute_overall_score: 统计与评分
    - 静态启发式扫描: eval / shell=True / 硬编码密钥 / 裸 except / print
    - ReviewOrchestrator.review_diff / review_files: mock LLM 端到端
    - 熔断截断: max_files / 单文件超长 / 总长度预算
    - generate_fix: LLM 补丁生成与提取
    - review_api 三个端点: /run /fix /pr（TestClient + mock）
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.server.routers import review_api as review_api_mod
from pycoder.server.services import review_orchestrator as ro
from pycoder.server.services.review_orchestrator import (
    MAX_FILE_CHARS,
    MAX_TOTAL_CHARS,
    ReviewIssue,
    ReviewOrchestrator,
    compute_overall_score,
    compute_stats,
    extract_json_payload,
    parse_diff_files,
    parse_llm_issues,
)

# ══════════════════════════════════════════════════════════
# 测试数据
# ══════════════════════════════════════════════════════════

SAMPLE_DIFF = """--- a/app.py
+++ b/app.py
@@ -1,2 +1,2 @@
-import os
+import sys
+print(2)
--- a/util.py
+++ b/util.py
@@ -1,1 +1,1 @@
-x = 1
+x = 2
"""

LLM_JSON_OK = (
    '{"issues": [{"file_path": "app.py", "line_start": 2, "line_end": 2,'
    ' "severity": "warning", "category": "style",'
    ' "message": "使用 print 输出", "suggestion": "改用 logging"}]}'
)


def _make_issue(**kwargs) -> ReviewIssue:
    """构造测试用 ReviewIssue，字段可覆盖."""
    base = {
        "file_path": "a.py",
        "line_start": 1,
        "line_end": 1,
        "severity": "info",
        "category": "style",
        "message": "m",
        "suggestion": "s",
    }
    base.update(kwargs)
    return ReviewIssue(**base)


# ══════════════════════════════════════════════════════════
# parse_diff_files
# ══════════════════════════════════════════════════════════


class TestParseDiffFiles:
    """diff 按文件切分"""

    def test_splits_multiple_files(self):
        files = parse_diff_files(SAMPLE_DIFF)
        assert set(files.keys()) == {"app.py", "util.py"}
        assert "+print(2)" in files["app.py"]
        assert "+x = 2" in files["util.py"]

    def test_strips_git_prefix(self):
        assert "b/app.py" not in parse_diff_files(SAMPLE_DIFF)

    def test_empty_diff(self):
        assert parse_diff_files("") == {}

    def test_git_style_header(self):
        diff = "diff --git a/x.py b/x.py\nindex 111..222 100644\n--- a/x.py\n+++ b/x.py\n@@ -0,0 +1 @@\n+pass\n"
        files = parse_diff_files(diff)
        assert list(files.keys()) == ["x.py"]


# ══════════════════════════════════════════════════════════
# extract_json_payload — JSON 容错
# ══════════════════════════════════════════════════════════


class TestExtractJsonPayload:
    """LLM 输出 JSON 容错解析"""

    def test_direct_json(self):
        data = extract_json_payload('{"issues": []}')
        assert data == {"issues": []}

    def test_json_code_fence(self):
        text = f"审查结果如下:\n```json\n{LLM_JSON_OK}\n```\n以上。"
        data = extract_json_payload(text)
        assert data is not None
        assert len(data["issues"]) == 1

    def test_prose_wrapped_json(self):
        text = f"好的，结果: {LLM_JSON_OK} 完毕"
        data = extract_json_payload(text)
        assert data is not None
        assert data["issues"][0]["severity"] == "warning"

    def test_array_payload_normalized(self):
        data = extract_json_payload('[{"severity": "info"}]')
        assert data == {"issues": [{"severity": "info"}]}

    def test_garbage_returns_none(self):
        assert extract_json_payload("完全不是 JSON 的输出") is None
        assert extract_json_payload("") is None


# ══════════════════════════════════════════════════════════
# parse_llm_issues — 结构化意见字段容错
# ══════════════════════════════════════════════════════════


class TestParseLlmIssues:
    """结构化意见解析与字段规范化"""

    def test_normal_parse(self):
        payload = {
            "issues": [
                {
                    "file_path": "a.py",
                    "line_start": 3,
                    "line_end": 5,
                    "severity": "error",
                    "category": "security",
                    "message": "SQL 注入",
                    "suggestion": "参数化查询",
                }
            ]
        }
        issues = parse_llm_issues(payload, default_file="x.py")
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].line_end == 5

    def test_invalid_severity_coerced_to_info(self):
        payload = {"issues": [{"severity": "fatal", "message": "m"}]}
        issues = parse_llm_issues(payload, default_file="x.py")
        assert issues[0].severity == "info"

    def test_invalid_category_coerced(self):
        payload = {"issues": [{"category": "unknown", "message": "m"}]}
        issues = parse_llm_issues(payload, default_file="x.py")
        assert issues[0].category == "best-practice"

    def test_bad_line_numbers_fallback(self):
        payload = {"issues": [{"line_start": "abc", "line_end": -5, "message": "m"}]}
        issues = parse_llm_issues(payload, default_file="x.py")
        assert issues[0].line_start == 1
        assert issues[0].line_end == 1

    def test_default_file_used(self):
        payload = {"issues": [{"message": "m"}]}
        issues = parse_llm_issues(payload, default_file="fallback.py")
        assert issues[0].file_path == "fallback.py"

    def test_non_dict_entries_skipped(self):
        payload = {"issues": ["junk", 42, {"message": "ok"}]}
        issues = parse_llm_issues(payload, default_file="x.py")
        assert len(issues) == 1

    def test_issues_not_list(self):
        assert parse_llm_issues({"issues": "nope"}, default_file="x.py") == []


# ══════════════════════════════════════════════════════════
# 统计与评分
# ══════════════════════════════════════════════════════════


class TestStatsAndScore:
    """severity/category 统计与 overall_score 计算"""

    def test_stats_by_severity_and_category(self):
        issues = [
            _make_issue(severity="critical", category="security"),
            _make_issue(severity="error", category="security"),
            _make_issue(severity="warning", category="perf"),
            _make_issue(severity="info", category="style"),
        ]
        stats = compute_stats(issues)
        assert stats["by_severity"] == {
            "info": 1,
            "warning": 1,
            "error": 1,
            "critical": 1,
        }
        assert stats["by_category"]["security"] == 2
        assert stats["by_category"]["perf"] == 1

    def test_score_no_issues_is_100(self):
        assert compute_overall_score([]) == 100.0

    def test_score_weighted_penalty(self):
        issues = [
            _make_issue(severity="critical"),  # -25
            _make_issue(severity="error"),  # -12
            _make_issue(severity="warning"),  # -5
            _make_issue(severity="info"),  # -1
        ]
        assert compute_overall_score(issues) == 57.0

    def test_score_floor_zero(self):
        issues = [_make_issue(severity="critical") for _ in range(10)]
        assert compute_overall_score(issues) == 0.0


# ══════════════════════════════════════════════════════════
# 静态启发式扫描
# ══════════════════════════════════════════════════════════


class TestStaticScan:
    """内置启发式危险模式扫描"""

    def _scan(self, content: str):
        return ro._static_scan_file("t.py", content)

    def test_eval_is_critical_security(self):
        issues = self._scan("result = eval(user_input)\n")
        assert any(i.severity == "critical" and i.category == "security" for i in issues)

    def test_shell_true_is_error(self):
        issues = self._scan("subprocess.run(cmd, shell=True)\n")
        assert any(i.severity == "error" and i.category == "security" for i in issues)

    def test_hardcoded_secret(self):
        issues = self._scan("api_key = 'sk-abcdef123456'\n")
        assert any(i.category == "security" for i in issues)

    def test_bare_except_is_warning(self):
        issues = self._scan("try:\n    pass\nexcept:\n    pass\n")
        assert any(i.severity == "warning" and i.category == "bug" for i in issues)

    def test_line_numbers_correct(self):
        issues = self._scan("a = 1\nb = 2\nresult = eval(x)\n")
        eval_issues = [i for i in issues if "eval" in i.message]
        assert eval_issues[0].line_start == 3

    def test_clean_code_no_issues(self):
        issues = self._scan("import logging\nlogger = logging.getLogger(__name__)\n")
        assert issues == []


# ══════════════════════════════════════════════════════════
# ReviewOrchestrator — mock LLM 端到端
# ══════════════════════════════════════════════════════════


def _mock_llm_factory(responses: list[str] | None = None, counter: dict | None = None):
    """构造可注入的 mock LLM 函数."""
    responses = responses or [LLM_JSON_OK]

    async def mock_chat(prompt: str, max_tokens: int) -> str:
        if counter is not None:
            counter["calls"] = counter.get("calls", 0) + 1
        idx = min(counter.get("calls", 1) - 1, len(responses) - 1) if counter else 0
        return responses[idx]

    return mock_chat


class TestOrchestratorReview:
    """review_diff / review_files 主流程"""

    async def test_review_diff_end_to_end(self):
        orch = ReviewOrchestrator(llm_chat=_mock_llm_factory())
        result = await orch.review_diff(SAMPLE_DIFF)
        # 静态扫描发现 print（info） + LLM 发现 warning
        assert result.overall_score < 100.0
        assert len(result.issues) >= 2
        categories = {i.category for i in result.issues}
        assert "style" in categories
        # LLM 每文件调用一次，2 个文件 → 2 条 warning
        assert result.stats["by_severity"]["warning"] == 2
        assert "2 个文件" in result.summary

    async def test_review_files_end_to_end(self):
        orch = ReviewOrchestrator(llm_chat=_mock_llm_factory())
        result = await orch.review_files(
            [{"path": "a.py", "content": "x = eval(input())\n"}]
        )
        # eval → critical；overall 扣分
        assert any(i.severity == "critical" for i in result.issues)
        assert result.overall_score <= 75.0

    async def test_empty_diff_returns_100(self):
        orch = ReviewOrchestrator(llm_chat=_mock_llm_factory())
        result = await orch.review_diff("")
        assert result.overall_score == 100.0
        assert result.issues == []

    async def test_llm_invalid_json_degrades_gracefully(self):
        async def bad_llm(prompt: str, max_tokens: int) -> str:
            return "这不是 JSON，无法解析"

        orch = ReviewOrchestrator(llm_chat=bad_llm)
        result = await orch.review_files(
            [{"path": "a.py", "content": "x = 1\n"}],
            include_static=False,
        )
        # 容错降级为 info issue，不中断
        assert len(result.issues) == 1
        assert result.issues[0].severity == "info"
        assert "无法解析" in result.issues[0].message

    async def test_llm_exception_degrades_gracefully(self):
        async def boom_llm(prompt: str, max_tokens: int) -> str:
            raise RuntimeError("api down")

        orch = ReviewOrchestrator(llm_chat=boom_llm)
        result = await orch.review_files(
            [{"path": "a.py", "content": "x = 1\n"}],
            include_static=False,
        )
        assert len(result.issues) == 1
        assert result.issues[0].severity == "info"
        assert "失败" in result.issues[0].message

    async def test_diff_static_scan_uses_added_lines(self):
        """diff 模式下静态扫描只针对 + 行."""

        async def no_issue_llm(prompt: str, max_tokens: int) -> str:
            return '{"issues": []}'

        diff = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-result = eval(x)\n+result = safe(x)\n"
        orch = ReviewOrchestrator(llm_chat=no_issue_llm)
        result = await orch.review_diff(diff)
        # - 行中的 eval 不应被报出
        assert result.issues == []
        assert result.overall_score == 100.0


# ══════════════════════════════════════════════════════════
# 熔断截断
# ══════════════════════════════════════════════════════════


class TestCircuitBreaker:
    """成本/长度熔断"""

    async def test_max_files_truncation(self):
        counter: dict = {}
        orch = ReviewOrchestrator(llm_chat=_mock_llm_factory(counter=counter))
        files = [{"path": f"f{i}.py", "content": "x = 1\n"} for i in range(5)]
        result = await orch.review_files(files, max_files=2, include_static=False)
        assert result.truncated is True
        assert counter["calls"] == 2

    async def test_single_file_char_truncation(self):
        captured: dict = {}

        async def capture_llm(prompt: str, max_tokens: int) -> str:
            captured["len"] = len(prompt)
            return '{"issues": []}'

        orch = ReviewOrchestrator(llm_chat=capture_llm)
        big_content = "x = 1\n" * 5000  # 30_000 字符 > MAX_FILE_CHARS
        result = await orch.review_files(
            [{"path": "big.py", "content": big_content}],
            include_static=False,
        )
        assert result.truncated is True
        # prompt 中的内容已被截断（远小于原始长度 + 模板）
        assert captured["len"] < len(big_content)

    async def test_total_char_budget_breaks(self):
        counter: dict = {}
        orch = ReviewOrchestrator(llm_chat=_mock_llm_factory(counter=counter))
        # 每个文件 15_000 字符，预算 120_000 → 审查 8 个后停止
        files = [{"path": f"f{i}.py", "content": "a" * 15_000} for i in range(10)]
        result = await orch.review_files(files, max_files=10, include_static=False)
        assert result.truncated is True
        assert counter["calls"] == MAX_TOTAL_CHARS // 15_000

    async def test_no_truncation_when_within_limits(self):
        orch = ReviewOrchestrator(llm_chat=_mock_llm_factory())
        result = await orch.review_files(
            [{"path": "a.py", "content": "x = 1\n"}],
            include_static=False,
        )
        assert result.truncated is False


# ══════════════════════════════════════════════════════════
# generate_fix
# ══════════════════════════════════════════════════════════


class TestGenerateFix:
    """LLM 修复补丁生成"""

    PATCH = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-print(1)\n+logger.info(1)\n"

    async def test_generate_fix_plain_patch(self):
        async def llm(prompt: str, max_tokens: int) -> str:
            return TestGenerateFix.PATCH

        orch = ReviewOrchestrator(llm_chat=llm)
        patch = await orch.generate_fix(_make_issue())
        assert patch.startswith("--- ")
        assert "+logger.info(1)" in patch

    async def test_generate_fix_fenced_patch(self):
        async def llm(prompt: str, max_tokens: int) -> str:
            return f"修复如下:\n```diff\n{TestGenerateFix.PATCH}\n```"

        orch = ReviewOrchestrator(llm_chat=llm)
        patch = await orch.generate_fix(_make_issue())
        assert patch.startswith("--- ")

    async def test_generate_fix_llm_failure_returns_empty(self):
        async def boom(prompt: str, max_tokens: int) -> str:
            raise RuntimeError("down")

        orch = ReviewOrchestrator(llm_chat=boom)
        assert await orch.generate_fix(_make_issue()) == ""

    async def test_generate_fix_no_patch_returns_empty(self):
        async def llm(prompt: str, max_tokens: int) -> str:
            return "无法修复此问题"

        orch = ReviewOrchestrator(llm_chat=llm)
        assert await orch.generate_fix(_make_issue()) == ""


# ══════════════════════════════════════════════════════════
# review_api 端点（TestClient）
# ══════════════════════════════════════════════════════════


@pytest.fixture
def api_client(monkeypatch):
    """仅含 review 路由的 FastAPI 应用 + mock 编排器."""
    orch = ReviewOrchestrator(llm_chat=_mock_llm_factory())
    monkeypatch.setattr(
        review_api_mod,
        "_make_orchestrator",
        lambda scan_dependencies=False: orch,
    )
    app = FastAPI()
    app.include_router(review_api_mod.router)
    with TestClient(app) as client:
        yield client


class TestReviewRunEndpoint:
    """POST /api/review/run"""

    def test_run_with_diff(self, api_client):
        resp = api_client.post("/api/review/run", json={"diff": SAMPLE_DIFF})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        result = data["result"]
        assert "overall_score" in result
        assert "issues" in result
        assert result["stats"]["by_severity"]["warning"] == 2  # 2 个文件 × 1 条 LLM warning

    def test_run_with_files(self, api_client):
        resp = api_client.post(
            "/api/review/run",
            json={"files": [{"path": "a.py", "content": "x = eval(y)\n"}]},
        )
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert any(i["severity"] == "critical" for i in result["issues"])

    def test_run_missing_input_returns_400(self, api_client):
        resp = api_client.post("/api/review/run", json={})
        assert resp.status_code == 400


class TestReviewFixEndpoint:
    """POST /api/review/fix"""

    def test_fix_returns_patch_and_preview(self, api_client, monkeypatch):
        patch = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n"

        async def llm(prompt: str, max_tokens: int) -> str:
            return patch

        orch = ReviewOrchestrator(llm_chat=llm)
        monkeypatch.setattr(
            review_api_mod,
            "_make_orchestrator",
            lambda scan_dependencies=False: orch,
        )
        resp = api_client.post(
            "/api/review/fix",
            json={
                "issue": {
                    "file_path": "a.py",
                    "line_start": 1,
                    "line_end": 1,
                    "severity": "warning",
                    "category": "style",
                    "message": "m",
                    "suggestion": "s",
                }
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["patch"].startswith("--- ")
        assert data["applied_preview"]["added"] == 1
        assert data["applied_preview"]["removed"] == 1


class _FakeResponse:
    """mock httpx.Response"""

    def __init__(self, status_code: int = 200, text: str = "", json_data: dict | None = None):
        self.status_code = status_code
        self.text = text
        self._json = json_data or {}

    def json(self):
        return self._json


class _FakeAsyncClient:
    """mock httpx.AsyncClient（支持 async with + get/post）"""

    def __init__(self, get_resp: _FakeResponse, post_resp: _FakeResponse | None = None):
        self._get = get_resp
        self._post = post_resp or _FakeResponse(201, json_data={"html_url": "http://x/c/1"})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, *args, **kwargs):
        return self._get

    async def post(self, *args, **kwargs):
        return self._post


class TestReviewPrEndpoint:
    """POST /api/review/pr"""

    def _setup_github_mocks(self, monkeypatch, get_resp, post_resp=None):
        from pycoder.server.routers import github as github_mod

        monkeypatch.setattr(github_mod, "_load_token", lambda: "fake-token")
        fake_client = _FakeAsyncClient(get_resp, post_resp)
        monkeypatch.setattr(
            review_api_mod.httpx, "AsyncClient", lambda *a, **k: fake_client
        )

    def test_pr_review_success(self, api_client, monkeypatch):
        self._setup_github_mocks(
            monkeypatch, _FakeResponse(200, text=SAMPLE_DIFF)
        )
        resp = api_client.post(
            "/api/review/pr",
            json={"owner": "o", "repo": "r", "pr_number": 1},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["result"]["stats"]["by_severity"]["warning"] == 2  # 2 个文件 × 1 条 LLM warning
        assert data["comment_posted"] is False

    def test_pr_review_with_auto_comment(self, api_client, monkeypatch):
        self._setup_github_mocks(
            monkeypatch,
            _FakeResponse(200, text=SAMPLE_DIFF),
            _FakeResponse(201, json_data={"html_url": "http://github/c/1"}),
        )
        resp = api_client.post(
            "/api/review/pr",
            json={"owner": "o", "repo": "r", "pr_number": 1, "auto_comment": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["comment_posted"] is True
        assert data["comment_url"] == "http://github/c/1"

    def test_pr_review_no_token_returns_401(self, api_client, monkeypatch):
        from pycoder.server.routers import github as github_mod

        monkeypatch.setattr(github_mod, "_load_token", lambda: "")
        resp = api_client.post(
            "/api/review/pr",
            json={"owner": "o", "repo": "r", "pr_number": 1},
        )
        assert resp.status_code == 401

    def test_pr_review_github_error(self, api_client, monkeypatch):
        self._setup_github_mocks(
            monkeypatch, _FakeResponse(404, text="not found")
        )
        resp = api_client.post(
            "/api/review/pr",
            json={"owner": "o", "repo": "r", "pr_number": 99},
        )
        assert resp.status_code == 404
