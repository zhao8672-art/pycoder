"""
PyCoder 进化闭环自动化脚本

实现"读取错误案例 → 分析问题 → 生成修复方案 → 沙箱测试 → 应用更新"的完整流程。

用法:
  python scripts/run_evolution.py              # 运行一次完整进化闭环
  python scripts/run_evolution.py --dry-run    # 干运行（不应用修改）
  python scripts/run_evolution.py --auto       # 自动应用修复
  python scripts/run_evolution.py --watch      # 启动持续监控模式
  python scripts/run_evolution.py --report     # 生成进化报告
  python scripts/run_evolution.py --stats      # 查看进化统计
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("evo_runner")


def print_banner():
    print("""
╔══════════════════════════════════════════════════════════╗
║           PyCoder 自我进化引擎 v2.0                       ║
║     observe → analyze → generate → validate → apply      ║
╚══════════════════════════════════════════════════════════╝
""")


def print_phase(phase: str, icon: str, detail: str = ""):
    """打印进化阶段"""
    detail_str = f" — {detail}" if detail else ""
    print(f"  {icon} [{phase}]{detail_str}")


def print_report(report):
    """打印进化报告"""
    print()
    print("=" * 60)
    print("  进化报告")
    print("=" * 60)
    print(f"  任务 ID:     {report.task_id}")
    print(f"  成功:        {'✅ 是' if report.success else '❌ 否'}")
    print(f"  完成阶段:    {', '.join(report.phases_completed)}")
    print(f"  发现问题:    {report.issues_found}")
    print(f"  生成修复:    {report.fixes_generated}")
    print(f"  应用修复:    {report.fixes_applied}")
    print(f"  测试通过:    {'✅ 是' if report.tests_passed else '❌ 否'}")
    print(f"  进化评分:    {report.grade:.1f}/100")
    print(f"  耗时:        {report.duration_ms:.0f}ms")
    if report.error:
        print(f"  错误:        {report.error}")
    if report.recommendations:
        print(f"  建议:")
        for rec in report.recommendations:
            print(f"    - {rec}")
    print("=" * 60)


async def run_once(args) -> int:
    """运行一次进化闭环"""
    from pycoder.evolution import EvolutionBrain, EvolutionPipeline

    print_banner()

    brain = EvolutionBrain()
    pipeline = EvolutionPipeline(brain)

    print_phase("开始", "🔍", f"模式: {'干运行' if args.dry_run else '自动' if args.auto else '手动'}")
    print()

    # 阶段 1: 观察
    print_phase("observe", "👁", "从 memory/observability 采集错误数据...")
    from pycoder.evolution.core import EvolutionTask
    task = EvolutionTask(
        task_type="auto_fix",
        target=args.target or "",
        description=args.desc or "",
    )
    task = await brain.observe(task)
    print(f"      采集到 {len(task.errors_collected)} 条错误/反馈")
    if task.errors_collected:
        for e in task.errors_collected[:3]:
            src = e.get("source", "unknown")
            content = str(e.get("content", ""))[:120]
            print(f"      [{src}] {content}...")

    if not task.errors_collected:
        print("      ⚠ 无错误数据，进化结束")
        return 0

    # 阶段 2: 分析
    print_phase("analyze", "🧠", "LLM 深度分析问题根因...")
    task = await brain.analyze(task)
    print(f"      分析结果: {len(task.llm_analysis)} 字符")
    if task.llm_analysis:
        for line in task.llm_analysis.split("\n")[:5]:
            if line.strip():
                print(f"      {line.strip()[:120]}")

    # 阶段 3: 生成
    print_phase("generate", "⚙", "生成修复方案...")
    task = await brain.generate(task)
    fix_count = len([m for m in __import__("re").finditer(r"\[FIX:", task.fix_plan)])
    print(f"      生成 {fix_count} 个修复方案")

    # 阶段 4: 验证
    print_phase("validate", "🛡", "safety 沙箱验证...")
    task = await brain.validate(task)
    if task.validation_result.get("passed"):
        print("      ✅ 验证通过")
    else:
        print(f"      ❌ 验证失败: {task.validation_result.get('reason', '未知')}")

    # 阶段 5: 应用
    if not args.dry_run and task.validation_result.get("passed"):
        print_phase("apply", "📝", "应用修复 + 运行测试...")
        brain._config.auto_apply = args.auto
        task = await brain.apply(task)
        if task.applied:
            print(f"      ✅ 修复已应用, 测试: {'通过' if task.test_passed else '失败'}")
        else:
            print(f"      ⚠ {task.error or '未应用修复'}")
    elif args.dry_run:
        print_phase("apply", "📝", "干运行模式 — 跳过应用")
    else:
        print_phase("apply", "📝", "验证未通过 — 跳过应用")

    # 阶段 6: 学习
    print_phase("learn", "📚", "经验沉淀到知识库...")
    task = await brain.learn(task)
    print(f"      {task.lessons[:200]}")

    # 完整报告
    report = await pipeline.run(
        task_type="auto_fix",
        target=args.target or "",
        description=args.desc or "",
        auto_apply=args.auto,
    )
    print_report(report)

    return 0 if report.success else 1


async def watch_mode(args) -> None:
    """持续监控模式 — 定期运行进化"""
    from pycoder.evolution import EvolutionBrain, EvolutionPipeline

    print_banner()
    print(f"  🔄 持续监控模式已启动 (间隔: {args.interval}s)")
    print(f"  按 Ctrl+C 停止")
    print()

    brain = EvolutionBrain()
    pipeline = EvolutionPipeline(brain)

    try:
        while True:
            print(f"\n--- 进化周期 {time.strftime('%H:%M:%S')} ---")
            report = await pipeline.run(
                task_type="auto_fix",
                auto_apply=args.auto,
            )
            print(f"  评分: {report.grade:.1f} | 发现: {report.issues_found} | 修复: {report.fixes_applied} | 耗时: {report.duration_ms:.0f}ms")
            await asyncio.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n\n  ⏹ 监控已停止")


def show_stats():
    """显示进化统计"""
    from pycoder.evolution import get_evolution_metrics

    metrics = get_evolution_metrics()
    summary = metrics.get_summary()

    print_banner()
    print("=" * 60)
    print("  进化统计")
    print("=" * 60)
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print("=" * 60)

    print("\n  最近趋势:")
    trend = metrics.get_trend_data(days=7)
    if trend:
        for t in trend:
            print(f"  {t['date']}: {t['count']}次进化, 成功率 {t['success_rate']}%, 均分 {t['avg_grade']}")
    else:
        print("  (无数据)")


def generate_report():
    """生成进化报告"""
    from pycoder.evolution import get_evolution_pipeline, get_evolution_metrics

    print_banner()

    pipeline = get_evolution_pipeline()
    metrics = get_evolution_metrics()

    reports = pipeline.get_reports(limit=10)
    summary = metrics.get_summary()

    print("=" * 60)
    print("  PyCoder 自我进化功能评估报告")
    print("=" * 60)
    print(f"  生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    print("  一、进化统计")
    print("  " + "-" * 40)
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print()
    print("  二、最近进化记录")
    print("  " + "-" * 40)
    if reports:
        for r in reports:
            status = "✅" if r["success"] else "❌"
            print(f"  {status} {r['task_id']}: 评分 {r['grade']:.1f} | 耗时 {r['duration_ms']:.0f}ms")
    else:
        print("  (暂无进化记录)")
    print()
    print("  三、趋势数据")
    print("  " + "-" * 40)
    trend = metrics.get_trend_data(days=7)
    if trend:
        for t in trend:
            bar = "█" * int(t["success_rate"] / 10)
            print(f"  {t['date']}: {bar} {t['success_rate']}% ({t['count']}次)")
    else:
        print("  (暂无趋势数据)")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="PyCoder 自我进化引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/run_evolution.py                  # 运行一次进化闭环
  python scripts/run_evolution.py --dry-run         # 干运行
  python scripts/run_evolution.py --auto            # 自动应用修复
  python scripts/run_evolution.py --watch            # 持续监控
  python scripts/run_evolution.py --report           # 生成报告
  python scripts/run_evolution.py --stats            # 查看统计
        """,
    )

    parser.add_argument("--dry-run", action="store_true", help="干运行，不实际修改代码")
    parser.add_argument("--auto", action="store_true", help="自动应用修复（需配合 --dry-run 的反义）")
    parser.add_argument("--watch", action="store_true", help="启动持续监控模式")
    parser.add_argument("--interval", type=int, default=3600, help="监控间隔（秒，默认 3600）")
    parser.add_argument("--report", action="store_true", help="生成进化报告")
    parser.add_argument("--stats", action="store_true", help="查看进化统计")
    parser.add_argument("--target", "-t", type=str, default="", help="目标文件或目录")
    parser.add_argument("--desc", "-d", type=str, default="", help="任务描述")

    args = parser.parse_args()

    if args.report:
        generate_report()
    elif args.stats:
        show_stats()
    elif args.watch:
        asyncio.run(watch_mode(args))
    else:
        exit_code = asyncio.run(run_once(args))
        sys.exit(exit_code)


if __name__ == "__main__":
    main()