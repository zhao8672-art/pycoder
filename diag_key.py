"""诊断Key状态"""
import json, os
d = json.load(open(r"C:\Users\Administrator\.pycoder\config.json"))
k = d.get("provider", {}).get("api_keys", {})
for prov in ["deepseek","agnes","openai"]:
    v = k.get(prov,"")
    if v: print(f"  config.{prov}: {v[:15]}...{v[-4:]}")
for var in ["DEEPSEEK_API_KEY","AGNES_API_KEY"]:
    v = os.environ.get(var,"")
    if v: print(f"  ENV.{var}: {v[:15]}...{v[-4:]}")
    else: print(f"  ENV.{var}: (not set)")
env_ds = os.environ.get("DEEPSEEK_API_KEY","")
cfg_ds = k.get("deepseek","")
if env_ds and cfg_ds and env_ds != cfg_ds:
    print(f"\n❌ 冲突！env={env_ds[:15]}... cfg={cfg_ds[:15]}...")
