"""修复 config.json - 清理损坏的 Key 和重复配置"""
import json, shutil

path = r"C:\Users\Administrator\.pycoder\config.json"
backup = path + ".bak"

shutil.copy2(path, backup)
print(f"备份: {backup}")

d = json.load(open(path, encoding="utf-8"))
prov = d.setdefault("provider", {})
keys = prov.setdefault("api_keys", {})

print("=== 修复前 ===")
for k, v in keys.items():
    print(f"  {k}: {v[:15]}...{v[-4:] if v else 'EMPTY'} ({len(v) if v else 0} chars)")
print(f"  default_model: {prov.get('default_model', 'N/A')}")

# 修复1: 修复被模型名污染的 Agnes Key
agnes_env = "REDACTED-PYCODER-OLD-KEY"
if keys.get("agnes") and "2.0 Flash" in keys["agnes"]:
    keys["agnes"] = agnes_env
    print("\n[修复] agnes key 被污染 -> 已修复")

# 修复2: deepseek key 如果是占位符或空的，保留但提示
if not keys.get("deepseek") or "FIXME" in keys.get("deepseek", ""):
    print("\n[提示] deepseek key 未配置，请通过 Settings 面板配置")

# 修复3: 移除重复的 default_model
if "default_model" in d and "default_model" in prov:
    d.pop("default_model", None)
    print("\n[修复] 重复 default_model -> 已清理")

json.dump(d, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print("\n=== 修复后 ===")
for k, v in keys.items():
    print(f"  {k}: {v[:15]}...{v[-4:] if v else 'EMPTY'} ({len(v) if v else 0} chars)")
print(f"  default_model: {prov.get('default_model', 'N/A')}")
print("\n✅ 修复完成，请重启后端")

if 'agnes' in keys and keys['agnes']:
    old_default = prov.get('default_model', 'N/A')
    prov['default_model'] = 'agnes-2.0-flash'
    print(f"\n[修复] 默认模型: {old_default} → agnes-2.0-flash")

# 保存
json.dump(d, open(path, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
print("\n=== 修复后 ===")
d2 = json.load(open(path, encoding='utf-8'))
k2 = d2.get('provider', {}).get('api_keys', {})
print(json.dumps({k: v[:10]+'...'+v[-4:] for k, v in k2.items()}, ensure_ascii=False))
print(f"Default model: {d2.get('provider', {}).get('default_model', 'N/A')}")
print("\n✅ 修复完成，请重启后端")
