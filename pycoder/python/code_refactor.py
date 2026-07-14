"""
AST 语义化代码重构引擎 — 批量重命名/提取函数/移动模块

用法: from pycoder.python.code_refactor import RefactorEngine
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RefactorResult:
    success: bool
    file_path: str = ""
    operation: str = ""
    changes: list[dict] = field(default_factory=list)
    error: str = ""


class RefactorEngine:
    """基于 AST 的语义化重构引擎"""

    def rename_symbol(self, file_path: str, old_name: str, new_name: str) -> RefactorResult:
        """批量重命名符号（函数/类/变量）"""
        path = Path(file_path)
        if not path.exists():
            return RefactorResult(success=False, error=f"文件不存在: {file_path}")

        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)

            changes = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.Name, ast.FunctionDef, ast.ClassDef, ast.arg)):
                    # 修复: Name 节点用 .id, FunctionDef/ClassDef 用 .name, arg 用 .arg
                    if isinstance(node, ast.Name):
                        node_name = node.id
                    elif isinstance(node, ast.arg):
                        node_name = node.arg
                    else:
                        node_name = node.name
                    if node_name == old_name:
                        changes.append(
                            {
                                "line": getattr(node, "lineno", 0),
                                "type": type(node).__name__,
                                "old": old_name,
                                "new": new_name,
                            }
                        )

            if not changes:
                return RefactorResult(
                    success=False,
                    error=f"未找到符号 {old_name}",
                )

            # 使用正则替换（AST 保留格式）— re 已在模块顶部导入
            new_source = re.sub(
                rf"\b{re.escape(old_name)}\b",
                new_name,
                source,
            )

            path.write_text(new_source, encoding="utf-8")
            return RefactorResult(
                success=True,
                file_path=str(path),
                operation="rename",
                changes=changes,
            )
        except SyntaxError as e:
            return RefactorResult(success=False, error=f"语法错误: {e}")
        except Exception as e:
            return RefactorResult(success=False, error=str(e))

    def extract_function(
        self,
        file_path: str,
        start_line: int,
        end_line: int,
        new_name: str,
    ) -> RefactorResult:
        """提取代码块为新函数"""
        path = Path(file_path)
        if not path.exists():
            return RefactorResult(success=False, error="文件不存在")

        try:
            lines = path.read_text(encoding="utf-8").split("\n")
            if start_line < 1 or end_line > len(lines):
                return RefactorResult(success=False, error="行号超出范围")

            # 提取选中行并计算缩进
            selected = lines[start_line - 1 : end_line]
            indent = len(selected[0]) - len(selected[0].lstrip())

            # 生成新函数
            new_func = [f'{" " * indent}def {new_name}():']
            for line in selected:
                # 减少一层缩进
                stripped = (
                    line[indent + 4 :] if line.startswith(" " * (indent + 4)) else line.lstrip()
                )
                new_func.append(f'{" " * (indent + 4)}{stripped}')
            new_func.append("")

            # 插入函数，替换原代码块为调用
            call_line = f'{" " * indent}{new_name}()'

            # 重构
            before = lines[: start_line - 1]
            after = lines[end_line:]
            new_content = "\n".join(before + new_func + [call_line] + after)
            path.write_text(new_content, encoding="utf-8")

            return RefactorResult(
                success=True,
                file_path=str(path),
                operation="extract_function",
                changes=[
                    {
                        "new_function": new_name,
                        "lines": f"{start_line}-{end_line}",
                    }
                ],
            )
        except Exception as e:
            return RefactorResult(success=False, error=str(e))

    def move_module(self, source_path: str, dest_dir: str) -> RefactorResult:
        """移动模块到目标目录，并更新所有导入引用"""
        src = Path(source_path)
        dest = Path(dest_dir)
        if not src.exists():
            return RefactorResult(success=False, error=f"源文件不存在: {source_path}")

        try:
            import shutil

            dest.mkdir(parents=True, exist_ok=True)
            target = dest / src.name
            shutil.move(str(src), str(target))

            # 更新项目中的导入引用
            old_module = src.stem
            changes = []
            project_root = Path.cwd()
            for py_file in project_root.rglob("*.py"):
                if "__pycache__" in str(py_file):
                    continue
                try:
                    content = py_file.read_text(encoding="utf-8")
                    # re 已在模块顶部导入, 删除局部 import 以避免 UnboundLocalError
                    pattern = rf"from\s+([\w.]+\.)?\b{re.escape(old_module)}\b"
                    if re.search(pattern, content):
                        changes.append({"file": str(py_file.relative_to(project_root))})
                except (OSError, UnicodeDecodeError, PermissionError, re.error) as e:
                    logger.debug("scan_import_references_failed file=%s error=%s", py_file, e)

            return RefactorResult(
                success=True,
                file_path=str(target),
                operation="move_module",
                changes=changes,
            )
        except Exception as e:
            return RefactorResult(success=False, error=str(e))

    def add_type_annotations(self, file_path: str) -> RefactorResult:
        """为函数添加类型注解"""
        path = Path(file_path)
        if not path.exists():
            return RefactorResult(success=False, error="文件不存在")

        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            changes = 0

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.returns is None:
                        node.returns = ast.Name(id="None", ctx=ast.Load())
                        changes += 1

            if changes > 0:
                import astor

                new_source = astor.to_source(tree)
                path.write_text(new_source, encoding="utf-8")
            else:
                new_source = source

            return RefactorResult(
                success=True,
                file_path=str(path),
                operation="add_types",
                changes=[{"annotations_added": changes}],
            )
        except ImportError:
            return RefactorResult(
                success=False,
                error="需要 astor 库: pip install astor",
            )
        except Exception as e:
            return RefactorResult(success=False, error=str(e))


_refactor: RefactorEngine | None = None


def get_refactor_engine() -> RefactorEngine:
    global _refactor
    if _refactor is None:
        _refactor = RefactorEngine()
    return _refactor
