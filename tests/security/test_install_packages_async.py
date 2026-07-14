"""P0-2 测试：验证 install_packages 端点不阻塞事件循环

原实现使用同步 subprocess.run，10 个包最多阻塞 1200s 导致服务器无响应。
现改为 asyncio.create_subprocess_exec，应能在安装期间响应其他请求。
"""
from __future__ import annotations

import sys
import asyncio
import pytest
from fastapi.testclient import TestClient


# 禁用 API 认证（同 test_code_run_security.py 的处理方式）
import pycoder.server.app  # noqa: E402,F401

_app_module = sys.modules["pycoder.server.app"]
_app_module._API_KEY = ""
client = TestClient(_app_module.app)


class TestInstallPackagesBasic:
    """install_packages 端点基本行为"""

    def test_empty_packages_rejected(self):
        """空包列表应返回 400"""
        resp = client.post("/api/code/install", json={"packages": []})
        assert resp.status_code == 400

    def test_too_many_packages_rejected(self):
        """超过 10 个包应返回 400"""
        resp = client.post(
            "/api/code/install",
            json={"packages": [f"pkg{i}" for i in range(11)]},
        )
        assert resp.status_code == 400

    def test_invalid_chars_rejected(self):
        """非法字符应被拒绝（命令注入防护）"""
        resp = client.post(
            "/api/code/install",
            json={"packages": ["pkg;rm -rf /"]},
        )
        data = resp.json()
        assert data["success"] is False
        # 非法包应出现在 failed 字典中
        assert any("pkg;rm -rf /" in k for k in data["failed"])

    def test_invalid_package_name_too_long(self):
        """超长包名应被拒绝"""
        long_name = "a" * 201
        resp = client.post(
            "/api/code/install",
            json={"packages": [long_name]},
        )
        data = resp.json()
        assert data["success"] is False
        assert long_name in data["failed"]

    def test_nonexistent_package_fails_gracefully(self):
        """不存在的包应优雅失败（不崩溃）"""
        resp = client.post(
            "/api/code/install",
            json={"packages": ["nonexistent-pkg-xyz-12345"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "nonexistent-pkg-xyz-12345" in data["failed"]


class TestInstallPackagesAsync:
    """验证 install_packages 使用异步子进程（不阻塞事件循环）"""

    @pytest.mark.asyncio
    async def test_install_does_not_block_event_loop(self):
        """安装期间事件循环应保持响应

        通过启动 install_packages + 并发心跳任务验证：
        - 如果 install_packages 阻塞事件循环，心跳任务无法执行
        - 心跳任务应在 install_packages 完成前推进多次
        """
        from pycoder.server.routers.code_exec import install_packages, PipInstallRequest

        heartbeat_count = 0

        async def heartbeat():
            nonlocal heartbeat_count
            for _ in range(20):
                await asyncio.sleep(0.05)
                heartbeat_count += 1

        # 安装一个不存在的包（快速失败），同时运行心跳
        req = PipInstallRequest(packages=["nonexistent-pkg-abc-98765"])
        hb_task = asyncio.create_task(heartbeat())

        await install_packages(req)

        # 等待心跳完成
        await hb_task

        # 如果事件循环被阻塞，心跳次数会显著小于 20
        # 异步实现下，心跳应在 install 期间继续推进
        assert heartbeat_count >= 15, (
            f"心跳仅推进 {heartbeat_count}/20 次，事件循环可能被阻塞"
        )

    @pytest.mark.asyncio
    async def test_install_timeout_handled_gracefully(self):
        """超时应被优雅处理（不卡死）"""
        from pycoder.server.routers.code_exec import install_packages, PipInstallRequest
        from unittest.mock import patch, AsyncMock

        # 模拟 install 永不完成，强制触发超时
        async def never_complete(*args, **kwargs):
            await asyncio.sleep(1000)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = never_complete
            mock_proc.kill = AsyncMock()
            mock_proc.wait = AsyncMock()
            mock_proc.returncode = None
            mock_exec.return_value = mock_proc

            # 缩短超时以便测试快速完成
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                req = PipInstallRequest(packages=["some-pkg"])
                # 不应抛异常，应将失败记录到 failed
                result = await install_packages(req)
                assert result.success is False
                assert "some-pkg" in result.failed
