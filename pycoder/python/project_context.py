"""
项目上下文管理器 — 构建项目级别的代码索引和依赖关系。

功能:
- 扫描项目目录，构建符号索引（类、函数、变量）
- 解析导入关系，构建依赖图
- 检测循环依赖
- 跨文件符号解析（跳转到定义、查找引用）
- 生成依赖可视化数据
"""

from __future__ import annotations

import ast
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SymbolInfo:
    """符号信息"""

    name: str
    type: str
    file_path: str
    line: int
    column: int
    code_snippet: str = ""
    docstring: str = ""


@dataclass
class ImportInfo:
    """导入信息"""

    module: str
    alias: str | None
    file_path: str
    line: int


@dataclass
class DependencyGraph:
    """依赖图"""

    nodes: set[str] = field(default_factory=set)
    edges: dict[str, set[str]] = field(default_factory=dict)
    circular_dependencies: list[list[str]] = field(default_factory=list)


@dataclass
class ProjectAnalysis:
    """项目分析结果"""

    success: bool
    symbols: list[SymbolInfo] = field(default_factory=list)
    imports: list[ImportInfo] = field(default_factory=list)
    dependency_graph: DependencyGraph = field(default_factory=DependencyGraph)
    summary: str = ""


class ProjectContext:
    """
    项目上下文管理器 — 扫描项目并构建完整的代码索引。

    支持的操作:
    - build_index(): 构建项目符号索引
    - find_symbol(name): 查找符号定义
    - find_references(name): 查找符号引用
    - detect_circular_dependencies(): 检测循环依赖
    - get_dependency_graph(): 获取依赖图
    """

    def __init__(self, project_path: str):
        self.project_path = Path(project_path).resolve()
        self.symbols: dict[str, list[SymbolInfo]] = {}
        self.imports: list[ImportInfo] = []
        self.dependency_graph: DependencyGraph = DependencyGraph()
        self.file_to_symbols: dict[str, list[SymbolInfo]] = {}

    def build_index(self) -> ProjectAnalysis:
        """构建项目符号索引和依赖图"""
        self.symbols = {}
        self.imports = []
        self.file_to_symbols = {}

        python_files = list(self.project_path.rglob("*.py"))

        for file_path in python_files:
            if self._should_skip(file_path):
                continue

            try:
                with open(file_path, encoding="utf-8") as f:
                    code = f.read()
                self._analyze_file(str(file_path), code)
            except (OSError, UnicodeDecodeError, SyntaxError, ValueError) as e:
                logger.debug("analyze_project_file_failed file=%s error=%s", file_path, e)
                continue

        self._build_dependency_graph()
        self._detect_circular_dependencies()

        return ProjectAnalysis(
            success=True,
            symbols=[s for lst in self.symbols.values() for s in lst],
            imports=self.imports,
            dependency_graph=self.dependency_graph,
            summary=self._generate_summary(),
        )

    def _should_skip(self, file_path: Path) -> bool:
        """判断是否跳过文件"""
        parts = file_path.parts
        skip_dirs = ("__pycache__", ".git", "node_modules", "venv", ".venv", "env")
        for part in parts:
            if part in skip_dirs or part.startswith("."):
                return True
        return False

    def _analyze_file(self, file_path: str, code: str):
        """分析单个文件"""
        try:
            tree = ast.parse(code)
            lines = code.split("\n")
            rel_path = os.path.relpath(file_path, str(self.project_path))

            self.file_to_symbols[rel_path] = []

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    self._add_symbol(
                        name=node.name,
                        type="function",
                        file_path=rel_path,
                        line=node.lineno,
                        column=node.col_offset,
                        code_snippet=lines[node.lineno - 1].strip()[:100],
                        docstring=ast.get_docstring(node) or "",
                    )

                elif isinstance(node, ast.AsyncFunctionDef):
                    self._add_symbol(
                        name=node.name,
                        type="async_function",
                        file_path=rel_path,
                        line=node.lineno,
                        column=node.col_offset,
                        code_snippet=lines[node.lineno - 1].strip()[:100],
                        docstring=ast.get_docstring(node) or "",
                    )

                elif isinstance(node, ast.ClassDef):
                    self._add_symbol(
                        name=node.name,
                        type="class",
                        file_path=rel_path,
                        line=node.lineno,
                        column=node.col_offset,
                        code_snippet=lines[node.lineno - 1].strip()[:100],
                        docstring=ast.get_docstring(node) or "",
                    )

                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        self._add_import(
                            module=alias.name,
                            alias=alias.asname,
                            file_path=rel_path,
                            line=node.lineno,
                        )

                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for alias in node.names:
                        full_module = f"{module}.{alias.name}" if module else alias.name
                        self._add_import(
                            module=full_module,
                            alias=alias.asname,
                            file_path=rel_path,
                            line=node.lineno,
                        )

        except (SyntaxError, ValueError) as e:
            logger.debug("analyze_file_ast_failed file=%s error=%s", file_path, e)

    def _add_symbol(self, **kwargs):
        """添加符号到索引"""
        info = SymbolInfo(**kwargs)
        self.symbols.setdefault(info.name, []).append(info)
        self.file_to_symbols.setdefault(kwargs["file_path"], []).append(info)

    def _add_import(self, **kwargs):
        """添加导入信息"""
        self.imports.append(ImportInfo(**kwargs))

    def _build_dependency_graph(self):
        """构建依赖图"""
        # file_to_symbols 的键已经是 rel_path（_analyze_file 用 rel_path 作为键）
        for file_path, _symbols in self.file_to_symbols.items():
            self.dependency_graph.nodes.add(file_path)
            self.dependency_graph.edges.setdefault(file_path, set())

        for imp in self.imports:
            source_file = imp.file_path
            target_module = self._module_to_file(imp.module)
            if target_module and source_file != target_module:
                self.dependency_graph.edges[source_file].add(target_module)

    def _module_to_file(self, module_name: str) -> str | None:
        """将模块名转换为文件路径"""
        parts = module_name.split(".")

        for base_path, _, _files in os.walk(self.project_path):
            if "__pycache__" in base_path or ".git" in base_path:
                continue

            candidate = Path(base_path)
            for part in parts:
                candidate = candidate / part

            if (candidate / "__init__.py").exists():
                return os.path.relpath(str(candidate / "__init__.py"), str(self.project_path))
            elif (candidate.with_suffix(".py")).exists():
                return os.path.relpath(str(candidate.with_suffix(".py")), str(self.project_path))

        return None

    def _detect_circular_dependencies(self):
        """检测循环依赖"""
        visited = set()
        rec_stack = set()
        cycles = []

        def dfs(node, path):
            visited.add(node)
            rec_stack.add(node)

            for neighbor in self.dependency_graph.edges.get(node, set()):
                if neighbor not in visited:
                    result = dfs(neighbor, path + [node])
                    if result:
                        cycles.append(result)
                elif neighbor in rec_stack:
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [node, neighbor]
                    if cycle not in cycles:
                        cycles.append(cycle)

            rec_stack.discard(node)
            return None

        for node in self.dependency_graph.nodes:
            if node not in visited:
                dfs(node, [])

        self.dependency_graph.circular_dependencies = cycles

    def find_symbol(self, name: str) -> list[SymbolInfo]:
        """查找符号定义"""
        return self.symbols.get(name, [])

    def find_references(self, name: str) -> list[tuple[str, int]]:
        """查找符号引用位置"""
        references = []

        for file_path, _symbols in self.file_to_symbols.items():
            try:
                full_path = self.project_path / file_path
                with open(full_path, encoding="utf-8") as f:
                    code = f.read()
                tree = ast.parse(code)
                code.split("\n")

                for node in ast.walk(tree):
                    if isinstance(node, ast.Name) and node.id == name:
                        if isinstance(node.ctx, ast.Load):
                            references.append((str(file_path), node.lineno))
            except (OSError, UnicodeDecodeError, SyntaxError, ValueError) as e:
                logger.debug("find_references_scan_failed file=%s error=%s", file_path, e)
                continue

        return references

    def resolve_symbol(self, name: str) -> SymbolInfo | None:
        """解析符号来源"""
        symbols = self.find_symbol(name)
        if symbols:
            return symbols[0]
        return None

    def get_dependencies(self, file_path: str) -> set[str]:
        """获取文件的依赖"""
        return self.dependency_graph.edges.get(file_path, set())

    def _generate_summary(self) -> str:
        """生成分析摘要"""
        symbol_counts = {"class": 0, "function": 0, "async_function": 0}
        for symbols in self.symbols.values():
            for s in symbols:
                symbol_counts[s.type] += 1

        summary = "项目分析完成:\n\n"
        summary += f"📁 扫描文件: {len(self.file_to_symbols)}\n"
        summary += f"🏷️ 符号总数: {sum(symbol_counts.values())}\n"
        summary += f"   - 类: {symbol_counts['class']}\n"
        summary += f"   - 函数: {symbol_counts['function']}\n"
        summary += f"   - 异步函数: {symbol_counts['async_function']}\n"
        summary += f"🔗 导入数量: {len(self.imports)}\n"
        summary += f"🔄 循环依赖: {len(self.dependency_graph.circular_dependencies)}\n"

        if self.dependency_graph.circular_dependencies:
            summary += "\n⚠️ 发现循环依赖:\n"
            for i, cycle in enumerate(self.dependency_graph.circular_dependencies[:5], 1):
                summary += f"   {i}. {' → '.join(cycle)}\n"

        return summary


# ── 项目上下文管理器（兼容旧 API）───────────────────────────


class ModuleInfo:
    """模块信息"""

    def __init__(self, name: str, path: str):
        self.name = name
        self.path = path
        self.functions = {}
        self.classes = {}
        self.constants = {}


class FunctionInfo:
    """函数信息"""

    def __init__(self, name: str, file_path: str, line_number: int):
        self.name = name
        self.file_path = file_path
        self.line_number = line_number
        self.parameters = []
        self.return_type = "Any"
        self.docstring = ""


class ClassInfo:
    """类信息"""

    def __init__(self, name: str, file_path: str, line_number: int):
        self.name = name
        self.file_path = file_path
        self.line_number = line_number
        self.base_classes = []
        self.methods = {}
        self.docstring = ""


class ProjectContextData:
    """项目上下文数据"""

    def __init__(self):
        self.project_name = ""
        self.project_root = ""
        self.modules = {}
        self.last_scanned = ""

    @property
    def all_functions(self) -> dict:
        """所有函数"""
        result = {}
        for module in self.modules.values():
            for full_name, func in module.functions.items():
                result[full_name] = func
        return result

    @property
    def all_classes(self) -> dict:
        """所有类"""
        result = {}
        for module in self.modules.values():
            for full_name, cls in module.classes.items():
                result[full_name] = cls
        return result

    @property
    def all_constants(self) -> dict:
        """所有常量"""
        result = {}
        for module_name, module in self.modules.items():
            for const_name in module.constants:
                result[const_name] = module_name
        return result


class ProjectContextManager:
    """项目上下文管理器（兼容旧 API）"""

    _instances = {}

    def __init__(self, project_path: str):
        self.project_path = project_path
        self.context = ProjectContextData()

    def scan_project(self, force: bool = False) -> ProjectContextData:
        """扫描项目"""
        ctx = ProjectContext(self.project_path)
        ctx.build_index()

        self.context = ProjectContextData()
        self.context.project_name = os.path.basename(self.project_path)
        self.context.project_root = self.project_path
        self.context.last_scanned = time.strftime("%Y-%m-%d %H:%M:%S")

        file_modules = {}
        for file_path in ctx.file_to_symbols:
            # file_to_symbols 的键已经是 rel_path（_analyze_file 用 rel_path 作为键）
            rel_path = file_path
            module_name = rel_path.replace(os.sep, ".").replace(".py", "")
            if module_name.endswith(".__init__"):
                module_name = module_name[:-9]
            file_modules[file_path] = module_name

        for file_path, symbols in ctx.file_to_symbols.items():
            module_name = file_modules.get(file_path, "")
            if module_name not in self.context.modules:
                self.context.modules[module_name] = ModuleInfo(module_name, file_path)

            for symbol in symbols:
                if symbol.type in ("function", "async_function"):
                    func = FunctionInfo(symbol.name, file_path, symbol.line)
                    func.docstring = symbol.docstring
                    full_name = f"{module_name}.{symbol.name}"
                    self.context.modules[module_name].functions[full_name] = func
                elif symbol.type == "class":
                    cls = ClassInfo(symbol.name, file_path, symbol.line)
                    cls.docstring = symbol.docstring
                    full_name = f"{module_name}.{symbol.name}"
                    self.context.modules[module_name].classes[full_name] = cls

        return self.context

    def get_context(self) -> ProjectContextData:
        """获取上下文"""
        return self.context


def get_context_manager(project_path: str = None) -> ProjectContextManager:
    """获取上下文管理器"""
    if project_path is None:
        project_path = os.getcwd()

    if project_path not in ProjectContextManager._instances:
        ProjectContextManager._instances[project_path] = ProjectContextManager(project_path)

    return ProjectContextManager._instances[project_path]
