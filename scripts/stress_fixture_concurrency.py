"""高并发 fixture 竞争压测脚本

专门验证 fresh_store fixture 修复 (tmp_path 隔离 + 全局单例 patch)
在高并发场景下的稳定性。修复前的固定 test_data 目录路径会在
xdist 并行时被多 worker 同时 mkdir/rmdir 导致竞争; 修复后每个
测试用 pytest 内置 tmp_path 获得唯一隔离的 SessionStore。

测试维度:
  1. xdist 进程级并行压测: 高 worker 数重复运行 test_session_store.py,
     捕获间歇性竞争失败 (flake)。
  2. SessionStore 实例隔离验证: 同一进程内创建大量独立 store (各自
     临时 db 路径), 验证数据不串台 —— 这是 tmp_path 隔离的核心保证。
  3. 单例并发线程安全: 多线程共享全局 store 做并发 CRUD, 验证
     SessionStore 的线程安全 (threading.local + 连接池 + 锁)。
  4. 残留物泄漏检测: 扫描 test_data 目录 / 孤儿 sessions.db /
     .coverage.* 并行文件, 确保修复后无遗留。

用法:
  python scripts/stress_fixture_concurrency.py
  python scripts/stress_fixture_concurrency.py --workers 32 --rounds 5
  python scripts/stress_fixture_concurrency.py --skip-xdist   # 跳过 subprocess 压测
  python scripts/stress_fixture_concurrency.py --only isolation  # 仅运行指定阶段

退出码:
  0: 所有压测通过, 无竞争/泄漏
  1: 检测到竞争或泄漏
  2: 脚本错误
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RESULTS_FILE = ROOT / "stress-fixture-results.json"


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
# 结果收集
# ─────────────────────────────────────────────────────


class PhaseResult:
    """单个压测阶段结果"""

    def __init__(self, name: str, phase: str) -> None:
        self.name = name
        self.phase = phase
        self.passed = False
        self.error_message = ""
        self.duration_ms = 0.0
        self.details: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "phase": self.phase,
            "passed": self.passed,
            "error_message": self.error_message,
            "duration_ms": self.duration_ms,
            "details": self.details,
        }


# ─────────────────────────────────────────────────────
# 阶段 1: xdist 进程级并行压测
# ─────────────────────────────────────────────────────


def phase_xdist_stress(workers: int, rounds: int) -> list[PhaseResult]:
    """高 worker 数重复运行 test_session_store.py, 捕获间歇性竞争。

    xdist 每个 worker 是独立进程, 拥有独立内存空间, 因此
    _db_initialized 类标志和 _store 全局单例都是进程隔离的。
    本阶段验证 fixture 在真实并行条件下的稳定性。
    """
    results: list[PhaseResult] = []
    test_file = "tests/test_session_store.py"

    print(_c(C.CYAN, f"\n[阶段 1] xdist 进程级并行压测 ({workers} workers × {rounds} 轮)"))
    print("-" * 60)

    total_pass = 0
    total_fail = 0
    flaky_detected = False
    per_round_stats: list[dict[str, Any]] = []

    for rnd in range(1, rounds + 1):
        result = PhaseResult(f"xdist_round_{rnd}", "xdist")
        start = time.perf_counter()

        # 构造 pytest 命令: 高 worker 数 + loadfile 分配 + 超时保护
        cmd = [
            sys.executable, "-m", "pytest", test_file,
            "-n", str(workers),
            "--dist=loadfile",
            "--timeout=60",
            "-ra", "--tb=short",
            "-q",
            "-p", "no:cacheprovider",  # 禁用缓存避免跨轮干扰
        ]

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
            )
            duration_ms = (time.perf_counter() - start) * 1000

            # 解析结果: pytest -q 输出末尾形如 "9 passed in 5.30s"
            tail = (proc.stdout or "") + (proc.stderr or "")
            passed = proc.returncode == 0

            if passed:
                total_pass += 1
                status = _c(C.GREEN, "✅ 通过")
            else:
                total_fail += 1
                status = _c(C.RED, "❌ 失败")

            result.passed = passed
            result.duration_ms = duration_ms
            result.details = {
                "round": rnd,
                "returncode": proc.returncode,
                "tail": tail.strip().split("\n")[-3:] if tail.strip() else [],
            }
            if not passed:
                result.error_message = tail.strip().split("\n")[-1] if tail.strip() else "unknown"

            print(f"  轮次 {rnd}/{rounds}: {status} ({duration_ms:.0f}ms)")
        except subprocess.TimeoutExpired:
            duration_ms = (time.perf_counter() - start) * 1000
            result.passed = False
            result.duration_ms = duration_ms
            result.error_message = "subprocess 超时 (>180s)"
            result.details = {"round": rnd, "timeout": True}
            total_fail += 1
            print(f"  轮次 {rnd}/{rounds}: {_c(C.RED, '❌ 超时')} ({duration_ms:.0f}ms)")
        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            result.passed = False
            result.duration_ms = duration_ms
            result.error_message = f"{type(e).__name__}: {e}"
            total_fail += 1
            print(f"  轮次 {rnd}/{rounds}: {_c(C.RED, '❌ 错误')} {e}")

        per_round_stats.append(result.to_dict())
        results.append(result)

    # 检测 flake: 如果有失败也有通过, 说明间歇性竞争
    if total_pass > 0 and total_fail > 0:
        flaky_detected = True

    print(f"\n  汇总: {total_pass} 通过, {total_fail} 失败"
          + (_c(C.YELLOW, " ⚠ 检测到 flake (间歇性竞争)") if flaky_detected else ""))

    # 清理本轮可能产生的 coverage 并行文件
    for f in ROOT.glob(".coverage.*"):
        try:
            f.unlink()
        except OSError:
            pass

    return results


# ─────────────────────────────────────────────────────
# 阶段 2: SessionStore 实例隔离验证
# ─────────────────────────────────────────────────────


def phase_instance_isolation(instances: int) -> list[PhaseResult]:
    """同一进程内创建大量独立 SessionStore, 验证数据不串台。

    模拟 fixture 的核心行为: 每次用唯一临时 db 路径创建独立 store。
    验证每个 store 只能看到自己创建的 session, 不会看到其他 store
    的数据 —— 这是 tmp_path 隔离修复的核心保证。

    注意: SessionStore._db_initialized 是类级标志, 同进程内创建多个
    实例时需重置该标志, 否则只有第一个实例会建表。fixture 已处理此点,
    本阶段复现相同逻辑以验证正确性。
    """
    result = PhaseResult("instance_isolation", "isolation")
    start = time.perf_counter()

    print(_c(C.CYAN, f"\n[阶段 2] SessionStore 实例隔离验证 ({instances} 个独立 store)"))
    print("-" * 60)

    import pycoder.server.session_store as ss_module

    stores: list[tuple[Any, Path, set[str]]] = []
    created_dirs: list[Path] = []
    original_store = ss_module._store

    try:
        # 创建 N 个独立 store, 每个有自己的临时 db 路径
        for i in range(instances):
            tmp_dir = Path(tempfile.mkdtemp(prefix=f"iso_{i}_"))
            created_dirs.append(tmp_dir)
            db_path = tmp_dir / "sessions.db"

            # 重置类级标志 (与 fixture 一致), 确保新实例在新路径建表
            ss_module.SessionStore._db_initialized = False
            store = ss_module.SessionStore(db_path=str(db_path))

            # 每个 store 创建 3 个 session, 记录 id
            session_ids: set[str] = set()
            for j in range(3):
                s = store.create_session(model=f"iso_{i}_model_{j}")
                session_ids.add(s.id)
                store.add_message(s.id, "user", f"msg from store {i} session {j}")

            stores.append((store, tmp_dir, session_ids))

        # 验证隔离性: 每个 store 只能看到自己的 3 个 session
        leakage_count = 0
        for i, (store, _tmp, expected_ids) in enumerate(stores):
            listed = store.list_sessions(limit=100)
            listed_ids = {s.id for s in listed}
            # 不应有多余 session (泄漏)
            if listed_ids != expected_ids:
                leakage_count += 1
                if leakage_count <= 3:
                    extra = listed_ids - expected_ids
                    missing = expected_ids - listed_ids
                    print(_c(C.RED, f"    store {i} 数据串台: extra={extra}, missing={missing}"))

        # 再次验证: get_session 不应能取到其他 store 的 session
        cross_access_count = 0
        for i, (store, _tmp, _ids) in enumerate(stores):
            other_store_idx = (i + 1) % len(stores)
            other_ids = stores[other_store_idx][2]
            for oid in other_ids:
                if store.get_session(oid) is not None:
                    cross_access_count += 1

        result.duration_ms = (time.perf_counter() - start) * 1000
        result.details = {
            "instances": instances,
            "sessions_per_store": 3,
            "leakage_count": leakage_count,
            "cross_access_count": cross_access_count,
        }

        if leakage_count == 0 and cross_access_count == 0:
            result.passed = True
            print(f"  {_c(C.GREEN, '✅ 通过')}: {instances} 个 store 完全隔离, 无数据串台")
        else:
            result.passed = False
            result.error_message = f"隔离失败: {leakage_count} store 数据串台, {cross_access_count} 跨访问"
            print(f"  {_c(C.RED, '❌ 失败')}: {result.error_message}")

    except Exception as e:
        result.passed = False
        result.duration_ms = (time.perf_counter() - start) * 1000
        result.error_message = f"{type(e).__name__}: {e}"
        print(f"  {_c(C.RED, '❌ 错误')}: {e}")
    finally:
        # 清理: 关闭所有 store, 恢复全局状态, 删除临时目录
        for store, _tmp, _ids in stores:
            try:
                store.close()
            except Exception:
                pass
        ss_module._store = original_store
        ss_module.SessionStore._db_initialized = original_store is not None
        for d in created_dirs:
            shutil.rmtree(d, ignore_errors=True)

    return [result]


# ─────────────────────────────────────────────────────
# 阶段 3: 单例并发线程安全
# ─────────────────────────────────────────────────────


def phase_singleton_thread_safety(threads: int, ops: int) -> list[PhaseResult]:
    """多线程共享全局 store 做并发 CRUD, 验证 SessionStore 线程安全。

    SessionStore 使用 threading.local 缓存连接 + 连接池 + 初始化锁。
    本阶段在共享单例上压测并发 create/add_message/list/delete,
    验证无线程安全崩溃、无丢失写入。
    """
    result = PhaseResult("singleton_thread_safety", "thread_safety")
    start = time.perf_counter()

    print(_c(C.CYAN, f"\n[阶段 3] 单例并发线程安全 ({threads} 线程 × {ops} ops/线程)"))
    print("-" * 60)

    import pycoder.server.session_store as ss_module

    tmp_dir = Path(tempfile.mkdtemp(prefix="thread_safety_"))
    original_store = ss_module._store
    created_session_ids: set[str] = set()
    ids_lock = threading.Lock()
    errors: list[str] = []
    errors_lock = threading.Lock()

    try:
        # 创建共享 store (重置标志确保建表)
        ss_module.SessionStore._db_initialized = False
        shared_store = ss_module.SessionStore(db_path=str(tmp_dir / "shared.db"))
        ss_module._store = shared_store

        def worker(thread_id: int) -> tuple[int, int, int]:
            """每个线程做 ops 轮 create + add_message + get_session。

            返回 (thread_id, created_count, error_count)。
            """
            created = 0
            errs = 0
            for op in range(ops):
                try:
                    s = shared_store.create_session(model=f"t{thread_id}_m{op}")
                    with ids_lock:
                        created_session_ids.add(s.id)
                    shared_store.add_message(s.id, "user", f"thread {thread_id} op {op}")
                    fetched = shared_store.get_session(s.id)
                    if fetched is None or fetched.id != s.id:
                        errs += 1
                        with errors_lock:
                            if len(errors) < 10:
                                errors.append(f"t{thread_id} op{op}: get_session 返回不一致")
                    created += 1
                except Exception as e:
                    errs += 1
                    with errors_lock:
                        if len(errors) < 10:
                            errors.append(f"t{thread_id} op{op}: {type(e).__name__}: {e}")
            return thread_id, created, errs

        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = [executor.submit(worker, t) for t in range(threads)]
            worker_results = [f.result() for f in as_completed(futures)]

        total_created = sum(r[1] for r in worker_results)
        total_errors = sum(r[2] for r in worker_results)

        # 验证: 列出的 session 总数应 == 创建的总数 (无丢失)
        listed = shared_store.list_sessions(limit=threads * ops + 100)
        listed_count = len(listed)

        # 验证: 每个 session 的消息可取回
        msg_check_fail = 0
        for s in listed[:50]:  # 抽样检查前 50 个
            msgs = shared_store.get_messages(s.id)
            if len(msgs) < 1:
                msg_check_fail += 1

        result.duration_ms = (time.perf_counter() - start) * 1000
        result.details = {
            "threads": threads,
            "ops_per_thread": ops,
            "total_created": total_created,
            "total_errors": total_errors,
            "listed_count": listed_count,
            "msg_check_failures": msg_check_fail,
            "sample_errors": errors[:5],
        }

        # 通过条件: 无错误 + 列出数 >= 创建数 (允许少量并发可见性延迟)
        if total_errors == 0 and listed_count >= total_created and msg_check_fail == 0:
            result.passed = True
            print(f"  {_c(C.GREEN, '✅ 通过')}: {total_created} 次并发 CRUD 全部成功, "
                  f"列出 {listed_count} 条, 无丢失")
        else:
            result.passed = False
            result.error_message = (f"错误 {total_errors}, 创建 {total_created}, "
                                    f"列出 {listed_count}, 消息检查失败 {msg_check_fail}")
            print(f"  {_c(C.RED, '❌ 失败')}: {result.error_message}")
            if errors:
                print(f"    样例错误: {errors[0]}")

    except Exception as e:
        result.passed = False
        result.duration_ms = (time.perf_counter() - start) * 1000
        result.error_message = f"{type(e).__name__}: {e}"
        print(f"  {_c(C.RED, '❌ 错误')}: {e}")
    finally:
        try:
            shared_store.close()
        except Exception:
            pass
        ss_module._store = original_store
        ss_module.SessionStore._db_initialized = original_store is not None
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return [result]


# ─────────────────────────────────────────────────────
# 阶段 4: 残留物泄漏检测
# ─────────────────────────────────────────────────────


def phase_leak_detection() -> list[PhaseResult]:
    """扫描项目残留物: test_data 目录 / 孤儿 sessions.db / .coverage.* 文件。

    修复前 fresh_store 会在 tests/ 下创建固定 test_data 目录, xdist
    并行时多 worker 竞争导致残留。修复后应无此目录。
    """
    result = PhaseResult("leak_detection", "leak")
    start = time.perf_counter()

    print(_c(C.CYAN, "\n[阶段 4] 残留物泄漏检测"))
    print("-" * 60)

    leaks: list[str] = []

    try:
        # 1. tests/test_data 目录 (旧 fixture 残留)
        test_data_dir = ROOT / "tests" / "test_data"
        if test_data_dir.exists():
            leaks.append(f"tests/test_data 目录存在 (旧 fixture 残留): {test_data_dir}")

        # 2. 项目根/ tests 下的孤儿 sessions.db* 文件 (非临时目录)
        for pattern in ["sessions.db", "sessions.db-wal", "sessions.db-shm"]:
            for f in ROOT.glob(f"**/{pattern}"):
                # 排除 .venv / node_modules / 临时目录
                parts = f.parts
                if any(p.startswith(".") or p in ("node_modules", "build", "dist")
                       for p in parts):
                    continue
                # 排除合理的 data 目录
                if "data" in parts and "skills" not in parts:
                    continue
                leaks.append(f"孤儿 {pattern}: {f.relative_to(ROOT)}")

        # 3. .coverage.* 并行文件残留 (pytest-cov 应已合并清理)
        cov_files = list(ROOT.glob(".coverage.*"))
        if cov_files:
            # 1 个 .coveragerc 是配置文件, 不算; 其余 .coverage.<host>.<pid> 是残留
            stale = [f for f in cov_files if f.name != ".coveragerc"]
            if stale:
                leaks.append(f"{len(stale)} 个 .coverage.* 并行文件残留: "
                             + ", ".join(f.name for f in stale[:5]))

        # 4. tests/ 下的临时 .db 文件
        for f in (ROOT / "tests").glob("*.db*"):
            leaks.append(f"tests/ 下临时 db 文件: {f.name}")

        result.duration_ms = (time.perf_counter() - start) * 1000
        result.details = {"leak_count": len(leaks), "leaks": leaks[:10]}

        if not leaks:
            result.passed = True
            print(f"  {_c(C.GREEN, '✅ 通过')}: 无残留物泄漏")
        else:
            result.passed = False
            result.error_message = f"检测到 {len(leaks)} 处泄漏"
            print(f"  {_c(C.RED, '❌ 失败')}: 检测到 {len(leaks)} 处泄漏:")
            for leak in leaks[:10]:
                print(f"    - {leak}")

    except Exception as e:
        result.passed = False
        result.duration_ms = (time.perf_counter() - start) * 1000
        result.error_message = f"{type(e).__name__}: {e}"
        print(f"  {_c(C.RED, '❌ 错误')}: {e}")

    return [result]


# ─────────────────────────────────────────────────────
# 报告生成
# ─────────────────────────────────────────────────────


def generate_report(all_results: list[PhaseResult]) -> int:
    """生成压测报告, 返回退出码 (0=全通过, 1=有失败)"""
    print(_c(C.BOLD, "\n" + "═" * 60))
    print(_c(C.BOLD, "高并发 fixture 竞争压测报告"))
    print(_c(C.BOLD, "═" * 60))

    report = {
        "timestamp": datetime.now().isoformat(),
        "phases": {},
    }
    total_passed = 0
    total_failed = 0

    # 按阶段分组
    phases: dict[str, list[PhaseResult]] = {}
    for r in all_results:
        phases.setdefault(r.phase, []).append(r)

    for phase, results in phases.items():
        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed)
        report["phases"][phase] = {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "results": [r.to_dict() for r in results],
        }
        total_passed += passed
        total_failed += failed

    try:
        RESULTS_FILE.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(_c(C.GREEN, f"\n✅ 结果已保存到 {RESULTS_FILE.name}"))
    except OSError as e:
        print(_c(C.YELLOW, f"\n⚠ 无法保存结果: {e}"))

    print(_c(C.BOLD, "\n汇总:"))
    print("-" * 60)
    for phase, results in phases.items():
        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed)
        total = len(results)
        status = _c(C.GREEN, "✅") if failed == 0 else _c(C.RED, "❌")
        print(f"  {phase:<20} {passed}/{total} 通过 {status}")

    print(_c(C.BOLD, "\n" + "═" * 60))
    print(f"  总计: {total_passed} 通过, {total_failed} 失败")
    if total_failed == 0:
        print(_c(C.GREEN, _c(C.BOLD, "✅ 高并发场景下 fixture 修复稳定, 无竞争/泄漏")))
        print(_c(C.BOLD, "═" * 60))
        return 0
    else:
        print(_c(C.RED, _c(C.BOLD, f"❌ 检测到 {total_failed} 项失败, 存在竞争/泄漏风险")))
        print(_c(C.BOLD, "═" * 60))
        return 1


# ─────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="高并发 fixture 竞争压测",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--workers", type=int, default=max(8, (os.cpu_count() or 4) * 2),
                        help="xdist worker 数 (默认: 2×CPU)")
    parser.add_argument("--rounds", type=int, default=3,
                        help="xdist 重复轮数 (默认: 3)")
    parser.add_argument("--instances", type=int, default=50,
                        help="隔离验证的 store 实例数 (默认: 50)")
    parser.add_argument("--threads", type=int, default=16,
                        help="线程安全测试的线程数 (默认: 16)")
    parser.add_argument("--ops", type=int, default=20,
                        help="每线程操作数 (默认: 20)")
    parser.add_argument("--skip-xdist", action="store_true",
                        help="跳过 xdist subprocess 压测 (更快)")
    parser.add_argument("--skip-thread", action="store_true",
                        help="跳过线程安全测试")
    parser.add_argument("--only", choices=["xdist", "isolation", "thread_safety", "leak"],
                        help="仅运行指定阶段")
    args = parser.parse_args()

    print(_c(C.BOLD, "═" * 60))
    print(_c(C.BOLD, f"高并发 fixture 竞争压测 — {datetime.now().strftime('%Y-%m-%d %H:%M')}"))
    print(_c(C.BOLD, "═" * 60))
    print(f"  workers={args.workers}, rounds={args.rounds}, "
          f"instances={args.instances}, threads={args.threads}, ops={args.ops}")

    all_results: list[PhaseResult] = []

    run_all = args.only is None

    # 阶段 1: xdist 进程级并行压测
    if run_all or args.only == "xdist":
        if args.skip_xdist and run_all:
            print(_c(C.YELLOW, "\n[阶段 1] 已跳过 (--skip-xdist)"))
        else:
            all_results.extend(phase_xdist_stress(args.workers, args.rounds))

    # 阶段 2: SessionStore 实例隔离验证
    if run_all or args.only == "isolation":
        all_results.extend(phase_instance_isolation(args.instances))

    # 阶段 3: 单例并发线程安全
    if run_all or args.only == "thread_safety":
        if args.skip_thread and run_all:
            print(_c(C.YELLOW, "\n[阶段 3] 已跳过 (--skip-thread)"))
        else:
            all_results.extend(phase_singleton_thread_safety(args.threads, args.ops))

    # 阶段 4: 残留物泄漏检测
    if run_all or args.only == "leak":
        all_results.extend(phase_leak_detection())

    if not all_results:
        print(_c(C.YELLOW, "\n⚠ 未运行任何阶段"))
        return 2

    return generate_report(all_results)


if __name__ == "__main__":
    sys.exit(main())
