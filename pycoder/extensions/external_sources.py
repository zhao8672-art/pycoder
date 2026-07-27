"""
外部扩展数据源采集器 — 大幅扩充扩展市场数量

扩展外部数据源的两种方式:
1. 通过 GitHub API 搜索热门 Python 工具仓库
2. 解析 Awesome 列表中的工具

用法:
    from pycoder.extensions.external_sources import import_external_extensions
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from pycoder.core.services.log import log
from pycoder.core.services.net import make_github_request


def import_external_extensions() -> dict:
    """从外部数据源采集扩展，写入扩展缓存文件

    策略:
      1. 从 GitHub Search API 获取热门 Python 仓库 (stars>2000)
      2. 合并现有缓存
      3. 去重后写回缓存文件

    Returns:
        导入统计
    """
    cache_path = Path.home() / ".pycoder" / "external_extensions_cache.json"
    source_health_path = Path.home() / ".pycoder" / "source_health.json"

    # 1. 读取现有缓存
    existing: list[dict] = []
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            existing = data.get("extensions", [])
        except (json.JSONDecodeError, OSError):
            pass
    existing_ids = {e["id"] for e in existing if e.get("id")}

    # 2. 从 GitHub Search 采集热门 Python 仓库
    new_extensions: list[dict] = []
    search_queries = [
        # Python 开发工具 (大范围)
        {"q": "language:python+topic:developer-tools+stars:>500", "sort": "stars", "per_page": 50},
        {"q": "language:python+topic:cli+stars:>1000", "sort": "stars", "per_page": 50},
        {"q": "language:python+stars:>10000", "sort": "stars", "per_page": 50},
        # AI/ML 工具
        {"q": "language:python+topic:ai+stars:>3000", "sort": "stars", "per_page": 50},
        {"q": "language:python+topic:llm+stars:>1000", "sort": "stars", "per_page": 50},
        {"q": "language:python+topic:machine-learning+stars:>5000", "sort": "stars", "per_page": 30},
        # 测试/代码质量
        {"q": "language:python+topic:testing+stars:>1000", "sort": "stars", "per_page": 30},
        {"q": "language:python+topic:linter+stars:>200", "sort": "stars", "per_page": 30},
        # Web 框架
        {"q": "language:python+topic:web-framework+stars:>2000", "sort": "stars", "per_page": 30},
        {"q": "language:python+topic:api+stars:>2000", "sort": "stars", "per_page": 30},
        # 数据库/存储
        {"q": "language:python+topic:database+stars:>2000", "sort": "stars", "per_page": 30},
        # DevOps
        {"q": "language:python+topic:devops+stars:>1000", "sort": "stars", "per_page": 30},
        # 通用高星
        {"q": "language:python+topic:framework+stars:>5000", "sort": "stars", "per_page": 30},
    ]

    seen_urls: set[str] = set()
    added = 0

    for query in search_queries:
        try:
            q_str = "&".join(f"{k}={v}" for k, v in query.items())
            url = f"https://api.github.com/search/repositories?{q_str}"
            data = make_github_request(url)
        except RuntimeError as e:
            log.warning("external_ext_search_failed", query=query["q"][:40], error=str(e)[:60])
            continue

        for item in data.get("items", []):
            repo_url = item.get("html_url", "")
            if repo_url in seen_urls:
                continue
            seen_urls.add(repo_url)

            repo_id = item.get("full_name", "").replace("/", ".").lower()
            if repo_id in existing_ids:
                continue

            name = item.get("name", "")
            desc = (item.get("description") or "")[:200]
            stars = item.get("stargazers_count", 0)
            topics = item.get("topics", [])[:5]
            author = item.get("owner", {}).get("login", "")
            language = item.get("language", "Unknown")

            # 推断分类
            category = "tools"
            text_for_cat = (name + " " + desc + " " + " ".join(topics)).lower()
            if any(kw in text_for_cat for kw in ["test", "pytest", "unittest", "coverage"]):
                category = "code-quality"
            elif any(kw in text_for_cat for kw in ["ai", "ml", "llm", "agent", "chatgpt", "gpt"]):
                category = "ai"
            elif any(kw in text_for_cat for kw in ["web", "api", "fastapi", "flask", "django"]):
                category = "web"
            elif any(kw in text_for_cat for kw in ["database", "sql", "orm", "sqlalchemy"]):
                category = "data-science"
            elif any(kw in text_for_cat for kw in ["docker", "k8s", "kubernetes", "devops", "deploy"]):
                category = "devops"
            elif any(kw in text_for_cat for kw in ["linter", "format", "lint", "style"]):
                category = "code-quality"
            elif any(kw in text_for_cat for kw in ["cli", "command", "terminal"]):
                category = "tools"

            ext = {
                "id": repo_id,
                "name": name.replace("-", " ").title(),
                "description": desc,
                "author": author,
                "stars": stars,
                "category": category,
                "tags": topics,
                "version": "1.0.0",
                "installed": False,
                "is_seed": True,
                "source": "external",
                "url": repo_url,
                "language": language,
            }
            new_extensions.append(ext)
            existing_ids.add(repo_id)
            added += 1

    if not new_extensions:
        return {"success": True, "added": 0, "total": len(existing), "message": "无新增扩展"}

    # 3. 合并并写回缓存
    all_exts = existing + new_extensions
    cache_data = {
        "updated_at": time.time(),
        "extensions": all_exts,
        "source_info": {
            "external_import": {
                "name": "外部扩展导入",
                "success": True,
                "count": added,
                "total": len(all_exts),
            }
        },
        "total": len(all_exts),
    }
    cache_path.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 更新 source_health
    health = {}
    if source_health_path.exists():
        try:
            health = json.loads(source_health_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    health["external_import"] = {
        "added": added,
        "total": len(all_exts),
        "timestamp": time.time(),
    }
    source_health_path.write_text(json.dumps(health, ensure_ascii=False, indent=2), encoding="utf-8")

    log.info("external_extensions_imported", added=added, total=len(all_exts))
    return {
        "success": True,
        "added": added,
        "total": len(all_exts),
        "message": f"新增 {added} 个扩展，总计 {len(all_exts)} 个",
    }
