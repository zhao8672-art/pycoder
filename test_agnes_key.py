"""测试 Agnes 通过 PyCoder 后端"""
import json, urllib.request

def post(url, data):
    req = urllib.request.Request(
        url, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    return json.loads(urllib.request.urlopen(req, timeout=120).read())

print("=== 测试 Agnes-2.0-Flash 通过 PyCoder 后端 ===")
r = post("http://127.0.0.1:8423/api/chat", {
    "message": "回复:ok",
    "model": "agnes-2.0-flash",
})
reply = r.get("reply", "")
print(f"  Model: {r.get('model')}")
print(f"  Reply: {reply[:200] if reply else '(empty)'}")
if "401" not in reply and "降级" not in reply and reply:
    print("  ✅ Agnes 2.0 可用")
else:
    print("  ❌ Agnes 2.0 不可用")

print("\n=== 测试 Agnes-1.5-Flash ===")
r2 = post("http://127.0.0.1:8423/api/chat", {
    "message": "回复:ok",
    "model": "agnes-1.5-flash",
})
reply2 = r2.get("reply", "")
print(f"  Model: {r2.get('model')}")
print(f"  Reply: {reply2[:200] if reply2 else '(empty)'}")
if "401" not in reply2 and "降级" not in reply2 and reply2:
    print("  ✅ Agnes 1.5 可用")
else:
    print("  ❌ Agnes 1.5 不可用")

print("\n=== 对比: DeepSeek ===")
r3 = post("http://127.0.0.1:8423/api/chat", {
    "message": "回复:ok",
    "model": "deepseek-chat",
})
reply3 = r3.get("reply", "")
print(f"  Model: {r3.get('model')}")
print(f"  Reply: {reply3[:100] if reply3 else '(empty)'}")
print("  ✅ DeepSeek 可用")
