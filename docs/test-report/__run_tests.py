"""PyCoder 综合测试执行器 - v3 (高稳定性版本)"""
import json
import time
import statistics
import socket
import sys
from pathlib import Path
from typing import Any
import http.client
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL_HOST = "127.0.0.1"
BASE_URL_PORT = 8423
API_KEY = "AX8iZWiH7B0aK2Lh1ZdC8F_hbjvA58h6QW6CkDFI9z0"
REPORT_DIR = Path(__file__).parent
RESULTS_FILE = REPORT_DIR / "test-results.json"
LOG_FILE = REPORT_DIR / "_test_run.log"

results: list[dict[str, Any]] = []
issues: list[dict[str, Any]] = []
_log_fh = None


def log(msg: str) -> None:
    global _log_fh
    if _log_fh is None:
        _log_fh = open(LOG_FILE, "w", encoding="utf-8")
    line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
    _log_fh.write(line)
    _log_fh.flush()
    print(msg, flush=True)


def call_api(
    method: str,
    path: str,
    body: dict | None = None,
    headers: dict | None = None,
    timeout: float = 4.0,
    with_auth: bool = True,
) -> tuple[int, dict, float]:
    """统一 API 调用入口 - 使用 http.client 避免连接复用问题"""
    hdrs = {"Content-Type": "application/json", "Connection": "close"}
    if with_auth:
        hdrs["X-API-Key"] = API_KEY
    if headers:
        hdrs.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    start = time.perf_counter()
    conn = None
    try:
        conn = http.client.HTTPConnection(BASE_URL_HOST, BASE_URL_PORT, timeout=timeout)
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        elapsed = (time.perf_counter() - start) * 1000
        content = resp.read().decode("utf-8")
        try:
            payload = json.loads(content) if content else {}
        except json.JSONDecodeError:
            payload = {"_raw": content[:500]}
        return resp.status, payload, elapsed
    except socket.timeout:
        return 0, {"_timeout": True}, (time.perf_counter() - start) * 1000
    except Exception as e:
        return 0, {"_exception": type(e).__name__, "_message": str(e)[:200]}, (time.perf_counter() - start) * 1000
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def save_results():
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    summary = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_tests": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total * 100, 2) if total else 0,
        "issues_count": len(issues),
        "issues_by_severity": {
            sev: sum(1 for i in issues if i["severity"] == sev)
            for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
        },
    }
    output = {"summary": summary, "issues": issues, "results": results}
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)


def record_test(category, name, method, path, expected, body=None, severity="MEDIUM", description=""):
    status, payload, elapsed = call_api(method, path, body=body)
    expected_list = expected if isinstance(expected, tuple) else (expected,)
    passed = status in expected_list and status != 0

    result = {
        "category": category,
        "name": name,
        "method": method,
        "path": path,
        "expected_status": list(expected_list),
        "actual_status": status,
        "elapsed_ms": round(elapsed, 2),
        "passed": passed,
    }
    if status == 0:
        result["error"] = payload

    if not passed:
        issues.append({
            "id": f"BUG-{len(issues) + 1:03d}",
            "severity": severity,
            "category": category,
            "name": name,
            "endpoint": f"{method} {path}",
            "expected": list(expected_list),
            "actual": status,
            "elapsed_ms": round(elapsed, 2),
            "response_sample": str(payload)[:300],
            "description": description,
        })

    results.append(result)
    return result


# ============================================================
# 阶段 2: 功能测试
# ============================================================

def t_health():
    record_test("Functional", "Health check", "GET", "/api/health", 200, severity="HIGH")
    record_test("Functional", "V2 health", "GET", "/api/v2/health", 200, severity="MEDIUM")
    record_test("Functional", "V2 status", "GET", "/api/v2/status", 200, severity="MEDIUM")
    record_test("Functional", "V2 stats", "GET", "/api/v2/stats", 200, severity="MEDIUM")
    record_test("Functional", "V2 capabilities", "GET", "/api/v2/capabilities", 200, severity="MEDIUM")


def t_model():
    record_test("Functional", "List models", "GET", "/api/models", 200, severity="HIGH")
    record_test("Functional", "Recommended", "GET", "/api/models/recommended", (200, 404), severity="MEDIUM")
    record_test("Functional", "Current model", "GET", "/api/model/current", (200, 404), severity="MEDIUM")
    record_test("Functional", "Config status", "GET", "/api/config/status", 200, severity="HIGH")


def t_session():
    record_test("Functional", "List sessions", "GET", "/api/sessions", (200, 404), severity="HIGH")
    record_test("Functional", "List all sessions", "GET", "/api/sessions/all", (200, 404), severity="MEDIUM")
    record_test("Functional", "Memory sessions", "GET", "/api/memory/sessions", (200, 404), severity="MEDIUM")
    record_test("Functional", "Memory current", "GET", "/api/memory/current", (200, 404), severity="MEDIUM")


def t_file():
    record_test("Functional", "Workspace current", "GET", "/api/files/workspace/current", (200, 404), severity="MEDIUM")
    record_test("Functional", "Workspace recent", "GET", "/api/files/workspace/recent", (200, 404), severity="MEDIUM")
    record_test("Functional", "List workspaces", "GET", "/api/workspaces/list", (200, 404), severity="MEDIUM")


def t_git():
    record_test("Functional", "Git status", "GET", "/api/git/status", (200, 500), severity="HIGH")
    record_test("Functional", "Git log", "GET", "/api/git/log", (200, 500), severity="HIGH")
    record_test("Functional", "Git branches", "GET", "/api/git/branches", (200, 500), severity="HIGH")
    record_test("Functional", "Git remotes", "GET", "/api/git/remotes", (200, 500), severity="LOW")


def t_code():
    record_test("Functional", "Code languages", "GET", "/api/code/languages", (200, 404), severity="MEDIUM")
    record_test("Functional", "Code capabilities", "GET", "/api/code/capabilities", (200, 404), severity="MEDIUM")
    record_test("Functional", "Code exec config", "GET", "/api/code/exec/config", (200, 404), severity="MEDIUM")
    record_test("Functional", "Code history", "GET", "/api/code/history", (200, 404), severity="LOW")


def t_skill():
    record_test("Functional", "List skills", "GET", "/api/skills", (200, 404), severity="MEDIUM")
    record_test("Functional", "Skills list v1", "GET", "/api/skills/list", (200, 404), severity="MEDIUM")
    record_test("Functional", "Skills stats", "GET", "/api/skills/stats", (200, 404), severity="LOW")
    record_test("Functional", "Skills V2 search", "GET", "/api/skills/v2/search", (200, 422), severity="LOW")
    record_test("Functional", "Skills V2 trending", "GET", "/api/skills/v2/trending", (200, 404), severity="LOW")
    record_test("Functional", "Skills V2 stats", "GET", "/api/skills/v2/stats/overview", (200, 404), severity="LOW")


def t_extension():
    record_test("Functional", "Extensions installed", "GET", "/api/extensions/installed", (200, 404), severity="MEDIUM")
    record_test("Functional", "Extensions recommended", "GET", "/api/extensions/recommended", (200, 404), severity="LOW")
    record_test("Functional", "Extensions stats", "GET", "/api/extensions/stats", (200, 404), severity="LOW")
    record_test("Functional", "Extensions commands", "GET", "/api/extensions/commands", (200, 404), severity="LOW")
    record_test("Functional", "Extensions cache status", "GET", "/api/extensions/cache-status", (200, 404), severity="LOW")


def t_evolution():
    record_test("Functional", "Evolution history", "GET", "/api/v2/evolution/history", (200, 404), severity="LOW")
    record_test("Functional", "Evolution stats", "GET", "/api/v2/evolution/stats", (200, 404), severity="LOW")
    record_test("Functional", "Evolution tasks", "GET", "/api/v2/evolution/tasks", (200, 404), severity="LOW")
    record_test("Functional", "Trust status", "GET", "/api/v2/trust/status", (200, 404), severity="LOW")
    record_test("Functional", "Evolution token status", "GET", "/api/v2/evolution/token/status", (200, 404), severity="LOW")
    record_test("Functional", "Evolution approvals", "GET", "/api/v2/evolution/approvals", (200, 404), severity="LOW")


def t_refactor():
    record_test("Functional", "Type hint status", "GET", "/api/typehint/status", (200, 404), severity="LOW")
    record_test("Functional", "Docstring styles", "GET", "/api/docstring/styles", (200, 404), severity="LOW")


def t_test():
    record_test("Functional", "Test mock", "GET", "/api/test/mock", (200, 422), severity="LOW")
    record_test("Functional", "Test coverage", "GET", "/api/test/coverage", (200, 404), severity="LOW")
    record_test("Functional", "Test benchmark", "GET", "/api/test/benchmark", (200, 422), severity="LOW")


def t_misc():
    record_test("Functional", "Pipeline list", "GET", "/api/pipeline/list", (200, 404), severity="MEDIUM")
    record_test("Functional", "Scaffold templates", "GET", "/api/scaffold/templates", (200, 404), severity="LOW")
    record_test("Functional", "Async patterns", "GET", "/api/async/patterns", (200, 404), severity="LOW")
    record_test("Functional", "SQLAlchemy models", "GET", "/api/sqlalchemy/models", (200, 404), severity="LOW")
    record_test("Functional", "Security types", "GET", "/api/security/types", (200, 404), severity="MEDIUM")
    record_test("Functional", "Agent status", "GET", "/api/agent/status", (200, 404), severity="MEDIUM")
    record_test("Functional", "Dependencies", "GET", "/api/dependencies", (200, 404), severity="MEDIUM")
    record_test("Functional", "MCP marketplace", "GET", "/api/mcp/marketplace", (200, 404), severity="LOW")
    record_test("Functional", "MCP servers", "GET", "/api/mcp/servers", (200, 404), severity="LOW")
    record_test("Functional", "Recommendations for-me", "GET", "/api/recommendations/for-me", (200, 404), severity="LOW")
    record_test("Functional", "Recommendations trending", "GET", "/api/recommendations/trending", (200, 404), severity="LOW")
    record_test("Functional", "Learning stats", "GET", "/api/learning/stats", (200, 404), severity="LOW")


def t_visualize():
    record_test("Functional", "Visualize structure", "GET", "/api/visualize/structure", (200, 422), severity="LOW")
    record_test("Functional", "Visualize imports", "GET", "/api/visualize/imports", (200, 422), severity="LOW")
    record_test("Functional", "Visualize calls", "GET", "/api/visualize/calls", (200, 422), severity="LOW")


# ============================================================
# 阶段 3: 性能测试
# ============================================================

def perf_health_seq(n=10):
    durations = []
    for i in range(n):
        _, _, elapsed = call_api("GET", "/api/health", timeout=3.0)
        durations.append(elapsed)
    return durations


def perf_models_seq(n=10):
    durations = []
    for i in range(n):
        _, _, elapsed = call_api("GET", "/api/models", timeout=3.0)
        durations.append(elapsed)
    return durations


def perf_concurrent(n=20):
    def call():
        _, _, elapsed = call_api("GET", "/api/health", timeout=3.0)
        return elapsed

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(call) for _ in range(n)]
        durations = []
        for f in as_completed(futures, timeout=15):
            try:
                durations.append(f.result(timeout=3))
            except Exception:
                durations.append(5000)
    return durations


# ============================================================
# 阶段 5: 安全性测试
# ============================================================

def sec_no_auth():
    return call_api("GET", "/api/models", with_auth=False)[0]


def sec_wrong_auth():
    return call_api("GET", "/api/models", headers={"X-API-Key": "wrong-key-12345"})[0]


def sec_sql_injection():
    payloads = ["'; DROP TABLE x; --", "1' OR '1'='1", "admin'--"]
    results = []
    for p in payloads:
        s, _, _ = call_api("GET", f"/api/sessions/{urllib.parse.quote(p)}")
        results.append((p, s))
    return results


def sec_path_traversal():
    payloads = ["../../etc/passwd", "..\\..\\Windows\\System32\\config\\SAM", "/etc/passwd"]
    results = []
    for p in payloads:
        s, _, _ = call_api("GET", f"/api/files/read?path={urllib.parse.quote(p)}")
        results.append((p[:50], s))
    return results


def sec_command_injection():
    payloads = ["; ls -la", "| cat /etc/passwd", "$(whoami)"]
    results = []
    for p in payloads:
        s, _, _ = call_api("POST", "/api/code/exec", body={"code": f"print('hi'){p}", "lang": "python"})
        results.append((p, s))
    return results


def sec_xss():
    payloads = ["<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "javascript:alert(1)"]
    results = []
    for p in payloads:
        s, _, _ = call_api("POST", "/api/chat", body={"message": p})
        results.append((p[:30], s))
    return results


def sec_large_payload():
    data = "x" * 50000
    s, _, elapsed = call_api("POST", "/api/chat", body={"message": data})
    return s, elapsed


def sec_oversized_header():
    s, _, elapsed = call_api("GET", "/api/health", headers={"X-Custom": "x" * 50000})
    return s, elapsed


def sec_rate_limit(n=50):
    durations = []
    for _ in range(n):
        _, _, elapsed = call_api("GET", "/api/health", timeout=3.0)
        durations.append(elapsed)
    return durations


# ============================================================
# 主流程
# ============================================================

def safe_run(func, name):
    log(f"  -> {name}")
    try:
        func()
        log(f"     OK ({len(results)} tests so far)")
    except Exception as e:
        log(f"     EXCEPTION: {type(e).__name__}: {e}")
        issues.append({
            "id": f"BUG-{len(issues) + 1:03d}",
            "severity": "HIGH",
            "category": "TestRunner",
            "name": name,
            "endpoint": "N/A",
            "expected": "OK",
            "actual": "EXCEPTION",
            "elapsed_ms": 0,
            "response_sample": f"{type(e).__name__}: {e}",
            "description": f"Test function raised exception: {e}",
        })


def main():
    log("=" * 70)
    log("PyCoder Comprehensive Test Suite (v3)")
    log("=" * 70)

    # 阶段 2: 功能测试
    log("\n[Phase 2] Functional Testing")
    tests = [
        (t_health, "t_health"),
        (t_model, "t_model"),
        (t_session, "t_session"),
        (t_file, "t_file"),
        (t_git, "t_git"),
        (t_code, "t_code"),
        (t_skill, "t_skill"),
        (t_extension, "t_extension"),
        (t_evolution, "t_evolution"),
        (t_refactor, "t_refactor"),
        (t_test, "t_test"),
        (t_misc, "t_misc"),
        (t_visualize, "t_visualize"),
    ]
    for fn, name in tests:
        safe_run(fn, name)
        save_results()
        time.sleep(0.3)  # 防止过快连接

    log(f"  Functional tests completed: {len(results)} tests, {len(issues)} issues")

    # 阶段 3: 性能测试
    log("\n[Phase 3] Performance Testing")
    perf = {}

    log("  - Health endpoint x10 sequential")
    d = perf_health_seq(10)
    perf["health_seq_10"] = {
        "samples": len(d),
        "p50_ms": round(statistics.median(d), 2),
        "p95_ms": round(sorted(d)[int(len(d) * 0.9)], 2),
        "max_ms": round(max(d), 2),
        "min_ms": round(min(d), 2),
        "mean_ms": round(statistics.mean(d), 2),
    }
    log(f"    P50={perf['health_seq_10']['p50_ms']}ms P95={perf['health_seq_10']['p95_ms']}ms Max={perf['health_seq_10']['max_ms']}ms")

    log("  - Models endpoint x10 sequential")
    d = perf_models_seq(10)
    perf["models_seq_10"] = {
        "samples": len(d),
        "p50_ms": round(statistics.median(d), 2),
        "p95_ms": round(sorted(d)[int(len(d) * 0.9)], 2),
        "max_ms": round(max(d), 2),
        "min_ms": round(min(d), 2),
        "mean_ms": round(statistics.mean(d), 2),
    }
    log(f"    P50={perf['models_seq_10']['p50_ms']}ms P95={perf['models_seq_10']['p95_ms']}ms Max={perf['models_seq_10']['max_ms']}ms")

    log("  - 20x concurrent to /api/health")
    d = perf_concurrent(20)
    perf["health_concurrent_20"] = {
        "samples": len(d),
        "p50_ms": round(statistics.median(d), 2),
        "p95_ms": round(sorted(d)[int(len(d) * 0.95) - 1] if len(d) > 1 else d[0], 2),
        "max_ms": round(max(d), 2),
        "min_ms": round(min(d), 2),
        "mean_ms": round(statistics.mean(d), 2),
    }
    log(f"    P50={perf['health_concurrent_20']['p50_ms']}ms P95={perf['health_concurrent_20']['p95_ms']}ms Max={perf['health_concurrent_20']['max_ms']}ms")

    # 阶段 5: 安全性测试
    log("\n[Phase 5] Security Testing")
    sec = {}

    log("  - No authentication")
    sec["no_auth"] = sec_no_auth()
    log(f"    status={sec['no_auth']} (expected 401/403)")

    log("  - Wrong API key")
    sec["wrong_auth"] = sec_wrong_auth()
    log(f"    status={sec['wrong_auth']} (expected 401/403)")

    log("  - SQL injection (3 payloads)")
    sec["sql_injection"] = sec_sql_injection()
    log(f"    statuses={[s for _, s in sec['sql_injection']]}")

    log("  - Path traversal (3 payloads)")
    sec["path_traversal"] = sec_path_traversal()
    log(f"    statuses={[s for _, s in sec['path_traversal']]}")

    log("  - Command injection (3 payloads)")
    sec["command_injection"] = sec_command_injection()
    log(f"    statuses={[s for _, s in sec['command_injection']]}")

    log("  - XSS (3 payloads)")
    sec["xss"] = sec_xss()
    log(f"    statuses={[s for _, s in sec['xss']]}")

    log("  - Large payload (50KB)")
    sec["large_payload"] = sec_large_payload()
    log(f"    status={sec['large_payload'][0]} elapsed={sec['large_payload'][1]:.0f}ms")

    log("  - Oversized header (50KB)")
    sec["oversized_header"] = sec_oversized_header()
    log(f"    status={sec['oversized_header'][0]} elapsed={sec['oversized_header'][1]:.0f}ms")

    log("  - Rate limit (50 rapid requests)")
    d = sec_rate_limit(50)
    sec["rate_limit"] = {
        "samples": len(d),
        "p50_ms": round(statistics.median(d), 2),
        "p95_ms": round(sorted(d)[int(len(d) * 0.9)], 2),
        "max_ms": round(max(d), 2),
    }
    log(f"    P95={sec['rate_limit']['p95_ms']}ms Max={sec['rate_limit']['max_ms']}ms")

    # 最终汇总
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    summary = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_tests": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total * 100, 2) if total else 0,
        "issues_count": len(issues),
        "issues_by_severity": {
            sev: sum(1 for i in issues if i["severity"] == sev)
            for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
        },
        "performance": perf,
        "security": sec,
    }
    output = {"summary": summary, "issues": issues, "results": results}
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    log("\n" + "=" * 70)
    log("Test Summary")
    log("=" * 70)
    log(f"Total tests: {total}")
    log(f"Passed: {passed} ({summary['pass_rate']}%)")
    log(f"Failed: {total - passed}")
    log(f"Issues: {len(issues)}")
    log(f"  CRITICAL: {summary['issues_by_severity']['CRITICAL']}")
    log(f"  HIGH:     {summary['issues_by_severity']['HIGH']}")
    log(f"  MEDIUM:   {summary['issues_by_severity']['MEDIUM']}")
    log(f"  LOW:      {summary['issues_by_severity']['LOW']}")
    log(f"\nResults saved to: {RESULTS_FILE}")

    if _log_fh:
        _log_fh.close()


if __name__ == "__main__":
    main()
