"""检查后端健康状态"""
import urllib.request
try:
    r = urllib.request.urlopen("http://127.0.0.1:8423/api/health", timeout=5)
    print("BACKEND:" + str(r.status))
except Exception as e:
    print("BACKEND_DOWN:" + str(e))
