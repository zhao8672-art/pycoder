"""阶段 0 改造后回归验证 — 跑关键测试并把结果写入文件"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "_regression.log"

# 关注与本次改动直接相关的测试
TESTS = [
    "tests/test_di.py",
    "tests/test_registry.py",
    "tests/test_chat_routes_coverage.py",
    "tests/test_session_store.py",
    "tests/test_workspace.py",
    "tests/test_browser.py",
    "tests/test_health_api.py",
    "tests/test_capabilities_permissions.py",
    "tests/test_capabilities_degradation.py",
    "tests/test_ai_modules.py",
    "tests/test_bus_capabilities_modules.py",
    "tests/test_safety_audit.py",
    "tests/test_safety_rollback.py",
    "tests/test_safety_permission.py",
    "tests/architecture/test_clean_architecture.py",
    "tests/architecture/test_no_bare_except.py",
    "tests/architecture/test_path_validation_m8.py",
    "tests/architecture/test_team_orchestrator_split.py",
    "tests/architecture/test_chat_bridge_m5.py",
    "tests/architecture/test_git_router_h7.py",
    "tests/architecture/test_tool_calls_json_schema.py",
    "tests/security/test_api_auth_strong.py",
    "tests/security/test_p3_security_fixes.py",
    "tests/security/test_install_packages_async.py",
    "tests/security/test_evolution_rollback.py",
    "tests/security/test_self_evolution_async.py",
    "tests/security/test_code_run_security.py",
]

with LOG.open("w", encoding="utf-8") as f:
    f.write("=" * 70 + "\n")
    f.write("阶段 0 改造后回归验证\n")
    f.write("改动：\n")
    f.write("  - pycoder/__init__.py 移除 subprocess monkey-patch 副作用（移到 pycoder._compat.popen）\n")
    f.write("  - pycoder/server/__init__.py 改为 PEP 562 lazy import（消除模块加载时循环触发器）\n")
    f.write("  - 创建 pycoder/_compat/ 包承载懒加载补丁\n")
    f.write("=" * 70 + "\n")
    f.flush()
    total_pass = 0
    total_fail = 0
    for t in TESTS:
        full = ROOT / t
        if not full.exists():
            f.write(f"[skip] {t} (not found)\n")
            f.flush()
            continue
        r = subprocess.run(
            [sys.executable, "-m", "pytest", t, "--tb=line", "-q", "--no-header",
             "--timeout=30", "-p", "no:cacheprovider", "--color=no"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120,
        )
        out = (r.stdout + r.stderr).replace("\r", "\n")
        lines = [l for l in out.splitlines() if l.strip()]
        summary = lines[-1] if lines else "(empty)"
        f.write(f"{t}\n  exit={r.returncode} | {summary}\n")
        f.flush()
        import re
        m = re.search(r"(\d+) passed", summary)
        if m:
            total_pass += int(m.group(1))
        m = re.search(r"(\d+) failed", summary)
        if m:
            total_fail += int(m.group(1))
    f.write("\n" + "=" * 70 + "\n")
    f.write(f"汇总：passed={total_pass}, failed={total_fail}\n")
    f.write("=" * 70 + "\n")
    f.flush()

print(f"regression log: {LOG}", flush=True)
print(f"passed={total_pass}, failed={total_fail}", flush=True)
