"""
Jupyter Notebook 集成 — Cell 级读写与执行

支持通过 nbformat 直接操作 Jupyter notebook:
- 读取 cell 内容（code/markdown）
- 修改/添加/删除 cell
- 在 notebook 内执行代码并获取输出
- 与项目 env_detector 协作自动选择 kernel
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ── 数据模型 ──────────────────────────────────────────────


@dataclass
class NotebookCell:
    """Jupyter Notebook Cell"""

    cell_type: str  # "code" | "markdown" | "raw"
    source: str = ""
    outputs: list[dict] = field(default_factory=list)
    execution_count: int | None = None
    metadata: dict = field(default_factory=dict)
    index: int = -1

    def to_dict(self) -> dict:
        """转换为 nbformat cell dict"""
        cell = {
            "cell_type": self.cell_type,
            "source": self.source,
            "metadata": self.metadata,
        }
        if self.cell_type == "code":
            cell["outputs"] = self.outputs
            cell["execution_count"] = self.execution_count
        return cell

    @classmethod
    def from_dict(cls, d: dict, index: int = -1) -> NotebookCell:
        """从 nbformat cell dict 创建"""
        source = d.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        return cls(
            cell_type=d.get("cell_type", "code"),
            source=source,
            outputs=d.get("outputs", []),
            execution_count=d.get("execution_count"),
            metadata=d.get("metadata", {}),
            index=index,
        )


@dataclass
class NotebookInfo:
    """Notebook 元信息"""

    path: Path
    cell_count: int
    code_cells: int
    markdown_cells: int
    kernel_name: str = "python3"
    language: str = "python"


# ── Notebook 读取 ────────────────────────────────────────


class JupyterNotebook:
    """Jupyter Notebook 读写控制器"""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self._nb: dict = {}
        self._cells: list[NotebookCell] = []
        self._loaded = False

    @property
    def cells(self) -> list[NotebookCell]:
        if not self._loaded:
            self.load()
        return self._cells

    @property
    def info(self) -> NotebookInfo:
        if not self._loaded:
            self.load()
        metadata = self._nb.get("metadata", {})
        kernel_info = metadata.get("kernelspec", {})
        return NotebookInfo(
            path=self.path,
            cell_count=len(self._cells),
            code_cells=sum(1 for c in self._cells if c.cell_type == "code"),
            markdown_cells=sum(1 for c in self._cells if c.cell_type == "markdown"),
            kernel_name=kernel_info.get("name", "python3"),
            language=kernel_info.get("language", "python"),
        )

    def load(self) -> JupyterNotebook:
        """加载 notebook 文件"""
        if not self.path.exists():
            raise FileNotFoundError(f"Notebook 不存在: {self.path}")

        with open(self.path, encoding="utf-8") as f:
            self._nb = json.load(f)

        self._cells = [
            NotebookCell.from_dict(c, i) for i, c in enumerate(self._nb.get("cells", []))
        ]
        self._loaded = True
        return self

    def save(self, output_path: str | Path | None = None):
        """保存 notebook 到文件"""
        target = Path(output_path) if output_path else self.path
        self._nb["cells"] = [c.to_dict() for c in self._cells]

        with open(target, "w", encoding="utf-8") as f:
            json.dump(self._nb, f, ensure_ascii=False, indent=1)

    # ── Cell 操作 ──────────────────────────────────────────

    def get_cell(self, index: int) -> NotebookCell:
        """获取指定 cell"""
        return self.cells[index]

    def get_code_cells(self) -> list[NotebookCell]:
        """获取所有代码 cell"""
        return [c for c in self.cells if c.cell_type == "code"]

    def get_markdown_cells(self) -> list[NotebookCell]:
        """获取所有 Markdown cell"""
        return [c for c in self.cells if c.cell_type == "markdown"]

    def add_code_cell(self, source: str, index: int | None = None) -> NotebookCell:
        """添加代码 cell"""
        cell = NotebookCell(cell_type="code", source=source)
        if index is not None and 0 <= index < len(self._cells):
            self._cells.insert(index, cell)
        else:
            self._cells.append(cell)
        return cell

    def add_markdown_cell(self, source: str, index: int | None = None) -> NotebookCell:
        """添加 Markdown cell"""
        cell = NotebookCell(cell_type="markdown", source=source)
        if index is not None and 0 <= index < len(self._cells):
            self._cells.insert(index, cell)
        else:
            self._cells.append(cell)
        return cell

    def update_cell(self, index: int, source: str) -> NotebookCell:
        """更新 cell 内容"""
        cell = self.cells[index]
        cell.source = source
        return cell

    def remove_cell(self, index: int) -> NotebookCell:
        """删除 cell"""
        return self._cells.pop(index)

    def clear_outputs(self):
        """清除所有 cell 输出"""
        for cell in self._cells:
            if cell.cell_type == "code":
                cell.outputs = []
                cell.execution_count = None

    # ── Notebook 内容提取 ──────────────────────────────────

    def get_source(self) -> str:
        """提取所有代码合并为单个 Python 脚本"""
        parts = []
        for i, cell in enumerate(self.get_code_cells()):
            parts.append(f"# %% Cell {i + 1}")
            parts.append(cell.source)
            parts.append("")
        return "\n".join(parts)

    def extract_context(self, max_chars: int = 8000) -> str:
        """提取 notebook 上下文（用于发给 LLM）"""
        lines = [f"# Notebook: {self.path.name}", f"# 共 {len(self._cells)} 个 cell\n"]
        total = 0

        for cell in self._cells:
            header = f"## {'Code' if cell.cell_type == 'code' else 'Markdown'} Cell [{cell.index}]"
            body = cell.source[:500]
            chunk = f"{header}\n{body}\n"
            if total + len(chunk) > max_chars:
                lines.append(f"\n# ... (截断，已显示 {total} 字符)")
                break
            lines.append(chunk)
            total += len(chunk)

        return "\n".join(lines)


# ── Notebook 执行 ────────────────────────────────────────


def execute_notebook(
    notebook_path: str | Path,
    kernel: str = "python3",
    timeout: int = 300,
) -> dict:
    """
    使用 jupyter nbconvert 执行 notebook 并返回结果。

    Args:
        notebook_path: notebook 文件路径
        kernel: kernel 名称
        timeout: 超时秒数

    Returns:
        {"success": bool, "output": str, "error": str}
    """
    path = Path(notebook_path)
    if not path.exists():
        return {"success": False, "error": f"文件不存在: {path}"}

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "jupyter",
                "nbconvert",
                "--to",
                "notebook",
                "--execute",
                f"--ExecutePreprocessor.timeout={timeout:d}",
                f"--ExecutePreprocessor.kernel_name={kernel:s}",
                "--output",
                str(path.stem) + "_executed",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 30,
            cwd=path.parent,
        )

        return {
            "success": result.returncode == 0,
            "output": result.stdout[-2000:],
            "error": result.stderr[-2000:] if result.stderr else "",
            "returncode": result.returncode,
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"执行超时 ({timeout}s)"}
    except FileNotFoundError:
        return {"success": False, "error": "jupyter 未安装，请运行: pip install jupyter nbconvert"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def execute_cell_code(
    code: str,
    notebook_path: str | Path | None = None,
    timeout: int = 60,
) -> dict:
    """
    在 notebook 上下文中执行单段代码。

    通过 jupyter run 执行，可以访问 notebook 中已定义的变量。
    """
    try:
        # 写入临时脚本
        import tempfile

        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8")
        tmp.write(code)
        tmp.close()

        cwd = None
        if notebook_path:
            cwd = str(Path(notebook_path).parent)

        result = subprocess.run(
            [sys.executable, tmp.name],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )

        Path(tmp.name).unlink(missing_ok=True)

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout[-5000:],
            "stderr": result.stderr[-2000:],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"执行超时 ({timeout}s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── 项目 Notebook 扫描 ────────────────────────────────────


def find_notebooks(directory: str | Path = ".") -> list[Path]:
    """扫描目录下所有 .ipynb 文件"""
    return sorted(Path(directory).rglob("*.ipynb"))


def scan_notebooks(directory: str | Path = ".") -> list[NotebookInfo]:
    """批量扫描并获取 notebook 信息"""
    infos = []
    for nb_path in find_notebooks(directory):
        try:
            nb = JupyterNotebook(nb_path)
            infos.append(nb.info)
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
            logger.debug("scan_notebook_failed path=%s error=%s", nb_path, e)
    return infos
