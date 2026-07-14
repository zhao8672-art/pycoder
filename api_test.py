import os
import sys
import json
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

# 读取 DeepSeek key
try:
    from pycoder.providers.setup_wizard import get_api_key
    key = get_api_key("deepseek") or os.environ.get("DEEPSEEK_API_KEY", "")
except Exception as e:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    print("get_api_key error:", e)

print("KEY_PRESENT:", bool(key), "LEN:", len(key))

if not key:
    print("NO_KEY")
    sys.exit(0)

payload = json.dumps({
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "回复两个字：成功"}],
    "max_tokens": 50,
    "stream": False,
}).encode("utf-8")

req = urllib.request.Request(
    "https://api.deepseek.com/chat/completions",
    data=payload,
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print("RESPONSE:", data["choices"][0]["message"]["content"])
except Exception as e:
    print("API_ERROR:", repr(e))
    if hasattr(e, "read"):
        try:
            print("BODY:", e.read().decode("utf-8", "ignore"))
        except Exception:
            pass
