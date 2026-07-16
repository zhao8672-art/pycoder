"""
Hermes 引擎单元测试 — 覆盖 hermes_engine.py 中的 _execute_hermes_write 函数

测试范围:
  - 成功写入文件
  - 路径穿越拒绝
  - 空 content 且文件存在（读取现有内容）
  - 空 content 且文件不存在（返回错误）
  - 写入异常处理
  - 嵌套目录创建
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pycoder.server.hermes_engine import _execute_hermes_write


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def temp_workspace() -> Path:
    """创建临时工作区目录"""
    with tempfile.TemporaryDirectory(prefix="hermes_test_") as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_workspace_root(temp_workspace: Path) -> MagicMock:
    """模拟 get_workspace_root 返回临时目录"""
    # hermes_engine 在模块顶层 import 了 get_workspace_root，
    # 需要 patch 函数引用所在位置
    with patch(
        "pycoder.server.routers.files.get_workspace_root",
        return_value=temp_workspace,
    ) as mock_fn:
        yield mock_fn


# ── 成功写入测试 ──────────────────────────────────────────


class TestHermesWriteSuccess:
    """成功写入文件场景"""

    @pytest.mark.asyncio
    async def test_write_new_file(self, mock_workspace_root: MagicMock, temp_workspace: Path) -> None:
        """测试写入新文件"""
        result = await _execute_hermes_write("test.py", "print('hello world')")
        assert result["success"] is True
        assert result["path"] == "test.py"
        assert result["size"] > 0

        # 验证文件已写入
        written = (temp_workspace / "test.py").read_text(encoding="utf-8")
        assert written == "print('hello world')"

    @pytest.mark.asyncio
    async def test_write_overwrite_existing(self, mock_workspace_root: MagicMock, temp_workspace: Path) -> None:
        """测试覆盖已存在的文件"""
        # 先创建文件
        (temp_workspace / "existing.py").write_text("old content", encoding="utf-8")

        result = await _execute_hermes_write("existing.py", "new content")
        assert result["success"] is True
        assert result["path"] == "existing.py"

        # 验证内容已更新
        written = (temp_workspace / "existing.py").read_text(encoding="utf-8")
        assert written == "new content"

    @pytest.mark.asyncio
    async def test_write_nested_directory(self, mock_workspace_root: MagicMock, temp_workspace: Path) -> None:
        """测试写入嵌套目录中的文件（自动创建父目录）"""
        result = await _execute_hermes_write("deep/nested/file.py", "nested content")
        assert result["success"] is True
        assert result["path"] == "deep/nested/file.py"

        # 验证目录和文件已创建
        written = (temp_workspace / "deep" / "nested" / "file.py").read_text(encoding="utf-8")
        assert written == "nested content"

    @pytest.mark.asyncio
    async def test_write_unicode_content(self, mock_workspace_root: MagicMock, temp_workspace: Path) -> None:
        """测试写入包含中文的内容"""
        result = await _execute_hermes_write("readme.txt", "你好，世界！\n这是中文内容。")
        assert result["success"] is True
        assert result["size"] > 0

        written = (temp_workspace / "readme.txt").read_text(encoding="utf-8")
        assert "你好" in written

    @pytest.mark.asyncio
    async def test_write_empty_content_with_existing_file(
        self, mock_workspace_root: MagicMock, temp_workspace: Path
    ) -> None:
        """测试空 content 但文件存在：读取现有内容"""
        (temp_workspace / "existing.txt").write_text("existing data", encoding="utf-8")

        result = await _execute_hermes_write("existing.txt", "")
        assert result["success"] is True
        assert result["path"] == "existing.txt"

        # 文件内容应保持不变（使用原有内容）
        written = (temp_workspace / "existing.txt").read_text(encoding="utf-8")
        assert written == "existing data"


# ── 路径穿越测试 ──────────────────────────────────────────


class TestHermesWritePathTraversal:
    """路径穿越拒绝场景"""

    @pytest.mark.asyncio
    async def test_reject_dot_dot_path(self, mock_workspace_root: MagicMock, temp_workspace: Path) -> None:
        """测试拒绝 ../ 路径穿越"""
        result = await _execute_hermes_write("../outside.txt", "malicious")
        assert result["success"] is False
        assert result["path"] == "../outside.txt"
        assert "路径穿越拒绝" in result["error"]

    @pytest.mark.asyncio
    async def test_reject_absolute_path(self, mock_workspace_root: MagicMock, temp_workspace: Path) -> None:
        """测试拒绝绝对路径"""
        result = await _execute_hermes_write("C:/Windows/System32/test.txt", "malicious")
        assert result["success"] is False
        assert "路径穿越拒绝" in result["error"]

    @pytest.mark.asyncio
    async def test_reject_multiple_dot_dot(self, mock_workspace_root: MagicMock, temp_workspace: Path) -> None:
        """测试拒绝多层 ../ 路径穿越"""
        result = await _execute_hermes_write("a/../../../../etc/passwd", "malicious")
        assert result["success"] is False
        assert "路径穿越拒绝" in result["error"]


# ── 空内容 + 文件不存在测试 ───────────────────────────────


class TestHermesWriteEmptyContentNoFile:
    """空 content 且文件不存在的场景"""

    @pytest.mark.asyncio
    async def test_empty_content_no_file(self, mock_workspace_root: MagicMock, temp_workspace: Path) -> None:
        """测试空 content 且文件不存在返回错误"""
        result = await _execute_hermes_write("nonexistent.py", "")
        assert result["success"] is False
        assert result["path"] == "nonexistent.py"
        assert "file_content为空" in result["error"]


# ── 异常处理测试 ──────────────────────────────────────────


class TestHermesWriteExceptions:
    """异常处理场景"""

    @pytest.mark.asyncio
    async def test_write_to_readonly_directory(self, mock_workspace_root: MagicMock) -> None:
        """测试写入只读目录（模拟异常）"""
        with patch(
            "pycoder.server.routers.files.get_workspace_root",
            side_effect=Exception("无法访问工作区"),
        ):
            result = await _execute_hermes_write("test.py", "content")
            assert result["success"] is False
            assert result["path"] == "test.py"
            assert "无法访问工作区" in result["error"]

    @pytest.mark.asyncio
    async def test_write_large_content(self, mock_workspace_root: MagicMock, temp_workspace: Path) -> None:
        """测试写入大内容"""
        large_content = "x" * 10000
        result = await _execute_hermes_write("large.txt", large_content)
        assert result["success"] is True
        assert result["size"] == 10000

        written = (temp_workspace / "large.txt").read_text(encoding="utf-8")
        assert len(written) == 10000

    @pytest.mark.asyncio
    async def test_write_special_chars_in_path(
        self, mock_workspace_root: MagicMock, temp_workspace: Path
    ) -> None:
        """测试路径中包含特殊字符"""
        result = await _execute_hermes_write("path-with-dashes/test_file.py", "content")
        assert result["success"] is True

        written = (temp_workspace / "path-with-dashes" / "test_file.py").read_text(encoding="utf-8")
        assert written == "content"