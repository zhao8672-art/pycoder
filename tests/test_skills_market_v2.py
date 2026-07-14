"""测试升级版 Skills Market"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pycoder.server.skills_market_v2 import get_enhanced_market
from pycoder.server.skills_updater_v2 import get_enhanced_fetcher


async def test_enhanced_sync():
    """测试数据源同步"""
    print("\n[TEST] 增强型数据源同步...")
    manager = get_enhanced_market()
    result = await manager.sync_from_all_sources()

    assert result.get("success"), f"同步失败: {result.get('error')}"
    print(f"✓ 同步成功: {result['total']} 个技能")
    for source in result.get("sources", [])[:3]:
        status = "✓" if source["success"] else "✗"
        name = source.get("name", source["source"])
        count = source.get("count", "ERROR")
        print(f"    {status} {name}: {count}")


def test_advanced_search():
    """测试高级搜索"""
    print("\n[TEST] 高级搜索功能...")
    manager = get_enhanced_market()
    manager._load_registry()

    # 测试基础搜索
    result = manager.search(query="test", limit=5)
    print(f"✓ 搜索 'test': 找到 {result['total']} 个结果")

    # 测试分类搜索
    categories = manager.get_categories()
    if categories:
        first_cat = list(categories.keys())[0]
        result = manager.search(category=first_cat, limit=3)
        print(f"✓ 分类 '{first_cat}': {result['total']} 个技能")

    # 测试排序
    for sort_by in ["quality", "stars", "downloads"]:
        result = manager.search(sort_by=sort_by, limit=1)
        if result["skills"]:
            skill = result["skills"][0]
            print(f"✓ 按 {sort_by} 排序, 首个: {skill.get('name', 'N/A')}")


def test_recommendations():
    """测试推荐引擎"""
    print("\n[TEST] 推荐引擎...")
    manager = get_enhanced_market()
    manager._load_registry()

    recommendations = manager.get_recommendations(limit=3)
    print(f"✓ 推荐 ({len(recommendations)} 个):")
    for rec in recommendations[:3]:
        print(f"    - {rec.skill_name} (得分: {rec.score:.1f})")


def test_trending():
    """测试热门技能"""
    print("\n[TEST] 热门技能...")
    manager = get_enhanced_market()
    manager._load_registry()

    trending = manager.get_trending(limit=5)
    print(f"✓ 热门技能 ({len(trending)} 个):")
    for skill in trending[:3]:
        print(f"    - {skill.get('name')} (⭐{skill.get('stars')})")


def test_stats():
    """测试统计"""
    print("\n[TEST] 统计信息...")
    manager = get_enhanced_market()
    manager._load_registry()

    stats = manager.get_stats()
    print(f"✓ 总技能: {stats['total_skills']}")
    print(f"✓ 分类: {stats['categories_count']}")
    print(f"✓ 总星数: {stats['total_stars']}")
    print(f"✓ 平均评分: {stats['avg_rating']}")


def test_skill_rating():
    """测试评分功能"""
    print("\n[TEST] 技能评分...")
    manager = get_enhanced_market()
    manager._load_registry()

    if not manager._registry:
        print("✓ 无技能数据，跳过评分测试")
        return

    skill_id = list(manager._registry.keys())[0]
    result = manager.rate_skill(skill_id, rating=5, review="很棒!")

    assert result.get("success"), "评分失败"
    print(f"✓ 评分成功: {skill_id} = {result['rating']} ⭐")


async def run_all_tests():
    """运行所有测试"""
    print("=" * 70)
    print("  Skills Market 升级版测试")
    print("=" * 70)

    tests = [
        ("数据源同步", test_enhanced_sync, True),
        ("高级搜索", test_advanced_search, False),
        ("推荐引擎", test_recommendations, False),
        ("热门技能", test_trending, False),
        ("统计信息", test_stats, False),
        ("技能评分", test_skill_rating, False),
    ]

    results = {}
    for name, func, is_async in tests:
        try:
            if is_async:
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
    print(f"\n总体: {passed}/{len(results)} 通过\n")

    return passed == len(results)


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
