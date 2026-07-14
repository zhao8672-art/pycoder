"""
扩展市场 — 多数据源智能聚合引擎

架构:
    1. SourceRegistry — 数据源注册表（健康追踪 + 自动排序）
    2. MultiFetcher — 并行拉取 + 最佳结果选择
    3. Merger — 跨源去重合并 + 质量评分
    4. 数据源: GitHub / npm / PyPI / Open VSX / 种子扩展

数据流:
    search_extensions(query)
      → _get_best_cached_or_fresh()
        → _parallel_fetch_all()  [所有源并行]
          → _merge_results()     [去重+评分]
            → _sort_by_score()   [按质量排序]
              → _save_cache() + return

源选择:
    健康度评分 = success_rate × 权重 - latency_penalty
    健康源优先；故障源自动降级；全故障时返回缓存
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("pycoder.marketplace")

# ══════════════════════════════════════════════════════════
# 缓存
# ══════════════════════════════════════════════════════════

MARKETPLACE_CACHE = Path.home() / ".pycoder" / "extensions_cache.json"
CACHE_TTL = 3600 * 6  # 6小时
SOURCE_HEALTH_CACHE = Path.home() / ".pycoder" / "source_health.json"

# ══════════════════════════════════════════════════════════
# 数据源健康追踪
# ══════════════════════════════════════════════════════════


@dataclass
class SourceHealth:
    """单个数据源的健康状态"""

    name: str = ""
    priority: int = 100
    weight: float = 1.0
    success_count: int = 0
    fail_count: int = 0
    total_latency: float = 0.0
    call_count: int = 0
    last_success: float = 0.0
    last_fail: float = 0.0
    consecutive_fails: int = 0
    is_dead: bool = False
    recovery_after: float = 0.0

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.5

    @property
    def avg_latency(self) -> float:
        return self.total_latency / self.call_count if self.call_count > 0 else 999

    @property
    def score(self) -> float:
        if self.is_dead and time.time() < self.recovery_after:
            return -999
        latency_penalty = min(self.avg_latency / 10, 0.5)
        return self.success_rate * self.weight * 100 - latency_penalty * 20

    def record_success(self, latency: float):
        self.success_count += 1
        self.call_count += 1
        self.total_latency += latency
        self.last_success = time.time()
        self.consecutive_fails = 0
        self.is_dead = False

    def record_failure(self):
        self.fail_count += 1
        self.call_count += 1
        self.last_fail = time.time()
        self.consecutive_fails += 1
        if self.consecutive_fails >= 3:
            self.is_dead = True
            self.recovery_after = time.time() + 3600


class SourceRegistry:
    """数据源注册表 — 管理所有扩展数据源的健康度和排序"""

    def __init__(self):
        self._sources: dict[str, SourceHealth] = {}
        self._load()

    def register(self, name: str, priority: int = 100, weight: float = 1.0) -> SourceHealth:
        if name not in self._sources:
            self._sources[name] = SourceHealth(name=name, priority=priority, weight=weight)
        return self._sources[name]

    def record_success(self, name: str, latency: float):
        if name in self._sources:
            self._sources[name].record_success(latency)
            self._save()

    def record_failure(self, name: str):
        if name in self._sources:
            self._sources[name].record_failure()
            self._save()

    def get_ranked_sources(self) -> list[str]:
        alive = [
            s for s in self._sources.values() if not s.is_dead or time.time() >= s.recovery_after
        ]
        alive.sort(key=lambda s: (s.priority, -s.score))
        return [s.name for s in alive]

    def summary(self) -> list[dict]:
        return [
            {
                "name": s.name,
                "score": round(s.score, 1),
                "success_rate": round(s.success_rate, 2),
                "avg_latency": round(s.avg_latency, 2),
                "alive": not s.is_dead or time.time() >= s.recovery_after,
                "calls": s.call_count,
            }
            for s in sorted(self._sources.values(), key=lambda x: -x.score)
        ]

    def _load(self):
        if SOURCE_HEALTH_CACHE.exists():
            try:
                data = json.loads(SOURCE_HEALTH_CACHE.read_text(encoding="utf-8"))
                for name, h in data.items():
                    self._sources[name] = SourceHealth(**h)
            except (json.JSONDecodeError, OSError, TypeError, ValueError) as e:
                log.debug("source_health_load_failed error=%s", e)

    def _save(self):
        SOURCE_HEALTH_CACHE.parent.mkdir(parents=True, exist_ok=True)
        SOURCE_HEALTH_CACHE.write_text(
            json.dumps(
                {k: v.__dict__ for k, v in self._sources.items()}, indent=2, ensure_ascii=False
            ),
            encoding="utf-8",
        )


_source_registry = SourceRegistry()

# ══════════════════════════════════════════════════════════
# 多源扩展拉取器
# ══════════════════════════════════════════════════════════

_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
_GITHUB_TIMEOUT = 8


def _gh_headers() -> dict:
    h = {"Accept": "application/vnd.github.v3+json"}
    if _GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {_GITHUB_TOKEN}"
    return h


async def _fetch_github_pycoder(client) -> tuple[list[dict], float]:
    """数据源 1: GitHub Python 开发工具 — stars>500 + Python"""
    start = time.time()
    result = await _github_request_with_retry(
        client,
        "https://api.github.com/search/repositories",
        {"q": "language:python+stars:>1000", "sort": "stars", "per_page": 50},
    )
    exts = [_gh_repo_to_extension(r) for r in (result or {}).get("items", [])]
    return exts, time.time() - start


async def _fetch_github_vscode(client) -> tuple[list[dict], float]:
    """数据源 2: GitHub Python 热门项目 — stars>5000"""
    start = time.time()
    result = await _github_request_with_retry(
        client,
        "https://api.github.com/search/repositories",
        {"q": "language:python+stars:>5000", "sort": "stars", "per_page": 30},
    )
    exts = []
    for repo in (result or {}).get("items", []):
        ext = _gh_repo_to_extension(repo)
        ext["category"] = "vscode-compatible"
        ext["tags"].append("python-project")
        exts.append(ext)
    return exts, time.time() - start


async def _fetch_github_awesome(client) -> tuple[list[dict], float]:
    """数据源 3: GitHub 开发者工具 — topic:developer-tools"""
    start = time.time()
    result = await _github_request_with_retry(
        client,
        "https://api.github.com/search/repositories",
        {"q": "topic:developer-tools+language:python", "sort": "stars", "per_page": 20},
    )
    exts = [_gh_repo_to_extension(r) for r in (result or {}).get("items", [])]
    for e in exts:
        e["category"] = "devtools"
        e["tags"].append("devtools")
    return exts, time.time() - start


async def _fetch_github_devtools(client) -> tuple[list[dict], float]:
    """数据源 4: GitHub 开发者工具（CLI/Linter/Formatter）"""
    start = time.time()
    queries = [
        ("topic:developer-tools+language:python+stars:>200", "devtools", "devtools"),
        ("topic:cli+language:python+stars:>200", "devtools", "cli"),
        ("topic:linter+language:python+stars:>200", "code-quality", "linter"),
    ]
    exts, seen = [], set()
    for q, cat, tag in queries:
        result = await _github_request_with_retry(
            client,
            "https://api.github.com/search/repositories",
            {"q": q, "sort": "stars", "per_page": 15},
        )
        for repo in (result or {}).get("items", []):
            rid = repo["full_name"]
            if rid not in seen:
                seen.add(rid)
                ext = _gh_repo_to_extension(repo)
                ext["category"] = cat
                ext["tags"].append(tag)
                exts.append(ext)
    return exts, time.time() - start


async def _fetch_github_trending_python(client) -> tuple[list[dict], float]:
    """数据源 8: GitHub Python 项目 — stars:500-5000 适中规模"""
    start = time.time()
    result = await _github_request_with_retry(
        client,
        "https://api.github.com/search/repositories",
        {"q": "language:python+stars:500..5000", "sort": "stars", "per_page": 30},
    )
    exts = [_gh_repo_to_extension(r) for r in (result or {}).get("items", [])]
    for e in exts:
        e["category"] = "trending"
        e["tags"].append("trending")
    return exts, time.time() - start


async def _fetch_github_mcp_servers(client) -> tuple[list[dict], float]:
    """数据源 9: GitHub MCP Servers — 模型上下文协议实现"""
    start = time.time()
    result = await _github_request_with_retry(
        client,
        "https://api.github.com/search/repositories",
        {"q": "topic:mcp+language:python+stars:>5", "sort": "stars", "per_page": 30},
    )
    exts = [_gh_repo_to_extension(r) for r in (result or {}).get("items", [])]
    for e in exts:
        e["category"] = "mcp"
        e["tags"].extend(["mcp", "model-context-protocol"])
    return exts, time.time() - start


async def _fetch_npm_registry(client) -> tuple[list[dict], float]:
    """数据源 5: npm Registry — vscode/pycoder 相关"""
    start = time.time()
    exts = []
    try:
        resp = await client.get(
            "https://registry.npmjs.org/-/v1/search",
            params={"text": "keywords:vscode-extension,python-tools", "size": 30},
            timeout=10,
        )
        if resp.status_code == 200:
            for obj in resp.json().get("objects", []):
                pkg = obj.get("package", {})
                name = pkg.get("name", "")
                keywords = pkg.get("keywords", [])
                exts.append(
                    {
                        "id": f"npm.{name}",
                        "name": name.split("/")[-1] if "/" in name else name,
                        "description": pkg.get("description", ""),
                        "author": pkg.get("publisher", {}).get("username", "unknown"),
                        "stars": int(
                            (obj.get("score", {}).get("detail", {}).get("popularity", 0) or 0)
                            * 10000
                        ),
                        "url": pkg.get("links", {}).get(
                            "npm", f"https://www.npmjs.com/package/{name}"
                        ),
                        "category": "npm",
                        "tags": keywords[:5],
                        "version": pkg.get("version", "latest"),
                        "installed": False,
                        "source": "npm",
                    }
                )
    except Exception as e:
        log.debug("npm_fetch_failed", error=str(e)[:100])
    return exts, time.time() - start


async def _fetch_pypi_popular(client) -> tuple[list[dict], float]:
    """数据源 6: PyPI — 热门 Python 开发工具"""
    start = time.time()
    popular = [
        "black",
        "ruff",
        "pytest",
        "mypy",
        "flake8",
        "isort",
        "pre-commit",
        "poetry",
        "click",
        "typer",
        "rich",
        "cookiecutter",
        "tox",
        "nox",
    ]
    exts = []
    for pkg in popular:
        try:
            resp = await client.get(f"https://pypi.org/pypi/{pkg}/json", timeout=5)
            if resp.status_code == 200:
                info = resp.json().get("info", {})
                exts.append(
                    {
                        "id": f"pypi.{pkg}",
                        "name": pkg,
                        "description": (info.get("summary", "") or "")[:200],
                        "author": info.get("author", info.get("maintainer", "unknown")),
                        "stars": (info.get("downloads", {}) or {}).get("releases", 0) or 0 // 1000,
                        "url": info.get("package_url", f"https://pypi.org/project/{pkg}/"),
                        "category": "pypi",
                        "tags": ["python", "pypi", pkg],
                        "version": info.get("version", "latest"),
                        "installed": False,
                        "source": "pypi",
                    }
                )
        except (httpx.HTTPError, json.JSONDecodeError, OSError) as e:
            log.debug("pypi_fetch_failed pkg=%s error=%s", pkg, e)
            continue
    return exts, time.time() - start


async def _fetch_open_vsx(client) -> tuple[list[dict], float]:
    """数据源 7: Open VSX Registry"""
    start = time.time()
    exts = []
    try:
        resp = await client.get(
            "https://open-vsx.org/api/-/search",
            params={"query": "python", "size": 30},
            timeout=10,
        )
        if resp.status_code == 200:
            for ext in resp.json().get("extensions", []):
                name = ext.get("name", "")
                ns = ext.get("namespace", "")
                files = ext.get("files", {}) or {}
                dl = files.get("download", 0) or 0
                exts.append(
                    {
                        "id": f"ovsx.{ns}.{name}",
                        "name": name,
                        "description": (ext.get("description", "") or "")[:200],
                        "author": ns or ext.get("publisher", "unknown"),
                        "stars": dl // 100,
                        "url": f"https://open-vsx.org/extension/{ns}/{name}",
                        "category": "vscode-compatible",
                        "tags": (ext.get("tags", []) or [])[:5],
                        "version": ext.get("version", "latest"),
                        "installed": False,
                        "source": "open-vsx",
                    }
                )
    except Exception as e:
        log.debug("open_vsx_fetch_failed", error=str(e)[:100])
    return exts, time.time() - start


# ══════════════════════════════════════════════════════════
# GitHub 通用重试
# ══════════════════════════════════════════════════════════

_GITHUB_RETRY_MAX = 2


async def _github_request_with_retry(client, url: str, params: dict) -> dict | None:
    headers = _gh_headers()
    for attempt in range(_GITHUB_RETRY_MAX + 1):
        try:
            resp = await client.get(url, params=params, headers=headers, timeout=_GITHUB_TIMEOUT)
            if resp.status_code == 200:
                remaining = resp.headers.get("X-RateLimit-Remaining")
                if remaining and int(remaining) < 10:
                    log.warning("github_rate_limit_low: remaining=%s", remaining)
                return resp.json()
            elif resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                if attempt < _GITHUB_RETRY_MAX:
                    await asyncio.sleep(retry_after)
                    continue
                return None
            elif resp.status_code in (403, 404):
                return None
            return None
        except (TimeoutError, Exception):
            if attempt < _GITHUB_RETRY_MAX:
                await asyncio.sleep(2**attempt)
                continue
            return None
    return None


# ══════════════════════════════════════════════════════════
# 公共 API
# ══════════════════════════════════════════════════════════

ALL_SOURCES = [
    ("github-pycoder", _fetch_github_pycoder, 10, 1.0),
    ("github-vscode", _fetch_github_vscode, 20, 0.8),
    ("github-awesome", _fetch_github_awesome, 30, 0.6),
    ("github-devtools", _fetch_github_devtools, 25, 0.7),
    ("npm-registry", _fetch_npm_registry, 40, 0.5),
    ("pypi-popular", _fetch_pypi_popular, 50, 0.4),
    ("open-vsx", _fetch_open_vsx, 35, 0.6),
    ("github-trending-python", _fetch_github_trending_python, 15, 0.9),
    ("github-mcp-servers", _fetch_github_mcp_servers, 18, 0.85),
]

_PARALLEL_TIMEOUT = 25


# GitHub 未认证 API 限流 60 req/h，串行执行，减少间隔
_GITHUB_REQ_DELAY = 0.3
_GITHUB_TIMEOUT = 10

# ── 模块级预缓存标志 ──
_cache_warm_started = False
_cache_warm_lock = asyncio.Lock()


async def search_extensions(
    query: str = "",
    category: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """搜索扩展 — 从多源智能聚合

    策略:
      - 有缓存（即使过期）立即返回，后台异步刷新
      - 无缓存时: 首次尝试同步刷新, 若失败返回种子数据+后台刷新
      - 避免请求阻塞在远程 API 调用上
    """
    cache = _load_cache()

    if cache and cache.get("extensions"):
        all_extensions = cache.get("extensions", [])
        if _is_cache_stale(cache):
            asyncio.create_task(_background_refresh())
        use_cache = True
        log.info(
            "marketplace_cache_hit total=%d stale=%s", len(all_extensions), _is_cache_stale(cache)
        )
    else:
        # 无缓存 — 先尝试实时拉取（最多等 15s），失败则返回种子
        log.info("marketplace_cache_miss_starting_inline_refresh")
        try:
            all_extensions, source_info = await asyncio.wait_for(
                _parallel_fetch_all(),
                timeout=15,
            )
            seeds = get_seed_extensions()
            seen_ids = {e["id"] for e in all_extensions if e.get("id")}
            for s in seeds:
                if s["id"] not in seen_ids:
                    all_extensions.append(s)
            all_extensions = _merge_and_dedup(all_extensions)
            _save_cache(
                {
                    "updated_at": time.time(),
                    "extensions": all_extensions,
                    "source_info": source_info,
                    "total": len(all_extensions),
                }
            )
            log.info("marketplace_inline_refresh_done total=%d", len(all_extensions))
            use_cache = True
        except (TimeoutError, OSError, Exception) as e:
            log.warning("marketplace_inline_refresh_failed error=%s", e)
            # 回退到种子数据，后台再刷新
            all_extensions = get_seed_extensions()
            asyncio.create_task(_background_refresh())
            use_cache = False

    results = _filter(all_extensions, query, category)
    paged = results[offset : offset + limit]

    return {
        "extensions": paged,
        "total": len(results),
        "total_all": len(all_extensions),
        "offset": offset,
        "limit": limit,
        "has_more": (offset + limit) < len(results),
        "sources": {
            "healthy": _source_registry.summary(),
            "used_cache": use_cache,
        },
    }


async def _background_refresh():
    """后台刷新缓存 — 从远程源拉取最新扩展数据"""
    try:
        all_extensions, source_info = await _parallel_fetch_all()
        seeds = get_seed_extensions()
        seen_ids = {e["id"] for e in all_extensions if e.get("id")}
        for s in seeds:
            if s["id"] not in seen_ids:
                seen_ids.add(s["id"])
                all_extensions.append(s)
        all_extensions = _merge_and_dedup(all_extensions)
        _save_cache(
            {
                "updated_at": time.time(),
                "extensions": all_extensions,
                "source_info": source_info,
                "total": len(all_extensions),
            }
        )
        log.info("marketplace_background_refresh_done total=%d", len(all_extensions))
    except (TimeoutError, OSError, RuntimeError) as e:
        log.warning("marketplace_background_refresh_failed error=%s", e)


async def _parallel_fetch_all() -> tuple[list[dict], dict]:
    """并行拉取所有活跃数据源"""
    import httpx

    all_extensions: list[dict] = []
    source_info: dict[str, Any] = {}
    ranked = _source_registry.get_ranked_sources()
    registered_names = set(ranked)

    async with httpx.AsyncClient(timeout=10) as client:
        tasks = []
        github_sources = {
            "github-pycoder",
            "github-vscode",
            "github-awesome",
            "github-devtools",
            "github-trending-python",
            "github-mcp-servers",
        }
        for name, fetch_func, priority, weight in ALL_SOURCES:
            if name not in registered_names:
                _source_registry.register(name, priority=priority, weight=weight)
            tasks.append((name, fetch_func))

        # GitHub 源串行执行 + 延迟避免限流
        github_results = []
        other_tasks = []
        for name, fetch_func in tasks:
            if name in github_sources:
                # 串行: 等上一个完成后等 2s 再发下一个
                if github_results:
                    await asyncio.sleep(_GITHUB_REQ_DELAY)
                r = await _fetch_with_health(name, fetch_func, client)
                github_results.append(r)
            else:
                other_tasks.append(_fetch_with_health(name, fetch_func, client))

        # 非 GitHub 源并行执行
        other_results = await asyncio.gather(*other_tasks, return_exceptions=True)

        for r in list(github_results) + list(other_results):
            if isinstance(r, Exception):
                continue
            if r is None:
                continue
            exts, sname, slatency, ok = r
            source_info[sname] = {
                "extensions_found": len(exts),
                "latency": round(slatency, 2),
                "status": "ok" if ok else "failed",
            }
            if ok:
                all_extensions.extend(exts)

        if not any(v["status"] == "ok" for v in source_info.values()):
            log.info("all_remote_sources_failed_fallback_to_seeds")

    return all_extensions, source_info


async def _fetch_with_health(
    name: str,
    fetch_func,
    client,
) -> tuple[list[dict], str, float, bool] | None:
    _source_registry.register(name)
    try:
        exts, latency = await asyncio.wait_for(fetch_func(client), timeout=10)
        _source_registry.record_success(name, latency)
        return exts, name, latency, True
    except (TimeoutError, Exception) as e:
        log.debug("source_fetch_failed", source=name, error=str(e)[:100])
        _source_registry.record_failure(name)
        return [], name, 15.0, False


# ══════════════════════════════════════════════════════════
# 合并 / 去重 / 分类
# ══════════════════════════════════════════════════════════


def _merge_and_dedup(extensions: list[dict]) -> list[dict]:
    """跨源去重合并 — 同名取最高星 + 合并标签"""
    merged: dict[str, dict] = {}
    for ext in extensions:
        ext_id = ext.get("id", "")
        if not ext_id:
            continue
        if ext_id in merged:
            existing = merged[ext_id]
            existing["stars"] = max(existing.get("stars", 0) or 0, ext.get("stars", 0) or 0)
            existing_desc = existing.get("description", "") or ""
            new_desc = ext.get("description", "") or ""
            if len(new_desc) > len(existing_desc):
                existing["description"] = new_desc
            existing_tags = set(existing.get("tags", []) or [])
            existing_tags.update(ext.get("tags", []) or [])
            existing["tags"] = sorted(existing_tags)[:10]
            sources = existing.setdefault("_sources", [])
            src = ext.get("source", "unknown")
            if src not in sources:
                sources.append(src)
        else:
            ext["_sources"] = [ext.get("source", "seed")]
            merged[ext_id] = ext
    return list(merged.values())


def _filter(extensions: list[dict], query: str, category: str) -> list[dict]:
    """筛选 + 排序"""
    results = list(extensions)
    if query:
        q = query.lower()
        results = [
            e
            for e in results
            if q in (e.get("name", "") or "").lower()
            or q in (e.get("description", "") or "").lower()
            or q in " ".join(e.get("tags", []) or [])
        ]
    if category:
        results = [
            e
            for e in results
            if e.get("category", "") == category or category in (e.get("tags", []) or [])
        ]
    results.sort(key=lambda e: -(e.get("stars", 0) or 0))
    return results


# ══════════════════════════════════════════════════════════
# 缓存
# ══════════════════════════════════════════════════════════


def _load_cache() -> dict:
    if MARKETPLACE_CACHE.exists():
        try:
            return json.loads(MARKETPLACE_CACHE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.debug("marketplace_cache_load_failed error=%s", e)
            return {}
    return {}


def _save_cache(data: dict):
    MARKETPLACE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    MARKETPLACE_CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_cache_stale(cache: dict) -> bool:
    return time.time() - (cache.get("updated_at", 0)) > CACHE_TTL


# ══════════════════════════════════════════════════════════
# GitHub 仓库 → 扩展
# ══════════════════════════════════════════════════════════


def _gh_repo_to_extension(repo: dict) -> dict:
    return {
        "id": repo["full_name"],
        "name": repo["name"],
        "description": (repo.get("description", "") or "")[:300],
        "author": repo["owner"]["login"],
        "stars": repo["stargazers_count"],
        "url": repo["html_url"],
        "category": (repo.get("language", "") or "").lower() or "unknown",
        "tags": repo.get("topics", []),
        "version": "latest",
        "installed": False,
        "source": "github",
    }


# ══════════════════════════════════════════════════════════
# 种子扩展（扩充至 50+ 个真实开发工具）
# ══════════════════════════════════════════════════════════

_ENRICHED_SEEDS: list[dict] = [
    # ── Python 代码质量 ──
    {
        "id": "astral.sh.ruff",
        "name": "Ruff",
        "description": "极速 Python linter & formatter（Rust 编写，比 Flake8 快 100 倍）",
        "author": "Astral",
        "stars": 35000,
        "category": "code-quality",
        "tags": ["linter", "formatter", "python", "rust"],
        "version": "0.9.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "psf.black",
        "name": "Black",
        "description": "毫不妥协的 Python 代码格式化工具",
        "author": "Python Software Foundation",
        "stars": 40000,
        "category": "code-quality",
        "tags": ["formatter", "python", "style"],
        "version": "25.1.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "python.mypy",
        "name": "Mypy",
        "description": "Python 静态类型检查器",
        "author": "Python Community",
        "stars": 19000,
        "category": "code-quality",
        "tags": ["type-checker", "python", "static-analysis"],
        "version": "1.14.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "PyCQA.isort",
        "name": "isort",
        "description": "Python import 排序工具",
        "author": "PyCQA",
        "stars": 7000,
        "category": "code-quality",
        "tags": ["import", "sort", "python", "formatter"],
        "version": "6.0.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "PyCQA.flake8",
        "name": "Flake8",
        "description": "Python 代码风格检查（PEP 8 + pyflakes + mccabe）",
        "author": "PyCQA",
        "stars": 10000,
        "category": "code-quality",
        "tags": ["linter", "pep8", "python"],
        "version": "7.1.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "PyCQA.pylint",
        "name": "Pylint",
        "description": "全功能 Python 静态代码分析器",
        "author": "PyCQA",
        "stars": 5500,
        "category": "code-quality",
        "tags": ["linter", "static-analysis", "python"],
        "version": "3.3.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "pytest-dev.pytest",
        "name": "Pytest",
        "description": "Python 测试框架 — 简单灵活、插件丰富",
        "author": "Pytest Dev",
        "stars": 13000,
        "category": "code-quality",
        "tags": ["test", "pytest", "python", "testing"],
        "version": "8.3.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "nedbat.coveragepy",
        "name": "Coverage.py",
        "description": "Python 代码覆盖率测量工具",
        "author": "Ned Batchelder",
        "stars": 3000,
        "category": "code-quality",
        "tags": ["coverage", "test", "python"],
        "version": "7.6.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "pre-commit.pre-commit",
        "name": "Pre-commit",
        "description": "Git 预提交钩子管理框架",
        "author": "Pre-commit",
        "stars": 13000,
        "category": "code-quality",
        "tags": ["git", "hooks", "automation", "ci"],
        "version": "4.1.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "sphinx-doc.sphinx",
        "name": "Sphinx",
        "description": "Python 文档生成器，支持 reStructuredText/Markdown",
        "author": "Sphinx",
        "stars": 7000,
        "category": "code-quality",
        "tags": ["docs", "documentation", "python"],
        "version": "8.1.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    # ── 测试工具 ──
    {
        "id": "tox-dev.tox",
        "name": "Tox",
        "description": "多 Python 版本自动化测试工具",
        "author": "Tox Dev",
        "stars": 3800,
        "category": "code-quality",
        "tags": ["test", "ci", "multi-version", "python"],
        "version": "4.23.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "nox-dev.nox",
        "name": "Nox",
        "description": "灵活的 Python 测试自动化工具（类似 tox）",
        "author": "Nox Dev",
        "stars": 1500,
        "category": "code-quality",
        "tags": ["test", "ci", "automation"],
        "version": "2024.10.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "hypothesis.hypothesis",
        "name": "Hypothesis",
        "description": "基于属性的 Python 测试框架",
        "author": "Hypothesis",
        "stars": 7500,
        "category": "code-quality",
        "tags": ["test", "property-based", "python"],
        "version": "6.120.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    # ── Git / 版本控制 ──
    {
        "id": "pycoder.gitlens",
        "name": "GitLens for PyCoder",
        "description": "Git 超级增强：行内 blame、历史对比、分支可视化。支持 git blame 和 commit log 查询",
        "author": "PyCoder Team",
        "stars": 5000,
        "category": "git",
        "tags": ["git", "productivity", "blame", "history"],
        "version": "1.0.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "pycoder.ai-commit",
        "name": "AI Commit Message",
        "description": "AI 自动生成 Git 提交信息。分析 diff 生成规范的 commit message",
        "author": "PyCoder Team",
        "stars": 2600,
        "category": "git",
        "tags": ["git", "ai", "commit", "automation"],
        "version": "1.0.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "commitizen.commitizen",
        "name": "Commitizen",
        "description": "Git 提交信息规范化工具",
        "author": "Commitizen",
        "stars": 2800,
        "category": "git",
        "tags": ["git", "commit", "conventional-commits"],
        "version": "4.0.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "gitpython.gitpython",
        "name": "GitPython",
        "description": "Python 操作 Git 的库",
        "author": "GitPython",
        "stars": 5000,
        "category": "git",
        "tags": ["git", "python", "library"],
        "version": "3.1.44",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    # ── Devops / 容器 ──
    {
        "id": "pycoder.docker",
        "name": "Docker Manager",
        "description": "Docker 容器和镜像管理。支持容器列表、启动/停止、日志查看",
        "author": "PyCoder Team",
        "stars": 3200,
        "category": "devops",
        "tags": ["docker", "container", "devops"],
        "version": "1.0.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "docker.compose",
        "name": "Docker Compose",
        "description": "多容器 Docker 应用编排工具",
        "author": "Docker Inc",
        "stars": 35000,
        "category": "devops",
        "tags": ["docker", "compose", "container", "orchestration"],
        "version": "2.32.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "ansible.ansible",
        "name": "Ansible",
        "description": "IT 自动化配置管理与应用部署",
        "author": "Red Hat",
        "stars": 65000,
        "category": "devops",
        "tags": ["automation", "configuration", "deployment", "infra"],
        "version": "11.1.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "httpie.cli",
        "name": "HTTPie",
        "description": "用户友好的 HTTP 命令行客户端",
        "author": "HTTPie",
        "stars": 35000,
        "category": "devops",
        "tags": ["http", "cli", "api", "rest"],
        "version": "3.2.4",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    # ── Web 框架 / API ──
    {
        "id": "fastapi.fastapi",
        "name": "FastAPI",
        "description": "高性能 Python Web 框架，自动生成 OpenAPI 文档",
        "author": "Sebastián Ramírez",
        "stars": 80000,
        "category": "tools",
        "tags": ["web", "api", "rest", "async", "python"],
        "version": "0.115.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "flask.pallets",
        "name": "Flask",
        "description": "轻量级 Python Web 框架",
        "author": "Pallets",
        "stars": 70000,
        "category": "tools",
        "tags": ["web", "framework", "python"],
        "version": "3.1.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "django.django",
        "name": "Django",
        "description": "全栈 Python Web 框架，自带 ORM/Admin",
        "author": "Django",
        "stars": 83000,
        "category": "tools",
        "tags": ["web", "framework", "full-stack", "python"],
        "version": "5.1.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "streamlit.streamlit",
        "name": "Streamlit",
        "description": "Python 数据应用快速构建框架",
        "author": "Snowflake",
        "stars": 38000,
        "category": "tools",
        "tags": ["data", "dashboard", "web", "ml"],
        "version": "1.41.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "gradio.gradio",
        "name": "Gradio",
        "description": "Python ML 演示 Web UI 构建工具",
        "author": "Gradio",
        "stars": 35000,
        "category": "tools",
        "tags": ["ml", "demo", "web", "ui"],
        "version": "5.12.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "pycoder.rest-client",
        "name": "REST Client",
        "description": "HTTP API 测试客户端。支持 GET/POST/PUT/DELETE 和内联请求",
        "author": "PyCoder Team",
        "stars": 2800,
        "category": "tools",
        "tags": ["http", "api", "rest", "testing"],
        "version": "1.0.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    # ── 数据科学 / 数据分析 ──
    {
        "id": "pandas.pandas",
        "name": "Pandas",
        "description": "Python 数据分析核心库（DataFrame）",
        "author": "Pandas",
        "stars": 45000,
        "category": "data-science",
        "tags": ["data", "analysis", "dataframe", "python"],
        "version": "2.2.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "numpy.numpy",
        "name": "NumPy",
        "description": "Python 科学计算基础库",
        "author": "NumPy",
        "stars": 29000,
        "category": "data-science",
        "tags": ["math", "array", "scientific", "python"],
        "version": "2.2.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "matplotlib.matplotlib",
        "name": "Matplotlib",
        "description": "Python 数据可视化库",
        "author": "Matplotlib",
        "stars": 22000,
        "category": "data-science",
        "tags": ["plot", "chart", "visualization", "python"],
        "version": "3.10.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "seaborn.seaborn",
        "name": "Seaborn",
        "description": "统计数据可视化库（基于 Matplotlib）",
        "author": "Seaborn",
        "stars": 14000,
        "category": "data-science",
        "tags": ["statistics", "plot", "visualization"],
        "version": "0.13.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "jupyter.project",
        "name": "Jupyter",
        "description": "交互式笔记本计算环境",
        "author": "Project Jupyter",
        "stars": 30000,
        "category": "data-science",
        "tags": ["notebook", "interactive", "python"],
        "version": "7.3.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "plotly.plotly",
        "name": "Plotly",
        "description": "交互式数据可视化库",
        "author": "Plotly",
        "stars": 17000,
        "category": "data-science",
        "tags": ["interactive", "plot", "chart", "web"],
        "version": "5.24.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    # ── CLI / 终端工具 ──
    {
        "id": "textual.textual",
        "name": "Textual",
        "description": "Python TUI 框架 — 构建美观的终端应用",
        "author": "Textualize",
        "stars": 28000,
        "category": "tools",
        "tags": ["tui", "terminal", "ui", "framework"],
        "version": "2.1.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "rich.textualize",
        "name": "Rich",
        "description": "Python 终端富文本美化库",
        "author": "Textualize",
        "stars": 51000,
        "category": "tools",
        "tags": ["terminal", "formatting", "color", "ui"],
        "version": "13.9.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "tiangolo.typer",
        "name": "Typer",
        "description": "Python CLI 应用构建库（基于 Click）",
        "author": "Sebastián Ramírez",
        "stars": 16000,
        "category": "tools",
        "tags": ["cli", "command-line", "python"],
        "version": "0.15.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "pallets.click",
        "name": "Click",
        "description": "Python 命令行工具构建框架",
        "author": "Pallets",
        "stars": 16000,
        "category": "tools",
        "tags": ["cli", "command-line", "python"],
        "version": "8.1.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    # ── 代码导航 / 生产力 ──
    {
        "id": "pycoder.todo-tree",
        "name": "TODO Tree",
        "description": "代码 TODO/FIXME/HACK 高亮和树视图。支持自定义正则和标签颜色",
        "author": "PyCoder Team",
        "stars": 2100,
        "category": "code-quality",
        "tags": ["todo", "productivity", "annotation"],
        "version": "1.0.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "pycoder.bookmarks",
        "name": "Code Bookmarks",
        "description": "代码书签导航。快速跳转到收藏位置，支持分组和注释",
        "author": "PyCoder Team",
        "stars": 1500,
        "category": "navigation",
        "tags": ["bookmark", "navigation", "jump"],
        "version": "1.0.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "pycoder.project-manager",
        "name": "Project Manager",
        "description": "多项目管理，快速切换工作目录。保存项目列表、最近打开",
        "author": "PyCoder Team",
        "stars": 1800,
        "category": "tools",
        "tags": ["project", "management", "workspace"],
        "version": "1.0.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "pycoder.snippets",
        "name": "Code Snippets",
        "description": "代码片段管理。保存、分类、快速插入常用代码片段",
        "author": "PyCoder Team",
        "stars": 1600,
        "category": "tools",
        "tags": ["snippet", "template", "productivity"],
        "version": "1.0.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "pycoder.markdown-preview",
        "name": "Markdown Preview",
        "description": "Markdown 预览增强。实时渲染、数学公式、目录生成",
        "author": "PyCoder Team",
        "stars": 2200,
        "category": "tools",
        "tags": ["markdown", "preview", "docs"],
        "version": "1.0.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "pycoder.test-runner",
        "name": "Test Runner",
        "description": "测试运行面板。可视化运行 pytest/unittest，实时显示进度",
        "author": "PyCoder Team",
        "stars": 1900,
        "category": "code-quality",
        "tags": ["test", "pytest", "coverage", "quality"],
        "version": "1.0.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    # ── AI / LLM / MCP ──
    {
        "id": "langchain.langchain",
        "name": "LangChain",
        "description": "LLM 应用开发框架 — 链式调用、Agent、RAG",
        "author": "LangChain",
        "stars": 100000,
        "category": "ai",
        "tags": ["llm", "ai", "chain", "agent", "rag"],
        "version": "0.3.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "llama-index.llamaindex",
        "name": "LlamaIndex",
        "description": "数据索引与 RAG 框架（连接 LLM 与外部数据）",
        "author": "LlamaIndex",
        "stars": 38000,
        "category": "ai",
        "tags": ["llm", "rag", "index", "data"],
        "version": "0.12.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "openai.openai-python",
        "name": "OpenAI Python SDK",
        "description": "OpenAI API 的 Python 客户端库",
        "author": "OpenAI",
        "stars": 25000,
        "category": "ai",
        "tags": ["openai", "api", "llm", "client"],
        "version": "1.55.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "huggingface.transformers",
        "name": "Hugging Face Transformers",
        "description": "SOTA 自然语言处理模型库",
        "author": "Hugging Face",
        "stars": 140000,
        "category": "ai",
        "tags": ["nlp", "transformers", "ml", "deep-learning"],
        "version": "4.48.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "modelcontextprotocol.servers",
        "name": "MCP Servers",
        "description": "Model Context Protocol 官方服务器集合（文件系统/Git/Slack 等）",
        "author": "Anthropic",
        "stars": 9000,
        "category": "ai",
        "tags": ["mcp", "model-context-protocol", "ai", "tools"],
        "version": "0.1.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "crewai.crewai",
        "name": "CrewAI",
        "description": "多 AI Agent 协作框架",
        "author": "CrewAI",
        "stars": 27000,
        "category": "ai",
        "tags": ["agent", "multi-agent", "ai", "framework"],
        "version": "0.108.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "autogen.autogen",
        "name": "AutoGen",
        "description": "多 Agent 对话框架（微软）",
        "author": "Microsoft",
        "stars": 38000,
        "category": "ai",
        "tags": ["agent", "multi-agent", "conversation", "ai"],
        "version": "0.7.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    # ── 数据库 / 存储 ──
    {
        "id": "sqlalchemy.sqlalchemy",
        "name": "SQLAlchemy",
        "description": "Python SQL 工具包和 ORM",
        "author": "SQLAlchemy",
        "stars": 10000,
        "category": "tools",
        "tags": ["sql", "orm", "database", "python"],
        "version": "2.0.36",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "redis.redis-py",
        "name": "Redis Python",
        "description": "Redis 数据库的 Python 客户端",
        "author": "Redis",
        "stars": 13000,
        "category": "tools",
        "tags": ["redis", "cache", "database", "python"],
        "version": "5.2.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "mongodb.motor",
        "name": "Motor",
        "description": "MongoDB 异步 Python 驱动",
        "author": "MongoDB",
        "stars": 2500,
        "category": "tools",
        "tags": ["mongodb", "database", "async", "python"],
        "version": "3.7.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    # ── 自动化 / 爬虫 ──
    {
        "id": "scrapy.scrapy",
        "name": "Scrapy",
        "description": "Python 爬虫框架",
        "author": "Scrapy",
        "stars": 55000,
        "category": "tools",
        "tags": ["crawler", "scraping", "web", "python"],
        "version": "2.12.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "selenium.selenium",
        "name": "Selenium",
        "description": "浏览器自动化测试工具",
        "author": "Selenium",
        "stars": 32000,
        "category": "tools",
        "tags": ["browser", "automation", "testing", "web"],
        "version": "4.28.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "apache.airflow",
        "name": "Apache Airflow",
        "description": "工作流调度与编排平台",
        "author": "Apache",
        "stars": 39000,
        "category": "devops",
        "tags": ["workflow", "scheduler", "pipeline", "etl"],
        "version": "2.10.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "celery.celery",
        "name": "Celery",
        "description": "分布式任务队列",
        "author": "Celery",
        "stars": 26000,
        "category": "tools",
        "tags": ["task-queue", "async", "distributed", "python"],
        "version": "5.4.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    # ── 包管理 / 构建 ──
    {
        "id": "python-poetry.poetry",
        "name": "Poetry",
        "description": "Python 依赖管理与打包工具",
        "author": "Python Poetry",
        "stars": 32000,
        "category": "tools",
        "tags": ["package", "dependency", "build", "python"],
        "version": "2.0.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "pdm.pdm",
        "name": "PDM",
        "description": "新一代 Python 包管理器（PEP 582）",
        "author": "PDM",
        "stars": 8000,
        "category": "tools",
        "tags": ["package", "dependency", "python", "pep582"],
        "version": "2.22.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "astral-sh.uv",
        "name": "uv",
        "description": "极速 Python 包管理工具（Rust 编写）",
        "author": "Astral",
        "stars": 45000,
        "category": "tools",
        "tags": ["package", "python", "fast", "rust"],
        "version": "0.6.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
    {
        "id": "cookiecutter.cookiecutter",
        "name": "Cookiecutter",
        "description": "项目脚手架生成工具",
        "author": "Cookiecutter",
        "stars": 24000,
        "category": "tools",
        "tags": ["template", "scaffold", "project", "generator"],
        "version": "2.6.0",
        "installed": False,
        "is_seed": True,
        "source": "seed",
    },
]


def get_seed_extensions() -> list[dict]:
    """获取内置推荐扩展（始终可用，零依赖）"""
    return [dict(e) for e in _ENRICHED_SEEDS]


def get_source_health_summary() -> list[dict]:
    """获取数据源健康评估"""
    return _source_registry.summary()


async def force_refresh() -> dict:
    """强制刷新扩展市场缓存（同步等待完成）

    从 GitHub/npm/PyPI 等远程源拉取最新数据，合并种子，写入缓存。

    Returns:
        {"success": True, "total": N, "sources": {...}}
    """
    try:
        all_extensions, source_info = await _parallel_fetch_all()
        seeds = get_seed_extensions()
        seen_ids = {e["id"] for e in all_extensions if e.get("id")}
        for s in seeds:
            if s["id"] not in seen_ids:
                all_extensions.append(s)
        all_extensions = _merge_and_dedup(all_extensions)
        _save_cache(
            {
                "updated_at": time.time(),
                "extensions": all_extensions,
                "source_info": source_info,
                "total": len(all_extensions),
            }
        )
        log.info("marketplace_force_refresh_done total=%d", len(all_extensions))
        return {"success": True, "total": len(all_extensions), "sources": source_info}
    except Exception as e:
        log.warning("marketplace_force_refresh_failed error=%s", e)
        return {"success": False, "error": str(e)}


def get_cache_status() -> dict:
    """获取当前缓存状态"""
    cache = _load_cache()
    if cache and cache.get("extensions"):
        return {
            "has_cache": True,
            "total": len(cache["extensions"]),
            "updated_at": cache.get("updated_at", 0),
            "age_seconds": time.time() - cache.get("updated_at", 0),
            "stale": _is_cache_stale(cache),
        }
    return {"has_cache": False, "total": 0, "stale": True}
