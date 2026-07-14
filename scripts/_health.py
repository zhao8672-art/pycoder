import urllib.request
try:
    r = urllib.request.urlopen('http://127.0.0.1:8423/api/health', timeout=5)
    print(f"BACKEND: {r.status}")
except Exception as e:
    print(f"BACKEND_DOWN: {e}")
