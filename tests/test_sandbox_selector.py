"""P1-4: 沙箱选择器 + Docker 沙箱 测试"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def reset_selector():
    """每个测试前重置全局选择器"""
    from pycoder.adapters.sandbox_selector import (
        invalidate_docker_cache,
        reset_selector,
    )

    reset_selector()
    invalidate_docker_cache()
    # 清理环境变量
    for k in ["PYCODER_SANDBOX", "PYCODER_DOCKER_IMAGE", "PYCODER_DOCKER_REQUIRED"]:
        os.environ.pop(k, None)
    yield
    reset_selector()
    invalidate_docker_cache()


async def test_selector_auto_fallback_when_no_docker():
    """auto 模式下无 Docker 应回退到 subprocess"""
    from pycoder.adapters.sandbox_selector import SandboxSelector

    selector = SandboxSelector()
    with patch(
        "pycoder.adapters.sandbox_selector.check_docker_available",
        new=AsyncMock(return_value=(False, "docker CLI 未安装")),
    ):
        info = await selector.select(force_check=True)
    assert info.backend == "subprocess"
    assert info.docker_available is False


async def test_selector_auto_uses_docker_when_available():
    """auto 模式下有 Docker 应使用 docker"""
    from pycoder.adapters.sandbox_selector import SandboxSelector

    selector = SandboxSelector()
    with patch(
        "pycoder.adapters.sandbox_selector.check_docker_available",
        new=AsyncMock(return_value=(True, "OK")),
    ):
        info = await selector.select(force_check=True)
    assert info.backend == "docker"


async def test_selector_force_subprocess():
    """强制 subprocess 配置"""
    from pycoder.adapters.sandbox_selector import SandboxSelector

    selector = SandboxSelector(prefer="subprocess")
    with patch(
        "pycoder.adapters.sandbox_selector.check_docker_available",
        new=AsyncMock(return_value=(True, "OK")),  # 即便 Docker 可用
    ):
        info = await selector.select(force_check=True)
    assert info.backend == "subprocess"


async def test_selector_docker_required_raises():
    """强制 docker 且 required=true 但不可用时应抛错"""
    from pycoder.adapters.sandbox_selector import SandboxSelector

    selector = SandboxSelector(prefer="docker", docker_required=True)
    with patch(
        "pycoder.adapters.sandbox_selector.check_docker_available",
        new=AsyncMock(return_value=(False, "未安装")),
    ):
        with pytest.raises(RuntimeError):
            await selector.select(force_check=True)


async def test_check_docker_no_cli(monkeypatch):
    """无 docker CLI 时应返回 (False, ...)"""
    from pycoder.adapters import sandbox_selector

    monkeypatch.setattr(sandbox_selector.shutil, "which", lambda _: None)
    sandbox_selector.invalidate_docker_cache()
    available, reason = await sandbox_selector.check_docker_available()
    assert available is False
    assert "未安装" in reason or "CLI" in reason


async def test_check_docker_daemon_unreachable(monkeypatch):
    """docker CLI 存在但 daemon 不可达"""
    from pycoder.adapters import sandbox_selector

    monkeypatch.setattr(sandbox_selector.shutil, "which", lambda _: "/usr/bin/docker")
    sandbox_selector.invalidate_docker_cache()

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(
        return_value=(b"", b"Cannot connect to Docker daemon")
    )
    mock_proc.returncode = 1

    async def fake_exec(*args, **kwargs):
        return mock_proc

    monkeypatch.setattr(
        sandbox_selector.asyncio, "create_subprocess_exec", fake_exec
    )
    available, reason = await sandbox_selector.check_docker_available()
    assert available is False
    assert "daemon" in reason or "不可用" in reason


async def test_check_docker_success(monkeypatch):
    """docker info 成功时返回 True"""
    from pycoder.adapters import sandbox_selector

    monkeypatch.setattr(sandbox_selector.shutil, "which", lambda _: "/usr/bin/docker")
    sandbox_selector.invalidate_docker_cache()

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"Server Version: 24.0", b""))
    mock_proc.returncode = 0

    async def fake_exec(*args, **kwargs):
        return mock_proc

    monkeypatch.setattr(
        sandbox_selector.asyncio, "create_subprocess_exec", fake_exec
    )
    available, _reason = await sandbox_selector.check_docker_available()
    assert available is True


def test_sandbox_info_dataclass():
    """SandboxInfo 数据类字段完整"""
    from pycoder.adapters.sandbox_selector import SandboxInfo

    info = SandboxInfo(
        backend="docker",
        docker_available=True,
        reason="OK",
        image="python:3.12-slim",
    )
    assert info.backend == "docker"
    assert info.image == "python:3.12-slim"
    d = {
        "backend": info.backend,
        "docker_available": info.docker_available,
        "reason": info.reason,
        "image": info.image,
    }
    assert d["backend"] == "docker"


def test_selector_env_var_prefer(monkeypatch):
    """PYCODER_SANDBOX=subprocess 环境变量应被读取"""
    monkeypatch.setenv("PYCODER_SANDBOX", "subprocess")
    from pycoder.adapters.sandbox_selector import SandboxSelector

    selector = SandboxSelector()
    assert selector._prefer == "subprocess"


def test_selector_env_var_image(monkeypatch):
    """PYCODER_DOCKER_IMAGE 环境变量"""
    monkeypatch.setenv("PYCODER_DOCKER_IMAGE", "python:3.11-slim")
    from pycoder.adapters.sandbox_selector import SandboxSelector

    selector = SandboxSelector()
    assert selector._docker_image == "python:3.11-slim"


def test_selector_reset_clears_cache():
    """reset 后缓存应清空"""
    from pycoder.adapters.sandbox_selector import SandboxInfo, SandboxSelector

    selector = SandboxSelector()
    selector._cached_info = SandboxInfo(
        backend="docker", docker_available=True, reason="cached"
    )
    selector.reset()
    assert selector._cached_info is None
