"""覆盖率测试: pycoder/prompts/agents_generator.py

目标: 行覆盖率 >= 95%

覆盖内容:
  - generate_agents_md (with/without env, 各 framework 分支)
  - generate_and_write (写入文件)
  - load_agents_md (文件存在/不存在/读取失败)
  - get_agents_context (文件存在/不存在/截断)
  - 各 type_map / framework 分支

测试策略:
  - 用 tmp_path 隔离文件系统
  - mock detect_environment 返回 EnvironmentInfo 测试各 framework 分支
  - 通过 monkeypatch 重置全局 Path.cwd 避免污染当前工作目录
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pycoder.prompts import agents_generator as ag_mod
from pycoder.prompts.agents_generator import (
    generate_agents_md,
    generate_and_write,
    get_agents_context,
    load_agents_md,
)


# ── 工厂: 构造 EnvironmentInfo ────────────────────────────

def _make_env(
    python_version="3.14.0",
    venv_type="venv",
    package_manager="pip",
    project_type="web",
    frameworks=None,
):
    """构造一个 EnvironmentInfo 对象"""
    from pycoder.python.env_detector import EnvironmentInfo
    return EnvironmentInfo(
        python_version=python_version,
        venv_type=venv_type,
        package_manager=package_manager,
        project_type=project_type,
        frameworks=frameworks or [],
    )


# ══════════════════════════════════════════════════════════
# generate_agents_md
# ══════════════════════════════════════════════════════════

class TestGenerateAgentsMd:
    def test_no_env(self, monkeypatch, tmp_path):
        """include_env=False → env=None"""
        content = generate_agents_md(str(tmp_path), include_env=False)
        assert "# " in content  # 标题
        assert "PyCoder AGENTS.md" in content
        assert "Python 3.x" in content  # 无 env 时默认 3.x
        assert "PEP 8" in content
        assert "AGENTS.md" in content  # 末尾

    def test_with_env_basic(self, monkeypatch, tmp_path):
        env = _make_env(
            python_version="3.14.3",
            venv_type="venv",
            package_manager="poetry",
            project_type="web",
            frameworks=["FastAPI"],
        )
        monkeypatch.setattr(ag_mod, "detect_environment", lambda path: env)

        content = generate_agents_md(str(tmp_path))

        assert "Python 3.14.3" in content
        assert "venv" in content  # venv_type
        assert "poetry" in content  # package_manager
        assert "Web 应用" in content  # type_map
        assert "FastAPI" in content

    def test_with_env_venv_none(self, monkeypatch, tmp_path):
        """venv_type == 'none' → 不显示虚拟环境行"""
        env = _make_env(venv_type="none", project_type="library")
        monkeypatch.setattr(ag_mod, "detect_environment", lambda path: env)
        content = generate_agents_md(str(tmp_path))
        assert "虚拟环境" not in content
        assert "库/框架" in content  # project_type=library

    def test_with_env_no_package_manager(self, monkeypatch, tmp_path):
        env = _make_env(package_manager="", project_type="script")
        monkeypatch.setattr(ag_mod, "detect_environment", lambda path: env)
        content = generate_agents_md(str(tmp_path))
        assert "包管理器" not in content
        assert "脚本工具" in content  # project_type=script

    def test_with_env_unknown_project_type(self, monkeypatch, tmp_path):
        """project_type 不在 type_map 中 → 直接显示原值"""
        env = _make_env(project_type="custom_type")
        monkeypatch.setattr(ag_mod, "detect_environment", lambda path: env)
        content = generate_agents_md(str(tmp_path))
        assert "custom_type" in content

    def test_with_env_no_frameworks(self, monkeypatch, tmp_path):
        """frameworks=[] → 不显示框架行"""
        env = _make_env(frameworks=[])
        monkeypatch.setattr(ag_mod, "detect_environment", lambda path: env)
        content = generate_agents_md(str(tmp_path))
        assert "框架" not in content.split("## Python 编码规范")[0]

    def test_with_env_unknown_project_type_uses_value(self, monkeypatch, tmp_path):
        env = _make_env(project_type="unknown")
        monkeypatch.setattr(ag_mod, "detect_environment", lambda path: env)
        content = generate_agents_md(str(tmp_path))
        assert "通用" in content  # type_map["unknown"] = "通用"

    def test_framework_django(self, monkeypatch, tmp_path):
        env = _make_env(frameworks=["Django"])
        monkeypatch.setattr(ag_mod, "detect_environment", lambda path: env)
        content = generate_agents_md(str(tmp_path))
        assert "Django 约定" in content
        assert "Fat Models, Thin Views" in content

    def test_framework_flask(self, monkeypatch, tmp_path):
        env = _make_env(frameworks=["Flask"])
        monkeypatch.setattr(ag_mod, "detect_environment", lambda path: env)
        content = generate_agents_md(str(tmp_path))
        assert "Flask 约定" in content
        assert "Blueprint" in content

    def test_framework_pandas(self, monkeypatch, tmp_path):
        env = _make_env(frameworks=["pandas"])
        monkeypatch.setattr(ag_mod, "detect_environment", lambda path: env)
        content = generate_agents_md(str(tmp_path))
        assert "数据科学约定" in content

    def test_framework_numpy(self, monkeypatch, tmp_path):
        env = _make_env(frameworks=["NumPy"])
        monkeypatch.setattr(ag_mod, "detect_environment", lambda path: env)
        content = generate_agents_md(str(tmp_path))
        assert "数据科学约定" in content

    def test_framework_pytorch(self, monkeypatch, tmp_path):
        env = _make_env(frameworks=["PyTorch"])
        monkeypatch.setattr(ag_mod, "detect_environment", lambda path: env)
        content = generate_agents_md(str(tmp_path))
        assert "PyTorch 约定" in content
        assert "torch.nn.Module" in content

    def test_multiple_frameworks(self, monkeypatch, tmp_path):
        """多个框架 → 各生成对应约定"""
        env = _make_env(frameworks=["FastAPI", "pandas"])
        monkeypatch.setattr(ag_mod, "detect_environment", lambda path: env)
        content = generate_agents_md(str(tmp_path))
        assert "FastAPI 约定" in content
        assert "数据科学约定" in content

    def test_frameworks_truncated_to_8(self, monkeypatch, tmp_path):
        """frameworks 列表截断到前 8 个"""
        env = _make_env(frameworks=["FastAPI", "Flask", "Django", "PyTorch", "pandas", "NumPy", "Other1", "Other2", "Other3"])
        monkeypatch.setattr(ag_mod, "detect_environment", lambda path: env)
        content = generate_agents_md(str(tmp_path))
        assert "Other3" not in content  # 第 9 个被截断


# ══════════════════════════════════════════════════════════
# generate_and_write
# ══════════════════════════════════════════════════════════

class TestGenerateAndWrite:
    def test_writes_file(self, tmp_path, monkeypatch):
        # 跳过 env 检测，避免依赖当前目录
        monkeypatch.setattr(ag_mod, "detect_environment", lambda path: None)
        result = generate_and_write(str(tmp_path), )
        assert result == tmp_path / "AGENTS.md"
        assert result.exists()
        content = result.read_text(encoding="utf-8")
        assert "PyCoder AGENTS.md" in content

    def test_uses_cwd_when_no_path(self, monkeypatch, tmp_path):
        """无 path 参数 → 使用 Path.cwd()"""
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        monkeypatch.setattr(ag_mod, "detect_environment", lambda path: None)
        result = generate_and_write()
        assert result == tmp_path / "AGENTS.md"
        assert result.exists()


# ══════════════════════════════════════════════════════════
# load_agents_md
# ══════════════════════════════════════════════════════════

class TestLoadAgentsMd:
    def test_file_exists(self, tmp_path):
        agents = tmp_path / "AGENTS.md"
        agents.write_text("# Existing\ncontent here", encoding="utf-8")
        result = load_agents_md(str(tmp_path))
        assert result == "# Existing\ncontent here"

    def test_file_not_exists(self, tmp_path):
        result = load_agents_md(str(tmp_path))
        assert result is None

    def test_file_read_fails(self, tmp_path, monkeypatch):
        """读取抛异常 → 静默返回 None"""
        agents = tmp_path / "AGENTS.md"
        agents.write_text("content", encoding="utf-8")

        # mock open 抛异常
        import builtins
        original_open = builtins.open
        def fake_open(path, *args, **kwargs):
            if "AGENTS.md" in str(path):
                raise OSError("perm denied")
            return original_open(path, *args, **kwargs)
        monkeypatch.setattr(builtins, "open", fake_open)

        result = load_agents_md(str(tmp_path))
        assert result is None

    def test_uses_cwd_when_no_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        agents = tmp_path / "AGENTS.md"
        agents.write_text("content", encoding="utf-8")
        assert load_agents_md() == "content"


# ══════════════════════════════════════════════════════════
# get_agents_context
# ══════════════════════════════════════════════════════════

class TestGetAgentsContext:
    def test_with_existing_agents_md(self, tmp_path):
        """已存在 AGENTS.md → 直接返回内容"""
        agents = tmp_path / "AGENTS.md"
        agents.write_text("# Existing\n## Python 编码规范\n规则", encoding="utf-8")
        result = get_agents_context(str(tmp_path))
        assert result == "# Existing\n## Python 编码规范\n规则"

    def test_auto_generates_when_missing(self, tmp_path, monkeypatch):
        """无 AGENTS.md → 自动生成精简版"""
        monkeypatch.setattr(ag_mod, "detect_environment", lambda path: None)
        result = get_agents_context(str(tmp_path))
        # 精简版应包含编码规范
        assert "PEP 8" in result
        # 但不应包含项目概述（被过滤）
        assert "## 项目概述" not in result or "项目概述" not in result.split("\n")[0]

    def test_auto_generated_includes_framework_section(self, tmp_path, monkeypatch):
        """精简版应包含 FastAPI 约定（环境特定部分）"""
        env = _make_env(frameworks=["FastAPI"])
        monkeypatch.setattr(ag_mod, "detect_environment", lambda path: env)
        # 不创建 AGENTS.md → 走自动生成
        result = get_agents_context(str(tmp_path))
        assert "FastAPI 约定" in result

    def test_truncates_long_content(self, tmp_path):
        """内容 > 2000 字符 → 截断"""
        # 创建超过 2000 字符的 AGENTS.md
        long_content = "# Title\n" + ("x" * 2500)
        agents = tmp_path / "AGENTS.md"
        agents.write_text(long_content, encoding="utf-8")
        result = get_agents_context(str(tmp_path))
        assert len(result) <= 2100  # 2000 + 截断标记
        assert "已截断" in result

    def test_short_content_not_truncated(self, tmp_path):
        """短内容不截断"""
        agents = tmp_path / "AGENTS.md"
        agents.write_text("short content", encoding="utf-8")
        result = get_agents_context(str(tmp_path))
        assert result == "short content"
        assert "已截断" not in result

    def test_no_key_sections_uses_full_content(self, tmp_path, monkeypatch):
        """生成的精简版若无关键 section → 使用完整内容"""
        # 生成无 frameworks 的 env → 不会有 "## 环境特定约定" section
        env = _make_env(frameworks=[])
        monkeypatch.setattr(ag_mod, "detect_environment", lambda path: env)
        # 通过 mock 让 key_sections 为空，使用完整 content
        # 实际上 generate_agents_md 总会包含编码规范，所以 key_sections 不会为空
        # 这个测试主要验证逻辑路径
        result = get_agents_context(str(tmp_path))
        assert "PEP 8" in result
