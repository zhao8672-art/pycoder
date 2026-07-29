"""项目虚拟文件索引 — 增量缓存 + 符号索引 + SQLite 持久化

功能:
  1. 扫描整个项目，构建文件摘要索引
  2. 增量更新：仅重新索引有变更的文件
  3. 符号索引：按类/函数名快速定位文件
  4. SQLite 持久化：跨会话复用索引

使用场景:
    indexer = ProjectIndex()
    indexer.scan_project("src/")
    files = indexer.find_symbol("MyClass")  # 快速查找符号所在文件
    summary = indexer.export_summary()       # 导出索引摘要供 AI 上下文使用
"""

from __future__ import annotations

import ast
import hashlib
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from pycoder.io.file_indexer import FileIndexer, SymbolDef

logger = logging.getLogger(__name__)


@dataclass
class FileSummary:
    """文件摘要"""

    path: str
    module: str = ""  # 模块名 (如 pycoder.server.app)
    size: int = 0
    content_hash: str = ""
    symbols: list[SymbolDef] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    config_items: dict[str, str] = field(default_factory=dict)
    last_indexed: float = 0.0

    def to_dict(self) -> dict:
        """转换为字典 (用于序列化)"""
        return {
            "path": self.path,
            "module": self.module,
            "size": self.size,
            "content_hash": self.content_hash,
            "symbols": [
                {"name": s.name, "kind": s.kind, "line": s.start_line} for s in self.symbols
            ],
            "imports": self.imports[:20],  # 限制导入列表长度
            "config_items": self.config_items,
            "last_indexed": self.last_indexed,
        }


# 忽略的目录
_IGNORE_DIRS: set[str] = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".eggs",
    "*.egg-info",
    ".tox",
    ".coverage",
    "htmlcov",
}

# 支持的文件扩展名
_SUPPORTED_EXTENSIONS: set[str] = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".cfg",
    ".ini",
    ".md",
    ".txt",
    ".env",
}

# 配置文件
_CONFIG_FILES: set[str] = {
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    ".env",
    ".env.example",
    "Makefile",
    "docker-compose.yml",
    "package.json",
    "tsconfig.json",
}


class ProjectIndex:
    """项目虚拟文件索引 — 增量缓存 + 符号索引"""

    def __init__(self, cache_path: str | Path | None = None) -> None:
        """初始化项目索引

        Args:
            cache_path: SQLite 缓存路径 (None 则仅内存缓存)
        """
        self._index: dict[str, FileSummary] = {}  # path → summary
        self._symbol_index: dict[str, list[str]] = {}  # symbol_name → [file_paths]
        self._config_index: dict[str, dict[str, str]] = {}  # config_file → items
        self._file_indexer = FileIndexer()
        self._cache_path = Path(cache_path) if cache_path else None
        self._root: Path | None = None

        # 加载持久化缓存
        if self._cache_path and self._cache_path.exists():
            self._load_cache()

    def scan_project(self, root_dir: str | Path, *, force: bool = False) -> int:
        """扫描整个项目，构建索引

        Args:
            root_dir: 项目根目录
            force: 是否强制重新扫描 (忽略缓存)

        Returns:
            索引的文件总数
        """
        root = Path(root_dir).resolve()
        self._root = root
        count = 0

        for file_path in self._walk(root):
            rel_path = str(file_path.relative_to(root)).replace("\\", "/")
            self._index_file(file_path, rel_path, force=force)
            count += 1

        # 重建符号索引
        self._rebuild_symbol_index()

        # 持久化
        if self._cache_path:
            self._save_cache()

        logger.info("project_index_scanned root=%s files=%d", root, count)
        return count

    def update_file(self, file_path: str | Path) -> None:
        """增量更新单个文件

        Args:
            file_path: 文件路径 (相对于项目根目录或绝对路径)
        """
        if self._root is None:
            return

        path = Path(file_path)
        if not path.is_absolute():
            path = self._root / path

        if not path.exists():
            self.remove_file(file_path)
            return

        rel_path = str(path.relative_to(self._root)).replace("\\", "/")
        self._index_file(path, rel_path, force=True)
        self._rebuild_symbol_index()

        if self._cache_path:
            self._save_cache()

    def remove_file(self, file_path: str | Path) -> None:
        """从索引中移除文件"""
        if self._root is None:
            return

        path = Path(file_path)
        if not path.is_absolute():
            path = self._root / path

        rel_path = str(path.relative_to(self._root)).replace("\\", "/")

        if rel_path in self._index:
            del self._index[rel_path]
            self._rebuild_symbol_index()

            if self._cache_path:
                self._save_cache()

    def find_symbol(self, name: str) -> list[str]:
        """按符号名查找文件

        Args:
            name: 符号名 (类名、函数名)

        Returns:
            匹配的文件路径列表
        """
        # 精确匹配
        if name in self._symbol_index:
            return self._symbol_index[name]

        # 模糊匹配
        results: list[str] = []
        name_lower = name.lower()
        for symbol, paths in self._symbol_index.items():
            if name_lower in symbol.lower():
                results.extend(paths)
        return list(dict.fromkeys(results))  # 去重保持顺序

    def find_file(self, pattern: str) -> list[str]:
        """按文件名模式查找文件

        Args:
            pattern: 文件名模式 (支持 * 通配符)

        Returns:
            匹配的文件路径列表
        """
        import fnmatch

        results: list[str] = []
        for path in self._index:
            filename = Path(path).name
            if fnmatch.fnmatch(filename, pattern):
                results.append(path)
        return sorted(results)

    def get_summary(self, file_path: str) -> FileSummary | None:
        """获取文件摘要"""
        return self._index.get(file_path)

    def export_summary(self, max_entries: int = 200) -> dict:
        """导出索引摘要 (供 AI 上下文使用)

        Args:
            max_entries: 最大条目数

        Returns:
            包含项目结构摘要的字典
        """
        if not self._index:
            return {"files": [], "symbols": {}, "configs": {}}

        # 按目录分组
        dir_structure: dict[str, list[str]] = {}
        for path in sorted(self._index.keys())[:max_entries]:
            dir_name = str(Path(path).parent)
            dir_structure.setdefault(dir_name, []).append(Path(path).name)

        # 导出符号索引 (最常见的符号)
        symbols: dict[str, list[str]] = {}
        for name, paths in sorted(self._symbol_index.items())[:100]:
            symbols[name] = paths[:3]  # 每个符号最多 3 个文件

        return {
            "total_files": len(self._index),
            "root": str(self._root) if self._root else "",
            "dir_structure": dir_structure,
            "symbols": symbols,
            "configs": dict(self._config_index),
        }

    def get_stats(self) -> dict:
        """获取索引统计信息"""
        total_symbols = sum(len(s.symbols) for s in self._index.values())
        total_size = sum(s.size for s in self._index.values())
        return {
            "total_files": len(self._index),
            "total_symbols": total_symbols,
            "total_size_bytes": total_size,
            "symbol_index_size": len(self._symbol_index),
            "config_files": len(self._config_index),
            "cache_enabled": self._cache_path is not None,
        }

    # ── 内部方法 ──────────────────────────────────────────

    def _walk(self, root: Path):
        """遍历项目目录 (过滤忽略目录)"""
        for path in root.rglob("*"):
            if path.is_dir():
                continue
            # 检查是否在忽略目录中
            if any(part in _IGNORE_DIRS for part in path.parts):
                continue
            # 检查文件扩展名
            if path.suffix not in _SUPPORTED_EXTENSIONS:
                continue
            yield path

    def _index_file(self, file_path: Path, rel_path: str, *, force: bool = False) -> None:
        """索引单个文件"""
        try:
            content_hash = self._hash_file(file_path)
            if not force and rel_path in self._index:
                cached = self._index[rel_path]
                if cached.content_hash == content_hash:
                    return  # 文件未变更，跳过

            # 使用 FileIndexer 获取符号
            file_index = self._file_indexer.index_file(file_path)
            symbols = file_index.symbols if file_index else []

            # 提取导入 (仅 Python)
            imports: list[str] = []
            if file_path.suffix == ".py":
                imports = self._extract_imports(file_path)

            # 提取配置项
            config_items: dict[str, str] = {}
            if file_path.name in _CONFIG_FILES:
                config_items = self._extract_config(file_path)

            # 计算模块名
            module = ""
            if file_path.suffix == ".py":
                # 从文件路径推断模块名
                parts = rel_path.removesuffix(".py").replace("/", ".")
                module = parts

            self._index[rel_path] = FileSummary(
                path=rel_path,
                module=module,
                size=file_path.stat().st_size,
                content_hash=content_hash,
                symbols=symbols,
                imports=imports,
                config_items=config_items,
                last_indexed=time.time(),
            )
        except (OSError, UnicodeDecodeError, PermissionError) as e:
            logger.debug("index_file_failed path=%s error=%s", file_path, e)

    def _rebuild_symbol_index(self) -> None:
        """重建符号索引"""
        self._symbol_index.clear()
        self._config_index.clear()

        for path, summary in self._index.items():
            for symbol in summary.symbols:
                self._symbol_index.setdefault(symbol.name, []).append(path)
            if summary.config_items:
                self._config_index[path] = summary.config_items

    @staticmethod
    def _extract_imports(file_path: Path) -> list[str]:
        """提取 Python 文件的导入列表"""
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            imports: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append(node.module)
            return imports
        except (SyntaxError, OSError):
            return []

    @staticmethod
    def _extract_config(file_path: Path) -> dict[str, str]:
        """提取配置文件的关键项"""
        items: dict[str, str] = {}
        try:
            text = file_path.read_text(encoding="utf-8")
            if file_path.name == "pyproject.toml":
                # 简单解析 pyproject.toml
                for line in text.splitlines():
                    line = line.strip()
                    if line.startswith("name = "):
                        items["name"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("version = "):
                        items["version"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif file_path.name in ("requirements.txt",):
                # 统计依赖数量
                deps = [
                    line.strip()
                    for line in text.splitlines()
                    if line.strip() and not line.startswith("#")
                ]
                items["dependencies"] = str(len(deps))
            elif file_path.name.startswith(".env"):
                # 提取环境变量名 (不提取值，安全考虑)
                keys = [
                    line.split("=")[0].strip()
                    for line in text.splitlines()
                    if "=" in line and not line.startswith("#")
                ]
                items["env_keys"] = ",".join(keys[:20])
        except (OSError, UnicodeDecodeError):
            pass
        return items

    @staticmethod
    def _hash_file(path: Path) -> str:
        """计算文件内容 MD5 哈希"""
        try:
            return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()
        except OSError:
            return ""

    # ── SQLite 持久化 ──────────────────────────────────────

    def _save_cache(self) -> None:
        """保存索引到 SQLite"""
        if not self._cache_path:
            return

        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._cache_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_index (
                    path TEXT PRIMARY KEY,
                    module TEXT,
                    size INTEGER,
                    content_hash TEXT,
                    symbols_json TEXT,
                    imports_json TEXT,
                    config_json TEXT,
                    last_indexed REAL
                )
            """)
            conn.execute("DELETE FROM file_index")

            for path, summary in self._index.items():
                import json

                conn.execute(
                    "INSERT OR REPLACE INTO file_index VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        path,
                        summary.module,
                        summary.size,
                        summary.content_hash,
                        json.dumps(
                            [
                                {"name": s.name, "kind": s.kind, "line": s.start_line}
                                for s in summary.symbols
                            ]
                        ),
                        json.dumps(summary.imports[:20]),
                        json.dumps(summary.config_items),
                        summary.last_indexed,
                    ),
                )
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            logger.warning("save_cache_failed error=%s", e)

    def _load_cache(self) -> None:
        """从 SQLite 加载索引"""
        if not self._cache_path or not self._cache_path.exists():
            return

        try:
            import json

            conn = sqlite3.connect(str(self._cache_path))
            cursor = conn.execute("SELECT * FROM file_index")
            for row in cursor:
                (
                    path,
                    module,
                    size,
                    content_hash,
                    symbols_json,
                    imports_json,
                    config_json,
                    last_indexed,
                ) = row
                symbols = [
                    SymbolDef(
                        name=s["name"], kind=s["kind"], start_line=s["line"], end_line=s["line"]
                    )
                    for s in json.loads(symbols_json or "[]")
                ]
                imports = json.loads(imports_json or "[]")
                config_items = json.loads(config_json or "{}")
                self._index[path] = FileSummary(
                    path=path,
                    module=module,
                    size=size,
                    content_hash=content_hash,
                    symbols=symbols,
                    imports=imports,
                    config_items=config_items,
                    last_indexed=last_indexed,
                )
            conn.close()
            self._rebuild_symbol_index()
            logger.info("project_index_loaded from=%s files=%d", self._cache_path, len(self._index))
        except (sqlite3.Error, json.JSONDecodeError) as e:
            logger.warning("load_cache_failed error=%s", e)


# ── 全局单例 ──────────────────────────────────────────────

_project_index: ProjectIndex | None = None


def get_project_index() -> ProjectIndex:
    """获取全局项目索引单例"""
    global _project_index
    if _project_index is None:
        from pathlib import Path

        cache_dir = Path.home() / ".pycoder"
        cache_dir.mkdir(parents=True, exist_ok=True)
        _project_index = ProjectIndex(cache_path=cache_dir / "project_index.db")
    return _project_index
