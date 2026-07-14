#!/usr/bin/env python
"""深度测试 Skills Market 功能"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pycoder.server.skills_market import get_skills_market, SkillsMarketManager
from pycoder.server.skills_updater import get_skills_fetcher


def test_local_cache():
    """测试本地缓存加载"""
    print("\n[TEST] 本地缓存加载...")
    manager = get_skills_market()
    manager._load_local(force=True)
    print(f"✓ 加载了 {len(manager._registry)} 个技能")
    assert len(manager._registry) > 0, "本地缓存为空"


async def test_fetcher():
    """测试爬虫数据源"""
    print("\n[TEST] 爬虫数据源连接...")
    fetcher = get_skills_fetcher()
    result = await fetcher.fetch_all_sources()
    print(f"✓ 总技能数: {result.get('total_skills', 0)}")
    for source in result.get('sources', []):
        status = "✓" if source.get('success') else "✗"
        print(f"    {status} {source['source']}: {source.get('count', '失败')}")
    assert result.get('success', False), "爬虫数据源获取失败"


def test_list_search():
    """测试列表和搜索"""
    print("\n[TEST] 列表和搜索...")
    manager = get_skills_market()
    manager._load_local()

    result = manager.list_skills(sort_by="stars", limit=5)
    print("✓ Top 5 技能 (按星数):")
    for s in result.get('skills', [])[:5]:
        print(f"    - {s['name']} (⭐{s['stars']})")

    search_result = manager.list_skills(search="test", limit=3)
    print(f"✓ 搜索 'test': 找到 {search_result['total']} 个结果")

    categories = manager.get_categories()
    print(f"✓ 分类: {len(categories)} 个")


def test_install():
    """测试技能安装"""
    print("\n[TEST] 技能安装...")
    manager = get_skills_market()
    manager._load_local()

    skills = list(manager._registry.values())
    assert skills, "没有可用技能"

    skill = skills[0]
    print(f"  尝试安装: {skill.name}")

    result = manager.install_skill(skill.id)
    assert result.get('success'), f"安装失败: {result.get('error')}"
    print(f"✓ 安装成功: {result['method']}")
    if manager._is_installed(skill):
        print("✓ 验证安装: 技能已在本地")


def test_rating():
    """测试评分系统"""
    print("\n[TEST] 评分系统...")
    manager = get_skills_market()
    manager._load_local()

    skills = list(manager._registry.values())
    assert skills, "没有可用技能"

    skill = skills[0]
    result = manager.rate_skill(skill.id, rating=4, review="很有用!")
    assert result.get('success'), "评分失败"
    print(f"✓ 评分成功: {result['new_rating']} ⭐")


def test_version():
    """测试版本号比较"""
    print("\n[TEST] 版本号比较...")
    manager = get_skills_market()

    tests = [
        ("1.0.0", "1.0.1", -1),
        ("1.0.1", "1.0.0", 1),
        ("1.0.0", "1.0.0", 0),
    ]

    for v1, v2, expected in tests:
        result = manager._compare_versions(v1, v2)
        status = "✓" if result == expected else "✗"
        print(f"  {status} {v1} vs {v2}: {result}")
        assert result == expected, f"{v1} vs {v2}: 期望 {expected}, 实际 {result}"


def test_persistence():
    """测试数据持久化"""
    print("\n[TEST] 数据持久化...")
    manager = get_skills_market()
    manager._load_local()

    original_count = len(manager._registry)
    manager._save_local()
    print("✓ 保存到本地")

    manager2 = SkillsMarketManager()
    manager2._load_local()
    print(f"  重新加载: {len(manager2._registry)} 个技能")

    assert len(manager2._registry) == original_count, "持久化前后数量不一致"


def test_errors():
    """测试错误处理"""
    print("\n[TEST] 错误处理...")
    manager = get_skills_market()
    manager._load_local()

    result = manager.install_skill("nonexistent-xyz")
    if not result.get('success'):
        print("✓ 正确处理不存在的技能")

    result = manager.rate_skill("test", rating=10)
    if not result.get('success'):
        print("✓ 正确处理无效评分")


async def run_all():
    """运行所有测试"""
    print("=" * 70)
    print("  Skills Market 深度测试")
    print("=" * 70)

    tests = [
        ("本地缓存加载", test_local_cache),
        ("爬虫数据源", test_fetcher),
        ("列表和搜索", test_list_search),
        ("技能安装", test_install),
        ("评分系统", test_rating),
        ("版本号比较", test_version),
        ("数据持久化", test_persistence),
        ("错误处理", test_errors),
    ]

    results = {}
    for name, func in tests:
        try:
            if asyncio.iscoroutinefunction(func):
                await func()
            else:
                func()
            results[name] = "✓ PASS"
        except Exception as e:
            results[name] = f"✗ ERROR: {str(e)[:40]}"

    print("\n" + "=" * 70)
    print("  测试总结")
    print("=" * 70)
    for name, status in results.items():
        print(f"{status:15} {name}")

    passed = sum(1 for s in results.values() if "PASS" in s)
    print(f"\n总体: {passed}/{len(results)} 通过")

    return passed == len(tests)


if __name__ == "__main__":
    success = asyncio.run(run_all())
    sys.exit(0 if success else 1)
