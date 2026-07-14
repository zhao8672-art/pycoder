"""marketplace.py 模块单元测试 — 覆盖率目标 ≥80%

覆盖内容:
  - SourceHealth: 健康度计算 / 成功失败记录 / 死亡恢复
  - SourceRegistry: 注册 / 排序 / 持久化
  - GitHub 请求重试 / 各数据源拉取 (GitHub/npm/PyPI/OpenVSX)
  - search_extensions: 缓存命中 / 缓存过期 / 过滤分页
  - _parallel_fetch_all / _fetch_with_health
  - _merge_and_dedup / _filter / _gh_repo_to_extension
  - 缓存读写 / 种子扩展

测试策略:
  - monkeypatch MARKETPLACE_CACHE / SOURCE_HEALTH_CACHE 重定向 tmp_path
  - 自定义 MockHTTPClient 替换 httpx.AsyncClient
  - monkeypatch asyncio.sleep 避免真实延迟
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pycoder.extensions import marketplace as mp


# ══════════════════════════════════════════════════════════
# Mock 辅助
# ══════════════════════════════════════════════════════════

class MockHTTPResponse:
    def __init__(self, status_code=200, json_data=None, headers=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._json


class MockHTTPClient:
    """模拟 httpx.AsyncClient — 支持按 URL 返回不同响应"""

    def __init__(self, responses=None, default_response=None, get_exc=None):
        # responses: dict[url_substr -> MockHTTPResponse | callable | Exception]
        self._responses = responses or {}
        self._default = default_response or MockHTTPResponse(status_code=404)
        self._get_exc = get_exc
        self.calls = []

    async def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params})
        if self._get_exc is not None:
            raise self._get_exc
        for key, resp in self._responses.items():
            if key in url:
                if isinstance(resp, Exception):
                    raise resp
                if callable(resp):
                    return resp(url, params)
                return resp
        return self._default

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """重定向缓存路径并重置 registry"""
    cache = tmp_path / "ext_cache.json"
    health = tmp_path / "source_health.json"
    monkeypatch.setattr(mp, "MARKETPLACE_CACHE", cache)
    monkeypatch.setattr(mp, "SOURCE_HEALTH_CACHE", health)
    # 用全新的 registry 替换模块级单例
    fresh = mp.SourceRegistry()
    monkeypatch.setattr(mp, "_source_registry", fresh)
    return {"cache": cache, "health": health, "registry": fresh}


# ══════════════════════════════════════════════════════════
# SourceHealth
# ══════════════════════════════════════════════════════════

def test_source_health_defaults():
    h = mp.SourceHealth()
    assert h.name == ""
    assert h.success_count == 0
    assert h.success_rate == 0.5  # 无数据时默认 0.5


def test_source_health_success_rate():
    h = mp.SourceHealth(name="x")
    h.success_count = 8
    h.fail_count = 2
    assert h.success_rate == 0.8


def test_source_health_avg_latency_no_calls():
    h = mp.SourceHealth()
    assert h.avg_latency == 999


def test_source_health_avg_latency_with_calls():
    h = mp.SourceHealth()
    h.total_latency = 100.0
    h.call_count = 5
    assert h.avg_latency == 20.0


def test_source_health_score_alive():
    h = mp.SourceHealth(name="x", weight=1.0)
    h.success_count = 10
    h.fail_count = 0
    h.call_count = 10
    h.total_latency = 50.0
    # success_rate=1.0, avg_latency=5.0, latency_penalty=min(0.5,0.5)=0.5
    # score = 1.0 * 1.0 * 100 - 0.5 * 20 = 100 - 10 = 90
    assert h.score == 90.0


def test_source_health_score_dead():
    h = mp.SourceHealth(name="x", is_dead=True)
    h.recovery_after = time.time() + 3600
    assert h.score == -999


def test_source_health_score_dead_recovered():
    h = mp.SourceHealth(name="x", is_dead=True)
    h.recovery_after = time.time() - 10  # 已过恢复期
    assert h.score != -999


def test_source_health_record_success():
    h = mp.SourceHealth(name="x")
    h.record_success(0.5)
    assert h.success_count == 1
    assert h.call_count == 1
    assert h.total_latency == 0.5
    assert h.consecutive_fails == 0
    assert h.is_dead is False


def test_source_health_record_success_clears_dead():
    h = mp.SourceHealth(name="x", is_dead=True)
    h.record_success(0.5)
    assert h.is_dead is False


def test_source_health_record_failure_below_threshold():
    h = mp.SourceHealth(name="x")
    h.record_failure()
    h.record_failure()
    assert h.fail_count == 2
    assert h.consecutive_fails == 2
    assert h.is_dead is False


def test_source_health_record_failure_marks_dead():
    h = mp.SourceHealth(name="x")
    h.record_failure()
    h.record_failure()
    h.record_failure()
    assert h.fail_count == 3
    assert h.consecutive_fails == 3
    assert h.is_dead is True
    assert h.recovery_after > time.time()


# ══════════════════════════════════════════════════════════
# SourceRegistry
# ══════════════════════════════════════════════════════════

def test_registry_register_new(tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "SOURCE_HEALTH_CACHE", tmp_path / "h.json")
    reg = mp.SourceRegistry()
    s = reg.register("github", priority=10, weight=1.0)
    assert s.name == "github"
    assert s.priority == 10
    # 重复注册返回同一个
    s2 = reg.register("github")
    assert s is s2


def test_registry_record_success(tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "SOURCE_HEALTH_CACHE", tmp_path / "h.json")
    reg = mp.SourceRegistry()
    reg.register("npm")
    reg.record_success("npm", 0.5)
    assert reg._sources["npm"].success_count == 1


def test_registry_record_success_unknown_source(tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "SOURCE_HEALTH_CACHE", tmp_path / "h.json")
    reg = mp.SourceRegistry()
    # 未知源不应抛错
    reg.record_success("unknown", 0.5)


def test_registry_record_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "SOURCE_HEALTH_CACHE", tmp_path / "h.json")
    reg = mp.SourceRegistry()
    reg.register("npm")
    reg.record_failure("npm")
    assert reg._sources["npm"].fail_count == 1


def test_registry_get_ranked_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "SOURCE_HEALTH_CACHE", tmp_path / "h.json")
    reg = mp.SourceRegistry()
    reg.register("a", priority=10)
    reg.register("b", priority=20)
    ranked = reg.get_ranked_sources()
    # 按 priority 升序
    assert ranked == ["a", "b"]


def test_registry_get_ranked_excludes_dead(tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "SOURCE_HEALTH_CACHE", tmp_path / "h.json")
    reg = mp.SourceRegistry()
    reg.register("alive", priority=10)
    dead = reg.register("dead", priority=20)
    dead.is_dead = True
    dead.recovery_after = time.time() + 3600
    ranked = reg.get_ranked_sources()
    assert "dead" not in ranked
    assert "alive" in ranked


def test_registry_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "SOURCE_HEALTH_CACHE", tmp_path / "h.json")
    reg = mp.SourceRegistry()
    reg.register("x")
    reg.record_success("x", 0.5)
    summary = reg.summary()
    assert len(summary) == 1
    assert summary[0]["name"] == "x"
    assert summary[0]["alive"] is True


def test_registry_load_from_file(tmp_path, monkeypatch):
    health_file = tmp_path / "h.json"
    health_file.write_text(json.dumps({
        "github": {"name": "github", "priority": 10, "success_count": 5},
    }), encoding="utf-8")
    monkeypatch.setattr(mp, "SOURCE_HEALTH_CACHE", health_file)
    reg = mp.SourceRegistry()
    assert "github" in reg._sources
    assert reg._sources["github"].success_count == 5


def test_registry_load_corrupted(tmp_path, monkeypatch):
    health_file = tmp_path / "h.json"
    health_file.write_text("not json {{{", encoding="utf-8")
    monkeypatch.setattr(mp, "SOURCE_HEALTH_CACHE", health_file)
    reg = mp.SourceRegistry()  # 不应抛异常
    assert len(reg._sources) == 0


def test_registry_save_persists(tmp_path, monkeypatch):
    health_file = tmp_path / "h.json"
    monkeypatch.setattr(mp, "SOURCE_HEALTH_CACHE", health_file)
    reg = mp.SourceRegistry()
    reg.register("x")
    reg.record_success("x", 0.5)
    assert health_file.exists()
    data = json.loads(health_file.read_text(encoding="utf-8"))
    assert "x" in data


# ══════════════════════════════════════════════════════════
# _gh_headers / _GITHUB_TOKEN
# ══════════════════════════════════════════════════════════

def test_gh_headers_no_token(monkeypatch):
    monkeypatch.setattr(mp, "_GITHUB_TOKEN", "")
    h = mp._gh_headers()
    assert h["Accept"] == "application/vnd.github.v3+json"
    assert "Authorization" not in h


def test_gh_headers_with_token(monkeypatch):
    monkeypatch.setattr(mp, "_GITHUB_TOKEN", "ghp_test123")
    h = mp._gh_headers()
    assert h["Authorization"] == "Bearer ghp_test123"


# ══════════════════════════════════════════════════════════
# _github_request_with_retry
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_github_request_success(monkeypatch):
    monkeypatch.setattr(mp.asyncio, "sleep", _no_sleep)
    resp = MockHTTPResponse(status_code=200, json_data={"items": []},
                            headers={"X-RateLimit-Remaining": "5000"})
    client = MockHTTPClient(responses={"api.github.com": resp})
    result = await mp._github_request_with_retry(client, "https://api.github.com/search/repositories", {"q": "test"})
    assert result == {"items": []}


@pytest.mark.asyncio
async def test_github_request_rate_limit_warning(monkeypatch):
    monkeypatch.setattr(mp.asyncio, "sleep", _no_sleep)
    # 注意: 源文件 line 351 log.warning(..., remaining=...) 使用 structlog 风格
    # 但 log 是 stdlib logging.Logger → 会抛 TypeError，被 except 捕获导致重试
    # 这里 mock log 以隔离该 bug，验证 rate-limit 分支本身
    monkeypatch.setattr(mp, "log", MagicMock())
    resp = MockHTTPResponse(status_code=200, json_data={"items": []},
                            headers={"X-RateLimit-Remaining": "5"})
    client = MockHTTPClient(responses={"api.github.com": resp})
    result = await mp._github_request_with_retry(client, "https://api.github.com/x", {})
    assert result == {"items": []}


@pytest.mark.asyncio
async def test_github_request_429_then_success(monkeypatch):
    monkeypatch.setattr(mp.asyncio, "sleep", _no_sleep)
    resp429 = MockHTTPResponse(status_code=429, headers={"Retry-After": "1"})
    resp200 = MockHTTPResponse(status_code=200, json_data={"ok": True})
    call_count = [0]

    def get_fn(url, params):
        call_count[0] += 1
        return resp429 if call_count[0] == 1 else resp200

    client = MockHTTPClient(responses={"api.github.com": get_fn})
    result = await mp._github_request_with_retry(client, "https://api.github.com/x", {})
    assert result == {"ok": True}
    assert call_count[0] == 2


@pytest.mark.asyncio
async def test_github_request_429_exhausted(monkeypatch):
    monkeypatch.setattr(mp.asyncio, "sleep", _no_sleep)
    resp = MockHTTPResponse(status_code=429, headers={"Retry-After": "1"})
    client = MockHTTPClient(responses={"api.github.com": resp})
    result = await mp._github_request_with_retry(client, "https://api.github.com/x", {})
    assert result is None


@pytest.mark.asyncio
async def test_github_request_403(monkeypatch):
    monkeypatch.setattr(mp.asyncio, "sleep", _no_sleep)
    resp = MockHTTPResponse(status_code=403)
    client = MockHTTPClient(responses={"api.github.com": resp})
    result = await mp._github_request_with_retry(client, "https://api.github.com/x", {})
    assert result is None


@pytest.mark.asyncio
async def test_github_request_404(monkeypatch):
    monkeypatch.setattr(mp.asyncio, "sleep", _no_sleep)
    resp = MockHTTPResponse(status_code=404)
    client = MockHTTPClient(responses={"api.github.com": resp})
    result = await mp._github_request_with_retry(client, "https://api.github.com/x", {})
    assert result is None


@pytest.mark.asyncio
async def test_github_request_other_status(monkeypatch):
    monkeypatch.setattr(mp.asyncio, "sleep", _no_sleep)
    resp = MockHTTPResponse(status_code=500)
    client = MockHTTPClient(responses={"api.github.com": resp})
    result = await mp._github_request_with_retry(client, "https://api.github.com/x", {})
    assert result is None


@pytest.mark.asyncio
async def test_github_request_exception_retries(monkeypatch):
    monkeypatch.setattr(mp.asyncio, "sleep", _no_sleep)
    call_count = [0]

    def get_fn(url, params):
        call_count[0] += 1
        if call_count[0] == 1:
            raise asyncio.TimeoutError()
        return MockHTTPResponse(status_code=200, json_data={"ok": True})

    client = MockHTTPClient(responses={"api.github.com": get_fn})
    result = await mp._github_request_with_retry(client, "https://api.github.com/x", {})
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_github_request_exception_exhausted(monkeypatch):
    monkeypatch.setattr(mp.asyncio, "sleep", _no_sleep)
    client = MockHTTPClient(responses={"api.github.com": RuntimeError("always fails")})
    result = await mp._github_request_with_retry(client, "https://api.github.com/x", {})
    assert result is None


# ══════════════════════════════════════════════════════════
# 各数据源拉取
# ══════════════════════════════════════════════════════════

def _gh_repo(name, lang="python"):
    return {
        "full_name": f"user/{name}", "name": name,
        "description": f"desc {name}", "owner": {"login": "user"},
        "stargazers_count": 100, "html_url": f"https://github.com/user/{name}",
        "language": lang, "topics": ["topic1"],
    }


@pytest.mark.asyncio
async def test_fetch_github_pycoder(monkeypatch):
    monkeypatch.setattr(mp.asyncio, "sleep", _no_sleep)
    data = {"items": [_gh_repo("ext1"), _gh_repo("ext2")]}
    monkeypatch.setattr(mp, "_github_request_with_retry", _async_return(data))
    client = MockHTTPClient()
    exts, latency = await mp._fetch_github_pycoder(client)
    assert len(exts) == 2
    assert exts[0]["source"] == "github"
    assert latency >= 0


@pytest.mark.asyncio
async def test_fetch_github_vscode(monkeypatch):
    monkeypatch.setattr(mp.asyncio, "sleep", _no_sleep)
    data = {"items": [_gh_repo("vscode-ext")]}
    monkeypatch.setattr(mp, "_github_request_with_retry", _async_return(data))
    client = MockHTTPClient()
    exts, latency = await mp._fetch_github_vscode(client)
    assert len(exts) == 1
    assert exts[0]["category"] == "vscode-compatible"
    assert "python-project" in exts[0]["tags"]


@pytest.mark.asyncio
async def test_fetch_github_awesome(monkeypatch):
    monkeypatch.setattr(mp.asyncio, "sleep", _no_sleep)
    data = {"items": [_gh_repo("awesome-list")]}
    monkeypatch.setattr(mp, "_github_request_with_retry", _async_return(data))
    client = MockHTTPClient()
    exts, latency = await mp._fetch_github_awesome(client)
    assert len(exts) == 1
    assert exts[0]["category"] == "devtools"
    assert "devtools" in exts[0]["tags"]


@pytest.mark.asyncio
async def test_fetch_github_devtools(monkeypatch):
    monkeypatch.setattr(mp.asyncio, "sleep", _no_sleep)
    # 三次查询返回不同结果
    results = [
        {"items": [_gh_repo("devtool1", "python")]},
        {"items": [_gh_repo("cli1", "python")]},
        {"items": [_gh_repo("linter1", "python")]},
    ]
    idx = [0]

    async def fake_retry(client, url, params):
        r = results[idx[0]]
        idx[0] += 1
        return r

    monkeypatch.setattr(mp, "_github_request_with_retry", fake_retry)
    client = MockHTTPClient()
    exts, latency = await mp._fetch_github_devtools(client)
    assert len(exts) == 3
    categories = {e["category"] for e in exts}
    assert "devtools" in categories and "code-quality" in categories


@pytest.mark.asyncio
async def test_fetch_github_devtools_dedup(monkeypatch):
    monkeypatch.setattr(mp.asyncio, "sleep", _no_sleep)
    # 两个查询返回同一个仓库 → 去重
    dup_repo = _gh_repo("same-repo")
    results = [{"items": [dup_repo]}, {"items": [dup_repo]}, {"items": []}]
    idx = [0]

    async def fake_retry(client, url, params):
        r = results[idx[0]]
        idx[0] += 1
        return r

    monkeypatch.setattr(mp, "_github_request_with_retry", fake_retry)
    client = MockHTTPClient()
    exts, _ = await mp._fetch_github_devtools(client)
    assert len(exts) == 1


@pytest.mark.asyncio
async def test_fetch_github_pycoder_empty(monkeypatch):
    monkeypatch.setattr(mp.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(mp, "_github_request_with_retry", _async_return(None))
    client = MockHTTPClient()
    exts, _ = await mp._fetch_github_pycoder(client)
    assert exts == []


@pytest.mark.asyncio
async def test_fetch_npm_registry_success():
    data = {
        "objects": [
            {"package": {"name": "test-pkg", "description": "a test",
                         "keywords": ["k1"], "version": "1.0",
                         "publisher": {"username": "alice"},
                         "links": {"npm": "http://npm/test-pkg"}},
             "score": {"detail": {"popularity": 0.5}}},
        ],
    }
    resp = MockHTTPResponse(status_code=200, json_data=data)
    client = MockHTTPClient(responses={"registry.npmjs.org": resp})
    exts, latency = await mp._fetch_npm_registry(client)
    assert len(exts) == 1
    assert exts[0]["id"] == "npm.test-pkg"
    assert exts[0]["source"] == "npm"


@pytest.mark.asyncio
async def test_fetch_npm_registry_non_200():
    resp = MockHTTPResponse(status_code=500)
    client = MockHTTPClient(responses={"registry.npmjs.org": resp})
    exts, _ = await mp._fetch_npm_registry(client)
    assert exts == []


@pytest.mark.asyncio
async def test_fetch_npm_registry_exception():
    client = MockHTTPClient(responses={"registry.npmjs.org": RuntimeError("boom")})
    exts, _ = await mp._fetch_npm_registry(client)
    assert exts == []


@pytest.mark.asyncio
async def test_fetch_pypi_popular_success():
    data = {"info": {"summary": "a lib", "author": "bob", "version": "2.0",
                     "package_url": "http://pypi/black"}}
    resp = MockHTTPResponse(status_code=200, json_data=data)
    # 所有 pypi.org 路径返回同一响应
    client = MockHTTPClient(responses={"pypi.org": resp})
    exts, latency = await mp._fetch_pypi_popular(client)
    assert len(exts) > 0
    assert exts[0]["source"] == "pypi"


@pytest.mark.asyncio
async def test_fetch_pypi_popular_partial_failure():
    call_count = [0]

    def get_fn(url, params):
        call_count[0] += 1
        if call_count[0] <= 2:
            raise OSError("fail")
        return MockHTTPResponse(status_code=200, json_data={"info": {"summary": "ok"}})

    client = MockHTTPClient(responses={"pypi.org": get_fn})
    exts, _ = await mp._fetch_pypi_popular(client)
    # 部分成功
    assert len(exts) >= 1


@pytest.mark.asyncio
async def test_fetch_open_vsx_success():
    data = {"extensions": [
        {"name": "ext1", "namespace": "ns1", "description": "d",
         "files": {"download": 500}, "tags": ["t1"], "version": "1.0"},
    ]}
    resp = MockHTTPResponse(status_code=200, json_data=data)
    client = MockHTTPClient(responses={"open-vsx.org": resp})
    exts, _ = await mp._fetch_open_vsx(client)
    assert len(exts) == 1
    assert exts[0]["id"] == "ovsx.ns1.ext1"


@pytest.mark.asyncio
async def test_fetch_open_vsx_non_200():
    resp = MockHTTPResponse(status_code=500)
    client = MockHTTPClient(responses={"open-vsx.org": resp})
    exts, _ = await mp._fetch_open_vsx(client)
    assert exts == []


@pytest.mark.asyncio
async def test_fetch_open_vsx_exception():
    client = MockHTTPClient(responses={"open-vsx.org": RuntimeError("boom")})
    exts, _ = await mp._fetch_open_vsx(client)
    assert exts == []


# ══════════════════════════════════════════════════════════
# _gh_repo_to_extension
# ══════════════════════════════════════════════════════════

def test_gh_repo_to_extension():
    repo = _gh_repo("myrepo", "Python")
    ext = mp._gh_repo_to_extension(repo)
    assert ext["id"] == "user/myrepo"
    assert ext["name"] == "myrepo"
    assert ext["author"] == "user"
    assert ext["stars"] == 100
    assert ext["source"] == "github"


def test_gh_repo_to_extension_no_language():
    repo = _gh_repo("myrepo", "")
    ext = mp._gh_repo_to_extension(repo)
    assert ext["category"] == "unknown"


def test_gh_repo_to_extension_none_description():
    repo = _gh_repo("myrepo")
    repo["description"] = None
    ext = mp._gh_repo_to_extension(repo)
    assert ext["description"] == ""


# ══════════════════════════════════════════════════════════
# _merge_and_dedup / _filter
# ══════════════════════════════════════════════════════════

def test_merge_and_dedup_new():
    exts = [{"id": "a", "name": "A", "stars": 10, "description": "d", "tags": ["t"], "source": "github"}]
    result = mp._merge_and_dedup(exts)
    assert len(result) == 1
    assert result[0]["_sources"] == ["github"]


def test_merge_and_dedup_duplicate_keeps_max_stars():
    exts = [
        {"id": "a", "name": "A", "stars": 10, "description": "short", "tags": ["t1"], "source": "github"},
        {"id": "a", "name": "A", "stars": 50, "description": "longer description here", "tags": ["t2"], "source": "npm"},
    ]
    result = mp._merge_and_dedup(exts)
    assert len(result) == 1
    assert result[0]["stars"] == 50
    assert "t1" in result[0]["tags"] and "t2" in result[0]["tags"]
    assert "github" in result[0]["_sources"] and "npm" in result[0]["_sources"]


def test_merge_and_dedup_no_id_skipped():
    exts = [{"name": "no-id", "source": "x"}, {"id": "b", "name": "B", "source": "y"}]
    result = mp._merge_and_dedup(exts)
    assert len(result) == 1


def test_filter_by_query_name():
    exts = [
        {"id": "1", "name": "Python Tools", "description": "", "tags": [], "stars": 10},
        {"id": "2", "name": "Other", "description": "", "tags": [], "stars": 5},
    ]
    result = mp._filter(exts, "python", "")
    assert len(result) == 1
    assert result[0]["name"] == "Python Tools"


def test_filter_by_query_description():
    exts = [
        {"id": "1", "name": "X", "description": "best python lib", "tags": [], "stars": 10},
    ]
    result = mp._filter(exts, "python", "")
    assert len(result) == 1


def test_filter_by_query_tags():
    exts = [
        {"id": "1", "name": "X", "description": "", "tags": ["python-tool"], "stars": 10},
    ]
    result = mp._filter(exts, "python", "")
    assert len(result) == 1


def test_filter_by_category():
    exts = [
        {"id": "1", "name": "X", "description": "", "tags": [], "category": "git", "stars": 10},
        {"id": "2", "name": "Y", "description": "", "tags": [], "category": "tools", "stars": 5},
    ]
    result = mp._filter(exts, "", "git")
    assert len(result) == 1


def test_filter_by_category_tag():
    exts = [
        {"id": "1", "name": "X", "description": "", "tags": ["git-tag"], "category": "other", "stars": 10},
    ]
    result = mp._filter(exts, "", "git-tag")
    assert len(result) == 1


def test_filter_sorts_by_stars():
    exts = [
        {"id": "1", "name": "A", "description": "", "tags": [], "stars": 5},
        {"id": "2", "name": "B", "description": "", "tags": [], "stars": 100},
    ]
    result = mp._filter(exts, "", "")
    assert result[0]["stars"] == 100


def test_filter_empty():
    result = mp._filter([], "test", "")
    assert result == []


# ══════════════════════════════════════════════════════════
# 缓存读写
# ══════════════════════════════════════════════════════════

def test_load_cache_nonexistent(isolated_cache):
    result = mp._load_cache()
    assert result == {}


def test_load_cache_valid(isolated_cache):
    data = {"updated_at": time.time(), "extensions": [{"id": "x"}]}
    isolated_cache["cache"].write_text(json.dumps(data), encoding="utf-8")
    result = mp._load_cache()
    assert "extensions" in result


def test_load_cache_corrupted(isolated_cache):
    isolated_cache["cache"].write_text("bad json {{{", encoding="utf-8")
    result = mp._load_cache()
    assert result == {}


def test_save_cache(isolated_cache):
    data = {"updated_at": time.time(), "extensions": []}
    mp._save_cache(data)
    assert isolated_cache["cache"].exists()
    loaded = json.loads(isolated_cache["cache"].read_text(encoding="utf-8"))
    assert loaded["extensions"] == []


def test_is_cache_stale_fresh():
    cache = {"updated_at": time.time()}
    assert mp._is_cache_stale(cache) is False


def test_is_cache_stale_old():
    cache = {"updated_at": time.time() - mp.CACHE_TTL - 100}
    assert mp._is_cache_stale(cache) is True


def test_is_cache_stale_no_timestamp():
    cache = {}
    assert mp._is_cache_stale(cache) is True


# ══════════════════════════════════════════════════════════
# 种子扩展
# ══════════════════════════════════════════════════════════

def test_get_seed_extensions():
    seeds = mp.get_seed_extensions()
    assert len(seeds) >= 10
    for s in seeds:
        assert "id" in s and "name" in s
        assert s["is_seed"] is True


def test_get_seed_extensions_returns_copy():
    s1 = mp.get_seed_extensions()
    s2 = mp.get_seed_extensions()
    assert s1 is not s2
    assert s1 == s2


def test_get_source_health_summary(isolated_cache):
    isolated_cache["registry"].register("test")
    summary = mp.get_source_health_summary()
    assert len(summary) == 1


# ══════════════════════════════════════════════════════════
# _fetch_with_health
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_fetch_with_health_success(isolated_cache):
    async def good_fetcher(client):
        return [{"id": "x"}], 0.5

    result = await mp._fetch_with_health("test-src", good_fetcher, MockHTTPClient())
    assert result is not None
    exts, name, latency, ok = result
    assert ok is True
    assert name == "test-src"
    assert exts == [{"id": "x"}]


@pytest.mark.asyncio
async def test_fetch_with_health_timeout(isolated_cache, monkeypatch):
    monkeypatch.setattr(mp.asyncio, "sleep", _no_sleep)

    async def slow_fetcher(client):
        await asyncio.sleep(100)  # 会被 wait_for 超时
        return [], 0.1

    # monkeypatch wait_for 的 timeout 为极小值
    import pycoder.extensions.marketplace as mp_mod
    orig_wait_for = mp_mod.asyncio.wait_for

    async def fast_wait_for(coro, timeout):
        # 立即取消
        coro.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(mp_mod.asyncio, "wait_for", fast_wait_for)
    result = await mp._fetch_with_health("test-src", slow_fetcher, MockHTTPClient())
    assert result is not None
    assert result[3] is False  # ok=False


@pytest.mark.asyncio
async def test_fetch_with_health_exception(isolated_cache, monkeypatch):
    monkeypatch.setattr(mp.asyncio, "sleep", _no_sleep)

    async def bad_fetcher(client):
        raise RuntimeError("fetch failed")

    result = await mp._fetch_with_health("test-src", bad_fetcher, MockHTTPClient())
    assert result is not None
    assert result[3] is False
    assert result[2] == 15.0  # latency 默认


# ══════════════════════════════════════════════════════════
# _parallel_fetch_all
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_parallel_fetch_all_with_mock_fetchers(isolated_cache, monkeypatch):
    """用 mock fetcher 替换 ALL_SOURCES 中的函数"""
    monkeypatch.setattr(mp.asyncio, "sleep", _no_sleep)

    async def fake_fetch(client):
        return [{"id": "fake-ext", "name": "Fake", "description": "d",
                 "tags": [], "stars": 10, "source": "fake"}], 0.1

    # 替换 ALL_SOURCES 中的 fetch 函数
    original = mp.ALL_SOURCES[:]
    try:
        mp.ALL_SOURCES[:] = [
            (name, fake_fetch, prio, w) for name, _, prio, w in original
        ]
        # mock httpx.AsyncClient
        monkeypatch.setattr(mp.httpx, "AsyncClient", lambda **kwargs: MockHTTPClient())
        exts, info = await mp._parallel_fetch_all()
        assert len(exts) > 0
        assert "fake-ext" in [e["id"] for e in exts]
    finally:
        mp.ALL_SOURCES[:] = original


@pytest.mark.asyncio
async def test_parallel_fetch_all_all_failed(isolated_cache, monkeypatch):
    monkeypatch.setattr(mp.asyncio, "sleep", _no_sleep)

    async def failing_fetch(client):
        raise RuntimeError("all fail")

    original = mp.ALL_SOURCES[:]
    try:
        mp.ALL_SOURCES[:] = [
            (name, failing_fetch, prio, w) for name, _, prio, w in original
        ]
        monkeypatch.setattr(mp.httpx, "AsyncClient", lambda **kwargs: MockHTTPClient())
        exts, info = await mp._parallel_fetch_all()
        assert exts == []
    finally:
        mp.ALL_SOURCES[:] = original


# ══════════════════════════════════════════════════════════
# search_extensions
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_search_extensions_cache_fresh(isolated_cache):
    """缓存未过期 → 直接返回缓存"""
    exts = [{"id": "cached", "name": "Cached", "description": "d",
             "tags": [], "stars": 10, "category": "tools"}]
    cache_data = {"updated_at": time.time(), "extensions": exts, "source_info": {}, "total": 1}
    isolated_cache["cache"].write_text(json.dumps(cache_data), encoding="utf-8")

    result = await mp.search_extensions(query="", category="", limit=10, offset=0)
    assert result["total"] == 1
    assert result["extensions"][0]["id"] == "cached"
    assert result["sources"]["used_cache"] is True


@pytest.mark.asyncio
async def test_search_extensions_cache_stale_refreshes(isolated_cache, monkeypatch):
    """缓存过期 → stale-while-revalidate: 立即返回缓存，后台刷新"""
    # 过期缓存（含一个旧扩展）
    stale_ext = {"id": "stale", "name": "Stale", "description": "old",
                 "tags": [], "stars": 1, "source": "test"}
    cache_data = {"updated_at": time.time() - mp.CACHE_TTL - 100, "extensions": [stale_ext]}
    isolated_cache["cache"].write_text(json.dumps(cache_data), encoding="utf-8")

    async def fake_fetch_all():
        return [{"id": "fresh", "name": "Fresh", "description": "d",
                 "tags": [], "stars": 5, "source": "test"}], {}

    monkeypatch.setattr(mp, "_parallel_fetch_all", fake_fetch_all)
    # stale-while-revalidate: 立即返回过期缓存数据（不阻塞等待远程拉取）
    result = await mp.search_extensions(query="", limit=50)
    assert result["sources"]["used_cache"] is True
    assert result["total_all"] == 1  # 过期缓存中的 1 个扩展
    assert result["extensions"][0]["id"] == "stale"

    # 等待后台刷新任务完成（使用真实 sleep 让出事件循环控制权）
    import asyncio as _asyncio
    await _asyncio.sleep(0.3)
    # 验证缓存已被后台任务更新
    new_cache = json.loads(isolated_cache["cache"].read_text(encoding="utf-8"))
    fresh_ids = [e["id"] for e in new_cache["extensions"]]
    assert "fresh" in fresh_ids  # 后台拉取的新数据已写入


@pytest.mark.asyncio
async def test_search_extensions_query_filter(isolated_cache):
    exts = [
        {"id": "1", "name": "Python Tool", "description": "", "tags": [], "stars": 10, "category": "x"},
        {"id": "2", "name": "Other", "description": "", "tags": [], "stars": 5, "category": "x"},
    ]
    cache_data = {"updated_at": time.time(), "extensions": exts}
    isolated_cache["cache"].write_text(json.dumps(cache_data), encoding="utf-8")

    result = await mp.search_extensions(query="python", limit=10)
    assert result["total"] == 1
    assert result["extensions"][0]["id"] == "1"


@pytest.mark.asyncio
async def test_search_extensions_category_filter(isolated_cache):
    exts = [
        {"id": "1", "name": "A", "description": "", "tags": [], "stars": 10, "category": "git"},
        {"id": "2", "name": "B", "description": "", "tags": [], "stars": 5, "category": "tools"},
    ]
    cache_data = {"updated_at": time.time(), "extensions": exts}
    isolated_cache["cache"].write_text(json.dumps(cache_data), encoding="utf-8")

    result = await mp.search_extensions(category="git", limit=10)
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_search_extensions_pagination(isolated_cache):
    exts = [
        {"id": str(i), "name": f"N{i}", "description": "", "tags": [], "stars": i, "category": "x"}
        for i in range(10)
    ]
    cache_data = {"updated_at": time.time(), "extensions": exts}
    isolated_cache["cache"].write_text(json.dumps(cache_data), encoding="utf-8")

    result = await mp.search_extensions(limit=3, offset=2)
    assert len(result["extensions"]) == 3
    assert result["has_more"] is True
    assert result["offset"] == 2


@pytest.mark.asyncio
async def test_search_extensions_no_more(isolated_cache):
    exts = [{"id": "1", "name": "A", "description": "", "tags": [], "stars": 1, "category": "x"}]
    cache_data = {"updated_at": time.time(), "extensions": exts}
    isolated_cache["cache"].write_text(json.dumps(cache_data), encoding="utf-8")

    result = await mp.search_extensions(limit=10)
    assert result["has_more"] is False


# ── 异步辅助 ──

async def _no_sleep(seconds):
    return None


def _async_return(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn
