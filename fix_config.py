"""修复 config.json - 分离 DeepSeek/OpenAI Key 并设置默认模型"""
import json, shutil, os

path = r'C:\Users\Administrator\.pycoder\config.json'
backup = path + '.bak'

# 备份
shutil.copy2(path, backup)
print(f"备份已创建: {backup}")

d = json.load(open(path, encoding='utf-8'))
prov = d.setdefault('provider', {})
keys = prov.setdefault('api_keys', {})

print("=== 修复前 ===")
print(json.dumps({k: v[:10]+'...'+v[-4:] for k, v in keys.items()}, ensure_ascii=False))
print(f"Default model: {prov.get('default_model', 'N/A')}")

# 修复1: deepseek 和 openai 共用同一个 Key
# 保留 Key 到 openai 下（它实际是 OpenAI Key）
# deepseek 清空
if keys.get('deepseek') and keys.get('openai') and keys['deepseek'] == keys['openai']:
    print("\n[修复] 移除 deepseek 下的错误 OpenAI Key")
    # 保留 openai 的 key 不变
    # deepseek 留空让用户后续配置
    del keys['deepseek']
    # 重新置空
    print("[提示] DeepSeek Key 已移除，请到 Settings 中配置正确的 DeepSeek Key")

# 修复2: 设置默认模型为 agnes-2.0-flash (免费可用)
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
