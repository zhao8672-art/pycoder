"""PyCoder 全功能自动检查脚本"""
import json, urllib.request, sys, time
HOST = "http://127.0.0.1:8423"
PASS = 0
FAIL = 0

def check(name, result, detail=""):
    global PASS, FAIL
    if result:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} — {detail}")

def get(url, timeout=10):
    return json.loads(urllib.request.urlopen(url, timeout=timeout).read().decode())

def post(url, data, timeout=30):
    req = urllib.request.Request(url, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())

print("=" * 55)
print(" PyCoder 全功能检查")
print("=" * 55)

# ─── 1. 后端基础设施 ───
print("\n📦 后端基础设施")
h = get(f"{HOST}/api/health")
check("Health API", h.get("status") == "ok", str(h))
check("版本号", h.get("version") == "0.5.0", h.get("version"))

# ─── 2. 模型与Key ───
print("\n🔑 模型与 Key 状态")
s = get(f"{HOST}/api/config/status")
check("/api/config/status", s.get("success"), str(s.get("error","")))
check("推荐模型非空", bool(s.get("recommended_model")), s.get("recommended_model"))
keys = [p["id"] for p in s.get("providers",[]) if p.get("has_key")]
check(f"已配置 Key ({keys})", len(keys) > 0, str(keys))
m = get(f"{HOST}/api/models")
check(f"/api/models ({m.get('total')}个)", m.get("total",0) > 0, str(m.get("total")))

# ─── 3. DeepSeek 聊天 ───
print("\n🤖 DeepSeek 聊天")
try:
    r = post(f"{HOST}/api/chat", {"message": "回复:ok", "model": "deepseek-chat"}, timeout=30)
    reply = r.get("reply","")
    check("DeepSeek 聊天", bool(reply) and "401" not in reply and "无效" not in reply, reply[:60])
except Exception as e:
    check("DeepSeek 聊天", False, str(e)[:100])

# ─── 4. Agnes 聊天 ───
print("\n🤖 Agnes 聊天")
try:
    r = post(f"{HOST}/api/chat", {"message": "回复:ok", "model": "agnes-2.0-flash"}, timeout=60)
    reply = r.get("reply","")
    ag_ok = bool(reply) and "401" not in reply and "无效" not in reply
    check("Agnes-2.0 聊天", ag_ok, reply[:60] if reply else "空回复")
except Exception as e:
    check("Agnes-2.0 聊天", False, str(e)[:100])

try:
    r1 = post(f"{HOST}/api/chat", {"message": "回复:ok", "model": "agnes-1.5-flash"}, timeout=60)
    reply1 = r1.get("reply","")
    ag15_ok = bool(reply1) and "401" not in reply1 and "无效" not in reply1
    check("Agnes-1.5 聊天", ag15_ok, reply1[:60] if reply1 else "空回复")
except Exception as e:
    check("Agnes-1.5 聊天", False, str(e)[:100])

# ─── 5. 工具调用测试 ───
print("\n🔧 工具调用")
try:
    r = post(f"{HOST}/api/chat", {"message": "读取项目根目录下README.md并总结", "model": "deepseek-chat"}, timeout=60)
    reply = r.get("reply","")
    has_tool = "🔧" in reply or "file_read" in reply.lower() or "read_file" in reply.lower()
    has_report = "📋" in reply or "报告" in reply
    check("工具调用", has_tool, "无工具痕迹" if not has_tool else reply[:30])
    check("任务报告", has_report, "无报告格式" if not has_report else "")
except Exception as e:
    check("工具调用", False, str(e)[:100])

# ─── 6. 模型选择持久化 ───
print("\n💾 模型选择")
r = post(f"{HOST}/api/model/select", {"model": "deepseek-chat"})
check("选择模型 deepseek-chat", r.get("success"), str(r))
r2 = get(f"{HOST}/api/model/current")
check("获取当前模型", r2.get("success"), str(r2.get("model",{}).get("id","")))
custom = post(f"{HOST}/api/model/custom-api-base", {"model":"deepseek-chat","api_base":"https://api.deepseek.com/v1"})
check("自定义 API Base", custom.get("success"), str(custom))

# ─── 7. 环境API ───
print("\n🌐 其他 API")
e = get(f"{HOST}/api/env", timeout=10)
check("/api/env", bool(e.get("python_version")), e.get("python_version",""))
g = get(f"{HOST}/api/config/guide")
check("/api/config/guide", bool(g.get("providers")), f"{len(g.get('providers',[]))} providers")

# ─── 8. FIM 补全 ───
print("\n✏️  FIM 补全")
try:
    req = urllib.request.Request(f"{HOST}/api/completion",
        data=json.dumps({"prefix":"def hello():\\n    print","language":"python"}).encode(),
        headers={"Content-Type":"application/json"}, method="POST")
    fim = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    check("FIM 补全", bool(fim.get("completion")) or fim.get("completion","") != "", str(fim.get("completion","")[:30]))
except Exception as e:
    check("FIM 补全", False, str(e)[:100])

# ─── 9. 模型推荐 ───
print("\n📊 推荐/验证")
r3 = post(f"{HOST}/api/config/validate-key", {"provider":"deepseek","api_key":"sk-REDACTED-DEEPSEEK"})
check("验证 DeepSeek Key", r3.get("success"), str(r3))

# ─── 10. Git状态 ───
print("\n📂 Git")
req = urllib.request.Request(f"{HOST}/api/git/status", method="GET")
try:
    gs = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
    check("Git 状态", bool(gs.get("branch")), gs.get("branch",""))
except Exception as e:
    check("Git 状态", False, str(e)[:100])

# ─── 结果汇总 ───
print("\n" + "=" * 55)
print(f" 总计: ✅ {PASS} / ❌ {FAIL}")
print("=" * 55)
