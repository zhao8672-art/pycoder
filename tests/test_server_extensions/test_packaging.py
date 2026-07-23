from __future__ import annotations

import json
import os
import sys
import time
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


