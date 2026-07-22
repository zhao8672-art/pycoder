import urllib.request, json
h = json.loads(urllib.request.urlopen("http://127.0.0.1:8423/api/health", timeout=5).read().decode())
m = json.loads(urllib.request.urlopen("http://127.0.0.1:8423/api/config/status", timeout=5).read().decode())
print(f"Backend: {h['status']} v{h['version']}")
print(f"Model: {m['recommended_model']}")
print(f"Keys: {[p['id'] for p in m['providers'] if p['has_key']]}")
