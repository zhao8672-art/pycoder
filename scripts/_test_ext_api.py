"""Test extension API directly"""
import httpx
import json
import os

base = "http://127.0.0.1:8423"
key_file = os.path.expanduser("~/.pycoder/.api_key")
key = open(key_file).read().strip()
headers = {"X-API-Key": key}

# 1. 搜索
print("=== 1. Search extensions ===")
r = httpx.get(f"{base}/api/extensions/search?q=ruff&limit=5", headers=headers, timeout=15)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    print(f"Success: {data.get('success', False)}")
    exts = data.get('extensions', [])
    print(f"Extensions found: {len(exts)}")
    if exts:
        print(f"First: {exts[0].get('name')} ({exts[0].get('id')})")
else:
    print(f"Error: {r.text[:500]}")
    # 可能是路由没注册或 import 错误

# 2. 搜索系统扩展 
print("\n=== 2. Search with category=system ===")
r2 = httpx.get(f"{base}/api/extensions/search?q=&limit=20", headers=headers, timeout=15)
print(f"Status: {r2.status_code}")
if r2.status_code == 200:
    data = r2.json()
    exts = data.get('extensions', [])
    print(f"All extensions: {len(exts)}")
    for e in exts[:5]:
        print(f"  {e.get('id')}: {e.get('name')} (seed={e.get('is_seed')})")

# 3. 安装一个种子扩展
print("\n=== 3. Install seed extension ===")
ext_id = "astral.sh.ruff"
r3 = httpx.post(f"{base}/api/extensions/install", json={"id": ext_id}, headers=headers, timeout=15)
print(f"Status: {r3.status_code}")
if r3.status_code == 200:
    print(f"Result: {json.dumps(r3.json(), ensure_ascii=False)[:500]}")
else:
    print(f"Error: {r3.text[:500]}")

# 4. 已安装列表
print("\n=== 4. Installed extensions ===")
r5 = httpx.get(f"{base}/api/extensions/list", headers=headers, timeout=15)
print(f"Status: {r5.status_code}")
if r5.status_code == 200:
    print(f"Result: {json.dumps(r5.json(), ensure_ascii=False)[:500]}")
else:
    print(f"Error: {r5.text[:500]}")
