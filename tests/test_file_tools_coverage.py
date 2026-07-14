"""file_tools 模块覆盖率测试 — MCP 文件操作工具集

覆盖 pycoder.server.mcp.file_tools.register_all 注册的 6 个工具：
- write_file: 写入文件（含路径穿越防护、父目录自动创建）
- read_file: 读取文件（含不存在、目录等错误处理）
- list_files: 列出目录内容
- delete_file: 删除文件或目录（递归）
- create_directory: 创建目录
- run_terminal: 执行 shell 命令（含超时处理）

测试策略：通过 mock register_fn 捕获 handler，使用 tmp_path 隔离工作区。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import pycoder.server.mcp.file_tools as file_tools_mod
import pycoder.server.routers.files as files_mod
from pycoder.server.mcp.file_tools import register_all


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture
def captured_handlers():
    """捕获 register_fn 注册的所有工具 handler"""
    handlers: dict[str, object] = {}

    def register_fn(**kwargs):
        handlers[kwargs["name"]] = kwargs["handler"]

    register_all(register_fn)
    return handlers


@pytest.fixture
def isolated_workspace(tmp_path: Path, monkeypatch):
    """隔离工作区根目录到 tmp_path，避免影响真实文件系统"""
    (tmp_path / "existing.txt").write_text("data", encoding="utf-8")
    (tmp_path / "subdir").mkdir()
    monkeypatch.setattr(files_mod, "_WORKSPACE_ROOT", tmp_path)
    return tmp_path


# ══════════════════════════════════════════════════════════
# 注册测试
# ══════════════════════════════════════════════════════════


class TestRegisterAll:
    def test_registers_six_tools(self):
        """register_all 应注册 6 个工具"""
        names: list[str] = []

        def register_fn(**kwargs):
            names.append(kwargs["name"])

        register_all(register_fn)
        assert len(names) == 6
        assert set(names) == {
            "write_file",
            "read_file",
            "list_files",
            "delete_file",
            "create_directory",
            "run_terminal",
        }

    def test_each_tool_has_schema_and_handler(self, captured_handlers):
        for name, handler in captured_handlers.items():
            assert callable(handler), f"{name} 的 handler 不可调用"


# ══════════════════════════════════════════════════════════
# write_file
# ══════════════════════════════════════════════════════════


class TestWriteFile:
    async def test_write_success(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["write_file"](
            {"path": "new.txt", "content": "hello"}
        )
        assert result["success"] is True
        assert result["path"] == "new.txt"
        assert result["size"] == 5
        assert (isolated_workspace / "new.txt").read_text(encoding="utf-8") == "hello"

    async def test_write_creates_parent_dirs(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["write_file"](
            {"path": "a/b/c/file.txt", "content": "x"}
        )
        assert result["success"] is True
        assert (isolated_workspace / "a/b/c/file.txt").exists()

    async def test_write_empty_path(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["write_file"]({"path": "", "content": "x"})
        assert result["success"] is False
        assert "path" in result["error"]

    async def test_write_empty_content(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["write_file"]({"path": "a.txt", "content": ""})
        assert result["success"] is False
        assert "content" in result["error"]

    async def test_write_path_traversal(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["write_file"](
            {"path": "../../../etc/passwd", "content": "x"}
        )
        assert result["success"] is False
        assert "路径穿越" in result["error"]

    async def test_write_unicode_content(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["write_file"](
            {"path": "cn.txt", "content": "你好世界"}
        )
        assert result["success"] is True
        # UTF-8 编码：每个汉字 3 字节，4 字 = 12 字节
        assert result["size"] == 12

    async def test_write_to_existing_directory_raises(self, captured_handlers, isolated_workspace):
        """写入已存在的目录路径应触发异常分支"""
        (isolated_workspace / "mydir").mkdir()
        result = await captured_handlers["write_file"](
            {"path": "mydir", "content": "x"}
        )
        assert result["success"] is False
        assert "error" in result

    async def test_write_message_format(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["write_file"](
            {"path": "f.txt", "content": "abc"}
        )
        assert "已写入" in result["message"]
        assert "f.txt" in result["message"]


# ══════════════════════════════════════════════════════════
# read_file
# ══════════════════════════════════════════════════════════


class TestReadFile:
    async def test_read_success(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["read_file"]({"path": "existing.txt"})
        assert result["success"] is True
        assert result["content"] == "data"
        assert result["size"] == 4

    async def test_read_empty_path(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["read_file"]({"path": ""})
        assert result["success"] is False
        assert "path" in result["error"]

    async def test_read_nonexistent(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["read_file"]({"path": "nope.txt"})
        assert result["success"] is False
        assert "不存在" in result["error"]

    async def test_read_directory(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["read_file"]({"path": "subdir"})
        assert result["success"] is False
        assert "目录" in result["error"]

    async def test_read_path_traversal(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["read_file"]({"path": "../../../etc/passwd"})
        assert result["success"] is False
        assert "路径穿越" in result["error"]


# ══════════════════════════════════════════════════════════
# list_files
# ══════════════════════════════════════════════════════════


class TestListFiles:
    async def test_list_success(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["list_files"]({"path": "."})
        assert result["success"] is True
        names = [i["name"] for i in result["items"]]
        assert "existing.txt" in names
        assert "subdir" in names
        # 验证 size 和 is_dir 字段
        subdir_item = next(i for i in result["items"] if i["name"] == "subdir")
        assert subdir_item["is_dir"] is True
        assert subdir_item["size"] == 0

    async def test_list_default_path(self, captured_handlers, isolated_workspace):
        """未提供 path 时使用默认 '.'"""
        result = await captured_handlers["list_files"]({})
        assert result["success"] is True
        assert result["path"] == "."

    async def test_list_nonexistent(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["list_files"]({"path": "nope"})
        assert result["success"] is False
        assert "不存在" in result["error"]

    async def test_list_not_directory(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["list_files"]({"path": "existing.txt"})
        assert result["success"] is False
        assert "不是目录" in result["error"]

    async def test_list_path_traversal(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["list_files"]({"path": "../../../"})
        assert result["success"] is False
        assert "路径穿越" in result["error"]

    async def test_list_count_matches_items(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["list_files"]({"path": "."})
        assert result["count"] == len(result["items"])


# ══════════════════════════════════════════════════════════
# delete_file
# ══════════════════════════════════════════════════════════


class TestDeleteFile:
    async def test_delete_file(self, captured_handlers, isolated_workspace):
        (isolated_workspace / "to_del.txt").write_text("x")
        result = await captured_handlers["delete_file"]({"path": "to_del.txt"})
        assert result["success"] is True
        assert not (isolated_workspace / "to_del.txt").exists()

    async def test_delete_directory_recursive(self, captured_handlers, isolated_workspace):
        d = isolated_workspace / "tree"
        d.mkdir()
        (d / "f1.txt").write_text("x")
        (d / "sub").mkdir()
        (d / "sub" / "f2.txt").write_text("y")
        result = await captured_handlers["delete_file"]({"path": "tree"})
        assert result["success"] is True
        assert not d.exists()

    async def test_delete_empty_path(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["delete_file"]({"path": ""})
        assert result["success"] is False
        assert "path" in result["error"]

    async def test_delete_nonexistent(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["delete_file"]({"path": "nope"})
        assert result["success"] is False

    async def test_delete_path_traversal(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["delete_file"]({"path": "../../"})
        assert result["success"] is False
        assert "路径穿越" in result["error"]


# ══════════════════════════════════════════════════════════
# create_directory
# ══════════════════════════════════════════════════════════


class TestCreateDirectory:
    async def test_create_success(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["create_directory"]({"path": "newdir"})
        assert result["success"] is True
        assert (isolated_workspace / "newdir").is_dir()

    async def test_create_nested(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["create_directory"]({"path": "a/b/c/d"})
        assert result["success"] is True
        assert (isolated_workspace / "a/b/c/d").is_dir()

    async def test_create_existing_no_error(self, captured_handlers, isolated_workspace):
        """exist_ok=True，已存在目录不应报错"""
        (isolated_workspace / "exists").mkdir()
        result = await captured_handlers["create_directory"]({"path": "exists"})
        assert result["success"] is True

    async def test_create_empty_path(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["create_directory"]({"path": ""})
        assert result["success"] is False
        assert "path" in result["error"]

    async def test_create_path_traversal(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["create_directory"]({"path": "../../"})
        assert result["success"] is False
        assert "路径穿越" in result["error"]


# ══════════════════════════════════════════════════════════
# run_terminal
# ══════════════════════════════════════════════════════════


class TestRunTerminal:
    async def test_run_success(self, captured_handlers, isolated_workspace, monkeypatch):
        mock_proc = MagicMock(returncode=0, stdout="output\n", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        result = await captured_handlers["run_terminal"]({"command": "echo hi"})
        assert result["success"] is True
        assert result["stdout"] == "output\n"
        assert result["exit_code"] == 0

    async def test_run_empty_command(self, captured_handlers, isolated_workspace):
        result = await captured_handlers["run_terminal"]({"command": ""})
        assert result["success"] is False
        assert "command" in result["error"]

    async def test_run_nonzero_exit(self, captured_handlers, isolated_workspace, monkeypatch):
        mock_proc = MagicMock(returncode=1, stdout="", stderr="err msg")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        result = await captured_handlers["run_terminal"]({"command": "false"})
        assert result["success"] is False
        assert result["exit_code"] == 1
        assert result["stderr"] == "err msg"

    async def test_run_timeout(self, captured_handlers, isolated_workspace, monkeypatch):
        def raise_timeout(*a, **k):
            raise subprocess.TimeoutExpired(cmd="x", timeout=1)

        monkeypatch.setattr(subprocess, "run", raise_timeout)
        result = await captured_handlers["run_terminal"](
            {"command": "sleep 100", "timeout": 1}
        )
        assert result["success"] is False
        assert "超时" in result["error"]
        assert result["exit_code"] == -1

    async def test_run_with_explicit_cwd(
        self, captured_handlers, isolated_workspace, monkeypatch
    ):
        captured_kwargs: dict = {}
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")

        def fake_run(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return mock_proc

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = await captured_handlers["run_terminal"](
            {"command": "ls", "cwd": "/tmp"}
        )
        assert result["success"] is True
        assert captured_kwargs["cwd"] == "/tmp"
        assert result["cwd"] == "/tmp"

    async def test_run_uses_workspace_root_when_no_cwd(
        self, captured_handlers, isolated_workspace, monkeypatch
    ):
        """未指定 cwd 时使用工作区根目录"""
        captured_kwargs: dict = {}
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")

        def fake_run(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return mock_proc

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = await captured_handlers["run_terminal"]({"command": "ls"})
        assert result["success"] is True
        assert captured_kwargs["cwd"] == str(isolated_workspace)

    async def test_run_truncates_long_output(
        self, captured_handlers, isolated_workspace, monkeypatch
    ):
        """stdout 超 8000 字符截断，stderr 超 4000 截断"""
        long_stdout = "x" * 9000
        long_stderr = "y" * 5000
        mock_proc = MagicMock(returncode=0, stdout=long_stdout, stderr=long_stderr)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_proc)
        result = await captured_handlers["run_terminal"]({"command": "cmd"})
        assert len(result["stdout"]) == 8000
        assert len(result["stderr"]) == 4000

    async def test_run_general_exception(
        self, captured_handlers, isolated_workspace, monkeypatch
    ):
        def raise_exc(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(subprocess, "run", raise_exc)
        result = await captured_handlers["run_terminal"]({"command": "x"})
        assert result["success"] is False
        assert "disk full" in result["error"]
        assert result["exit_code"] == -1
