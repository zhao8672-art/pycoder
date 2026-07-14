"""
端到端验证 — 关键功能集成测试
"""
import json, urllib.request

BASE = "http://127.0.0.1:8423"
PASS = 0; FAIL = 0

def test(name, method, url, body=None, expect_200=True):
    global PASS, FAIL
    try:
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(BASE + url, data=data, method=method,
            headers={"Content-Type": "application/json"} if body else {})
        resp = urllib.request.urlopen(req, timeout=15)
        code = resp.status
        d = json.loads(resp.read().decode())
        ok = (code == 200) == expect_200
        if ok:
            PASS += 1
            print(f"  ✅ {name}: HTTP {code}")
        else:
            FAIL += 1
            print(f"  ❌ {name}: HTTP {code} (expected {'200' if expect_200 else 'not 200'})")
        return d
    except urllib.error.HTTPError as e:
        code = e.code
        ok = not expect_200
        if ok: PASS += 1
        else: FAIL += 1
        body = e.read().decode()[:150]
        print(f"  {'✅' if ok else '❌'} {name}: HTTP {code} | {body}")
        return {"error": body}
    except Exception as e:
        FAIL += 1
        print(f"  ❌ {name}: {str(e)[:100]}")
        return {"error": str(e)}

print("=" * 55)
print(" PyCoder 端到端集成验证")
print("=" * 55)

# ── P0: 健康检查 ──
print("\n--- P0: 基础服务 ---")
test("Health check", "GET", "/api/health")
test("Git status", "GET", "/api/git/status")
test("Mobile status", "GET", "/api/mobile/status")
test("Extensions search", "GET", "/api/extensions/search?limit=3")

# ── P0: Git 功能 ──
print("\n--- P0: Git 功能 ---")
test("Git init check", "GET", "/api/git/init")
test("Git branches", "GET", "/api/git/branches")
test("Git log", "GET", "/api/git/log?limit=3")

# ── P1: GitHub 集成 ──
print("\n--- P1: GitHub 集成 ---")
test("GitHub auth status", "GET", "/api/github/auth/status")
d = test("GitHub public repo", "GET", "/api/github/repo/torvalds/linux")
if d and isinstance(d, dict) and d.get("success"):
    print("   → torvalds/linux 仓库可访问")

# ── P1: 扩展市场 ──
print("\n--- P1: 扩展市场 ---")
d = test("Extensions search", "GET", "/api/extensions/search?limit=3")
if d and isinstance(d, dict):
    print(f"   → 扩展数: {d.get('total', 0)}")
    healthy = d.get("sources", {}).get("healthy", [])
    if healthy:
        print(f"   → 数据源: {len(healthy)} 个健康")

# ── P2: AI Agent 团队 ──
print("\n--- P2: AI Agent 团队 ---")
test("Team runs", "GET", "/api/team/runs")

# ── P2: 代码执行 ──
print("\n--- P2: 代码执行沙箱 ---")
d = test("Code caps", "GET", "/api/code/capabilities")

# ── P2: 模型配置 ──
print("\n--- P2: AI 模型 ---")
d = test("Model config", "GET", "/api/model/config")

# ══════════════════════════════════════════════════════════
print("\n" + "=" * 55)
print(f" 总计: {PASS} 通过 / {FAIL} 失败 / {PASS+FAIL} 总用例")
print("=" * 55)

exit(0 if FAIL == 0 else 1)
