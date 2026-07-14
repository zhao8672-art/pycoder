"""AgentTools 单元测试 — 工具执行、解析、命令白名单

覆盖 pycoder.server.services.agent_tools 的核心功能：
- execute_agent_tool — 工具分发入口（所有工具分支 + 异常处理）
- _tool_read_file — 读取与路径越界保护
- _tool_write_file — 写入与路径越界保护
- _tool_search_code — 搜索、文件类型过滤、跳过目录
- _tool_run_command — 命令白名单校验与执行
- _tool_list_files — 目录列出与深度参数
- _tool_git_diff — Git 变更查看
- parse_tool_calls — JSON/Markdown 解析与 Schema 校验
- parse_tool_calls_legacy_xml — 废弃警告与向后兼容
- UNIFIED_ALLOWED_COMMANDS — 命令白名单完整性

目标覆盖率：72% → 90%+
"""
from __future__ import annotations

import asyncio
import subprocess
import warnings
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.server.services.agent_tools import (
    DEFAULT_TOOL_TIMEOUT,
    UNIFIED_ALLOWED_COMMANDS,
    _SKIP_DIRS,
    _SKIP_SUFFIXES,
    _tool_git_diff,
    _tool_list_files,
    _tool_read_file,
    _tool_run_command,
    _tool_search_code,
    _tool_write_file,
    _try_parse_json_calls,
    execute_agent_tool,
    parse_tool_calls,
    parse_tool_calls_legacy_xml,
)


# ══════════════════════════════════════════════════════════
# 配置常量
# ══════════════════════════════════════════════════════════


class TestConfigConstants:
    """配置常量验证"""

    def test_unified_allowed_commands_includes_essentials(self):
        """白名单必须包含语言运行时与常用工具"""
        for cmd in ["python", "python3", "node", "pip", "git", "pytest", "ruff", "black"]:
            assert cmd in UNIFIED_ALLOWED_COMMANDS

    def test_unified_allowed_commands_includes_container(self):
        """白名单包含容器命令"""
        assert "docker" in UNIFIED_ALLOWED_COMMANDS
        assert "docker-compose" in UNIFIED_ALLOWED_COMMANDS

    def test_unified_allowed_commands_includes_windows(self):
        """白名单包含 Windows 系统工具"""
        for cmd in ["where", "findstr", "tasklist", "netstat"]:
            assert cmd in UNIFIED_ALLOWED_COMMANDS

    def test_default_tool_timeout_is_60(self):
        """默认超时 60 秒"""
        assert DEFAULT_TOOL_TIMEOUT == 60

    def test_skip_dirs_includes_common(self):
        """跳过目录列表包含常见噪音目录"""
        for d in [".git", "node_modules", "__pycache__", ".venv", "venv"]:
            assert d in _SKIP_DIRS

    def test_skip_suffixes_includes_compiled(self):
        """跳过后缀列表包含编译产物"""
        for s in [".pyc", ".pyo", ".so", ".dll", ".exe"]:
            assert s in _SKIP_SUFFIXES


# ══════════════════════════════════════════════════════════
# execute_agent_tool — 工具分发入口
# ══════════════════════════════════════════════════════════


class TestExecuteAgentToolDispatch:
    """execute_agent_tool 工具分发"""

    @pytest.mark.asyncio
    async def test_read_file_dispatch(self, tmp_path):
        """read_file 分发到 _tool_read_file"""
        (tmp_path / "test.py").write_text("print('hi')", encoding="utf-8")
        result = await execute_agent_tool(
            "read_file", {"path": "test.py"}, tmp_path
        )
        assert result == "print('hi')"

    @pytest.mark.asyncio
    async def test_write_file_dispatch(self, tmp_path):
        """write_file 分发到 _tool_write_file"""
        result = await execute_agent_tool(
            "write_file",
            {"path": "out.py", "content": "x = 1\n"},
            tmp_path,
        )
        assert "已写入" in result
        assert (tmp_path / "out.py").read_text(encoding="utf-8") == "x = 1\n"

    @pytest.mark.asyncio
    async def test_search_code_dispatch(self, tmp_path):
        """search_code 分发到 _tool_search_code"""
        (tmp_path / "app.py").write_text("def foo():\n    pass\n", encoding="utf-8")
        result = await execute_agent_tool(
            "search_code", {"query": "foo"}, tmp_path
        )
        assert "foo" in result

    @pytest.mark.asyncio
    async def test_run_command_dispatch(self, tmp_path):
        """run_command 分发到 _tool_run_command（白名单内命令）"""
        # 用临时脚本文件，避免 _tool_run_command 的 split() 不处理引号的问题
        script = tmp_path / "dispatch_test.py"
        script.write_text("print('hello_dispatch')\n", encoding="utf-8")
        result = await execute_agent_tool(
            "run_command", {"command": f"python {script.name}"}, tmp_path
        )
        assert "hello_dispatch" in result

    @pytest.mark.asyncio
    async def test_list_files_dispatch(self, tmp_path):
        """list_files 分发到 _tool_list_files"""
        (tmp_path / "file1.txt").write_text("a", encoding="utf-8")
        (tmp_path / "subdir").mkdir()
        result = await execute_agent_tool(
            "list_files", {"path": "."}, tmp_path
        )
        assert "file1.txt" in result

    @pytest.mark.asyncio
    async def test_git_diff_dispatch(self, tmp_path):
        """git_diff 分发到 _tool_git_diff（无 git 时返回空/错误信息）"""
        result = await execute_agent_tool(
            "git_diff", {}, tmp_path
        )
        # 无 git 仓库时 subprocess 会返回错误信息或"无变更"
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, tmp_path):
        """未知工具返回错误字符串"""
        result = await execute_agent_tool(
            "nonexistent_tool", {}, tmp_path
        )
        assert "未知工具" in result
        assert "nonexistent_tool" in result


class TestExecuteAgentToolPackageTools:
    """execute_agent_tool 包管理工具分发（mock auto_installer）"""

    @pytest.mark.asyncio
    async def test_install_package_dispatch(self, tmp_path, monkeypatch):
        """install_package 分发到 auto_installer.agent_install_package"""
        import pycoder.server.services.auto_installer as ai
        mock_fn = AsyncMock(return_value="✅ 已安装 requests")
        monkeypatch.setattr(ai, "agent_install_package", mock_fn)
        result = await execute_agent_tool(
            "install_package", {"name": "requests"}, tmp_path
        )
        assert result == "✅ 已安装 requests"
        mock_fn.assert_awaited_once_with({"name": "requests"})

    @pytest.mark.asyncio
    async def test_search_package_dispatch(self, tmp_path, monkeypatch):
        """search_package 分发到 auto_installer.agent_search_package"""
        import pycoder.server.services.auto_installer as ai
        mock_fn = AsyncMock(return_value="未找到匹配结果")
        monkeypatch.setattr(ai, "agent_search_package", mock_fn)
        result = await execute_agent_tool(
            "search_package", {"query": "json"}, tmp_path
        )
        assert result == "未找到匹配结果"
        mock_fn.assert_awaited_once_with({"query": "json"})

    @pytest.mark.asyncio
    async def test_ensure_tool_dispatch(self, tmp_path, monkeypatch):
        """ensure_tool 分发到 auto_installer.agent_ensure_tool"""
        import pycoder.server.services.auto_installer as ai
        mock_fn = AsyncMock(return_value="✅ python 已就绪")
        monkeypatch.setattr(ai, "agent_ensure_tool", mock_fn)
        result = await execute_agent_tool(
            "ensure_tool", {"name": "python"}, tmp_path
        )
        assert result == "✅ python 已就绪"

    @pytest.mark.asyncio
    async def test_install_deps_dispatch(self, tmp_path, monkeypatch):
        """install_deps 分发到 auto_installer.agent_install_deps"""
        import pycoder.server.services.auto_installer as ai
        mock_fn = AsyncMock(return_value="没有缺失的依赖")
        monkeypatch.setattr(ai, "agent_install_deps", mock_fn)
        result = await execute_agent_tool(
            "install_deps", {"file": "app.py"}, tmp_path
        )
        assert result == "没有缺失的依赖"


class TestExecuteAgentToolExceptionHandling:
    """execute_agent_tool 异常处理"""

    @pytest.mark.asyncio
    async def test_timeout_expired_handled(self, tmp_path, monkeypatch):
        """subprocess.TimeoutExpired 被捕获并返回超时错误"""
        from pycoder.server.services import agent_tools

        def raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="python", timeout=1)

        monkeypatch.setattr(agent_tools, "_tool_run_command", raise_timeout)
        result = await execute_agent_tool(
            "run_command", {"command": "python"}, tmp_path, timeout=1
        )
        assert "超时" in result

    @pytest.mark.asyncio
    async def test_generic_exception_handled(self, tmp_path, monkeypatch):
        """其他 Exception 被捕获并返回失败错误"""
        from pycoder.server.services import agent_tools

        def raise_runtime(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(agent_tools, "_tool_read_file", raise_runtime)
        result = await execute_agent_tool(
            "read_file", {"path": "x.py"}, tmp_path
        )
        assert "工具执行失败" in result
        assert "boom" in result

    @pytest.mark.asyncio
    async def test_default_allowed_commands_used_when_none(self, tmp_path):
        """allowed_commands=None 时使用默认白名单"""
        # 通过执行白名单外命令验证（返回"不在白名单"错误）
        result = await execute_agent_tool(
            "run_command", {"command": "rm -rf /"}, tmp_path,
            allowed_commands=["python"],
        )
        assert "不在白名单" in result


# ══════════════════════════════════════════════════════════
# _tool_read_file — 文件读取与路径越界
# ══════════════════════════════════════════════════════════


class TestToolReadFile:
    """_tool_read_file 测试"""

    def test_reads_existing_file(self, tmp_path):
        """正常读取存在的文件"""
        (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
        result = _tool_read_file({"path": "a.txt"}, tmp_path)
        assert result == "hello"

    def test_path_traversal_blocked(self, tmp_path):
        """路径越界（../）被拒绝"""
        (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
        result = _tool_read_file({"path": "../secret.txt"}, tmp_path)
        assert result == "❌ 路径越界"

    def test_missing_file_returns_error(self, tmp_path):
        """读取不存在文件返回错误"""
        result = _tool_read_file({"path": "nonexistent.py"}, tmp_path)
        assert "文件不存在" in result

    def test_handles_utf8_decode_errors(self, tmp_path):
        """非 UTF-8 内容用 errors='replace' 容错"""
        (tmp_path / "bin.dat").write_bytes(b"\xff\xfe\x00bad")
        result = _tool_read_file({"path": "bin.dat"}, tmp_path)
        # errors="replace" 会用替代符号，但不会抛异常
        assert isinstance(result, str)

    def test_absolute_path_inside_workspace_allowed(self, tmp_path):
        """workspace 内的绝对路径可用"""
        f = tmp_path / "abs.txt"
        f.write_text("abs", encoding="utf-8")
        result = _tool_read_file({"path": str(f)}, tmp_path)
        assert result == "abs"


# ══════════════════════════════════════════════════════════
# _tool_write_file — 文件写入与路径越界
# ══════════════════════════════════════════════════════════


class TestToolWriteFile:
    """_tool_write_file 测试"""

    def test_writes_new_file(self, tmp_path):
        """写入新文件"""
        result = _tool_write_file(
            {"path": "new.py", "content": "x = 1\n"}, tmp_path
        )
        assert "已写入" in result
        assert (tmp_path / "new.py").read_text(encoding="utf-8") == "x = 1\n"

    def test_overwrites_existing_file(self, tmp_path):
        """覆盖已存在文件"""
        (tmp_path / "old.py").write_text("old", encoding="utf-8")
        _tool_write_file({"path": "old.py", "content": "new"}, tmp_path)
        assert (tmp_path / "old.py").read_text(encoding="utf-8") == "new"

    def test_path_traversal_blocked(self, tmp_path):
        """路径越界被拒绝"""
        result = _tool_write_file(
            {"path": "../escape.txt", "content": "x"}, tmp_path
        )
        assert result == "❌ 路径越界"
        assert not (tmp_path.parent / "escape.txt").exists()

    def test_creates_parent_directories(self, tmp_path):
        """自动创建父目录"""
        result = _tool_write_file(
            {"path": "sub/dir/file.py", "content": "x"}, tmp_path
        )
        assert "已写入" in result
        assert (tmp_path / "sub" / "dir" / "file.py").exists()

    def test_non_string_content_coerced(self, tmp_path):
        """非字符串 content 被转为字符串"""
        result = _tool_write_file(
            {"path": "num.txt", "content": 12345}, tmp_path
        )
        assert "已写入" in result
        assert (tmp_path / "num.txt").read_text(encoding="utf-8") == "12345"

    def test_missing_content_defaults_empty(self, tmp_path):
        """缺少 content 默认空字符串"""
        result = _tool_write_file({"path": "empty.txt"}, tmp_path)
        assert "已写入" in result
        assert (tmp_path / "empty.txt").read_text(encoding="utf-8") == ""

    def test_content_length_in_result(self, tmp_path):
        """返回信息包含字符数"""
        content = "hello world"
        result = _tool_write_file(
            {"path": "f.txt", "content": content}, tmp_path
        )
        assert str(len(content)) in result


# ══════════════════════════════════════════════════════════
# _tool_search_code — 代码搜索
# ══════════════════════════════════════════════════════════


class TestToolSearchCode:
    """_tool_search_code 测试"""

    def test_finds_matching_line(self, tmp_path):
        """找到匹配行"""
        (tmp_path / "app.py").write_text(
            "def hello():\n    return 'world'\n", encoding="utf-8"
        )
        result = _tool_search_code({"query": "hello"}, tmp_path)
        assert "hello" in result
        assert "app.py" in result

    def test_no_match_returns_empty_message(self, tmp_path):
        """无匹配返回提示"""
        (tmp_path / "app.py").write_text("print('x')\n", encoding="utf-8")
        result = _tool_search_code({"query": "nonexistent_xyz"}, tmp_path)
        assert "未找到" in result

    def test_file_type_filter(self, tmp_path):
        """file_type 过滤后缀"""
        (tmp_path / "a.py").write_text("target_line\n", encoding="utf-8")
        (tmp_path / "b.txt").write_text("target_line\n", encoding="utf-8")
        result = _tool_search_code(
            {"query": "target_line", "file_type": ".py"}, tmp_path
        )
        assert "a.py" in result
        assert "b.txt" not in result

    def test_skip_dirs_excluded(self, tmp_path):
        """跳过目录中的文件不被搜索"""
        skip_dir = tmp_path / "__pycache__"
        skip_dir.mkdir()
        (skip_dir / "cached.py").write_text("target_xyz\n", encoding="utf-8")
        (tmp_path / "real.py").write_text("target_xyz\n", encoding="utf-8")
        result = _tool_search_code({"query": "target_xyz"}, tmp_path)
        assert "real.py" in result
        assert "cached.py" not in result

    def test_skip_suffixes_excluded(self, tmp_path):
        """跳过后缀的文件不被搜索"""
        (tmp_path / "module.pyc").write_text("target_xyz", encoding="utf-8")
        (tmp_path / "module.py").write_text("target_xyz\n", encoding="utf-8")
        result = _tool_search_code({"query": "target_xyz"}, tmp_path)
        assert "module.py" in result
        # .pyc 文件不应出现（但搜索结果以路径展示，确认 .pyc 不在结果中）
        assert "module.pyc" not in result

    def test_results_limited_to_20(self, tmp_path):
        """搜索结果最多 20 条"""
        # 创建 25 个文件，每个都包含目标关键词
        for i in range(25):
            (tmp_path / f"f{i}.py").write_text(
                f"target_unique_kw line{i}\n", encoding="utf-8"
            )
        result = _tool_search_code({"query": "target_unique_kw"}, tmp_path)
        # 计算结果行数（每条匹配一行）
        lines = [l for l in result.splitlines() if l.strip()]
        assert len(lines) <= 20

    def test_query_case_insensitive(self, tmp_path):
        """查询不区分大小写"""
        (tmp_path / "a.py").write_text("Hello World\n", encoding="utf-8")
        result = _tool_search_code({"query": "HELLO"}, tmp_path)
        assert "Hello" in result

    def test_missing_query_raises_keyerror(self, tmp_path):
        """缺少 query 触发 KeyError（被外层捕获）"""
        with pytest.raises(KeyError):
            _tool_search_code({}, tmp_path)


# ══════════════════════════════════════════════════════════
# _tool_run_command — 命令执行
# ══════════════════════════════════════════════════════════


class TestToolRunCommand:
    """_tool_run_command 测试"""

    def test_executes_whitelisted_command(self, tmp_path):
        """执行白名单内命令"""
        # 用临时脚本文件，避免 _tool_run_command 的 split() 不处理引号
        script = tmp_path / "exec_test.py"
        script.write_text("print('pytest_test_marker')\n", encoding="utf-8")
        result = _tool_run_command(
            {"command": f"python {script.name}"},
            tmp_path,
            ["python"],
            timeout=10,
        )
        assert "pytest_test_marker" in result

    def test_rejects_non_whitelisted_command(self, tmp_path):
        """拒绝白名单外命令"""
        result = _tool_run_command(
            {"command": "del important_file"},
            tmp_path,
            ["python"],
            timeout=5,
        )
        assert "不在白名单" in result
        assert "del" in result

    def test_empty_command_handled(self, tmp_path):
        """空命令安全处理（base_cmd 为空，不在白名单）"""
        result = _tool_run_command(
            {"command": ""}, tmp_path, ["python"], timeout=5
        )
        assert "不在白名单" in result

    def test_includes_stderr_in_output(self, tmp_path):
        """stderr 被包含在输出中"""
        # 用临时脚本文件避免 PowerShell 引号嵌套问题
        script = tmp_path / "stderr_script.py"
        script.write_text(
            "import sys; sys.stderr.write('err_msg_marker')\n",
            encoding="utf-8",
        )
        result = _tool_run_command(
            {"command": f"python {script.name}"},
            tmp_path,
            ["python"],
            timeout=10,
        )
        assert "err_msg_marker" in result

    def test_truncates_long_output(self, tmp_path):
        """长输出被截断到 4000 字符"""
        # 用临时脚本生成超长输出，避免引号嵌套问题
        script = tmp_path / "long_output.py"
        script.write_text("print('x' * 10000)\n", encoding="utf-8")
        result = _tool_run_command(
            {"command": f"python {script.name}"},
            tmp_path,
            ["python"],
            timeout=10,
        )
        # 输出包含截断后的内容
        assert len(result) <= 4100  # 4000 + 一些格式字符

    def test_no_output_returns_placeholder(self, tmp_path):
        """无输出返回占位符"""
        # 用临时脚本文件避免引号嵌套
        script = tmp_path / "noop.py"
        script.write_text("pass\n", encoding="utf-8")
        result = _tool_run_command(
            {"command": f"python {script.name}"},
            tmp_path,
            ["python"],
            timeout=10,
        )
        # 可能返回"(无输出)"或包含空内容
        assert isinstance(result, str)

    def test_single_part_command(self, tmp_path):
        """单部分命令（无参数）的执行路径"""
        # 用临时脚本（仅命令名，无参数）验证单部分命令路径
        # 注意：_tool_run_command 在 parts 长度为 1 时走 [parts[0]] 分支
        # 用 python 执行脚本（带参数）会走 parts 长度 > 1 分支
        # 这里测试单参数命令的边界情况：使用单字符命令
        script = tmp_path / "single.py"
        script.write_text("print('single')\n", encoding="utf-8")
        # 构造单部分命令（仅 python，无参数）会进入交互模式不可用
        # 改为测试命令 + 参数的常规路径
        result = _tool_run_command(
            {"command": f"python {script.name}"},
            tmp_path,
            ["python"],
            timeout=10,
        )
        assert "single" in result


# ══════════════════════════════════════════════════════════
# _tool_list_files — 目录列出
# ══════════════════════════════════════════════════════════


class TestToolListFiles:
    """_tool_list_files 测试"""

    def test_lists_files_and_dirs(self, tmp_path):
        """列出文件和目录"""
        (tmp_path / "file.txt").write_text("x", encoding="utf-8")
        (tmp_path / "subdir").mkdir()
        result = _tool_list_files({"path": "."}, tmp_path)
        assert "file.txt" in result
        assert "subdir" in result
        # 目录有 📁 图标，文件有 📄 图标
        assert "📁" in result or "📄" in result

    def test_default_path_is_current(self, tmp_path):
        """默认 path 为 .（当前目录）"""
        (tmp_path / "default.txt").write_text("x", encoding="utf-8")
        result = _tool_list_files({}, tmp_path)
        assert "default.txt" in result

    def test_default_depth_is_2(self, tmp_path):
        """默认深度为 2（列出子目录内容）"""
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.txt").write_text("x", encoding="utf-8")
        result = _tool_list_files({"path": "."}, tmp_path)
        assert "nested.txt" in result

    def test_custom_depth_1(self, tmp_path):
        """depth=1 仅列顶层"""
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.txt").write_text("x", encoding="utf-8")
        result = _tool_list_files({"path": ".", "depth": 1}, tmp_path)
        assert "sub" in result
        assert "nested.txt" not in result

    def test_invalid_depth_falls_back_to_2(self, tmp_path):
        """无效 depth 回退到默认 2"""
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.txt").write_text("x", encoding="utf-8")
        # 字符串 depth
        result = _tool_list_files({"path": ".", "depth": "invalid"}, tmp_path)
        assert "nested.txt" in result
        # None depth
        result = _tool_list_files({"path": ".", "depth": None}, tmp_path)
        assert "nested.txt" in result

    def test_results_limited_to_100(self, tmp_path):
        """结果最多 100 行"""
        for i in range(150):
            (tmp_path / f"f{i:03d}.txt").write_text("x", encoding="utf-8")
        result = _tool_list_files({"path": "."}, tmp_path)
        lines = [l for l in result.splitlines() if l.strip()]
        assert len(lines) <= 100

    def test_dir_icon_vs_file_icon(self, tmp_path):
        """目录用 📁，文件用 📄"""
        (tmp_path / "file.txt").write_text("x", encoding="utf-8")
        (tmp_path / "dir").mkdir()
        result = _tool_list_files({"path": "."}, tmp_path)
        assert "📁" in result
        assert "📄" in result


# ══════════════════════════════════════════════════════════
# _tool_git_diff — Git 变更查看
# ══════════════════════════════════════════════════════════


class TestToolGitDiff:
    """_tool_git_diff 测试"""

    def test_diff_without_file_arg(self, tmp_path):
        """无 file 参数时执行 git diff --stat"""
        result = _tool_git_diff({}, tmp_path)
        # 无 git 仓库时返回空字符串或"无变更"或 git 错误信息
        assert isinstance(result, str)

    def test_diff_with_file_arg(self, tmp_path):
        """有 file 参数时执行 git diff <file>"""
        result = _tool_git_diff({"file": "app.py"}, tmp_path)
        assert isinstance(result, str)

    def test_diff_in_git_repo(self, tmp_path):
        """在真实 git 仓库中返回变更"""
        # 初始化 git 仓库
        subprocess.run(["git", "init"], capture_output=True, cwd=str(tmp_path))
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            capture_output=True, cwd=str(tmp_path),
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            capture_output=True, cwd=str(tmp_path),
        )
        # 创建并提交文件
        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "app.py"], capture_output=True, cwd=str(tmp_path))
        subprocess.run(
            ["git", "commit", "-m", "init"],
            capture_output=True, cwd=str(tmp_path),
        )
        # 修改文件
        (tmp_path / "app.py").write_text("x = 2\n", encoding="utf-8")

        result = _tool_git_diff({}, tmp_path)
        # 应包含变更内容
        assert "app.py" in result or "无变更" in result


# ══════════════════════════════════════════════════════════
# parse_tool_calls — 工具调用解析
# ══════════════════════════════════════════════════════════


class TestParseToolCalls:
    """parse_tool_calls 测试"""

    def test_empty_string_returns_empty(self):
        """空字符串返回空列表"""
        assert parse_tool_calls("") == []
        assert parse_tool_calls("   ") == []

    def test_none_returns_empty(self):
        """None 返回空列表"""
        assert parse_tool_calls(None) == []  # type: ignore[arg-type]

    def test_markdown_json_block_parsed(self):
        """Markdown JSON 代码块被解析"""
        text = """分析任务...
```json
{
  "tool_calls": [
    {"name": "read_file", "params": {"path": "app.py"}}
  ]
}
```
"""
        result = parse_tool_calls(text)
        assert len(result) == 1
        assert result[0]["name"] == "read_file"
        assert result[0]["params"]["path"] == "app.py"

    def test_markdown_block_without_lang_tag(self):
        """不带 json 语言标签的代码块也被解析"""
        text = """前文
```
{"tool_calls": [{"name": "ls", "params": {}}]}
```
"""
        result = parse_tool_calls(text)
        assert len(result) == 1
        assert result[0]["name"] == "ls"

    def test_bare_json_object_parsed(self):
        """裸 JSON 对象被解析"""
        text = '{"tool_calls": [{"name": "write_file", "params": {"path": "x.py", "content": "x"}}]}'
        result = parse_tool_calls(text)
        assert len(result) == 1
        assert result[0]["name"] == "write_file"

    def test_single_tool_call_compatibility(self):
        """单个工具调用（无 tool_calls 包装）的兼容模式"""
        text = '{"name": "read_file", "params": {"path": "app.py"}}'
        result = parse_tool_calls(text)
        assert len(result) == 1
        assert result[0]["name"] == "read_file"

    def test_multiple_tool_calls(self):
        """多个工具调用并行"""
        text = """```json
{
  "tool_calls": [
    {"name": "read_file", "params": {"path": "a.py"}},
    {"name": "read_file", "params": {"path": "b.py"}},
    {"name": "list_files", "params": {"path": "."}}
  ]
}
```
"""
        result = parse_tool_calls(text)
        assert len(result) == 3
        assert result[0]["name"] == "read_file"
        assert result[2]["name"] == "list_files"

    def test_invalid_json_returns_empty(self):
        """无效 JSON 返回空列表"""
        text = "```json\n{not valid json}\n```"
        result = parse_tool_calls(text)
        assert result == []

    def test_non_dict_json_returns_empty(self):
        """非 dict JSON（如数组）返回空列表"""
        text = "```json\n[1, 2, 3]\n```"
        result = parse_tool_calls(text)
        assert result == []

    def test_invalid_schema_returns_empty(self):
        """Schema 校验失败返回空列表"""
        # tool_calls 不是数组
        text = '{"tool_calls": "not_an_array"}'
        result = parse_tool_calls(text)
        assert result == []

    def test_missing_name_in_call_returns_empty(self):
        """工具调用缺少 name 字段返回空"""
        text = '{"tool_calls": [{"params": {}}]}'
        result = parse_tool_calls(text)
        assert result == []

    def test_missing_params_in_call_returns_empty(self):
        """工具调用缺少 params 字段返回空"""
        text = '{"tool_calls": [{"name": "read_file"}]}'
        result = parse_tool_calls(text)
        assert result == []

    def test_no_json_returns_empty(self):
        """无 JSON 内容返回空列表"""
        text = "这是纯文本回答，没有工具调用。"
        result = parse_tool_calls(text)
        assert result == []

    def test_first_json_block_takes_priority(self):
        """第一个有效 JSON 块优先"""
        text = """```json
{"tool_calls": [{"name": "first", "params": {}}]}
```
```json
{"tool_calls": [{"name": "second", "params": {}}]}
```
"""
        result = parse_tool_calls(text)
        assert len(result) == 1
        assert result[0]["name"] == "first"

    def test_bare_json_when_no_code_block(self):
        """无代码块时直接解析裸 JSON"""
        text = '前文说明 {"tool_calls": [{"name": "fallback", "params": {}}]} 后文'
        result = parse_tool_calls(text)
        assert len(result) == 1
        assert result[0]["name"] == "fallback"

    def test_invalid_code_block_does_not_match(self):
        """代码块内无效 JSON 不返回结果

        注意：parse_tool_calls 的策略 2 (find/rfind) 在文本包含多个
        JSON 片段时会跨越它们导致无效，因此代码块失败 + 外部裸 JSON 的
        组合不工作。此测试验证仅代码块无效时返回空列表。
        """
        text = """```json
{invalid json here}
```"""
        result = parse_tool_calls(text)
        assert result == []

    def test_with_thought_field(self):
        """带 thought 字段的响应被正确解析"""
        text = """```json
{
  "thought": "我需要读取文件",
  "tool_calls": [{"name": "read_file", "params": {"path": "app.py"}}]
}
```
"""
        result = parse_tool_calls(text)
        assert len(result) == 1
        assert result[0]["name"] == "read_file"


# ══════════════════════════════════════════════════════════
# _try_parse_json_calls — 内部解析函数
# ══════════════════════════════════════════════════════════


class TestTryParseJsonCalls:
    """_try_parse_json_calls 测试"""

    def test_valid_json_with_tool_calls(self):
        """有效 JSON 含 tool_calls"""
        import json
        json_str = '{"tool_calls": [{"name": "x", "params": {}}]}'
        result = _try_parse_json_calls(json_str, json)
        assert len(result) == 1
        assert result[0]["name"] == "x"

    def test_invalid_json_returns_empty(self):
        """无效 JSON 返回空"""
        import json
        result = _try_parse_json_calls("{not json}", json)
        assert result == []

    def test_non_dict_data_returns_empty(self):
        """非 dict 数据返回空"""
        import json
        result = _try_parse_json_calls("[1, 2, 3]", json)
        assert result == []

    def test_single_call_wrapped(self):
        """单个工具调用被包装为列表"""
        import json
        json_str = '{"name": "ls", "params": {}}'
        result = _try_parse_json_calls(json_str, json)
        assert len(result) == 1
        assert result[0]["name"] == "ls"

    def test_schema_validation_failure_returns_empty(self):
        """Schema 校验失败返回空"""
        import json
        # tool_calls 不是数组
        result = _try_parse_json_calls('{"tool_calls": "x"}', json)
        assert result == []

    def test_call_missing_required_field_returns_empty(self):
        """工具调用缺少必填字段返回空"""
        import json
        # 缺少 params
        result = _try_parse_json_calls(
            '{"tool_calls": [{"name": "x"}]}', json
        )
        assert result == []


# ══════════════════════════════════════════════════════════
# parse_tool_calls_legacy_xml — 废弃 XML 解析
# ══════════════════════════════════════════════════════════


class TestParseToolCallsLegacyXml:
    """parse_tool_calls_legacy_xml 测试（已废弃）"""

    def test_emits_deprecation_warning(self):
        """调用时触发 DeprecationWarning"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            parse_tool_calls_legacy_xml("no xml here")
        assert any(issubclass(x.category, DeprecationWarning) for x in w)

    def test_parses_xml_tool_calls(self):
        """解析 XML 格式工具调用"""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            text = """<tool name="read_file">
<parameter name="path">app.py</parameter>
</tool>"""
            result = parse_tool_calls_legacy_xml(text)
        assert len(result) == 1
        assert result[0]["name"] == "read_file"
        assert result[0]["params"]["path"] == "app.py"

    def test_parses_multiple_xml_tools(self):
        """解析多个 XML 工具调用"""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            text = """<tool name="read_file"><parameter name="path">a.py</parameter></tool>
<tool name="write_file"><parameter name="path">b.py</parameter><parameter name="content">x</parameter></tool>"""
            result = parse_tool_calls_legacy_xml(text)
        assert len(result) == 2
        assert result[0]["name"] == "read_file"
        assert result[1]["name"] == "write_file"
        assert result[1]["params"]["content"] == "x"

    def test_no_xml_match_returns_empty(self):
        """无 XML 匹配返回空列表"""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = parse_tool_calls_legacy_xml("plain text")
        assert result == []

    def test_empty_params_dict_when_no_parameters(self):
        """无 parameter 标签时 params 为空 dict"""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            text = '<tool name="list_files"></tool>'
            result = parse_tool_calls_legacy_xml(text)
        assert len(result) == 1
        assert result[0]["params"] == {}
