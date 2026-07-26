"""
技能市场增强数据源模块 — Phase 1

新增数据源:
1. OSSInsight API — 200+ 技术分类实时排名
2. O*NET 技能分类标准 — 标准化技能分类体系
3. GitHub 认证请求 — 支持 GITHUB_TOKEN, 速率限制+指数退避
4. 多级缓存 — Memory → SQLite → 全量同步

用法:
    from pycoder.server.skills_data_sources import (
        OssinsightClient,
        ONET_TAXONOMY_MAP,
        make_github_request,
        MultiLevelCache,
        classify_with_onet,
    )
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pycoder.core.services.log import log

# ──────────────────────────────────────────────
# 1. GitHub 认证请求 + 指数退避重试
# ──────────────────────────────────────────────


def _get_github_token() -> str:
    """获取 GitHub Token, 优先级: 环境变量 > ~/.pycoder/config.json"""
    token = os.environ.get("GITHUB_TOKEN", "") or os.environ.get("GH_TOKEN", "")
    if token:
        return token
    # 尝试从 config.json 读取
    config_path = Path.home() / ".pycoder" / "config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            token = cfg.get("github_token", "") or cfg.get("github", {}).get("token", "")
        except Exception:
            pass
    return token


def _check_rate_limit(headers: dict) -> dict:
    """检查 GitHub API 速率限制头, 返回剩余次数和重置时间"""
    remaining = int(headers.get("X-RateLimit-Remaining", 0))
    reset_at = int(headers.get("X-RateLimit-Reset", 0))
    limit = int(headers.get("X-RateLimit-Limit", 60))
    now = int(time.time())
    return {
        "limit": limit,
        "remaining": remaining,
        "reset_at": reset_at,
        "reset_in_seconds": max(0, reset_at - now),
        "is_authenticated": limit > 60,  # 认证后 5000, 匿名 60
    }


def make_github_request(
    url: str,
    max_retries: int = 3,
    timeout: int = 30,
) -> dict | list:
    """执行 GitHub API 请求 (认证 + 速率限制感知 + 指数退避)

    Args:
        url: GitHub API URL
        max_retries: 最大重试次数 (默认 3)
        timeout: 请求超时秒数 (默认 30)

    Returns:
        解析后的 JSON 响应

    Raises:
        RuntimeError: 超过最大重试次数或遇到不可恢复错误
    """
    import urllib.error
    import urllib.request
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"不允许的 URL 协议: {parsed.scheme}")

    token = _get_github_token()
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "PyCoder-Skills-Bot/3.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                # 检查速率限制
                rate_info = _check_rate_limit(resp.headers)
                if rate_info["remaining"] < 5:
                    sleep_time = rate_info["reset_in_seconds"] + 1
                    log.warning(
                        "github_rate_limit_low",
                        remaining=rate_info["remaining"],
                        reset_in=sleep_time,
                    )
                    if attempt < max_retries:
                        time.sleep(min(sleep_time, 60))
                        continue

                if not rate_info["is_authenticated"]:
                    log.warning(
                        "github_no_token",
                        remaining=rate_info["remaining"],
                        message="考虑设置 GITHUB_TOKEN 环境变量以提升配额到 5000/小时",
                    )

                return json.loads(resp.read().decode())

        except urllib.error.HTTPError as e:
            status = e.code
            if status == 403:
                # 速率限制或权限不足
                rate_info = _check_rate_limit(e.headers)
                wait = min(rate_info["reset_in_seconds"] + 1, 120)
                log.warning(
                    "github_http_403",
                    url=url[:60],
                    attempt=attempt,
                    wait=wait,
                    remaining=rate_info["remaining"],
                )
                last_error = e
                if attempt < max_retries:
                    time.sleep(wait)
                    continue
                raise RuntimeError(
                    f"GitHub API 403 (配额耗尽?): {e}, "
                    f"重置时间: {rate_info['reset_in_seconds']}s"
                ) from e
            elif status == 404:
                raise RuntimeError(f"GitHub API 404: {url}") from e
            elif status >= 500:
                last_error = e
                wait = min(2 ** attempt * 5, 60)
                log.warning("github_http_5xx", status=status, attempt=attempt, wait=wait)
                if attempt < max_retries:
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"GitHub API {status} after {max_retries} retries") from e
            else:
                raise RuntimeError(f"GitHub API {status}: {e}") from e

        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last_error = e
            wait = min(2 ** attempt * 3, 30)
            log.warning("github_network_error", error=str(e)[:60], attempt=attempt, wait=wait)
            if attempt < max_retries:
                time.sleep(wait)
                continue
            raise RuntimeError(f"GitHub 网络错误 after {max_retries} retries: {e}") from e

    raise RuntimeError(f"GitHub 请求失败 after {max_retries} retries: {last_error}")


# ──────────────────────────────────────────────
# 2. O*NET 技能分类标准 (精简版)
# ──────────────────────────────────────────────

ONET_TAXONOMY_MAP: dict[str, dict[str, Any]] = {
    # === 编程语言 ===
    "programming-language": {
        "onet_code": "15-1252.00",
        "onet_name": "Software Developers",
        "description": "编程语言技能",
        "subcategories": {
            "python": {"keywords": ["python", "django", "flask", "fastapi", "pytorch"],
                       "onet_skill": "2.C.4.a"},
            "javascript": {"keywords": ["javascript", "typescript", "node.js", "nodejs",
                                        "react", "vue", "angular", "svelte"],
                           "onet_skill": "2.C.4.a"},
            "rust": {"keywords": ["rust", "cargo", "wasm"],
                     "onet_skill": "2.C.4.a"},
            "go": {"keywords": ["golang", "go-lang", "go language"],
                   "onet_skill": "2.C.4.a"},
            "java": {"keywords": ["java", "spring", "kotlin", "jvm"],
                     "onet_skill": "2.C.4.a"},
            "cpp": {"keywords": ["c++", "cpp", "c-plus-plus"],
                    "onet_skill": "2.C.4.a"},
        },
    },
    # === AI/ML ===
    "ai-ml": {
        "onet_code": "15-2051.00",
        "onet_name": "Data Scientists",
        "description": "人工智能与机器学习",
        "subcategories": {
            "llm": {"keywords": ["llm", "gpt", "deepseek", "claude", "gemini",
                                 "openai", "anthropic", "language model"],
                    "onet_skill": "2.C.4.a"},
            "ml-framework": {"keywords": ["pytorch", "tensorflow", "jax", "keras",
                                          "scikit-learn", "transformers"],
                             "onet_skill": "2.C.4.a"},
            "agent": {"keywords": ["agent", "autonomous", "agentic", "multi-agent",
                                   "react", "tool-use", "function calling"],
                      "onet_skill": "2.C.4.a"},
            "rag": {"keywords": ["rag", "retrieval", "vector-search", "embedding",
                                 "chroma", "pinecone", "weaviate"],
                    "onet_skill": "2.C.4.a"},
        },
    },
    # === Web 开发 ===
    "web": {
        "onet_code": "15-1254.00",
        "onet_name": "Web Developers",
        "description": "Web 开发技术与框架",
        "subcategories": {
            "frontend": {"keywords": ["react", "vue", "angular", "svelte", "next.js",
                                      "nuxt", "css", "html", "tailwind", "bootstrap"],
                         "onet_skill": "2.C.4.a"},
            "backend": {"keywords": ["fastapi", "express", "spring", "django", "flask",
                                     "gin", "echo", "actix"],
                        "onet_skill": "2.C.4.a"},
            "api": {"keywords": ["rest", "graphql", "grpc", "openapi", "swagger"],
                    "onet_skill": "2.C.4.a"},
        },
    },
    # === 数据库 ===
    "database": {
        "onet_code": "15-1242.00",
        "onet_name": "Database Administrators",
        "description": "数据库技术与存储",
        "subcategories": {
            "relational": {"keywords": ["postgresql", "mysql", "sqlite", "mariadb",
                                        "oracle", "sql-server"],
                           "onet_skill": "2.C.4.a"},
            "nosql": {"keywords": ["mongodb", "redis", "cassandra", "dynamodb",
                                   "couchbase", "neo4j"],
                      "onet_skill": "2.C.4.a"},
            "vector": {"keywords": ["vector-database", "chroma", "pinecone",
                                    "weaviate", "qdrant", "milvus"],
                       "onet_skill": "2.C.4.a"},
        },
    },
    # === DevOps/云原生 ===
    "devops": {
        "onet_code": "15-1243.00",
        "onet_name": "DevOps Engineers",
        "description": "DevOps 与云原生技术",
        "subcategories": {
            "container": {"keywords": ["docker", "kubernetes", "k8s", "containerd",
                                       "podman"],
                          "onet_skill": "2.C.4.a"},
            "ci-cd": {"keywords": ["ci/cd", "github-actions", "gitlab-ci", "jenkins",
                                   "argocd", "terraform"],
                      "onet_skill": "2.C.4.a"},
            "cloud": {"keywords": ["aws", "azure", "gcp", "cloud", "serverless",
                                   "lambda"],
                      "onet_skill": "2.C.4.a"},
        },
    },
    # === 安全 ===
    "security": {
        "onet_code": "15-1212.00",
        "onet_name": "Information Security Analysts",
        "description": "信息安全与渗透测试",
        "subcategories": {
            "appsec": {"keywords": ["security", "appsec", "owasp", "vulnerability",
                                    "penetration", "pentest"],
                       "onet_skill": "2.C.4.a"},
            "crypto": {"keywords": ["cryptography", "encryption", "tls", "ssl",
                                    "zero-knowledge"],
                       "onet_skill": "2.C.4.a"},
        },
    },
    # === MCP/工具 ===
    "mcp-tools": {
        "onet_code": "15-1255.00",
        "onet_name": "Web and Digital Interface Designers",
        "description": "MCP 服务器与 AI 工具链",
        "subcategories": {
            "mcp-server": {"keywords": ["mcp", "model-context-protocol", "mcp-server",
                                        "mcp-client", "tool-server"],
                           "onet_skill": "2.C.4.a"},
            "prompt": {"keywords": ["prompt", "prompt-engineer", "prompt-template"],
                       "onet_skill": "2.C.4.a"},
        },
    },
    # === 测试 ===
    "testing": {
        "onet_code": "15-1253.00",
        "onet_name": "Software Quality Assurance Analysts",
        "description": "软件测试与质量保证",
        "subcategories": {
            "unit-test": {"keywords": ["pytest", "jest", "unittest", "vitest",
                                       "mocha", "junit"],
                          "onet_skill": "2.C.4.a"},
            "e2e-test": {"keywords": ["playwright", "cypress", "selenium", "puppeteer"],
                         "onet_skill": "2.C.4.a"},
        },
    },
}


def classify_with_onet(name: str, description: str, tags: list[str] = None) -> str:
    """使用 O*NET 分类标准进行技能分类

    Args:
        name: 技能名称
        description: 技能描述
        tags: 技能标签列表

    Returns:
        O*NET 分类编码 (如 'programming-language', 'ai-ml')
    """
    text = (name + " " + (description or "")).lower()
    if tags:
        text += " " + " ".join(t.lower() for t in tags)

    for category_id, category_info in ONET_TAXONOMY_MAP.items():
        for sub_id, sub_info in category_info["subcategories"].items():
            if any(kw in text for kw in sub_info["keywords"]):
                return category_id

    # 兜底: 使用关键词推断
    categories_flat = {
        "programming-language": ["language", "compile", "runtime", "sdk", "code"],
        "ai-ml": ["ai", "ml", "model", "neural", "train", "inference", "dataset"],
        "web": ["http", "web", "browser", "cdn", "middleware", "render"],
        "database": ["sql", "db", "store", "cache", "storage", "query"],
        "devops": ["pipeline", "deploy", "monitor", "infra", "orchestrate"],
        "security": ["threat", "exploit", "auth", "permission", "audit"],
        "mcp-tools": ["tool", "plugin", "extension", "integration"],
        "testing": ["benchmark", "coverage", "assert", "mock", "stub"],
    }
    for cat, keywords in categories_flat.items():
        if any(kw in text for kw in keywords):
            return cat
    return "other"


# ──────────────────────────────────────────────
# 3. OSSInsight 分类排名 API
# ──────────────────────────────────────────────

@dataclass
class OssinsightCollection:
    """OSSInsight 集合/分类"""

    id: str
    name: str
    url: str


# 与 PyCoder 技能市场相关的 OSSInsight 分类
OSSINSIGHT_COLLECTIONS = [
    OssinsightCollection("ai-agent-frameworks", "AI Agent 框架",
                         "https://ossinsight.io/collections/ai-agent-frameworks"),
    OssinsightCollection("llm-devtools", "LLM 开发工具",
                         "https://ossinsight.io/collections/llm-devtools"),
    OssinsightCollection("llm-tools", "LLM 工具",
                         "https://ossinsight.io/collections/llm-tools"),
    OssinsightCollection("model-context-protocol-mcp-client", "MCP 客户端",
                         "https://ossinsight.io/collections/model-context-protocol-mcp-client"),
    OssinsightCollection("artificial-intelligence", "人工智能",
                         "https://ossinsight.io/collections/artificial-intelligence"),
    OssinsightCollection("programming-language", "编程语言",
                         "https://ossinsight.io/collections/programming-language"),
    OssinsightCollection("web-framework", "Web 框架",
                         "https://ossinsight.io/collections/web-framework"),
    OssinsightCollection("testing-tools", "测试工具",
                         "https://ossinsight.io/collections/testing-tools"),
    OssinsightCollection("security-tool", "安全工具",
                         "https://ossinsight.io/collections/security-tool"),
    OssinsightCollection("database", "数据库",
                         "https://ossinsight.io/collections/database"),
    OssinsightCollection("vector-database--vector-store", "向量数据库",
                         "https://ossinsight.io/collections/vector-database--vector-store"),
    OssinsightCollection("cicd", "CI/CD",
                         "https://ossinsight.io/collections/cicd"),
    OssinsightCollection("documentation-generator", "文档生成器",
                         "https://ossinsight.io/collections/documentation-generator"),
    OssinsightCollection("static-site-generator", "静态站点生成器",
                         "https://ossinsight.io/collections/static-site-generator"),
    OssinsightCollection("graphrag---knowledge-graph-based-rag", "GraphRAG",
                         "https://ossinsight.io/collections/graphrag---knowledge-graph-based-rag"),
    OssinsightCollection("chatgpt-alternatives", "ChatGPT 替代方案",
                         "https://ossinsight.io/collections/chatgpt-alternatives"),
]


@dataclass
class OssinsightRankItem:
    """OSSInsight 排名项"""
    rank: int
    repo_name: str
    stars_28d: int
    stars_total: int
    change_pct: float
    collection_id: str


class OssinsightClient:
    """OSSInsight API 客户端 — 获取 GitHub 技术分类排名"""

    BASE_URL = "https://ossinsight.io/api"

    def __init__(self):
        self._cache: dict[str, list[OssinsightRankItem]] = {}
        self._cache_time: float = 0
        self._cache_ttl: float = 3600  # 1 小时

    def fetch_collection_ranking(self, collection_id: str) -> list[OssinsightRankItem]:
        """获取指定分类的 28 天排名数据

        通过 OSSInsight 公共 SQL API 获取排名。
        当 API 不可用时返回空列表。
        """
        import urllib.error

        url = f"{self.BASE_URL}/collections/{collection_id}/ranking"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "PyCoder-Skills-Bot/3.0"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())

            items = []
            # OSSInsight 排名返回结构可能变化, 稳健解析
            rows = data.get("data", []) if isinstance(data, dict) else data
            if isinstance(rows, list):
                for i, row in enumerate(rows):
                    if isinstance(row, dict):
                        items.append(OssinsightRankItem(
                            rank=i + 1,
                            repo_name=row.get("repo_name", row.get("name", "")),
                            stars_28d=int(row.get("stars", row.get("stars_28d", 0))),
                            stars_total=int(row.get("stars_total", 0)),
                            change_pct=float(row.get("change_pct", row.get("change", 0))),
                            collection_id=collection_id,
                        ))
            return items[:50]

        except (urllib.error.HTTPError, urllib.error.URLError, OSError,
                json.JSONDecodeError, TimeoutError) as e:
            log.debug("ossinsight_fetch_failed", collection=collection_id, error=str(e)[:60])
            return []

    def fetch_all_collections(self) -> dict[str, list[OssinsightRankItem]]:
        """获取所有配置分类的排名"""
        result = {}
        for col in OSSINSIGHT_COLLECTIONS:
            items = self.fetch_collection_ranking(col.id)
            if items:
                result[col.id] = items
                log.info("ossinsight_collection_fetched", collection=col.id, count=len(items))
            # 避免请求过快
            time.sleep(0.5)
        self._cache = result
        self._cache_time = time.time()
        return result

    def get_trending_repos(self, min_stars_28d: int = 5) -> list[OssinsightRankItem]:
        """获取所有分类中的热门仓库 (28天 star 增长)"""
        if time.time() - self._cache_time > self._cache_ttl:
            self.fetch_all_collections()

        all_items = []
        for collection_id, items in self._cache.items():
            for item in items:
                if item.stars_28d >= min_stars_28d:
                    all_items.append(item)
        # 按 28 天 star 排序
        all_items.sort(key=lambda x: x.stars_28d, reverse=True)
        return all_items[:100]

    def get_trending_by_category(
        self, collection_id: str, min_stars_28d: int = 0
    ) -> list[OssinsightRankItem]:
        """获取指定分类的排名"""
        if time.time() - self._cache_time > self._cache_ttl:
            items = self.fetch_collection_ranking(collection_id)
            self._cache[collection_id] = items
        else:
            items = self._cache.get(collection_id, [])
        return [i for i in items if i.stars_28d >= min_stars_28d]


# 全局单例
_ossinsight_client: OssinsightClient | None = None


def get_ossinsight_client() -> OssinsightClient:
    global _ossinsight_client
    if _ossinsight_client is None:
        _ossinsight_client = OssinsightClient()
    return _ossinsight_client


# ──────────────────────────────────────────────
# 4. 多级缓存 (Memory → SQLite)
# ──────────────────────────────────────────────


class MultiLevelCache:
    """多级技能缓存

    层级:
        L1: 内存字典 (TTL 5 分钟)
        L2: SQLite 文件 (TTL 24 小时)
        L3: 全量同步 (手动触发)
    """

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = Path(os.getcwd()) / "data" / "skills" / "cache.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # L1: 内存
        self._memory: dict[str, dict] = {}
        self._memory_time: float = 0
        self._memory_ttl: float = 300  # 5 分钟

        # L2: SQLite
        self._init_sqlite()

    def _init_sqlite(self):
        """初始化 SQLite 缓存表"""
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS skills_cache (
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    ttl REAL NOT NULL DEFAULT 86400
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_skills_cache_created
                ON skills_cache(created_at)
            """)
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            log.warning("cache_db_init_failed", error=str(e))

    def get(self, key: str) -> dict | None:
        """从缓存获取

        优先 L1 (内存), 其次 L2 (SQLite)
        """
        now = time.time()

        # L1
        if now - self._memory_time < self._memory_ttl:
            val = self._memory.get(key)
            if val is not None:
                return val

        # L2
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5)
            cursor = conn.execute(
                "SELECT data, created_at, ttl FROM skills_cache WHERE key = ?",
                (key,),
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                data, created_at, ttl = row
                if now - created_at < ttl:
                    # 提升到 L1
                    parsed = json.loads(data)
                    self._memory[key] = parsed
                    self._memory_time = now
                    return parsed
                else:
                    # 过期, 删除
                    self.delete(key)
        except (sqlite3.Error, json.JSONDecodeError) as e:
            log.debug("cache_read_failed", key=key, error=str(e))

        return None

    def set(self, key: str, data: dict, ttl: float = 86400):
        """写入缓存 (L1 + L2)"""
        now = time.time()

        # L1
        self._memory[key] = data
        self._memory_time = now

        # L2
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5)
            conn.execute(
                "INSERT OR REPLACE INTO skills_cache"
                " (key, data, created_at, ttl) VALUES (?, ?, ?, ?)",
                (key, json.dumps(data, ensure_ascii=False), now, ttl),
            )
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            log.debug("cache_write_failed", key=key, error=str(e))

    def delete(self, key: str):
        """删除缓存"""
        self._memory.pop(key, None)
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5)
            conn.execute("DELETE FROM skills_cache WHERE key = ?", (key,))
            conn.commit()
            conn.close()
        except sqlite3.Error:
            pass

    def clear_expired(self):
        """清除过期缓存"""
        now = time.time()
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5)
            conn.execute("DELETE FROM skills_cache WHERE ? - created_at >= ttl", (now,))
            conn.commit()
            conn.close()
        except sqlite3.Error:
            pass

    def stats(self) -> dict:
        """缓存统计"""
        l1_count = len(self._memory)
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5)
            cursor = conn.execute("SELECT COUNT(*) FROM skills_cache")
            l2_count = cursor.fetchone()[0]
            conn.close()
        except sqlite3.Error:
            l2_count = 0
        return {
            "memory_count": l1_count,
            "sqlite_count": l2_count,
            "memory_ttl_seconds": self._memory_ttl,
        }
