"""
jupyter.py 模块单元测试 — 覆盖率目标 >=95%

测试策略:
- NotebookCell: to_dict / from_dict 各种 cell_type 分支, source 为 list 的情况
- NotebookInfo: 默认值
- JupyterNotebook: load / save / get_cell / get_code_cells / add/remove/update_cell
- get_source / extract_context (含截断分支)
- execute_notebook: mock subprocess.run, 覆盖成功/失败/超时/FileNotFoundError
- execute_cell_code: mock subprocess.run, 覆盖成功/失败/超时/异常
- find_notebooks / scan_notebooks (含异常路径)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pycoder.python import jupyter as jupyter_mod
from pycoder.python.jupyter import (
    NotebookCell,
    NotebookInfo,
    JupyterNotebook,
    execute_notebook,
    execute_cell_code,
    find_notebooks,
    scan_notebooks,
)


# ── 辅助函数 ────────────────────────────────────────────────


def _make_notebook(cells: list[dict], kernelspec: dict | None = None) -> dict:
    """构造一个最小化 notebook dict"""
    nb = {
        "cells": cells,
        "metadata": {
            "kernelspec": kernelspec or {"name": "python3", "language": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return nb


def _write_notebook(path: Path, cells: list[dict], kernelspec: dict | None = None) -> None:
    """写入一个 notebook 文件"""
    path.write_text(
        json.dumps(_make_notebook(cells, kernelspec), ensure_ascii=False),
        encoding="utf-8",
    )


# ── NotebookCell ────────────────────────────────────────────


class TestNotebookCell:
    def test_to_dict_code(self):
        cell = NotebookCell(
            cell_type="code",
            source="print('hi')",
            outputs=[{"output_type": "stream", "text": "hi\n"}],
            execution_count=1,
            metadata={"collapsed": False},
            index=0,
        )
        d = cell.to_dict()
        assert d["cell_type"] == "code"
        assert d["source"] == "print('hi')"
        assert d["outputs"] == [{"output_type": "stream", "text": "hi\n"}]
        assert d["execution_count"] == 1
        assert d["metadata"] == {"collapsed": False}

    def test_to_dict_markdown(self):
        # markdown cell 不应有 outputs / execution_count
        cell = NotebookCell(cell_type="markdown", source="# Title")
        d = cell.to_dict()
        assert d["cell_type"] == "markdown"
        assert d["source"] == "# Title"
        assert "outputs" not in d
        assert "execution_count" not in d

    def test_to_dict_raw(self):
        cell = NotebookCell(cell_type="raw", source="raw text")
        d = cell.to_dict()
        assert "outputs" not in d

    def test_from_dict_string_source(self):
        d = {"cell_type": "code", "source": "x = 1", "outputs": [], "execution_count": 2}
        cell = NotebookCell.from_dict(d, index=5)
        assert cell.cell_type == "code"
        assert cell.source == "x = 1"
        assert cell.index == 5
        assert cell.execution_count == 2

    def test_from_dict_list_source(self):
        # source 为 list 时应拼接
        d = {"cell_type": "code", "source": ["line1\n", "line2"]}
        cell = NotebookCell.from_dict(d)
        assert cell.source == "line1\nline2"

    def test_from_dict_defaults(self):
        cell = NotebookCell.from_dict({})
        assert cell.cell_type == "code"
        assert cell.source == ""
        assert cell.outputs == []
        assert cell.execution_count is None
        assert cell.metadata == {}
        assert cell.index == -1

    def test_from_dict_with_metadata(self):
        d = {"cell_type": "markdown", "source": "x", "metadata": {"tags": ["t"]}}
        cell = NotebookCell.from_dict(d, index=2)
        assert cell.metadata == {"tags": ["t"]}


# ── NotebookInfo ─────────────────────────────────────────────


class TestNotebookInfo:
    def test_defaults(self):
        info = NotebookInfo(path=Path("/x.ipynb"), cell_count=0, code_cells=0, markdown_cells=0)
        assert info.kernel_name == "python3"
        assert info.language == "python"


# ── JupyterNotebook ────────────────────────────────────────


class TestJupyterNotebook:
    def test_load_not_exists(self, tmp_path):
        nb = JupyterNotebook(tmp_path / "nope.ipynb")
        with pytest.raises(FileNotFoundError):
            nb.load()

    def test_load_success(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [
            {"cell_type": "code", "source": "print(1)", "outputs": [], "execution_count": 1},
            {"cell_type": "markdown", "source": "# Title"},
        ])
        nb = JupyterNotebook(path)
        loaded = nb.load()
        assert loaded is nb
        assert nb._loaded is True
        assert len(nb._cells) == 2

    def test_cells_lazy_load(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [{"cell_type": "code", "source": "x=1"}])
        nb = JupyterNotebook(path)
        assert nb._loaded is False
        cells = nb.cells  # 触发 lazy load
        assert nb._loaded is True
        assert len(cells) == 1

    def test_info_property(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(
            path,
            [
                {"cell_type": "code", "source": "x=1"},
                {"cell_type": "code", "source": "y=2"},
                {"cell_type": "markdown", "source": "# Title"},
            ],
            kernelspec={"name": "ipykernel", "language": "python"},
        )
        nb = JupyterNotebook(path)
        info = nb.info
        assert info.cell_count == 3
        assert info.code_cells == 2
        assert info.markdown_cells == 1
        assert info.kernel_name == "ipykernel"
        assert info.language == "python"

    def test_info_default_kernelspec(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [{"cell_type": "code", "source": "x=1"}], kernelspec=None)
        # 修改 metadata 没有 kernelspec
        nb_data = json.loads(path.read_text(encoding="utf-8"))
        nb_data["metadata"] = {}
        path.write_text(json.dumps(nb_data), encoding="utf-8")
        nb = JupyterNotebook(path)
        info = nb.info
        assert info.kernel_name == "python3"
        assert info.language == "python"

    def test_save_default_path(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [{"cell_type": "code", "source": "x=1"}])
        nb = JupyterNotebook(path)
        nb.load()
        nb.add_code_cell("print('new')")
        nb.save()
        # 重新读取验证
        nb2 = JupyterNotebook(path)
        nb2.load()
        assert len(nb2._cells) == 2

    def test_save_output_path(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [{"cell_type": "code", "source": "x=1"}])
        nb = JupyterNotebook(path)
        nb.load()
        out_path = tmp_path / "out.ipynb"
        nb.save(out_path)
        assert out_path.exists()
        # 验证写入内容
        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert "cells" in data

    def test_get_cell(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [
            {"cell_type": "code", "source": "x=1"},
            {"cell_type": "markdown", "source": "# t"},
        ])
        nb = JupyterNotebook(path)
        cell = nb.get_cell(0)
        assert cell.source == "x=1"
        cell2 = nb.get_cell(1)
        assert cell2.cell_type == "markdown"

    def test_get_code_cells(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [
            {"cell_type": "code", "source": "x=1"},
            {"cell_type": "markdown", "source": "# t"},
            {"cell_type": "code", "source": "y=2"},
        ])
        nb = JupyterNotebook(path)
        code_cells = nb.get_code_cells()
        assert len(code_cells) == 2

    def test_get_markdown_cells(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [
            {"cell_type": "code", "source": "x=1"},
            {"cell_type": "markdown", "source": "# t"},
        ])
        nb = JupyterNotebook(path)
        md_cells = nb.get_markdown_cells()
        assert len(md_cells) == 1

    def test_add_code_cell_append(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [{"cell_type": "code", "source": "x=1"}])
        nb = JupyterNotebook(path)
        nb.load()
        cell = nb.add_code_cell("print('new')")
        assert cell.cell_type == "code"
        assert len(nb._cells) == 2

    def test_add_code_cell_at_index(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [
            {"cell_type": "code", "source": "x=1"},
            {"cell_type": "code", "source": "y=2"},
        ])
        nb = JupyterNotebook(path)
        nb.load()
        nb.add_code_cell("z=3", index=0)
        assert nb._cells[0].source == "z=3"

    def test_add_code_cell_invalid_index_appends(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [{"cell_type": "code", "source": "x=1"}])
        nb = JupyterNotebook(path)
        nb.load()
        # index = 5 超出范围 -> append
        nb.add_code_cell("z=3", index=5)
        assert len(nb._cells) == 2
        assert nb._cells[-1].source == "z=3"

    def test_add_markdown_cell_append(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [{"cell_type": "code", "source": "x=1"}])
        nb = JupyterNotebook(path)
        nb.load()
        cell = nb.add_markdown_cell("# Title")
        assert cell.cell_type == "markdown"

    def test_add_markdown_cell_at_index(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [{"cell_type": "code", "source": "x=1"}])
        nb = JupyterNotebook(path)
        nb.load()
        nb.add_markdown_cell("# Title", index=0)
        assert nb._cells[0].cell_type == "markdown"

    def test_add_markdown_cell_invalid_index(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [{"cell_type": "code", "source": "x=1"}])
        nb = JupyterNotebook(path)
        nb.load()
        nb.add_markdown_cell("# Title", index=10)
        assert len(nb._cells) == 2

    def test_update_cell(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [{"cell_type": "code", "source": "x=1"}])
        nb = JupyterNotebook(path)
        nb.load()
        cell = nb.update_cell(0, "y=2")
        assert cell.source == "y=2"
        assert nb._cells[0].source == "y=2"

    def test_remove_cell(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [
            {"cell_type": "code", "source": "x=1"},
            {"cell_type": "code", "source": "y=2"},
        ])
        nb = JupyterNotebook(path)
        nb.load()
        removed = nb.remove_cell(0)
        assert removed.source == "x=1"
        assert len(nb._cells) == 1
        assert nb._cells[0].source == "y=2"

    def test_clear_outputs(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [
            {"cell_type": "code", "source": "x=1", "outputs": [{"x": 1}], "execution_count": 1},
            {"cell_type": "markdown", "source": "# t"},
        ])
        nb = JupyterNotebook(path)
        nb.load()
        nb.clear_outputs()
        assert nb._cells[0].outputs == []
        assert nb._cells[0].execution_count is None

    def test_get_source(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [
            {"cell_type": "code", "source": "x=1"},
            {"cell_type": "markdown", "source": "# t"},
            {"cell_type": "code", "source": "y=2"},
        ])
        nb = JupyterNotebook(path)
        source = nb.get_source()
        assert "Cell 1" in source
        assert "x=1" in source
        assert "Cell 2" in source
        assert "y=2" in source

    def test_extract_context_within_limit(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [
            {"cell_type": "code", "source": "x=1"},
            {"cell_type": "markdown", "source": "# Title"},
        ])
        nb = JupyterNotebook(path)
        # 必须先 load() 才能填充 _cells, 否则 extract_context 访问空列表
        nb.load()
        ctx = nb.extract_context(max_chars=10000)
        assert "Notebook" in ctx
        assert "Cell" in ctx
        assert "x=1" in ctx

    def test_extract_context_truncated(self, tmp_path):
        path = tmp_path / "test.ipynb"
        # 创建超长内容触发截断
        long_source = "x" * 5000
        cells = [{"cell_type": "code", "source": long_source} for _ in range(5)]
        _write_notebook(path, cells)
        nb = JupyterNotebook(path)
        # 必须先 load() 才能填充 _cells
        nb.load()
        ctx = nb.extract_context(max_chars=2000)
        assert "截断" in ctx


# ── execute_notebook ────────────────────────────────────────


class TestExecuteNotebook:
    def test_file_not_exists(self, tmp_path):
        result = execute_notebook(tmp_path / "nope.ipynb")
        assert result["success"] is False
        assert "文件不存在" in result["error"]

    def test_success(self, tmp_path, monkeypatch):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [{"cell_type": "code", "source": "x=1"}])
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(jupyter_mod.subprocess, "run", lambda *a, **k: mock_result)
        result = execute_notebook(path)
        assert result["success"] is True
        assert result["returncode"] == 0

    def test_failure(self, tmp_path, monkeypatch):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [{"cell_type": "code", "source": "x=1"}])
        mock_result = MagicMock(returncode=1, stdout="", stderr="error")
        monkeypatch.setattr(jupyter_mod.subprocess, "run", lambda *a, **k: mock_result)
        result = execute_notebook(path)
        assert result["success"] is False
        assert "error" in result["error"]

    def test_timeout(self, tmp_path, monkeypatch):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [{"cell_type": "code", "source": "x=1"}])

        def raise_timeout(*a, **k):
            raise subprocess.TimeoutExpired(cmd="jupyter", timeout=10)

        monkeypatch.setattr(jupyter_mod.subprocess, "run", raise_timeout)
        result = execute_notebook(path, timeout=10)
        assert result["success"] is False
        assert "超时" in result["error"]

    def test_filenotfound_jupyter(self, tmp_path, monkeypatch):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [{"cell_type": "code", "source": "x=1"}])

        def raise_fnf(*a, **k):
            raise FileNotFoundError("jupyter not found")

        monkeypatch.setattr(jupyter_mod.subprocess, "run", raise_fnf)
        result = execute_notebook(path)
        assert result["success"] is False
        assert "jupyter 未安装" in result["error"]

    def test_generic_exception(self, tmp_path, monkeypatch):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [{"cell_type": "code", "source": "x=1"}])

        def raise_error(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(jupyter_mod.subprocess, "run", raise_error)
        result = execute_notebook(path)
        assert result["success"] is False
        assert "boom" in result["error"]

    def test_with_empty_stderr(self, tmp_path, monkeypatch):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [{"cell_type": "code", "source": "x=1"}])
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(jupyter_mod.subprocess, "run", lambda *a, **k: mock_result)
        result = execute_notebook(path)
        assert result["error"] == ""


# ── execute_cell_code ────────────────────────────────────────


class TestExecuteCellCode:
    def test_success(self, monkeypatch):
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(jupyter_mod.subprocess, "run", lambda *a, **k: mock_result)
        result = execute_cell_code("print('hi')")
        assert result["success"] is True
        assert "ok" in result["stdout"]

    def test_failure(self, monkeypatch):
        mock_result = MagicMock(returncode=1, stdout="", stderr="error")
        monkeypatch.setattr(jupyter_mod.subprocess, "run", lambda *a, **k: mock_result)
        result = execute_cell_code("invalid_code")
        assert result["success"] is False
        assert "error" in result["stderr"]

    def test_with_notebook_path(self, tmp_path, monkeypatch):
        # 提供 notebook_path 应设置 cwd
        nb_path = tmp_path / "test.ipynb"
        _write_notebook(nb_path, [{"cell_type": "code", "source": "x=1"}])
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(jupyter_mod.subprocess, "run", lambda *a, **k: mock_result)
        result = execute_cell_code("print('hi')", notebook_path=nb_path)
        assert result["success"] is True

    def test_timeout(self, monkeypatch):
        def raise_timeout(*a, **k):
            raise subprocess.TimeoutExpired(cmd="python", timeout=10)

        monkeypatch.setattr(jupyter_mod.subprocess, "run", raise_timeout)
        result = execute_cell_code("while True: pass", timeout=5)
        assert result["success"] is False
        assert "超时" in result["error"]

    def test_generic_exception(self, monkeypatch):
        def raise_error(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(jupyter_mod.subprocess, "run", raise_error)
        result = execute_cell_code("x=1")
        assert result["success"] is False
        assert "boom" in result["error"]


# ── find_notebooks / scan_notebooks ──────────────────────────


class TestFindAndScanNotebooks:
    def test_find_notebooks_empty(self, tmp_path):
        result = find_notebooks(tmp_path)
        assert result == []

    def test_find_notebooks_multiple(self, tmp_path):
        (tmp_path / "a.ipynb").write_text("{}", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.ipynb").write_text("{}", encoding="utf-8")
        (tmp_path / "c.py").write_text("x=1", encoding="utf-8")
        result = find_notebooks(tmp_path)
        names = [p.name for p in result]
        assert "a.ipynb" in names
        assert "b.ipynb" in names
        assert "c.py" not in names
        # 验证已排序
        assert result == sorted(result)

    def test_scan_notebooks_success(self, tmp_path):
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [
            {"cell_type": "code", "source": "x=1"},
            {"cell_type": "markdown", "source": "# t"},
        ])
        result = scan_notebooks(tmp_path)
        assert len(result) == 1
        info = result[0]
        assert info.cell_count == 2
        assert info.code_cells == 1
        assert info.markdown_cells == 1

    def test_scan_notebooks_handles_invalid(self, tmp_path):
        # 创建一个无效 JSON 的 ipynb 文件
        (tmp_path / "bad.ipynb").write_text("not json", encoding="utf-8")
        # 创建一个有效 notebook
        path = tmp_path / "good.ipynb"
        _write_notebook(path, [{"cell_type": "code", "source": "x=1"}])
        result = scan_notebooks(tmp_path)
        # 应跳过 bad.ipynb, 只返回 good.ipynb
        assert len(result) == 1
        assert result[0].path.name == "good.ipynb"

    def test_scan_notebooks_handles_oserror(self, tmp_path, monkeypatch):
        # 创建一个 notebook
        path = tmp_path / "test.ipynb"
        _write_notebook(path, [{"cell_type": "code", "source": "x=1"}])
        # 让 JupyterNotebook.load 抛 OSError
        original_open = open

        def fake_open(file, *args, **kwargs):
            if str(file) == str(path):
                raise OSError("permission denied")
            return original_open(file, *args, **kwargs)

        monkeypatch.setattr("builtins.open", fake_open)
        result = scan_notebooks(tmp_path)
        # 应静默跳过, 返回空列表
        assert result == []
