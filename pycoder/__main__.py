"""
PyCoder CLI 入口

桌面版入口，启动 FastAPI 后端供 Electron 桌面端使用。
"""

import os
import sys

# Python 3.14+ Windows: 强制 UTF-8 避免 subprocess GBK 崩溃
if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# 自动加载 ~/.pycoder/.env 配置（JWT_SECRET / API_KEY 等）
# 注意: 使用直接赋值（非 setdefault），确保 .env 文件始终优先于
# 终端会话中残留的旧环境变量。
_env_path = os.path.join(os.path.expanduser("~"), ".pycoder", ".env")
if os.path.isfile(_env_path):
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ[_k.strip()] = _v.strip()

# 阶段 0 架构升级：显式触发 subprocess 兼容补丁安装
# （从 pycoder/__init__.py 的导入期副作用拆出，延迟到此处执行）
from pycoder import _install_subprocess_compat  # noqa: E402 — .env must be loaded before imports

_install_subprocess_compat()

import argparse  # noqa: E402 — .env must be loaded before imports

from pycoder.python.generate import _run_generate_mode  # noqa: E402


def main():
    """PyCoder CLI 入口"""
    os.environ["PYCODER_ACTIVE"] = "1"
    parser = argparse.ArgumentParser(
        description="PyCoder - 桌面端 AI 编程助手",
    )
    parser.add_argument(
        "--version",
        "-V",
        action="store_true",
        help="显示版本号",
    )
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        default=None,
        help="指定 AI 模型 (默认自动选择)",
    )
    parser.add_argument(
        "--server",
        action="store_true",
        help="启动 App Server (FastAPI + WebSocket)",
    )
    parser.add_argument(
        "--server-port",
        type=int,
        default=8423,
        help="Server 端口 (默认 8423)",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="运行 API Key 配置向导",
    )
    parser.add_argument(
        "--env",
        action="store_true",
        help="显示当前 Python 环境信息",
    )
    parser.add_argument(
        "--cost",
        action="store_true",
        help="显示费用报告",
    )
    parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="传递给 Aider 的参数（兼容模式）",
    )
    parser.add_argument(
        "--generate",
        "-g",
        type=str,
        metavar="DESCRIPTION",
        help="一键生成完整项目 (例如: --generate 'FastAPI 用户管理系统')",
    )
    parser.add_argument(
        "--project-dir",
        "-o",
        type=str,
        default="",
        help="生成项目的目标目录 (默认使用当前目录)",
    )
    parser.add_argument(
        "--list-templates",
        action="store_true",
        help="列出所有可用的项目模板",
    )
    parser.add_argument(
        "--autonomous",
        "-a",
        action="store_true",
        help="启动全自主开发模式 (配合 --task 使用)",
    )
    parser.add_argument(
        "--task",
        "-t",
        type=str,
        metavar="DESCRIPTION",
        help="全自主开发任务描述 (例如: '做一个FastAPI用户管理系统')",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="显示 API Key 和模型配置状态",
    )
    parser.add_argument(
        "--evolve",
        action="store_true",
        help="启动自我进化模式: 扫描 → 分析 → 修复 → 测试",
    )
    parser.add_argument(
        "--scan",
        type=str,
        nargs="?",
        const="pycoder",
        metavar="PATH",
        help="扫描代码库并生成问题报告 (默认: pycoder/)",
    )
    parser.add_argument(
        "--evolve-path",
        type=str,
        default="pycoder",
        help="自进化扫描路径 (默认: pycoder/)",
    )

    args, unknown = parser.parse_known_args()

    # 版本
    if args.version:
        from pycoder import __version__

        print(f"PyCoder v{__version__}")
        sys.exit(0)

    # 模型/Key 状态
    if args.status:
        from pycoder.providers.auth import get_model_manager

        mgr = get_model_manager()
        print(mgr.format_status())
        sys.exit(0)

    # 环境检测
    if args.env:
        from pycoder.providers.auth import get_model_manager
        from pycoder.python.env_detector import detect_environment, print_env_info

        info = detect_environment()
        print(print_env_info(info))
        print()
        mgr = get_model_manager()
        print(mgr.format_status())
        sys.exit(0)

    # 费用报告
    if args.cost:
        from pycoder.providers.cost import get_cost_tracker

        tracker = get_cost_tracker()
        print(tracker.format_report())
        sys.exit(0)

    # 列出模板
    if args.list_templates:
        from pycoder.python.scaffold import list_templates

        templates = list_templates()
        print("\n📦 可用的项目模板:\n")
        for t in templates:
            print(f"  🏷  {t.display_name}")
            print(f"     ID: {t.name}  |  分类: {t.category}")
            print(f"     {t.description}")
            print(f"     启动: {t.run_command}")
            print()
        sys.exit(0)

    # 一键生成
    if args.generate:
        _run_generate_mode(args.generate, args.project_dir)
        return

    # 配置向导
    if args.setup:
        from pycoder.providers.setup_wizard import get_setup_guide

        print(get_setup_guide())
        sys.exit(0)

    # 全自主开发模式
    if args.autonomous and args.task:
        _run_autonomous_mode(args.task, args.model, args.server_port)
        return

    # 自我进化模式
    if args.evolve:
        _run_evolution_mode(args.evolve_path)
        return

    # 代码扫描
    if args.scan:
        _run_scan_mode(args.scan)
        return

    # App Server (默认模式)
    if args.server or not unknown:
        from pycoder.server.app import run_server

        print(f"PyCoder v{__import__('pycoder').__version__} — V2 AI-Centric Engine")
        run_server(port=args.server_port)
        return

    # 其他参数 -> CLI 模式
    _run_cli_mode(unknown + args.args)


def _run_autonomous_mode(task: str, model: str | None, port: int) -> None:
    """全自主开发模式 — 启动 Server 并通过流水线自动执行任务"""
    import asyncio

    from pycoder.server.services.autonomous_pipeline import AutonomousPipeline

    print(f"\n{'=' * 60}")
    print("  PyCoder 全自主开发模式")
    print(f"{'=' * 60}")
    print(f"  任务: {task[:100]}")
    print(f"  模型: {model or 'deepseek-chat'}")
    print(f"{'=' * 60}\n")

    async def _execute():
        pipeline = AutonomousPipeline()
        step_count = 0
        async for event in pipeline.run(task):
            etype = event.get("type", "")
            if etype == "phase":
                step_count += 1
                print(f"\n  [{step_count}/7] {event.get('message', '')}")
            elif etype == "agent_done":
                files = event.get("files", [])
                print(f"    生成文件: {len(files)} 个")
                for f in files[:5]:
                    print(f"      📄 {f}")
                if len(files) > 5:
                    print(f"      ... 等共 {len(files)} 个文件")
            elif etype == "quality_report":
                r = event.get("report", {})
                print(f"    质量评分: {r.get('average_score', 'N/A')}")
            elif etype == "test_result":
                r = event.get("result", {})
                print(f"    测试: {r.get('total_passed', 0)}/" f"{r.get('total_tests', 0)} 通过")
            elif etype == "acceptance":
                print(f"    验收: {'✅ 通过' if event.get('passed') else '❌ 未通过'}")
            elif etype == "delivery":
                pkg = event.get("package", {})
                print(f"    交付: {pkg.get('files_count', 0)} 个文件")
            elif etype == "done":
                report = event.get("report", {})
                print(f"\n{'=' * 60}")
                print("  ✅ 流水线执行完成!")
                print(f"  项目: {report.get('project_name', '')}")
                print(f"  文件: {report.get('total_files', 0)} 个")
                print(f"  耗时: {report.get('duration_seconds', 0)} 秒")
                print(f"{'=' * 60}\n")
            elif etype == "error":
                print(f"  ❌ 错误: {event.get('message', '')}")

    asyncio.run(_execute())


def _infer_name(desc: str) -> str:
    keywords = {
        "用户": "user-api",
        "图书": "library-api",
        "博客": "blog-api",
        "订单": "order-api",
        "商品": "product-api",
        "股票": "stock-monitor",
    }
    for kw, name in keywords.items():
        if kw in desc:
            return name
    return "my-project"


def _run_cli_mode(argv: list[str]) -> None:
    """CLI 兼容模式"""
    from pycoder.config.settings import get_config

    config = get_config()

    print(f"PyCoder {config.get('version', '0.5.0')} - CLI 模式")
    print(f"模型: {config.get('provider', {}).get('default', 'auto')}")
    print(f"Python: {sys.version.split()[0]}")
    print()
    print("提示: 使用 --server 启动 API 后端")
    print("      使用 --setup 配置 API Key")
    print("      使用 --scan 扫描代码库")
    print("      使用 --evolve 启动自我进化")
    print("      桌面端: cd pycoder/electron && npm run start")


def _run_scan_mode(path: str) -> None:
    """代码扫描模式 — 分析代码库并生成问题报告"""
    import asyncio

    from pycoder.v2 import V2Engine, V2EngineConfig

    print("\n  PyCoder V2 代码扫描")
    print(f"  路径: {path}")
    print()

    async def _scan():
        engine = V2Engine(V2EngineConfig(workspace_root=os.getcwd()))
        await engine.initialize()

        if engine.evolution is None:
            print("  错误: 自我进化引擎未初始化")
            return

        print("  正在扫描...")
        report = await engine.evolution.scan(path, use_llm=False)
        print(
            f"  完成: {report.files_scanned} 个文件, {report.total_issues} 个问题 ({report.duration_seconds:.1f}s)"
        )
        print()

        if report.total_issues == 0:
            print("  No issues found.")
            return

        # 按严重度分组
        from collections import Counter

        sev = Counter(i.severity for i in report.issues)

        print("  严重度分布:")
        for level in ["critical", "high", "medium", "low"]:
            count = sev.get(level, 0)
            if count > 0:
                icon = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}[
                    level
                ]
                print(f"    [{icon}] {count} 个")

        print("\n  问题详情 (前 15 个):")
        for i, issue in enumerate(report.issues[:15], 1):
            print(f"  {i:>3}. [{issue.severity}] {issue.file}:{issue.line}")
            print(f"       {issue.title}")
            if issue.suggestion:
                print(f"       建议: {issue.suggestion}")

    asyncio.run(_scan())


def _run_evolution_mode(path: str) -> None:
    """自我进化模式 — 扫描并自动修复问题"""
    import asyncio

    from pycoder.capabilities.self_evo.engine import EvolutionRecord
    from pycoder.v2 import V2Engine, V2EngineConfig

    print(f"\n{'=' * 60}")
    print("  PyCoder V2 自我进化模式")
    print(f"  路径: {path}")
    print(f"{'=' * 60}\n")

    async def _evolve():
        engine = V2Engine(V2EngineConfig(workspace_root=os.getcwd(), enable_self_evo=True))
        await engine.initialize()

        if engine.evolution is None:
            print("  错误: 自我进化引擎未初始化")
            return

        # Step 1: 扫描
        print("  [1/4] 扫描代码库...")
        report = await engine.evolution.scan(path, use_llm=False)
        print(f"        发现 {report.total_issues} 个问题 ({report.files_scanned} 文件)")
        print()

        if report.total_issues == 0:
            print("  No issues found.")
            return

        # Step 2: 生成修复方案
        print("  [2/4] 生成修复方案...")
        proposals = []
        for issue in report.issues[:5]:  # 每次最多处理 5 个
            if issue.severity in ("critical", "high"):
                p = await engine.evolution.generate_fix(issue)
                proposals.append(p)
                print(f"        [{p.action}] {issue.file}:{issue.line} — {issue.title[:60]}")
        print(f"        生成了 {len(proposals)} 个修复方案")
        print()

        if not proposals:
            print("  无可自动修复的问题。")
            return

        # Step 3: 应用修复（仅应用模板修复，跳过需要 LLM 的）
        print("  [3/4] 应用修复...")
        applied = 0
        for p in proposals:
            if p.risk_level == "low" and p.old_code and p.new_code:
                result = await engine.evolution.apply_fix(p)
                if result.success:
                    applied += 1
                    print(f"        已修复: {p.file_path}")
                    engine.evolution.record_evolution(
                        EvolutionRecord(
                            action="apply_fix",
                            issue_type=p.issue.issue_type,
                            file=p.file_path,
                            success=True,
                            fix_description=p.reasoning[:200],
                            test_result="passed" if result.test_passed else "failed",
                        )
                    )
                else:
                    print(f"        跳过: {p.file_path} — {result.error or '测试未通过'}")
            else:
                print(f"        跳过: {p.file_path} — 需要 LLM 生成修复方案")

        print(f"        成功应用 {applied} 个修复")
        print()

        # Step 4: 报告
        print("  [4/4] 进化报告:")
        stats = engine.evolution.get_stats()
        print(f"        总进化次数: {stats['total_evolutions']}")
        print(f"        本次修复: {applied} 个")
        print()
        print(f"{'=' * 60}")
        print("  自我进化完成!")
        print(f"{'=' * 60}")

    asyncio.run(_evolve())


if __name__ == "__main__":
    main()
