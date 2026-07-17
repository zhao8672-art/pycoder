import json, urllib.request
r = urllib.request.urlopen("http://127.0.0.1:8423/api/models", timeout=5)
d = json.loads(r.read().decode())
print(f"推荐: {d['recommended_model']}")
av = [m["id"] for m in d["models"] if m["available"]]
print(f"可用: {av}")
has_agnes = "agnes" in d["recommended_model"]
print(f"Agnes已排除: {not has_agnes}")
if not has_agnes:
    print("SUCCESS: 推荐模型正确 (非agnes)")
else:
    print("FAIL: 推荐模型仍是agnes!")
