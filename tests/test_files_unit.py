"""Files 路由单元测试 — 文件系统 API 与工作区管理

覆盖 pycoder.server.routers.files 的核心功能：
- _safe_path — 路径穿越防护（安全关键）
- _detect_language — 语言映射
- _file_icon — 文件图标
- FileItem — 目录项数据类
- list_files — 目录列出 API
- read_file — 文件读取 API（含编码探测、大小限制）
- write_file — 文件写入 API
- switch_workspace / get_current_workspace / get_recent_workspaces / restore_workspace
  — 工作区切换与持久化

测试策略：直接调用 async 端点函数（绕过 HTTP/认证层），用 monkeypatch
隔离 _WORKSPACE_ROOT 和配置文件路径，避免影响真实文件系统。

目标覆盖率：23.6% → 80%+
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

import pycoder.server.routers.files as files_mod
from pycoder.server.routers.files import (
    FileItem,
    LAST_WORKSPACE_FILE,
    MAX_HISTORY,
    RECENT_WORKSPACES_FILE,
    _detect_language,
    _file_icon,
    _LANG_MAP,
    _safe_path,
    get_workspace_root,
    restore_workspace,
)


# ══════════════════════════════════════════════════════════
# Fixtures — 隔离工作区与配置文件
# ══════════════════════════════════════════════════════════


@pytest.fixture
def isolated_workspace(tmp_path: Path, monkeypatch):
    """隔离 _WORKSPACE_ROOT 到 tmp_path，避免影响真实文件系统"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "print('hello')\n", encoding="utf-8"
    )
    (tmp_path / "src" / "data.json").write_text(
        '{"key": "value"}\n', encoding="utf-8"
    )
    (tmp_path / "readme.md").write_text("# Project\n", encoding="utf-8")
    monkeypatch.setattr(files_mod, "_WORKSPACE_ROOT", tmp_path)
    yield tmp_path


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch):
    """隔离配置文件路径（last_workspace.json / recent_workspaces.json）"""
    last_file = tmp_path / "last_workspace.json"
    recent_file = tmp_path / "recent_workspaces.json"
    monkeypatch.setattr(files_mod, "LAST_WORKSPACE_FILE", last_file)
    monkeypatch.setattr(files_mod, "RECENT_WORKSPACES_FILE", recent_file)
    yield {"last": last_file, "recent": recent_file}


# ══════════════════════════════════════════════════════════
# 工具函数测试
# ══════════════════════════════════════════════════════════


class TestSafePath:
    """_safe_path 路径穿越防护"""

    def test_dot_returns_workspace_root(self, isolated_workspace):
        """path='.' 返回工作区根"""
        result = _safe_path(".")
        assert result == isolated_workspace

    def test_empty_returns_workspace_root(self, isolated_workspace):
        """空字符串返回工作区根"""
        result = _safe_path("")
        assert result == isolated_workspace

    def test_valid_relative_path(self, isolated_workspace):
        """有效的相对路径被正确解析"""
        result = _safe_path("src/app.py")
        assert result == (isolated_workspace / "src" / "app.py").resolve()

    def test_nested_relative_path(self, isolated_workspace):
        """嵌套相对路径"""
        result = _safe_path("src/sub/deep.py")
        assert str(result).startswith(str(isolated_workspace))

    def test_path_traversal_blocked(self, isolated_workspace):
        """../ 路径穿越被拒绝"""
        with pytest.raises(HTTPException) as exc_info:
            _safe_path("../../etc/passwd")
        assert exc_info.value.status_code == 400
        assert "路径穿越" in exc_info.value.detail

    def test_absolute_path_inside_workspace(self, isolated_workspace):
        """workspace 内的绝对路径可用"""
        abs_path = str(isolated_workspace / "src" / "app.py")
        result = _safe_path(abs_path)
        assert result == Path(abs_path).resolve()

    def test_subdir_path(self, isolated_workspace):
        """子目录路径"""
        result = _safe_path("src")
        assert result == (isolated_workspace / "src").resolve()
        assert result.is_dir()


class TestDetectLanguage:
    """_detect_language 语言映射"""

    @pytest.mark.parametrize("suffix,expected", [
        (".py", "python"),
        (".js", "javascript"),
        (".ts", "typescript"),
        (".jsx", "javascript"),
        (".tsx", "typescript"),
        (".json", "json"),
        (".yaml", "yaml"),
        (".yml", "yaml"),
        (".toml", "toml"),
        (".md", "markdown"),
        (".html", "html"),
        (".css", "css"),
        (".java", "java"),
        (".go", "go"),
        (".rs", "rust"),
        (".c", "c"),
        (".cpp", "cpp"),
        (".sql", "sql"),
        (".sh", "shell"),
        (".ps1", "powershell"),
        (".bat", "batch"),
        (".xml", "xml"),
        (".ini", "ini"),
        (".txt", "plaintext"),
        (".csv", "plaintext"),
    ])
    def test_known_extensions(self, suffix, expected):
        """已知扩展名映射正确"""
        p = Path(f"file{suffix}")
        assert _detect_language(p) == expected

    def test_unknown_extension_defaults_plaintext(self):
        """未知扩展名默认 plaintext"""
        p = Path("file.unknownext")
        assert _detect_language(p) == "plaintext"

    def test_no_extension_defaults_plaintext(self):
        """无扩展名默认 plaintext"""
        p = Path("Makefile")
        assert _detect_language(p) == "plaintext"

    def test_case_insensitive(self):
        """扩展名大小写不敏感"""
        assert _detect_language(Path("FILE.PY")) == "python"
        assert _detect_language(Path("app.JS")) == "javascript"

    def test_lang_map_completeness(self):
        """语言映射表包含常用扩展名"""
        for ext in [".py", ".js", ".ts", ".json", ".md", ".html", ".css"]:
            assert ext in _LANG_MAP


class TestFileIcon:
    """_file_icon 图标返回"""

    def test_dir_returns_folder_icon(self):
        """目录返回 folder 图标"""
        assert _file_icon(True, Path("somedir")) == "folder"

    def test_file_with_extension(self):
        """文件返回扩展名（无点）"""
        assert _file_icon(False, Path("app.py")) == "py"
        assert _file_icon(False, Path("app.js")) == "js"

    def test_file_without_extension(self):
        """无扩展名文件返回 file"""
        assert _file_icon(False, Path("Makefile")) == "file"

    def test_extension_case_insensitive(self):
        """扩展名大小写不敏感"""
        assert _file_icon(False, Path("APP.PY")) == "py"


# ══════════════════════════════════════════════════════════
# FileItem 类测试
# ══════════════════════════════════════════════════════════


class TestFileItem:
    """FileItem 数据类"""

    def test_construction_with_defaults(self):
        """默认值构造"""
        item = FileItem(name="test.py", is_dir=False, path="src/test.py")
        assert item.name == "test.py"
        assert item.is_dir is False
        assert item.path == "src/test.py"
        assert item.size == 0
        assert item.icon == "file"

    def test_construction_with_all_fields(self):
        """完整字段构造"""
        item = FileItem(
            name="app.py", is_dir=False, path="src/app.py",
            size=1024, icon="py",
        )
        assert item.size == 1024
        assert item.icon == "py"

    def test_to_dict_returns_all_fields(self):
        """to_dict 包含所有字段"""
        item = FileItem(name="x.py", is_dir=False, path="x.py", size=10, icon="py")
        d = item.to_dict()
        assert d == {
            "name": "x.py",
            "is_dir": False,
            "path": "x.py",
            "size": 10,
            "icon": "py",
        }

    def test_dir_item_to_dict(self):
        """目录项 to_dict"""
        item = FileItem(name="src", is_dir=True, path="src", icon="folder")
        d = item.to_dict()
        assert d["is_dir"] is True
        assert d["icon"] == "folder"


# ══════════════════════════════════════════════════════════
# list_files API 端点测试
# ══════════════════════════════════════════════════════════


class TestListFiles:
    """list_files API 端点"""

    @pytest.mark.asyncio
    async def test_list_root_directory(self, isolated_workspace):
        """列出根目录内容"""
        result = await files_mod.list_files(path=".")
        assert result["workspace"] == str(isolated_workspace)
        assert "items" in result
        names = [i["name"] for i in result["items"]]
        assert "src" in names
        assert "readme.md" in names

    @pytest.mark.asyncio
    async def test_list_subdirectory(self, isolated_workspace):
        """列出子目录内容"""
        result = await files_mod.list_files(path="src")
        names = [i["name"] for i in result["items"]]
        assert "app.py" in names
        assert "data.json" in names

    @pytest.mark.asyncio
    async def test_list_returns_relative_paths(self, isolated_workspace):
        """返回相对路径"""
        result = await files_mod.list_files(path="src")
        for item in result["items"]:
            assert not item["path"].startswith("/")  # 相对路径
            assert "\\" not in item["path"]  # Unix 风格分隔符

    @pytest.mark.asyncio
    async def test_list_dirs_before_files(self, isolated_workspace):
        """目录排在文件前"""
        result = await files_mod.list_files(path=".")
        items = result["items"]
        # 找到第一个文件（is_dir=False）的位置
        first_file_idx = next(
            (i for i, it in enumerate(items) if not it["is_dir"]), len(items)
        )
        # 之后不应再有目录
        for it in items[first_file_idx:]:
            assert not it["is_dir"], f"目录 {it['name']} 出现在文件之后"

    @pytest.mark.asyncio
    async def test_list_nonexistent_path_raises_404(self, isolated_workspace):
        """不存在的路径返回 404"""
        with pytest.raises(HTTPException) as exc:
            await files_mod.list_files(path="nonexistent_dir")
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_list_file_not_dir_raises_400(self, isolated_workspace):
        """传入文件路径返回 400"""
        with pytest.raises(HTTPException) as exc:
            await files_mod.list_files(path="readme.md")
        assert exc.value.status_code == 400
        assert "不是目录" in exc.value.detail

    @pytest.mark.asyncio
    async def test_list_includes_file_size(self, isolated_workspace):
        """文件项包含 size"""
        result = await files_mod.list_files(path="src")
        for item in result["items"]:
            if not item["is_dir"]:
                assert item["size"] > 0

    @pytest.mark.asyncio
    async def test_list_dir_size_is_zero(self, isolated_workspace):
        """目录项 size 为 0"""
        result = await files_mod.list_files(path=".")
        for item in result["items"]:
            if item["is_dir"]:
                assert item["size"] == 0

    @pytest.mark.asyncio
    async def test_list_includes_icon(self, isolated_workspace):
        """每个项包含 icon"""
        result = await files_mod.list_files(path=".")
        for item in result["items"]:
            assert "icon" in item
            if item["is_dir"]:
                assert item["icon"] == "folder"

    @pytest.mark.asyncio
    async def test_list_path_traversal_blocked(self, isolated_workspace):
        """路径穿越被拦截"""
        with pytest.raises(HTTPException) as exc:
            await files_mod.list_files(path="../../../etc")
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_list_empty_directory(self, isolated_workspace):
        """空目录返回空 items"""
        (isolated_workspace / "empty").mkdir()
        result = await files_mod.list_files(path="empty")
        assert result["items"] == []


# ══════════════════════════════════════════════════════════
# read_file API 端点测试
# ══════════════════════════════════════════════════════════


class TestReadFile:
    """read_file API 端点"""

    @pytest.mark.asyncio
    async def test_read_utf8_file(self, isolated_workspace):
        """读取 UTF-8 文件"""
        result = await files_mod.read_file(path="src/app.py")
        assert result["content"] == "print('hello')\n"
        assert result["language"] == "python"
        assert result["encoding"] == "utf-8"
        assert result["size"] > 0

    @pytest.mark.asyncio
    async def test_read_json_file(self, isolated_workspace):
        """读取 JSON 文件"""
        result = await files_mod.read_file(path="src/data.json")
        assert result["language"] == "json"
        assert "key" in result["content"]

    @pytest.mark.asyncio
    async def test_read_markdown_file(self, isolated_workspace):
        """读取 Markdown 文件"""
        result = await files_mod.read_file(path="readme.md")
        assert result["language"] == "markdown"
        assert result["content"] == "# Project\n"

    @pytest.mark.asyncio
    async def test_read_nonexistent_raises_404(self, isolated_workspace):
        """读取不存在文件返回 404"""
        with pytest.raises(HTTPException) as exc:
            await files_mod.read_file(path="nonexistent.py")
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_read_directory_raises_400(self, isolated_workspace):
        """读取目录返回 400"""
        with pytest.raises(HTTPException) as exc:
            await files_mod.read_file(path="src")
        assert exc.value.status_code == 400
        assert "是目录" in exc.value.detail

    @pytest.mark.asyncio
    async def test_read_path_traversal_blocked(self, isolated_workspace):
        """路径穿越被拦截"""
        with pytest.raises(HTTPException) as exc:
            await files_mod.read_file(path="../../../etc/passwd")
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_read_large_file_raises_413(self, isolated_workspace):
        """超过 1MB 的文件返回 413"""
        big_file = isolated_workspace / "big.txt"
        big_file.write_text("x" * (1024 * 1024 + 1), encoding="utf-8")
        with pytest.raises(HTTPException) as exc:
            await files_mod.read_file(path="big.txt")
        assert exc.value.status_code == 413
        assert "文件过大" in exc.value.detail

    @pytest.mark.asyncio
    async def test_read_file_at_size_limit(self, isolated_workspace):
        """刚好 1MB 的文件可读取"""
        max_file = isolated_workspace / "max.txt"
        max_file.write_text("x" * (1024 * 1024), encoding="utf-8")
        result = await files_mod.read_file(path="max.txt")
        assert result["content"].startswith("xxx")

    @pytest.mark.asyncio
    async def test_read_gbk_encoded_file(self, isolated_workspace):
        """GBK 编码文件可读取"""
        gbk_file = isolated_workspace / "chinese.txt"
        gbk_file.write_bytes("中文内容".encode("gbk"))
        result = await files_mod.read_file(path="chinese.txt")
        assert "中文内容" in result["content"]
        assert result["encoding"] == "gbk"

    @pytest.mark.asyncio
    async def test_read_returns_relative_path(self, isolated_workspace):
        """返回相对路径"""
        result = await files_mod.read_file(path="src/app.py")
        assert result["path"] == "src/app.py"

    @pytest.mark.asyncio
    async def test_read_binary_file_raises_415(self, isolated_workspace, monkeypatch):
        """所有编码都失败时返回 415

        注意：latin-1 能映射所有 0-255 字节，因此真实场景下 415 路径
        几乎不可达。此测试用 mock 强制所有编码失败以覆盖该路径。
        """
        bin_file = isolated_workspace / "binary.dat"
        bin_file.write_bytes(b"\xff\xfe\x00bad")

        original_read_text = Path.read_text

        def fail_read_text(self, encoding=None, **kwargs):
            raise UnicodeDecodeError(encoding or "utf-8", b"", 0, 1, "forced fail")

        monkeypatch.setattr(Path, "read_text", fail_read_text)
        with pytest.raises(HTTPException) as exc:
            await files_mod.read_file(path="binary.dat")
        assert exc.value.status_code == 415
        assert "二进制" in exc.value.detail


# ══════════════════════════════════════════════════════════
# write_file API 端点测试
# ══════════════════════════════════════════════════════════


class TestWriteFile:
    """write_file API 端点"""

    @pytest.mark.asyncio
    async def test_write_new_file(self, isolated_workspace):
        """写入新文件"""
        req = files_mod.FileWriteRequest(
            path="new.py", content="print('new')\n"
        )
        result = await files_mod.write_file(req)
        assert result["success"] is True
        assert result["size"] > 0
        assert (isolated_workspace / "new.py").read_text(encoding="utf-8") == "print('new')\n"

    @pytest.mark.asyncio
    async def test_write_overwrites_existing(self, isolated_workspace):
        """覆盖已存在文件"""
        req = files_mod.FileWriteRequest(
            path="src/app.py", content="# overwritten\n"
        )
        result = await files_mod.write_file(req)
        assert result["success"] is True
        assert (isolated_workspace / "src" / "app.py").read_text(encoding="utf-8") == "# overwritten\n"

    @pytest.mark.asyncio
    async def test_write_creates_parent_dirs(self, isolated_workspace):
        """自动创建父目录"""
        req = files_mod.FileWriteRequest(
            path="deep/nested/dir/file.py", content="x = 1\n"
        )
        result = await files_mod.write_file(req)
        assert result["success"] is True
        assert (isolated_workspace / "deep" / "nested" / "dir" / "file.py").exists()

    @pytest.mark.asyncio
    async def test_write_to_directory_raises_400(self, isolated_workspace):
        """写入目录路径返回 400"""
        req = files_mod.FileWriteRequest(
            path="src", content="x"
        )
        with pytest.raises(HTTPException) as exc:
            await files_mod.write_file(req)
        assert exc.value.status_code == 400
        assert "是目录" in exc.value.detail

    @pytest.mark.asyncio
    async def test_write_path_traversal_blocked(self, isolated_workspace):
        """路径穿越被拦截"""
        req = files_mod.FileWriteRequest(
            path="../../escape.txt", content="x"
        )
        with pytest.raises(HTTPException) as exc:
            await files_mod.write_file(req)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_write_returns_byte_size(self, isolated_workspace):
        """返回写入的字节数"""
        content = "hello world"
        req = files_mod.FileWriteRequest(path="size.txt", content=content)
        result = await files_mod.write_file(req)
        assert result["size"] == len(content.encode("utf-8"))

    @pytest.mark.asyncio
    async def test_write_unicode_content(self, isolated_workspace):
        """写入 Unicode 内容"""
        content = "中文内容 🎉\n"
        req = files_mod.FileWriteRequest(path="unicode.txt", content=content)
        result = await files_mod.write_file(req)
        assert result["success"] is True
        assert (isolated_workspace / "unicode.txt").read_text(encoding="utf-8") == content

    @pytest.mark.asyncio
    async def test_write_returns_relative_path(self, isolated_workspace):
        """返回相对路径"""
        req = files_mod.FileWriteRequest(
            path="src/new.py", content="x"
        )
        result = await files_mod.write_file(req)
        assert result["path"] == "src/new.py"

    @pytest.mark.asyncio
    async def test_write_empty_file(self, isolated_workspace):
        """写入空文件"""
        req = files_mod.FileWriteRequest(path="empty.txt", content="")
        result = await files_mod.write_file(req)
        assert result["success"] is True
        assert result["size"] == 0
        assert (isolated_workspace / "empty.txt").read_text(encoding="utf-8") == ""


# ══════════════════════════════════════════════════════════
# 工作区管理测试
# ══════════════════════════════════════════════════════════


class TestGetWorkspaceRoot:
    """get_workspace_root 测试"""

    def test_returns_current_workspace(self, isolated_workspace):
        """返回当前工作区根"""
        result = get_workspace_root()
        assert result == isolated_workspace


class TestGetCurrentWorkspace:
    """get_current_workspace API 端点"""

    @pytest.mark.asyncio
    async def test_returns_workspace_info(self, isolated_workspace):
        """返回工作区路径和名称"""
        result = await files_mod.get_current_workspace()
        assert result["workspace"] == str(isolated_workspace)
        assert result["name"] == isolated_workspace.name


class TestSwitchWorkspace:
    """switch_workspace API 端点"""

    @pytest.mark.asyncio
    async def test_switch_to_valid_directory(
        self, isolated_workspace, isolated_config, tmp_path
    ):
        """切换到有效目录"""
        new_dir = tmp_path / "new_project"
        new_dir.mkdir()
        result = await files_mod.switch_workspace({"path": str(new_dir)})
        assert result["workspace"] == str(new_dir.resolve())
        assert result["name"] == "new_project"
        # 验证全局状态已更新
        assert files_mod._WORKSPACE_ROOT == new_dir.resolve()
        # 验证持久化文件已写入
        assert isolated_config["last"].exists()
        data = json.loads(isolated_config["last"].read_text(encoding="utf-8"))
        assert data["path"] == str(new_dir.resolve())

    @pytest.mark.asyncio
    async def test_switch_missing_path_raises_400(
        self, isolated_workspace, isolated_config
    ):
        """缺少 path 参数返回 400"""
        with pytest.raises(HTTPException) as exc:
            await files_mod.switch_workspace({})
        assert exc.value.status_code == 400
        assert "path is required" in exc.value.detail

    @pytest.mark.asyncio
    async def test_switch_to_nonexistent_raises_400(
        self, isolated_workspace, isolated_config
    ):
        """切换到不存在的目录返回 400"""
        with pytest.raises(HTTPException) as exc:
            await files_mod.switch_workspace({"path": "/nonexistent/path/xyz"})
        assert exc.value.status_code == 400
        assert "目录不存在" in exc.value.detail

    @pytest.mark.asyncio
    async def test_switch_to_file_raises_400(
        self, isolated_workspace, isolated_config
    ):
        """切换到文件（非目录）返回 400"""
        file_path = isolated_workspace / "somefile.txt"
        file_path.write_text("x", encoding="utf-8")
        with pytest.raises(HTTPException) as exc:
            await files_mod.switch_workspace({"path": str(file_path)})
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_switch_persists_to_recent(
        self, isolated_workspace, isolated_config, tmp_path
    ):
        """切换后追加到 recent_workspaces.json"""
        new_dir = tmp_path / "proj1"
        new_dir.mkdir()
        await files_mod.switch_workspace({"path": str(new_dir)})
        assert isolated_config["recent"].exists()
        recent = json.loads(isolated_config["recent"].read_text(encoding="utf-8"))
        assert len(recent) == 1
        assert recent[0]["path"] == str(new_dir.resolve())

    @pytest.mark.asyncio
    async def test_switch_deduplicates_recent(
        self, isolated_workspace, isolated_config, tmp_path
    ):
        """重复切换同一目录时去重"""
        new_dir = tmp_path / "dedup_project"
        new_dir.mkdir()
        await files_mod.switch_workspace({"path": str(new_dir)})
        await files_mod.switch_workspace({"path": str(new_dir)})
        recent = json.loads(isolated_config["recent"].read_text(encoding="utf-8"))
        assert len(recent) == 1  # 去重后仍为 1

    @pytest.mark.asyncio
    async def test_switch_limits_recent_to_max_history(
        self, isolated_workspace, isolated_config, tmp_path
    ):
        """recent_workspaces 最多保留 MAX_HISTORY 条"""
        for i in range(MAX_HISTORY + 5):
            d = tmp_path / f"proj_{i}"
            d.mkdir()
            await files_mod.switch_workspace({"path": str(d)})
        recent = json.loads(isolated_config["recent"].read_text(encoding="utf-8"))
        assert len(recent) <= MAX_HISTORY


class TestGetRecentWorkspaces:
    """get_recent_workspaces API 端点"""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_file(self, isolated_config):
        """无历史文件时返回空列表"""
        result = await files_mod.get_recent_workspaces()
        assert result["recent"] == []

    @pytest.mark.asyncio
    async def test_returns_recent_list(self, isolated_config):
        """返回历史工作区列表"""
        recent_data = [
            {"path": "/path/a", "timestamp": 1000},
            {"path": "/path/b", "timestamp": 2000},
        ]
        isolated_config["recent"].write_text(
            json.dumps(recent_data), encoding="utf-8"
        )
        result = await files_mod.get_recent_workspaces()
        assert len(result["recent"]) == 2
        assert result["recent"][0]["path"] == "/path/a"


class TestRestoreWorkspace:
    """restore_workspace API 端点"""

    @pytest.mark.asyncio
    async def test_restores_when_last_file_exists(
        self, isolated_workspace, isolated_config, tmp_path
    ):
        """有 last_workspace.json 时恢复"""
        # 先切换到一个新目录，创建持久化记录
        new_dir = tmp_path / "restorable"
        new_dir.mkdir()
        await files_mod.switch_workspace({"path": str(new_dir)})
        # 模拟重启：重置 _WORKSPACE_ROOT 到原值
        monkeypatch_target = isolated_workspace
        import pycoder.server.routers.files as fm
        original = fm._WORKSPACE_ROOT
        fm._WORKSPACE_ROOT = monkeypatch_target
        # 调用 restore
        result = await files_mod.restore_workspace()
        assert result["success"] is True
        assert result["restored"] is True
        assert result["path"] == str(new_dir.resolve())
        # 恢复全局状态以避免影响后续测试
        fm._WORKSPACE_ROOT = original

    @pytest.mark.asyncio
    async def test_no_restore_when_last_file_missing(
        self, isolated_workspace, isolated_config
    ):
        """无 last_workspace.json 时不恢复"""
        result = await files_mod.restore_workspace()
        assert result["success"] is True
        assert result["restored"] is False
        assert result["path"] == str(isolated_workspace)

    @pytest.mark.asyncio
    async def test_restore_with_invalid_json_falls_back(
        self, isolated_workspace, isolated_config
    ):
        """last_workspace.json 损坏时回退到当前工作区"""
        isolated_config["last"].write_text("not json {", encoding="utf-8")
        result = await files_mod.restore_workspace()
        assert result["success"] is True
        assert result["restored"] is False

    @pytest.mark.asyncio
    async def test_restore_with_nonexistent_path_falls_back(
        self, isolated_workspace, isolated_config
    ):
        """last_workspace.json 指向的路径不存在时回退"""
        isolated_config["last"].write_text(
            json.dumps({"path": "/nonexistent/xyz", "timestamp": 0}),
            encoding="utf-8",
        )
        result = await files_mod.restore_workspace()
        assert result["restored"] is False


# ══════════════════════════════════════════════════════════
# FileWriteRequest 模型测试
# ══════════════════════════════════════════════════════════


class TestFileWriteRequest:
    """FileWriteRequest Pydantic 模型"""

    def test_valid_request(self):
        """有效请求"""
        req = files_mod.FileWriteRequest(path="x.py", content="x")
        assert req.path == "x.py"
        assert req.content == "x"

    def test_missing_path_raises_validation_error(self):
        """缺少 path 触发验证错误"""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            files_mod.FileWriteRequest(content="x")

    def test_missing_content_raises_validation_error(self):
        """缺少 content 触发验证错误"""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            files_mod.FileWriteRequest(path="x.py")
