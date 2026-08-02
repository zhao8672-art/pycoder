"""PyCoder 后端 PyInstaller 入口点

由 PyInstaller 打包时使用。打包版本默认使用 --quick-start 加速冷启动。

⚠️ 重要: 必须保留并转发原始 CLI 参数（特别是 --server-port），
   否则 Electron 传递的端口号会被忽略，导致端口冲突。
"""
import os
import sys


def main() -> None:
    """启动 PyCoder 后端服务。"""
    # 强制无缓冲输出（PyInstaller 打包时需要）
    os.environ.setdefault("PYTHONUNBUFFERED", "1")

    from pycoder.__main__ import main as cli_main

    # ── 解析参数: 保留 Electron 传入的 --server-port，仅追加缺失参数 ──
    raw_argv = sys.argv[1:]

    # 查找是否已存在 --server 和 --server-port
    has_server = "--server" in raw_argv
    has_port = any(a == "--server-port" for a in raw_argv)
    has_quick = "--quick-start" in raw_argv

    # 端口优先级: CLI > PYCODER_PORT 环境变量 > 默认 8423
    port = "8423"
    if has_port:
        idx = raw_argv.index("--server-port")
        if idx + 1 < len(raw_argv):
            port = raw_argv[idx + 1]
    else:
        port = os.environ.get("PYCODER_PORT", "8423")

    # 重建 argv: 保留原始参数，追加缺失的默认值
    new_argv = [sys.argv[0]] + list(raw_argv)
    if not has_server:
        new_argv.append("--server")
    if not has_port:
        new_argv += ["--server-port", port]
    if not has_quick:
        new_argv.append("--quick-start")
    sys.argv = new_argv

    # 转发到 __main__.main
    cli_main()


if __name__ == "__main__":
    main()
