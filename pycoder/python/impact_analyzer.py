"""P1-2: 多文件引用图与影响分析

在 repomap.py（文件级依赖图）之上，构建函数/类级别的引用图。
当用户修改一个函数时，自动列出所有调用点与被引用情况。

核心能力:
- 符号提取：使用 ast 解析 Python 文件，提取所有 def/class/import 符号
- 引用关系：解析函数体内的 Name/Attribute 调用，建立 caller → callee 边
- 影响分析：给定一个符号，递归查找所有上游调用方（被影响范围）
- 依赖分析：给定一个符号，递归查找所有下游被调用方（影响面）
- 导出：JSON / DOT 格式（DOT 可用 Graphviz 渲染为图片）

设计取舍:
- 使用 ast 而非 rope：零额外依赖，适合离线/受限环境
- 使用简单的 Name 解析 + 启发式（module:func 推断），不维护完整类型系统
- 支持跨文件通过 import 链追踪

典型用法:
    analyzer = ImpactAnalyzer(workspace=Path("/project"))
    analyzer.build()

    # 谁调用了 foo?
    callers = analyzer.find_callers("foo", file="a.py")

    # 修改 foo 会影响哪些文件/函数?
    impact = analyzer.find_impact("foo", file="a.py", depth=3)

    # foo 调用了哪些东西?
    callees = analyzer.find_callees("foo", file="a.py")

    # 导出引用图为 DOT
    dot = analyzer.export_dot()
"""
from __future__ import annotations

import ast
import json
import logging
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ── 数据模型 ─────────────────────────────────────────────


@dataclass
class Symbol:
    """代码符号（函数/类/方法/全局变量）"""

    file: str  # 相对路径
    name: str  # 符号名
    kind: str  # "function" | "class" | "method" | "variable"
    line: int  # 定义行号 (1-indexed)
    qualname: str = ""  # 全限定名 (ClassName.method_name)
    args: list[str] = field(default_factory=list)  # 参数列表（仅函数）
    docstring: str = ""

    def __hash__(self) -> int:
        return hash((self.file, self.qualname or self.name))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Symbol):
            return False
        return self.file == other.file and (
            self.qualname or self.name
        ) == (other.qualname or other.name)


@dataclass
class Reference:
    """符号引用（一个调用点）"""

    caller_file: str
    caller_symbol: str  # 包含此调用的函数/类名
    caller_line: int  # 调用行号
    callee_name: str  # 被调用符号名（裸名）
    callee_qualname: str = ""  # 解析后的全限定名
    is_attribute: bool = False  # 是否为 obj.method() 形式
    attribute_target: str = ""  # 属性访问的对象

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ImpactResult:
    """影响分析结果"""

    target_file: str
    target_symbol: str
    affected: list[dict] = field(default_factory=list)  # 所有上游调用方
    total_count: int = 0
    max_depth: int = 0

    def to_dict(self) -> dict:
        return {
            "target_file": self.target_file,
            "target_symbol": self.target_symbol,
            "total_count": self.total_count,
            "max_depth": self.max_depth,
            "affected": self.affected,
        }


# ── 主分析器 ─────────────────────────────────────────────


class ImpactAnalyzer:
    """符号级引用图构建与影响分析"""

    def __init__(self, workspace: Path, exclude_patterns: list[str] | None = None) -> None:
        self.workspace = Path(workspace).resolve()
        self.exclude_patterns = exclude_patterns or [
            r"\.venv",
            r"/venv/",
            r"__pycache__",
            r"/tests?/",
            r"/build/",
            r"/dist/",
            r"\.git",
        ]
        self._exclude_re = re.compile("|".join(self.exclude_patterns))

        # 符号表 { (file, qualname) : Symbol }
        self._symbols: dict[tuple[str, str], Symbol] = {}
        # 引用列表 [Reference]
        self._references: list[Reference] = []
        # 缓存：符号 -> 引用它的所有 Reference
        self._callers_index: dict[tuple[str, str], list[Reference]] = defaultdict(list)
        # 缓存：符号 -> 它引用的所有 Reference
        self._callees_index: dict[tuple[str, str], list[Reference]] = defaultdict(list)

    def build(self) -> None:
        """构建引用图：扫描工作区所有 .py 文件并解析"""
        self._symbols.clear()
        self._references.clear()
        self._callers_index.clear()
        self._callees_index.clear()

        py_files = list(self._iter_python_files())
        logger.info("impact_analyzer_build_start files=%d", len(py_files))

        for f in py_files:
            try:
                self._parse_file(f)
            except SyntaxError as e:
                logger.debug("impact_analyzer_syntax_error file=%s error=%s", f, e)
            except Exception as e:
                logger.warning("impact_analyzer_parse_failed file=%s error=%s", f, e)

        # 解析 import 链
        self._resolve_imports()

        # 构建索引
        for ref in self._references:
            if ref.callee_qualname:
                key = (ref.caller_file, ref.callee_qualname)
                self._callers_index[key].append(ref)
            caller_key = (ref.caller_file, ref.caller_symbol)
            self._callees_index[caller_key].append(ref)

        logger.info(
            "impact_analyzer_build_done symbols=%d references=%d",
            len(self._symbols),
            len(self._references),
        )

    # ── 公开查询 API ─────────────────────────────────

    def find_callers(
        self, name: str, file: str = "", qualname: str = ""
    ) -> list[Reference]:
        """查找调用指定符号的所有引用点

        Args:
            name: 符号名（如 "foo"）
            file: 限定文件（可选，用于消歧）
            qualname: 全限定名（如 "ClassName.method"）
        """
        target_qual = qualname or name
        if file:
            return list(self._callers_index.get((file, target_qual), []))
        # 在所有文件中查找匹配 qualname/name 的
        results = []
        for (f, q), refs in self._callers_index.items():
            if q == target_qual or q.endswith(f".{name}"):
                results.extend(refs)
        return results

    def find_callees(self, name: str, file: str = "", qualname: str = "") -> list[Reference]:
        """查找指定符号内部调用的所有下游符号

        Args:
            name: 符号名
            file: 限定文件
            qualname: 全限定名
        """
        target_qual = qualname or name
        if file:
            return list(self._callees_index.get((file, target_qual), []))
        for (f, q), refs in self._callees_index.items():
            if q == target_qual or q.endswith(f".{name}"):
                return list(refs)
        return []

    def find_impact(
        self, name: str, file: str = "", qualname: str = "", max_depth: int = 3
    ) -> ImpactResult:
        """影响分析：修改此符号会影响哪些上游调用方？

        通过 BFS 沿引用图反向遍历 max_depth 层。
        """
        target_qual = qualname or name
        visited: set[tuple[str, str]] = set()
        queue: list[tuple[tuple[str, str], int]] = [((file, target_qual), 0)]
        affected: list[dict] = []
        max_seen_depth = 0

        while queue:
            (cur_file, cur_qual), depth = queue.pop(0)
            if (cur_file, cur_qual) in visited:
                continue
            visited.add((cur_file, cur_qual))
            if depth > max_depth:
                continue
            max_seen_depth = max(max_seen_depth, depth)

            callers = self._callers_index.get((cur_file, cur_qual), [])
            if not cur_file:
                # 全局查找
                callers = self._callers_index.get(("", cur_qual), [])

            for ref in callers:
                affected.append(
                    {
                        "depth": depth,
                        "file": ref.caller_file,
                        "symbol": ref.caller_symbol,
                        "line": ref.caller_line,
                    }
                )
                # 继续向上传播
                next_key = (ref.caller_file, ref.caller_symbol)
                if next_key not in visited and depth + 1 <= max_depth:
                    queue.append((next_key, depth + 1))

        return ImpactResult(
            target_file=file,
            target_symbol=target_qual,
            affected=affected,
            total_count=len(affected),
            max_depth=max_seen_depth,
        )

    def get_symbol(self, file: str, qualname: str) -> Symbol | None:
        """获取符号定义详情"""
        return self._symbols.get((file, qualname))

    def list_symbols(self, file: str = "") -> list[Symbol]:
        """列出所有符号（或指定文件内的符号）"""
        if file:
            return [s for (f, _q), s in self._symbols.items() if f == file]
        return list(self._symbols.values())

    def stats(self) -> dict:
        """统计信息"""
        files = {f for f, _ in self._symbols.keys()}
        kinds: dict[str, int] = defaultdict(int)
        for s in self._symbols.values():
            kinds[s.kind] += 1
        return {
            "total_symbols": len(self._symbols),
            "total_references": len(self._references),
            "files": len(files),
            "by_kind": dict(kinds),
        }

    def export_json(self) -> str:
        """导出为 JSON 字符串"""
        return json.dumps(
            {
                "stats": self.stats(),
                "symbols": [asdict(s) for s in self._symbols.values()],
                "references": [r.to_dict() for r in self._references],
            },
            indent=2,
            ensure_ascii=False,
        )

    def export_dot(self, max_nodes: int = 200) -> str:
        """导出为 Graphviz DOT 格式（可用于生成图片）"""
        lines = ["digraph impact {", "  rankdir=LR;", "  node [shape=box, style=rounded];"]

        # 选择高频被引用的符号作为节点
        sym_call_count: dict[tuple[str, str], int] = defaultdict(int)
        for ref in self._references:
            if ref.callee_qualname:
                sym_call_count[(ref.caller_file, ref.callee_qualname)] += 1

        top_syms = sorted(sym_call_count.items(), key=lambda x: -x[1])[:max_nodes]
        top_set = {(f, q) for (f, q), _ in top_syms}

        for (f, q), cnt in top_syms:
            label = q.replace('"', '\\"')
            lines.append(f'  "{f}::{q}" [label="{label}\\n({f})", fontsize=10];')

        # 边：caller -> callee
        edge_count = 0
        for ref in self._references:
            if not ref.callee_qualname:
                continue
            src = f"{ref.caller_file}::{ref.caller_symbol}"
            dst = f"{ref.caller_file}::{ref.callee_qualname}"
            if (ref.caller_file, ref.callee_qualname) in top_set:
                lines.append(f'  "{src}" -> "{dst}";')
                edge_count += 1
                if edge_count >= 500:
                    break

        lines.append("}")
        return "\n".join(lines)

    # ── 内部实现 ─────────────────────────────────────

    def _iter_python_files(self) -> list[Path]:
        """遍历工作区下的所有 .py 文件（排除规则）"""
        results: list[Path] = []
        for p in self.workspace.rglob("*.py"):
            try:
                rel = p.relative_to(self.workspace).as_posix()
            except ValueError:
                continue
            if self._exclude_re.search(rel):
                continue
            if not p.is_file():
                continue
            results.append(p)
        return results

    def _parse_file(self, file_path: Path) -> None:
        """解析单个 Python 文件，提取符号与引用"""
        rel_path = file_path.relative_to(self.workspace).as_posix()
        try:
            source = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.debug("impact_analyzer_read_failed file=%s error=%s", file_path, e)
            return

        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as e:
            logger.debug("impact_analyzer_syntax_error file=%s error=%s", rel_path, e)
            return

        # 第一遍：收集所有 import（用于跨文件消歧）
        file_imports: dict[str, str] = {}  # alias -> module.path
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    file_imports[name] = alias.name
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    name = alias.asname or alias.name
                    file_imports[name] = f"{module}.{alias.name}" if module else alias.name

        # 第二遍：提取 def/class 定义
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = node.name
                # 简单处理：如果是 class 的 method，记录为 ClassName.method
                # 此处无法直接通过 ast.walk 获取父节点，所以先记录短名，
                # 后续 _resolve_qualnames 阶段会补全
                args = [a.arg for a in node.args.args]
                doc = ast.get_docstring(node) or ""
                sym = Symbol(
                    file=rel_path,
                    name=node.name,
                    kind="function",
                    line=node.lineno,
                    qualname=qualname,
                    args=args,
                    docstring=doc[:200],
                )
                self._symbols[(rel_path, qualname)] = sym
                # 提取函数体内的引用（顶层 def 不在 ClassDef 分支中处理）
                self._extract_refs_in_body(node, rel_path, qualname, file_imports)
            elif isinstance(node, ast.ClassDef):
                sym = Symbol(
                    file=rel_path,
                    name=node.name,
                    kind="class",
                    line=node.lineno,
                    qualname=node.name,
                    docstring=(ast.get_docstring(node) or "")[:200],
                )
                self._symbols[(rel_path, node.name)] = sym
                # 提取类内方法
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_qual = f"{node.name}.{item.name}"
                        m_args = [a.arg for a in item.args.args]
                        m_doc = ast.get_docstring(item) or ""
                        msym = Symbol(
                            file=rel_path,
                            name=item.name,
                            kind="method",
                            line=item.lineno,
                            qualname=method_qual,
                            args=m_args,
                            docstring=m_doc[:200],
                        )
                        self._symbols[(rel_path, method_qual)] = msym
                        # 解析方法体中的引用
                        self._extract_refs_in_body(item, rel_path, method_qual, file_imports)

    def _extract_refs_in_body(
        self,
        func_node: ast.AST,
        file: str,
        caller_symbol: str,
        file_imports: dict[str, str],
    ) -> None:
        """提取函数体内的所有引用（Name/Attribute 节点）"""
        for sub in ast.walk(func_node):
            if isinstance(sub, ast.Call):
                callee_name = ""
                callee_qual = ""
                is_attr = False
                attr_target = ""

                if isinstance(sub.func, ast.Name):
                    callee_name = sub.func.id
                    # 如果是已导入的模块，尝试解析
                    if callee_name in file_imports:
                        callee_qual = file_imports[callee_name]
                elif isinstance(sub.func, ast.Attribute):
                    is_attr = True
                    callee_name = sub.func.attr
                    if isinstance(sub.func.value, ast.Name):
                        attr_target = sub.func.value.id
                    callee_qual = f"{attr_target}.{callee_name}" if attr_target else callee_name

                if callee_name:
                    # 本地调用（非 import）也记录为 qualname = 短名
                    # 这样 find_callers("foo", file="a.py") 可正常匹配
                    effective_qual = (
                        callee_qual
                        if callee_qual
                        else callee_name
                    )
                    self._references.append(
                        Reference(
                            caller_file=file,
                            caller_symbol=caller_symbol,
                            caller_line=sub.lineno,
                            callee_name=callee_name,
                            callee_qualname=effective_qual,
                            is_attribute=is_attr,
                            attribute_target=attr_target,
                        )
                    )

    def _resolve_imports(self) -> None:
        """尝试解析 import 别名与真实模块路径，完善 cross-file 引用

        简单实现：把已记录到 _symbols 中的同名符号尝试匹配。
        """
        # 建立 短名 -> [(file, qualname)] 反向索引
        short_name_index: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for (f, q), sym in self._symbols.items():
            short_name_index[sym.name].append((f, q))

        for ref in self._references:
            if ref.callee_qualname and "." in ref.callee_qualname:
                # 已经是 attribute 形式，尝试匹配
                short = ref.callee_name
                if short in short_name_index and len(short_name_index[short]) == 1:
                    # 唯一同名符号，假定就是它
                    _f, q = short_name_index[short][0]
                    ref.callee_qualname = q

    # ── Prompt 上下文生成 ────────────────────────────

    def generate_prompt_context(self, focus_files: list[str] | None = None) -> str:
        """生成 Prompt 上下文（用于注入到 system prompt）"""
        lines = ["## 项目引用图概览", ""]
        stats = self.stats()
        lines.append(f"- 符号总数: {stats['total_symbols']}")
        lines.append(f"- 引用边数: {stats['total_references']}")
        lines.append(f"- 涉及文件: {stats['files']}")
        lines.append(f"- 分类: {stats['by_kind']}")

        # 高频被引用的符号 top 10
        sym_call_count: dict[tuple[str, str], int] = defaultdict(int)
        for ref in self._references:
            if ref.callee_qualname:
                sym_call_count[(ref.caller_file, ref.callee_qualname)] += 1

        top = sorted(sym_call_count.items(), key=lambda x: -x[1])[:10]
        if top:
            lines.append("\n### 高频被引用符号 (Top 10)")
            for (f, q), cnt in top:
                lines.append(f"  - {q} ({f}) — 被引用 {cnt} 次")

        # 关注文件的影响范围
        if focus_files:
            lines.append("\n### 关注文件影响范围")
            for ff in focus_files[:3]:
                symbols_in_file = self.list_symbols(file=ff)
                if not symbols_in_file:
                    continue
                lines.append(f"\n**{ff}** (含 {len(symbols_in_file)} 个符号):")
                for s in symbols_in_file[:5]:
                    impact = self.find_impact(s.name, file=ff, qualname=s.qualname, max_depth=2)
                    if impact.total_count > 0:
                        lines.append(
                            f"  - {s.qualname} → 影响 {impact.total_count} 处调用"
                        )

        return "\n".join(lines)
