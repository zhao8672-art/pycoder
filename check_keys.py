"""检查 Key 配置"""
import json
d = json.load(open(r'C:\Users\Administrator\.pycoder\config.json'))
keys = d.get('provider', {}).get('api_keys', {})
print(f"默认模型: {d.get('provider', {}).get('default_model', 'N/A')}")
for k, v in keys.items():
    print(f"  {k}: {v[:10]}...{v[-4:]} ({len(v)} chars)")
