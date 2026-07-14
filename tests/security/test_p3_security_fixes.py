"""P3-0: CRITICAL 安全修复验证测试

验证 4 个 CRITICAL 安全问题已修复：
- C1: 沙箱 __import__ 逃逸
- C2: WebSocket 认证绕过
- C3: 密码时序攻击
- C4: API Key 日志泄露
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class TestSandboxNoImportBuiltin:
    """C1: 沙箱 _safe_builtins 不应包含 __import__"""

    def test_safe_builtins_no_import(self):
        """_SANDBOX_RUNNER 字符串中不应包含 '__import__': __import__"""
        sandbox_path = PROJECT_ROOT / "pycoder" / "server" / "routers" / "code_exec.py"
        content = sandbox_path.read_text(encoding="utf-8")
        # 提取 _SANDBOX_RUNNER 定义部分
        assert "'__import__': __import__" not in content, (
            "_safe_builtins 仍包含 __import__，沙箱可逃逸导致 RCE"
        )

    def test_sandbox_runner_imports_before_builtins(self):
        """沙箱 runner 的 import 应在 _safe_builtins 定义之前执行，
        确保模块可用但不暴露给用户代码"""
        sandbox_path = PROJECT_ROOT / "pycoder" / "routers" / "code_exec.py"
        if not sandbox_path.exists():
            sandbox_path = PROJECT_ROOT / "pycoder" / "server" / "routers" / "code_exec.py"
        content = sandbox_path.read_text(encoding="utf-8")
        # 验证 _SANDBOX_RUNNER 开头有 import 语句
        runner_start = content.find("_SANDBOX_RUNNER =")
        assert runner_start != -1
        runner_section = content[runner_start:runner_start + 500]
        assert "import sys" in runner_section


class TestWebSocketAuth:
    """C2: WebSocket 端点认证校验"""

    @pytest.mark.asyncio
    async def test_verify_ws_auth_rejects_missing_key(self):
        """未提供 API Key 时应拒绝连接"""
        from pycoder.server.app import verify_ws_auth

        mock_ws = AsyncMock()
        mock_ws.query_params = {}
        mock_ws.headers = {}

        with patch("pycoder.server.app._API_KEY", "test-secret-key"):
            result = await verify_ws_auth(mock_ws)

        assert result is False
        mock_ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_ws_auth_rejects_wrong_key(self):
        """错误的 API Key 应拒绝连接"""
        from pycoder.server.app import verify_ws_auth

        mock_ws = AsyncMock()
        mock_ws.query_params = {"api_key": "wrong-key"}
        mock_ws.headers = {}

        with patch("pycoder.server.app._API_KEY", "correct-key"):
            result = await verify_ws_auth(mock_ws)

        assert result is False
        mock_ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_ws_auth_accepts_correct_query_key(self):
        """正确的 query 参数 api_key 应通过"""
        from pycoder.server.app import verify_ws_auth

        mock_ws = AsyncMock()
        mock_ws.query_params = {"api_key": "correct-key"}
        mock_ws.headers = {}

        with patch("pycoder.server.app._API_KEY", "correct-key"):
            result = await verify_ws_auth(mock_ws)

        assert result is True
        mock_ws.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_verify_ws_auth_accepts_correct_header_key(self):
        """正确的 X-API-Key 头应通过"""
        from pycoder.server.app import verify_ws_auth

        mock_ws = AsyncMock()
        mock_ws.query_params = {}
        mock_ws.headers = {"x-api-key": "correct-key"}

        with patch("pycoder.server.app._API_KEY", "correct-key"):
            result = await verify_ws_auth(mock_ws)

        assert result is True

    @pytest.mark.asyncio
    async def test_verify_ws_auth_passes_when_auth_disabled(self):
        """认证关闭时（_API_KEY 为空）应直接放行"""
        from pycoder.server.app import verify_ws_auth

        mock_ws = AsyncMock()
        mock_ws.query_params = {}
        mock_ws.headers = {}

        with patch("pycoder.server.app._API_KEY", ""):
            result = await verify_ws_auth(mock_ws)

        assert result is True
        mock_ws.close.assert_not_called()

    def test_all_ws_endpoints_have_auth_check(self):
        """所有 WebSocket 端点都应调用 verify_ws_auth"""
        ws_files = [
            "pycoder/server/app.py",
            "pycoder/server/routers/terminal.py",
            "pycoder/server/routers/autonomous_api.py",
            "pycoder/server/routers/advanced_api.py",
            "pycoder/server/routers/v2/evolution.py",
            "pycoder/server/routers/team_api.py",
        ]
        for f in ws_files:
            path = PROJECT_ROOT / f
            content = path.read_text(encoding="utf-8")
            assert "verify_ws_auth" in content, (
                f"{f} 中的 WebSocket 端点未调用 verify_ws_auth"
            )


class TestPasswordTimingSafe:
    """C3: 密码验证使用 hmac.compare_digest"""

    def test_verify_password_uses_compare_digest(self):
        """verify_password 应使用 hmac.compare_digest 而非 =="""
        auth_path = PROJECT_ROOT / "pycoder" / "server" / "auth" / "cloud_auth.py"
        content = auth_path.read_text(encoding="utf-8")
        # 提取 verify_password 函数体
        func_start = content.find("def verify_password")
        assert func_start != -1
        func_body = content[func_start:func_start + 500]
        assert "compare_digest" in func_body, (
            "verify_password 应使用 hmac.compare_digest 防止时序攻击"
        )
        assert "new_key == original_key" not in func_body, (
            "verify_password 不应使用 == 比较密码"
        )

    def test_verify_password_correct(self):
        """正确密码应验证通过"""
        from pycoder.server.auth.cloud_auth import hash_password, verify_password

        hashed = hash_password("test-password-123")
        assert verify_password("test-password-123", hashed) is True

    def test_verify_password_wrong(self):
        """错误密码应验证失败"""
        from pycoder.server.auth.cloud_auth import hash_password, verify_password

        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_verify_password_invalid_hash(self):
        """无效哈希应返回 False 而非抛异常"""
        from pycoder.server.auth.cloud_auth import verify_password

        assert verify_password("any", "not-valid-base64!!!") is False


class TestAPIKeyLogMasking:
    """C4: API Key 不应明文写入日志"""

    def test_auto_generated_key_not_logged_plaintext(self):
        """自动生成的 API Key 不应在日志中明文出现"""
        app_path = PROJECT_ROOT / "pycoder" / "server" / "app.py"
        content = app_path.read_text(encoding="utf-8")
        # 查找自动生成 key 的日志语句
        auto_gen_start = content.find("已自动生成临时 API Key")
        assert auto_gen_start != -1
        log_section = content[auto_gen_start - 200:auto_gen_start + 200]
        # 不应直接用 _API_KEY 作为日志参数
        assert "_masked" in log_section, "日志应使用脱敏后的 _masked 而非 _API_KEY"

    def test_api_key_written_to_file(self):
        """完整密钥应写入 ~/.pycoder/.api_key 文件"""
        app_path = PROJECT_ROOT / "pycoder" / "server" / "app.py"
        content = app_path.read_text(encoding="utf-8")
        assert ".api_key" in content, "应将完整 API Key 写入 ~/.pycoder/.api_key"
