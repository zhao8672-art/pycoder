"""P0: RepoMap — 代码仓库智能上下文映射

借鉴 Aider 的 repomap.py，面向 Python 优先优化。
使用 ast 模块 (替代 tree-sitter) 降低依赖，PageRank 算法排序文件重要性。

核心流程:
    1. TagExtractor  — ast 提取 Python 符号 (def/class/import)
    2. GraphBuilder  — 构建文件→文件的有向依赖图
    3. PageRankRanker— PageRank 算法排序文件重要性
    4. ContextAssembler — 按 token budget 组装上下文

用法:
    from pycoder.python.repomap import RepoMap
    rmap = RepoMap(workspace=Path("/project"))
    ctx = rmap.get_repo_map(chat_files=["src/main.py"])
    # ctx 不超过 max_tokens，包含最重要的文件摘要
"""

from __future__ import annotations

import ast
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CodeTag:
    """代码符号标签"""

    fname: str  # 相对路径
    name: str  # 符号名
    kind: str  # "def" | "class" | "import" | "ref"
    line: int  # 行号 (0-indexed)


@dataclass
class FileNode:
    """依赖图中的文件节点"""

    path: str
    tags: list[CodeTag] = field(default_factory=list)
    score: float = 0.0
    content_hash: str = ""


class RepoMap:
    """仓库代码地图 — 为 LLM 提供智能上下文

    解决大型项目 (>50 files) 中 LLM 无上下文可用的问题。
    使用 ast 的 Python 符号提取 + PageRank 文件重要性排序。

    属性:
        workspace: 项目根目录
        max_tokens: 上下文最大 token 数（默认 8000）
    """

    def __init__(self, workspace: Path, max_tokens: int = 8000) -> None:
        self._workspace = workspace
        self._max_tokens = max_tokens
        self._cache: dict[str, list[CodeTag]] = {}  # file_hash → tags

    # ── 公开 API ──

    def get_repo_map(
        self,
        chat_files: list[str],
        other_files: list[str] | None = None,
    ) -> str:
        """生成仓库地图文本，供注入 system prompt。

        Args:
            chat_files: 用户正在编辑/关注的文件（优先包含）
            other_files: 仓库中的其他文件（自动扫描如果未提供）

        Returns:
            token 预算内的 Markdown 格式仓库地图文本
        """
        all_tags: dict[str, list[CodeTag]] = {}

        # 1. 提取所有文件的标签
        for f in chat_files:
            all_tags[f] = self._extract_tags(Path(f))

        if other_files is None:
            other_files = self._scan_python_files()
        for f in other_files:
            if f not in all_tags:
                tags = self._extract_tags(Path(f))
                if tags:
                    all_tags[f] = tags

        if not all_tags:
            return ""

        # 2. 构建依赖图
        graph = self._build_dependency_graph(all_tags)

        # 3. PageRank 排序
        scores = self._pagerank(graph)

        # 4. 按 token 预算组装
        return self._assemble_context(all_tags, scores, chat_files)

    def get_repo_map_compact(self, chat_files: list[str]) -> str:
        """紧凑版 — 仅返回最高排名的 5 个文件的摘要"""
        all_tags: dict[str, list[CodeTag]] = {}
        for f in chat_files:
            all_tags[f] = self._extract_tags(Path(f))
        for f in self._scan_python_files()[:30]:
            if f not in all_tags:
                tags = self._extract_tags(Path(f))
                if tags:
                    all_tags[f] = tags
        scores = self._pagerank(self._build_dependency_graph(all_tags))
        top5 = sorted(scores, key=scores.get, reverse=True)[:5]
        return self._assemble_context(all_tags, {k: scores[k] for k in top5}, chat_files)

    def invalidate_cache(self, file_path: str | None = None) -> None:
        """使缓存失效。file_path 为 None 时清空全部缓存。"""
        if file_path is None:
            self._cache.clear()
        else:
            self._cache.pop(file_path, None)

    # ── 标签提取 ──

    def _extract_tags(self, file_path: Path) -> list[CodeTag]:
        """使用 ast 模块提取 Python 符号定义和引用"""
        full = self._workspace / file_path
        content_hash = self._hash_file(full)
        if content_hash in self._cache:
            return self._cache[content_hash]

        try:
            source = full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []

        tags: list[CodeTag] = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return tags

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                tags.append(
                    CodeTag(
                        fname=str(file_path),
                        name=node.name,
                        kind="def",
                        line=node.lineno - 1,
                    )
                )
            elif isinstance(node, ast.AsyncFunctionDef):
                tags.append(
                    CodeTag(
                        fname=str(file_path),
                        name=node.name,
                        kind="def",
                        line=node.lineno - 1,
                    )
                )
            elif isinstance(node, ast.ClassDef):
                tags.append(
                    CodeTag(
                        fname=str(file_path),
                        name=node.name,
                        kind="class",
                        line=node.lineno - 1,
                    )
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    tags.append(
                        CodeTag(
                            fname=str(file_path),
                            name=alias.name or "",
                            kind="import",
                            line=node.lineno - 1,
                        )
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                tags.append(
                    CodeTag(
                        fname=str(file_path),
                        name=node.module,
                        kind="import",
                        line=node.lineno - 1,
                    )
                )

        self._cache[content_hash] = tags
        return tags

    # ── 依赖图构建 ──

    def _build_dependency_graph(
        self, all_tags: dict[str, list[CodeTag]]
    ) -> dict[str, set[str]]:
        """构建文件→文件的有向依赖图。

        如果文件 A 导入了模块 M，且模块 M 对应仓库内文件 B，
        则存在边 A→B (A 依赖 B)。被依赖越多的文件越重要。
        """
        graph: dict[str, set[str]] = defaultdict(set)
        for fname in all_tags:
            graph[fname]  # 确保每个文件都有入口

        for fname, tags in all_tags.items():
            for tag in tags:
                if tag.kind != "import":
                    continue
                # 尝试将 import 模块名映射到仓库内文件
                for other in all_tags:
                    if other == fname:
                        continue
                    mod_name = other.replace("/", ".").replace("\\", ".").replace(".py", "")
                    if mod_name.endswith(tag.name) or tag.name in mod_name:
                        graph[fname].add(other)

        return dict(graph)

    # ── PageRank ──

    def _pagerank(
        self,
        graph: dict[str, set[str]],
        damping: float = 0.85,
        iterations: int = 20,
    ) -> dict[str, float]:
        """简化 PageRank — 文件重要性排序。

        被越多文件引用的文件获得越高的 PageRank 分数。
        聊天文件通过 chat_files 优先排序（在 _assemble_context 中处理）。
        """
        nodes = list(graph.keys())
        n = len(nodes)
        if n == 0:
            return {}
        if n == 1:
            return {nodes[0]: 1.0}

        scores: dict[str, float] = dict.fromkeys(nodes, 1.0 / n)

        for _ in range(iterations):
            new_scores: dict[str, float] = dict.fromkeys(nodes, (1.0 - damping) / n)
            for node in nodes:
                out_links = graph.get(node, set())
                if not out_links:
                    continue
                share = damping * scores[node] / len(out_links)
                for target in out_links:
                    new_scores[target] += share
            scores = new_scores

        return scores

    # ── 上下文组装 ──

    def _assemble_context(
        self,
        all_tags: dict[str, list[CodeTag]],
        scores: dict[str, float],
        chat_files: list[str],
    ) -> str:
        """按 token 预算组装可注入的仓库地图 Markdown"""
        # 优先包含 chat_files
        sorted_files = sorted(
            all_tags.keys(),
            key=lambda f: (f not in chat_files, -scores.get(f, 0)),
        )

        lines: list[str] = ["# Repository Map\n"]
        token_count = len(lines[0])

        for fname in sorted_files:
            tags = all_tags[fname]
            def_only = [t for t in tags if t.kind in ("def", "class")]
            if not def_only:
                continue

            entry = f"\n## {fname}\n"
            for t in sorted(def_only, key=lambda x: x.line)[:10]:
                indent = "  " if t.kind == "def" else ""
                entry += f"{indent}{t.kind} {t.name} (line {t.line + 1})\n"

            token_count += len(entry) // 4  # 粗略 token 估算
            if token_count > self._max_tokens:
                lines.append("\n... (truncated for token budget)")
                break
            lines.append(entry)

        return "".join(lines)

    # ── 工具方法 ──

    def _scan_python_files(self) -> list[str]:
        """扫描工作区所有 .py 文件（排除缓存和虚拟环境）"""
        files: list[str] = []
        exclude_dirs = {"__pycache__", ".venv", "venv", ".git", "node_modules", "dist", "build"}
        for py_file in self._workspace.rglob("*.py"):
            parts = set(py_file.parts)
            if parts & exclude_dirs:
                continue
            try:
                rel = py_file.relative_to(self._workspace)
                files.append(str(rel))
            except ValueError:
                continue
        return files

    @staticmethod
    def _hash_file(path: Path) -> str:
        """计算文件 MD5 哈希用于缓存"""
        try:
            return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()
        except OSError:
            return ""


# ── 全局单例 ──

_repo_map: RepoMap | None = None


def get_repo_map(workspace: Path | None = None, max_tokens: int = 8000) -> RepoMap:
    """获取或创建 RepoMap 单例"""
    global _repo_map
    if _repo_map is None:
        from pycoder.server.routers.files import get_workspace_root

        ws = workspace or Path(get_workspace_root())
        _repo_map = RepoMap(workspace=ws, max_tokens=max_tokens)
    return _repo_map


def reset_repo_map() -> None:
    """重置 RepoMap 单例（测试用）"""
    global _repo_map
    _repo_map = None
