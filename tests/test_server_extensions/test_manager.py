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