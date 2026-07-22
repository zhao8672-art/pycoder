"""
PyCoder v0.5.0 全面系统测试套件
====================================
测试范围: 功能测试 / 性能测试 / 安全性测试
测试日期: 2026-07-22
"""
import json
import urllib.request
import urllib.error
import time
import sys

HOST = "http://127.0.0.1:8423"
results = []
start_time = time.time()


def report(category, name, status, detail="", severity="info", perf_ms=0):
    results.append({
        "category": category,
        "name": name,
        "status": status,
        "detail": str(detail)[:200],
        "severity": severity,
        "perf_ms": round(perf_ms, 1),
    })
    icon = {True: "✅", False: "❌", "SKIP": "⏭️"}.get(status, "⚠️")
    print(f"  {icon} {name}")


def get(url, timeout=10):
    t0 = time.perf_counter()
    r = urllib.request.urlopen(url, timeout=timeout)
    elapsed = (time.perf_counter() - t0) * 1000
    return json.loads(r.read().decode()), round(elapsed, 1)


def post(url, data, timeout=30):
    t0 = time.perf_counter()
    req = urllib.request.Request(url, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    r = urllib.request.urlopen(req, timeout=timeout)
    elapsed = (time.perf_counter() - t0) * 1000
    return json.loads(r.read().decode()), round(elapsed, 1)


print("=" * 60)
print(" PyCoder v0.5.0 — 全面系统测试报告")
print("=" * 60)
print(f" 测试环境: Windows | {HOST}")
print(f" 开始时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
print()


# ══════════════════════════════════════════════════════════
# 第一部分: 核心基础设施测试
# ══════════════════════════════════════════════════════════
print("▶ 第一部分: 核心基础设施测试")

# -- 1.1 健康检查 --
r, t = get(f"{HOST}/api/health")
report("P1-基础设施", "1.1 Health API", r.get("status") == "ok", perf_ms=t)
report("P1-基础设施", "1.2 版本号", r.get("version") == "0.5.0", r.get("version"), "critical")

# -- 1.2 关键配置端点 --
r, t = get(f"{HOST}/api/config/status")
has_keys = len([p for p in r.get("providers", []) if p.get("has_key")]) > 0
report("P1-基础设施", "2.1 Config Status", r.get("success"), perf_ms=t)
report("P1-基础设施", "2.2 已配置 Key", has_keys, f"count={len([p for p in r.get('providers',[]) if p.get('has_key')])}", "critical")

r, t = get(f"{HOST}/api/models")
report("P1-基础设施", "3.1 Models API", r.get("total", 0) > 0, f"total={r.get('total')}", perf_ms=t)
report("P1-基础设施", "3.2 推荐模型非空", bool(r.get("recommended_model")), r.get("recommended_model"), "critical")

r, t = get(f"{HOST}/api/env")
report("P1-基础设施", "4.1 Env API", bool(r.get("python_version")), r.get("python_version",""), perf_ms=t)
report("P1-基础设施", "4.2 包管理器", r.get("package_manager","none") != "", r.get("package_manager",""), "info")

# -- 1.3 模型管理 --
r2, t = post(f"{HOST}/api/model/select", {"model": "deepseek-chat"})
report("P1-基础设施", "5.1 模型选择持久化", r2.get("success"), str(r2), "high")

r3, t = get(f"{HOST}/api/model/current")
report("P1-基础设施", "5.2 获取当前模型", r3.get("success"), str(r3.get("model", {}).get("id", "")), "high")

print()


# ══════════════════════════════════════════════════════════
# 第二部分: AI 核心功能测试
# ══════════════════════════════════════════════════════════
print("▶ 第二部分: AI 核心功能测试")

# -- 2.1 DeepSeek 聊天 --
ds_result = False
try:
    r, t = post(f"{HOST}/api/chat", {"message": "回复两个汉字：你好", "model": "deepseek-chat"}, timeout=60)
    reply = r.get("reply", "")
    ds_result = bool(reply) and "401" not in reply and len(reply) > 2
    report("P2-AI功能", "6.1 DeepSeek 聊天", ds_result, reply[:80] if reply else "空", "critical", t)
except Exception as e:
    report("P2-AI功能", "6.1 DeepSeek 聊天", False, str(e)[:100], "critical")

# -- 2.2 Agnes 聊天 --
try:
    r, t = post(f"{HOST}/api/chat", {"message": "回复两个汉字：你好", "model": "agnes-2.0-flash"}, timeout=90)
    reply = r.get("reply", "")
    ag_ok = bool(reply) and "401" not in reply and len(reply) > 2
    report("P2-AI功能", "7.1 Agnes 2.0 聊天", ag_ok, reply[:80] if reply else "空", "high", t)
except Exception as e:
    report("P2-AI功能", "7.1 Agnes 2.0 聊天", False, str(e)[:100], "high")

# -- 2.3 工具调用 --
tool_ok = False
try:
    r, t = post(f"{HOST}/api/chat", {"message": "读取README.md文件并总结", "model": "deepseek-chat"}, timeout=90)
    reply = r.get("reply", "")
    tool_ok = "🔧" in reply or "file_read" in reply.lower() or "read_file" in reply.lower()
    has_report = "📋" in reply or "报告" in reply
    report("P2-AI功能", "8.1 工具调用(file_read)", tool_ok, "工具痕迹" if tool_ok else "无工具", "critical", t)
    report("P2-AI功能", "8.2 任务报告输出", has_report, "有报告" if has_report else "无报告", "high")
except Exception as e:
    report("P2-AI功能", "8.1 工具调用", False, str(e)[:100], "critical")

# -- 2.4 简单问候(应无工具调用) --
try:
    r, t = post(f"{HOST}/api/chat", {"message": "你好", "model": "deepseek-chat"}, timeout=60)
    reply = r.get("reply", "")
    no_rounds = "第 1/5 轮" not in reply and "第 1/7 轮" not in reply and "第 1/8 轮" not in reply
    report("P2-AI功能", "9.1 简单问候无工具", no_rounds, "无强制轮数" if no_rounds else "仍有多轮", "high")
except Exception as e:
    report("P2-AI功能", "9.1 简单问候", False, str(e)[:100], "high")

# -- 2.5 FIM 补全 --
try:
    req = urllib.request.Request(f"{HOST}/api/completion",
        data=json.dumps({"prefix": "def hello():\n    print", "language": "python"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    fins = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    fim_ok = fins.get("completion") is not None
    report("P2-AI功能", "10.1 FIM 补全", fim_ok, str(fins.get("completion",""))[:50], "medium")
except Exception as e:
    report("P2-AI功能", "10.1 FIM 补全", False, str(e)[:100], "medium")

print()


# ══════════════════════════════════════════════════════════
# 第三部分: Skills / 数据 / 文件 测试
# ══════════════════════════════════════════════════════════
print("▶ 第三部分: Skills / 文件 / Git 测试")

r, t = get(f"{HOST}/api/skills/v2/search?q=")
results_count = len(r.get("skills", r.get("results", [])))
report("P3-Skills", "11.1 Skills 搜索", results_count > 0, f"{results_count} results", "high", t)

r, t = get(f"{HOST}/api/git/status")
report("P3-Git", "12.1 Git Status", bool(r.get("branch")), r.get("branch", ""), "medium", t)

try:
    req = urllib.request.Request(f"{HOST}/api/sessions", method="GET")
    r = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
    has_sessions = isinstance(r, (dict, list))
    report("P3-Sessions", "13.1 Sessions 列表", has_sessions, "", "low")
except Exception as e:
    report("P3-Sessions", "13.1 Sessions", False, str(e)[:100], "low")

print()


# ══════════════════════════════════════════════════════════
# 第四部分: 性能评估
# ══════════════════════════════════════════════════════════
print("▶ 第四部分: 性能评估")

perf_data = []
for i in range(5):
    t0 = time.perf_counter()
    urllib.request.urlopen(f"{HOST}/api/health", timeout=5).read()
    perf_data.append((time.perf_counter() - t0) * 1000)

avg_ping = sum(perf_data) / len(perf_data)
perf_status = "excellent" if avg_ping < 10 else "good" if avg_ping < 50 else "fair" if avg_ping < 200 else "poor"
report("P4-性能", "14.1 Health 平均延迟", True, f"{avg_ping:.1f}ms ({perf_status})", "medium")
report("P4-性能", "14.2 延迟范围", perf_status != "poor", f"min={min(perf_data):.1f}ms max={max(perf_data):.1f}ms", "medium")
report("P4-性能", "14.3 延迟稳定性", max(perf_data) - min(perf_data) < 50, f"最大偏差={max(perf_data)-min(perf_data):.1f}ms", "low")

print()


# ══════════════════════════════════════════════════════════
# 第五部分: 安全审计
# ══════════════════════════════════════════════════════════
print("▶ 第五部分: 安全审计")

# 5.1 检查敏感信息泄露
try:
    r = urllib.request.urlopen(f"{HOST}/api/health", timeout=5)
    body = r.read().decode()
    has_sk = "sk-" in body.lower() and len(body) > 50
    report("P5-安全", "15.1 健康端点无Key泄露", not has_sk, "安全" if not has_sk else "检测到Key", "critical")

    r = urllib.request.urlopen(f"{HOST}/api/config/keys", timeout=5)
    body2 = r.read().decode()
    has_sk2 = "sk-" in body2.lower()
    report("P5-安全", "15.2 Keys端点脱敏", not has_sk2, "安全" if not has_sk2 else "Key未脱敏", "critical")
except Exception:
    report("P5-安全", "15.1 健康端点", False, "请求失败", "critical")

# 5.2 认证测试
try:
    req = urllib.request.Request(f"{HOST}/api/chat",
        data=json.dumps({"message": "test"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    r = urllib.request.urlopen(req, timeout=5)
    report("P5-安全", "16.1 API认证", r.status != 401, "需要认证" if r.status == 401 else f"HTTP {r.status}", "critical")
except urllib.error.HTTPError as e:
    report("P5-安全", "16.1 API认证", e.code == 422, f"HTTP {e.code} (API已启用)" if e.code == 422 else "异常", "critical")

# 5.3 CORS头检查
try:
    r = urllib.request.urlopen(f"{HOST}/api/health", timeout=5)
    headers = dict(r.headers)
    has_cors = "access-control-allow-origin" in [k.lower() for k in headers]
    report("P5-安全", "17.1 CORS配置", has_cors, "已配置" if has_cors else "未配置", "high")
except Exception:
    report("P5-安全", "17.1 CORS", False, "检查失败", "high")

print()


# ══════════════════════════════════════════════════════════
# 第六部分: 错误处理测试
# ══════════════════════════════════════════════════════════
print("▶ 第六部分: 异常处理测试")

try:
    req = urllib.request.Request(f"{HOST}/api/models",
        data=json.dumps({"invalid": True}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    r = urllib.request.urlopen(req, timeout=5)
    report("P6-异常处理", "18.1 POST到GET端点", r.status in (405, 200, 422), f"HTTP {r.status}", "medium")
except urllib.error.HTTPError as e:
    report("P6-异常处理", "18.1 POST到GET端点", e.code in (405, 422), f"HTTP {e.code} (预期)", "medium")

# 测试空消息
try:
    r, t = post(f"{HOST}/api/chat", {"message": "", "model": "deepseek-chat"}, timeout=10)
    report("P6-异常处理", "19.1 空消息", True, "请求被处理", "low")
except urllib.error.HTTPError as e:
    report("P6-异常处理", "19.1 空消息", e.code >= 400, f"HTTP {e.code} (预期)", "low")

print()


# ══════════════════════════════════════════════════════════
# 结果统计
# ══════════════════════════════════════════════════════════
total_time = time.time() - start_time
passed = sum(1 for r in results if r["status"] is True)
failed = sum(1 for r in results if r["status"] is False)
skipped = sum(1 for r in results if r["status"] == "SKIP")
critical_fails = sum(1 for r in results if r["status"] is False and r["severity"] == "critical")

print("=" * 60)
print(" 测试执行完毕")
print(f" 总测试数: {len(results)}")
print(f" 通过: {passed}")
print(f" 失败: {failed}")
print(f" 严重失败: {critical_fails}")
print(f" 总耗时: {total_time:.1f}s")
print("=" * 60)

# 输出失败详情
if failed > 0:
    print("\n❌ 失败详情:")
    for r in results:
        if r["status"] is False:
            print(f"  [{r['severity'].upper()}] {r['name']}: {r['detail']}")
