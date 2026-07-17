"""验证 AI 功能"""
import json
import urllib.request

# 检查模型
r = urllib.request.urlopen("http://127.0.0.1:8423/api/models", timeout=5)
data = json.loads(r.read())
print("推荐模型:", data["recommended_model"])
print("可用模型:", [m["id"] for m in data["models"] if m["available"]])
print()

# 检查 chat 端点
req = urllib.request.Request(
    "http://127.0.0.1:8423/api/chat",
    data=json.dumps({"message": "你好", "model": "auto", "stream": False}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    r = urllib.request.urlopen(req, timeout=30)
    resp = json.loads(r.read())
    print("完整响应:", json.dumps(resp, indent=2, ensure_ascii=False)[:500])
    print("使用模型:", resp.get("model", "未知"))
except Exception as e:
    print(f"Chat 失败: {e}")
