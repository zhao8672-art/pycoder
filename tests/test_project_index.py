"""project_index.py 单元测试 — 项目虚拟文件索引"""

from __future__ import annotations

import pytest
from pathlib import Path

from pycoder.io.project_index import (
    FileSummary,
    ProjectIndex,
    get_project_index,
)


class TestFileSummary:
    """FileSummary 数据类测试"""

    def test_default_values(self) -> None:
        summary = FileSummary(path="test.py")
        assert summary.path == "test.py"
        assert summary.module == ""
        assert summary.size == 0
        assert summary.symbols == []
        assert summary.imports == []

    def test_to_dict(self) -> None:
        summary = FileSummary(
            path="src/app.py",
            module="src.app",
            size=1024,
            content_hash="abc123",
        )
        d = summary.to_dict()
        assert d["path"] == "src/app.py"
        assert d["module"] == "src.app"
        assert d["size"] == 1024


class TestProjectIndex:
    """ProjectIndex 核心功能测试"""

    @pytest.fixture
    def indexer(self, tmp_path: Path) -> ProjectIndex:
        """创建索引器 (无持久化)"""
        return ProjectIndex(cache_path=None)

    @pytest.fixture
    def sample_project(self, tmp_path: Path) -> Path:
        """创建示例项目结构"""
        # 创建 Python 文件
        (tmp_path / "app.py").write_text(
            "import os\n"
            "from pathlib import Path\n"
            "\n"
            "class MyApp:\n"
            "    def run(self):\n"
            "        pass\n"
            "\n"
            "def main():\n"
            "    pass\n",
            encoding="utf-8",
        )
        # 创建子目录
        (tmp_path / "utils").mkdir()
        (tmp_path / "utils" / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "utils" / "helper.py").write_text(
            "def helper_func():\n"
            "    return 42\n",
            encoding="utf-8",
        )
        # 创建配置文件
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test_project"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )
        (tmp_path / "requirements.txt").write_text(
            "fastapi\npytest\nrequests\n",
            encoding="utf-8",
        )
        # 创建忽略目录
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "app.cpython-314.pyc").write_text("", encoding="utf-8")
        return tmp_path

    def test_scan_project(self, indexer: ProjectIndex, sample_project: Path) -> None:
        """测试扫描项目"""
        count = indexer.scan_project(sample_project)
        assert count >= 5  # app.py, utils/__init__.py, utils/helper.py, pyproject.toml, requirements.txt
        # __pycache__ 应被忽略
        assert all("__pycache__" not in p for p in indexer._index)

    def test_find_symbol(self, indexer: ProjectIndex, sample_project: Path) -> None:
        """测试符号查找"""
        indexer.scan_project(sample_project)
        results = indexer.find_symbol("MyApp")
        assert len(results) >= 1
        assert "app.py" in results[0]

    def test_find_symbol_fuzzy(self, indexer: ProjectIndex, sample_project: Path) -> None:
        """测试模糊符号查找"""
        indexer.scan_project(sample_project)
        results = indexer.find_symbol("helper")
        assert len(results) >= 1
        assert "helper" in results[0]

    def test_find_symbol_not_found(self, indexer: ProjectIndex, sample_project: Path) -> None:
        """测试查找不存在的符号"""
        indexer.scan_project(sample_project)
        results = indexer.find_symbol("NonExistentClass")
        assert results == []

    def test_find_file(self, indexer: ProjectIndex, sample_project: Path) -> None:
        """测试文件名查找"""
        indexer.scan_project(sample_project)
        results = indexer.find_file("*.py")
        assert len(results) >= 3
        assert any("app.py" in r for r in results)

    def test_find_file_toml(self, indexer: ProjectIndex, sample_project: Path) -> None:
        """测试查找配置文件"""
        indexer.scan_project(sample_project)
        results = indexer.find_file("*.toml")
        assert len(results) >= 1
        assert "pyproject.toml" in results[0]

    def test_get_summary(self, indexer: ProjectIndex, sample_project: Path) -> None:
        """测试获取文件摘要"""
        indexer.scan_project(sample_project)
        summary = indexer.get_summary("app.py")
        assert summary is not None
        assert summary.module == "app"
        assert summary.size > 0

    def test_get_summary_not_found(self, indexer: ProjectIndex, sample_project: Path) -> None:
        """测试获取不存在的文件摘要"""
        indexer.scan_project(sample_project)
        summary = indexer.get_summary("nonexistent.py")
        assert summary is None

    def test_export_summary(self, indexer: ProjectIndex, sample_project: Path) -> None:
        """测试导出索引摘要"""
        indexer.scan_project(sample_project)
        summary = indexer.export_summary()
        assert summary["total_files"] >= 5
        assert "dir_structure" in summary
        assert "symbols" in summary
        assert summary["root"] != ""

    def test_get_stats(self, indexer: ProjectIndex, sample_project: Path) -> None:
        """测试获取统计信息"""
        indexer.scan_project(sample_project)
        stats = indexer.get_stats()
        assert stats["total_files"] >= 5
        assert stats["total_symbols"] >= 3  # MyApp, run, main, helper_func
        assert stats["total_size_bytes"] > 0
        assert stats["cache_enabled"] is False

    def test_config_items(self, indexer: ProjectIndex, sample_project: Path) -> None:
        """测试配置文件解析"""
        indexer.scan_project(sample_project)
        toml_summary = indexer.get_summary("pyproject.toml")
        assert toml_summary is not None
        assert toml_summary.config_items.get("name") == "test_project"
        assert toml_summary.config_items.get("version") == "1.0.0"

    def test_update_file(self, indexer: ProjectIndex, sample_project: Path) -> None:
        """测试增量更新文件"""
        indexer.scan_project(sample_project)
        # 修改文件
        (sample_project / "app.py").write_text(
            "class NewClass:\n    pass\n",
            encoding="utf-8",
        )
        indexer.update_file(sample_project / "app.py")
        results = indexer.find_symbol("NewClass")
        assert len(results) >= 1

    def test_remove_file(self, indexer: ProjectIndex, sample_project: Path) -> None:
        """测试移除文件"""
        indexer.scan_project(sample_project)
        assert indexer.get_summary("app.py") is not None
        indexer.remove_file(sample_project / "app.py")
        assert indexer.get_summary("app.py") is None

    def test_persist_and_load(self, tmp_path: Path) -> None:
        """测试 SQLite 持久化"""
        cache_path = tmp_path / "index.db"
        indexer1 = ProjectIndex(cache_path=cache_path)

        # 创建测试文件
        (tmp_path / "test.py").write_text("def foo(): pass\n", encoding="utf-8")
        indexer1.scan_project(tmp_path)
        assert cache_path.exists()

        # 创建新索引器加载缓存
        indexer2 = ProjectIndex(cache_path=cache_path)
        assert indexer2.get_summary("test.py") is not None
        assert len(indexer2.find_symbol("foo")) >= 1


class TestGetProjectIndex:
    """全局单例测试"""

    def test_singleton(self) -> None:
        idx1 = get_project_index()
        idx2 = get_project_index()
        assert idx1 is idx2
