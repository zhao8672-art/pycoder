"""env_checker 模块覆盖率测试 — 环境能力检测器

覆盖 pycoder.server.env_checker:
- EnvCapability / EnvCapabilities 数据类
- EnvChecker: has / get_capabilities / _check_binary / _check_docker / _check_docker_compose
- get_env_checker 单例

测试策略：mock shutil.which 与 subprocess.run，避免触发真实命令执行。
"""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

import pycoder.server.env_checker as env_mod
from pycoder.server.env_checker import (
    EnvCapability,
    EnvCapabilities,
    EnvChecker,
    get_env_checker,
)


# ══════════════════════════════════════════════════════════
# EnvCapability
# ══════════════════════════════════════════════════════════


class TestEnvCapability:
    def test_defaults(self):
        cap = EnvCapability(name="test")
        assert cap.name == "test"
        assert cap.available is False
        assert cap.version == ""
        assert cap.error == ""
        assert cap.checked_at == 0.0
        assert cap.hint == ""

    def test_with_values(self):
        cap = EnvCapability(
            name="x", available=True, version="1.0", error="", hint="ok"
        )
        assert cap.available is True
        assert cap.version == "1.0"


# ══════════════════════════════════════════════════════════
# EnvCapabilities
# ══════════════════════════════════════════════════════════


class TestEnvCapabilities:
    def test_defaults(self):
        caps = EnvCapabilities()
        assert caps.docker.name == "docker"
        assert caps.kubectl.name == "kubectl"
        assert caps.alembic.name == "alembic"
        assert caps.node.name == "node"
        assert caps.git.name == "git"
        assert caps.make.name == "make"
        assert caps.curl.name == "curl"
        assert caps.docker_compose.name == "docker_compose"

    def test_to_dict(self):
        caps = EnvCapabilities()
        caps.docker.available = True
        caps.docker.version = "20.0"
        caps.git.hint = "install me"
        d = caps.to_dict()
        assert "docker" in d
        assert d["docker"]["available"] is True
        assert d["docker"]["version"] == "20.0"
        assert "git" in d
        assert d["git"]["hint"] == "install me"

    def test_to_dict_excludes_non_capability_attrs(self):
        """to_dict 只包含 EnvCapability 类型的属性"""
        caps = EnvCapabilities()
        caps.custom_attr = "not a capability"  # type: ignore[attr-defined]
        d = caps.to_dict()
        assert "custom_attr" not in d

    def test_summary(self):
        caps = EnvCapabilities()
        caps.git.available = True
        caps.git.version = "2.30"
        s = caps.summary()
        assert isinstance(s, list)
        names = [item["name"] for item in s]
        assert "git" in names
        assert "docker" in names
        assert "kubectl" in names
        git_item = next(i for i in s if i["name"] == "git")
        assert git_item["available"] is True
        assert git_item["version"] == "2.30"

    def test_summary_count(self):
        caps = EnvCapabilities()
        s = caps.summary()
        # 8 个能力
        assert len(s) == 8


# ══════════════════════════════════════════════════════════
# _check_binary
# ══════════════════════════════════════════════════════════


class TestCheckBinary:
    def test_not_found(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: None)
        cap = checker._check_binary("foo")
        assert cap.available is False
        assert "未找到" in cap.hint

    def test_success(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: "/usr/bin/foo")
        mock_proc = MagicMock(returncode=0, stdout="foo 1.0\n", stderr="")
        monkeypatch.setattr(env_mod.subprocess, "run", lambda *a, **k: mock_proc)
        cap = checker._check_binary("foo")
        assert cap.available is True
        assert cap.version == "foo 1.0"

    def test_failure_returncode(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: "/usr/bin/foo")
        mock_proc = MagicMock(returncode=1, stdout="", stderr="error\n")
        monkeypatch.setattr(env_mod.subprocess, "run", lambda *a, **k: mock_proc)
        cap = checker._check_binary("foo")
        assert cap.available is False
        assert "执行失败" in cap.hint
        assert "error" in cap.error

    def test_timeout(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: "/usr/bin/foo")

        def raise_timeout(*a, **k):
            raise subprocess.TimeoutExpired(cmd="foo", timeout=5)

        monkeypatch.setattr(env_mod.subprocess, "run", raise_timeout)
        cap = checker._check_binary("foo")
        assert cap.available is False
        assert "超时" in cap.hint

    def test_filenotfound(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: "/usr/bin/foo")

        def raise_fnf(*a, **k):
            raise FileNotFoundError()

        monkeypatch.setattr(env_mod.subprocess, "run", raise_fnf)
        cap = checker._check_binary("foo")
        assert cap.available is False
        assert "未找到" in cap.hint

    def test_general_exception(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: "/usr/bin/foo")

        def raise_exc(*a, **k):
            raise ValueError("oops")

        monkeypatch.setattr(env_mod.subprocess, "run", raise_exc)
        cap = checker._check_binary("foo")
        assert cap.available is False
        assert "oops" in cap.error

    def test_custom_version_flag(self, monkeypatch):
        """显式 version_flag 参数"""
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: "/usr/bin/foo")
        captured: dict = {}
        mock_proc = MagicMock(returncode=0, stdout="1.0\n", stderr="")

        def fake_run(args, **kwargs):
            captured["args"] = args
            return mock_proc

        monkeypatch.setattr(env_mod.subprocess, "run", fake_run)
        cap = checker._check_binary("foo", "--version")
        assert cap.available is True
        assert captured["args"] == ["foo", "--version"]


# ══════════════════════════════════════════════════════════
# _check_docker
# ══════════════════════════════════════════════════════════


class TestCheckDocker:
    def test_not_installed(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: None)
        cap = checker._check_docker()
        assert cap.available is False
        assert "Docker 未安装" in cap.hint

    def test_success(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: "/usr/bin/docker")
        mock_proc = MagicMock(returncode=0, stdout="20.0\n", stderr="")
        monkeypatch.setattr(env_mod.subprocess, "run", lambda *a, **k: mock_proc)
        cap = checker._check_docker()
        assert cap.available is True
        assert "Docker 20.0" in cap.version

    def test_daemon_not_running(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: "/usr/bin/docker")
        mock_proc = MagicMock(returncode=1, stdout="", stderr="error")
        monkeypatch.setattr(env_mod.subprocess, "run", lambda *a, **k: mock_proc)
        cap = checker._check_docker()
        assert cap.available is False
        assert "daemon 未运行" in cap.hint

    def test_empty_output_treated_as_unavailable(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: "/usr/bin/docker")
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(env_mod.subprocess, "run", lambda *a, **k: mock_proc)
        cap = checker._check_docker()
        assert cap.available is False

    def test_timeout(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: "/usr/bin/docker")

        def raise_timeout(*a, **k):
            raise subprocess.TimeoutExpired(cmd="docker", timeout=5)

        monkeypatch.setattr(env_mod.subprocess, "run", raise_timeout)
        cap = checker._check_docker()
        assert cap.available is False
        assert "超时" in cap.hint

    def test_general_exception(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: "/usr/bin/docker")

        def raise_exc(*a, **k):
            raise OSError("permission denied")

        monkeypatch.setattr(env_mod.subprocess, "run", raise_exc)
        cap = checker._check_docker()
        assert cap.available is False
        assert "permission denied" in cap.hint


# ══════════════════════════════════════════════════════════
# _check_docker_compose
# ══════════════════════════════════════════════════════════


class TestCheckDockerCompose:
    def test_no_docker(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: None)
        cap = checker._check_docker_compose()
        assert cap.available is False
        assert "Docker 未安装" in cap.hint

    def test_success(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(
            env_mod.shutil,
            "which",
            lambda name: "/usr/bin/docker" if name == "docker" else None,
        )
        mock_proc = MagicMock(returncode=0, stdout="Docker Compose v2\n", stderr="")
        monkeypatch.setattr(env_mod.subprocess, "run", lambda *a, **k: mock_proc)
        cap = checker._check_docker_compose()
        assert cap.available is True
        assert "Compose" in cap.version

    def test_failure(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(
            env_mod.shutil,
            "which",
            lambda name: "/usr/bin/docker" if name == "docker" else None,
        )
        mock_proc = MagicMock(returncode=1, stdout="", stderr="")
        monkeypatch.setattr(env_mod.subprocess, "run", lambda *a, **k: mock_proc)
        cap = checker._check_docker_compose()
        assert cap.available is False
        assert "Compose" in cap.hint

    def test_empty_output(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(
            env_mod.shutil,
            "which",
            lambda name: "/usr/bin/docker" if name == "docker" else None,
        )
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(env_mod.subprocess, "run", lambda *a, **k: mock_proc)
        cap = checker._check_docker_compose()
        assert cap.available is False

    def test_exception(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(
            env_mod.shutil,
            "which",
            lambda name: "/usr/bin/docker" if name == "docker" else None,
        )

        def raise_exc(*a, **k):
            raise OSError("oops")

        monkeypatch.setattr(env_mod.subprocess, "run", raise_exc)
        cap = checker._check_docker_compose()
        assert cap.available is False
        assert "Compose" in cap.hint


# ══════════════════════════════════════════════════════════
# get_capabilities
# ══════════════════════════════════════════════════════════


class TestGetCapabilities:
    def test_first_call_populates_cache(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: None)
        caps = checker.get_capabilities()
        assert isinstance(caps, EnvCapabilities)
        assert checker._cache is not None
        assert checker._last_checked > 0

    def test_cache_hit(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: None)
        caps1 = checker.get_capabilities()
        # 修改缓存以验证第二次调用返回缓存
        caps1.docker.available = True
        caps2 = checker.get_capabilities()
        assert caps2.docker.available is True
        assert caps2 is caps1

    def test_force_refresh(self, monkeypatch):
        checker = EnvChecker()
        # 第一次：docker 不可用
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: None)
        caps1 = checker.get_capabilities()
        assert caps1.docker.available is False
        # 修改 which 返回 docker 可用
        monkeypatch.setattr(
            env_mod.shutil,
            "which",
            lambda name: "/usr/bin/docker" if name == "docker" else None,
        )
        mock_proc = MagicMock(returncode=0, stdout="20.0\n", stderr="")
        monkeypatch.setattr(env_mod.subprocess, "run", lambda *a, **k: mock_proc)
        # 强制刷新
        caps2 = checker.get_capabilities(force=True)
        assert caps2.docker.available is True

    def test_kubectl_hint_added_when_unavailable(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: None)
        caps = checker.get_capabilities()
        assert "kubectl" in caps.kubectl.hint

    def test_alembic_hint_added_when_unavailable(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: None)
        caps = checker.get_capabilities()
        assert "alembic" in caps.alembic.hint

    def test_checks_all_capabilities(self, monkeypatch):
        """get_capabilities 应填充所有 8 个能力字段"""
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: None)
        caps = checker.get_capabilities()
        # 所有能力都应被检测（虽然都不可用）
        assert caps.docker.name == "docker"
        assert caps.docker_compose.name == "docker_compose"
        assert caps.kubectl.name == "kubectl"
        assert caps.alembic.name == "alembic"
        assert caps.node.name == "node"
        assert caps.git.name == "git"
        assert caps.make.name == "make"
        assert caps.curl.name == "curl"


# ══════════════════════════════════════════════════════════
# has
# ══════════════════════════════════════════════════════════


class TestHas:
    def test_has_existing_capability(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: None)
        assert checker.has("docker") is False

    def test_has_nonexistent_capability_returns_false(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(env_mod.shutil, "which", lambda name: None)
        # 不存在的能力名应返回 False（不抛异常）
        assert checker.has("nonexistent") is False

    def test_has_returns_true_when_available(self, monkeypatch):
        checker = EnvChecker()
        monkeypatch.setattr(
            env_mod.shutil,
            "which",
            lambda name: "/usr/bin/docker" if name == "docker" else None,
        )
        mock_proc = MagicMock(returncode=0, stdout="20.0\n", stderr="")
        monkeypatch.setattr(env_mod.subprocess, "run", lambda *a, **k: mock_proc)
        assert checker.has("docker") is True


# ══════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════


class TestSingleton:
    def test_get_env_checker_singleton(self, monkeypatch):
        monkeypatch.setattr(env_mod, "_checker", None)
        c1 = get_env_checker()
        c2 = get_env_checker()
        assert c1 is c2

    def test_get_env_checker_returns_env_checker(self, monkeypatch):
        monkeypatch.setattr(env_mod, "_checker", None)
        assert isinstance(get_env_checker(), EnvChecker)
