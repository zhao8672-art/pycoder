"""
PyCoder v0.6.0 全功能验收测试脚本
"""
import json
import time
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8423"
results = []


def call(method, path, data=None, timeout=15):
    url = BASE + path
    body = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw[:300]
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        return e.code, raw[:300]
    except Exception as e:
        return -1, str(e)


def test(name, fn):
    try:
        ok, detail = fn()
        results.append((name, ok, detail))
        print(f"[{'OK' if ok else 'FAIL'}] {name}: {detail}")
    except Exception as e:
        results.append((name, False, str(e)))
        print(f"[FAIL] {name}: EXC {e}")


# ── 1. 核心健康检查 ──
def t_health():
    s, d = call("GET", "/api/health")
    return s == 200 and d.get("status") == "ok", d


def t_models():
    s, d = call("GET", "/api/models")
    return s == 200 and len(d.get("models", [])) > 0, f"{len(d.get('models', []))} models"


def t_env():
    s, d = call("GET", "/api/env")
    return s == 200, d.get("workspace", "?") if isinstance(d, dict) else d


def t_sessions_list():
    s, d = call("GET", "/api/sessions")
    return s == 200, f"{d.get('total', '?')} sessions"


# ── 2. Git 功能 ──
def t_git_status():
    s, d = call("GET", "/api/git/status")
    return s == 200 and "branch" in d, d.get("branch")


def t_git_branches():
    s, d = call("GET", "/api/git/branches")
    return s == 200 and "branches" in d, f"{len(d.get('branches', []))} branches, active={d.get('active')}"


def t_git_log():
    s, d = call("GET", "/api/git/log?limit=3")
    return s == 200, f"{len(d.get('commits', []))} commits"


def t_git_diff():
    s, d = call("GET", "/api/git/diff")
    return s == 200, "diff ok" if "diff" in d else d


def t_git_stash_list():
    s, d = call("POST", "/api/git/stash", {"action": "list"})
    return s == 200, d


def t_git_commit_gen_msg():
    s, d = call("POST", "/api/git/commit/generate-message")
    return s == 200 and "message" in d, d.get("message", "?")[:50]


# ── 3. 搜索功能 ──
def t_search_query():
    s, d = call("POST", "/api/search/query", {"query": "def ", "limit": 5})
    return s == 200 and "results" in d, f"engine={d.get('engine')}, {len(d.get('results', []))} results"


def t_search_files():
    s, d = call("GET", "/api/search/files?pattern=*.py&limit=5")
    return s == 200, f"{len(d.get('results', []))} files"


# ── 4. 扩展系统 ──
def t_ext_search():
    s, d = call("GET", "/api/extensions/search?q=")
    return s == 200 and d.get("total", 0) > 0, f"{d.get('total')} extensions"


def t_ext_installed():
    s, d = call("GET", "/api/extensions/installed")
    return s == 200, f"{len(d.get('extensions', []))} installed"


def t_ext_install():
    s, d = call("POST", "/api/extensions/install", {"id": "pycoder.todo-tree"})
    return s == 200 and d.get("success"), d


def t_ext_verify():
    s, d = call("GET", "/api/extensions/verify/pycoder.todo-tree")
    return s == 200 and d.get("installed"), d


def t_ext_run():
    s, d = call("POST", "/api/extensions/run", {
        "id": "pycoder.todo-tree", "function": "scan_directory",
        "args": {"root_path": "pycoder/extensions"}
    })
    return s == 200 and d.get("success"), str(d.get("result", {}))[:150]


def t_ext_uninstall():
    s, d = call("POST", "/api/extensions/uninstall", {"id": "pycoder.todo-tree"})
    return s == 200 and d.get("success"), d


# ── 5. Skills 市场 ──
def t_skills_list():
    s, d = call("GET", "/api/skills")
    return s == 200, d if isinstance(d, str) else f"{len(d) if isinstance(d, list) else d}"


# ── 6. 会话管理 ──
def t_session_create():
    s, d = call("POST", "/api/sessions", {"model": "auto"})
    return s == 200 and "id" in d, d.get("id", "?")[:12]


def t_session_batch_delete():
    # create two throwaway sessions then batch delete
    s1, d1 = call("POST", "/api/sessions", {"model": "auto"})
    s2, d2 = call("POST", "/api/sessions", {"model": "auto"})
    ids = [d1.get("id"), d2.get("id")]
    s, d = call("POST", "/api/sessions/batch-delete", {"session_ids": ids})
    return s == 200 and d.get("deleted") == 2, d


# ── 7. 工作区/文件管理 ──
def t_workspace_current():
    s, d = call("GET", "/api/files/workspace/current")
    return s == 200, d.get("workspace", "?")


def t_files_list():
    s, d = call("GET", "/api/files/list?path=.")
    return s == 200, f"{len(d.get('files', []))} entries" if isinstance(d, dict) else d


# ── 8. 自我进化引擎 ──
def t_evolution_stats():
    s, d = call("GET", "/api/evolution/stats")
    return s == 200 and "stats" in d, d.get("stats")


def t_evolution_tasks():
    s, d = call("GET", "/api/evolution/tasks")
    return s == 200, f"{d.get('total', '?')} tasks"


# ── 9. Agent 相关（通过 chat_handler 走 hermes/agent_mode，走 WS 更合适，这里只测健康）──
def t_context_symbols():
    s, d = call("GET", "/api/context/symbols?q=main")
    return s == 200, d if isinstance(d, str) else "ok"


print("=" * 60)
print("PyCoder v0.6.0 全功能验收测试")
print("=" * 60)

sections = [
    ("核心API", [t_health, t_models, t_env, t_sessions_list]),
    ("Git功能", [t_git_status, t_git_branches, t_git_log, t_git_diff, t_git_stash_list, t_git_commit_gen_msg]),
    ("搜索功能", [t_search_query, t_search_files]),
    ("扩展系统", [t_ext_search, t_ext_installed, t_ext_install, t_ext_verify, t_ext_run, t_ext_uninstall]),
    ("Skills市场", [t_skills_list]),
    ("会话管理", [t_session_create, t_session_batch_delete]),
    ("工作区/文件", [t_workspace_current, t_files_list]),
    ("自我进化", [t_evolution_stats, t_evolution_tasks]),
    ("上下文/符号", [t_context_symbols]),
]

for section_name, fns in sections:
    print(f"\n--- {section_name} ---")
    for fn in fns:
        test(fn.__name__, fn)
        time.sleep(0.2)

print("\n" + "=" * 60)
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
print(f"总计: {passed}/{total} 通过")
print("=" * 60)
for name, ok, detail in results:
    if not ok:
        print(f"  FAILED: {name} -> {detail}")
