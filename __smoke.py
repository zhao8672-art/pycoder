"""Quick smoke test runner — 阶段 0 改造后验证不回归

运行关键架构测试与认证测试，输出到 _smoke.log
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

TEST_GROUPS = [
    ("clean_architecture", "tests/architecture/test_clean_architecture.py"),
    ("no_bare_except", "tests/architecture/test_no_bare_except.py"),
    ("no_bare_except_p3_3", "tests/architecture/test_no_bare_except_p3_3.py"),
    ("path_validation", "tests/architecture/test_path_validation_m8.py"),
    ("react_loop", "tests/architecture/test_react_loop.py"),
    ("team_orchestrator", "tests/architecture/test_team_orchestrator_split.py"),
    ("tool_calls_json_schema", "tests/architecture/test_tool_calls_json_schema.py"),
    ("chat_bridge", "tests/architecture/test_chat_bridge_m5.py"),
    ("git_router", "tests/architecture/test_git_router_h7.py"),
    ("api_auth_strong", "tests/security/test_api_auth_strong.py"),
    ("p3_security_fixes", "tests/security/test_p3_security_fixes.py"),
    ("install_packages_async", "tests/security/test_install_packages_async.py"),
    ("evolution_rollback", "tests/security/test_evolution_rollback.py"),
    ("self_evolution_async", "tests/security/test_self_evolution_async.py"),
    ("code_run_security", "tests/security/test_code_run_security.py"),
    ("di", "tests/test_di.py"),
    ("registry", "tests/test_registry.py"),
    ("chat_routes", "tests/test_chat_routes_coverage.py"),
    ("ai_modules", "tests/test_ai_modules.py"),
    ("bus_capabilities", "tests/test_bus_capabilities_modules.py"),
]

log_path = ROOT / "_smoke.log"
with log_path.open("w", encoding="utf-8") as logf:
    total_pass = 0
    total_fail = 0
    for label, test_path in TEST_GROUPS:
        full = ROOT / test_path
        if not full.exists():
            logf.write(f"[skip] {label}: {test_path} (not found)\n")
            continue
        logf.write(f"\n=== {label} ({test_path}) ===\n")
        logf.flush()
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(full), "--tb=line", "-q", "--no-header", "-p", "no:cacheprovider", "--color=no"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        # pytest 用 \r 进度行，需要替换为 \n
        out = (result.stdout + result.stderr).replace("\r", "\n")
        logf.write(out)
        logf.write(f"[exit={result.returncode}]\n")
        logf.flush()
        # 解析最后一行 passed/failed
        last_line = [l for l in out.splitlines() if l.strip()][-1] if out.strip() else ""
        logf.write(f"[summary] {label}: {last_line}\n")
        logf.flush()
    logf.write("\n=== ALL DONE ===\n")
print("done", log_path)
