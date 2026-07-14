"""P0-1 安全测试：验证 /api/code/run 的沙箱隔离

确保用户提交的代码无法：
- 导入危险模块（os、subprocess、socket 等）
- 使用 __import__、exec、eval、compile 等危险内置函数
- 通过子类遍历绕过限制
- 访问主进程变量
- 通过死循环耗尽资源
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# 模块级禁用 API 认证（在 P0-4 实施前，'disabled' 字符串会被当作有效 API Key，
# 因此直接覆盖模块变量 _API_KEY = ""，让中间件 dispatch 跳过认证逻辑）
import sys  # noqa: E402
import pycoder.server.app  # noqa: E402,F401  触发导入

_app_module = sys.modules["pycoder.server.app"]
_app_module._API_KEY = ""
client = TestClient(_app_module.app)


class TestCodeRunSandbox:
    """验证 /api/code/run 的沙箱隔离"""

    def test_safe_code_runs(self):
        """安全代码应正常执行"""
        resp = client.post("/api/code/run", json={"code": "print(1 + 1)"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "2" in data["stdout"]

    def test_empty_code_rejected(self):
        """空代码应返回 400"""
        resp = client.post("/api/code/run", json={"code": ""})
        assert resp.status_code == 400

    def test_dangerous_import_os_blocked(self):
        """os 模块应被禁止"""
        resp = client.post(
            "/api/code/run",
            json={"code": "import os\nprint(os.listdir('/'))"},
        )
        data = resp.json()
        assert data["success"] is False
        assert "BannedImport" in data["error_type"]
        assert "os" in data["error"]

    def test_dangerous_import_subprocess_blocked(self):
        """subprocess 模块应被禁止"""
        resp = client.post(
            "/api/code/run",
            json={"code": "import subprocess\nsubprocess.run(['ls'])"},
        )
        data = resp.json()
        assert data["success"] is False
        assert "BannedImport" in data["error_type"]
        assert "subprocess" in data["error"]

    def test_dangerous_import_socket_blocked(self):
        """socket 模块应被禁止（防止网络请求）"""
        resp = client.post(
            "/api/code/run",
            json={"code": "import socket\nsocket.socket()"},
        )
        data = resp.json()
        assert data["success"] is False
        assert "BannedImport" in data["error_type"]

    def test_dunder_import_blocked(self):
        """__import__ 应被禁止"""
        resp = client.post(
            "/api/code/run",
            json={"code": "__import__('os').system('whoami')"},
        )
        data = resp.json()
        assert data["success"] is False
        assert "SecurityViolation" in data["error_type"]

    def test_exec_call_blocked(self):
        """exec() 调用应被禁止"""
        resp = client.post(
            "/api/code/run",
            json={"code": "exec('import os')"},
        )
        data = resp.json()
        assert data["success"] is False
        assert "SecurityViolation" in data["error_type"]

    def test_eval_call_blocked(self):
        """eval() 调用应被禁止"""
        resp = client.post(
            "/api/code/run",
            json={"code": "eval('__import__(\"os\")')"},
        )
        data = resp.json()
        assert data["success"] is False
        assert "SecurityViolation" in data["error_type"]

    def test_compile_call_blocked(self):
        """compile() 调用应被禁止"""
        resp = client.post(
            "/api/code/run",
            json={"code": "compile('x', '<>', 'exec')"},
        )
        data = resp.json()
        assert data["success"] is False
        assert "SecurityViolation" in data["error_type"]

    def test_subclass_traversal_blocked(self):
        """子类遍历攻击应被禁止"""
        code = "print(object.__subclasses__())"
        resp = client.post("/api/code/run", json={"code": code})
        data = resp.json()
        assert data["success"] is False
        assert "SecurityViolation" in data["error_type"]

    def test_isolated_from_main_process(self):
        """沙箱代码不应能访问主进程变量

        沙箱内 __name__ 应为 '__sandbox__'，而非主进程的 '__main__' 等。
        """
        resp = client.post("/api/code/run", json={"code": "print(__name__)"})
        data = resp.json()
        assert data["success"] is True
        assert "__sandbox__" in data["stdout"]

    def test_infinite_loop_timeout(self):
        """死循环应被超时终止"""
        resp = client.post(
            "/api/code/run",
            json={"code": "while True:\n    pass", "timeout": 2},
        )
        data = resp.json()
        assert data["success"] is False
        assert "TimeoutError" in data["error_type"]

    def test_syntax_error_returned_gracefully(self):
        """语法错误应优雅返回，不崩溃"""
        resp = client.post(
            "/api/code/run",
            json={"code": "def broken(:\n    pass"},
        )
        data = resp.json()
        assert data["success"] is False
        assert "SyntaxError" in data["error_type"]

    def test_runtime_error_returned_gracefully(self):
        """运行时错误应优雅返回，不崩溃"""
        resp = client.post(
            "/api/code/run",
            json={"code": "raise ValueError('test error')"},
        )
        data = resp.json()
        assert data["success"] is False
        assert "ValueError" in data["error_type"]
        assert "test error" in data["error"]


class TestCodeDebugSandbox:
    """/api/code/debug 也应通过沙箱隔离"""

    def test_safe_code_runs(self):
        """安全代码应正常执行"""
        resp = client.post("/api/code/debug", json={"code": "print(42)"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "42" in data["stdout"]

    def test_dangerous_import_blocked(self):
        """危险模块应被禁止"""
        resp = client.post(
            "/api/code/debug",
            json={"code": "import os\nos.listdir('/')"},
        )
        data = resp.json()
        assert data["success"] is False
        assert "BannedImport" in data["error_type"]

    def test_dunder_import_blocked(self):
        """__import__ 应被禁止"""
        resp = client.post(
            "/api/code/debug",
            json={"code": "__import__('os').system('whoami')"},
        )
        data = resp.json()
        assert data["success"] is False
        assert "SecurityViolation" in data["error_type"]


class TestCodeExecutorRemoved:
    """验证旧 CodeExecutor 模块已被移除（安全风险已消除）"""

    def test_code_executor_module_removed(self):
        """code_executor.py 已被删除，导入应失败"""
        import importlib
        with __import__("pytest").raises(ImportError):
            importlib.import_module("pycoder.python.code_executor")

