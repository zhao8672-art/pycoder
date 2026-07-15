"""
测试 pycoder 核心模块 — skills/v2/__main__/__init__

覆盖范围:
- pycoder/__init__.py: 版本号、编码设置、subprocess 猴子补丁
- pycoder/__main__.py: CLI 入口、_infer_name、_run_cli_mode、main
- pycoder/skills/__init__.py: SkillDefinition 补充、register_capabilities、处理器函数
- pycoder/skills/builtin/__init__.py: 内置技能补充测试
- pycoder/v2/__init__.py: V2EngineConfig、V2Engine 各方法

运行: pytest tests/test_skills_v2_modules.py -v
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════


def _make_skill_def(
    skill_id: str = "test-skill",
    name: str = "测试技能",
    version: str = "1.0.0",
    description: str = "测试技能描述",
    author: str = "PyCoder",
    category: str = "general",
    tags: list[str] | None = None,
    dependencies: list[str] | None = None,
    is_builtin: bool = False,
    markdown_content: str = "",
) -> "SkillDefinition":
    """创建测试用 SkillDefinition"""
    from pycoder.skills import SkillDefinition

    return SkillDefinition(
        id=skill_id,
        name=name,
        version=version,
        description=description,
        author=author,
        category=category,
        tags=tags or [],
        dependencies=dependencies or [],
        is_builtin=is_builtin,
        markdown_content=markdown_content or f"# {name}\n\n测试技能内容。",
    )


# ══════════════════════════════════════════════════════════════
# 第一部分: pycoder/__init__.py 测试
# ══════════════════════════════════════════════════════════════


class TestPycoderInit:
    """pycoder/__init__.py 包初始化测试"""

    def test_version_string(self) -> None:
        """测试 __version__ 存在且为有效字符串"""
        import pycoder

        assert pycoder.__version__ == "0.5.0"
        assert isinstance(pycoder.__version__, str)
        assert len(pycoder.__version__) > 0

    def test_pythonutf8_env_set(self) -> None:
        """测试 PYTHONUTF8 环境变量已设置"""
        assert os.environ.get("PYTHONUTF8") == "1"

    def test_pythonioencoding_env_set(self) -> None:
        """测试 PYTHONIOENCODING 环境变量已设置"""
        assert os.environ.get("PYTHONIOENCODING") == "utf-8"

    def test_subprocess_popen_patched(self) -> None:
        """测试 subprocess.Popen.__init__ 已被猴子补丁替换"""
        import subprocess as _subprocess

        # 猴子补丁后的 __init__ 应该不是原始的内置函数
        assert _subprocess.Popen.__init__.__name__ == "_patched_popen_init"

    def test_subprocess_patch_text_defaults_to_replace(self) -> None:
        """测试猴子补丁: text=True 且未指定 errors 时默认使用 'replace'"""
        import pycoder  # 确保模块已导入
        import subprocess as _subprocess

        patched = _subprocess.Popen.__init__
        orig = pycoder._orig_popen_init

        captured_kwargs = {}

        def mock_orig_init(self, args, **kwargs):
            captured_kwargs.update(kwargs)

        pycoder._orig_popen_init = mock_orig_init
        try:
            patched(MagicMock(), ["echo", "hello"], text=True)
            assert captured_kwargs.get("errors") == "replace"
        finally:
            pycoder._orig_popen_init = orig

    def test_subprocess_patch_with_explicit_encoding(self) -> None:
        """测试猴子补丁: 显式指定 encoding 时不覆盖 errors"""
        import pycoder
        import subprocess as _subprocess

        patched = _subprocess.Popen.__init__
        orig = pycoder._orig_popen_init

        captured_kwargs = {}

        def mock_orig_init(self, args, **kwargs):
            captured_kwargs.update(kwargs)

        pycoder._orig_popen_init = mock_orig_init
        try:
            patched(MagicMock(), ["echo", "hello"], text=True, encoding="gbk")
            assert "errors" not in captured_kwargs
        finally:
            pycoder._orig_popen_init = orig

    def test_subprocess_patch_with_explicit_errors(self) -> None:
        """测试猴子补丁: 显式指定 errors 时不覆盖"""
        import pycoder
        import subprocess as _subprocess

        patched = _subprocess.Popen.__init__
        orig = pycoder._orig_popen_init

        captured_kwargs = {}

        def mock_orig_init(self, args, **kwargs):
            captured_kwargs.update(kwargs)

        pycoder._orig_popen_init = mock_orig_init
        try:
            patched(MagicMock(), ["echo", "hello"], text=True, errors="strict")
            assert captured_kwargs.get("errors") == "strict"
        finally:
            pycoder._orig_popen_init = orig

    def test_subprocess_patch_no_text_mode(self) -> None:
        """测试猴子补丁: 非 text 模式不添加 errors"""
        import pycoder
        import subprocess as _subprocess

        patched = _subprocess.Popen.__init__
        orig = pycoder._orig_popen_init

        captured_kwargs = {}

        def mock_orig_init(self, args, **kwargs):
            captured_kwargs.update(kwargs)

        pycoder._orig_popen_init = mock_orig_init
        try:
            patched(MagicMock(), ["echo", "hello"])
            assert "errors" not in captured_kwargs
        finally:
            pycoder._orig_popen_init = orig

    def test_stdout_reconfigure_on_windows(self) -> None:
        """测试 Windows 平台 stdout 重配置为 UTF-8"""
        # 导入后 stdout encoding 应为 utf-8
        assert sys.stdout.encoding.lower() in ("utf-8", "utf8")

    def test_stderr_reconfigure_on_windows(self) -> None:
        """测试 Windows 平台 stderr 重配置为 UTF-8"""
        assert sys.stderr.encoding.lower() in ("utf-8", "utf8")


# ══════════════════════════════════════════════════════════════
# 第二部分: pycoder/__main__.py 测试
# ══════════════════════════════════════════════════════════════


class TestInferName:
    """_infer_name 函数测试"""

    def test_infer_name_user(self) -> None:
        """测试从包含"用户"的描述推断名称"""
        from pycoder.__main__ import _infer_name

        assert _infer_name("用户管理系统") == "user-api"

    def test_infer_name_book(self) -> None:
        """测试从包含"图书"的描述推断名称"""
        from pycoder.__main__ import _infer_name

        assert _infer_name("图书管理系统") == "library-api"

    def test_infer_name_blog(self) -> None:
        """测试从包含"博客"的描述推断名称"""
        from pycoder.__main__ import _infer_name

        assert _infer_name("博客系统") == "blog-api"

    def test_infer_name_order(self) -> None:
        """测试从包含"订单"的描述推断名称"""
        from pycoder.__main__ import _infer_name

        assert _infer_name("订单处理系统") == "order-api"

    def test_infer_name_product(self) -> None:
        """测试从包含"商品"的描述推断名称"""
        from pycoder.__main__ import _infer_name

        assert _infer_name("商品管理系统") == "product-api"

    def test_infer_name_stock(self) -> None:
        """测试从包含"股票"的描述推断名称"""
        from pycoder.__main__ import _infer_name

        assert _infer_name("股票监控系统") == "stock-monitor"

    def test_infer_name_no_match(self) -> None:
        """测试没有匹配关键词时返回默认名称"""
        from pycoder.__main__ import _infer_name

        assert _infer_name("一个随机的项目描述") == "my-project"

    def test_infer_name_empty(self) -> None:
        """测试空字符串返回默认名称"""
        from pycoder.__main__ import _infer_name

        assert _infer_name("") == "my-project"

    def test_infer_name_first_match_priority(self) -> None:
        """测试关键词优先级 — 用户 > 图书"""
        from pycoder.__main__ import _infer_name

        # "用户" 在关键词字典中排在 "图书" 前面
        assert _infer_name("用户图书管理系统") == "user-api"


class TestMainVersion:
    """main 函数 — --version 参数测试"""

    def test_version_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        """测试 --version 输出版本号并退出"""
        from pycoder.__main__ import main

        with patch.object(sys, "argv", ["pycoder", "--version"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

        captured = capsys.readouterr()
        assert "PyCoder v" in captured.out


class TestMainStatus:
    """main 函数 — --status 参数测试"""

    def test_status_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试 --status 输出模型状态"""
        mock_mgr = MagicMock()
        mock_mgr.format_status.return_value = "模型状态: OK"
        monkeypatch.setattr(
            "pycoder.providers.auth.get_model_manager",
            lambda: mock_mgr,
        )

        from pycoder.__main__ import main

        with patch.object(sys, "argv", ["pycoder", "--status"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0


class TestMainEnv:
    """main 函数 — --env 参数测试"""

    def test_env_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试 --env 输出环境信息"""
        # Mock detect_environment
        mock_info = MagicMock()
        monkeypatch.setattr(
            "pycoder.python.env_detector.detect_environment",
            lambda: mock_info,
        )
        monkeypatch.setattr(
            "pycoder.python.env_detector.print_env_info",
            lambda info: "环境信息输出",
        )

        mock_mgr = MagicMock()
        mock_mgr.format_status.return_value = "模型状态"
        monkeypatch.setattr(
            "pycoder.providers.auth.get_model_manager",
            lambda: mock_mgr,
        )

        from pycoder.__main__ import main

        with patch.object(sys, "argv", ["pycoder", "--env"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0


class TestMainCost:
    """main 函数 — --cost 参数测试"""

    def test_cost_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试 --cost 输出费用报告"""
        mock_tracker = MagicMock()
        mock_tracker.format_report.return_value = "费用报告"
        monkeypatch.setattr(
            "pycoder.providers.cost.get_cost_tracker",
            lambda: mock_tracker,
        )

        from pycoder.__main__ import main

        with patch.object(sys, "argv", ["pycoder", "--cost"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0


class TestMainListTemplates:
    """main 函数 — --list-templates 参数测试"""

    def test_list_templates_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试 --list-templates 列出模板"""
        from dataclasses import dataclass

        @dataclass
        class MockTemplate:
            name: str = "fastapi"
            display_name: str = "FastAPI 项目"
            category: str = "web"
            description: str = "FastAPI 项目模板"
            run_command: str = "uvicorn main:app"

        monkeypatch.setattr(
            "pycoder.python.scaffold.list_templates",
            lambda: [MockTemplate()],
        )

        from pycoder.__main__ import main

        with patch.object(sys, "argv", ["pycoder", "--list-templates"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0


class TestMainGenerate:
    """main 函数 — --generate 参数测试"""

    def test_generate_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试 --generate 调用 _run_generate_mode"""
        mock_generate = MagicMock()
        monkeypatch.setattr(
            "pycoder.__main__._run_generate_mode",
            mock_generate,
        )

        from pycoder.__main__ import main

        with patch.object(sys, "argv", ["pycoder", "--generate", "FastAPI app"]):
            main()

        mock_generate.assert_called_once_with("FastAPI app", "")

    def test_generate_with_project_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试 --generate 带 --project-dir 参数"""
        mock_generate = MagicMock()
        monkeypatch.setattr(
            "pycoder.__main__._run_generate_mode",
            mock_generate,
        )

        from pycoder.__main__ import main

        with patch.object(
            sys, "argv",
            ["pycoder", "--generate", "FastAPI app", "--project-dir", "/tmp/myapp"],
        ):
            main()

        mock_generate.assert_called_once_with("FastAPI app", "/tmp/myapp")


class TestMainSetup:
    """main 函数 — --setup 参数测试"""

    def test_setup_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试 --setup 输出配置向导"""
        monkeypatch.setattr(
            "pycoder.providers.setup_wizard.get_setup_guide",
            lambda: "配置向导内容",
        )

        from pycoder.__main__ import main

        with patch.object(sys, "argv", ["pycoder", "--setup"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0


class TestMainAutonomous:
    """main 函数 — --autonomous 参数测试"""

    def test_autonomous_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试 --autonomous --task 调用全自主模式"""
        mock_run = MagicMock()
        monkeypatch.setattr(
            "pycoder.__main__._run_autonomous_mode",
            mock_run,
        )

        from pycoder.__main__ import main

        with patch.object(
            sys, "argv",
            ["pycoder", "--autonomous", "--task", "做一个API"],
        ):
            main()

        mock_run.assert_called_once()

    def test_autonomous_without_task(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试 --autonomous 无 --task 时进入 server 模式"""
        # 模拟 uvicorn.run 避免实际启动服务器
        monkeypatch.setattr("uvicorn.run", lambda *a, **kw: None)

        from pycoder.__main__ import main

        with patch.object(sys, "argv", ["pycoder", "--autonomous"]):
            main()  # 应进入 server 模式，不报错


class TestMainEvolve:
    """main 函数 — --evolve 参数测试"""

    def test_evolve_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试 --evolve 调用进化模式"""
        mock_evolve = MagicMock()
        monkeypatch.setattr(
            "pycoder.__main__._run_evolution_mode",
            mock_evolve,
        )

        from pycoder.__main__ import main

        with patch.object(sys, "argv", ["pycoder", "--evolve"]):
            main()

        mock_evolve.assert_called_once()

    def test_evolve_with_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试 --evolve --evolve-path 指定路径"""
        mock_evolve = MagicMock()
        monkeypatch.setattr(
            "pycoder.__main__._run_evolution_mode",
            mock_evolve,
        )

        from pycoder.__main__ import main

        with patch.object(
            sys, "argv",
            ["pycoder", "--evolve", "--evolve-path", "src/myapp"],
        ):
            main()

        mock_evolve.assert_called_once_with("src/myapp")


class TestMainScan:
    """main 函数 — --scan 参数测试"""

    def test_scan_flag_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试 --scan 默认扫描 pycoder 目录"""
        mock_scan = MagicMock()
        monkeypatch.setattr(
            "pycoder.__main__._run_scan_mode",
            mock_scan,
        )

        from pycoder.__main__ import main

        with patch.object(sys, "argv", ["pycoder", "--scan"]):
            main()

        mock_scan.assert_called_once_with("pycoder")

    def test_scan_flag_with_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试 --scan 指定路径"""
        mock_scan = MagicMock()
        monkeypatch.setattr(
            "pycoder.__main__._run_scan_mode",
            mock_scan,
        )

        from pycoder.__main__ import main

        with patch.object(sys, "argv", ["pycoder", "--scan", "src"]):
            main()

        mock_scan.assert_called_once_with("src")


class TestMainServer:
    """main 函数 — --server 参数测试"""

    def test_server_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试 --server 启动服务器"""
        mock_run_server = MagicMock()
        monkeypatch.setattr("uvicorn.run", mock_run_server)

        from pycoder.__main__ import main

        with patch.object(sys, "argv", ["pycoder", "--server"]):
            main()

        mock_run_server.assert_called_once()

    def test_server_flag_with_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试 --server --server-port 指定端口"""
        mock_run_server = MagicMock()
        monkeypatch.setattr("uvicorn.run", mock_run_server)

        from pycoder.__main__ import main

        with patch.object(sys, "argv", ["pycoder", "--server", "--server-port", "9999"]):
            main()

        mock_run_server.assert_called_once()
        # 验证端口参数传递正确
        call_args = mock_run_server.call_args[1]
        assert call_args.get("port") == 9999


class TestMainCLIMode:
    """main 函数 — CLI 模式测试"""

    def test_cli_mode_with_extra_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试带未知参数时进入 CLI 模式（parse_known_args 的 unknown 非空）"""
        mock_cli = MagicMock()
        monkeypatch.setattr(
            "pycoder.__main__._run_cli_mode",
            mock_cli,
        )

        from pycoder.__main__ import main

        # 使用 --unknown-flag 使 parse_known_args 产生非空 unknown
        with patch.object(sys, "argv", ["pycoder", "--unknown-flag", "value"]):
            main()

        mock_cli.assert_called_once()

    def test_cli_mode_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试无参数时默认进入 server 模式"""
        mock_run_server = MagicMock()
        monkeypatch.setattr("uvicorn.run", mock_run_server)

        from pycoder.__main__ import main

        with patch.object(sys, "argv", ["pycoder"]):
            main()

        mock_run_server.assert_called_once()


class TestRunCLIMode:
    """_run_cli_mode 函数测试"""

    def test_run_cli_mode_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        """测试 _run_cli_mode 输出提示信息"""
        from pycoder.__main__ import _run_cli_mode

        _run_cli_mode([])
        captured = capsys.readouterr()
        assert "CLI 模式" in captured.out
        assert "PyCoder" in captured.out

    def test_run_cli_mode_with_args(self, capsys: pytest.CaptureFixture[str]) -> None:
        """测试 _run_cli_mode 带参数"""
        from pycoder.__main__ import _run_cli_mode

        _run_cli_mode(["some", "args"])
        captured = capsys.readouterr()
        assert "CLI 模式" in captured.out


class TestPYCODER_ACTIVE:
    """main 函数设置 PYCODER_ACTIVE 环境变量测试"""

    def test_pycoder_active_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试 main 执行后 PYCODER_ACTIVE 被设置为 1"""
        monkeypatch.setattr("uvicorn.run", lambda *a, **kw: None)

        from pycoder.__main__ import main

        with patch.object(sys, "argv", ["pycoder"]):
            main()

        assert os.environ.get("PYCODER_ACTIVE") == "1"


# ══════════════════════════════════════════════════════════════
# 第三部分: pycoder/skills/__init__.py 补充测试
# ══════════════════════════════════════════════════════════════


class TestSkillDefinitionExtended:
    """SkillDefinition 数据类补充测试"""

    def test_default_values(self) -> None:
        """测试默认值"""
        from pycoder.skills import SkillDefinition

        sd = SkillDefinition(id="test", name="测试")
        assert sd.version == "1.0.0"
        assert sd.description == ""
        assert sd.author == "PyCoder"
        assert sd.category == "general"
        assert sd.tags == []
        assert sd.dependencies == []
        assert sd.install_count == 0
        assert sd.rating == 0.0
        assert sd.created_at == ""
        assert sd.updated_at == ""
        assert sd.markdown_content == ""
        assert sd.is_builtin is False

    def test_to_dict_contains_all_keys(self) -> None:
        """测试 to_dict 包含所有必要键"""
        sd = _make_skill_def(
            skill_id="dict-test",
            name="字典测试",
            tags=["python", "test"],
            dependencies=["dep1"],
        )
        d = sd.to_dict()
        expected_keys = {
            "id", "name", "version", "description", "author",
            "category", "tags", "dependencies", "install_count",
            "rating", "created_at", "updated_at", "is_builtin",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_values(self) -> None:
        """测试 to_dict 值正确性"""
        sd = _make_skill_def(
            skill_id="val-test",
            name="值测试",
            version="3.0.0",
            description="desc",
            author="author1",
            category="cat1",
            tags=["t1", "t2"],
            dependencies=["d1"],
            is_builtin=True,
        )
        sd.install_count = 42
        sd.rating = 4.5
        sd.created_at = "2024-01-01T00:00:00"
        sd.updated_at = "2024-06-01T00:00:00"

        d = sd.to_dict()
        assert d["id"] == "val-test"
        assert d["name"] == "值测试"
        assert d["version"] == "3.0.0"
        assert d["description"] == "desc"
        assert d["author"] == "author1"
        assert d["category"] == "cat1"
        assert d["tags"] == ["t1", "t2"]
        assert d["dependencies"] == ["d1"]
        assert d["install_count"] == 42
        assert d["rating"] == 4.5
        assert d["created_at"] == "2024-01-01T00:00:00"
        assert d["updated_at"] == "2024-06-01T00:00:00"
        assert d["is_builtin"] is True

    def test_to_dict_excludes_markdown_content(self) -> None:
        """测试 to_dict 不包含 markdown_content（安全考虑）"""
        sd = _make_skill_def(
            skill_id="secret", name="机密", markdown_content="敏感内容"
        )
        d = sd.to_dict()
        assert "markdown_content" not in d


# ── 技能市场 fixtures ──


@pytest.fixture
def temp_skills_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """创建临时技能目录，隔离测试数据"""
    from pycoder.skills import SkillMarketplace

    skills_dir = tmp_path / "data" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    SkillMarketplace._instance = None

    import pycoder.skills as skills_module

    monkeypatch.setattr(skills_module, "DATA_DIR", skills_dir)
    monkeypatch.setattr(skills_module, "DB_PATH", skills_dir / "skills.db")

    yield skills_dir

    SkillMarketplace._instance = None
    if skills_dir.exists():
        shutil.rmtree(skills_dir, ignore_errors=True)


@pytest.fixture
def marketplace(temp_skills_dir: Path) -> "SkillMarketplace":
    """创建隔离的技能市场实例"""
    from pycoder.skills import SkillMarketplace

    mp = SkillMarketplace()
    return mp


class TestSkillMarketplaceExtended:
    """SkillMarketplace 补充测试"""

    def test_row_to_skill_def(self, marketplace: "SkillMarketplace") -> None:
        """测试 _row_to_skill_def 方法"""
        from pycoder.skills import SkillDefinition

        # 先保存一个技能到数据库
        sd = _make_skill_def(
            skill_id="row-test",
            name="行转换测试",
            tags=["tag1", "tag2"],
            dependencies=["dep1"],
            is_builtin=True,
            markdown_content="# Row Test",
        )
        sd.created_at = "2024-01-01T00:00:00"
        sd.updated_at = "2024-01-02T00:00:00"
        marketplace._save_skill_to_db(sd, mark_as_installed=True)

        # 从数据库读取并使用 _row_to_skill_def 转换
        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM skills WHERE id = ?", (sd.id,)
            ).fetchone()

        result = marketplace._row_to_skill_def(row)
        assert isinstance(result, SkillDefinition)
        assert result.id == "row-test"
        assert result.name == "行转换测试"
        assert result.tags == ["tag1", "tag2"]
        assert result.dependencies == ["dep1"]
        assert result.is_builtin is True
        assert result.markdown_content == "# Row Test"

    def test_row_to_skill_def_empty_tags(self, marketplace: "SkillMarketplace") -> None:
        """测试 _row_to_skill_def 空 tags 和 dependencies"""
        sd = _make_skill_def(
            skill_id="empty-tags",
            name="空标签",
            tags=[],
            dependencies=[],
            markdown_content="# Empty",
        )
        marketplace._save_skill_to_db(sd, mark_as_installed=False)

        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM skills WHERE id = ?", (sd.id,)
            ).fetchone()

        result = marketplace._row_to_skill_def(row)
        assert result.tags == []
        assert result.dependencies == []

    def test_row_to_dict(self, marketplace: "SkillMarketplace") -> None:
        """测试 _row_to_dict 方法"""
        sd = _make_skill_def(
            skill_id="dict-row-test",
            name="字典行测试",
            tags=["a", "b"],
            is_builtin=False,
            markdown_content="# Dict Row",
        )
        marketplace._save_skill_to_db(sd, mark_as_installed=True)

        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM skills WHERE id = ?", (sd.id,)
            ).fetchone()

        result = marketplace._row_to_dict(row)
        assert result["id"] == "dict-row-test"
        assert result["tags"] == ["a", "b"]
        assert result["is_builtin"] is False
        assert result["installed"] is True
        assert "rating_count" in result
        assert "markdown_content" not in result  # 不包含全文

    def test_row_to_dict_not_installed(self, marketplace: "SkillMarketplace") -> None:
        """测试 _row_to_dict 未安装的技能"""
        sd = _make_skill_def(
            skill_id="not-installed-dict",
            name="未安装",
            markdown_content="# Not Installed",
        )
        marketplace._save_skill_to_db(sd, mark_as_installed=False)

        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM skills WHERE id = ?", (sd.id,)
            ).fetchone()

        result = marketplace._row_to_dict(row)
        assert result["installed"] is False

    def test_load_skill_content_exists(self, marketplace: "SkillMarketplace") -> None:
        """测试 _load_skill_content 文件存在"""
        sd = _make_skill_def(
            skill_id="load-test",
            name="加载测试",
            markdown_content="# 加载内容\n\n测试加载。",
        )
        marketplace._save_skill_content(sd)

        content = marketplace._load_skill_content("load-test")
        assert "# 加载内容" in content
        assert "测试加载" in content

    def test_load_skill_content_not_exists(self, marketplace: "SkillMarketplace") -> None:
        """测试 _load_skill_content 文件不存在"""
        content = marketplace._load_skill_content("nonexistent-file")
        assert content == ""

    def test_save_skill_content_no_markdown(self, marketplace: "SkillMarketplace") -> None:
        """测试 _save_skill_content 无 markdown 内容时不写入"""
        from pycoder.skills import SkillDefinition

        sd = SkillDefinition(
            id="no-content",
            name="无内容",
            markdown_content="",  # 直接传空字符串，不使用 _make_skill_def
        )
        # 不应报错
        marketplace._save_skill_content(sd)
        skill_file = marketplace._skills_dir / "no-content" / "SKILL.md"
        assert not skill_file.exists()

    def test_preinstall_builtins_import_error(
        self, temp_skills_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """测试 _preinstall_builtins 导入失败时降级处理"""
        from pycoder.skills import SkillMarketplace

        # 重置单例，使用干净的 DB
        SkillMarketplace._instance = None

        original_import = __import__

        def mock_import(name, *args, **kwargs):
            if "pycoder.skills.builtin" in name:
                raise ImportError("模拟导入失败")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            mp = SkillMarketplace()
            # 不应崩溃，但内置技能数为 0
            stats = mp.get_stats()
            assert stats["builtin_skills"] == 0


class TestGetMarketplace:
    """get_marketplace 函数测试"""

    def test_get_marketplace_returns_same_instance(self) -> None:
        """测试 get_marketplace 返回同一实例"""
        from pycoder.skills import get_marketplace, SkillMarketplace

        SkillMarketplace._instance = None
        # 重置全局变量
        import pycoder.skills as skills_module

        skills_module._marketplace = None

        mp1 = get_marketplace()
        mp2 = get_marketplace()
        assert mp1 is mp2

    def test_get_marketplace_creates_instance(self) -> None:
        """测试 get_marketplace 创建新实例"""
        from pycoder.skills import get_marketplace, SkillMarketplace

        SkillMarketplace._instance = None
        import pycoder.skills as skills_module

        skills_module._marketplace = None

        mp = get_marketplace()
        assert mp is not None
        assert isinstance(mp, SkillMarketplace)


class TestSkillMarketplaceRateSkillEdges:
    """rate_skill 边界情况测试"""

    @pytest.mark.asyncio
    async def test_rate_skill_minimum(self, marketplace: "SkillMarketplace") -> None:
        """测试最低评分 1"""
        result = await marketplace.rate_skill("code-review", 1)
        assert result["success"] is True
        assert result["new_rating"] > 0

    @pytest.mark.asyncio
    async def test_rate_skill_maximum(self, marketplace: "SkillMarketplace") -> None:
        """测试最高评分 5"""
        result = await marketplace.rate_skill("code-review", 5)
        assert result["success"] is True
        assert result["new_rating"] > 0


class TestSkillMarketplaceUpdateSkillEdges:
    """update_skill 边界情况测试"""

    @pytest.mark.asyncio
    async def test_update_skill_tags_list(self, marketplace: "SkillMarketplace") -> None:
        """测试更新 tags 为列表"""
        sd = _make_skill_def(
            skill_id="tag-update",
            name="标签更新",
            markdown_content="# Tag Update",
        )
        await marketplace.register_skill(sd, sd.markdown_content)

        result = await marketplace.update_skill(
            "tag-update",
            {"tags": ["new-tag1", "new-tag2"]},
        )
        assert result["success"] is True
        detail = await marketplace.get_skill("tag-update")
        assert "new-tag1" in detail["skill"]["tags"]

    @pytest.mark.asyncio
    async def test_update_skill_dependencies_list(self, marketplace: "SkillMarketplace") -> None:
        """测试更新 dependencies 为列表"""
        sd = _make_skill_def(
            skill_id="dep-update",
            name="依赖更新",
            markdown_content="# Dep Update",
        )
        await marketplace.register_skill(sd, sd.markdown_content)

        result = await marketplace.update_skill(
            "dep-update",
            {"dependencies": ["new-dep1", "new-dep2"]},
        )
        assert result["success"] is True
        detail = await marketplace.get_skill("dep-update")
        assert "new-dep1" in detail["skill"]["dependencies"]

    @pytest.mark.asyncio
    async def test_update_skill_markdown_content(self, marketplace: "SkillMarketplace") -> None:
        """测试更新 markdown_content 同步到文件系统"""
        sd = _make_skill_def(
            skill_id="md-update",
            name="MD更新",
            markdown_content="# 原始",
        )
        await marketplace.register_skill(sd, sd.markdown_content)

        result = await marketplace.update_skill(
            "md-update",
            {"markdown_content": "# 已更新内容"},
        )
        assert result["success"] is True

        # 验证文件系统也更新了
        content = marketplace._load_skill_content("md-update")
        assert "# 已更新内容" in content


class TestSkillMarketplaceGetStats:
    """get_stats 补充测试"""

    def test_get_stats_returns_categories(self, marketplace: "SkillMarketplace") -> None:
        """测试 get_stats 返回分类统计"""
        stats = marketplace.get_stats()
        assert "categories" in stats
        assert isinstance(stats["categories"], dict)

    def test_get_stats_data_dir(self, marketplace: "SkillMarketplace") -> None:
        """测试 get_stats 返回 data_dir"""
        stats = marketplace.get_stats()
        assert "data_dir" in stats
        assert len(stats["data_dir"]) > 0


# ══════════════════════════════════════════════════════════════
# 第四部分: pycoder/skills/builtin/__init__.py 补充测试
# ══════════════════════════════════════════════════════════════


class TestBuiltinSkillsExtended:
    """内置技能补充测试"""

    def test_builtin_skills_count_exact(self) -> None:
        """测试内置技能精确数量"""
        from pycoder.skills.builtin import BUILTIN_SKILLS

        assert len(BUILTIN_SKILLS) == 12

    def test_builtin_skills_all_categories_present(self) -> None:
        """测试所有分类都有技能"""
        from pycoder.skills.builtin import SKILLS_BY_CATEGORY

        expected_categories = {
            "quality", "testing", "documentation", "refactoring",
            "security", "performance", "tools",
        }
        assert set(SKILLS_BY_CATEGORY.keys()) == expected_categories

    def test_each_builtin_skill_has_tags(self) -> None:
        """测试每个内置技能都有标签"""
        from pycoder.skills.builtin import BUILTIN_SKILLS

        for skill in BUILTIN_SKILLS:
            assert len(skill.tags) > 0, f"技能 {skill.id} 缺少标签"

    def test_each_builtin_skill_has_description(self) -> None:
        """测试每个内置技能都有描述"""
        from pycoder.skills.builtin import BUILTIN_SKILLS

        for skill in BUILTIN_SKILLS:
            assert len(skill.description) > 0, f"技能 {skill.id} 缺少描述"

    def test_get_builtin_skill_all_ids(self) -> None:
        """测试所有内置技能 ID 都能通过 get_builtin_skill 获取"""
        from pycoder.skills.builtin import BUILTIN_SKILLS, get_builtin_skill

        for skill in BUILTIN_SKILLS:
            result = get_builtin_skill(skill.id)
            assert result is not None, f"技能 {skill.id} 未找到"
            assert result.id == skill.id

    def test_get_builtin_skill_empty_id(self) -> None:
        """测试空 ID 查询返回 None"""
        from pycoder.skills.builtin import get_builtin_skill

        assert get_builtin_skill("") is None

    def test_get_builtin_skills_by_category_empty(self) -> None:
        """测试空分类查询返回空列表"""
        from pycoder.skills.builtin import get_builtin_skills_by_category

        assert get_builtin_skills_by_category("") == []

    def test_get_builtin_skills_by_category_case_sensitive(self) -> None:
        """测试分类查询大小写敏感"""
        from pycoder.skills.builtin import get_builtin_skills_by_category

        # "Quality" vs "quality" — 应区分大小写
        assert get_builtin_skills_by_category("Quality") == []

    def test_skills_by_category_structure(self) -> None:
        """测试 SKILLS_BY_CATEGORY 结构完整性"""
        from pycoder.skills.builtin import SKILLS_BY_CATEGORY

        for category, ids in SKILLS_BY_CATEGORY.items():
            assert isinstance(category, str)
            assert isinstance(ids, list)
            assert len(ids) > 0
            for sid in ids:
                assert isinstance(sid, str)


# ══════════════════════════════════════════════════════════════
# 第五部分: pycoder/v2/__init__.py 测试
# ══════════════════════════════════════════════════════════════


class TestV2EngineConfig:
    """V2EngineConfig 数据类测试"""

    def test_default_config(self) -> None:
        """测试默认配置值"""
        from pycoder.v2 import V2EngineConfig
        from pycoder.bus.protocol import TrustLevel

        config = V2EngineConfig()
        assert config.workspace_root == "."
        assert config.initial_trust == TrustLevel.WORKSPACE_WRITE
        assert config.enable_consciousness is True
        assert config.enable_self_evo is True
        assert config.audit_log_path == ""
        assert config.snapshot_dir == ""

    def test_custom_config(self) -> None:
        """测试自定义配置"""
        from pycoder.v2 import V2EngineConfig
        from pycoder.bus.protocol import TrustLevel

        config = V2EngineConfig(
            workspace_root="/tmp/test",
            initial_trust=TrustLevel.READ_ONLY,
            enable_consciousness=False,
            enable_self_evo=False,
            audit_log_path="/tmp/audit.log",
            snapshot_dir="/tmp/snapshots",
        )
        assert config.workspace_root == "/tmp/test"
        assert config.initial_trust == TrustLevel.READ_ONLY
        assert config.enable_consciousness is False
        assert config.enable_self_evo is False
        assert config.audit_log_path == "/tmp/audit.log"
        assert config.snapshot_dir == "/tmp/snapshots"


class TestV2EngineInit:
    """V2Engine 初始化测试"""

    def test_engine_creation_without_config(self) -> None:
        """测试无配置创建 V2Engine"""
        from pycoder.v2 import V2Engine

        engine = V2Engine()
        assert engine._initialized is False
        assert engine.registry is not None
        assert engine.permission is not None
        assert engine.consciousness is not None
        assert engine.planner is not None
        assert engine.orchestrator is not None
        assert engine.memory is not None

    def test_engine_creation_with_config(self) -> None:
        """测试带配置创建 V2Engine"""
        from pycoder.v2 import V2Engine, V2EngineConfig

        config = V2EngineConfig(workspace_root="/tmp")
        engine = V2Engine(config)
        assert engine.config.workspace_root == "/tmp"

    def test_engine_double_initialize(self) -> None:
        """测试重复初始化不重复注册能力"""
        from pycoder.v2 import V2Engine, V2EngineConfig

        engine = V2Engine(V2EngineConfig(workspace_root=os.getcwd()))
        asyncio.run(engine.initialize())
        count1 = engine.registry.count

        # 第二次初始化不应改变
        asyncio.run(engine.initialize())
        count2 = engine.registry.count

        assert count1 == count2

    def test_get_stats_before_initialize(self) -> None:
        """测试未初始化时获取统计信息"""
        from pycoder.v2 import V2Engine

        engine = V2Engine()
        stats = engine.get_stats()
        assert stats["initialized"] is False
        assert "bus" in stats
        assert "safety" in stats
        assert "monitor" in stats
        assert "consciousness" in stats

    def test_get_stats_after_initialize(self) -> None:
        """测试初始化后获取统计信息"""
        from pycoder.v2 import V2Engine, V2EngineConfig

        engine = V2Engine(V2EngineConfig(workspace_root=os.getcwd()))
        asyncio.run(engine.initialize())
        stats = engine.get_stats()
        assert stats["initialized"] is True
        assert "capabilities" in stats["bus"]

    def test_get_health_report(self) -> None:
        """测试获取健康报告"""
        from pycoder.v2 import V2Engine

        engine = V2Engine()
        report = engine.get_health_report()
        assert "bus_health" in report
        assert "audit_report" in report
        assert "pending_rollbacks" in report
        assert "active_modules" in report

    def test_emergency_lockdown(self) -> None:
        """测试紧急锁定"""
        from pycoder.v2 import V2Engine
        from pycoder.brain.consciousness import OperatingMode

        engine = V2Engine()
        engine.emergency_lockdown()
        assert engine.consciousness.mode == OperatingMode.IDLE

    def test_shutdown(self) -> None:
        """测试优雅关闭"""
        from pycoder.v2 import V2Engine

        engine = V2Engine()
        # shutdown 不应抛出异常
        asyncio.run(engine.shutdown())


class TestV2EngineCall:
    """V2Engine.call 方法测试"""

    def test_call_not_found(self) -> None:
        """测试调用不存在的 capability"""
        from pycoder.v2 import V2Engine, V2EngineConfig

        engine = V2Engine(V2EngineConfig(workspace_root=os.getcwd()))
        asyncio.run(engine.initialize())

        result = asyncio.run(engine.call("nonexistent.capability.id", {}))
        assert result.success is False
        assert result.error_code == "NOT_FOUND"

    def test_call_without_initialize(self) -> None:
        """测试未初始化时调用（自动初始化）"""
        from pycoder.v2 import V2Engine, V2EngineConfig

        engine = V2Engine(V2EngineConfig(workspace_root=os.getcwd()))
        result = asyncio.run(engine.call("system.env.detect", {}, force=True))
        assert result.success is True
        assert engine._initialized is True

    def test_stream_basic(self) -> None:
        """测试流式调用基本功能"""
        from pycoder.v2 import V2Engine, V2EngineConfig

        engine = V2Engine(V2EngineConfig(workspace_root=os.getcwd()))
        asyncio.run(engine.initialize())

        # 流式调用不存在的 capability 应返回空
        async def _collect():
            events = []
            async for event in engine.stream("nonexistent.id"):
                events.append(event)
            return events

        events = asyncio.run(_collect())
        # 流式调用不存在的 ID 不应崩溃
        assert isinstance(events, list)

    def test_execute_task_basic(self) -> None:
        """测试执行任务基本功能"""
        from pycoder.v2 import V2Engine, V2EngineConfig

        engine = V2Engine(V2EngineConfig(workspace_root=os.getcwd()))
        asyncio.run(engine.initialize())

        result = asyncio.run(engine.execute_task("创建一个简单的API"))
        assert "intent" in result
        assert result["intent"] == "创建一个简单的API"
        assert "total_tasks" in result
        assert "success_count" in result
        assert "strategy" in result
        assert "results" in result

    def test_create_snapshot_before_write(self, tmp_path: Path) -> None:
        """测试写操作前创建快照"""
        from pycoder.v2 import V2Engine
        from pycoder.bus.protocol import CapabilityDefinition, CapabilityCategory, TrustLevel

        engine = V2Engine()
        # 创建临时文件
        test_file = tmp_path / "test_snapshot.txt"
        test_file.write_text("original content")

        cap_def = CapabilityDefinition(
            id="test.write",
            name="测试写入",
            description="",
            category=CapabilityCategory.EDITOR,
            permission=TrustLevel.WORKSPACE_WRITE,
            rollback_support=True,
        )

        # 模拟 input_transformer
        engine.input_transformer.extract_paths = lambda params: [str(test_file)]

        asyncio.run(engine._create_snapshot_before_write(
            {"path": str(test_file)}, cap_def
        ))
        # 不应报错，快照已创建


class TestV2EngineWithSelfEvoDisabled:
    """V2Engine 自进化禁用测试"""

    def test_initialize_without_self_evo(self) -> None:
        """测试禁用自进化时初始化"""
        from pycoder.v2 import V2Engine, V2EngineConfig

        engine = V2Engine(V2EngineConfig(
            workspace_root=os.getcwd(),
            enable_self_evo=False,
        ))
        asyncio.run(engine.initialize())
        assert engine.evolution is None
        assert engine._initialized is True


class TestV2EngineWithConsciousnessDisabled:
    """V2Engine 意识引擎禁用测试"""

    def test_initialize_without_consciousness(self) -> None:
        """测试禁用意识引擎时初始化"""
        from pycoder.v2 import V2Engine, V2EngineConfig

        engine = V2Engine(V2EngineConfig(
            workspace_root=os.getcwd(),
            enable_consciousness=False,
        ))
        asyncio.run(engine.initialize())
        assert engine._initialized is True