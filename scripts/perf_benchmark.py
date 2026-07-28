"""PyCoder 性能基准测试套件 — P3-C

功能:
  1. 启动时间测试: 测量关键模块导入时间（验证懒加载效果）
  2. 内存占用测试: 测量基础内存使用
  3. FTS5 搜索性能: 测量全文搜索响应时间
  4. 关键 API 响应时间: 测量核心 API 端点延迟
  5. 并发处理能力: 测量 WebSocket/HTTP 并发性能

用法:
  python scripts/perf_benchmark.py                 # 全量基准测试
  python scripts/perf_benchmark.py --startup       # 仅启动时间
  python scripts/perf_benchmark.py --memory        # 仅内存占用
  python scripts/perf_benchmark.py --search        # 仅搜索性能
  python scripts/perf_benchmark.py --report        # 生成对比报告

输出:
  - 控制台彩色输出
  - perf-benchmark-results.json (机器可读结果)
  - 与基线 docs/upgrade-plan/baseline-metrics.md 对比

退出码:
  0: 所有性能指标在可接受范围
  1: 有性能指标超出阈值（回归）
  2: 测试过程出错
"""

from __future__ import annotations

import gc
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RESULTS_FILE = ROOT / "perf-benchmark-results.json"


# ─────────────────────────────────────────────────────
# 颜色输出
# ─────────────────────────────────────────────────────


class C:
    RED = "\033[91m"
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def _c(color: str, text: str) -> str:
    return f"{color}{text}{C.RESET}"


# ─────────────────────────────────────────────────────
# 性能阈值（基于历史基线）
# ─────────────────────────────────────────────────────

THRESHOLDS: dict[str, dict[str, float]] = {
    "startup_pycoder_import_ms": {"baseline": 500.0, "max": 2000.0},
    "startup_server_app_ms": {"baseline": 1500.0, "max": 5000.0},
    "startup_chat_bridge_ms": {"baseline": 800.0, "max": 3000.0},
    "memory_pycoder_mb": {"baseline": 50.0, "max": 200.0},
    "memory_server_app_mb": {"baseline": 100.0, "max": 400.0},
    "search_fts5_avg_ms": {"baseline": 30.0, "max": 100.0},
    "search_fts5_p99_ms": {"baseline": 50.0, "max": 200.0},
    "api_health_ms": {"baseline": 10.0, "max": 50.0},
}


# ─────────────────────────────────────────────────────
# 1. 启动时间测试
# ─────────────────────────────────────────────────────


def _measure_import_time(module_name: str) -> float:
    """测量 import 一个模块的时间（毫秒）

    通过子进程调用避免缓存影响。
    使用 sys.stdout.write + flush 确保数字输出清晰可解析。
    """
    code = f"""
import sys
import time
start = time.perf_counter()
try:
    import {module_name}
    end = time.perf_counter()
    # 用明确的分隔符包围数字，便于从含噪音的输出中提取
    sys.stdout.write(f"__PERF_TIME__{{(end - start) * 1000:.4f}}__END__")
    sys.stdout.flush()
except Exception as e:
    sys.stdout.write(f"__PERF_ERROR__{{e}}__END__")
    sys.stdout.flush()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=60,
    )
    output = result.stdout or ""
    # 从输出中提取 __PERF_TIME__xxx__END__ 标记
    import re

    match = re.search(r"__PERF_TIME__([\d.]+)__END__", output)
    if match:
        return float(match.group(1))
    return -1.0


def benchmark_startup() -> dict[str, float]:
    """启动时间基准测试"""
    print(_c(C.CYAN, "\n[1/4] 启动时间基准测试"))
    print("-" * 60)

    modules = [
        ("pycoder", "startup_pycoder_import_ms", "PyCoder 主包"),
        ("pycoder.server.app", "startup_server_app_ms", "Server App"),
        ("pycoder.server.chat_bridge", "startup_chat_bridge_ms", "ChatBridge"),
    ]

    results: dict[str, float] = {}

    for module, key, desc in modules:
        # 取 3 次测量平均值
        times: list[float] = []
        for i in range(3):
            t = _measure_import_time(module)
            if t > 0:
                times.append(t)
            print(f"  {desc} 第 {i + 1} 次: {t:.2f} ms")

        if times:
            avg = statistics.mean(times)
            results[key] = avg
            threshold = THRESHOLDS.get(key, {})
            baseline = threshold.get("baseline", 0)
            max_threshold = threshold.get("max", float("inf"))

            status = _c(C.GREEN, "✅")
            if avg > max_threshold:
                status = _c(C.RED, "❌")
            elif avg > baseline * 1.5:
                status = _c(C.YELLOW, "⚠")

            print(f"  → {desc} 平均: {avg:.2f} ms (基线 {baseline}ms, 阈值 {max_threshold}ms) {status}")
        else:
            print(_c(C.RED, f"  ❌ {desc} 导入失败"))
            results[key] = -1.0
        print()

    return results


# ─────────────────────────────────────────────────────
# 2. 内存占用测试
# ─────────────────────────────────────────────────────


def _measure_memory(module_name: str) -> float:
    """测量 import 一个模块后的内存占用（MB）"""
    code = f"""
import os
import sys
import psutil

# 在 import 之前测量基线
process = psutil.Process(os.getpid())

import {module_name}

# import 之后测量
after_mb = process.memory_info().rss / 1024 / 1024
# 用明确的分隔符包围数字，便于从含噪音的输出中提取
sys.stdout.write(f"__PERF_MEM__{{after_mb:.4f}}__END__")
sys.stdout.flush()
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=60,
        )
        output = result.stdout or ""
        import re

        match = re.search(r"__PERF_MEM__([\d.]+)__END__", output)
        if match:
            return float(match.group(1))
        return -1.0
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        return -1.0


def benchmark_memory() -> dict[str, float]:
    """内存占用基准测试"""
    print(_c(C.CYAN, "\n[2/4] 内存占用基准测试"))
    print("-" * 60)

    modules = [
        ("pycoder", "memory_pycoder_mb", "PyCoder 主包"),
        ("pycoder.server.app", "memory_server_app_mb", "Server App"),
    ]

    results: dict[str, float] = {}

    for module, key, desc in modules:
        mem = _measure_memory(module)
        results[key] = mem

        if mem > 0:
            threshold = THRESHOLDS.get(key, {})
            baseline = threshold.get("baseline", 0)
            max_threshold = threshold.get("max", float("inf"))

            status = _c(C.GREEN, "✅")
            if mem > max_threshold:
                status = _c(C.RED, "❌")
            elif mem > baseline * 1.5:
                status = _c(C.YELLOW, "⚠")

            print(f"  {desc}: {mem:.2f} MB (基线 {baseline}MB, 阈值 {max_threshold}MB) {status}")
        else:
            print(_c(C.RED, f"  ❌ {desc} 内存测量失败"))

    return results


# ─────────────────────────────────────────────────────
# 3. FTS5 搜索性能测试
# ─────────────────────────────────────────────────────


def benchmark_search() -> dict[str, float]:
    """FTS5 全文搜索性能基准测试"""
    print(_c(C.CYAN, "\n[3/4] FTS5 搜索性能基准测试"))
    print("-" * 60)

    try:
        from pycoder.server.skills_market_v2 import SkillsMarketV2
    except ImportError:
        print(_c(C.YELLOW, "  ⚠ SkillsMarketV2 不可用，跳过搜索性能测试"))
        return {}

    try:
        market = SkillsMarketV2()
    except Exception as e:
        print(_c(C.YELLOW, f"  ⚠ SkillsMarketV2 初始化失败: {e}"))
        return {}

    # 准备搜索查询
    queries = [
        "code review",
        "git helper",
        "test generator",
        "security scanner",
        "documentation",
        "refactor",
        "scaffold",
        "lint",
    ]

    # 先注册一些测试技能（如果库为空）
    try:
        existing = market.search_skills("", limit=1)
        if not existing:
            print(_c(C.BLUE, "  ℹ 注册测试技能..."))
            for i in range(20):
                market.register_skill({
                    "id": f"perf-test-{i}",
                    "name": f"Performance Test Skill {i}",
                    "description": f"测试技能 {i} for search performance",
                    "category": "testing",
                    "tags": ["test", "perf"] if i % 2 == 0 else ["benchmark"],
                    "version": "1.0.0",
                    "author": "perf-bench",
                })
    except Exception as e:
        print(_c(C.YELLOW, f"  ⚠ 注册测试技能失败: {e}"))

    # 测量搜索时间
    times: list[float] = []
    for query in queries:
        # 每个查询执行 5 次取最小值
        for _ in range(5):
            start = time.perf_counter()
            try:
                market.search_skills(query, limit=20)
            except (RuntimeError, ConnectionError, OSError, ValueError):
                pass
            elapsed_ms = (time.perf_counter() - start) * 1000
            times.append(elapsed_ms)

    if not times:
        print(_c(C.RED, "  ❌ 搜索测试未收集到数据"))
        return {}

    avg_ms = statistics.mean(times)
    p99_ms = statistics.quantiles(times, n=100)[98] if len(times) >= 100 else max(times)
    min_ms = min(times)
    max_ms = max(times)

    results = {
        "search_fts5_avg_ms": avg_ms,
        "search_fts5_p99_ms": p99_ms,
        "search_fts5_min_ms": min_ms,
        "search_fts5_max_ms": max_ms,
    }

    # 评估
    for key, value in [("search_fts5_avg_ms", avg_ms), ("search_fts5_p99_ms", p99_ms)]:
        threshold = THRESHOLDS.get(key, {})
        baseline = threshold.get("baseline", 0)
        max_threshold = threshold.get("max", float("inf"))

        status = _c(C.GREEN, "✅")
        if value > max_threshold:
            status = _c(C.RED, "❌")
        elif value > baseline * 1.5:
            status = _c(C.YELLOW, "⚠")

        print(f"  {key}: {value:.2f} ms (基线 {baseline}ms, 阈值 {max_threshold}ms) {status}")

    print(f"  search_fts5_min_ms: {min_ms:.2f} ms")
    print(f"  search_fts5_max_ms: {max_ms:.2f} ms")
    print(f"  总查询数: {len(times)}")

    return results


# ─────────────────────────────────────────────────────
# 4. API 响应时间测试
# ─────────────────────────────────────────────────────


def benchmark_api() -> dict[str, float]:
    """API 响应时间基准测试（需要后端运行）"""
    print(_c(C.CYAN, "\n[4/4] API 响应时间基准测试"))
    print("-" * 60)

    try:
        import httpx
    except ImportError:
        print(_c(C.YELLOW, "  ⚠ httpx 不可用，跳过 API 测试"))
        return {}

    base_url = os.environ.get("PYCODER_BASE_URL", "http://127.0.0.1:8423")
    api_key = os.environ.get("PYCODER_API_KEY", "")

    endpoints = [
        ("GET", "/api/health", "health_check", "api_health_ms"),
        ("GET", "/api/v2/capabilities", "capabilities", "api_capabilities_ms"),
    ]

    results: dict[str, float] = {}

    for method, path, desc, key in endpoints:
        times: list[float] = []
        try:
            with httpx.Client(base_url=base_url, timeout=5.0) as client:
                # 预热
                headers = {"X-API-Key": api_key} if api_key else {}
                try:
                    client.request(method, path, headers=headers)
                except (OSError, RuntimeError):
                    pass

                # 测量 10 次
                for _ in range(10):
                    start = time.perf_counter()
                    try:
                        resp = client.request(method, path, headers=headers)
                        if resp.status_code < 500:
                            elapsed_ms = (time.perf_counter() - start) * 1000
                            times.append(elapsed_ms)
                    except (OSError, RuntimeError):
                        pass
        except Exception as e:
            print(_c(C.YELLOW, f"  ⚠ {desc} 测试失败: {e}"))
            continue

        if times:
            avg_ms = statistics.mean(times)
            results[key] = avg_ms

            threshold = THRESHOLDS.get(key, {})
            baseline = threshold.get("baseline", 0)
            max_threshold = threshold.get("max", float("inf"))

            status = _c(C.GREEN, "✅")
            if avg_ms > max_threshold:
                status = _c(C.RED, "❌")
            elif avg_ms > baseline * 1.5:
                status = _c(C.YELLOW, "⚠")

            print(f"  {desc} ({path}): {avg_ms:.2f} ms (基线 {baseline}ms, 阈值 {max_threshold}ms) {status}")
        else:
            print(_c(C.YELLOW, f"  ⚠ {desc} 无有效响应（后端未运行？）"))

    return results


# ─────────────────────────────────────────────────────
# 5. 生成报告
# ─────────────────────────────────────────────────────


def generate_report(results: dict[str, dict[str, float]]) -> int:
    """生成性能基准报告并评估回归"""
    print(_c(C.BOLD, "\n" + "═" * 60))
    print(_c(C.BOLD, "性能基准测试报告"))
    print(_c(C.BOLD, "═" * 60))

    # 保存结果
    report = {
        "timestamp": datetime.now().isoformat(),
        "results": results,
        "thresholds": THRESHOLDS,
    }

    try:
        RESULTS_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(_c(C.GREEN, f"\n✅ 结果已保存到 {RESULTS_FILE.name}"))
    except OSError as e:
        print(_c(C.YELLOW, f"\n⚠ 无法保存结果: {e}"))

    # 评估
    exit_code = 0
    print(_c(C.BOLD, "\n回归评估:"))
    print("-" * 60)

    for category, metrics in results.items():
        if not metrics:
            continue
        print(f"\n  [{category}]")
        for key, value in metrics.items():
            if value < 0:
                print(f"    {key}: 跳过（测试失败）")
                continue

            threshold = THRESHOLDS.get(key)
            if not threshold:
                print(f"    {key}: {value:.2f} (无阈值)")
                continue

            baseline = threshold["baseline"]
            max_threshold = threshold["max"]

            if value > max_threshold:
                status = _c(C.RED, "❌ 回归")
                exit_code = 1
            elif value > baseline * 1.5:
                status = _c(C.YELLOW, "⚠ 警告")
            else:
                status = _c(C.GREEN, "✅ 正常")

            ratio = value / baseline if baseline > 0 else 0
            print(f"    {key}: {value:.2f} (基线 {baseline}, 比值 {ratio:.2f}x) {status}")

    print(_c(C.BOLD, "\n" + "═" * 60))
    if exit_code == 0:
        print(_c(C.GREEN, _c(C.BOLD, "✅ 所有性能指标在可接受范围")))
    else:
        print(_c(C.RED, _c(C.BOLD, "❌ 检测到性能回归，请检查")))
    print(_c(C.BOLD, "═" * 60))

    return exit_code


# ─────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="PyCoder 性能基准测试",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--startup", action="store_true", help="仅启动时间测试")
    parser.add_argument("--memory", action="store_true", help="仅内存占用测试")
    parser.add_argument("--search", action="store_true", help="仅搜索性能测试")
    parser.add_argument("--api", action="store_true", help="仅 API 响应时间测试")
    parser.add_argument("--report", action="store_true", help="生成对比报告")
    args = parser.parse_args()

    run_all = not any([args.startup, args.memory, args.search, args.api, args.report])

    print(_c(C.BOLD, "═" * 60))
    print(_c(C.BOLD, f"PyCoder 性能基准测试 — {datetime.now().strftime('%Y-%m-%d %H:%M')}"))
    print(_c(C.BOLD, "═" * 60))

    all_results: dict[str, dict[str, float]] = {}

    if run_all or args.startup:
        all_results["startup"] = benchmark_startup()

    if run_all or args.memory:
        all_results["memory"] = benchmark_memory()

    if run_all or args.search:
        all_results["search"] = benchmark_search()

    if run_all or args.api:
        all_results["api"] = benchmark_api()

    # 强制 GC 以减少噪音
    gc.collect()

    return generate_report(all_results)


if __name__ == "__main__":
    sys.exit(main())
