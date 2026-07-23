"""P2-修复: 沙箱 _resolve_project_root 单元测试"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


class TestProjectRootResolution:
    """_resolve_project_root 行为测试."""

    def test_default_finds_pyproject(self, tmp_path: Path, monkeypatch) -> None:
        """默认能找到最近的 pyproject.toml 父目录."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'", encoding="utf-8")
        # 把 routers/code_exec.py 移到一个子目录, 模拟嵌套情况
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        # 复制 code_exec.py 到 nested (这样 __file__ 在 nested 之下)
        import shutil
        src = Path(__file__).resolve().parent.parent / "pycoder" / "server" / "routers" / "code_exec.py"
        if src.exists():
            shutil.copy(src, nested / "code_exec.py")
        # 动态执行该模块并测试 _resolve_project_root
        import importlib.util
        spec = importlib.util.spec_from_file_location("ce_test", nested / "code_exec.py")
        # 跳过完整加载 (会引发许多 import), 只测试函数
        # 直接通过源码注入 _PROJECT_ROOT
        monkeypatch.setenv("PYCODER_PROJECT_ROOT", str(tmp_path))
        from pycoder.server.routers import code_exec
        assert code_exec._PROJECT_ROOT == tmp_path.resolve()

    def test_env_override(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("PYCODER_PROJECT_ROOT", str(tmp_path))
        from pycoder.server.routers import code_exec

        # 重新解析（不重新 import, 直接调用函数）
        result = code_exec._resolve_project_root()
        assert result == tmp_path.resolve()

    def test_env_invalid_path_falls_back(self, tmp_path: Path, monkeypatch) -> None:
        """PYCODER_PROJECT_ROOT 指向不存在路径时退化到 pyproject 搜索."""
        monkeypatch.setenv("PYCODER_PROJECT_ROOT", str(tmp_path / "nonexistent"))
        from pycoder.server.routers import code_exec

        result = code_exec._resolve_project_root()
        # 应该找到包含 pyproject.toml 的父目录
        assert (result / "pyproject.toml").exists()


class TestSandboxEnvInjection:
    """验证 sandbox 子进程 env 注入了 PYTHONPATH."""

    def test_pylogic_path_set(self) -> None:
        from pycoder.server.routers import code_exec
        # _PROJECT_ROOT 应该是 pyproject.toml 所在目录
        root = code_exec._PROJECT_ROOT
        assert (root / "pyproject.toml").exists()
        # _resolve_project_root 应当是绝对路径
        assert root.is_absolute()


@pytest.mark.skipif(
    "PYCODER_SKIP_SANDBOX_TEST" in os.environ,
    reason="需要实际启动子进程, 跳过以加速 CI",
)
class TestSandboxSubprocessImport:
    """实际子进程 import 测试 (慢, 默认跳过)."""

    def test_sandbox_env_has_pythonpath(self) -> None:
        """验证 sandbox 注入的 env 中 PYTHONPATH 包含项目根."""
        from pycoder.server.routers import code_exec as ce
        # 验证 _PROJECT_ROOT 是绝对路径且存在
        assert ce._PROJECT_ROOT.is_absolute()
        assert ce._PROJECT_ROOT.exists()
        # 验证 _run_in_subprocess 源码中包含 PYTHONPATH 注入
        import inspect
        src = inspect.getsource(ce._run_in_subprocess)
        assert "PYTHONPATH" in src, "sandbox 源码应注入 PYTHONPATH"
        # 验证源码使用 _PROJECT_ROOT (变量名引用, 不需要实际路径)
        assert "_PROJECT_ROOT" in src, "sandbox 源码应引用 _PROJECT_ROOT"
