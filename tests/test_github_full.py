"""全面测试 GitHub 集成所有端点"""
import json, urllib.request, sys

BASE = "http://127.0.0.1:8423"
PASS = 0; FAIL = 0; ISSUES = []

def test(name, method, url, body=None, expect_code=200, expect_key=None):
    global PASS, FAIL
    try:
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(BASE + url, data=data, method=method,
            headers={"Content-Type": "application/json"} if body else {})
        resp = urllib.request.urlopen(req, timeout=15)
        code = resp.status
        d = json.loads(resp.read().decode())
        ok = code == expect_code
        key_ok = True
        if expect_key and expect_key not in d:
            key_ok = False
        if ok and key_ok:
            PASS += 1
            print(f"  ✅ {name}: HTTP {code}")
        else:
            FAIL += 1
            msg = f"code={code} != {expect_code}" if not ok else f"missing key '{expect_key}'"
            print(f"  ❌ {name}: {msg} | resp={json.dumps(d)[:120]}")
            ISSUES.append(f"{name}: {msg}")
    except urllib.error.HTTPError as e:
        FAIL += 1
        body = e.read().decode()[:200]
        print(f"  ❌ {name}: HTTP {e.code} | {body}")
        ISSUES.append(f"{name}: HTTP {e.code} - {body}")
    except Exception as e:
        FAIL += 1
        print(f"  ❌ {name}: {str(e)[:150]}")
        ISSUES.append(f"{name}: {e}")

# ══════════════════════════════
print("=" * 55)
print(" GitHub 集成 - 全面功能测试")
print("=" * 55)

# ── 1. Git 基础 ──
print("\n--- 1. Git 基础 ---")
test("Git status", "GET", "/api/git/status", expect_key="files")
test("Git init check", "GET", "/api/git/init", expect_key="is_git")
test("Git log", "GET", "/api/git/log?limit=3", expect_key="commits")
test("Git branches", "GET", "/api/git/branches", expect_key="branches")

# ── 2. GitHub Auth ──
print("\n--- 2. GitHub Auth ---")
test("Auth status (no token)", "GET", "/api/github/auth/status", expect_key="authenticated")
test("Auth clear (no-op ok)", "DELETE", "/api/github/auth")
test("Auth with bad token", "POST", "/api/github/auth", {"token": "ghp_invalid"})

# ── 3. GitHub Repos (需要token, 预期401或空列表) ──
print("\n--- 3. GitHub Repos ---")
test("List repos (no token)", "GET", "/api/github/repos")
test("Repo detail (public)", "GET", "/api/github/repo/torvalds/linux", expect_key="success")

# ── 4. GitHub PRs ──
print("\n--- 4. GitHub PRs ---")
test("List PRs (public repo)", "GET", "/api/github/pulls/torvalds/linux?state=open", expect_key="pulls")
test("PR detail (public)", "GET", "/api/github/pulls/torvalds/linux/1")

# ── 5. GitHub Issues ──
print("\n--- 5. GitHub Issues ---")
test("List issues (public repo)", "GET", "/api/github/issues/torvalds/linux?state=open&per_page=3", expect_key="issues")

# ── 6. Clone (测试URL验证, 不实际clone) ──
print("\n--- 6. Clone (URL验证) ---")
test("Clone empty url (should 400)", "POST", "/api/github/clone", {"url": ""}, expect_code=400)

# ── 7. Create Repo (无token测试) ──
print("\n--- 7. Create Repo (无token) ---")
test("Create repo no token", "POST", "/api/github/create-repo", {"name": "test-repo"}, expect_code=401)
test("Publish no token", "POST", "/api/github/publish", {"repo_name": "test"}, expect_code=401)

# ══════════════════════════════
print("\n" + "=" * 55)
print(f" 总计: {PASS} 通过 / {FAIL} 失败 / {PASS+FAIL} 总用例")
print("=" * 55)

if ISSUES:
    print("\n--- 问题清单 ---")
    for i, issue in enumerate(ISSUES, 1):
        print(f"  {i}. {issue}")
else:
    print("\n✅ 未发现问题")
