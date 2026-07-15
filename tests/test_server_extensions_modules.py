"""综合单元测试: pycoder/server/log.py, app_lifecycle.py, 
   pycoder/extensions/packaging.py, contributions.py, host.py, manager.py(未覆盖部分)

覆盖范围:
  - log.py: get_logger 函数、structlog 配置、降级回退
  - app_lifecycle.py: get_uptime, get_health_info, run_server, _check_upgrade_on_startup
  - packaging.py: validate_manifest, pack, unpack, pack_installed, scaffold
  - contributions.py: 所有 dataclass 模型、CommandRegistry、SettingsRegistry、
    parse_contributions_from_manifest、register/unregister
  - host.py: ExtensionAPI, ExtensionSandbox, ExtensionHostManager
  - manager.py: _install_seed_metadata, scaffold_extension, npm/pypi/vsix 安装,
    get_extension_details, get_stats 等未覆盖部分

测试策略:
  - monkeypatch 用于 external dependencies 和 import 模拟
  - tmp_path 用于文件系统隔离
  - MagicMock/AsyncMock 用于子进程和网络调用
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ══════════════════════════════════════════════════════════
# 第一部分: log.py 模块测试
# ══════════════════════════════════════════════════════════


class TestLogModule:
    """测试 pycoder/server/log.py 日志模块"""

    def test_get_logger_returns_logger(self, monkeypatch):
        """get_logger 返回一个有效的日志对象"""
        # 确保 structlog 可用
        monkeypatch.setattr("pycoder.server.log._has_structlog", True)
        import structlog

        from pycoder.server.log import get_logger

        logger = get_logger("test_logger")
        assert logger is not None

    def test_get_logger_with_custom_name(self, monkeypatch):
        """get_logger 使用自定义名称返回日志器"""
        monkeypatch.setattr("pycoder.server.log._has_structlog", True)
        from pycoder.server.log import get_logger

        logger = get_logger("my_custom_module")
        assert logger is not None

    def test_get_logger_default_name(self, monkeypatch):
        """get_logger 不传名称时使用 __name__"""
        monkeypatch.setattr("pycoder.server.log._has_structlog", True)
        from pycoder.server.log import get_logger

        logger = get_logger()
        assert logger is not None

    def test_log_convenience_access(self, monkeypatch):
        """log 便捷访问变量存在"""
        monkeypatch.setattr("pycoder.server.log._has_structlog", True)
        from pycoder.server.log import log

        assert log is not None

    def test_get_logger_fallback_no_structlog(self, monkeypatch):
        """没有 structlog 时降级使用标准 logging"""
        import logging

        # 模拟 structlog 导入失败：在模块导入前阻止 structlog
        import builtins

        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "structlog":
                raise ImportError("No module named structlog")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        # 删除已缓存的模块并重新导入
        for key in list(sys.modules.keys()):
            if "pycoder.server.log" in key:
                del sys.modules[key]

        import pycoder.server.log as log_mod

        logger = log_mod.get_logger("fallback_test")
        assert isinstance(logger, logging.Logger)

    def test_get_logger_none_name_fallback(self, monkeypatch):
        """get_logger(None) 降级时返回标准 logger"""
        import logging

        import builtins

        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "structlog":
                raise ImportError("No module named structlog")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        for key in list(sys.modules.keys()):
            if "pycoder.server.log" in key:
                del sys.modules[key]

        import pycoder.server.log as log_mod

        logger = log_mod.get_logger(None)
        assert isinstance(logger, logging.Logger)


# ══════════════════════════════════════════════════════════
# 第二部分: app_lifecycle.py 模块测试
# ══════════════════════════════════════════════════════════


class TestAppLifecycle:
    """测试 pycoder/server/app_lifecycle.py 应用生命周期"""

    def test_get_uptime_positive(self):
        """get_uptime 返回正数（秒）"""
        from pycoder.server.app_lifecycle import get_uptime

        uptime = get_uptime()
        assert uptime >= 0

    def test_get_uptime_increases(self):
        """get_uptime 随时间增加"""
        import time

        from pycoder.server.app_lifecycle import get_uptime

        t1 = get_uptime()
        time.sleep(0.01)
        t2 = get_uptime()
        assert t2 >= t1

    def test_get_health_info_ok(self):
        """get_health_info 返回 status=ok"""
        from pycoder.server.app_lifecycle import get_health_info

        info = get_health_info("3.14.0")
        assert info["status"] == "ok"

    def test_get_health_info_contains_version(self):
        """get_health_info 包含版本号"""
        from pycoder import __version__
        from pycoder.server.app_lifecycle import get_health_info

        info = get_health_info("3.14.0")
        assert info["version"] == __version__

    def test_get_health_info_contains_python(self):
        """get_health_info 包含 Python 版本"""
        from pycoder.server.app_lifecycle import get_health_info

        info = get_health_info("3.14.0")
        assert info["python"] == "3.14.0"

    def test_get_health_info_contains_pid(self):
        """get_health_info 包含 pid"""
        from pycoder.server.app_lifecycle import get_health_info

        info = get_health_info("3.14.0")
        assert "pid" in info
        assert isinstance(info["pid"], int)

    def test_get_health_info_contains_uptime(self):
        """get_health_info 包含 uptime"""
        from pycoder.server.app_lifecycle import get_health_info

        info = get_health_info("3.14.0")
        assert "server_uptime_seconds" in info
        assert isinstance(info["server_uptime_seconds"], float)

    def test_run_server_calls_uvicorn(self, monkeypatch):
        """run_server 调用 uvicorn.run"""
        mock_run = MagicMock()
        monkeypatch.setattr("uvicorn.run", mock_run)

        from pycoder.server.app_lifecycle import run_server

        # 避免 _check_upgrade_on_startup 副作用
        monkeypatch.setattr(
            "pycoder.server.app_lifecycle._check_upgrade_on_startup",
            lambda: None,
        )

        run_server(host="0.0.0.0", port=1234, reload=True)
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["host"] == "0.0.0.0"
        assert call_kwargs["port"] == 1234
        assert call_kwargs["reload"] is True

    def test_run_server_defaults(self, monkeypatch):
        """run_server 使用默认参数"""
        mock_run = MagicMock()
        monkeypatch.setattr("uvicorn.run", mock_run)
        monkeypatch.setattr(
            "pycoder.server.app_lifecycle._check_upgrade_on_startup",
            lambda: None,
        )

        from pycoder.server.app_lifecycle import run_server

        run_server()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["host"] == "127.0.0.1"
        assert call_kwargs["port"] == 8423
        assert call_kwargs["reload"] is False

    def test_check_upgrade_on_startup_no_module(self, monkeypatch):
        """_check_upgrade_on_startup 在 auto_upgrade 模块不存在时静默失败"""
        monkeypatch.setitem(sys.modules, "pycoder.server.auto_upgrade", None)

        from pycoder.server.app_lifecycle import _check_upgrade_on_startup

        # 不应抛出异常
        _check_upgrade_on_startup()

    def test_check_upgrade_on_startup_import_error(self, monkeypatch):
        """_check_upgrade_on_startup ImportError 时不崩溃"""
        import builtins

        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if "auto_upgrade" in name:
                raise ImportError("No module named auto_upgrade")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        from pycoder.server.app_lifecycle import _check_upgrade_on_startup

        _check_upgrade_on_startup()  # 不应抛出异常

    def test_check_upgrade_on_startup_failed_status(self, monkeypatch, capsys):
        """_check_upgrade_on_startup 处理 failed 状态"""
        mock_check = MagicMock(return_value={"status": "failed"})
        monkeypatch.setattr(
            "pycoder.server.auto_upgrade.check_pending_on_startup",
            mock_check,
        )
        monkeypatch.setitem(sys.modules, "pycoder.server.auto_upgrade", MagicMock())
        monkeypatch.setattr(
            sys.modules["pycoder.server.auto_upgrade"],
            "check_pending_on_startup",
            mock_check,
        )

        from pycoder.server.app_lifecycle import _check_upgrade_on_startup

        _check_upgrade_on_startup()
        captured = capsys.readouterr()
        assert "升级恢复失败" in captured.out

    def test_check_upgrade_on_startup_resumed_status(self, monkeypatch, capsys):
        """_check_upgrade_on_startup 处理 resumed_and_completed 状态"""
        mock_check = MagicMock(return_value={"status": "resumed_and_completed"})
        monkeypatch.setattr(
            "pycoder.server.auto_upgrade.check_pending_on_startup",
            mock_check,
        )
        monkeypatch.setitem(sys.modules, "pycoder.server.auto_upgrade", MagicMock())
        monkeypatch.setattr(
            sys.modules["pycoder.server.auto_upgrade"],
            "check_pending_on_startup",
            mock_check,
        )

        from pycoder.server.app_lifecycle import _check_upgrade_on_startup

        _check_upgrade_on_startup()
        captured = capsys.readouterr()
        assert "升级已恢复并完成" in captured.out

    def test_check_upgrade_on_startup_exception(self, monkeypatch, capsys):
        """_check_upgrade_on_startup 异常时打印警告但不崩溃"""
        mock_check = MagicMock(side_effect=RuntimeError("测试异常"))
        monkeypatch.setattr(
            "pycoder.server.auto_upgrade.check_pending_on_startup",
            mock_check,
        )
        monkeypatch.setitem(sys.modules, "pycoder.server.auto_upgrade", MagicMock())
        monkeypatch.setattr(
            sys.modules["pycoder.server.auto_upgrade"],
            "check_pending_on_startup",
            mock_check,
        )

        from pycoder.server.app_lifecycle import _check_upgrade_on_startup

        _check_upgrade_on_startup()
        captured = capsys.readouterr()
        assert "升级检测跳过" in captured.out
        assert "测试异常" in captured.out


# ══════════════════════════════════════════════════════════
# 第三部分: packaging.py 模块测试
# ══════════════════════════════════════════════════════════


class TestValidateManifest:
    """测试 manifest 验证"""

    def test_valid_manifest_passes(self):
        """有效的 manifest 不应产生错误"""
        from pycoder.extensions.packaging import validate_manifest

        manifest = {
            "id": "publisher.myext",
            "name": "My Extension",
            "version": "1.0.0",
            "description": "A test extension",
            "author": "Test Author",
        }
        errors = validate_manifest(manifest)
        assert errors == []

    def test_missing_required_fields(self):
        """缺少必填字段应报错"""
        from pycoder.extensions.packaging import validate_manifest

        errors = validate_manifest({})
        assert len(errors) >= 5  # id, name, version, description, author
        assert any("id" in e for e in errors)
        assert any("name" in e for e in errors)
        assert any("version" in e for e in errors)
        assert any("description" in e for e in errors)
        assert any("author" in e for e in errors)

    def test_empty_required_fields(self):
        """必填字段为空字符串应报错"""
        from pycoder.extensions.packaging import validate_manifest

        manifest = {
            "id": "",
            "name": "",
            "version": "",
            "description": "",
            "author": "",
        }
        errors = validate_manifest(manifest)
        assert len(errors) >= 5

    def test_invalid_id_no_dot(self):
        """无效 ID（无 . 分隔符）"""
        from pycoder.extensions.packaging import validate_manifest

        manifest = {
            "id": "badid",
            "name": "Test",
            "version": "1.0.0",
            "description": "desc",
            "author": "author",
        }
        errors = validate_manifest(manifest)
        assert any("ID 格式无效" in e for e in errors)

    def test_invalid_id_with_space(self):
        """无效 ID（含空格）"""
        from pycoder.extensions.packaging import validate_manifest

        manifest = {
            "id": "bad id",
            "name": "Test",
            "version": "1.0.0",
            "description": "desc",
            "author": "author",
        }
        errors = validate_manifest(manifest)
        assert any("ID 格式无效" in e for e in errors)

    def test_invalid_version_format(self):
        """无效版本号格式"""
        from pycoder.extensions.packaging import validate_manifest

        manifest = {
            "id": "pub.ext",
            "name": "Test",
            "version": "not-semver",
            "description": "desc",
            "author": "author",
        }
        errors = validate_manifest(manifest)
        assert any("版本号格式无效" in e for e in errors)

    def test_semver_version_passes(self):
        """semver 版本号通过验证"""
        from pycoder.extensions.packaging import validate_manifest

        for v in ["0.0.1", "1.0.0", "2.3.4", "10.20.30", "1.0.0-beta"]:
            manifest = {
                "id": "pub.ext",
                "name": "Test",
                "version": v,
                "description": "desc",
                "author": "author",
            }
            errors = validate_manifest(manifest)
            assert not any("版本号格式无效" in e for e in errors), f"版本 {v} 应有效"

    def test_missing_pycoder_engine(self):
        """engines 中缺少 pycoder 声明"""
        from pycoder.extensions.packaging import validate_manifest

        manifest = {
            "id": "pub.ext",
            "name": "Test",
            "version": "1.0.0",
            "description": "desc",
            "author": "author",
            "engines": {"vscode": ">=1.0.0"},
        }
        errors = validate_manifest(manifest)
        assert any("pycoder" in e for e in errors)

    def test_invalid_activation_event(self):
        """无效的 activationEvent"""
        from pycoder.extensions.packaging import validate_manifest

        manifest = {
            "id": "pub.ext",
            "name": "Test",
            "version": "1.0.0",
            "description": "desc",
            "author": "author",
            "activationEvents": ["badEvent", "onCommand:test", "*"],
        }
        errors = validate_manifest(manifest)
        assert any("badEvent" in e for e in errors)

    def test_valid_activation_events(self):
        """有效的 activationEvent 全部通过"""
        from pycoder.extensions.packaging import validate_manifest

        manifest = {
            "id": "pub.ext",
            "name": "Test",
            "version": "1.0.0",
            "description": "desc",
            "author": "author",
            "activationEvents": [
                "onCommand:test",
                "onLanguage:python",
                "onView:explorer",
                "onStartupFinished",
                "*",
            ],
        }
        errors = validate_manifest(manifest)
        assert not any("activationEvent" in e for e in errors)

    def test_contributes_not_dict(self):
        """contributes 不是对象时报错"""
        from pycoder.extensions.packaging import validate_manifest

        manifest = {
            "id": "pub.ext",
            "name": "Test",
            "version": "1.0.0",
            "description": "desc",
            "author": "author",
            "contributes": "not-a-dict",
        }
        errors = validate_manifest(manifest)
        assert any("contributes 必须是对象" in e for e in errors)

    def test_contributes_command_missing_command(self):
        """contributes.commands 中缺少 command 字段"""
        from pycoder.extensions.packaging import validate_manifest

        manifest = {
            "id": "pub.ext",
            "name": "Test",
            "version": "1.0.0",
            "description": "desc",
            "author": "author",
            "contributes": {"commands": [{"title": "No Command"}]},
        }
        errors = validate_manifest(manifest)
        assert any("缺少 'command'" in e for e in errors)

    def test_contributes_command_missing_title(self):
        """contributes.commands 中缺少 title 字段"""
        from pycoder.extensions.packaging import validate_manifest

        manifest = {
            "id": "pub.ext",
            "name": "Test",
            "version": "1.0.0",
            "description": "desc",
            "author": "author",
            "contributes": {"commands": [{"command": "test.cmd"}]},
        }
        errors = validate_manifest(manifest)
        assert any("缺少 'title'" in e for e in errors)


class TestPack:
    """测试打包功能"""

    def test_pack_not_a_directory(self):
        """打包不存在的目录抛出异常"""
        from pycoder.extensions.packaging import pack

        with pytest.raises(NotADirectoryError):
            pack("/nonexistent/path")

    def test_pack_missing_manifest(self, tmp_path):
        """缺少 manifest.json 抛出异常"""
        from pycoder.extensions.packaging import pack

        src = tmp_path / "myext"
        src.mkdir()
        with pytest.raises(FileNotFoundError):
            pack(str(src))

    def test_pack_invalid_manifest(self, tmp_path):
        """无效 manifest 打包抛出异常"""
        from pycoder.extensions.packaging import pack

        src = tmp_path / "myext"
        src.mkdir()
        (src / "manifest.json").write_text(json.dumps({}), encoding="utf-8")
        with pytest.raises(ValueError, match="Manifest 校验失败"):
            pack(str(src))

    def test_pack_success(self, tmp_path):
        """成功打包生成 .pycoder-ext 文件"""
        from pycoder.extensions.packaging import pack

        src = tmp_path / "myext"
        src.mkdir()
        manifest = {
            "id": "pub.myext",
            "name": "My Extension",
            "version": "1.0.0",
            "description": "A test",
            "author": "test",
        }
        (src / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (src / "extension.py").write_text("# test", encoding="utf-8")

        output = pack(str(src))
        assert output.endswith(".pycoder-ext")
        assert Path(output).exists()

    def test_pack_with_extension_subdir(self, tmp_path):
        """源目录下有 extension/ 子目录时使用子目录"""
        from pycoder.extensions.packaging import pack

        src = tmp_path / "myext"
        ext_dir = src / "extension"
        ext_dir.mkdir(parents=True)
        manifest = {
            "id": "pub.myext",
            "name": "My Extension",
            "version": "1.0.0",
            "description": "A test",
            "author": "test",
        }
        (ext_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (ext_dir / "extension.py").write_text("# test", encoding="utf-8")

        output = pack(str(src))
        assert output.endswith(".pycoder-ext")
        assert Path(output).exists()

    def test_pack_custom_output(self, tmp_path):
        """自定义输出路径"""
        from pycoder.extensions.packaging import pack

        src = tmp_path / "myext"
        src.mkdir()
        manifest = {
            "id": "pub.myext",
            "name": "My Extension",
            "version": "1.0.0",
            "description": "A test",
            "author": "test",
        }
        (src / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (src / "extension.py").write_text("# test", encoding="utf-8")

        custom_out = tmp_path / "custom.python-ext"
        output = pack(str(src), str(custom_out))
        assert str(custom_out) == output


class TestUnpack:
    """测试解包功能"""

    def test_unpack_missing_archive(self, tmp_path):
        """解包不存在的文件抛出异常"""
        from pycoder.extensions.packaging import unpack

        with pytest.raises(FileNotFoundError):
            unpack(tmp_path / "nonexistent.python-ext")

    def test_unpack_creates_target(self, tmp_path):
        """解包创建目标目录"""
        from pycoder.extensions.packaging import unpack

        # 创建一个有效的 .pycoder-ext
        archive_path = tmp_path / "test.python-ext"
        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr(
                "manifest.json",
                json.dumps({"id": "pub.test", "name": "Test"}),
            )
            zf.writestr("extension.py", "# test")

        target = tmp_path / "output"
        result = unpack(str(archive_path), str(target))
        assert Path(result).exists()
        assert (target / "manifest.json").exists()

    def test_unpack_default_target(self, tmp_path, monkeypatch):
        """解包使用默认目标目录"""
        from pycoder.extensions.packaging import unpack

        # 创建一个有效的 .pycoder-ext
        archive_path = tmp_path / "test.python-ext"
        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr(
                "manifest.json",
                json.dumps({"id": "pub.test", "name": "Test"}),
            )
            zf.writestr("extension.py", "# test")

        # 重定向 EXTENSIONS_DIR
        import pycoder.extensions.manager as mgr

        default_ext_dir = tmp_path / "default_exts"
        monkeypatch.setattr(mgr, "EXTENSIONS_DIR", default_ext_dir)

        result = unpack(str(archive_path))
        assert Path(result).exists()

    def test_unpack_no_manifest_in_archive(self, tmp_path):
        """解包不含 manifest.json 的 archive"""
        from pycoder.extensions.packaging import unpack

        archive_path = tmp_path / "test.python-ext"
        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr("extension.py", "# no manifest")

        target = tmp_path / "output"
        result = unpack(str(archive_path), str(target))
        assert Path(result).exists()


class TestPackInstalled:
    """测试 pack_installed"""

    def test_pack_installed_not_found(self, tmp_path, monkeypatch):
        """扩展未安装时抛出 FileNotFoundError"""
        from pycoder.extensions.packaging import pack_installed

        import pycoder.extensions.manager as mgr

        monkeypatch.setattr(mgr, "EXTENSIONS_DIR", tmp_path)

        with pytest.raises(FileNotFoundError):
            pack_installed("nonexistent.ext")


class TestScaffold:
    """测试脚手架生成"""

    def test_scaffold_creates_directory(self, tmp_path, monkeypatch):
        """scaffold 创建扩展目录"""
        from pycoder.extensions.packaging import scaffold

        import pycoder.extensions.manager as mgr

        monkeypatch.setattr(mgr, "EXTENSIONS_DIR", tmp_path)

        result = scaffold("pub.myext", "My Extension", "描述", "作者")
        assert Path(result).exists()
        assert Path(result).is_dir()

    def test_scaffold_creates_manifest(self, tmp_path, monkeypatch):
        """scaffold 创建 manifest.json"""
        from pycoder.extensions.packaging import scaffold

        import pycoder.extensions.manager as mgr

        monkeypatch.setattr(mgr, "EXTENSIONS_DIR", tmp_path)

        result = scaffold("pub.myext", "My Extension")
        manifest_path = Path(result) / "manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["id"] == "pub.myext"
        assert manifest["name"] == "My Extension"
        assert manifest["version"] == "0.1.0"

    def test_scaffold_creates_extension_py(self, tmp_path, monkeypatch):
        """scaffold 创建 extension.py"""
        from pycoder.extensions.packaging import scaffold

        import pycoder.extensions.manager as mgr

        monkeypatch.setattr(mgr, "EXTENSIONS_DIR", tmp_path)

        result = scaffold("pub.myext", "My Extension")
        code_path = Path(result) / "extension.py"
        assert code_path.exists()
        code = code_path.read_text(encoding="utf-8")
        assert "My Extension" in code
        assert "activate" in code
        assert "deactivate" in code

    def test_scaffold_creates_readme(self, tmp_path, monkeypatch):
        """scaffold 创建 README.md"""
        from pycoder.extensions.packaging import scaffold

        import pycoder.extensions.manager as mgr

        monkeypatch.setattr(mgr, "EXTENSIONS_DIR", tmp_path)

        result = scaffold("pub.myext", "My Extension", "描述")
        readme_path = Path(result) / "README.md"
        assert readme_path.exists()
        content = readme_path.read_text(encoding="utf-8")
        assert "My Extension" in content
        assert "描述" in content

    def test_scaffold_default_description(self, tmp_path, monkeypatch):
        """scaffold 默认描述"""
        from pycoder.extensions.packaging import scaffold

        import pycoder.extensions.manager as mgr

        monkeypatch.setattr(mgr, "EXTENSIONS_DIR", tmp_path)

        result = scaffold("pub.myext", "My Extension")
        manifest_path = Path(result) / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "PyCoder 扩展" in manifest["description"]

    def test_scaffold_default_author(self, tmp_path, monkeypatch):
        """scaffold 默认作者"""
        from pycoder.extensions.packaging import scaffold

        import pycoder.extensions.manager as mgr

        monkeypatch.setattr(mgr, "EXTENSIONS_DIR", tmp_path)

        result = scaffold("pub.myext", "My Extension")
        manifest_path = Path(result) / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["author"] == "anonymous"


# ══════════════════════════════════════════════════════════
# 第四部分: contributions.py 模块测试
# ══════════════════════════════════════════════════════════


class TestContributionDataclasses:
    """测试贡献点 dataclass 模型"""

    def test_command_contribution_defaults(self):
        """CommandContribution 默认值"""
        from pycoder.extensions.contributions import CommandContribution

        cmd = CommandContribution(id="test.cmd", title="Test Command")
        assert cmd.id == "test.cmd"
        assert cmd.title == "Test Command"
        assert cmd.category == ""
        assert cmd.icon == ""
        assert cmd.enablement == ""
        assert cmd.keybinding == ""

    def test_command_contribution_full(self):
        """CommandContribution 完整字段"""
        from pycoder.extensions.contributions import CommandContribution

        cmd = CommandContribution(
            id="test.cmd",
            title="Test",
            category="Tools",
            icon="star",
            enablement="editorFocus",
            keybinding="ctrl+t",
        )
        assert cmd.category == "Tools"
        assert cmd.icon == "star"
        assert cmd.keybinding == "ctrl+t"

    def test_setting_contribution_defaults(self):
        """SettingContribution 默认值"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(id="test.setting", title="Test Setting")
        assert s.id == "test.setting"
        assert s.title == "Test Setting"
        assert s.type == "string"
        assert s.default is None
        assert s.scope == "resource"

    def test_setting_contribution_enum(self):
        """SettingContribution 枚举值"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(
            id="test.setting",
            title="Test",
            type="string",
            enum=["a", "b", "c"],
        )
        assert s.enum == ["a", "b", "c"]

    def test_keybinding_contribution(self):
        """KeybindingContribution 字段"""
        from pycoder.extensions.contributions import KeybindingContribution

        kb = KeybindingContribution(
            key="ctrl+shift+g",
            command="test.cmd",
            when="editorFocus",
            mac="cmd+shift+g",
        )
        assert kb.key == "ctrl+shift+g"
        assert kb.command == "test.cmd"
        assert kb.when == "editorFocus"
        assert kb.mac == "cmd+shift+g"

    def test_view_contribution(self):
        """ViewContribution 字段"""
        from pycoder.extensions.contributions import ViewContribution

        v = ViewContribution(id="test.view", name="Test View", type="webview", when="explorer")
        assert v.id == "test.view"
        assert v.name == "Test View"
        assert v.type == "webview"

    def test_menu_contribution(self):
        """MenuContribution 字段"""
        from pycoder.extensions.contributions import MenuContribution

        m = MenuContribution(command="test.cmd", group="navigation", when="editorFocus")
        assert m.command == "test.cmd"
        assert m.group == "navigation"

    def test_language_contribution(self):
        """LanguageContribution 字段"""
        from pycoder.extensions.contributions import LanguageContribution

        lang = LanguageContribution(
            id="python",
            extensions=[".py", ".pyw"],
            aliases=["Python", "py"],
        )
        assert lang.id == "python"
        assert lang.extensions == [".py", ".pyw"]
        assert lang.aliases == ["Python", "py"]

    def test_extension_contributions_is_empty(self):
        """ExtensionContributions 空判断"""
        from pycoder.extensions.contributions import ExtensionContributions

        ec = ExtensionContributions()
        assert ec.is_empty() is True

    def test_extension_contributions_not_empty(self):
        """ExtensionContributions 非空"""
        from pycoder.extensions.contributions import (
            CommandContribution,
            ExtensionContributions,
        )

        ec = ExtensionContributions()
        ec.commands.append(CommandContribution(id="test", title="Test"))
        assert ec.is_empty() is False


class TestCommandRegistry:
    """测试命令注册中心"""

    @pytest.fixture
    def registry(self):
        from pycoder.extensions.contributions import CommandRegistry

        return CommandRegistry()

    def test_register_command(self, registry):
        """注册命令"""
        from pycoder.extensions.contributions import CommandContribution

        cmd = CommandContribution(id="test.cmd", title="Test")
        registry.register(cmd, ext_id="test_ext")
        assert registry.get("test.cmd") is not None

    def test_register_with_handler(self, registry):
        """注册命令并绑定处理器"""
        from pycoder.extensions.contributions import CommandContribution

        cmd = CommandContribution(id="test.cmd", title="Test")
        handler = MagicMock(return_value="result")
        registry.register(cmd, handler=handler)
        result = registry.execute("test.cmd")
        assert result == "result"
        handler.assert_called_once()

    def test_execute_not_registered(self, registry):
        """执行未注册的命令抛出 KeyError"""
        with pytest.raises(KeyError, match="命令未注册"):
            registry.execute("nonexistent.cmd")

    def test_execute_no_handler(self, registry):
        """执行无处理器的命令抛出 KeyError"""
        from pycoder.extensions.contributions import CommandContribution

        cmd = CommandContribution(id="test.cmd", title="Test")
        registry.register(cmd)
        with pytest.raises(KeyError, match="命令无处理器"):
            registry.execute("test.cmd")

    def test_get_nonexistent(self, registry):
        """获取不存在的命令返回 None"""
        assert registry.get("nonexistent") is None

    def test_list_commands(self, registry):
        """列出所有命令"""
        from pycoder.extensions.contributions import CommandContribution

        cmd1 = CommandContribution(id="test.cmd1", title="Test 1")
        cmd2 = CommandContribution(id="test.cmd2", title="Test 2")
        registry.register(cmd1, ext_id="ext1")
        registry.register(cmd2, ext_id="ext2")

        all_cmds = registry.list()
        assert len(all_cmds) == 2

    def test_list_commands_filtered(self, registry):
        """按扩展 ID 过滤命令"""
        from pycoder.extensions.contributions import CommandContribution

        cmd1 = CommandContribution(id="ext1.cmd", title="Cmd 1")
        cmd2 = CommandContribution(id="ext2.cmd", title="Cmd 2")
        registry.register(cmd1, ext_id="ext1")
        registry.register(cmd2, ext_id="ext2")

        filtered = registry.list(ext_id="ext1")
        assert len(filtered) == 1
        assert filtered[0].id == "ext1.cmd"

    def test_search_commands(self, registry):
        """搜索命令"""
        from pycoder.extensions.contributions import CommandContribution

        cmd = CommandContribution(
            id="pycoder.gitlens.blame",
            title="Git: 查看 Blame",
            category="Git",
        )
        registry.register(cmd, ext_id="pycoder.gitlens")

        results = registry.search("blame")
        assert len(results) == 1
        assert results[0]["id"] == "pycoder.gitlens.blame"

    def test_search_empty_query(self, registry):
        """空查询返回所有命令"""
        from pycoder.extensions.contributions import CommandContribution

        cmd = CommandContribution(id="test.cmd", title="Test")
        registry.register(cmd, ext_id="test")
        results = registry.search("")
        assert len(results) == 1

    def test_count(self, registry):
        """统计命令数量"""
        from pycoder.extensions.contributions import CommandContribution

        assert registry.count() == 0
        registry.register(CommandContribution(id="test.cmd", title="Test"))
        assert registry.count() == 1

    def test_clear_extension(self, registry):
        """清除扩展的所有命令"""
        from pycoder.extensions.contributions import CommandContribution

        cmd1 = CommandContribution(id="ext1.cmd", title="Cmd 1")
        cmd2 = CommandContribution(id="ext2.cmd", title="Cmd 2")
        registry.register(cmd1, ext_id="ext1")
        registry.register(cmd2, ext_id="ext2")

        removed = registry.clear_extension("ext1")
        assert removed == 1
        assert registry.get("ext1.cmd") is None
        assert registry.get("ext2.cmd") is not None

    def test_execute_with_args(self, registry):
        """执行命令时传递参数"""
        from pycoder.extensions.contributions import CommandContribution

        cmd = CommandContribution(id="test.cmd", title="Test")
        handler = MagicMock(return_value="done")
        registry.register(cmd, handler=handler)

        registry.execute("test.cmd", "arg1", key="value")
        handler.assert_called_once_with("arg1", key="value")


class TestSettingsRegistry:
    """测试设置注册中心"""

    @pytest.fixture
    def registry(self):
        from pycoder.extensions.contributions import SettingsRegistry

        return SettingsRegistry()

    def test_register_setting(self, registry):
        """注册设置项"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(
            id="test.setting",
            title="Test Setting",
            type="boolean",
            default=True,
        )
        registry.register(s, ext_id="test_ext")
        assert registry.get("test.setting") is True

    def test_get_default_value(self, registry):
        """获取设置默认值"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(
            id="test.setting",
            title="Test",
            type="string",
            default="hello",
        )
        registry.register(s)
        assert registry.get("test.setting") == "hello"

    def test_get_unregistered_returns_none(self, registry):
        """获取未注册的设置返回 None"""
        assert registry.get("nonexistent") is None

    def test_set_valid_value(self, registry):
        """设置有效值"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(
            id="test.setting",
            title="Test",
            type="string",
            default="old",
        )
        registry.register(s)
        assert registry.set("test.setting", "new") is True
        assert registry.get("test.setting") == "new"

    def test_set_unregistered_key(self, registry):
        """设置未注册的 key 返回 False"""
        assert registry.set("nonexistent", "value") is False

    def test_set_type_mismatch(self, registry):
        """类型不匹配时设置失败"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(
            id="test.setting",
            title="Test",
            type="boolean",
            default=True,
        )
        registry.register(s)
        assert registry.set("test.setting", "not-a-bool") is False

    def test_set_number_type(self, registry):
        """number 类型接受 int 和 float"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(
            id="test.num",
            title="Test",
            type="number",
            default=0,
        )
        registry.register(s)
        assert registry.set("test.num", 42) is True
        assert registry.set("test.num", 3.14) is True

    def test_set_enum_validation(self, registry):
        """枚举值校验"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(
            id="test.enum",
            title="Test",
            type="string",
            enum=["a", "b", "c"],
            default="a",
        )
        registry.register(s)
        assert registry.set("test.enum", "b") is True
        assert registry.set("test.enum", "d") is False

    def test_set_range_validation_min(self, registry):
        """最小值校验"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(
            id="test.range",
            title="Test",
            type="number",
            minimum=0,
            maximum=100,
            default=50,
        )
        registry.register(s)
        assert registry.set("test.range", -1) is False
        assert registry.set("test.range", 50) is True

    def test_set_range_validation_max(self, registry):
        """最大值校验"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(
            id="test.range",
            title="Test",
            type="number",
            minimum=0,
            maximum=100,
            default=50,
        )
        registry.register(s)
        assert registry.set("test.range", 101) is False
        assert registry.set("test.range", 100) is True

    def test_list_settings(self, registry):
        """列出设置项"""
        from pycoder.extensions.contributions import SettingContribution

        s1 = SettingContribution(id="ext1.setting", title="S1", type="boolean", default=True)
        s2 = SettingContribution(id="ext2.setting", title="S2", type="string", default="x")
        registry.register(s1, ext_id="ext1")
        registry.register(s2, ext_id="ext2")

        all_settings = registry.list_settings()
        assert len(all_settings) == 2

    def test_list_settings_filtered(self, registry):
        """按扩展过滤设置"""
        from pycoder.extensions.contributions import SettingContribution

        s1 = SettingContribution(id="ext1.setting", title="S1", type="boolean", default=True)
        s2 = SettingContribution(id="ext2.setting", title="S2", type="string", default="x")
        registry.register(s1, ext_id="ext1")
        registry.register(s2, ext_id="ext2")

        filtered = registry.list_settings(ext_id="ext1")
        assert len(filtered) == 1
        assert filtered[0]["id"] == "ext1.setting"

    def test_export_json(self, registry):
        """导出设置为 JSON"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(id="test.s", title="Test", type="string", default="v")
        registry.register(s)
        registry.set("test.s", "custom")

        exported = registry.export_json()
        assert exported["test.s"] == "custom"

    def test_import_json(self, registry):
        """从 JSON 导入设置"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(id="test.s", title="Test", type="string", default="v")
        registry.register(s)

        count = registry.import_json({"test.s": "imported"})
        assert count == 1
        assert registry.get("test.s") == "imported"

    def test_clear_extension(self, registry):
        """清除扩展的所有设置"""
        from pycoder.extensions.contributions import SettingContribution

        s1 = SettingContribution(id="ext1.s", title="S1", type="string", default="a")
        s2 = SettingContribution(id="ext2.s", title="S2", type="string", default="b")
        registry.register(s1, ext_id="ext1")
        registry.register(s2, ext_id="ext2")

        removed = registry.clear_extension("ext1")
        assert removed == 1
        assert registry.get("ext1.s") is None
        assert registry.get("ext2.s") == "b"

    def test_register_preserves_existing_value(self, registry):
        """注册设置时保留已有值"""
        from pycoder.extensions.contributions import SettingContribution

        s = SettingContribution(id="test.s", title="Test", type="string", default="default")
        registry.register(s)
        registry.set("test.s", "custom")

        # 重新注册（模拟重新加载）
        s2 = SettingContribution(id="test.s", title="Test", type="string", default="new_default")
        registry.register(s2)
        assert registry.get("test.s") == "custom"  # 保留旧值


class TestParseContributions:
    """测试从 manifest 解析贡献点"""

    def test_parse_empty_manifest(self):
        """空 manifest 返回空贡献"""
        from pycoder.extensions.contributions import parse_contributions_from_manifest

        result = parse_contributions_from_manifest({})
        assert result.is_empty() is True

    def test_parse_no_contributes(self):
        """无 contributes 字段返回空"""
        from pycoder.extensions.contributions import parse_contributions_from_manifest

        result = parse_contributions_from_manifest({"id": "test"})
        assert result.is_empty() is True

    def test_parse_commands(self):
        """解析 commands"""
        from pycoder.extensions.contributions import parse_contributions_from_manifest

        manifest = {
            "contributes": {
                "commands": [
                    {"command": "test.cmd", "title": "Test", "category": "Tools"},
                ]
            }
        }
        result = parse_contributions_from_manifest(manifest)
        assert len(result.commands) == 1
        assert result.commands[0].id == "test.cmd"
        assert result.commands[0].title == "Test"
        assert result.commands[0].category == "Tools"

    def test_parse_settings(self):
        """解析 settings"""
        from pycoder.extensions.contributions import parse_contributions_from_manifest

        manifest = {
            "contributes": {
                "settings": [
                    {
                        "id": "test.enabled",
                        "title": "Enable",
                        "type": "boolean",
                        "default": True,
                    },
                ]
            }
        }
        result = parse_contributions_from_manifest(manifest)
        assert len(result.settings) == 1
        assert result.settings[0].id == "test.enabled"
        assert result.settings[0].type == "boolean"
        assert result.settings[0].default is True

    def test_parse_keybindings(self):
        """解析 keybindings"""
        from pycoder.extensions.contributions import parse_contributions_from_manifest

        manifest = {
            "contributes": {
                "keybindings": [
                    {
                        "key": "ctrl+shift+g",
                        "command": "test.cmd",
                        "when": "editorFocus",
                    },
                ]
            }
        }
        result = parse_contributions_from_manifest(manifest)
        assert len(result.keybindings) == 1
        assert result.keybindings[0].key == "ctrl+shift+g"

    def test_parse_views(self):
        """解析 views"""
        from pycoder.extensions.contributions import parse_contributions_from_manifest

        manifest = {
            "contributes": {
                "views": [
                    {"id": "test.view", "name": "Test View", "type": "tree"},
                ]
            }
        }
        result = parse_contributions_from_manifest(manifest)
        assert len(result.views) == 1
        assert result.views[0].id == "test.view"

    def test_parse_menus(self):
        """解析 menus"""
        from pycoder.extensions.contributions import parse_contributions_from_manifest

        manifest = {
            "contributes": {
                "menus": [
                    {"command": "test.cmd", "group": "navigation"},
                ]
            }
        }
        result = parse_contributions_from_manifest(manifest)
        assert len(result.menus) == 1
        assert result.menus[0].command == "test.cmd"

    def test_parse_languages(self):
        """解析 languages"""
        from pycoder.extensions.contributions import parse_contributions_from_manifest

        manifest = {
            "contributes": {
                "languages": [
                    {
                        "id": "python",
                        "extensions": [".py"],
                        "aliases": ["Python"],
                    },
                ]
            }
        }
        result = parse_contributions_from_manifest(manifest)
        assert len(result.languages) == 1
        assert result.languages[0].id == "python"


class TestGlobalRegistries:
    """测试全局注册中心单例"""

    def test_get_command_registry_returns_singleton(self):
        """get_command_registry 返回同一个实例"""
        from pycoder.extensions.contributions import get_command_registry

        r1 = get_command_registry()
        r2 = get_command_registry()
        assert r1 is r2

    def test_get_settings_registry_returns_singleton(self):
        """get_settings_registry 返回同一个实例"""
        from pycoder.extensions.contributions import get_settings_registry

        r1 = get_settings_registry()
        r2 = get_settings_registry()
        assert r1 is r2

    def test_register_extension_contributions(self):
        """register_extension_contributions 将贡献注册到全局注册中心"""
        from pycoder.extensions.contributions import (
            get_command_registry,
            get_settings_registry,
            register_extension_contributions,
        )

        manifest = {
            "contributes": {
                "commands": [
                    {"command": "test.cmd", "title": "Test Command"},
                ],
                "settings": [
                    {
                        "id": "test.setting",
                        "title": "Test Setting",
                        "type": "boolean",
                        "default": True,
                    },
                ],
            }
        }

        result = register_extension_contributions("test_ext", manifest)
        assert len(result.commands) == 1
        assert len(result.settings) == 1

        cmd_reg = get_command_registry()
        assert cmd_reg.get("test.cmd") is not None

        set_reg = get_settings_registry()
        assert set_reg.get("test.setting") is True

        # 清理
        cmd_reg.clear_extension("test_ext")
        set_reg.clear_extension("test_ext")

    def test_unregister_extension_contributions(self):
        """unregister_extension_contributions 清除扩展贡献"""
        from pycoder.extensions.contributions import (
            get_command_registry,
            get_settings_registry,
            register_extension_contributions,
            unregister_extension_contributions,
        )

        manifest = {
            "contributes": {
                "commands": [
                    {"command": "test.cmd", "title": "Test"},
                ],
                "settings": [
                    {
                        "id": "test.setting",
                        "title": "Test",
                        "type": "string",
                        "default": "x",
                    },
                ],
            }
        }

        register_extension_contributions("test_ext", manifest)
        result = unregister_extension_contributions("test_ext")
        assert result["commands_removed"] == 1
        assert result["settings_removed"] == 1

        cmd_reg = get_command_registry()
        assert cmd_reg.get("test.cmd") is None


# ══════════════════════════════════════════════════════════
# 第五部分: host.py 模块测试
# ══════════════════════════════════════════════════════════


class TestExtensionAPI:
    """测试扩展 API"""

    @pytest.fixture
    def api(self):
        from pycoder.extensions.host import ExtensionAPI

        return ExtensionAPI("test.ext", {"version": "2.0.0"})

    def test_api_id(self, api):
        """ExtensionAPI.id 属性"""
        assert api.id == "test.ext"

    def test_api_version(self, api):
        """ExtensionAPI.version 属性"""
        assert api.version == "2.0.0"

    def test_api_version_default(self):
        """ExtensionAPI.version 默认值"""
        from pycoder.extensions.host import ExtensionAPI

        api = ExtensionAPI("test.ext", {})
        assert api.version == "0.0.0"

    def test_api_extension_path(self, api, monkeypatch, tmp_path):
        """ExtensionAPI.extension_path 属性"""
        from pycoder.extensions.host import ExtensionAPI

        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )
        api2 = ExtensionAPI("test.ext", {"version": "1.0.0"})
        expected = str(tmp_path / "test.ext")
        assert api2.extension_path == expected

    def test_api_context_set_get(self, api):
        """ExtensionAPI 上下文存储"""
        api.set_context("key1", "value1")
        assert api.get_context("key1") == "value1"

    def test_api_context_default(self, api):
        """get_context 默认值"""
        assert api.get_context("missing", "default") == "default"

    def test_api_subscribe_and_dispose(self, api):
        """ExtensionAPI subscribe 和 dispose"""
        callback = MagicMock()
        api.subscribe(callback)
        api.dispose()
        callback.assert_called_once()

    def test_api_dispose_multiple_callbacks(self, api):
        """dispose 调用所有订阅回调"""
        cb1 = MagicMock()
        cb2 = MagicMock()
        api.subscribe(cb1)
        api.subscribe(cb2)
        api.dispose()
        cb1.assert_called_once()
        cb2.assert_called_once()

    def test_api_dispose_callback_exception(self, api):
        """dispose 回调异常不阻止其他回调"""
        cb1 = MagicMock(side_effect=RuntimeError("boom"))
        cb2 = MagicMock()
        api.subscribe(cb1)
        api.subscribe(cb2)
        api.dispose()  # 不应抛出异常
        cb2.assert_called_once()

    def test_api_info_log(self, api, caplog):
        """ExtensionAPI.info 日志"""
        import logging

        with caplog.at_level(logging.INFO):
            api.info("测试消息")
        assert "测试消息" in caplog.text

    def test_api_warn_log(self, api, caplog):
        """ExtensionAPI.warn 日志"""
        import logging

        with caplog.at_level(logging.WARNING):
            api.warn("警告消息")
        assert "警告消息" in caplog.text

    def test_api_error_log(self, api, caplog):
        """ExtensionAPI.error 日志"""
        import logging

        with caplog.at_level(logging.ERROR):
            api.error("错误消息")
        assert "错误消息" in caplog.text

    def test_api_log_custom_level(self, api, caplog):
        """ExtensionAPI.log 自定义级别"""
        import logging

        with caplog.at_level(logging.DEBUG):
            api.log("DEBUG", "调试消息")
        assert "调试消息" in caplog.text

    def test_api_read_file(self, api, monkeypatch, tmp_path):
        """ExtensionAPI.read_file 读取扩展内文件"""
        from pycoder.extensions.host import ExtensionAPI

        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )
        ext_dir = tmp_path / "test.ext"
        ext_dir.mkdir()
        (ext_dir / "data.txt").write_text("hello", encoding="utf-8")

        api2 = ExtensionAPI("test.ext", {})
        content = api2.read_file("data.txt")
        assert content == "hello"

    def test_api_read_file_nonexistent(self, api):
        """ExtensionAPI.read_file 文件不存在返回 None"""
        content = api.read_file("nonexistent.txt")
        assert content is None

    def test_api_list_files(self, api, monkeypatch, tmp_path):
        """ExtensionAPI.list_files 列出扩展内文件"""
        from pycoder.extensions.host import ExtensionAPI

        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )
        ext_dir = tmp_path / "test.ext"
        ext_dir.mkdir()
        (ext_dir / "a.py").write_text("a", encoding="utf-8")
        (ext_dir / "b.py").write_text("b", encoding="utf-8")

        api2 = ExtensionAPI("test.ext", {})
        files = api2.list_files()
        assert len(files) == 2

    def test_api_list_files_empty(self, api):
        """ExtensionAPI.list_files 空目录"""
        files = api.list_files()
        assert files == []


class TestExtensionSandbox:
    """测试扩展沙箱"""

    @pytest.fixture
    def sandbox_dir(self, tmp_path, monkeypatch):
        """创建沙箱测试目录"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )
        ext_dir = tmp_path / "test.ext"
        ext_dir.mkdir()
        return ext_dir

    def test_sandbox_is_installed_false(self, tmp_path, monkeypatch):
        """扩展未安装时 is_installed 返回 False"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )
        from pycoder.extensions.host import ExtensionSandbox

        sandbox = ExtensionSandbox("nonexistent.ext")
        assert sandbox.is_installed() is False

    def test_sandbox_is_installed_true(self, sandbox_dir):
        """扩展已安装时 is_installed 返回 True"""
        from pycoder.extensions.host import ExtensionSandbox

        sandbox = ExtensionSandbox("test.ext")
        # 创建 extension.py
        (sandbox_dir / "extension.py").write_text("# test", encoding="utf-8")
        assert sandbox.is_installed() is True

    def test_sandbox_load_manifest(self, sandbox_dir):
        """加载 manifest.json"""
        from pycoder.extensions.host import ExtensionSandbox

        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (sandbox_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

        sandbox = ExtensionSandbox("test.ext")
        result = sandbox.load_manifest()
        assert result is not None
        assert result["id"] == "test.ext"

    def test_sandbox_load_manifest_missing(self, sandbox_dir):
        """manifest 文件不存在返回 None"""
        from pycoder.extensions.host import ExtensionSandbox

        sandbox = ExtensionSandbox("test.ext")
        assert sandbox.load_manifest() is None

    def test_sandbox_load_manifest_corrupted(self, sandbox_dir):
        """损坏的 manifest 返回 None"""
        from pycoder.extensions.host import ExtensionSandbox

        (sandbox_dir / "manifest.json").write_text("bad json", encoding="utf-8")

        sandbox = ExtensionSandbox("test.ext")
        assert sandbox.load_manifest() is None

    def test_sandbox_manifest_path_property(self, sandbox_dir):
        """manifest_path 属性"""
        from pycoder.extensions.host import ExtensionSandbox

        sandbox = ExtensionSandbox("test.ext")
        assert sandbox.manifest_path.name == "manifest.json"

    def test_sandbox_code_path_property(self, sandbox_dir):
        """code_path 属性"""
        from pycoder.extensions.host import ExtensionSandbox

        sandbox = ExtensionSandbox("test.ext")
        assert sandbox.code_path.name == "extension.py"

    @pytest.mark.asyncio
    async def test_sandbox_activate_not_installed(self, tmp_path, monkeypatch):
        """未安装扩展激活失败"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )
        from pycoder.extensions.host import ExtensionSandbox

        sandbox = ExtensionSandbox("nonexistent.ext")
        result = await sandbox.activate()
        assert result is False

    @pytest.mark.asyncio
    async def test_sandbox_activate_no_manifest(self, sandbox_dir):
        """无 manifest 激活失败"""
        from pycoder.extensions.host import ExtensionSandbox

        sandbox = ExtensionSandbox("test.ext")
        (sandbox_dir / "extension.py").write_text("# empty", encoding="utf-8")
        result = await sandbox.activate()
        assert result is False

    @pytest.mark.asyncio
    async def test_sandbox_activate_success(self, sandbox_dir):
        """成功激活扩展"""
        from pycoder.extensions.host import ExtensionSandbox

        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (sandbox_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (sandbox_dir / "extension.py").write_text(
            'name = "Test"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )

        sandbox = ExtensionSandbox("test.ext")
        result = await sandbox.activate()
        assert result is True

    @pytest.mark.asyncio
    async def test_sandbox_activate_with_activate_func(self, sandbox_dir):
        """激活扩展时调用 activate 函数"""
        from pycoder.extensions.host import ExtensionSandbox

        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (sandbox_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (sandbox_dir / "extension.py").write_text(
            '''
name = "Test"
version = "1.0.0"
activated = False

def activate(api):
    global activated
    activated = True
    api.info("activated")
''',
            encoding="utf-8",
        )

        sandbox = ExtensionSandbox("test.ext")
        result = await sandbox.activate()
        assert result is True

    @pytest.mark.asyncio
    async def test_sandbox_deactivate(self, sandbox_dir):
        """停用扩展"""
        from pycoder.extensions.host import ExtensionSandbox

        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (sandbox_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (sandbox_dir / "extension.py").write_text(
            'name = "Test"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )

        sandbox = ExtensionSandbox("test.ext")
        await sandbox.activate()
        result = sandbox.deactivate()
        assert result is True

    @pytest.mark.asyncio
    async def test_sandbox_get_available_functions(self, sandbox_dir):
        """获取扩展的公开函数列表"""
        from pycoder.extensions.host import ExtensionSandbox

        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (sandbox_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (sandbox_dir / "extension.py").write_text(
            '''
name = "Test"
version = "1.0.0"

def my_func():
    return "hello"

def another_func(x):
    return x * 2
''',
            encoding="utf-8",
        )

        sandbox = ExtensionSandbox("test.ext")
        await sandbox.activate()
        funcs = sandbox.get_available_functions()
        assert "my_func" in funcs
        assert "another_func" in funcs
        assert "activate" not in funcs
        assert "deactivate" not in funcs

    @pytest.mark.asyncio
    async def test_sandbox_execute_function(self, sandbox_dir):
        """执行扩展函数"""
        from pycoder.extensions.host import ExtensionSandbox

        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (sandbox_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (sandbox_dir / "extension.py").write_text(
            '''
name = "Test"
version = "1.0.0"

def greet(name="World"):
    return f"Hello, {name}!"
''',
            encoding="utf-8",
        )

        sandbox = ExtensionSandbox("test.ext")
        await sandbox.activate()
        result = await sandbox.execute_function("greet", {"name": "Tester"})
        assert result["success"] is True
        assert "Hello, Tester" in str(result["result"])

    @pytest.mark.asyncio
    async def test_sandbox_execute_nonexistent_function(self, sandbox_dir):
        """执行不存在的函数"""
        from pycoder.extensions.host import ExtensionSandbox

        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (sandbox_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (sandbox_dir / "extension.py").write_text(
            'name = "Test"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )

        sandbox = ExtensionSandbox("test.ext")
        await sandbox.activate()
        result = await sandbox.execute_function("nonexistent_func")
        assert result["success"] is False
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_sandbox_execute_non_callable(self, sandbox_dir):
        """执行非可调用属性时返回其值"""
        from pycoder.extensions.host import ExtensionSandbox

        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (sandbox_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (sandbox_dir / "extension.py").write_text(
            'name = "Test"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )

        sandbox = ExtensionSandbox("test.ext")
        await sandbox.activate()
        result = await sandbox.execute_function("name")
        assert result["success"] is True
        assert result["result"] == "Test"


class TestExtensionHostManager:
    """测试扩展主机管理器"""

    @pytest.fixture
    def host(self):
        from pycoder.extensions.host import ExtensionHostManager

        return ExtensionHostManager()

    def test_get_extension_host_singleton(self):
        """get_extension_host 返回单例"""
        from pycoder.extensions.host import get_extension_host

        h1 = get_extension_host()
        h2 = get_extension_host()
        assert h1 is h2

    def test_is_activated_initially_false(self, host):
        """初始状态扩展未激活"""
        assert host.is_activated("test.ext") is False

    def test_list_activated_empty(self, host):
        """初始状态激活列表为空"""
        assert host.list_activated() == []

    def test_count_activated_zero(self, host):
        """初始状态激活计数为 0"""
        assert host.count_activated() == 0

    def test_deactivate_not_activated(self, host):
        """停用未激活的扩展返回 False"""
        assert host.deactivate_extension("nonexistent") is False

    @pytest.mark.asyncio
    async def test_activate_extension(self, host, tmp_path, monkeypatch):
        """激活扩展"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )
        ext_dir = tmp_path / "test.ext"
        ext_dir.mkdir()
        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (ext_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (ext_dir / "extension.py").write_text(
            'name = "Test"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )

        result = await host.activate_extension("test.ext")
        assert result is True
        assert host.is_activated("test.ext") is True
        assert host.count_activated() == 1

    @pytest.mark.asyncio
    async def test_activate_already_activated(self, host, tmp_path, monkeypatch):
        """重复激活返回 True"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )
        ext_dir = tmp_path / "test.ext"
        ext_dir.mkdir()
        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (ext_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (ext_dir / "extension.py").write_text(
            'name = "Test"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )

        await host.activate_extension("test.ext")
        result = await host.activate_extension("test.ext")
        assert result is True

    @pytest.mark.asyncio
    async def test_deactivate_extension(self, host, tmp_path, monkeypatch):
        """停用扩展"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )
        ext_dir = tmp_path / "test.ext"
        ext_dir.mkdir()
        manifest = {"id": "test.ext", "name": "Test", "version": "1.0.0"}
        (ext_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (ext_dir / "extension.py").write_text(
            'name = "Test"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )

        await host.activate_extension("test.ext")
        result = host.deactivate_extension("test.ext")
        assert result is True
        assert host.is_activated("test.ext") is False

    @pytest.mark.asyncio
    async def test_activate_all(self, host, tmp_path, monkeypatch):
        """激活所有已启用的扩展"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )

        for ext_id in ["ext1.test", "ext2.test"]:
            ext_dir = tmp_path / ext_id.replace("/", "_")
            ext_dir.mkdir()
            manifest = {"id": ext_id, "name": ext_id, "version": "1.0.0"}
            (ext_dir / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (ext_dir / "extension.py").write_text(
                f'name = "{ext_id}"\nversion = "1.0.0"\n',
                encoding="utf-8",
            )

        installed = [
            {"id": "ext1.test", "enabled": True},
            {"id": "ext2.test", "enabled": True},
            {"id": "ext3.test", "enabled": False},  # 禁用，不应激活
        ]
        results = await host.activate_all(installed)
        assert len(results) == 2
        assert results["ext1.test"] is True
        assert results["ext2.test"] is True
        assert host.count_activated() == 2

    @pytest.mark.asyncio
    async def test_activate_all_disabled_skipped(self, host, tmp_path, monkeypatch):
        """禁用的扩展不被激活"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )

        ext_dir = tmp_path / "ext1.test"
        ext_dir.mkdir()
        manifest = {"id": "ext1.test", "name": "ext1", "version": "1.0.0"}
        (ext_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (ext_dir / "extension.py").write_text(
            'name = "ext1"\nversion = "1.0.0"\n', encoding="utf-8"
        )

        installed = [{"id": "ext1.test", "enabled": False}]
        results = await host.activate_all(installed)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_deactivate_all(self, host, tmp_path, monkeypatch):
        """停用所有扩展"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )

        ext_dir = tmp_path / "ext1.test"
        ext_dir.mkdir()
        manifest = {"id": "ext1.test", "name": "ext1", "version": "1.0.0"}
        (ext_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (ext_dir / "extension.py").write_text(
            'name = "ext1"\nversion = "1.0.0"\n', encoding="utf-8"
        )

        await host.activate_extension("ext1.test")
        results = host.deactivate_all()
        assert results["ext1.test"] is True
        assert host.count_activated() == 0

    @pytest.mark.asyncio
    async def test_reload_extension(self, host, tmp_path, monkeypatch):
        """重新加载扩展"""
        monkeypatch.setattr(
            "pycoder.extensions.host.EXTENSIONS_DIR",
            tmp_path,
        )

        ext_dir = tmp_path / "ext1.test"
        ext_dir.mkdir()
        manifest = {"id": "ext1.test", "name": "ext1", "version": "1.0.0"}
        (ext_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (ext_dir / "extension.py").write_text(
            'name = "ext1"\nversion = "1.0.0"\n', encoding="utf-8"
        )

        await host.activate_extension("ext1.test")
        result = await host.reload_extension("ext1.test")
        assert result is True

    def test_get_sandbox(self, host):
        """获取扩展沙箱"""
        sandbox = host.get_sandbox("nonexistent")
        assert sandbox is None

    @pytest.mark.asyncio
    async def test_execute_not_activated(self, host):
        """执行未激活扩展的函数"""
        result = await host.execute("nonexistent", "func")
        assert result["success"] is False
        assert "未激活" in result["error"]

    @pytest.mark.asyncio
    async def test_activate_all_no_id_field(self, host):
        """activate_all 跳过无 id 的扩展"""
        installed = [{"enabled": True}]  # 无 id 字段
        results = await host.activate_all(installed)
        assert results == {}


# ══════════════════════════════════════════════════════════
# 第六部分: manager.py 补充测试（未覆盖部分）
# ══════════════════════════════════════════════════════════


class TestManagerAdditional:
    """ExtensionManager 补充测试"""

    @pytest.fixture
    def ext_dir(self, tmp_path, monkeypatch):
        """重定向 EXTENSIONS_DIR"""
        import pycoder.extensions.manager as mgr

        d = tmp_path / "extensions"
        d.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(mgr, "EXTENSIONS_DIR", d)
        return d

    @pytest.fixture
    def em(self, ext_dir):
        """ExtensionManager 实例"""
        import pycoder.extensions.manager as mgr

        return mgr.ExtensionManager()

    @pytest.mark.asyncio
    async def test_install_seed_metadata(self, em, ext_dir):
        """安装元数据种子扩展"""
        ext_data = {
            "name": "Meta Ext",
            "version": "2.0.0",
            "description": "A meta extension",
            "author": "tester",
            "category": "tools",
            "is_seed": True,
            "url": "",
        }
        result = await em.install("pub.meta-ext", ext_data)
        assert result is True
        target = ext_dir / "pub.meta-ext"
        assert (target / "manifest.json").exists()
        assert (target / "extension.py").exists()

        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["is_seed"] is True
        assert manifest["id"] == "pub.meta-ext"

    @pytest.mark.asyncio
    async def test_install_seed_metadata_source(self, em, ext_dir):
        """通过 source=seed 安装元数据种子扩展"""
        ext_data = {
            "name": "Seed Meta",
            "source": "seed",
            "url": "",
        }
        result = await em.install("pub.seed-meta", ext_data)
        assert result is True
        assert em.is_installed("pub.seed-meta")

    @pytest.mark.asyncio
    async def test_install_npm_extension_success(self, em, ext_dir, monkeypatch):
        """npm 扩展安装 — 通过 mock _install_npm 内部方法验证"""
        import pycoder.extensions.manager as mgr

        # 直接 mock _install_npm 方法，避免复杂的子进程模拟
        async def mock_install_npm(ext_id, ext_data):
            target = ext_dir / ext_id.replace("/", "_")
            target.mkdir(parents=True, exist_ok=True)
            ext_data["path"] = str(target)
            ext_data["installed"] = True
            ext_data["enabled"] = True
            ext_data["installed_at"] = 0
            em._installed[ext_id] = ext_data
            em._save()
            return True

        monkeypatch.setattr(em, "_install_npm", mock_install_npm)

        ext_data = {
            "name": "my-npm-pkg",
            "source": "npm",
            "url": "",
        }
        result = await em.install("pub.npm-ext", ext_data)
        assert result is True
        assert em.is_installed("pub.npm-ext")

    @pytest.mark.asyncio
    async def test_install_npm_extension_failure(self, em, ext_dir, monkeypatch):
        """npm 扩展安装失败"""
        async def mock_install_npm(ext_id, ext_data):
            return False

        monkeypatch.setattr(em, "_install_npm", mock_install_npm)

        ext_data = {
            "name": "my-npm-pkg",
            "source": "npm",
            "url": "",
        }
        result = await em.install("pub.npm-ext", ext_data)
        assert result is False

    @pytest.mark.asyncio
    async def test_install_npm_fail_nonzero(self, em, ext_dir, monkeypatch):
        """npm 安装失败（returncode != 0）"""
        import pycoder.extensions.manager as mgr

        class _MockProc:
            returncode = 1

            async def wait(self):
                return 1

            def kill(self):
                pass

        async def fake_exec(*args, **kwargs):
            return _MockProc()

        monkeypatch.setattr(mgr.asyncio, "create_subprocess_exec", fake_exec)

        ext_data = {
            "name": "fail-pkg",
            "source": "npm",
            "url": "",
        }
        result = await em.install("pub.npm-fail", ext_data)
        assert result is False

    @pytest.mark.asyncio
    async def test_install_pypi_extension_success(self, em, ext_dir, monkeypatch):
        """PyPI 扩展安装 — 通过 mock _install_pypi 内部方法验证"""
        async def mock_install_pypi(ext_id, ext_data):
            target = ext_dir / ext_id.replace("/", "_")
            target.mkdir(parents=True, exist_ok=True)
            ext_data["path"] = str(target)
            ext_data["installed"] = True
            ext_data["enabled"] = True
            ext_data["installed_at"] = 0
            em._installed[ext_id] = ext_data
            em._save()
            return True

        monkeypatch.setattr(em, "_install_pypi", mock_install_pypi)

        ext_data = {
            "name": "my-pypi-pkg",
            "source": "pypi",
            "url": "",
        }
        result = await em.install("pub.pypi-ext", ext_data)
        assert result is True
        assert em.is_installed("pub.pypi-ext")

    @pytest.mark.asyncio
    async def test_install_pypi_extension_failure(self, em, ext_dir, monkeypatch):
        """PyPI 扩展安装失败"""
        async def mock_install_pypi(ext_id, ext_data):
            return False

        monkeypatch.setattr(em, "_install_pypi", mock_install_pypi)

        ext_data = {
            "name": "fail-pypi",
            "source": "pypi",
            "url": "",
        }
        result = await em.install("pub.pypi-fail", ext_data)
        assert result is False

    @pytest.mark.asyncio
    async def test_install_pypi_fail_nonzero(self, em, ext_dir, monkeypatch):
        """PyPI 安装失败（returncode != 0）"""
        import pycoder.extensions.manager as mgr

        class _MockProc:
            returncode = 1

            async def wait(self):
                return 1

            def kill(self):
                pass

        async def fake_exec(*args, **kwargs):
            return _MockProc()

        monkeypatch.setattr(mgr.asyncio, "create_subprocess_exec", fake_exec)

        ext_data = {
            "name": "fail-pypi",
            "source": "pypi",
            "url": "",
        }
        result = await em.install("pub.pypi-fail", ext_data)
        assert result is False

    @pytest.mark.asyncio
    async def test_install_ovsx_prefix(self, em, ext_dir, monkeypatch):
        """ovsx. 前缀触发 vsix 安装 — mock _install_vsix"""
        async def mock_install_vsix(ext_id, ext_data):
            target = ext_dir / ext_id.replace("/", "_")
            target.mkdir(parents=True, exist_ok=True)
            ext_data["path"] = str(target)
            ext_data["installed"] = True
            ext_data["enabled"] = True
            ext_data["installed_at"] = 0
            em._installed[ext_id] = ext_data
            em._save()
            return True

        monkeypatch.setattr(em, "_install_vsix", mock_install_vsix)

        ext_data = {
            "name": "vsix-ext",
            "author": "publisher",
            "version": "1.0.0",
            "url": "",
        }
        result = await em.install("ovsx.vsix-ext", ext_data)
        assert result is True
        assert em.is_installed("ovsx.vsix-ext")

    @pytest.mark.asyncio
    async def test_install_vsix_download_fail(self, em, ext_dir, monkeypatch):
        """vsix 安装失败 — mock _install_vsix 返回 False"""
        async def mock_install_vsix(ext_id, ext_data):
            return False

        monkeypatch.setattr(em, "_install_vsix", mock_install_vsix)

        ext_data = {
            "name": "vsix-fail",
            "author": "pub",
            "version": "1.0.0",
            "source": "open-vsx",
            "url": "",
        }
        result = await em.install("pub.vsix-fail", ext_data)
        assert result is False

    @pytest.mark.asyncio
    async def test_install_npm_prefix(self, em, ext_dir, monkeypatch):
        """npm. 前缀触发 npm 安装"""
        import pycoder.extensions.manager as mgr

        class _MockProc:
            returncode = 0

            async def wait(self):
                return 0

            def kill(self):
                pass

        async def fake_exec(*args, **kwargs):
            return _MockProc()

        monkeypatch.setattr(mgr.asyncio, "create_subprocess_exec", fake_exec)

        ext_data = {
            "name": "npm-pkg",
            "url": "",
        }
        result = await em.install("npm.test-pkg", ext_data)
        assert result is False  # 无 tarball → False

    @pytest.mark.asyncio
    async def test_install_pypi_prefix(self, em, ext_dir, monkeypatch):
        """pypi. 前缀触发 PyPI 安装"""
        import pycoder.extensions.manager as mgr

        class _MockProc:
            returncode = 0

            async def wait(self):
                return 0

            def kill(self):
                pass

        async def fake_exec(*args, **kwargs):
            return _MockProc()

        monkeypatch.setattr(mgr.asyncio, "create_subprocess_exec", fake_exec)

        ext_data = {
            "name": "pypi-pkg",
            "url": "",
        }
        result = await em.install("pypi.test-pkg", ext_data)
        assert result is False  # 无 archive → False

    def test_scaffold_extension(self, em, ext_dir, monkeypatch):
        """scaffold_extension 调用 packaging.scaffold"""
        import pycoder.extensions.packaging as pkg

        mock_scaffold = MagicMock(return_value="/fake/path")
        monkeypatch.setattr(pkg, "scaffold", mock_scaffold)

        result = em.scaffold_extension("pub.myext", "My Ext", "desc", "author")
        mock_scaffold.assert_called_once_with("pub.myext", "My Ext", "desc", "author")
        assert result == "/fake/path"

    @pytest.mark.asyncio
    async def test_get_extension_details_not_installed(self, em):
        """未安装扩展的详情返回 None"""
        result = em.get_extension_details("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_extension_details_with_manifest(self, em, ext_dir):
        """获取已安装扩展的详情"""
        await em.install("pycoder.gitlens", {"name": "GitLens"})
        result = em.get_extension_details("pycoder.gitlens")
        assert result is not None
        assert "manifest" in result
        assert "contributions" in result
        assert "has_readme" in result
        assert "code_size" in result

    @pytest.mark.asyncio
    async def test_get_extension_details_no_manifest(self, em, ext_dir):
        """无 manifest 文件的扩展详情"""
        target = ext_dir / "test_ext"
        target.mkdir()
        (target / "extension.py").write_text("pass", encoding="utf-8")
        em._installed["test_ext"] = {
            "name": "Test",
            "path": str(target),
            "enabled": True,
        }
        em._save()

        result = em.get_extension_details("test_ext")
        assert result is not None

    def test_get_stats(self, em, ext_dir):
        """get_stats 返回统计信息"""
        stats = em.get_stats()
        assert "total_installed" in stats
        assert "enabled" in stats
        assert "disabled" in stats
        assert "activated" in stats
        assert "commands_registered" in stats
        assert "settings_registered" in stats
        assert "categories" in stats
        assert stats["total_installed"] == 0

    @pytest.mark.asyncio
    async def test_get_stats_with_extensions(self, em):
        """有扩展时的统计信息"""
        await em.install("pycoder.gitlens", {"name": "GitLens"})
        await em.install("pycoder.docker", {"name": "Docker"})
        em.disable("pycoder.docker")

        stats = em.get_stats()
        assert stats["total_installed"] == 2
        assert stats["enabled"] == 1
        assert stats["disabled"] == 1

    def test_get_config_all_without_key(self, em, ext_dir):
        """get_config 不传 key 返回全部配置"""
        em._installed["test_ext"] = {"name": "Test", "path": str(ext_dir / "test_ext")}
        em._save()

        cfg_dir = ext_dir / "test_ext"
        cfg_dir.mkdir()
        (cfg_dir / "config.json").write_text(
            json.dumps({"a": 1, "b": 2}), encoding="utf-8"
        )

        result = em.get_config("test_ext")
        assert result == {"a": 1, "b": 2}

    def test_get_config_default_for_missing_key(self, em, ext_dir):
        """get_config 对缺失 key 返回默认值"""
        em._installed["test_ext"] = {"name": "Test", "path": str(ext_dir / "test_ext")}
        em._save()

        cfg_dir = ext_dir / "test_ext"
        cfg_dir.mkdir()
        (cfg_dir / "config.json").write_text(
            json.dumps({"only": "this"}), encoding="utf-8"
        )

        result = em.get_config("test_ext", "missing", "fallback")
        assert result == "fallback"

    def test_get_config_no_file_returns_default(self, em):
        """无配置文件时返回默认值"""
        em._installed["test_ext"] = {"name": "Test"}
        result = em.get_config("test_ext", "any", "my_default")
        assert result == "my_default"

    def test_uninstall_directory_not_in_extensions_dir(self, em, ext_dir, monkeypatch):
        """卸载路径不在扩展目录内时安全跳过"""
        fake_rmtree_calls = []

        def fake_rmtree(p):
            fake_rmtree_calls.append(str(p))

        monkeypatch.setattr("pycoder.extensions.manager.shutil.rmtree", fake_rmtree)

        # 路径指向 ext_dir 之外
        outside_path = str(Path.home() / "outside")
        em._installed["test_ext"] = {"name": "Test", "path": outside_path}
        result = em.uninstall("test_ext")
        assert result is True
        assert "test_ext" not in em._installed
        # rmtree 不应被调用（路径不在 EXTENSIONS_DIR 内）
        assert len(fake_rmtree_calls) == 0

    @pytest.mark.asyncio
    async def test_install_github_clone_timeout(self, em, ext_dir, monkeypatch):
        """git clone 超时返回 False"""
        import pycoder.extensions.manager as mgr

        class _TimeoutProc:
            def __init__(self):
                self._call_count = 0

            @property
            def returncode(self):
                return 0

            async def wait(self):
                self._call_count += 1
                if self._call_count == 1:
                    raise asyncio.TimeoutError()
                return 0

            def kill(self):
                pass

        async def fake_exec(*args, **kwargs):
            return _TimeoutProc()

        monkeypatch.setattr(mgr.asyncio, "create_subprocess_exec", fake_exec)

        ext_data = {
            "name": "TimeoutExt",
            "url": "https://github.com/user/timeout",
        }
        result = await em.install("user/timeout", ext_data)
        assert result is False

    @pytest.mark.asyncio
    async def test_install_npm_timeout(self, em, ext_dir, monkeypatch):
        """npm pack 超时"""
        import pycoder.extensions.manager as mgr

        class _TimeoutProc:
            def __init__(self):
                self._call_count = 0

            @property
            def returncode(self):
                return 0

            async def wait(self):
                self._call_count += 1
                if self._call_count == 1:
                    raise asyncio.TimeoutError()
                return 0

            def kill(self):
                pass

        async def fake_exec(*args, **kwargs):
            return _TimeoutProc()

        monkeypatch.setattr(mgr.asyncio, "create_subprocess_exec", fake_exec)

        ext_data = {
            "name": "npm-timeout",
            "source": "npm",
            "url": "",
        }
        result = await em.install("pub.npm-timeout", ext_data)
        assert result is False

    @pytest.mark.asyncio
    async def test_install_pypi_timeout(self, em, ext_dir, monkeypatch):
        """pip download 超时"""
        import pycoder.extensions.manager as mgr

        class _TimeoutProc:
            def __init__(self):
                self._call_count = 0

            @property
            def returncode(self):
                return 0

            async def wait(self):
                self._call_count += 1
                if self._call_count == 1:
                    raise asyncio.TimeoutError()
                return 0

            def kill(self):
                pass

        async def fake_exec(*args, **kwargs):
            return _TimeoutProc()

        monkeypatch.setattr(mgr.asyncio, "create_subprocess_exec", fake_exec)

        ext_data = {
            "name": "pypi-timeout",
            "source": "pypi",
            "url": "",
        }
        result = await em.install("pub.pypi-timeout", ext_data)
        assert result is False

    def test__safe_extract_archive_tar(self, tmp_path):
        """安全解压 tar 归档"""
        import tarfile
        import io

        from pycoder.extensions.manager import _safe_extract_archive

        target = tmp_path / "safe_extract"
        target.mkdir()

        # 创建合法 tar
        tar_path = tmp_path / "test.tar"
        with tarfile.open(tar_path, "w") as tf:
            info = tarfile.TarInfo(name="good_file.txt")
            info.size = 5
            tf.addfile(info, io.BytesIO(b"hello"))

        with tarfile.open(tar_path, "r") as tf:
            _safe_extract_archive(tf, target, fmt="tar")

        assert (target / "good_file.txt").exists()

    def test__safe_extract_archive_tar_path_traversal(self, tmp_path):
        """检测 tar 路径穿越攻击"""
        import tarfile
        import io

        from pycoder.extensions.manager import _safe_extract_archive

        target = tmp_path / "safe_extract"
        target.mkdir()

        # 创建含路径穿越的 tar
        tar_path = tmp_path / "bad.tar"
        content = b"evil!"
        with tarfile.open(tar_path, "w") as tf:
            info = tarfile.TarInfo(name="../evil.txt")
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))

        with tarfile.open(tar_path, "r") as tf:
            with pytest.raises(ValueError, match="路径穿越"):
                _safe_extract_archive(tf, target, fmt="tar")

    def test__safe_extract_archive_zip(self, tmp_path):
        """安全解压 zip 归档"""
        import zipfile
        import io

        from pycoder.extensions.manager import _safe_extract_archive

        target = tmp_path / "safe_zip"
        target.mkdir()

        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("good_file.txt", "hello")

        with zipfile.ZipFile(zip_path, "r") as zf:
            _safe_extract_archive(zf, target, fmt="zip")

        assert (target / "good_file.txt").exists()

    def test__safe_extract_archive_zip_path_traversal(self, tmp_path):
        """检测 zip 路径穿越攻击"""
        import zipfile

        from pycoder.extensions.manager import _safe_extract_archive

        target = tmp_path / "safe_zip"
        target.mkdir()

        zip_path = tmp_path / "bad.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../evil.txt", "evil")

        with zipfile.ZipFile(zip_path, "r") as zf:
            with pytest.raises(ValueError, match="路径穿越"):
                _safe_extract_archive(zf, target, fmt="zip")

    def test__safe_extract_archive_zip_absolute_path(self, tmp_path):
        """检测 zip 绝对路径穿越攻击"""
        import zipfile

        from pycoder.extensions.manager import _safe_extract_archive

        target = tmp_path / "safe_zip"
        target.mkdir()

        zip_path = tmp_path / "bad_abs.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("C:/windows/system32/evil.txt", "evil")

        with zipfile.ZipFile(zip_path, "r") as zf:
            with pytest.raises(ValueError, match="路径穿越"):
                _safe_extract_archive(zf, target, fmt="zip")