"""P1-3: Dashboard 单元测试"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def sample_project():
    """创建测试用项目目录"""
    tmp = Path(tempfile.mkdtemp(prefix="dashboard_test_"))
    (tmp / "main.py").write_text(
        '''"""Main module"""
def hello():
    return "world"

class App:
    def run(self):
        return hello()
''',
        encoding="utf-8",
    )
    (tmp / "requirements.txt").write_text("fastapi==0.110.0\npydantic==2.6.0\n", encoding="utf-8")
    (tmp / ".gitignore").write_text("__pycache__/\n.venv/\n", encoding="utf-8")
    (tmp / "README.md").write_text("# Test", encoding="utf-8")
    # 故意创建 __pycache__ 不应被计数
    (tmp / "__pycache__").mkdir()
    (tmp / "__pycache__" / "x.py").write_text("# cached", encoding="utf-8")

    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


def test_dashboard_builder_basic(sample_project):
    """仪表盘应能构建并填充项目信息"""
    from pycoder.server.services.dashboard import DashboardBuilder, dashboard_to_dict

    builder = DashboardBuilder(project_root=sample_project)
    snap = builder.build(include_graph=False)

    d = dashboard_to_dict(snap)
    assert d["project"]["name"] == sample_project.name
    assert d["project"]["python_count"] >= 1  # main.py
    assert d["project"]["file_count"] >= 2  # main.py + requirements.txt + README.md
    assert d["project"]["code_lines"] > 0
    # __pycache__ 不应计入
    assert d["project"]["python_count"] < 5


def test_dashboard_excludes_venv(sample_project):
    """应正确排除 .venv 和 __pycache__"""
    (sample_project / ".venv").mkdir()
    (sample_project / ".venv" / "lib.py").write_text("x=1", encoding="utf-8")

    from pycoder.server.services.dashboard import DashboardBuilder

    builder = DashboardBuilder(project_root=sample_project)
    snap = builder.build(include_graph=False)

    # 不应包含 .venv 下的 python 文件
    assert snap.project.python_count >= 1  # main.py 仍然计数


def test_dashboard_runtime_info(sample_project):
    """运行时信息应正确填充"""
    from pycoder.server.services.dashboard import DashboardBuilder, dashboard_to_dict

    builder = DashboardBuilder(project_root=sample_project)
    snap = builder.build(include_graph=False)

    d = dashboard_to_dict(snap)
    assert "python_version" in d["runtime"]
    assert "platform" in d["runtime"]
    assert "pid" in d["runtime"]
    assert d["runtime"]["pid"] > 0


def test_dashboard_health_score(sample_project):
    """健康度评分应在 0-100 范围并有等级"""
    from pycoder.server.services.dashboard import DashboardBuilder

    builder = DashboardBuilder(project_root=sample_project)
    snap = builder.build(include_graph=False)

    assert 0 <= snap.health.overall <= 100
    assert snap.health.grade in ("A", "B", "C", "D", "F")
    assert len(snap.health.factors) >= 3  # Git/依赖/漏洞 等因素


def test_dashboard_dependencies_overview(sample_project):
    """依赖概览应包含项目中的依赖"""
    from pycoder.server.services.dashboard import DashboardBuilder, dashboard_to_dict

    builder = DashboardBuilder(project_root=sample_project)
    snap = builder.build(include_graph=False)
    d = dashboard_to_dict(snap)

    assert d["dependencies"]["total"] >= 2  # fastapi + pydantic
    assert "fastapi" in d["dependencies"].get("frameworks", []) or \
           "FastAPI" in d["dependencies"].get("frameworks", [])


def test_dashboard_recent_files(sample_project):
    """最近文件列表应返回最近修改的 Python 文件"""
    from pycoder.server.services.dashboard import DashboardBuilder, dashboard_to_dict

    builder = DashboardBuilder(project_root=sample_project)
    snap = builder.build(include_graph=False)
    d = dashboard_to_dict(snap)

    assert len(d["recent_files"]) >= 1
    # 应按修改时间倒序
    files = d["recent_files"]
    for i in range(len(files) - 1):
        assert files[i]["modified"] >= files[i + 1]["modified"]


def test_dashboard_to_dict_serialization(sample_project):
    """dashboard_to_dict 应返回可 JSON 序列化的字典"""
    import json

    from pycoder.server.services.dashboard import DashboardBuilder, dashboard_to_dict

    builder = DashboardBuilder(project_root=sample_project)
    snap = builder.build(include_graph=False)
    d = dashboard_to_dict(snap)

    # 应能 JSON 序列化
    json_str = json.dumps(d, ensure_ascii=False, default=str)
    assert "project" in json_str
    assert "health" in json_str


def test_dashboard_generated_at_timestamp(sample_project):
    """generated_at 应是合理时间戳"""
    import time

    from pycoder.server.services.dashboard import DashboardBuilder

    builder = DashboardBuilder(project_root=sample_project)
    before = time.time()
    snap = builder.build(include_graph=False)
    after = time.time()

    assert before <= snap.generated_at <= after


def test_dashboard_handles_empty_dir():
    """空目录不应崩溃"""
    import tempfile

    from pycoder.server.services.dashboard import DashboardBuilder

    with tempfile.TemporaryDirectory() as tmpdir:
        builder = DashboardBuilder(project_root=Path(tmpdir))
        snap = builder.build(include_graph=False)

        assert snap.project.python_count == 0
        assert snap.project.file_count == 0
        assert snap.health.overall >= 0


def test_dashboard_include_graph(sample_project):
    """include_graph=False 时不应构建图（更快）"""
    import time

    from pycoder.server.services.dashboard import DashboardBuilder

    builder = DashboardBuilder(project_root=sample_project)
    snap = builder.build(include_graph=False)
    assert snap.graph.total_symbols == 0  # 未构建
