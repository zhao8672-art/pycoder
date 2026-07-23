from __future__ import annotations

import json
import os
import sys
import time
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════
# 7. plugin_executor.py 测试
# ═══════════════════════════════════════════════════════════════


class TestPluginExecutor:
    """PluginExecutor 测试"""

    @pytest.fixture
    def executor(self):
        """创建 PluginExecutor 实例"""
        from pycoder.server.services.plugin_executor import PluginExecutor

        return PluginExecutor()

    def test_init(self, executor):
        """初始化应设置默认属性"""
        assert executor._plugin_callback is None
        assert executor._results == {}

    def test_set_plugin_callback(self, executor):
        """设置回调应正确存储"""
        async def my_callback(event: dict) -> None:
            pass

        executor.set_plugin_callback(my_callback)
        assert executor._plugin_callback is my_callback

    async def test_emit_plugin_event_no_callback(self, executor):
        """无回调时发射事件应不报错"""
        await executor._emit_plugin_event("test", "测试插件", "start")

    async def test_emit_plugin_event_with_callback(self, executor):
        """有回调时发射事件应调用回调"""
        events = []

        async def callback(event: dict) -> None:
            events.append(event)

        executor.set_plugin_callback(callback)
        await executor._emit_plugin_event("test-id", "测试插件", "start", duration_ms=100)

        assert len(events) == 1
        assert events[0]["type"] == "plugin_event"
        assert events[0]["plugin_id"] == "test-id"
        assert events[0]["plugin_name"] == "测试插件"
        assert events[0]["action"] == "start"
        assert events[0]["duration_ms"] == 100
        assert events[0]["hidden"] is True

    async def test_emit_plugin_event_with_error(self, executor):
        """带错误的事件应包含错误信息"""
        events = []

        async def callback(event: dict) -> None:
            events.append(event)

        executor.set_plugin_callback(callback)
        await executor._emit_plugin_event("test-id", "测试", "error", error="something went wrong")

        assert events[0]["error"] == "something went wrong"
        assert events[0]["action"] == "error"

    async def test_emit_plugin_event_callback_failure(self, executor):
        """回调失败应不抛出异常"""
        async def failing_callback(event: dict) -> None:
            raise RuntimeError("回调失败")

        executor.set_plugin_callback(failing_callback)
        # 不应抛出异常
        await executor._emit_plugin_event("test", "测试", "start")

    async def test_execute_matching_plugins_no_registry(self, executor):
        """无插件注册表时应返回空结果"""
        with patch("pycoder.plugins.base.PluginRegistry", side_effect=ImportError):
            results = await executor.execute_matching_plugins("test message", {})
            assert results == {}

    async def test_execute_all_no_plugins(self, executor):
        """execute_all 无匹配时应正常返回"""
        with patch.object(executor, "execute_matching_plugins", return_value={}):
            with patch.object(executor, "execute_matching_skills", return_value={}):
                results = await executor.execute_all("test message", {})
                assert isinstance(results, dict)

    async def test_execute_all_with_exception(self, executor):
        """execute_all 异常时应返回错误结果"""
        with patch.object(
            executor,
            "execute_matching_plugins",
            side_effect=RuntimeError("插件执行失败"),
        ):
            with patch.object(
                executor,
                "execute_matching_skills",
                side_effect=RuntimeError("技能执行失败"),
            ):
                results = await executor.execute_all("test message", {})
                assert "__plugin_error__" in results
                assert "__skill_error__" in results


# ═══════════════════════════════════════════════════════════════
# 8. auto_plugin_installer.py 测试
# ═══════════════════════════════════════════════════════════════


class TestInstallResult:
    """InstallResult 数据类测试"""

    def test_install_result_defaults(self):
        """InstallResult 应有合理的默认值"""
        from pycoder.server.services.auto_plugin_installer import InstallResult

        result = InstallResult()
        assert result.success is False
        assert result.candidate_id == ""
        assert result.error == ""


class TestAutoPluginInstallerValidateUrl:
    """URL 验证测试"""

    def test_valid_url(self):
        """有效的 URL 应通过验证"""
        from pycoder.server.services.auto_plugin_installer import _validate_url

        assert _validate_url("https://example.com") == "https://example.com"

    def test_invalid_url(self):
        """无效的 URL 协议应抛出 ValueError"""
        from pycoder.server.services.auto_plugin_installer import _validate_url

        with pytest.raises(ValueError, match="不允许的 URL 协议"):
            _validate_url("ftp://example.com")


class TestAutoPluginInstaller:
    """AutoPluginInstaller 测试"""

    @pytest.fixture
    def installer(self, tmp_path: Path):
        """创建 AutoPluginInstaller 实例"""
        from pycoder.server.services.auto_plugin_installer import AutoPluginInstaller, _SKILLS_INSTALL_DIR, _INSTALL_LOG

        # 使用临时目录覆盖安装路径
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir(parents=True, exist_ok=True)
        log_file = tmp_path / "install_log.jsonl"
        # 创建 .pycoder 目录（_register_skill 需要）
        pycoder_dir = tmp_path / ".pycoder"
        pycoder_dir.mkdir(parents=True, exist_ok=True)

        with patch(
            "pycoder.server.services.auto_plugin_installer._SKILLS_INSTALL_DIR",
            skill_dir,
        ), patch(
            "pycoder.server.services.auto_plugin_installer._INSTALL_LOG",
            log_file,
        ), patch(
            "pycoder.server.services.auto_plugin_installer.Path.home",
            return_value=tmp_path,
        ):
            inst = AutoPluginInstaller()
            yield inst

    def test_init_creates_directory(self, tmp_path: Path):
        """初始化应创建安装目录"""
        from pycoder.server.services.auto_plugin_installer import AutoPluginInstaller

        with patch(
            "pycoder.server.services.auto_plugin_installer._SKILLS_INSTALL_DIR",
            tmp_path / "skills",
        ), patch(
            "pycoder.server.services.auto_plugin_installer._INSTALL_LOG",
            tmp_path / "log.jsonl",
        ), patch(
            "pycoder.server.services.auto_plugin_installer.Path.home",
            return_value=tmp_path,
        ):
            AutoPluginInstaller()
            assert (tmp_path / "skills").exists()

    def test_is_installed_false(self, installer, tmp_path: Path):
        """未安装时应返回 False"""
        assert installer.is_installed("nonexistent-skill") is False

    async def test_install_with_description_fallback(self, installer, tmp_path: Path):
        """仅提供描述时应从描述生成内容"""
        # 模拟 _fetch_content 返回描述生成的内容
        mock_fetch = AsyncMock(return_value=("# 自动生成的 Skill\n\n描述内容", "0.1"))
        with patch.object(installer, "_fetch_content", mock_fetch):
            result = await installer.install(
                candidate_id="test-skill",
                skill_data={"name": "Test Skill", "description": "A test skill description"},
                source="market",
            )
        assert result.success is True
        assert result.candidate_id == "test-skill"
        assert result.destination.endswith("test-skill.md")

    async def test_install_without_content_fails(self, installer):
        """无法获取内容时安装失败"""
        with patch.object(installer, "_fetch_content", return_value=("", "")):
            result = await installer.install("test-skill")
            assert result.success is False
            assert "无法获取" in result.error

    async def test_install_exception_handling(self, installer):
        """安装异常应返回失败结果"""
        with patch.object(installer, "_create_snapshot", side_effect=OSError("磁盘错误")):
            result = await installer.install("test-skill", {"name": "Test"})
            assert result.success is False
            assert "磁盘错误" in result.error

    def test_get_installed_empty(self, installer):
        """空安装目录应返回空列表"""
        installed = installer.get_installed()
        assert installed == []

    def test_get_install_log_empty(self, installer):
        """空日志应返回空列表"""
        log = installer.get_install_log()
        assert log == []

    def test_generate_from_description(self, installer):
        """从描述生成内容应包含必要信息"""
        content = installer._generate_from_description("my-skill", "这是一个测试技能")
        assert "my-skill" in content
        assert "这是一个测试技能" in content
        assert "自动安装" in content

    def test_build_github_url(self, installer):
        """构建 GitHub URL 应正确"""
        url = installer._build_github_url("code-review")
        assert "code-review" in url
        assert "SKILL.md" in url
        assert url.startswith("https://")

    async def test_download_url_invalid(self, installer):
        """无效 URL 下载应返回空字符串"""
        content = await installer._download_url("file:///etc/passwd")
        assert content == ""

    def test_create_snapshot_no_file(self, installer, tmp_path: Path):
        """无现有文件时应返回空引用"""
        ref = installer._create_snapshot("nonexistent")
        assert ref == ""

    def test_create_snapshot_existing_file(self, installer, tmp_path: Path):
        """有现有文件时应创建快照"""
        # 先创建一个文件
        skill_file = tmp_path / "skills" / "test-skill.md"
        skill_file.parent.mkdir(parents=True, exist_ok=True)
        skill_file.write_text("original content", encoding="utf-8")

        ref = installer._create_snapshot("test-skill")
        assert ref != ""
        assert "test-skill" in ref

        # 验证快照文件存在
        snap_dir = tmp_path / "skills" / ".snapshots"
        assert snap_dir.exists()
        snapshots = list(snap_dir.glob(f"{ref}.md"))
        assert len(snapshots) == 1

    def test_register_skill(self, tmp_path: Path):
        """注册技能应写入 installed_skills.json"""
        from pycoder.server.services.auto_plugin_installer import AutoPluginInstaller

        # 先创建 .pycoder 目录
        pycoder_dir = tmp_path / ".pycoder"
        pycoder_dir.mkdir(parents=True, exist_ok=True)
        reg_path = pycoder_dir / "installed_skills.json"
        with patch(
            "pycoder.server.services.auto_plugin_installer.Path.home",
            return_value=tmp_path,
        ):
            AutoPluginInstaller._register_skill("test-skill", "Test Skill")

        assert reg_path.exists()
        data = json.loads(reg_path.read_text(encoding="utf-8"))
        assert "test-skill" in data
        assert data["test-skill"]["name"] == "Test Skill"
        assert data["test-skill"]["enabled"] is True


# ═══════════════════════════════════════════════════════════════
# 端到端集成测试
# ═══════════════════════════════════════════════════════════════


class TestEndToEndMemoryBankFlow:
    """MemoryBank 端到端流程测试"""

    def test_full_memory_workflow(self, tmp_path: Path):
        """完整的记忆工作流：创建→更新→查询→清除"""
        from pycoder.server.memory_bank import MemoryBank, reset_memory_bank

        reset_memory_bank()
        mb = MemoryBank(workspace=tmp_path)

        # 初始状态
        assert mb.has_memory() is False
        assert mb.list_memories() == []

        # 更新项目概述
        mb.update_project_brief("端到端测试项目")
        assert mb.has_memory() is True

        # 记录架构决策
        mb.record_architecture_decision("使用 pytest", "测试框架", "社区支持好")
        mb.record_architecture_decision("使用 FastAPI", "Web 框架", "高性能")

        # 更新技术栈
        mb.update_tech_context("Python 3.14", "fastapi, pytest, uvicorn")

        # 设置活跃上下文
        mb.set_active_context("正在开发测试模块", ["tests/test_core.py"])

        # 更新进度
        mb.update_progress("START", "开始编写测试")
        mb.mark_completed("编写 MemoryBank 测试")

        # 验证查询
        memories = mb.list_memories()
        assert len(memories) >= 3  # project_brief, architecture, tech_context, active_context, progress

        # 加载上下文
        context = mb.load_context_for_prompt(max_tokens=5000)
        assert "端到端测试项目" in context
        assert "pytest" in context
        assert "FastAPI" in context

        # 清除活跃上下文
        mb.clear_active_context()
        assert mb._read("active_context.md") == ""