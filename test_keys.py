"""测试 DeepSeek 和 Agnes 两个 API Key 的真实可用性"""
import json
import urllib.request
import os

HOST = "http://127.0.0.1:8423"

def post(url, data):
    req = urllib.request.Request(
        url, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

# ── 测试 1: 直接从后端 API 验证 Key ──
print("=" * 50)
print("测试 1: 后端验证 API Key")
print("=" * 50)
r = post(f"{HOST}/api/config/validate-key", {
    "provider": "deepseek",
    "api_key": "sk-REDACTED-DEEPSEEK",
})
print(f"DeepSeek: {'✅ 有效' if r.get('success') else '❌ 无效'}")

r2 = post(f"{HOST}/api/config/validate-key", {
    "provider": "agnes",
    "api_key": "REDACTED-PYCODER-OLD-KEY",
})
print(f"Agnes: {'✅ 有效' if r2.get('success') else '❌ 无效'}")

# ── 测试 2: 直接调用 DeepSeek API ──
print("\n" + "=" * 50)
print("测试 2: 直接调用 DeepSeek API（非流式）")
print("=" * 50)
req = urllib.request.Request(
    f"{HOST}/api/chat",
    data=json.dumps({
        "message": "回复'你好'两个字即可",
        "model": "deepseek-chat",
    }).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    r = urllib.request.urlopen(req, timeout=30)
    resp = json.loads(r.read().decode())
    reply = resp.get("reply", "")
    print(f"  DeepSeek: {'✅ 正常响应' if reply else '❌ 无回复'}")
    print(f"  回复: {reply[:100]}")
except Exception as e:
    print(f"  DeepSeek: ❌ 调用失败: {e}")

# ── 测试 3: 直接调用 Agnes API ──
print("\n" + "=" * 50)
print("测试 3: 直接调用 Agnes API（通过 Provider 降级）")
print("=" * 50)
req2 = urllib.request.Request(
    f"{HOST}/api/chat",
    data=json.dumps({
        "message": "回复'你好'两个字即可",
        "model": "agnes-2.0-flash",
    }).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    r2 = urllib.request.urlopen(req2, timeout=30)
    resp2 = json.loads(r2.read().decode())
    reply2 = resp2.get("reply", "")
    if "401" in str(reply2) or "无效" in reply2 or "降级" in reply2:
        print(f"  Agnes: ❌ 401 无效 - {reply2[:100]}")
    else:
        print(f"  Agnes: {'✅ 正常' if reply2 else '❌ 无回复'}")
        print(f"  回复: {reply2[:100]}")
except Exception as e:
    print(f"  Agnes: ❌ 调用异常: {e}")

# ── 测试 4: 用 DeepSeek 完成一个简单任务 ──
print("\n" + "=" * 50)
print("测试 4: DeepSeek 完整任务（有工具调用）")
print("=" * 50)
req3 = urllib.request.Request(
    f"{HOST}/api/chat",
    data=json.dumps({
        "message": "列出当前目录下所有.txt文件",
        "model": "deepseek-chat",
    }).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    r3 = urllib.request.urlopen(req3, timeout=60)
    resp3 = json.loads(r3.read().decode())
    reply3 = resp3.get("reply", "")
    has_tool = "file" in reply3.lower() or "search" in reply3.lower()
    print(f"  DeepSeek: {'✅ 成功(含工具调用)' if has_tool else '✅ 已回复'}")
    print(f"  回复前200字: {reply3[:200]}")
except Exception as e:
    print(f"  DeepSeek: ❌ {e}")

print("\n" + "=" * 50)
print("测试完成")
print("=" * 50)
