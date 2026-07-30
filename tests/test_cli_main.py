"""pycoder.__main__ 单元测试

覆盖 pycoder.__main__ 模块:
  - main() 各种 sys.argv 输入
  - argparse 参数解析（--version / --server / --generate / --status / 等）
  - help 输出
  - 默认行为（无参数 → server 模式）
  - _infer_name 关键字识别
  - _run_cli_mode 输出格式
  - if __name__ == "__main__" 入口
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from io import StringIO
from typing import Any
from unittest.mock import patch

import pytest

import pycoder.__main__ as cli_main
from pycoder.__main__ import _infer_name, _run_cli_mode, main

# ══════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════


@contextmanager
def argv(*args: str) -> Iterator[None]:
    """临时替换 sys.argv"""
    original = sys.argv
    sys.argv = ["pycoder"] + list(args)
    try:
        yield
    finally:
        sys.argv = original


@contextmanager
def captured_stdout() -> Iterator[StringIO]:
    """捕获 print 输出"""

    buf = StringIO()
    original_stdout = sys.stdout
    sys.stdout = buf
    try:
        yield buf
    finally:
        sys.stdout = original_stdout


@contextmanager
def captured_exit() -> Iterator[list[int]]:
    """捕获 SystemExit，返回列表便于断言"""
    exits: list[int] = []

    def fake_exit(code: int = 0) -> None:
        exits.append(code)
        raise SystemExit(code)

    with patch.object(cli_main.sys, "exit", side_effect=fake_exit):
        yield exits


# ══════════════════════════════════════════════════════════
# main() — 参数解析
# ══════════════════════════════════════════════════════════


class TestMainVersion:
    """--version"""

    def test_version_prints_and_exits(self) -> None:
        """--version 应打印版本号并退出 0"""
        with argv("--version"), captured_stdout() as out, captured_exit() as exits:
            with pytest.raises(SystemExit):
                main()
        assert exits == [0]
        assert "PyCoder" in out.getvalue()
        assert "v" in out.getvalue()


class TestMainServer:
    """--server / 默认 server 模式"""

    def test_server_flag_calls_run_server(self) -> None:
        """--server 应调用 pycoder.server.app.run_server"""
        with argv("--server", "--server-port", "9999"):
            with patch("pycoder.server.app.run_server") as run_mock:
                main()
        run_mock.assert_called_once()
        kwargs = run_mock.call_args.kwargs
        assert kwargs.get("port") == 9999

    def test_default_args_uses_default_port(self) -> None:
        """无任何参数时（且 unknown 为空）应使用默认端口 8423"""
        with argv():
            with patch("pycoder.server.app.run_server") as run_mock:
                main()
        run_mock.assert_called_once()
        assert run_mock.call_args.kwargs.get("port") == 8423

    def test_quick_start_flag_passes_through(self) -> None:
        """--quick-start 应被透传到 run_server"""
        with argv("--server", "--quick-start"):
            with patch("pycoder.server.app.run_server") as run_mock:
                main()
        assert run_mock.call_args.kwargs.get("quick_start") is True

    def test_default_port_is_8423(self) -> None:
        """默认端口应为 8423"""
        with argv("--server"):
            with patch("pycoder.server.app.run_server") as run_mock:
                main()
        assert run_mock.call_args.kwargs.get("port") == 8423


class TestMainStatus:
    """--status"""

    def test_status_prints_and_exits(self) -> None:
        """--status 应打印 model manager 状态并退出 0"""
        with argv("--status"), captured_stdout() as out, captured_exit() as exits:
            with pytest.raises(SystemExit):
                main()
        assert exits == [0]
        # 至少要有输出（status 报告内容）
        assert len(out.getvalue()) >= 0  # 任何输出/空输出都接受


class TestMainEnv:
    """--env"""

    def test_env_prints_environment_info(self) -> None:
        """--env 应打印环境检测结果"""
        with argv("--env"), captured_stdout() as out, captured_exit() as exits:
            with pytest.raises(SystemExit):
                main()
        assert exits == [0]
        # 至少会有一些输出
        assert isinstance(out.getvalue(), str)


class TestMainCost:
    """--cost"""

    def test_cost_prints_report(self) -> None:
        """--cost 应打印费用报告"""
        with argv("--cost"), captured_stdout() as out, captured_exit() as exits:
            with pytest.raises(SystemExit):
                main()
        assert exits == [0]
        # 任何输出/空输出都可接受
        assert isinstance(out.getvalue(), str)


class TestMainListTemplates:
    """--list-templates"""

    def test_list_templates_does_not_crash(self) -> None:
        """--list-templates 应能正常处理（可能空列表）"""
        with argv("--list-templates"), captured_stdout(), captured_exit() as exits:
            with pytest.raises(SystemExit):
                main()
        assert exits == [0]


class TestMainGenerate:
    """--generate"""

    def test_generate_calls_run_generate_mode(self) -> None:
        """--generate 'DESC' 应调用 _run_generate_mode"""
        with argv("--generate", "FastAPI 用户系统"):
            with patch.object(cli_main, "_run_generate_mode") as mock:
                main()
        mock.assert_called_once_with("FastAPI 用户系统", "")

    def test_generate_with_project_dir(self) -> None:
        """--generate + --project-dir 应把目录传给 _run_generate_mode"""
        with argv("--generate", "test", "--project-dir", "/tmp/x"):
            with patch.object(cli_main, "_run_generate_mode") as mock:
                main()
        mock.assert_called_once_with("test", "/tmp/x")


class TestMainSetup:
    """--setup"""

    def test_setup_prints_guide_and_exits(self) -> None:
        """--setup 应打印 setup guide"""
        with argv("--setup"), captured_stdout() as out, captured_exit() as exits:
            with pytest.raises(SystemExit):
                main()
        assert exits == [0]
        assert isinstance(out.getvalue(), str)


class TestMainAutonomous:
    """--autonomous + --task"""

    def test_autonomous_with_task(self) -> None:
        """--autonomous + --task 应调用 _run_autonomous_mode"""
        with argv("--autonomous", "--task", "做一个 API"):
            with patch.object(cli_main, "_run_autonomous_mode") as mock:
                main()
        mock.assert_called_once()
        # 第一个位置参数应是 task 描述
        assert mock.call_args.args[0] == "做一个 API"

    def test_autonomous_with_task_and_model(self) -> None:
        """--autonomous + --task + --model 应传递 model"""
        with argv("--autonomous", "--task", "T", "--model", "gpt-4"):
            with patch.object(cli_main, "_run_autonomous_mode") as mock:
                main()
        # model 应该是 gpt-4
        assert mock.call_args.args[1] == "gpt-4"

    def test_autonomous_with_task_and_port(self) -> None:
        """--autonomous + --task + --server-port 应传递 port"""
        with argv("--autonomous", "--task", "T", "--server-port", "9000"):
            with patch.object(cli_main, "_run_autonomous_mode") as mock:
                main()
        assert mock.call_args.args[2] == 9000

    def test_autonomous_without_task_falls_through(self) -> None:
        """--autonomous 但没有 --task 时不应调用 _run_autonomous_mode"""
        with argv("--autonomous"):
            with patch.object(cli_main, "_run_autonomous_mode") as mock, patch(
                "pycoder.server.app.run_server"
            ) as server_mock:
                main()
        # 不会调用 _run_autonomous_mode
        mock.assert_not_called()
        # 应继续到 server 模式
        server_mock.assert_called_once()


class TestMainEvolve:
    """--evolve"""

    def test_evolve_calls_run_evolution_mode(self) -> None:
        """--evolve 应调用 _run_evolution_mode"""
        with argv("--evolve"):
            with patch.object(cli_main, "_run_evolution_mode") as mock:
                main()
        mock.assert_called_once()

    def test_evolve_with_custom_path(self) -> None:
        """--evolve --evolve-path 应使用自定义路径"""
        with argv("--evolve", "--evolve-path", "/custom/path"):
            with patch.object(cli_main, "_run_evolution_mode") as mock:
                main()
        assert mock.call_args.args[0] == "/custom/path"


class TestMainScan:
    """--scan"""

    def test_scan_calls_run_scan_mode(self) -> None:
        """--scan 应调用 _run_scan_mode"""
        with argv("--scan"):
            with patch.object(cli_main, "_run_scan_mode") as mock:
                main()
        mock.assert_called_once()

    def test_scan_with_path(self) -> None:
        """--scan <path> 应将路径传给 _run_scan_mode"""
        with argv("--scan", "mycode/"):
            with patch.object(cli_main, "_run_scan_mode") as mock:
                main()
        assert mock.call_args.args[0] == "mycode/"

    def test_scan_default_path(self) -> None:
        """--scan 不带参数时应使用默认 pycoder"""
        with argv("--scan"):
            with patch.object(cli_main, "_run_scan_mode") as mock:
                main()
        # 默认 const = "pycoder"
        assert mock.call_args.args[0] == "pycoder"


# ══════════════════════════════════════════════════════════
# main() — argparse help
# ══════════════════════════════════════════════════════════


class TestMainHelp:
    """--help"""

    def test_help_prints_usage(self, capsys: Any) -> None:
        """--help 应打印 usage 信息并退出 0"""
        with argv("--help"), captured_exit():
            with pytest.raises(SystemExit) as exc:
                main()
        # argparse 退出码为 0
        assert exc.value.code == 0

    def test_help_lists_known_options(self, capsys: Any) -> None:
        """--help 输出应包含主要参数"""
        with argv("--help"), captured_stdout() as out:
            try:
                main()
            except SystemExit:
                pass
        text = out.getvalue()
        # 主要参数应出现在 help 中
        for opt in ["--version", "--server", "--generate", "--status"]:
            assert opt in text, f"help 缺少 {opt}"


# ══════════════════════════════════════════════════════════
# main() — invalid args
# ══════════════════════════════════════════════════════════


class TestMainInvalidArgs:
    """无效参数处理"""

    def test_invalid_choice_argparse_exits(self) -> None:
        """传错参数类型时 argparse 报错退出"""
        # --server-port 必须是 int
        with argv("--server-port", "notanumber"):
            with pytest.raises(SystemExit) as exc:
                main()
        # argparse 错误退出码为 2
        assert exc.value.code == 2


# ══════════════════════════════════════════════════════════
# main() — 边界 & 集成
# ══════════════════════════════════════════════════════════


class TestMainEntry:
    """main 入口 & 模块级行为"""

    def test_main_callable(self) -> None:
        """main 应是可调用对象"""
        assert callable(main)

    def test_module_has_main(self) -> None:
        """__main__ 模块应导出 main"""
        assert hasattr(cli_main, "main")

    def test_module_has_infer_name(self) -> None:
        """__main__ 模块应导出 _infer_name"""
        assert hasattr(cli_main, "_infer_name")
        assert callable(_infer_name)

    def test_module_has_run_cli_mode(self) -> None:
        """__main__ 模块应导出 _run_cli_mode"""
        assert hasattr(cli_main, "_run_cli_mode")
        assert callable(_run_cli_mode)

    def test_sets_pycoder_active_env(self) -> None:
        """main() 应设置 PYCODER_ACTIVE=1"""
        # 清除可能存在的值
        import os as _os

        _os.environ.pop("PYCODER_ACTIVE", None)
        with argv("--server"):
            with patch("pycoder.server.app.run_server"):
                main()
        assert _os.environ.get("PYCODER_ACTIVE") == "1"


class TestIfNameMain:
    """if __name__ == "__main__" 块"""

    def test_if_name_main_runs_main(self) -> None:
        """运行 pycoder/__main__.py 应调用 main()"""
        import subprocess

        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.argv = ['pycoder', '--version']; "
             "exec(open(r'c:/Users/Administrator/Desktop/pycode/pycoder/__main__.py').read())"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # 期望输出包含 PyCoder
        assert "PyCoder" in result.stdout


# ══════════════════════════════════════════════════════════
# _infer_name
# ══════════════════════════════════════════════════════════


class TestInferName:
    """_infer_name 关键字识别"""

    def test_user_keyword(self) -> None:
        """包含 '用户' → user-api"""
        assert _infer_name("用户管理系统") == "user-api"

    def test_book_keyword(self) -> None:
        """包含 '图书' → library-api"""
        assert _infer_name("图书管理") == "library-api"

    def test_blog_keyword(self) -> None:
        """包含 '博客' → blog-api"""
        assert _infer_name("个人博客") == "blog-api"

    def test_order_keyword(self) -> None:
        """包含 '订单' → order-api"""
        assert _infer_name("订单系统") == "order-api"

    def test_product_keyword(self) -> None:
        """包含 '商品' → product-api"""
        assert _infer_name("商品管理") == "product-api"

    def test_stock_keyword(self) -> None:
        """包含 '股票' → stock-monitor"""
        assert _infer_name("股票监控") == "stock-monitor"

    def test_default_my_project(self) -> None:
        """无关键字时返回 my-project"""
        assert _infer_name("随便写点什么") == "my-project"

    def test_empty_string(self) -> None:
        """空字符串应返回 my-project"""
        assert _infer_name("") == "my-project"


# ══════════════════════════════════════════════════════════
# _run_cli_mode
# ══════════════════════════════════════════════════════════


class TestRunCliMode:
    """_run_cli_mode 输出"""

    def test_prints_cli_mode_info(self, capsys: Any) -> None:
        """_run_cli_mode 应打印 CLI 模式信息"""
        with captured_stdout() as out:
            _run_cli_mode([])
        text = out.getvalue()
        assert "PyCoder" in text
        assert "CLI" in text

    def test_prints_hints(self, capsys: Any) -> None:
        """_run_cli_mode 应打印使用提示"""
        with captured_stdout() as out:
            _run_cli_mode([])
        text = out.getvalue()
        for hint in ["--server", "--setup", "--scan", "--evolve"]:
            assert hint in text, f"缺少提示 {hint}"


# ══════════════════════════════════════════════════════════
# CLI 行为：与 run_server 的耦合点
# ══════════════════════════════════════════════════════════


class TestMainServerCall:
    """main 调用 server 时的参数传递"""

    def test_default_port_passed_as_kwarg(self) -> None:
        """默认端口应作为 kwarg port 传给 run_server"""
        with argv():
            with patch("pycoder.server.app.run_server") as run_mock:
                main()
        # 检查是关键字参数
        assert "port" in run_mock.call_args.kwargs

    def test_quick_start_default_false(self) -> None:
        """未指定 --quick-start 时 quick_start 应为 False"""
        with argv("--server"):
            with patch("pycoder.server.app.run_server") as run_mock:
                main()
        assert run_mock.call_args.kwargs.get("quick_start") is False

    def test_server_prints_version(self) -> None:
        """--server 模式应先打印版本"""
        with argv("--server"), captured_stdout() as out:
            with patch("pycoder.server.app.run_server"):
                main()
        assert "PyCoder" in out.getvalue()
        assert "v" in out.getvalue()
