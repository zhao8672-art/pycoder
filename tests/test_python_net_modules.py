"""综合测试: repomap / scaffold_generator / file_undo / generate /
chart_generator / dep_conflict_resolver / runtime_installer / net.client

覆盖 pycoder/python 和 pycoder/net 中 8 个模块的全部公开接口。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ──────────────────────────────────────────────────────────────
# 1. repomap 模块测试
# ──────────────────────────────────────────────────────────────


class TestCodeTag:
    """CodeTag 数据类测试"""

    def test_create_default(self) -> None:
        """测试创建 CodeTag 实例"""
        from pycoder.python.repomap import CodeTag

        tag = CodeTag(fname="test.py", name="my_func", kind="def", line=3)
        assert tag.fname == "test.py"
        assert tag.name == "my_func"
        assert tag.kind == "def"
        assert tag.line == 3

    def test_class_kind(self) -> None:
        """测试 kind 为 class 的 CodeTag"""
        from pycoder.python.repomap import CodeTag

        tag = CodeTag(fname="models.py", name="User", kind="class", line=10)
        assert tag.kind == "class"
        assert tag.name == "User"

    def test_import_kind(self) -> None:
        """测试 kind 为 import 的 CodeTag"""
        from pycoder.python.repomap import CodeTag

        tag = CodeTag(fname="main.py", name="os", kind="import", line=0)
        assert tag.kind == "import"
        assert tag.name == "os"


class TestFileNode:
    """FileNode 数据类测试"""

    def test_default_values(self) -> None:
        """测试 FileNode 默认值"""
        from pycoder.python.repomap import FileNode

        node = FileNode(path="src/main.py")
        assert node.path == "src/main.py"
        assert node.tags == []
        assert node.score == 0.0
        assert node.content_hash == ""

    def test_with_tags(self) -> None:
        """测试带标签的 FileNode"""
        from pycoder.python.repomap import CodeTag, FileNode

        tag = CodeTag(fname="main.py", name="app", kind="def", line=0)
        node = FileNode(path="main.py", tags=[tag], score=0.5, content_hash="abc123")
        assert len(node.tags) == 1
        assert node.score == 0.5
        assert node.content_hash == "abc123"


class TestRepoMap:
    """RepoMap 类测试"""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        """创建带 Python 文件的临时工作区"""
        ws = tmp_path / "project"
        ws.mkdir()
        # 创建 main.py
        (ws / "main.py").write_text(
            "import os\n"
            "from utils import helper\n\n"
            "def main():\n"
            "    helper()\n",
            encoding="utf-8",
        )
        # 创建 utils.py
        (ws / "utils.py").write_text(
            "def helper():\n"
            "    pass\n\n"
            "class Utils:\n"
            "    pass\n",
            encoding="utf-8",
        )
        # 创建子目录中的模块
        sub = ws / "sub"
        sub.mkdir()
        (sub / "mod.py").write_text(
            "def sub_func():\n"
            "    pass\n",
            encoding="utf-8",
        )
        return ws

    def test_init(self, workspace: Path) -> None:
        """测试 RepoMap 初始化"""
        from pycoder.python.repomap import RepoMap

        rm = RepoMap(workspace=workspace, max_tokens=4000)
        assert rm._workspace == workspace
        assert rm._max_tokens == 4000
        assert rm._cache == {}

    def test_init_default_max_tokens(self, workspace: Path) -> None:
        """测试默认 max_tokens 值"""
        from pycoder.python.repomap import RepoMap

        rm = RepoMap(workspace=workspace)
        assert rm._max_tokens == 8000

    def test_get_repo_map_empty(self, workspace: Path) -> None:
        """测试空文件列表返回空字符串"""
        from pycoder.python.repomap import RepoMap

        rm = RepoMap(workspace=workspace)
        result = rm.get_repo_map([], other_files=[])
        assert result == ""

    def test_get_repo_map_with_chat_files(self, workspace: Path) -> None:
        """测试 get_repo_map 返回有效仓库地图"""
        from pycoder.python.repomap import RepoMap

        rm = RepoMap(workspace=workspace)
        result = rm.get_repo_map(["main.py"], other_files=[])
        assert "# Repository Map" in result
        assert "main.py" in result

    def test_get_repo_map_with_scan(self, workspace: Path) -> None:
        """测试自动扫描其他文件"""
        from pycoder.python.repomap import RepoMap

        rm = RepoMap(workspace=workspace, max_tokens=50000)
        result = rm.get_repo_map(["main.py"])
        assert "main.py" in result
        # utils.py 因 import 依赖也会被包含

    def test_get_repo_map_compact(self, workspace: Path) -> None:
        """测试紧凑版仓库地图"""
        from pycoder.python.repomap import RepoMap

        rm = RepoMap(workspace=workspace)
        result = rm.get_repo_map_compact(["main.py"])
        assert "# Repository Map" in result
        assert "main.py" in result

    def test_invalidate_cache_all(self, workspace: Path) -> None:
        """测试清空全部缓存"""
        from pycoder.python.repomap import RepoMap

        rm = RepoMap(workspace=workspace)
        rm._cache["fake"] = []
        rm.invalidate_cache()
        assert rm._cache == {}

    def test_invalidate_cache_specific(self, workspace: Path) -> None:
        """测试清除特定文件的缓存"""
        from pycoder.python.repomap import RepoMap

        rm = RepoMap(workspace=workspace)
        rm._cache["hash1"] = []
        rm._cache["hash2"] = []
        rm.invalidate_cache("hash1")
        assert "hash1" not in rm._cache
        assert "hash2" in rm._cache

    def test_extract_tags_valid(self, workspace: Path) -> None:
        """测试从有效 Python 文件提取标签"""
        from pycoder.python.repomap import RepoMap

        rm = RepoMap(workspace=workspace)
        tags = rm._extract_tags(Path("main.py"))
        kinds = {t.kind for t in tags}
        assert "def" in kinds
        assert "import" in kinds

    def test_extract_tags_nonexistent(self, workspace: Path) -> None:
        """测试不存在的文件返回空列表"""
        from pycoder.python.repomap import RepoMap

        rm = RepoMap(workspace=workspace)
        tags = rm._extract_tags(Path("nope.py"))
        assert tags == []

    def test_extract_tags_syntax_error(self, workspace: Path) -> None:
        """测试语法错误的文件返回空列表"""
        from pycoder.python.repomap import RepoMap

        (workspace / "bad.py").write_text("def broken(:\n", encoding="utf-8")
        rm = RepoMap(workspace=workspace)
        tags = rm._extract_tags(Path("bad.py"))
        assert tags == []

    def test_extract_tags_caching(self, workspace: Path) -> None:
        """测试标签提取的缓存机制"""
        from pycoder.python.repomap import RepoMap

        rm = RepoMap(workspace=workspace)
        tags1 = rm._extract_tags(Path("main.py"))
        tags2 = rm._extract_tags(Path("main.py"))
        assert len(tags1) == len(tags2)
        # 第二次应命中缓存，cache 大小不变
        assert len(rm._cache) == 1

    def test_extract_tags_class_def(self, workspace: Path) -> None:
        """测试提取 class 定义标签"""
        from pycoder.python.repomap import RepoMap

        rm = RepoMap(workspace=workspace)
        tags = rm._extract_tags(Path("utils.py"))
        kinds = {t.kind for t in tags}
        assert "class" in kinds

    def test_extract_tags_async_function(self, workspace: Path) -> None:
        """测试提取 async def 标签"""
        (workspace / "async_mod.py").write_text(
            "async def fetch():\n    pass\n", encoding="utf-8"
        )
        from pycoder.python.repomap import RepoMap

        rm = RepoMap(workspace=workspace)
        tags = rm._extract_tags(Path("async_mod.py"))
        assert any(t.kind == "def" and t.name == "fetch" for t in tags)

    def test_extract_tags_import_from(self, workspace: Path) -> None:
        """测试提取 from ... import 标签"""
        (workspace / "imp_mod.py").write_text(
            "from os import path\nfrom collections import defaultdict\n",
            encoding="utf-8",
        )
        from pycoder.python.repomap import RepoMap

        rm = RepoMap(workspace=workspace)
        tags = rm._extract_tags(Path("imp_mod.py"))
        import_tags = [t for t in tags if t.kind == "import"]
        assert len(import_tags) >= 2

    def test_build_dependency_graph(self, workspace: Path) -> None:
        """测试构建依赖图"""
        from pycoder.python.repomap import CodeTag, RepoMap

        rm = RepoMap(workspace=workspace)
        all_tags = {
            "main.py": [
                CodeTag(fname="main.py", name="utils", kind="import", line=0),
            ],
            "utils.py": [
                CodeTag(fname="utils.py", name="helper", kind="def", line=0),
            ],
        }
        graph = rm._build_dependency_graph(all_tags)
        assert "main.py" in graph
        assert "utils.py" in graph

    def test_build_dependency_graph_no_imports(self, workspace: Path) -> None:
        """测试无导入关系的依赖图"""
        from pycoder.python.repomap import CodeTag, RepoMap

        rm = RepoMap(workspace=workspace)
        all_tags = {
            "a.py": [CodeTag(fname="a.py", name="fa", kind="def", line=0)],
            "b.py": [CodeTag(fname="b.py", name="fb", kind="def", line=0)],
        }
        graph = rm._build_dependency_graph(all_tags)
        assert len(graph) == 2
        assert graph["a.py"] == set()
        assert graph["b.py"] == set()

    def test_pagerank_empty(self, workspace: Path) -> None:
        """测试空图的 PageRank"""
        from pycoder.python.repomap import RepoMap

        rm = RepoMap(workspace=workspace)
        scores = rm._pagerank({})
        assert scores == {}

    def test_pagerank_single_node(self, workspace: Path) -> None:
        """测试单节点的 PageRank"""
        from pycoder.python.repomap import RepoMap

        rm = RepoMap(workspace=workspace)
        scores = rm._pagerank({"a.py": set()})
        assert scores == {"a.py": 1.0}

    def test_pagerank_multiple_nodes(self, workspace: Path) -> None:
        """测试多节点的 PageRank 排序"""
        from pycoder.python.repomap import RepoMap

        rm = RepoMap(workspace=workspace)
        graph = {
            "a.py": {"b.py"},
            "b.py": set(),
            "c.py": {"b.py"},
        }
        scores = rm._pagerank(graph)
        assert len(scores) == 3
        assert scores["b.py"] > scores["a.py"]  # b 被更多文件引用

    def test_assemble_context(self, workspace: Path) -> None:
        """测试上下文组装"""
        from pycoder.python.repomap import CodeTag, RepoMap

        rm = RepoMap(workspace=workspace)
        all_tags = {
            "main.py": [
                CodeTag(fname="main.py", name="main", kind="def", line=0),
            ],
        }
        scores = {"main.py": 1.0}
        result = rm._assemble_context(all_tags, scores, ["main.py"])
        assert "# Repository Map" in result
        assert "main.py" in result
        assert "def main" in result

    def test_assemble_context_truncation(self, workspace: Path) -> None:
        """测试上下文因 token 预算截断"""
        from pycoder.python.repomap import CodeTag, RepoMap

        # 使用极小的 max_tokens 触发截断
        rm = RepoMap(workspace=workspace, max_tokens=1)
        all_tags = {
            "a.py": [CodeTag(fname="a.py", name="func_a", kind="def", line=0)],
            "b.py": [CodeTag(fname="b.py", name="func_b", kind="def", line=0)],
        }
        scores = {"a.py": 0.5, "b.py": 0.5}
        result = rm._assemble_context(all_tags, scores, [])
        assert "truncated" in result

    def test_scan_python_files(self, workspace: Path) -> None:
        """测试扫描 Python 文件"""
        from pycoder.python.repomap import RepoMap

        rm = RepoMap(workspace=workspace)
        files = rm._scan_python_files()
        assert "main.py" in files
        assert "utils.py" in files

    def test_scan_python_files_excludes_cache(self, workspace: Path) -> None:
        """测试扫描排除 __pycache__ 目录"""
        cache_dir = workspace / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "cached.py").write_text("x=1", encoding="utf-8")
        from pycoder.python.repomap import RepoMap

        rm = RepoMap(workspace=workspace)
        files = rm._scan_python_files()
        assert "cached.py" not in files

    def test_hash_file(self, tmp_path: Path) -> None:
        """测试文件哈希计算"""
        from pycoder.python.repomap import RepoMap

        f = tmp_path / "hash_test.py"
        f.write_text("hello", encoding="utf-8")
        h = RepoMap._hash_file(f)
        assert isinstance(h, str)
        assert len(h) == 32  # MD5 hex

    def test_hash_file_nonexistent(self, tmp_path: Path) -> None:
        """测试不存在文件的哈希返回空"""
        from pycoder.python.repomap import RepoMap

        h = RepoMap._hash_file(tmp_path / "nope.py")
        assert h == ""


class TestRepoMapSingleton:
    """RepoMap 单例测试"""

    def test_get_repo_map_creates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试创建 RepoMap 单例"""
        from pycoder.python.repomap import reset_repo_map, get_repo_map
        from pathlib import Path

        reset_repo_map()
        # get_workspace_root 在 get_repo_map 内部延迟导入
        monkeypatch.setattr(
            "pycoder.server.routers.files.get_workspace_root",
            lambda: str(Path.cwd()),
        )
        rm = get_repo_map(max_tokens=5000)
        assert rm is not None
        assert rm._max_tokens == 5000

    def test_get_repo_map_returns_same(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试获取的是同一个单例"""
        from pycoder.python.repomap import reset_repo_map, get_repo_map
        from pathlib import Path

        reset_repo_map()
        monkeypatch.setattr(
            "pycoder.server.routers.files.get_workspace_root",
            lambda: str(Path.cwd()),
        )
        rm1 = get_repo_map()
        rm2 = get_repo_map()
        assert rm1 is rm2

    def test_reset_repo_map(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试重置单例后创建新实例"""
        from pycoder.python.repomap import reset_repo_map, get_repo_map
        from pathlib import Path

        reset_repo_map()
        monkeypatch.setattr(
            "pycoder.server.routers.files.get_workspace_root",
            lambda: str(Path.cwd()),
        )
        rm1 = get_repo_map()
        reset_repo_map()
        rm2 = get_repo_map()
        assert rm1 is not rm2


# ──────────────────────────────────────────────────────────────
# 2. scaffold_generator 模块测试
# ──────────────────────────────────────────────────────────────


class TestScaffoldResult:
    """ScaffoldResult 数据类测试"""

    def test_default(self) -> None:
        """测试默认值"""
        from pycoder.python.scaffold_generator import ScaffoldResult

        sr = ScaffoldResult(success=False)
        assert sr.success is False
        assert sr.project_dir == ""
        assert sr.framework == ""
        assert sr.files_created == 0
        assert sr.error == ""

    def test_success(self) -> None:
        """测试成功结果"""
        from pycoder.python.scaffold_generator import ScaffoldResult

        sr = ScaffoldResult(
            success=True,
            project_dir="/tmp/my-project",
            framework="fastapi",
            files_created=5,
        )
        assert sr.success is True
        assert sr.framework == "fastapi"
        assert sr.files_created == 5

    def test_error(self) -> None:
        """测试错误结果"""
        from pycoder.python.scaffold_generator import ScaffoldResult

        sr = ScaffoldResult(success=False, error="未知框架")
        assert sr.error == "未知框架"


class TestScaffoldGenerator:
    """ScaffoldGenerator 类测试"""

    @pytest.fixture
    def gen(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> "ScaffoldGenerator":
        """创建 ScaffoldGenerator 实例，模板目录指向临时路径"""
        from pycoder.python.scaffold_generator import ScaffoldGenerator

        monkeypatch.setattr(
            "pycoder.python.scaffold_generator.TEMPLATE_DIR",
            tmp_path / "templates",
        )
        return ScaffoldGenerator()

    def test_list_templates(self, gen: "ScaffoldGenerator") -> None:
        """测试列出所有内置模板"""
        templates = gen.list_templates()
        names = {t["name"] for t in templates}
        assert "fastapi" in names
        assert "flask" in names
        assert "django" in names
        assert "express" in names

    def test_list_templates_has_description(self, gen: "ScaffoldGenerator") -> None:
        """测试模板包含描述信息"""
        templates = gen.list_templates()
        for t in templates:
            assert "name" in t
            assert "description" in t
            assert "file_count" in t

    def test_generate_fastapi(self, gen: "ScaffoldGenerator", tmp_path: Path) -> None:
        """测试生成 FastAPI 脚手架"""
        result = gen.generate("fastapi", target_dir=str(tmp_path), project_name="myapi")
        assert result.success is True
        assert result.framework == "fastapi"
        assert result.files_created > 0
        assert (tmp_path / "myapi" / "main.py").exists()

    def test_generate_flask(self, gen: "ScaffoldGenerator", tmp_path: Path) -> None:
        """测试生成 Flask 脚手架"""
        result = gen.generate("flask", target_dir=str(tmp_path), project_name="myflask")
        assert result.success is True
        assert result.framework == "flask"
        assert (tmp_path / "myflask" / "app.py").exists()

    def test_generate_django(self, gen: "ScaffoldGenerator", tmp_path: Path) -> None:
        """测试生成 Django 脚手架"""
        result = gen.generate("django", target_dir=str(tmp_path), project_name="mydjango")
        assert result.success is True
        assert (tmp_path / "mydjango" / "manage.py").exists()
        assert (tmp_path / "mydjango" / "config" / "settings.py").exists()

    def test_generate_express(self, gen: "ScaffoldGenerator", tmp_path: Path) -> None:
        """测试生成 Express 脚手架"""
        result = gen.generate("express", target_dir=str(tmp_path), project_name="myexpress")
        assert result.success is True
        assert (tmp_path / "myexpress" / "index.js").exists()

    def test_generate_unknown_framework(self, gen: "ScaffoldGenerator") -> None:
        """测试未知框架返回错误"""
        result = gen.generate("unknown_framework")
        assert result.success is False
        assert "未知框架" in result.error

    def test_generate_creates_directories(self, gen: "ScaffoldGenerator", tmp_path: Path) -> None:
        """测试生成时创建必要的目录结构"""
        result = gen.generate("fastapi", target_dir=str(tmp_path), project_name="dirs_test")
        assert result.success is True
        assert (tmp_path / "dirs_test" / "routers").is_dir()

    def test_save_template(self, gen: "ScaffoldGenerator", tmp_path: Path) -> None:
        """测试保存自定义模板"""
        from pycoder.python.scaffold_generator import TEMPLATE_DIR

        files = {"hello.py": "print('hello')", "README.md": "# My Project"}
        success = gen.save_template("my_custom", "A custom template", files)
        assert success is True
        template_path = TEMPLATE_DIR / "my_custom.json"
        assert template_path.exists()

        data = json.loads(template_path.read_text(encoding="utf-8"))
        assert data["description"] == "A custom template"
        assert data["files"] == files

    def test_save_template_appears_in_list(self, gen: "ScaffoldGenerator", tmp_path: Path) -> None:
        """测试保存的自定义模板出现在列表中"""
        gen.save_template("custom2", "Custom template", {"a.py": "x=1"})
        templates = gen.list_templates()
        names = [t["name"] for t in templates]
        assert "custom2" in names

    def test_delete_template(self, gen: "ScaffoldGenerator", tmp_path: Path) -> None:
        """测试删除自定义模板"""
        gen.save_template("to_delete", "Delete me", {"x.py": "pass"})
        success = gen.delete_template("to_delete")
        assert success is True

    def test_delete_template_nonexistent(self, gen: "ScaffoldGenerator") -> None:
        """测试删除不存在的模板"""
        success = gen.delete_template("does_not_exist")
        assert success is False

    def test_generate_custom_template(self, gen: "ScaffoldGenerator", tmp_path: Path) -> None:
        """测试使用自定义模板生成项目"""
        gen.save_template("myproj", "My custom project", {"main.py": "print('ok')"})
        result = gen.generate(
            "myproj", target_dir=str(tmp_path), project_name="generated"
        )
        assert result.success is True
        assert (tmp_path / "generated" / "main.py").exists()
        content = (tmp_path / "generated" / "main.py").read_text(encoding="utf-8")
        assert content == "print('ok')"

    def test_generate_default_target_dir(self, gen: "ScaffoldGenerator", monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """测试默认目标目录为当前工作目录"""
        monkeypatch.chdir(tmp_path)
        result = gen.generate("fastapi", project_name="defaultdir")
        assert result.success is True
        assert (tmp_path / "defaultdir" / "main.py").exists()


class TestScaffoldGeneratorSingleton:
    """ScaffoldGenerator 单例测试"""

    def test_get_scaffold_generator(self) -> None:
        """测试获取脚手架生成器单例"""
        from pycoder.python.scaffold_generator import (
            ScaffoldGenerator,
            get_scaffold_generator,
            _generator,
        )

        # 重置全局变量
        import pycoder.python.scaffold_generator as mod
        mod._generator = None

        g1 = get_scaffold_generator()
        g2 = get_scaffold_generator()
        assert isinstance(g1, ScaffoldGenerator)
        assert g1 is g2


# ──────────────────────────────────────────────────────────────
# 3. file_undo 模块测试
# ──────────────────────────────────────────────────────────────


class TestFileSnapshot:
    """FileSnapshot 数据类测试"""

    def test_create(self) -> None:
        """测试创建 FileSnapshot"""
        from pycoder.python.file_undo import FileSnapshot

        snap = FileSnapshot(
            file_path="/tmp/test.py",
            content="hello",
            operation="save",
        )
        assert snap.file_path == "/tmp/test.py"
        assert snap.content == "hello"
        assert snap.operation == "save"

    def test_timestamp_default(self) -> None:
        """测试默认时间戳"""
        from pycoder.python.file_undo import FileSnapshot

        snap = FileSnapshot(file_path="x.py", content="")
        assert snap.timestamp > 0


class TestFileUndoManager:
    """FileUndoManager 类测试"""

    def test_init(self) -> None:
        """测试初始化"""
        from pycoder.python.file_undo import FileUndoManager

        mgr = FileUndoManager()
        assert mgr._history == {}
        assert mgr._max_snapshots == 50

    def test_preview_diff_existing_file(self, tmp_path: Path) -> None:
        """测试预览已有文件的 diff"""
        from pycoder.python.file_undo import FileUndoManager

        f = tmp_path / "test.py"
        f.write_text("old content\nline 2\n", encoding="utf-8")

        mgr = FileUndoManager()
        result = mgr.preview_diff(str(f), "new content\nline 2\nline 3\n")
        assert result["file"] == str(f)
        assert result["added"] >= 1
        assert result["removed"] >= 1
        assert "diff" in result

    def test_preview_diff_new_file(self, tmp_path: Path) -> None:
        """测试预览新文件的 diff"""
        from pycoder.python.file_undo import FileUndoManager

        mgr = FileUndoManager()
        result = mgr.preview_diff(str(tmp_path / "new.py"), "content")
        assert result["file"] == str(tmp_path / "new.py")
        assert result["added"] > 0

    def test_preview_diff_truncation(self, tmp_path: Path) -> None:
        """测试长 diff 被截断"""
        from pycoder.python.file_undo import FileUndoManager

        f = tmp_path / "big.py"
        f.write_text("x\n" * 3000, encoding="utf-8")

        mgr = FileUndoManager()
        result = mgr.preview_diff(str(f), "y\n" * 3000)
        assert len(result["diff"]) <= 5000

    def test_snapshot(self, tmp_path: Path) -> None:
        """测试创建文件快照"""
        from pycoder.python.file_undo import FileUndoManager

        f = tmp_path / "snap.py"
        f.write_text("version 1", encoding="utf-8")

        mgr = FileUndoManager()
        mgr.snapshot(str(f), operation="save")
        assert str(f) in mgr._history
        assert len(mgr._history[str(f)]) == 1

    def test_snapshot_nonexistent(self) -> None:
        """测试快照不存在的文件不报错"""
        from pycoder.python.file_undo import FileUndoManager

        mgr = FileUndoManager()
        mgr.snapshot("/nonexistent/file.py")
        assert len(mgr._history) == 0

    def test_undo(self, tmp_path: Path) -> None:
        """测试撤销操作 — steps=2 回退到第 1 个快照"""
        from pycoder.python.file_undo import FileUndoManager

        f = tmp_path / "undo_test.py"
        f.write_text("version 1", encoding="utf-8")

        mgr = FileUndoManager()
        mgr.snapshot(str(f), operation="save v1")
        f.write_text("version 2", encoding="utf-8")
        mgr.snapshot(str(f), operation="save v2")

        # steps=2 回到 history[-2] 即 version 1 的快照
        result = mgr.undo(str(f), steps=2)
        assert result["success"] is True
        assert result["remaining_snapshots"] == 0
        assert f.read_text(encoding="utf-8") == "version 1"

    def test_undo_insufficient_history(self, tmp_path: Path) -> None:
        """测试撤销步数超过快照数"""
        from pycoder.python.file_undo import FileUndoManager

        f = tmp_path / "few.py"
        f.write_text("v1", encoding="utf-8")

        mgr = FileUndoManager()
        mgr.snapshot(str(f))
        result = mgr.undo(str(f), steps=5)
        assert result["success"] is False
        assert "只有" in result["error"]

    def test_undo_multiple_steps(self, tmp_path: Path) -> None:
        """测试多步撤销 — steps=2 回退到第 2 个快照（v2）"""
        from pycoder.python.file_undo import FileUndoManager

        f = tmp_path / "multi.py"
        f.write_text("v1", encoding="utf-8")
        mgr = FileUndoManager()
        mgr.snapshot(str(f), operation="save v1")

        f.write_text("v2", encoding="utf-8")
        mgr.snapshot(str(f), operation="save v2")

        f.write_text("v3", encoding="utf-8")
        mgr.snapshot(str(f), operation="save v3")

        # steps=2 回到 history[-2] = v2
        result = mgr.undo(str(f), steps=2)
        assert result["success"] is True
        assert f.read_text(encoding="utf-8") == "v2"

    def test_history(self, tmp_path: Path) -> None:
        """测试获取变更历史"""
        from pycoder.python.file_undo import FileUndoManager

        f = tmp_path / "hist.py"
        f.write_text("v1", encoding="utf-8")

        mgr = FileUndoManager()
        mgr.snapshot(str(f), operation="save")
        hist = mgr.history(str(f))
        assert len(hist) == 1
        assert "operation" in hist[0]
        assert "timestamp" in hist[0]

    def test_history_empty(self) -> None:
        """测试获取空白文件的历史"""
        from pycoder.python.file_undo import FileUndoManager

        mgr = FileUndoManager()
        hist = mgr.history("/nonexistent.py")
        assert hist == []

    def test_diff_history(self, tmp_path: Path) -> None:
        """测试历史版本与当前版本的 diff"""
        from pycoder.python.file_undo import FileUndoManager

        f = tmp_path / "diff_hist.py"
        f.write_text("v1", encoding="utf-8")
        mgr = FileUndoManager()
        mgr.snapshot(str(f), operation="save v1")

        f.write_text("v2", encoding="utf-8")
        result = mgr.diff_history(str(f), step=1)
        assert result["file"] == str(f)
        assert "diff" in result

    def test_diff_history_insufficient(self, tmp_path: Path) -> None:
        """测试 diff 步数超出历史"""
        from pycoder.python.file_undo import FileUndoManager

        f = tmp_path / "empty.py"
        f.write_text("x", encoding="utf-8")
        mgr = FileUndoManager()
        mgr.snapshot(str(f))
        result = mgr.diff_history(str(f), step=10)
        assert result["diff"] == ""

    def test_snapshot_max_limit(self, tmp_path: Path) -> None:
        """测试快照数量上限"""
        from pycoder.python.file_undo import FileUndoManager

        f = tmp_path / "max_snap.py"
        mgr = FileUndoManager()
        mgr._max_snapshots = 3
        for i in range(5):
            f.write_text(f"v{i}", encoding="utf-8")
            mgr.snapshot(str(f))
        assert len(mgr._history[str(f)]) == 3


class TestFileUndoManagerSingleton:
    """FileUndoManager 单例测试"""

    def test_get_undo_manager(self) -> None:
        """测试获取撤销管理器单例"""
        from pycoder.python.file_undo import FileUndoManager, get_undo_manager, _undo_manager

        import pycoder.python.file_undo as mod
        mod._undo_manager = None

        m1 = get_undo_manager()
        m2 = get_undo_manager()
        assert isinstance(m1, FileUndoManager)
        assert m1 is m2


# ──────────────────────────────────────────────────────────────
# 4. generate 模块测试
# ──────────────────────────────────────────────────────────────


class TestInferName:
    """_infer_name 函数测试"""

    def test_infer_with_entity(self) -> None:
        """测试从中文实体名推断项目名"""
        from pycoder.python.generate import _infer_name

        name = _infer_name("图书管理系统")
        assert name == "book-manager"

    def test_infer_with_entity_and_framework(self) -> None:
        """测试带框架前缀的实体名"""
        from pycoder.python.generate import _infer_name

        name = _infer_name("FastAPI 用户管理系统")
        assert name == "user-manager"

    def test_infer_multiple_entities_first_wins(self) -> None:
        """测试多个实体名时取第一个匹配"""
        # "图书" 在 "学生" 之前，所以匹配 "图书"
        from pycoder.python.generate import _infer_name

        name = _infer_name("图书学生管理系统")
        assert name == "book-manager"

    def test_infer_with_framework_prefix(self) -> None:
        """测试仅框架前缀无实体名"""
        from pycoder.python.generate import _infer_name

        name = _infer_name("Flask blog api")
        assert name == "blog-api"

    def test_infer_fallback(self) -> None:
        """测试无匹配实体的回退名"""
        from pycoder.python.generate import _infer_name

        name = _infer_name("some random project")
        assert name == "some-random-project"

    def test_infer_empty(self) -> None:
        """测试空描述返回默认名"""
        from pycoder.python.generate import _infer_name

        name = _infer_name("")
        assert name == "my-project"

    def test_infer_chinese_only(self) -> None:
        """测试纯中文无实体名 — Python 3 中 \\w 匹配中文字符"""
        from pycoder.python.generate import _infer_name

        name = _infer_name("一个很酷的网站")
        # Python 3 中 \w 匹配中文字符，所以中文字符不会被移除
        assert "一个很酷的网站" in name or name == "my-project"

    def test_infer_long_name_truncated(self) -> None:
        """测试超长名称截断到 30 字符"""
        from pycoder.python.generate import _infer_name

        name = _infer_name("a" * 50)
        assert len(name) <= 30

    def test_infer_framework_prefix_removal(self) -> None:
        """测试多种框架前缀被移除"""
        from pycoder.python.generate import _infer_name

        assert _infer_name("Django blog") == "blog"
        assert _infer_name("Express blog api") == "blog-api"
        assert _infer_name("Spring Boot app") == "app"


class TestGenerateProject:
    """generate_project 函数测试"""

    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试成功生成项目"""
        mock_run = MagicMock()
        monkeypatch.setattr(
            "pycoder.python.generate._run_generate_mode", mock_run
        )
        from pycoder.python.generate import generate_project

        result = generate_project("FastAPI blog", target_dir="/tmp/test")
        assert result["success"] is True
        assert result["project_path"] == "/tmp/test"
        mock_run.assert_called_once_with("FastAPI blog", "/tmp/test")

    def test_error_handling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试异常处理"""
        monkeypatch.setattr(
            "pycoder.python.generate._run_generate_mode",
            MagicMock(side_effect=RuntimeError("模拟错误")),
        )
        from pycoder.python.generate import generate_project

        result = generate_project("FastAPI blog")
        assert result["success"] is False
        assert "模拟错误" in result["error"]

    def test_default_target_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试默认目标目录"""
        mock_run = MagicMock()
        monkeypatch.setattr(
            "pycoder.python.generate._run_generate_mode", mock_run
        )
        from pycoder.python.generate import generate_project

        result = generate_project("test")
        assert result["success"] is True
        mock_run.assert_called_once_with("test", "")


# ──────────────────────────────────────────────────────────────
# 5. chart_generator 模块测试
# ──────────────────────────────────────────────────────────────


class TestChartGenerator:
    """ChartGenerator 类测试"""

    @pytest.fixture
    def gen(self) -> "ChartGenerator":
        from pycoder.python.chart_generator import ChartGenerator

        return ChartGenerator()

    @pytest.fixture
    def sample_data(self) -> list[dict]:
        """示例图表数据"""
        return [
            {"x": "A", "y": 10, "label": "A", "value": 10},
            {"x": "B", "y": 20, "label": "B", "value": 20},
            {"x": "C", "y": 30, "label": "C", "value": 30},
        ]

    def test_plotly_chart(self, gen: "ChartGenerator", sample_data: list[dict]) -> None:
        """测试生成 Plotly 图表"""
        result = gen.plotly_chart("bar", sample_data, title="测试图表")
        assert result["success"] is True
        assert result["chart_type"] == "bar"
        assert result["title"] == "测试图表"
        assert result["data_points"] == 3
        assert result["is_interactive"] is True
        assert "chart_path" in result
        # 验证文件存在
        import os
        assert os.path.exists(result["chart_path"])
        # 清理临时文件
        os.unlink(result["chart_path"])

    def test_plotly_chart_pie(self, gen: "ChartGenerator", sample_data: list[dict]) -> None:
        """测试饼图"""
        result = gen.plotly_chart("pie", sample_data, title="饼图")
        assert result["chart_type"] == "pie"
        import os
        os.unlink(result["chart_path"])

    def test_plotly_chart_scatter(self, gen: "ChartGenerator", sample_data: list[dict]) -> None:
        """测试散点图"""
        result = gen.plotly_chart("scatter", sample_data)
        assert result["chart_type"] == "scatter"
        import os
        os.unlink(result["chart_path"])

    def test_plotly_chart_html_content(self, gen: "ChartGenerator", sample_data: list[dict]) -> None:
        """测试生成的 HTML 包含必要元素"""
        result = gen.plotly_chart("bar", sample_data, title="HTML 测试")
        import os
        with open(result["chart_path"], encoding="utf-8") as f:
            html = f.read()
        assert "plotly" in html.lower()
        assert "HTML 测试" in html
        os.unlink(result["chart_path"])

    def test_altair_chart(self, gen: "ChartGenerator", sample_data: list[dict]) -> None:
        """测试生成 Altair 规范"""
        result = gen.altair_chart(sample_data, x_field="x", y_field="y", title="Altair 测试")
        assert result["success"] is True
        assert "spec" in result
        assert result["spec"]["mark"] == "bar"
        assert result["spec"]["encoding"]["x"]["field"] == "x"
        assert result["spec"]["encoding"]["y"]["field"] == "y"

    def test_altair_chart_no_title(self, gen: "ChartGenerator", sample_data: list[dict]) -> None:
        """测试无标题的 Altair 图表"""
        result = gen.altair_chart(sample_data, x_field="label", y_field="value")
        assert result["success"] is True

    def test_flame_graph_data_valid(self, gen: "ChartGenerator") -> None:
        """测试火焰图数据生成"""
        profile = {
            "output": "100 main\n50 sub_func\n30 helper\n",
        }
        result = gen.flame_graph_data(profile)
        assert result["success"] is True
        assert result["total_calls"] == 180
        assert len(result["frames"]) == 3
        assert result["format"] == "flame_graph"

    def test_flame_graph_data_empty_output(self, gen: "ChartGenerator") -> None:
        """测试空 profile 输出 — 空字符串被视为缺失"""
        result = gen.flame_graph_data({"output": ""})
        assert result["success"] is False
        assert "error" in result

    def test_flame_graph_data_missing_output(self, gen: "ChartGenerator") -> None:
        """测试缺少 output 字段"""
        result = gen.flame_graph_data({})
        assert result["success"] is False
        assert "error" in result

    def test_flame_graph_data_invalid_lines(self, gen: "ChartGenerator") -> None:
        """测试包含无效行的火焰图数据"""
        profile = {
            "output": "100 main\ninvalid line\n50 sub_func\n",
        }
        result = gen.flame_graph_data(profile)
        assert result["success"] is True
        assert result["total_calls"] == 150

    def test_flame_graph_data_frame_limit(self, gen: "ChartGenerator") -> None:
        """测试火焰图帧数限制为 50"""
        lines = "\n".join(f"{i} func_{i}" for i in range(1, 101))
        profile = {"output": lines}
        result = gen.flame_graph_data(profile)
        assert len(result["frames"]) <= 50

    def test_quick_charts(self, gen: "ChartGenerator", sample_data: list[dict]) -> None:
        """测试快速生成多种图表"""
        charts = gen.quick_charts(sample_data)
        assert len(charts) == 3
        types = [c["type"] for c in charts]
        assert "bar" in types
        assert "line" in types
        assert "pie" in types
        # 清理临时文件
        import os
        for c in charts:
            if "chart_path" in c["chart"]:
                os.unlink(c["chart"]["chart_path"])


class TestChartGeneratorSingleton:
    """ChartGenerator 单例测试"""

    def test_get_chart_generator(self) -> None:
        """测试获取图表生成器单例"""
        from pycoder.python.chart_generator import ChartGenerator, get_chart_generator, _chart_gen

        import pycoder.python.chart_generator as mod
        mod._chart_gen = None

        g1 = get_chart_generator()
        g2 = get_chart_generator()
        assert isinstance(g1, ChartGenerator)
        assert g1 is g2


# ──────────────────────────────────────────────────────────────
# 6. dep_conflict_resolver 模块测试
# ──────────────────────────────────────────────────────────────


class TestDependencyConflictResolver:
    """DependencyConflictResolver 类测试"""

    def test_parse_conflict_standard(self) -> None:
        """测试解析标准冲突行"""
        from pycoder.python.dep_conflict_resolver import DependencyConflictResolver

        resolver = DependencyConflictResolver()
        line = "pkg-a 1.0.0 has requirement pkg-b>=2.0, but you have pkg-b 1.5"
        result = resolver._parse_conflict(line)
        assert result["package"] == "pkg-a"
        assert result["dependency"] == "1.0.0"
        assert result["required"] == "pkg-b>=2.0"
        assert result["installed"] == "pkg-b 1.5"

    def test_parse_conflict_fallback(self) -> None:
        """测试无法解析的冲突行返回原始内容"""
        from pycoder.python.dep_conflict_resolver import DependencyConflictResolver

        resolver = DependencyConflictResolver()
        line = "some random output"
        result = resolver._parse_conflict(line)
        assert "raw" in result
        assert result["raw"] == "some random output"

    def test_parse_conflict_long_line(self) -> None:
        """测试超长冲突行被截断"""
        from pycoder.python.dep_conflict_resolver import DependencyConflictResolver

        resolver = DependencyConflictResolver()
        line = "x" * 300
        result = resolver._parse_conflict(line)
        assert "raw" in result
        assert len(result["raw"]) <= 200

    def test_suggest_fix_no_conflicts(self) -> None:
        """测试无冲突时的建议"""
        from pycoder.python.dep_conflict_resolver import DependencyConflictResolver

        resolver = DependencyConflictResolver()
        suggestions = resolver._suggest_fix([])
        assert len(suggestions) == 1
        assert "无依赖冲突" in suggestions[0]

    def test_suggest_fix_with_conflicts(self) -> None:
        """测试有冲突时的建议"""
        from pycoder.python.dep_conflict_resolver import DependencyConflictResolver

        resolver = DependencyConflictResolver()
        conflicts = [
            {
                "package": "pkg-a",
                "dependency": "1.0",
                "required": "pkg-b>=2.0",
                "installed": "pkg-b 1.5",
            }
        ]
        suggestions = resolver._suggest_fix(conflicts)
        assert len(suggestions) >= 1
        assert "pkg-a" in suggestions[0]

    def test_suggest_fix_dedup(self) -> None:
        """测试去重相同包名冲突"""
        from pycoder.python.dep_conflict_resolver import DependencyConflictResolver

        resolver = DependencyConflictResolver()
        conflicts = [
            {"package": "pkg-a", "required": "b>=1", "installed": "b 0.5"},
            {"package": "pkg-a", "required": "c>=1", "installed": "c 0.5"},
        ]
        suggestions = resolver._suggest_fix(conflicts)
        assert len(suggestions) == 1  # 去重后只有一条

    def test_analyze_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试分析成功（无冲突）"""
        mock_run = MagicMock()
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        monkeypatch.setattr(subprocess, "run", mock_run)
        from pycoder.python.dep_conflict_resolver import DependencyConflictResolver

        resolver = DependencyConflictResolver()
        result = resolver.analyze(".")
        assert result["success"] is True
        assert result["conflict_count"] == 0

    def test_analyze_with_conflicts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试分析有冲突"""
        mock_run = MagicMock()
        mock_run.return_value.stdout = (
            "pkg-a 1.0.0 has requirement pkg-b>=2.0, but you have pkg-b 1.5 which is incompatible\n"
        )
        mock_run.return_value.stderr = ""
        monkeypatch.setattr(subprocess, "run", mock_run)
        from pycoder.python.dep_conflict_resolver import DependencyConflictResolver

        resolver = DependencyConflictResolver()
        result = resolver.analyze(".")
        assert result["success"] is True
        assert result["conflict_count"] == 1

    def test_analyze_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试分析异常"""
        monkeypatch.setattr(
            subprocess, "run", MagicMock(side_effect=OSError("pip not found"))
        )
        from pycoder.python.dep_conflict_resolver import DependencyConflictResolver

        resolver = DependencyConflictResolver()
        result = resolver.analyze(".")
        assert result["success"] is False
        assert "error" in result


class TestDependencyConflictResolverSingleton:
    """DependencyConflictResolver 单例测试"""

    def test_get_dep_resolver(self) -> None:
        """测试获取依赖冲突解析器单例"""
        from pycoder.python.dep_conflict_resolver import (
            DependencyConflictResolver,
            get_dep_resolver,
            _resolver,
        )

        import pycoder.python.dep_conflict_resolver as mod
        mod._resolver = None

        r1 = get_dep_resolver()
        r2 = get_dep_resolver()
        assert isinstance(r1, DependencyConflictResolver)
        assert r1 is r2


# ──────────────────────────────────────────────────────────────
# 7. runtime_installer 模块测试
# ──────────────────────────────────────────────────────────────


class TestRuntimeInstaller:
    """RuntimeInstaller 类测试"""

    def test_check_unknown_language(self) -> None:
        """测试检查未知运行时"""
        from pycoder.python.runtime_installer import RuntimeInstaller

        installer = RuntimeInstaller()
        result = installer.check("unknown")
        assert result["available"] is False
        assert "未知运行时" in result["error"]

    def test_check_missing_runtime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试运行时未安装"""
        monkeypatch.setattr("shutil.which", lambda x: None)
        from pycoder.python.runtime_installer import RuntimeInstaller

        installer = RuntimeInstaller()
        result = installer.check("go")
        assert result["available"] is False
        assert "missing" in result
        assert "install_hint" in result

    def test_check_installed_runtime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试运行时已安装"""
        monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/go")
        mock_run = MagicMock()
        mock_run.return_value.stdout = "go version go1.21.0\n"
        mock_run.return_value.stderr = ""
        monkeypatch.setattr(subprocess, "run", mock_run)
        from pycoder.python.runtime_installer import RuntimeInstaller

        installer = RuntimeInstaller()
        result = installer.check("go")
        assert result["available"] is True
        assert "go1.21.0" in result["version"]

    def test_check_version_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试版本检查失败但命令存在"""
        monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/go")
        monkeypatch.setattr(
            subprocess, "run", MagicMock(side_effect=OSError("fail"))
        )
        from pycoder.python.runtime_installer import RuntimeInstaller

        installer = RuntimeInstaller()
        result = installer.check("go")
        assert result["available"] is True
        assert "版本未知" in result["version"]

    def test_check_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试检查所有运行时"""
        monkeypatch.setattr("shutil.which", lambda x: None)
        from pycoder.python.runtime_installer import RuntimeInstaller

        installer = RuntimeInstaller()
        results = installer.check_all()
        assert isinstance(results, dict)
        assert len(results) >= 6  # 至少有 6 种运行时
        assert "java" in results
        assert "go" in results
        assert "node" in results

    def test_install_unknown(self) -> None:
        """测试安装未知运行时"""
        from pycoder.python.runtime_installer import RuntimeInstaller

        installer = RuntimeInstaller()
        result = installer.install("unknown")
        assert result["success"] is False
        assert "未知运行时" in result["error"]

    def test_install_preview_mode(self) -> None:
        """测试安装预览模式（不实际安装）"""
        from pycoder.python.runtime_installer import RuntimeInstaller

        installer = RuntimeInstaller()
        result = installer.install("go")
        assert result["success"] is False
        assert "hint" in result
        assert "command" in result

    def test_scan_workspace_needs_empty(self, tmp_path: Path) -> None:
        """测试扫描空工作区"""
        from pycoder.python.runtime_installer import RuntimeInstaller

        installer = RuntimeInstaller()
        needs = installer.scan_workspace_needs(str(tmp_path))
        assert needs == []

    def test_scan_workspace_needs_go(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试扫描发现 Go 项目"""
        (tmp_path / "go.mod").write_text("module test", encoding="utf-8")
        monkeypatch.setattr("shutil.which", lambda x: None)
        from pycoder.python.runtime_installer import RuntimeInstaller

        installer = RuntimeInstaller()
        needs = installer.scan_workspace_needs(str(tmp_path))
        assert any(n["language"] == "go" for n in needs)

    def test_scan_workspace_needs_node(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试扫描发现 Node 项目"""
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr("shutil.which", lambda x: None)
        from pycoder.python.runtime_installer import RuntimeInstaller

        installer = RuntimeInstaller()
        needs = installer.scan_workspace_needs(str(tmp_path))
        assert any(n["language"] == "node" for n in needs)

    def test_scan_workspace_needs_rust(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试扫描发现 Rust 项目"""
        (tmp_path / "Cargo.toml").write_text("[package]", encoding="utf-8")
        monkeypatch.setattr("shutil.which", lambda x: None)
        from pycoder.python.runtime_installer import RuntimeInstaller

        installer = RuntimeInstaller()
        needs = installer.scan_workspace_needs(str(tmp_path))
        assert any(n["language"] == "rust" for n in needs)

    def test_scan_workspace_needs_docker(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试扫描发现 Docker 项目"""
        (tmp_path / "Dockerfile").write_text("FROM python", encoding="utf-8")
        monkeypatch.setattr("shutil.which", lambda x: None)
        from pycoder.python.runtime_installer import RuntimeInstaller

        installer = RuntimeInstaller()
        needs = installer.scan_workspace_needs(str(tmp_path))
        assert any(n["language"] == "docker" for n in needs)


class TestRuntimeInstallerSingleton:
    """RuntimeInstaller 单例测试"""

    def test_get_runtime_installer(self) -> None:
        """测试获取运行时安装器单例"""
        from pycoder.python.runtime_installer import (
            RuntimeInstaller,
            get_runtime_installer,
            _installer,
        )

        import pycoder.python.runtime_installer as mod
        mod._installer = None

        i1 = get_runtime_installer()
        i2 = get_runtime_installer()
        assert isinstance(i1, RuntimeInstaller)
        assert i1 is i2


# ──────────────────────────────────────────────────────────────
# 8. net/client 模块测试
# ──────────────────────────────────────────────────────────────


class TestCreateHttpxClient:
    """create_httpx_client 函数测试"""

    def test_create_default(self) -> None:
        """测试创建默认同步客户端"""
        from pycoder.net.client import create_httpx_client

        client = create_httpx_client()
        assert client is not None
        client.close()

    def test_create_with_custom_timeout(self) -> None:
        """测试自定义超时"""
        import httpx
        from pycoder.net.client import create_httpx_client

        client = create_httpx_client(timeout=30.0)
        assert client.timeout == httpx.Timeout(30.0)
        client.close()

    def test_create_with_headers(self) -> None:
        """测试自定义请求头"""
        from pycoder.net.client import create_httpx_client

        client = create_httpx_client(headers={"X-Custom": "value"})
        assert client.headers.get("x-custom") == "value"
        client.close()

    def test_create_no_verify(self) -> None:
        """测试禁用 SSL 验证"""
        from pycoder.net.client import create_httpx_client

        client = create_httpx_client(verify=False)
        client.close()

    def test_create_follow_redirects(self) -> None:
        """测试跟随重定向"""
        from pycoder.net.client import create_httpx_client

        client = create_httpx_client(follow_redirects=True)
        client.close()


class TestCreateAsyncHttpxClient:
    """create_async_httpx_client 函数测试"""

    def test_create_default(self) -> None:
        """测试创建默认异步客户端"""
        import anyio
        import httpx
        from pycoder.net.client import create_async_httpx_client

        client = create_async_httpx_client()
        assert isinstance(client, httpx.AsyncClient)
        anyio.run(client.aclose)

    def test_create_with_custom_timeout(self) -> None:
        """测试自定义超时"""
        import anyio
        import httpx
        from pycoder.net.client import create_async_httpx_client

        client = create_async_httpx_client(timeout=60.0)
        assert client.timeout == httpx.Timeout(60.0)
        anyio.run(client.aclose)

    def test_create_with_headers(self) -> None:
        """测试自定义请求头"""
        import anyio
        from pycoder.net.client import create_async_httpx_client

        client = create_async_httpx_client(headers={"Authorization": "Bearer token"})
        assert client.headers.get("authorization") == "Bearer token"
        anyio.run(client.aclose)


class TestHTTPClient:
    """HTTPClient 类测试

    注意: 标记为 network 的测试需要能访问 httpbin.org。
    设置 RUN_NETWORK_TESTS=1 环境变量来启用。
    """

    # 网络测试跳过标记（遵循项目 conftest.py 模式）
    _needs_network = pytest.mark.skipif(
        "not os.environ.get('RUN_NETWORK_TESTS')",
        reason="需要网络连接 — 设置 RUN_NETWORK_TESTS=1 启用",
    )

    def test_init_default(self) -> None:
        """测试默认初始化"""
        from pycoder.net.client import HTTPClient

        client = HTTPClient()
        assert client._base_url is None
        assert client._max_retries == 2
        assert client._headers == {}

    def test_init_with_base_url(self) -> None:
        """测试带 base_url 初始化"""
        from pycoder.net.client import HTTPClient

        client = HTTPClient(base_url="https://api.example.com")
        assert client._base_url == "https://api.example.com"

    def test_init_with_custom_timeout(self) -> None:
        """测试自定义超时"""
        from pycoder.net.client import HTTPClient

        client = HTTPClient(timeout=30.0)
        assert client._timeout == 30.0

    def test_init_with_headers(self) -> None:
        """测试自定义请求头"""
        from pycoder.net.client import HTTPClient

        client = HTTPClient(headers={"X-API-Key": "abc123"})
        assert client._headers == {"X-API-Key": "abc123"}

    def test_init_with_retries(self) -> None:
        """测试自定义重试次数"""
        from pycoder.net.client import HTTPClient

        client = HTTPClient(max_retries=5)
        assert client._max_retries == 5

    @pytest.mark.anyio
    @pytest.mark.skipif(
        "not os.environ.get('RUN_NETWORK_TESTS')",
        reason="需要网络连接 — 设置 RUN_NETWORK_TESTS=1 启用",
    )
    async def test_async_context_manager(self) -> None:
        """测试 async context manager"""
        from pycoder.net.client import HTTPClient

        async with HTTPClient(base_url="https://httpbin.org") as client:
            assert client._client is not None
        assert client._client is None

    @pytest.mark.anyio
    async def test_aclose(self) -> None:
        """测试手动关闭客户端"""
        from pycoder.net.client import HTTPClient

        client = HTTPClient()
        async with client:
            pass
        # 二次关闭不报错
        await client.aclose()

    @pytest.mark.anyio
    async def test_request_without_context_manager(self) -> None:
        """测试不通过 context manager 直接调用 request"""
        from pycoder.net.client import HTTPClient

        client = HTTPClient()
        with pytest.raises(AssertionError, match="must be used as async context manager"):
            await client.request("GET", "https://example.com")

    @pytest.mark.anyio
    @pytest.mark.skipif(
        "not os.environ.get('RUN_NETWORK_TESTS')",
        reason="需要网络连接 — 设置 RUN_NETWORK_TESTS=1 启用",
    )
    async def test_get(self) -> None:
        """测试 GET 请求"""
        from pycoder.net.client import HTTPClient

        async with HTTPClient(base_url="https://httpbin.org") as client:
            resp = await client.get("/get")
            assert resp.status_code == 200

    @pytest.mark.anyio
    @pytest.mark.skipif(
        "not os.environ.get('RUN_NETWORK_TESTS')",
        reason="需要网络连接 — 设置 RUN_NETWORK_TESTS=1 启用",
    )
    async def test_post(self) -> None:
        """测试 POST 请求"""
        from pycoder.net.client import HTTPClient

        async with HTTPClient(base_url="https://httpbin.org") as client:
            resp = await client.post("/post", json={"key": "value"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["json"] == {"key": "value"}

    @pytest.mark.anyio
    @pytest.mark.skipif(
        "not os.environ.get('RUN_NETWORK_TESTS')",
        reason="需要网络连接 — 设置 RUN_NETWORK_TESTS=1 启用",
    )
    async def test_delete(self) -> None:
        """测试 DELETE 请求"""
        from pycoder.net.client import HTTPClient

        async with HTTPClient(base_url="https://httpbin.org") as client:
            resp = await client.delete("/delete")
            assert resp.status_code == 200

    @pytest.mark.anyio
    @pytest.mark.skipif(
        "not os.environ.get('RUN_NETWORK_TESTS')",
        reason="需要网络连接 — 设置 RUN_NETWORK_TESTS=1 启用",
    )
    async def test_get_json(self) -> None:
        """测试 get_json 方法"""
        from pycoder.net.client import HTTPClient

        async with HTTPClient(base_url="https://httpbin.org") as client:
            data = await client.get_json("/get")
            assert isinstance(data, dict)
            assert "url" in data

    @pytest.mark.anyio
    @pytest.mark.skipif(
        "not os.environ.get('RUN_NETWORK_TESTS')",
        reason="需要网络连接 — 设置 RUN_NETWORK_TESTS=1 启用",
    )
    async def test_get_json_raises_on_error(self) -> None:
        """测试 get_json 对错误状态码抛出异常"""
        from pycoder.net.client import HTTPClient

        async with HTTPClient(base_url="https://httpbin.org") as client:
            with pytest.raises(Exception):
                await client.get_json("/status/404")

    @pytest.mark.anyio
    @pytest.mark.skipif(
        "not os.environ.get('RUN_NETWORK_TESTS')",
        reason="需要网络连接 — 设置 RUN_NETWORK_TESTS=1 启用",
    )
    async def test_stream(self) -> None:
        """测试流式请求"""
        from pycoder.net.client import HTTPClient

        async with HTTPClient(base_url="https://httpbin.org") as client:
            async with client.stream("GET", "/get") as resp:
                assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_stream_without_context_manager(self) -> None:
        """测试不通过 context manager 调用 stream"""
        from pycoder.net.client import HTTPClient

        client = HTTPClient()
        with pytest.raises(AssertionError, match="must be used as async context manager"):
            client.stream("GET", "https://example.com")

    @pytest.mark.anyio
    async def test_retry_on_timeout(self) -> None:
        """测试重试逻辑（超时异常）"""
        import httpx
        from pycoder.net.client import HTTPClient

        client = HTTPClient(max_retries=2)

        async with client:
            # 模拟前两次请求失败，第三次成功
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()

            call_count = [0]

            async def mock_request(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] < 3:
                    raise httpx.TimeoutException("timeout")
                return mock_resp

            client._client.request = mock_request  # type: ignore[assignment]
            resp = await client.request("GET", "/test")
            assert call_count[0] == 3
            assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_retry_exhausted(self) -> None:
        """测试重试耗尽后抛出异常"""
        import httpx
        from pycoder.net.client import HTTPClient

        client = HTTPClient(max_retries=2)

        async with client:
            async def always_fail(*args, **kwargs):
                raise httpx.ConnectError("connection failed")

            client._client.request = always_fail  # type: ignore[assignment]
            with pytest.raises(httpx.ConnectError):
                await client.request("GET", "/test")

    @pytest.mark.anyio
    @pytest.mark.skipif(
        "not os.environ.get('RUN_NETWORK_TESTS')",
        reason="需要网络连接 — 设置 RUN_NETWORK_TESTS=1 启用",
    )
    async def test_request_raise_for_status(self) -> None:
        """测试 raise_for_status 参数"""
        from pycoder.net.client import HTTPClient

        async with HTTPClient(base_url="https://httpbin.org") as client:
            with pytest.raises(Exception):
                await client.request("GET", "/status/500", raise_for_status=True)

    @pytest.mark.anyio
    @pytest.mark.skipif(
        "not os.environ.get('RUN_NETWORK_TESTS')",
        reason="需要网络连接 — 设置 RUN_NETWORK_TESTS=1 启用",
    )
    async def test_request_no_raise_for_status(self) -> None:
        """测试不抛出状态错误"""
        from pycoder.net.client import HTTPClient

        async with HTTPClient(base_url="https://httpbin.org") as client:
            resp = await client.request("GET", "/status/404", raise_for_status=False)
            assert resp.status_code == 404


class TestNetClientExports:
    """net/client 模块导出的异常类型测试"""

    def test_connect_error_export(self) -> None:
        """测试 ConnectError 导出"""
        from pycoder.net.client import ConnectError
        import httpx

        assert ConnectError is httpx.ConnectError

    def test_timeout_exception_export(self) -> None:
        """测试 TimeoutException 导出"""
        from pycoder.net.client import TimeoutException
        import httpx

        assert TimeoutException is httpx.TimeoutException

    def test_http_error_export(self) -> None:
        """测试 HTTPError 导出"""
        from pycoder.net.client import HTTPError
        import httpx

        assert HTTPError is httpx.HTTPError

    def test_transport_error_export(self) -> None:
        """测试 TransportError 导出"""
        from pycoder.net.client import TransportError
        import httpx

        assert TransportError is httpx.TransportError

    def test_default_timeout(self) -> None:
        """测试默认超时值"""
        from pycoder.net.client import DEFAULT_TIMEOUT

        assert DEFAULT_TIMEOUT == 10.0