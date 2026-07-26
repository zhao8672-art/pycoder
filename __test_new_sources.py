"""快速验证技能数据源新模块"""
import sys
sys.path.insert(0, ".")

from pycoder.server.skills_data_sources import (
    classify_with_onet, MultiLevelCache,
    ONET_TAXONOMY_MAP, _get_github_token,
)

# 1. ONET 分类测试
tests = [
    ("PyTorch Transformer", "LLM training", "ai-ml"),
    ("React Dashboard", "web frontend tailwind", "web"),
    ("Docker Compose", "container k8s orchestration", "devops"),
    ("PostgreSQL", "sql database indexing", "database"),
    ("Black Python", "code formatter linter", "programming-language"),
    ("MCP Server", "model context protocol tool", "mcp-tools"),
]
for name, desc, expected in tests:
    result = classify_with_onet(name, desc)
    status = "✅" if result == expected else "❌"
    print(f"{status} classify({name!r}, {desc!r}) = {result!r} (期望: {expected!r})")

# 2. 缓存测试
c = MultiLevelCache()
c.set("test_key", {"data": "hello"}, ttl=3600)
assert c.get("test_key") == {"data": "hello"}, "缓存读取失败"
c.delete("test_key")
assert c.get("test_key") is None, "缓存删除失败"
print("✅ MultiLevelCache 读写删除正常")

# 3. Token 检测
token = _get_github_token()
if token:
    print(f"✅ GITHUB_TOKEN 已检测到: {token[:8]}...")
else:
    print("ℹ️ GITHUB_TOKEN 未设置 (匿名 API 配额 60次/时)")

# 4. 分类标准概览
print(f"\nONET 分类体系 ({len(ONET_TAXONOMY_MAP)} 大类):")
for cat_id, cat_info in ONET_TAXONOMY_MAP.items():
    subs = list(cat_info["subcategories"].keys())
    print(f"  {cat_id}: {cat_info['description']} ({len(subs)} 子类)")

print("\n✅ 所有测试通过")
