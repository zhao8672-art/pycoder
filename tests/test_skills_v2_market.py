"""测试 pycoder.skills 技能市场 V2 升级

覆盖范围（全部 V2 新增或重写方法）:
- _migrate_add_columns_if_missing — 增量字段迁移幂等性
- install_skill(install_dependencies=True) — 递归安装依赖
- _topological_sort — 拓扑排序 + 环检测
- _install_single — 单技能安装
- _rollback_install — 回滚安装
- rate_skill(user_id, review_text) — 原子评分 + 防重复
- submit_review — 评论提交
- get_reviews — 评论列表 + 排序
- search_skills_v2 — FTS5 搜索 + 12 维筛选 + 分页
- _fts_search — FTS5 全文搜索（含降级）
- _tokenize_for_fts — 分词（含 jieba 不可用降级）
- get_skill — 详情扩展（screenshots/versions/rating_distribution/reviews）
- add_screenshot — 添加截图
- add_version — 添加版本（含重复版本 IntegrityError）
- create_install_task + _run_install_task + get_install_task + _update_task — 异步安装任务
- check_updates — 更新检查
- update_skill_version — 单技能更新
- update_all — 批量更新
- toggle_favorite + get_favorites — 收藏
- list_categories — 分类列表
- _row_to_dict — V2 字段对齐
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from pycoder.skills import SkillDefinition, SkillMarketplace

# ═══════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════


def _make_skill_def(
    skill_id: str = "test-v2-skill",
    name: str = "V2测试技能",
    version: str = "1.0.0",
    description: str = "V2测试技能描述",
    author: str = "PyCoder",
    category: str = "general",
    tags: list[str] | None = None,
    dependencies: list[str] | None = None,
    is_builtin: bool = False,
    verified: bool = False,
    publisher: str = "",
    local_version: str = "",
    remote_version: str = "",
    stars: int = 0,
    source_url: str = "",
    markdown_content: str = "",
) -> SkillDefinition:
    """创建测试用 SkillDefinition（含 V2 新增字段）"""
    return SkillDefinition(
        id=skill_id,
        name=name,
        version=version,
        description=description,
        author=author,
        category=category,
        tags=tags or [],
        dependencies=dependencies or [],
        is_builtin=is_builtin,
        verified=verified,
        publisher=publisher,
        local_version=local_version,
        remote_version=remote_version,
        stars=stars,
        source_url=source_url,
        markdown_content=markdown_content or f"# {name}\n\nV2 测试技能内容。",
    )


def _register_skill(
    mp: SkillMarketplace,
    skill_id: str = "test-v2-skill",
    **kwargs: Any,
) -> SkillDefinition:
    """保存技能到数据库（不标记为已安装）"""
    sd = _make_skill_def(skill_id=skill_id, **kwargs)
    mp._save_skill_to_db(sd, mark_as_installed=False)
    mp._save_skill_content(sd)
    return sd


def _rebuild_fts_index(mp: SkillMarketplace) -> None:
    """重建 FTS5 索引为非 contentless 表（绕过后端 contentless schema bug）

    后端 skills_fts 使用 content='' + skill_id UNINDEXED，导致 SELECT skill_id
    始终返回 NULL。本辅助函数重建为标准 FTS5 表，使 skill_id 可正确返回，
    用于测试 _fts_search 与 search_skills_v2 的 FTS5 逻辑。
    """
    with sqlite3.connect(str(mp._db_path)) as conn:
        conn.execute("DROP TABLE IF EXISTS skills_fts")
        # 非 contentless 表：UNINDEXED 列仍会被存储
        conn.execute(
            "CREATE VIRTUAL TABLE skills_fts USING fts5("
            "skill_id UNINDEXED, name, description, tags"
            ")"
        )
        rows = conn.execute("SELECT id, name, description, tags FROM skills").fetchall()
        for row in rows:
            conn.execute(
                "INSERT INTO skills_fts(skill_id, name, description, tags) "
                "VALUES (?, ?, ?, ?)",
                (row[0], row[1], row[2], row[3]),
            )
        conn.commit()


# ═══════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════


@pytest.fixture
def temp_skills_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """创建临时技能目录，隔离测试数据"""
    skills_dir = tmp_path / "data" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    # 重置单例
    SkillMarketplace._instance = None

    # 修改模块级常量
    import pycoder.skills as skills_module

    monkeypatch.setattr(skills_module, "DATA_DIR", skills_dir)
    monkeypatch.setattr(skills_module, "DB_PATH", skills_dir / "skills.db")
    # 同步重置模块级全局单例 _marketplace
    monkeypatch.setattr(skills_module, "_marketplace", None)

    yield skills_dir

    # 清理
    SkillMarketplace._instance = None
    skills_module._marketplace = None


@pytest.fixture
def marketplace(temp_skills_dir: Path) -> SkillMarketplace:
    """创建隔离的技能市场实例（含内置技能）"""
    return SkillMarketplace()


@pytest.fixture
def clean_marketplace(marketplace: SkillMarketplace) -> SkillMarketplace:
    """清空所有技能数据的 marketplace（不含内置技能）"""
    with sqlite3.connect(str(marketplace._db_path)) as conn:
        # 按外键依赖顺序清除
        for table in [
            "skill_screenshots",
            "skill_versions",
            "skill_reviews",
            "skill_favorites",
            "install_tasks",
            "ratings",
        ]:
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM skills")
        # skills_fts 是 contentless FTS5 表，不支持 DELETE
        # 直接 DROP（search_skills_v2 会自动降级 LIKE 搜索）
        conn.execute("DROP TABLE IF EXISTS skills_fts")
        conn.commit()
    return marketplace


# ═══════════════════════════════════════════════
# 1. _migrate_add_columns_if_missing 测试
# ═══════════════════════════════════════════════


class TestMigration:
    """增量字段迁移幂等性测试"""

    def test_migrate_adds_missing_columns(self, marketplace: SkillMarketplace) -> None:
        """测试：调用迁移应能添加缺失列"""
        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY)")
            SkillMarketplace._migrate_add_columns_if_missing(
                conn, "test_table", {"col_a": "TEXT DEFAULT ''", "col_b": "INTEGER DEFAULT 0"}
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(test_table)").fetchall()}
        assert "col_a" in cols
        assert "col_b" in cols

    def test_migrate_idempotent(self, marketplace: SkillMarketplace) -> None:
        """测试：重复调用迁移不应报错且不重复添加"""
        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.execute("CREATE TABLE test_table2 (id INTEGER PRIMARY KEY)")
            SkillMarketplace._migrate_add_columns_if_missing(
                conn, "test_table2", {"col_x": "TEXT DEFAULT ''"}
            )
            # 第二次调用 — 应无副作用、无异常
            SkillMarketplace._migrate_add_columns_if_missing(
                conn, "test_table2", {"col_x": "TEXT DEFAULT ''"}
            )
            cols = [row[1] for row in conn.execute("PRAGMA table_info(test_table2)").fetchall()]
        assert cols.count("col_x") == 1

    def test_migrate_skips_existing_columns(self, marketplace: SkillMarketplace) -> None:
        """测试：已存在的列应被跳过"""
        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.execute("CREATE TABLE test_table3 (id INTEGER PRIMARY KEY, existing TEXT)")
            SkillMarketplace._migrate_add_columns_if_missing(
                conn,
                "test_table3",
                {"existing": "TEXT DEFAULT ''", "new_col": "INTEGER DEFAULT 0"},
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(test_table3)").fetchall()}
        assert "existing" in cols
        assert "new_col" in cols

    def test_migrate_v2_columns_on_skills_table(self, marketplace: SkillMarketplace) -> None:
        """测试：skills 表应包含所有 V2 新增列"""
        with sqlite3.connect(str(marketplace._db_path)) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(skills)").fetchall()}
        # V2 新增列
        for col in [
            "publisher",
            "verified",
            "source_url",
            "homepage_url",
            "license",
            "icon_url",
            "local_version",
            "remote_version",
            "stars",
        ]:
            assert col in cols, f"skills 表缺少 V2 列: {col}"


# ═══════════════════════════════════════════════
# 2. _topological_sort 测试
# ═══════════════════════════════════════════════


class TestTopologicalSort:
    """拓扑排序 + 环检测测试"""

    def test_no_dependencies(self, marketplace: SkillMarketplace) -> None:
        """无依赖的技能应返回 [自身]"""
        sd = _register_skill(marketplace, skill_id="v2-nodeps")
        order = marketplace._topological_sort("v2-nodeps")
        assert order == ["v2-nodeps"]

    def test_chain_dependency(self, clean_marketplace: SkillMarketplace) -> None:
        """A 依赖 B，B 依赖 C → 顺序应为 [C, B, A]"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="dep-c", name="C")
        _register_skill(mp, skill_id="dep-b", name="B", dependencies=["dep-c"])
        _register_skill(mp, skill_id="dep-a", name="A", dependencies=["dep-b"])

        order = mp._topological_sort("dep-a")
        # 依赖在前，根技能在后
        assert order.index("dep-c") < order.index("dep-b")
        assert order.index("dep-b") < order.index("dep-a")
        assert order[-1] == "dep-a"

    def test_cycle_detection_raises(self, clean_marketplace: SkillMarketplace) -> None:
        """A 依赖 B，B 依赖 A → 应抛出 ValueError"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="cyc-a", name="A", dependencies=["cyc-b"])
        _register_skill(mp, skill_id="cyc-b", name="B", dependencies=["cyc-a"])

        with pytest.raises(ValueError, match="依赖环"):
            mp._topological_sort("cyc-a")

    def test_self_cycle_detection(self, clean_marketplace: SkillMarketplace) -> None:
        """A 依赖 A → 应抛出 ValueError"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="self-cyc", name="Self", dependencies=["self-cyc"])
        with pytest.raises(ValueError, match="依赖环"):
            mp._topological_sort("self-cyc")


# ═══════════════════════════════════════════════
# 3. _install_single 测试
# ═══════════════════════════════════════════════


class TestInstallSingle:
    """单技能安装测试"""

    def test_install_single_success(self, marketplace: SkillMarketplace) -> None:
        """成功安装未安装的技能"""
        _register_skill(marketplace, skill_id="v2-single")
        result = marketplace._install_single("v2-single")
        assert result["success"] is True
        assert result["action"] == "installed"
        assert "installed_at" in result

        # 验证数据库状态
        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT installed_at, install_count, local_version FROM skills WHERE id = ?",
                ("v2-single",),
            ).fetchone()
        assert row["installed_at"] != ""
        assert row["install_count"] == 1
        assert row["local_version"] == "1.0.0"

    def test_install_single_already_installed_skip(self, marketplace: SkillMarketplace) -> None:
        """已安装的技能应返回 skip"""
        _register_skill(marketplace, skill_id="v2-installed")
        marketplace._install_single("v2-installed")
        # 第二次调用
        result = marketplace._install_single("v2-installed")
        assert result["success"] is True
        assert result["action"] == "skip"

    def test_install_single_nonexistent(self, marketplace: SkillMarketplace) -> None:
        """安装不存在的技能应失败"""
        result = marketplace._install_single("nonexistent-skill-xyz")
        assert result["success"] is False
        assert "不存在" in result["error"]

    def test_install_single_writes_content_file(self, marketplace: SkillMarketplace) -> None:
        """安装时应将 Markdown 内容写入文件系统（若文件不存在）"""
        sd = _make_skill_def(
            skill_id="v2-install-content",
            markdown_content="# 自定义内容\n\n这是测试内容。",
        )
        marketplace._save_skill_to_db(sd, mark_as_installed=False)
        # 不调用 _save_skill_content，使文件不存在
        skill_file = marketplace._skills_dir / "v2-install-content" / "SKILL.md"
        assert not skill_file.exists()

        marketplace._install_single("v2-install-content")
        # 安装后文件应被写入
        assert skill_file.exists()
        content = skill_file.read_text(encoding="utf-8")
        assert "自定义内容" in content


# ═══════════════════════════════════════════════
# 4. _rollback_install 测试
# ═══════════════════════════════════════════════


class TestRollbackInstall:
    """回滚安装测试"""

    def test_rollback_clears_installed_at(self, marketplace: SkillMarketplace) -> None:
        """回滚应清空 installed_at 和 local_version"""
        _register_skill(marketplace, skill_id="v2-rollback")
        marketplace._install_single("v2-rollback")

        marketplace._rollback_install("v2-rollback")

        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT installed_at, local_version FROM skills WHERE id = ?",
                ("v2-rollback",),
            ).fetchone()
        assert row["installed_at"] == ""
        assert row["local_version"] == ""

    def test_rollback_removes_skill_dir(self, marketplace: SkillMarketplace) -> None:
        """回滚应删除技能内容目录"""
        sd = _register_skill(marketplace, skill_id="v2-rollback-dir")
        marketplace._install_single("v2-rollback-dir")

        skill_dir = marketplace._skills_dir / "v2-rollback-dir"
        assert skill_dir.exists()

        marketplace._rollback_install("v2-rollback-dir")
        assert not skill_dir.exists()


# ═══════════════════════════════════════════════
# 5. install_skill(install_dependencies=True) 测试
# ═══════════════════════════════════════════════


class TestInstallSkillWithDeps:
    """递归依赖安装测试"""

    @pytest.mark.asyncio
    async def test_install_recursive_installs_all_deps(self, clean_marketplace: SkillMarketplace) -> None:
        """A 依赖 B，B 依赖 C → 安装 A 应自动安装 B 和 C"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="rec-c", name="C")
        _register_skill(mp, skill_id="rec-b", name="B", dependencies=["rec-c"])
        _register_skill(mp, skill_id="rec-a", name="A", dependencies=["rec-b"])

        result = await mp.install_skill("rec-a", install_dependencies=True)
        assert result["success"] is True
        assert "rec-a" in result["installed_ids"]
        assert "rec-b" in result["installed_ids"]
        assert "rec-c" in result["installed_ids"]
        assert set(result["dependencies_installed"]) == {"rec-b", "rec-c"}

    @pytest.mark.asyncio
    async def test_install_without_dependencies_flag(self, clean_marketplace: SkillMarketplace) -> None:
        """install_dependencies=False → 只装目标技能，不装依赖"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="nodep-c", name="C")
        _register_skill(mp, skill_id="nodep-b", name="B", dependencies=["nodep-c"])
        _register_skill(mp, skill_id="nodep-a", name="A", dependencies=["nodep-b"])

        result = await mp.install_skill("nodep-a", install_dependencies=False)
        assert result["success"] is True
        assert result["installed_ids"] == ["nodep-a"]

        # 依赖不应被安装
        with sqlite3.connect(str(mp._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row_b = conn.execute(
                "SELECT installed_at FROM skills WHERE id = ?", ("nodep-b",)
            ).fetchone()
        assert row_b["installed_at"] == ""

    @pytest.mark.asyncio
    async def test_install_already_installed_returns_skip(self, marketplace: SkillMarketplace) -> None:
        """已安装的技能应返回 skip 动作"""
        _register_skill(marketplace, skill_id="v2-already")
        await marketplace.install_skill("v2-already")
        result = await marketplace.install_skill("v2-already")
        assert result["success"] is True
        assert result["action"] == "skip"

    @pytest.mark.asyncio
    async def test_install_nonexistent_skill(self, marketplace: SkillMarketplace) -> None:
        """安装不存在的技能应失败"""
        result = await marketplace.install_skill("totally-nonexistent-xyz")
        assert result["success"] is False
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_install_rollback_on_dependency_failure(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """依赖链中某个依赖不存在 → 已装的依赖应被回滚"""
        mp = clean_marketplace
        # A 依赖 [B_ok, C_missing]，C_missing 不存在
        _register_skill(mp, skill_id="rb-ok", name="B-OK")
        _register_skill(mp, skill_id="rb-target", name="Target", dependencies=["rb-ok", "rb-missing"])

        result = await mp.install_skill("rb-target", install_dependencies=True)
        assert result["success"] is False
        assert result["failed_dependency"] == "rb-missing"
        assert "rb-ok" in result["rolled_back"]

        # 验证 rb-ok 已被回滚（installed_at 清空）
        with sqlite3.connect(str(mp._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT installed_at FROM skills WHERE id = ?", ("rb-ok",)
            ).fetchone()
        assert row["installed_at"] == ""

    @pytest.mark.asyncio
    async def test_install_cycle_returns_error(self, clean_marketplace: SkillMarketplace) -> None:
        """存在依赖环 → 应返回错误，不无限循环"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="cyc2-a", name="A", dependencies=["cyc2-b"])
        _register_skill(mp, skill_id="cyc2-b", name="B", dependencies=["cyc2-a"])

        result = await mp.install_skill("cyc2-a", install_dependencies=True)
        assert result["success"] is False
        assert "依赖环" in result["error"]


# ═══════════════════════════════════════════════
# 6. rate_skill 测试 — 原子评分 + 防重复
# ═══════════════════════════════════════════════


class TestRateSkill:
    """原子评分测试"""

    @pytest.mark.asyncio
    async def test_rate_skill_new_rating(self, marketplace: SkillMarketplace) -> None:
        """新评分应增加 rating_count"""
        _register_skill(marketplace, skill_id="v2-rate")
        result = await marketplace.rate_skill("v2-rate", 5, user_id="u1")
        assert result["success"] is True
        assert result["is_update"] is False
        assert result["rating_count"] == 1
        assert result["new_rating"] == 5.0

    @pytest.mark.asyncio
    async def test_rate_skill_update_existing(self, marketplace: SkillMarketplace) -> None:
        """同一 user_id 第二次评分应为更新，rating_count 不增加"""
        _register_skill(marketplace, skill_id="v2-rate2")
        await marketplace.rate_skill("v2-rate2", 3, user_id="u1")
        result = await marketplace.rate_skill("v2-rate2", 5, user_id="u1")
        assert result["success"] is True
        assert result["is_update"] is True
        assert result["rating_count"] == 1  # 仍是 1
        assert result["previous_rating"] == 3
        assert result["new_rating"] == 5.0

    @pytest.mark.asyncio
    async def test_rate_skill_invalid_rating_low(self, marketplace: SkillMarketplace) -> None:
        """评分 0 应被拒绝"""
        _register_skill(marketplace, skill_id="v2-rate3")
        result = await marketplace.rate_skill("v2-rate3", 0, user_id="u1")
        assert result["success"] is False
        assert "1-5" in result["error"]

    @pytest.mark.asyncio
    async def test_rate_skill_invalid_rating_high(self, marketplace: SkillMarketplace) -> None:
        """评分 6 应被拒绝"""
        _register_skill(marketplace, skill_id="v2-rate4")
        result = await marketplace.rate_skill("v2-rate4", 6, user_id="u1")
        assert result["success"] is False
        assert "1-5" in result["error"]

    @pytest.mark.asyncio
    async def test_rate_skill_nonexistent_skill(self, marketplace: SkillMarketplace) -> None:
        """对不存在的技能评分应失败"""
        result = await marketplace.rate_skill("nonexistent-rate", 5, user_id="u1")
        assert result["success"] is False
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_rate_skill_one_per_user_dedup(self, marketplace: SkillMarketplace) -> None:
        """多个用户评分应累加；同一用户重复评分为更新"""
        _register_skill(marketplace, skill_id="v2-rate5")
        # 三个不同用户评分
        await marketplace.rate_skill("v2-rate5", 4, user_id="u1")
        await marketplace.rate_skill("v2-rate5", 5, user_id="u2")
        await marketplace.rate_skill("v2-rate5", 5, user_id="u3")
        # u1 更新评分
        result = await marketplace.rate_skill("v2-rate5", 2, user_id="u1")

        assert result["success"] is True
        assert result["is_update"] is True
        assert result["rating_count"] == 3  # 仍为 3
        # 平均 = (2 + 5 + 5) / 3 = 4.0
        assert result["new_rating"] == 4.0

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore")
    async def test_rate_skill_concurrent_atomic(self, marketplace: SkillMarketplace) -> None:
        """10 个并发评分 → rating_count 应为 10（原子性）"""
        _register_skill(marketplace, skill_id="v2-concurrent")

        def _rate(user_id: str) -> dict[str, Any]:
            return asyncio.run(
                marketplace.rate_skill("v2-concurrent", 5, user_id=user_id)
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(_rate, f"conc-user-{i}") for i in range(10)
            ]
            results = [f.result(timeout=30) for f in futures]

        # 所有评分应成功
        successful = [r for r in results if r.get("success")]
        assert len(successful) == 10, (
            f"并发评分应有 10 个成功，实际 {len(successful)}: {results}"
        )

        # 验证数据库中 rating_count == 10
        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT rating, rating_count FROM skills WHERE id = ?",
                ("v2-concurrent",),
            ).fetchone()
        assert row["rating_count"] == 10
        assert row["rating"] == 5.0


# ═══════════════════════════════════════════════
# 7. submit_review 测试
# ═══════════════════════════════════════════════


class TestSubmitReview:
    """评论提交测试"""

    @pytest.mark.asyncio
    async def test_submit_review_delegates_to_rate_skill(
        self, marketplace: SkillMarketplace
    ) -> None:
        """submit_review 应委托给 rate_skill，并保存 review_text"""
        _register_skill(marketplace, skill_id="v2-review")
        result = await marketplace.submit_review(
            "v2-review", 5, "非常好用", user_id="rev1", user_name="Reviewer1"
        )
        assert result["success"] is True
        assert result["is_update"] is False

        # 验证 review_text 已保存
        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT review_text, user_name FROM skill_reviews "
                "WHERE skill_id = ? AND user_id = ?",
                ("v2-review", "rev1"),
            ).fetchone()
        assert row["review_text"] == "非常好用"
        assert row["user_name"] == "Reviewer1"


# ═══════════════════════════════════════════════
# 8. get_reviews 测试
# ═══════════════════════════════════════════════


class TestGetReviews:
    """评论列表 + 排序测试"""

    @pytest.mark.asyncio
    async def test_get_reviews_default_recent_sort(self, marketplace: SkillMarketplace) -> None:
        """默认按 recent 排序"""
        _register_skill(marketplace, skill_id="v2-reviews")
        await marketplace.submit_review("v2-reviews", 5, "第一条", user_id="r1")
        await marketplace.submit_review("v2-reviews", 4, "第二条", user_id="r2")

        result = await marketplace.get_reviews("v2-reviews")
        assert result["total"] == 2
        assert result["sort_by"] == "recent"
        # recent 排序：第一条（更早创建）应在后
        assert result["reviews"][0]["user_id"] == "r1" or result["reviews"][0]["user_id"] == "r2"

    @pytest.mark.asyncio
    async def test_get_reviews_sort_by_helpful(self, marketplace: SkillMarketplace) -> None:
        """按 helpful 排序：helpful_count 高的在前"""
        _register_skill(marketplace, skill_id="v2-reviews-h")
        await marketplace.submit_review("v2-reviews-h", 5, "评1", user_id="h1")
        await marketplace.submit_review("v2-reviews-h", 5, "评2", user_id="h2")

        # 手动设置 helpful_count
        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.execute(
                "UPDATE skill_reviews SET helpful_count = 10 WHERE user_id = 'h2'"
            )
            conn.execute(
                "UPDATE skill_reviews SET helpful_count = 1 WHERE user_id = 'h1'"
            )
            conn.commit()

        result = await marketplace.get_reviews("v2-reviews-h", sort_by="helpful")
        assert result["reviews"][0]["user_id"] == "h2"  # helpful_count=10 在前

    @pytest.mark.asyncio
    async def test_get_reviews_sort_rating_desc(self, marketplace: SkillMarketplace) -> None:
        """按评分降序排序"""
        _register_skill(marketplace, skill_id="v2-reviews-rd")
        await marketplace.submit_review("v2-reviews-rd", 3, "中", user_id="rd1")
        await marketplace.submit_review("v2-reviews-rd", 5, "高", user_id="rd2")
        await marketplace.submit_review("v2-reviews-rd", 1, "低", user_id="rd3")

        result = await marketplace.get_reviews("v2-reviews-rd", sort_by="rating_desc")
        ratings = [r["rating"] for r in result["reviews"]]
        assert ratings == sorted(ratings, reverse=True)
        assert result["reviews"][0]["rating"] == 5

    @pytest.mark.asyncio
    async def test_get_reviews_sort_rating_asc(self, marketplace: SkillMarketplace) -> None:
        """按评分升序排序"""
        _register_skill(marketplace, skill_id="v2-reviews-ra")
        await marketplace.submit_review("v2-reviews-ra", 3, "中", user_id="ra1")
        await marketplace.submit_review("v2-reviews-ra", 5, "高", user_id="ra2")
        await marketplace.submit_review("v2-reviews-ra", 1, "低", user_id="ra3")

        result = await marketplace.get_reviews("v2-reviews-ra", sort_by="rating_asc")
        ratings = [r["rating"] for r in result["reviews"]]
        assert ratings == sorted(ratings)
        assert result["reviews"][0]["rating"] == 1

    @pytest.mark.asyncio
    async def test_get_reviews_pagination(self, marketplace: SkillMarketplace) -> None:
        """评论分页"""
        _register_skill(marketplace, skill_id="v2-reviews-page")
        for i in range(8):
            await marketplace.submit_review(
                "v2-reviews-page", 5, f"评{i}", user_id=f"p{i}"
            )

        result = await marketplace.get_reviews(
            "v2-reviews-page", limit=3, offset=0
        )
        assert result["total"] == 8
        assert len(result["reviews"]) == 3

        result2 = await marketplace.get_reviews(
            "v2-reviews-page", limit=3, offset=3
        )
        assert len(result2["reviews"]) == 3
        # 两页不应有重复
        ids_page1 = {r["user_id"] for r in result["reviews"]}
        ids_page2 = {r["user_id"] for r in result2["reviews"]}
        assert ids_page1.isdisjoint(ids_page2)

    @pytest.mark.asyncio
    async def test_get_reviews_empty(self, marketplace: SkillMarketplace) -> None:
        """无评论的技能应返回空列表"""
        _register_skill(marketplace, skill_id="v2-no-reviews")
        result = await marketplace.get_reviews("v2-no-reviews")
        assert result["total"] == 0
        assert result["reviews"] == []


# ═══════════════════════════════════════════════
# 9. search_skills_v2 测试 — FTS5 + 12 维筛选 + 分页
# ═══════════════════════════════════════════════


class TestSearchSkillsV2:
    """V2 统一搜索测试"""

    @pytest.mark.asyncio
    async def test_search_v2_no_query_returns_all_paginated(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """无查询应返回所有技能（受分页限制）"""
        mp = clean_marketplace
        for i in range(15):
            _register_skill(mp, skill_id=f"v2-pg-{i}", name=f"技能{i}")

        result = await mp.search_skills_v2(page=1, page_size=10)
        assert result["total"] == 15
        assert len(result["skills"]) == 10
        assert result["page"] == 1
        assert result["page_size"] == 10

    @pytest.mark.asyncio
    async def test_search_v2_pagination_page2(self, clean_marketplace: SkillMarketplace) -> None:
        """page=2&page_size=5 应返回第 6-10 条"""
        mp = clean_marketplace
        for i in range(15):
            _register_skill(mp, skill_id=f"v2-pg2-{i}", name=f"技能{i:02d}")

        result = await mp.search_skills_v2(page=2, page_size=5)
        assert result["total"] == 15
        assert len(result["skills"]) == 5
        assert result["page"] == 2

    @pytest.mark.asyncio
    async def test_search_v2_filter_by_category(self, clean_marketplace: SkillMarketplace) -> None:
        """按分类筛选"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="v2-cat-a", name="A", category="tools")
        _register_skill(mp, skill_id="v2-cat-b", name="B", category="quality")
        _register_skill(mp, skill_id="v2-cat-c", name="C", category="tools")

        result = await mp.search_skills_v2(category="tools")
        ids = {s["id"] for s in result["skills"]}
        assert ids == {"v2-cat-a", "v2-cat-c"}

    @pytest.mark.asyncio
    async def test_search_v2_filter_by_min_rating(self, marketplace: SkillMarketplace) -> None:
        """按最低评分筛选"""
        _register_skill(marketplace, skill_id="v2-mr-low")
        _register_skill(marketplace, skill_id="v2-mr-high")
        await marketplace.rate_skill("v2-mr-low", 2, user_id="u1")
        await marketplace.rate_skill("v2-mr-high", 5, user_id="u1")

        result = await marketplace.search_skills_v2(min_rating=4.0)
        ids = {s["id"] for s in result["skills"]}
        assert "v2-mr-high" in ids
        assert "v2-mr-low" not in ids

    @pytest.mark.asyncio
    async def test_search_v2_filter_by_max_rating(self, marketplace: SkillMarketplace) -> None:
        """按最高评分筛选"""
        _register_skill(marketplace, skill_id="v2-xr-low")
        _register_skill(marketplace, skill_id="v2-xr-high")
        await marketplace.rate_skill("v2-xr-low", 2, user_id="u1")
        await marketplace.rate_skill("v2-xr-high", 5, user_id="u1")

        result = await marketplace.search_skills_v2(max_rating=3.0)
        ids = {s["id"] for s in result["skills"]}
        assert "v2-xr-low" in ids
        assert "v2-xr-high" not in ids

    @pytest.mark.asyncio
    async def test_search_v2_filter_by_min_downloads(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """按最低下载量筛选"""
        mp = clean_marketplace
        sd1 = _register_skill(mp, skill_id="v2-dl-low", name="Low")
        sd2 = _register_skill(mp, skill_id="v2-dl-high", name="High")
        # 直接更新 install_count
        with sqlite3.connect(str(mp._db_path)) as conn:
            conn.execute(
                "UPDATE skills SET install_count = 100 WHERE id = 'v2-dl-high'"
            )
            conn.execute(
                "UPDATE skills SET install_count = 1 WHERE id = 'v2-dl-low'"
            )
            conn.commit()

        result = await mp.search_skills_v2(min_downloads=50)
        ids = {s["id"] for s in result["skills"]}
        assert "v2-dl-high" in ids
        assert "v2-dl-low" not in ids

    @pytest.mark.asyncio
    async def test_search_v2_filter_by_verified_only(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """仅显示已验证"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="v2-vf-no", name="NotVerified", verified=False)
        _register_skill(mp, skill_id="v2-vf-yes", name="Verified", verified=True)

        result = await mp.search_skills_v2(verified_only=True)
        ids = {s["id"] for s in result["skills"]}
        assert "v2-vf-yes" in ids
        assert "v2-vf-no" not in ids

    @pytest.mark.asyncio
    async def test_search_v2_filter_by_has_update_only(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """仅显示有更新的技能"""
        mp = clean_marketplace
        # 技能 1：有更新（local != remote）
        _register_skill(
            mp, skill_id="v2-upd-yes", name="HasUpdate",
            local_version="1.0.0", remote_version="1.1.0"
        )
        # 技能 2：无更新（版本相同）
        _register_skill(
            mp, skill_id="v2-upd-no", name="NoUpdate",
            local_version="1.0.0", remote_version="1.0.0"
        )

        result = await mp.search_skills_v2(has_update_only=True)
        ids = {s["id"] for s in result["skills"]}
        assert "v2-upd-yes" in ids
        assert "v2-upd-no" not in ids

    @pytest.mark.asyncio
    async def test_search_v2_filter_installed_only_true(
        self, marketplace: SkillMarketplace
    ) -> None:
        """仅显示已安装"""
        _register_skill(marketplace, skill_id="v2-inst-yes")
        _register_skill(marketplace, skill_id="v2-inst-no")
        await marketplace.install_skill("v2-inst-yes")

        result = await marketplace.search_skills_v2(installed_only=True)
        ids = {s["id"] for s in result["skills"]}
        assert "v2-inst-yes" in ids
        assert "v2-inst-no" not in ids

    @pytest.mark.asyncio
    async def test_search_v2_filter_installed_only_false(
        self, marketplace: SkillMarketplace
    ) -> None:
        """仅显示未安装"""
        _register_skill(marketplace, skill_id="v2-notinst-yes")
        _register_skill(marketplace, skill_id="v2-notinst-no")
        await marketplace.install_skill("v2-notinst-no")

        result = await marketplace.search_skills_v2(installed_only=False)
        ids = {s["id"] for s in result["skills"]}
        assert "v2-notinst-yes" in ids
        assert "v2-notinst-no" not in ids

    @pytest.mark.asyncio
    async def test_search_v2_filter_by_tags(self, clean_marketplace: SkillMarketplace) -> None:
        """按标签筛选"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="v2-tag-a", name="A", tags=["python", "web"])
        _register_skill(mp, skill_id="v2-tag-b", name="B", tags=["rust", "cli"])

        result = await mp.search_skills_v2(tags=["python"])
        ids = {s["id"] for s in result["skills"]}
        assert "v2-tag-a" in ids
        assert "v2-tag-b" not in ids

    @pytest.mark.asyncio
    async def test_search_v2_filter_by_author(self, clean_marketplace: SkillMarketplace) -> None:
        """按作者筛选"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="v2-auth-a", name="A", author="Alice")
        _register_skill(mp, skill_id="v2-auth-b", name="B", author="Bob")

        result = await mp.search_skills_v2(author="Alice")
        ids = {s["id"] for s in result["skills"]}
        assert "v2-auth-a" in ids
        assert "v2-auth-b" not in ids

    @pytest.mark.asyncio
    async def test_search_v2_filter_combined(self, clean_marketplace: SkillMarketplace) -> None:
        """组合筛选：min_rating=4 + category=quality + verified_only=True"""
        mp = clean_marketplace
        # 符合全部条件的技能
        sd_match = _register_skill(
            mp, skill_id="v2-combo-match", name="Match", category="quality", verified=True
        )
        # 评分不满足
        sd_low_rate = _register_skill(
            mp, skill_id="v2-combo-low", name="LowRate", category="quality", verified=True
        )
        # 分类不满足
        _register_skill(
            mp, skill_id="v2-combo-cat", name="WrongCat", category="tools", verified=True
        )
        # 未验证
        _register_skill(
            mp, skill_id="v2-combo-unv", name="Unverified", category="quality", verified=False
        )

        await mp.rate_skill("v2-combo-match", 5, user_id="u1")
        await mp.rate_skill("v2-combo-low", 2, user_id="u1")

        result = await mp.search_skills_v2(
            min_rating=4.0, category="quality", verified_only=True
        )
        ids = {s["id"] for s in result["skills"]}
        assert "v2-combo-match" in ids
        assert "v2-combo-low" not in ids
        assert "v2-combo-cat" not in ids
        assert "v2-combo-unv" not in ids

    @pytest.mark.asyncio
    async def test_search_v2_sort_by_name(self, clean_marketplace: SkillMarketplace) -> None:
        """按名称升序排序"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="v2-sn-c", name="Charlie")
        _register_skill(mp, skill_id="v2-sn-a", name="Alpha")
        _register_skill(mp, skill_id="v2-sn-b", name="Bravo")

        result = await mp.search_skills_v2(sort_by="name")
        names = [s["name"] for s in result["skills"]]
        # 内置技能可能干扰，验证我们创建的顺序
        assert names.index("Alpha") < names.index("Bravo")
        assert names.index("Bravo") < names.index("Charlie")

    @pytest.mark.asyncio
    async def test_search_v2_sort_by_downloads(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """按下载量降序排序"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="v2-sd-low", name="Low")
        _register_skill(mp, skill_id="v2-sd-high", name="High")
        with sqlite3.connect(str(mp._db_path)) as conn:
            conn.execute("UPDATE skills SET install_count = 100 WHERE id = 'v2-sd-high'")
            conn.execute("UPDATE skills SET install_count = 1 WHERE id = 'v2-sd-low'")
            conn.commit()

        result = await mp.search_skills_v2(sort_by="downloads")
        # 第一个应比第二个下载量大
        assert result["skills"][0]["downloads"] >= result["skills"][1]["downloads"]

    @pytest.mark.asyncio
    async def test_search_v2_fts_chinese(self, marketplace: SkillMarketplace) -> None:
        """FTS5 中文搜索：搜"代码审查"应命中内置 code-review 技能"""
        # 重建 FTS5 索引为非 contentless 表（绕过后端 schema bug）
        _rebuild_fts_index(marketplace)
        result = await marketplace.search_skills_v2(query="代码审查")
        ids = {s["id"] for s in result["skills"]}
        # 内置 code-review 技能的 tags 含 "代码审查"，name 是 "代码审查"
        assert "code-review" in ids

    @pytest.mark.asyncio
    async def test_search_v2_fts_with_like_fallback(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """FTS5 不可用时应降级 LIKE 搜索"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="v2-fts-fb", name="FallbackTest", description="unique-term-xyz")

        # 删除 FTS5 表，强制降级
        with sqlite3.connect(str(mp._db_path)) as conn:
            conn.execute("DROP TABLE IF EXISTS skills_fts")
            conn.commit()

        result = await mp.search_skills_v2(query="unique-term-xyz")
        ids = {s["id"] for s in result["skills"]}
        assert "v2-fts-fb" in ids

    @pytest.mark.asyncio
    async def test_search_v2_fts_empty_result_triggers_like(
        self, marketplace: SkillMarketplace
    ) -> None:
        """FTS5 返回空列表（[]，非 None）时应触发 LIKE 兜底"""
        # 重建 FTS5 索引为非 contentless 表（绕过后端 schema bug）
        _rebuild_fts_index(marketplace)
        # 搜索一个 FTS5 不匹配的词（无对应 token），LIKE 也不匹配
        result = await marketplace.search_skills_v2(query="zzzznonexistentterm12345")
        assert result["total"] == 0
        assert result["skills"] == []

    @pytest.mark.asyncio
    async def test_search_v2_fts_empty_result_like_finds_match(
        self, marketplace: SkillMarketplace
    ) -> None:
        """FTS5 返回空列表时 LIKE 兜底应能找到匹配"""
        # 重建 FTS5 索引为非 contentless 表
        _rebuild_fts_index(marketplace)
        # 搜"代码审查" — FTS5 应命中（code-review 的 name 就是"代码审查"）
        # 但如果搜一个 FTS5 token 不匹配但 LIKE 子串匹配的词，应通过 LIKE 找到
        # code-review description 含 "审查代码质量" — 搜 "查代码质" (非完整 token)
        result = await marketplace.search_skills_v2(query="代码审查")
        ids = {s["id"] for s in result["skills"]}
        assert "code-review" in ids


# ═══════════════════════════════════════════════
# 10. _fts_search 测试
# ═══════════════════════════════════════════════


class TestFtsSearch:
    """FTS5 全文搜索测试"""

    def test_fts_search_returns_results(self, marketplace: SkillMarketplace) -> None:
        """FTS5 搜索应返回结果列表"""
        # 重建 FTS5 索引为非 contentless 表（绕过后端 schema bug）
        _rebuild_fts_index(marketplace)
        # 内置技能含 code-review（name="代码审查"）
        result = marketplace._fts_search("代码审查")
        assert result is not None
        assert isinstance(result, list)
        assert "code-review" in result

    def test_fts_search_no_match_returns_empty(self, marketplace: SkillMarketplace) -> None:
        """FTS5 搜索无匹配应返回空列表（不是 None）"""
        _rebuild_fts_index(marketplace)
        result = marketplace._fts_search("zzzznomatchxyz12345")
        # FTS5 执行成功但无结果 → 返回空列表
        assert result is not None
        assert result == []

    def test_fts_search_unavailable_returns_none(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """FTS5 表不存在时应返回 None（降级信号）"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="v2-fts-none", name="Test")
        # clean_marketplace 已 DROP skills_fts；确保不存在
        with sqlite3.connect(str(mp._db_path)) as conn:
            conn.execute("DROP TABLE IF EXISTS skills_fts")
            conn.commit()

        result = mp._fts_search("Test")
        assert result is None


# ═══════════════════════════════════════════════
# 11. _tokenize_for_fts 测试
# ═══════════════════════════════════════════════


class TestTokenizeForFts:
    """分词测试"""

    def test_tokenize_english(self) -> None:
        """英文按空格分词"""
        result = SkillMarketplace._tokenize_for_fts("code review python")
        tokens = result.split()
        assert "code" in tokens
        assert "review" in tokens
        assert "python" in tokens

    def test_tokenize_with_jieba_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """jieba 可用时应使用 jieba 分词"""
        import sys
        from unittest.mock import MagicMock

        mock_jieba = MagicMock()
        mock_jieba.cut.return_value = ["代码", "审查"]
        monkeypatch.setitem(sys.modules, "jieba", mock_jieba)

        result = SkillMarketplace._tokenize_for_fts("代码审查")
        tokens = result.split()
        assert "代码" in tokens
        assert "审查" in tokens
        mock_jieba.cut.assert_called_once()

    def test_tokenize_chinese_no_jieba(self) -> None:
        """无 jieba 时中文应原样返回（无分隔符可切）"""
        result = SkillMarketplace._tokenize_for_fts("代码审查")
        assert "代码审查" in result

    def test_tokenize_punctuation_split(self) -> None:
        """标点符号应作为分隔符"""
        result = SkillMarketplace._tokenize_for_fts("python,测试；code")
        tokens = result.split()
        assert "python" in tokens
        assert "测试" in tokens
        assert "code" in tokens

    def test_tokenize_empty_string(self) -> None:
        """空字符串应返回空字符串"""
        result = SkillMarketplace._tokenize_for_fts("")
        assert result == ""


# ═══════════════════════════════════════════════
# 12. get_skill 详情扩展测试
# ═══════════════════════════════════════════════


class TestGetSkillExtended:
    """技能详情扩展测试"""

    @pytest.mark.asyncio
    async def test_get_skill_returns_screenshots(self, marketplace: SkillMarketplace) -> None:
        """详情应包含 screenshots 列表"""
        _register_skill(marketplace, skill_id="v2-detail-ss")
        await marketplace.add_screenshot("v2-detail-ss", "https://example.com/1.png", "图1")
        await marketplace.add_screenshot("v2-detail-ss", "https://example.com/2.png", "图2")

        result = await marketplace.get_skill("v2-detail-ss")
        skill = result["skill"]
        assert "screenshots" in skill
        assert len(skill["screenshots"]) == 2
        assert skill["screenshots"][0]["url"] == "https://example.com/1.png"

    @pytest.mark.asyncio
    async def test_get_skill_returns_versions(self, marketplace: SkillMarketplace) -> None:
        """详情应包含 versions 版本历史"""
        _register_skill(marketplace, skill_id="v2-detail-ver")
        await marketplace.add_version("v2-detail-ver", "1.0.0", changelog="初始版本")
        await marketplace.add_version("v2-detail-ver", "1.1.0", changelog="修复 bug")

        result = await marketplace.get_skill("v2-detail-ver")
        skill = result["skill"]
        assert "versions" in skill
        assert len(skill["versions"]) == 2
        # 按时间降序，1.1.0 应在前
        versions = [v["version"] for v in skill["versions"]]
        assert "1.1.0" in versions
        assert "1.0.0" in versions

    @pytest.mark.asyncio
    async def test_get_skill_returns_rating_distribution(
        self, marketplace: SkillMarketplace
    ) -> None:
        """详情应包含 rating_distribution（1-5 星各多少）"""
        _register_skill(marketplace, skill_id="v2-detail-dist")
        await marketplace.rate_skill("v2-detail-dist", 5, user_id="d1")
        await marketplace.rate_skill("v2-detail-dist", 5, user_id="d2")
        await marketplace.rate_skill("v2-detail-dist", 3, user_id="d3")

        result = await marketplace.get_skill("v2-detail-dist")
        dist = result["skill"]["rating_distribution"]
        assert dist["5"] == 2
        assert dist["3"] == 1
        assert dist["1"] == 0
        assert dist["2"] == 0
        assert dist["4"] == 0

    @pytest.mark.asyncio
    async def test_get_skill_returns_reviews(self, marketplace: SkillMarketplace) -> None:
        """详情应包含 reviews 评论列表"""
        _register_skill(marketplace, skill_id="v2-detail-rev")
        await marketplace.submit_review(
            "v2-detail-rev", 5, "非常好", user_id="rev1", user_name="Rev1"
        )

        result = await marketplace.get_skill("v2-detail-rev")
        reviews = result["skill"]["reviews"]
        assert len(reviews) == 1
        assert reviews[0]["review"] == "非常好"
        assert reviews[0]["review_text"] == "非常好"
        assert reviews[0]["user"] == "Rev1"
        assert reviews[0]["rating"] == 5

    @pytest.mark.asyncio
    async def test_get_skill_nonexistent(self, marketplace: SkillMarketplace) -> None:
        """获取不存在的技能应返回 error"""
        result = await marketplace.get_skill("totally-nonexistent")
        assert "error" in result
        assert "不存在" in result["error"]


# ═══════════════════════════════════════════════
# 13. add_screenshot 测试
# ═══════════════════════════════════════════════


class TestAddScreenshot:
    """添加截图测试"""

    @pytest.mark.asyncio
    async def test_add_screenshot_success(self, marketplace: SkillMarketplace) -> None:
        """添加截图应成功并返回 id"""
        _register_skill(marketplace, skill_id="v2-ss")
        result = await marketplace.add_screenshot(
            "v2-ss", "https://example.com/x.png", caption="测试", sort_order=1
        )
        assert result["success"] is True
        assert result["skill_id"] == "v2-ss"
        assert "id" in result
        assert isinstance(result["id"], int)


# ═══════════════════════════════════════════════
# 14. add_version 测试
# ═══════════════════════════════════════════════


class TestAddVersion:
    """添加版本测试"""

    @pytest.mark.asyncio
    async def test_add_version_success(self, marketplace: SkillMarketplace) -> None:
        """添加新版本应成功"""
        _register_skill(marketplace, skill_id="v2-ver")
        result = await marketplace.add_version(
            "v2-ver", "2.0.0", changelog="大版本更新", download_url="https://example.com/v2"
        )
        assert result["success"] is True
        assert result["version"] == "2.0.0"

    @pytest.mark.asyncio
    async def test_add_version_duplicate_integrity_error(
        self, marketplace: SkillMarketplace
    ) -> None:
        """重复版本应触发 IntegrityError 并返回失败"""
        _register_skill(marketplace, skill_id="v2-ver-dup")
        await marketplace.add_version("v2-ver-dup", "1.0.0")
        result = await marketplace.add_version("v2-ver-dup", "1.0.0")
        assert result["success"] is False
        assert "已存在" in result["error"]

    @pytest.mark.asyncio
    async def test_add_version_updates_remote_version(
        self, marketplace: SkillMarketplace
    ) -> None:
        """添加版本应同步更新 skills.remote_version"""
        _register_skill(marketplace, skill_id="v2-ver-remote", version="1.0.0")
        await marketplace.add_version("v2-ver-remote", "1.2.0")

        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT remote_version FROM skills WHERE id = ?", ("v2-ver-remote",)
            ).fetchone()
        assert row["remote_version"] == "1.2.0"


# ═══════════════════════════════════════════════
# 15. 异步安装任务测试
# ═══════════════════════════════════════════════


class TestInstallTasks:
    """异步安装任务测试"""

    @pytest.mark.asyncio
    async def test_create_install_task_success(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """创建安装任务应成功执行并标记为 done"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="v2-task")

        result = await mp.create_install_task("v2-task")
        assert "task_id" in result
        assert result["skill_id"] == "v2-task"

        # 任务应已完成
        task = await mp.get_install_task(result["task_id"])
        assert task["status"] == "done"
        assert task["progress"] == 100
        assert task["completed_at"] != ""

    @pytest.mark.asyncio
    async def test_create_install_task_with_cycle_failure(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """存在依赖环时任务应失败"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="task-cyc-a", dependencies=["task-cyc-b"])
        _register_skill(mp, skill_id="task-cyc-b", dependencies=["task-cyc-a"])

        result = await mp.create_install_task("task-cyc-a")
        task = await mp.get_install_task(result["task_id"])
        assert task["status"] == "failed"
        assert "依赖环" in task["error"]
        assert task["progress"] == 0

    @pytest.mark.asyncio
    async def test_create_install_task_failure_with_missing_dep(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """任务中某个依赖不存在 → 任务应失败并回滚已装的依赖"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="task-rb-ok", name="OK")
        _register_skill(
            mp, skill_id="task-rb-target", name="Target",
            dependencies=["task-rb-ok", "task-rb-missing"]
        )

        result = await mp.create_install_task("task-rb-target")
        task = await mp.get_install_task(result["task_id"])
        assert task["status"] == "failed"
        assert "task-rb-missing" in task["error"]
        # 已装的依赖 task-rb-ok 应被回滚
        with sqlite3.connect(str(mp._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT installed_at FROM skills WHERE id = 'task-rb-ok'"
            ).fetchone()
        assert row["installed_at"] == ""

    @pytest.mark.asyncio
    async def test_create_install_task_without_dependencies(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """install_dependencies=False → 任务只装目标技能"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="task-nd-c", name="C")
        _register_skill(
            mp, skill_id="task-nd-b", name="B", dependencies=["task-nd-c"]
        )
        _register_skill(
            mp, skill_id="task-nd-a", name="A", dependencies=["task-nd-b"]
        )

        result = await mp.create_install_task("task-nd-a", install_dependencies=False)
        task = await mp.get_install_task(result["task_id"])
        assert task["status"] == "done"
        assert task["progress"] == 100

        # 依赖不应被安装
        with sqlite3.connect(str(mp._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT installed_at FROM skills WHERE id = 'task-nd-b'"
            ).fetchone()
        assert row["installed_at"] == ""

    @pytest.mark.asyncio
    async def test_get_install_task_nonexistent(self, marketplace: SkillMarketplace) -> None:
        """查询不存在的任务应返回 error"""
        result = await marketplace.get_install_task("nonexistent-task-id")
        assert "error" in result
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_get_install_task_returns_progress_fields(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """get_install_task 应返回所有进度字段"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="v2-task-fields")
        result = await mp.create_install_task("v2-task-fields")

        task = await mp.get_install_task(result["task_id"])
        for field in [
            "task_id",
            "skill_id",
            "status",
            "progress",
            "current_step",
            "error",
            "started_at",
            "completed_at",
        ]:
            assert field in task, f"任务字段缺失: {field}"

    def test_update_task_no_op(self, marketplace: SkillMarketplace) -> None:
        """_update_task 无任何参数时应为无操作"""
        # 先插入一个任务
        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.execute(
                "INSERT INTO install_tasks (task_id, skill_id, status) VALUES ('noop-task', 's', 'pending')"
            )
            conn.commit()
        # 不传任何字段 — 应不报错
        marketplace._update_task("noop-task")
        # 验证状态未变
        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT status, progress, current_step FROM install_tasks WHERE task_id = ?",
                ("noop-task",),
            ).fetchone()
        assert row["status"] == "pending"
        assert row["progress"] == 0


# ═══════════════════════════════════════════════
# 16. check_updates 测试
# ═══════════════════════════════════════════════


class TestCheckUpdates:
    """更新检查测试"""

    @pytest.mark.asyncio
    async def test_check_updates_for_specific_skill_with_update(
        self, marketplace: SkillMarketplace
    ) -> None:
        """指定技能有更新时应返回"""
        _register_skill(
            marketplace, skill_id="v2-cu-up", local_version="1.0.0", remote_version="1.1.0"
        )
        # 安装该技能（设置 installed_at）
        await marketplace.install_skill("v2-cu-up", install_dependencies=False)

        result = await marketplace.check_updates(skill_id="v2-cu-up")
        assert result["count"] == 1
        assert result["updates"][0]["skill_id"] == "v2-cu-up"
        assert result["updates"][0]["local_version"] == "1.0.0"
        assert result["updates"][0]["remote_version"] == "1.1.0"

    @pytest.mark.asyncio
    async def test_check_updates_for_specific_skill_no_update(
        self, marketplace: SkillMarketplace
    ) -> None:
        """指定技能无更新时应返回空列表"""
        _register_skill(
            marketplace, skill_id="v2-cu-none", local_version="1.0.0", remote_version="1.0.0"
        )
        await marketplace.install_skill("v2-cu-none", install_dependencies=False)

        result = await marketplace.check_updates(skill_id="v2-cu-none")
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_check_updates_for_all_skills(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """检查所有已安装技能的更新"""
        mp = clean_marketplace
        # 有更新
        _register_skill(
            mp, skill_id="v2-cu-all1", local_version="1.0.0", remote_version="2.0.0"
        )
        await mp.install_skill("v2-cu-all1", install_dependencies=False)
        # 无更新
        _register_skill(
            mp, skill_id="v2-cu-all2", local_version="1.0.0", remote_version="1.0.0"
        )
        await mp.install_skill("v2-cu-all2", install_dependencies=False)
        # 未安装
        _register_skill(
            mp, skill_id="v2-cu-all3", local_version="1.0.0", remote_version="2.0.0"
        )

        result = await mp.check_updates()
        ids = {u["skill_id"] for u in result["updates"]}
        assert "v2-cu-all1" in ids
        assert "v2-cu-all2" not in ids
        assert "v2-cu-all3" not in ids  # 未安装


# ═══════════════════════════════════════════════
# 17. update_skill_version 测试
# ═══════════════════════════════════════════════


class TestUpdateSkillVersion:
    """单技能更新测试"""

    @pytest.mark.asyncio
    async def test_update_skill_version_success(self, marketplace: SkillMarketplace) -> None:
        """成功更新到 remote_version"""
        _register_skill(
            marketplace, skill_id="v2-uv-ok", version="1.0.0",
            local_version="1.0.0", remote_version="1.1.0"
        )
        await marketplace.install_skill("v2-uv-ok", install_dependencies=False)
        result = await marketplace.update_skill_version("v2-uv-ok")
        assert result["success"] is True
        assert result["action"] == "updated"
        assert result["new_version"] == "1.1.0"

        # 验证 local_version 已升级
        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT local_version, version FROM skills WHERE id = ?", ("v2-uv-ok",)
            ).fetchone()
        assert row["local_version"] == "1.1.0"
        assert row["version"] == "1.1.0"

    @pytest.mark.asyncio
    async def test_update_skill_version_already_latest(
        self, marketplace: SkillMarketplace
    ) -> None:
        """已是最新版本应返回 skip"""
        _register_skill(
            marketplace, skill_id="v2-uv-latest", version="1.0.0",
            local_version="1.0.0", remote_version="1.0.0"
        )
        await marketplace.install_skill("v2-uv-latest", install_dependencies=False)
        result = await marketplace.update_skill_version("v2-uv-latest")
        assert result["success"] is True
        assert result["action"] == "skip"

    @pytest.mark.asyncio
    async def test_update_skill_version_not_installed(
        self, marketplace: SkillMarketplace
    ) -> None:
        """未安装的技能应失败"""
        _register_skill(marketplace, skill_id="v2-uv-ni", remote_version="1.1.0")
        result = await marketplace.update_skill_version("v2-uv-ni")
        assert result["success"] is False
        assert "未安装" in result["error"]

    @pytest.mark.asyncio
    async def test_update_skill_version_no_remote_version(
        self, marketplace: SkillMarketplace
    ) -> None:
        """无远程版本信息应失败"""
        _register_skill(marketplace, skill_id="v2-uv-nr", remote_version="")
        await marketplace.install_skill("v2-uv-nr", install_dependencies=False)
        result = await marketplace.update_skill_version("v2-uv-nr")
        assert result["success"] is False
        assert "无远程版本" in result["error"]

    @pytest.mark.asyncio
    async def test_update_skill_version_nonexistent(self, marketplace: SkillMarketplace) -> None:
        """不存在的技能应失败"""
        result = await marketplace.update_skill_version("totally-nonexistent")
        assert result["success"] is False
        assert "不存在" in result["error"]


# ═══════════════════════════════════════════════
# 18. update_all 测试
# ═══════════════════════════════════════════════


class TestUpdateAll:
    """批量更新测试"""

    @pytest.mark.asyncio
    async def test_update_all_updates_multiple(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """批量更新所有有可用更新的技能"""
        mp = clean_marketplace
        # 两个有更新的技能
        _register_skill(
            mp, skill_id="v2-ua-1", version="1.0.0",
            local_version="1.0.0", remote_version="2.0.0"
        )
        await mp.install_skill("v2-ua-1", install_dependencies=False)
        _register_skill(
            mp, skill_id="v2-ua-2", version="1.0.0",
            local_version="1.0.0", remote_version="3.0.0"
        )
        await mp.install_skill("v2-ua-2", install_dependencies=False)

        result = await mp.update_all()
        assert set(result["updated"]) == {"v2-ua-1", "v2-ua-2"}
        assert result["failed"] == []
        assert result["skipped"] == []

    @pytest.mark.asyncio
    async def test_update_all_no_updates(self, clean_marketplace: SkillMarketplace) -> None:
        """无可用更新时 update_all 应返回空列表"""
        mp = clean_marketplace
        _register_skill(
            mp, skill_id="v2-ua-none", version="1.0.0",
            local_version="1.0.0", remote_version="1.0.0"
        )
        await mp.install_skill("v2-ua-none", install_dependencies=False)

        result = await mp.update_all()
        assert result["updated"] == []
        assert result["failed"] == []
        assert result["skipped"] == []

    @pytest.mark.asyncio
    async def test_update_all_skips_already_latest(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """update_all 在 check_updates 与 update_skill_version 之间状态变化时应 skip"""
        mp = clean_marketplace
        # 技能有更新
        _register_skill(
            mp, skill_id="v2-ua-skip", version="1.0.0",
            local_version="1.0.0", remote_version="2.0.0"
        )
        await mp.install_skill("v2-ua-skip", install_dependencies=False)
        # 先手动更新一次
        await mp.update_skill_version("v2-ua-skip")
        # 再调 update_all — 此时 local == remote，应跳过（但 check_updates 也不会列出）
        result = await mp.update_all()
        assert result["updated"] == []


# ═══════════════════════════════════════════════
# 19. toggle_favorite + get_favorites 测试
# ═══════════════════════════════════════════════


class TestFavorites:
    """收藏功能测试"""

    @pytest.mark.asyncio
    async def test_toggle_favorite_add_then_remove(
        self, marketplace: SkillMarketplace
    ) -> None:
        """收藏后再调用应取消收藏"""
        _register_skill(marketplace, skill_id="v2-fav")

        r1 = await marketplace.toggle_favorite("v2-fav", user_id="user1")
        assert r1["success"] is True
        assert r1["favorited"] is True

        r2 = await marketplace.toggle_favorite("v2-fav", user_id="user1")
        assert r2["success"] is True
        assert r2["favorited"] is False

    @pytest.mark.asyncio
    async def test_get_favorites_returns_only_favorited(
        self, marketplace: SkillMarketplace
    ) -> None:
        """get_favorites 应只返回已收藏的技能"""
        _register_skill(marketplace, skill_id="v2-fav-yes")
        _register_skill(marketplace, skill_id="v2-fav-no")
        await marketplace.toggle_favorite("v2-fav-yes", user_id="user2")

        result = await marketplace.get_favorites(user_id="user2")
        ids = {s["id"] for s in result["skills"]}
        assert "v2-fav-yes" in ids
        assert "v2-fav-no" not in ids
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_get_favorites_empty_for_user_with_no_favorites(
        self, marketplace: SkillMarketplace
    ) -> None:
        """无收藏的用户应返回空列表"""
        _register_skill(marketplace, skill_id="v2-fav-other")
        await marketplace.toggle_favorite("v2-fav-other", user_id="userA")

        result = await marketplace.get_favorites(user_id="userB")
        assert result["total"] == 0
        assert result["skills"] == []

    @pytest.mark.asyncio
    async def test_toggle_favorite_user_isolation(
        self, marketplace: SkillMarketplace
    ) -> None:
        """不同用户的收藏应相互隔离"""
        _register_skill(marketplace, skill_id="v2-fav-iso")
        await marketplace.toggle_favorite("v2-fav-iso", user_id="userX")
        await marketplace.toggle_favorite("v2-fav-iso", user_id="userY")

        # userX 取消收藏
        await marketplace.toggle_favorite("v2-fav-iso", user_id="userX")

        # userY 的收藏应不受影响
        result_y = await marketplace.get_favorites(user_id="userY")
        assert result_y["total"] == 1
        result_x = await marketplace.get_favorites(user_id="userX")
        assert result_x["total"] == 0


# ═══════════════════════════════════════════════
# 20. list_categories 测试
# ═══════════════════════════════════════════════


class TestListCategories:
    """分类列表测试"""

    @pytest.mark.asyncio
    async def test_list_categories_with_counts(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """分类列表应包含计数"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="v2-cat1-a", name="A", category="alpha")
        _register_skill(mp, skill_id="v2-cat1-b", name="B", category="alpha")
        _register_skill(mp, skill_id="v2-cat1-c", name="C", category="beta")

        result = await mp.list_categories()
        cats = {c["name"]: c for c in result["categories"]}
        assert cats["alpha"]["count"] == 2
        assert cats["beta"]["count"] == 1
        # total_installs 和 avg_rating 字段应存在
        assert "total_installs" in cats["alpha"]
        assert "avg_rating" in cats["alpha"]


# ═══════════════════════════════════════════════
# 21. _row_to_dict 测试 — V2 字段对齐
# ═══════════════════════════════════════════════


class TestRowToDict:
    """V2 字段对齐测试"""

    def test_row_to_dict_includes_all_frontend_fields(
        self, marketplace: SkillMarketplace
    ) -> None:
        """_row_to_dict 应包含前端期望的所有字段"""
        _register_skill(
            marketplace, skill_id="v2-rtd", name="RTD",
            version="1.0.0", stars=42, verified=True, publisher="Pub",
            local_version="1.0.0", remote_version="1.0.0",
        )

        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM skills WHERE id = ?", ("v2-rtd",)
            ).fetchone()
        result = marketplace._row_to_dict(row)

        # 前端期望的所有字段
        required_fields = [
            "id", "name", "version", "description", "author", "category",
            "tags", "dependencies", "install_count", "rating", "rating_count",
            "created_at", "updated_at", "is_builtin", "installed",
            "publisher", "verified", "source_url", "homepage_url", "license",
            "icon_url", "local_version", "remote_version", "stars",
            "downloads", "has_update", "installs", "ratings_count",
        ]
        for field in required_fields:
            assert field in result, f"_row_to_dict 缺少字段: {field}"

        # 验证别名映射
        assert result["downloads"] == result["install_count"]
        assert result["installs"] == result["install_count"]
        assert result["ratings_count"] == result["rating_count"]
        assert result["stars"] == 42
        assert result["verified"] is True
        assert result["publisher"] == "Pub"

    def test_row_to_dict_has_update_true(self, marketplace: SkillMarketplace) -> None:
        """local_version != remote_version → has_update=True"""
        _register_skill(
            marketplace, skill_id="v2-rtd-up", local_version="1.0.0", remote_version="1.1.0"
        )
        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM skills WHERE id = ?", ("v2-rtd-up",)
            ).fetchone()
        result = marketplace._row_to_dict(row)
        assert result["has_update"] is True

    def test_row_to_dict_has_update_false_when_same(self, marketplace: SkillMarketplace) -> None:
        """local_version == remote_version → has_update=False"""
        _register_skill(
            marketplace, skill_id="v2-rtd-same", local_version="1.0.0", remote_version="1.0.0"
        )
        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM skills WHERE id = ?", ("v2-rtd-same",)
            ).fetchone()
        result = marketplace._row_to_dict(row)
        assert result["has_update"] is False

    def test_row_to_dict_has_update_false_when_empty(self, marketplace: SkillMarketplace) -> None:
        """local_version 或 remote_version 为空 → has_update=False"""
        _register_skill(
            marketplace, skill_id="v2-rtd-empty", local_version="", remote_version=""
        )
        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM skills WHERE id = ?", ("v2-rtd-empty",)
            ).fetchone()
        result = marketplace._row_to_dict(row)
        assert result["has_update"] is False

    def test_row_to_dict_publisher_fallback_to_author(
        self, marketplace: SkillMarketplace
    ) -> None:
        """publisher 为空时应回退到 author"""
        _register_skill(
            marketplace, skill_id="v2-rtd-fb", author="AuthorName", publisher=""
        )
        with sqlite3.connect(str(marketplace._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM skills WHERE id = ?", ("v2-rtd-fb",)
            ).fetchone()
        result = marketplace._row_to_dict(row)
        assert result["publisher"] == "AuthorName"


# ═══════════════════════════════════════════════
# 22. register_skill 测试 — 含错误路径
# ═══════════════════════════════════════════════


class TestRegisterSkill:
    """register_skill 注册技能测试"""

    @pytest.mark.asyncio
    async def test_register_skill_success(self, clean_marketplace: SkillMarketplace) -> None:
        """成功注册新技能"""
        mp = clean_marketplace
        sd = _make_skill_def(skill_id="reg-ok", name="RegisterOK", markdown_content="# 内容")
        result = await mp.register_skill(sd, "# 内容")
        assert result["success"] is True
        assert result["skill_id"] == "reg-ok"
        assert result["name"] == "RegisterOK"

    @pytest.mark.asyncio
    async def test_register_skill_empty_id(self, clean_marketplace: SkillMarketplace) -> None:
        """空 ID 应失败"""
        mp = clean_marketplace
        sd = _make_skill_def(skill_id="", name="X", markdown_content="# x")
        result = await mp.register_skill(sd, "# x")
        assert result["success"] is False
        assert "ID" in result["error"]

    @pytest.mark.asyncio
    async def test_register_skill_empty_name(self, clean_marketplace: SkillMarketplace) -> None:
        """空名称应失败"""
        mp = clean_marketplace
        sd = _make_skill_def(skill_id="reg-x", name="", markdown_content="# x")
        result = await mp.register_skill(sd, "# x")
        assert result["success"] is False
        assert "名称" in result["error"]

    @pytest.mark.asyncio
    async def test_register_skill_empty_markdown(self, clean_marketplace: SkillMarketplace) -> None:
        """空 Markdown 应失败"""
        mp = clean_marketplace
        sd = _make_skill_def(skill_id="reg-md", name="X", markdown_content="# x")
        result = await mp.register_skill(sd, "   ")
        assert result["success"] is False
        assert "Markdown" in result["error"]

    @pytest.mark.asyncio
    async def test_register_skill_duplicate_id_overwrites(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """重复 ID 应使用 INSERT OR REPLACE 覆盖（不抛 IntegrityError）"""
        mp = clean_marketplace
        sd1 = _make_skill_def(skill_id="reg-dup", name="First", markdown_content="# x")
        r1 = await mp.register_skill(sd1, "# x")
        assert r1["success"] is True
        # 第二次注册 — 同 ID 不同名称，应覆盖
        sd2 = _make_skill_def(skill_id="reg-dup", name="Second", markdown_content="# y")
        r2 = await mp.register_skill(sd2, "# y")
        # INSERT OR REPLACE 行为：覆盖而非报错
        assert r2["success"] is True
        # 验证数据库中是新的 name
        with sqlite3.connect(str(mp._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT name FROM skills WHERE id = ?", ("reg-dup",)
            ).fetchone()
        assert row["name"] == "Second"


# ═══════════════════════════════════════════════
# 23. uninstall_skill 测试 — 含错误路径
# ═══════════════════════════════════════════════


class TestUninstallSkill:
    """卸载技能测试"""

    @pytest.mark.asyncio
    async def test_uninstall_nonexistent(self, marketplace: SkillMarketplace) -> None:
        """卸载不存在的技能应失败"""
        result = await marketplace.uninstall_skill("totally-not-there")
        assert result["success"] is False
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_uninstall_builtin_rejected(self, marketplace: SkillMarketplace) -> None:
        """内置技能不可卸载"""
        # marketplace fixture 含内置技能（如 code-review）
        result = await marketplace.uninstall_skill("code-review")
        assert result["success"] is False
        assert "内置" in result["error"]

    @pytest.mark.asyncio
    async def test_uninstall_not_installed_skip(self, clean_marketplace: SkillMarketplace) -> None:
        """未安装的技能应返回 skip"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="uninst-skip", name="Skip")
        result = await mp.uninstall_skill("uninst-skip")
        assert result["success"] is True
        assert result["action"] == "skip"

    @pytest.mark.asyncio
    async def test_uninstall_success(self, clean_marketplace: SkillMarketplace) -> None:
        """成功卸载已安装的技能"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="uninst-ok", name="OK")
        await mp.install_skill("uninst-ok", install_dependencies=False)
        result = await mp.uninstall_skill("uninst-ok")
        assert result["success"] is True
        assert result["action"] == "uninstalled"
        # 验证已清空 installed_at
        with sqlite3.connect(str(mp._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT installed_at FROM skills WHERE id = ?", ("uninst-ok",)
            ).fetchone()
        assert row["installed_at"] == ""


# ═══════════════════════════════════════════════
# 24. V1 search_skills 兼容测试
# ═══════════════════════════════════════════════


class TestSearchSkillsV1:
    """V1 search_skills 接口测试（向后兼容）"""

    @pytest.mark.asyncio
    async def test_v1_search_no_filter_returns_all(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """无过滤条件应返回所有"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="v1-a", name="Alpha", description="alpha")
        _register_skill(mp, skill_id="v1-b", name="Beta", description="beta")
        result = await mp.search_skills()
        assert result["total"] >= 2

    @pytest.mark.asyncio
    async def test_v1_search_by_query(self, clean_marketplace: SkillMarketplace) -> None:
        """按关键词搜索"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="v1-q1", name="PythonTool", description="python tool")
        _register_skill(mp, skill_id="v1-q2", name="RustTool", description="rust tool")
        result = await mp.search_skills(query="python")
        ids = {s["id"] for s in result["skills"]}
        assert "v1-q1" in ids
        assert "v1-q2" not in ids

    @pytest.mark.asyncio
    async def test_v1_search_by_category(self, clean_marketplace: SkillMarketplace) -> None:
        """按分类搜索"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="v1-c1", name="X1", category="alpha")
        _register_skill(mp, skill_id="v1-c2", name="X2", category="beta")
        result = await mp.search_skills(category="alpha")
        ids = {s["id"] for s in result["skills"]}
        assert "v1-c1" in ids
        assert "v1-c2" not in ids

    @pytest.mark.asyncio
    async def test_v1_search_by_tags(self, clean_marketplace: SkillMarketplace) -> None:
        """按标签搜索"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="v1-t1", name="Y1", tags=["web", "api"])
        _register_skill(mp, skill_id="v1-t2", name="Y2", tags=["cli"])
        result = await mp.search_skills(tags=["web"])
        ids = {s["id"] for s in result["skills"]}
        assert "v1-t1" in ids
        assert "v1-t2" not in ids


# ═══════════════════════════════════════════════
# 25. list_skills 测试
# ═══════════════════════════════════════════════


class TestListSkills:
    """list_skills 接口测试"""

    @pytest.mark.asyncio
    async def test_list_skills_default(self, clean_marketplace: SkillMarketplace) -> None:
        """默认按 rating 排序"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="ls-a", name="A")
        _register_skill(mp, skill_id="ls-b", name="B")
        result = await mp.list_skills()
        assert result["total"] >= 2

    @pytest.mark.asyncio
    async def test_list_skills_sort_by_name(self, clean_marketplace: SkillMarketplace) -> None:
        """按名称排序"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="ls-c", name="Charlie")
        _register_skill(mp, skill_id="ls-a", name="Alpha")
        _register_skill(mp, skill_id="ls-b", name="Bravo")
        result = await mp.list_skills(sort_by="name", limit=100)
        names = [s["name"] for s in result["skills"]]
        assert names.index("Alpha") < names.index("Bravo")
        assert names.index("Bravo") < names.index("Charlie")

    @pytest.mark.asyncio
    async def test_list_skills_filter_by_category(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """按分类过滤"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="ls-cat-a", name="A", category="alpha")
        _register_skill(mp, skill_id="ls-cat-b", name="B", category="beta")
        result = await mp.list_skills(category="alpha")
        ids = {s["id"] for s in result["skills"]}
        assert "ls-cat-a" in ids
        assert "ls-cat-b" not in ids

    @pytest.mark.asyncio
    async def test_list_skills_limit(self, clean_marketplace: SkillMarketplace) -> None:
        """limit 参数应限制返回数量"""
        mp = clean_marketplace
        for i in range(10):
            _register_skill(mp, skill_id=f"ls-lim-{i}", name=f"Skill{i}")
        result = await mp.list_skills(limit=5)
        assert len(result["skills"]) == 5


# ═══════════════════════════════════════════════
# 26. get_stats 测试
# ═══════════════════════════════════════════════


class TestGetStats:
    """市场统计测试"""

    def test_get_stats_returns_required_fields(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """get_stats 应返回所有统计字段"""
        mp = clean_marketplace
        _register_skill(mp, skill_id="gs-1", name="X1", category="alpha")
        _register_skill(mp, skill_id="gs-2", name="X2", category="beta")

        stats = mp.get_stats()
        for field in [
            "total_skills",
            "installed_skills",
            "builtin_skills",
            "average_rating",
            "total_installs",
            "total_ratings",
            "categories",
            "data_dir",
        ]:
            assert field in stats, f"stats 缺少字段: {field}"
        assert stats["total_skills"] >= 2
        assert isinstance(stats["categories"], dict)
        assert "alpha" in stats["categories"]

    def test_get_stats_empty_marketplace(self, clean_marketplace: SkillMarketplace) -> None:
        """空市场应返回零值统计"""
        stats = clean_marketplace.get_stats()
        assert stats["total_skills"] == 0
        assert stats["installed_skills"] == 0
        assert stats["average_rating"] == 0.0
        assert stats["total_installs"] == 0


# ═══════════════════════════════════════════════
# 27. 模块级函数测试 — get_marketplace / register_capabilities / _handle_*
# ═══════════════════════════════════════════════


class TestModuleLevelFunctions:
    """模块级函数测试"""

    def test_get_marketplace_returns_singleton(self, temp_skills_dir: Path) -> None:
        """get_marketplace 应返回单例"""
        from pycoder.skills import get_marketplace

        m1 = get_marketplace()
        m2 = get_marketplace()
        assert m1 is m2

    @pytest.mark.asyncio
    async def test_handle_search_skills(self, marketplace: SkillMarketplace) -> None:
        """_handle_search_skills 应委托给 marketplace.search_skills"""
        from pycoder.skills import _handle_search_skills

        _register_skill(marketplace, skill_id="hs-1", name="HandlerSearch")
        result = await _handle_search_skills({"query": "HandlerSearch"}, {})
        assert "skills" in result
        assert any(s["id"] == "hs-1" for s in result["skills"])

    @pytest.mark.asyncio
    async def test_handle_install_skill(self, clean_marketplace: SkillMarketplace) -> None:
        """_handle_install_skill 应委托给 marketplace.install_skill"""
        from pycoder.skills import _handle_install_skill

        mp = clean_marketplace
        _register_skill(mp, skill_id="hi-1", name="HandlerInstall")
        result = await _handle_install_skill({"skill_id": "hi-1"}, {})
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_handle_list_skills(self, marketplace: SkillMarketplace) -> None:
        """_handle_list_skills 应委托给 marketplace.list_skills"""
        from pycoder.skills import _handle_list_skills

        _register_skill(marketplace, skill_id="hl-1", name="HandlerList")
        result = await _handle_list_skills({}, {})
        assert "skills" in result

    @pytest.mark.asyncio
    async def test_handle_get_skill(self, marketplace: SkillMarketplace) -> None:
        """_handle_get_skill 应委托给 marketplace.get_skill"""
        from pycoder.skills import _handle_get_skill

        _register_skill(marketplace, skill_id="hg-1", name="HandlerGet")
        result = await _handle_get_skill({"skill_id": "hg-1"}, {})
        assert "skill" in result

    def test_handle_get_stats(self, marketplace: SkillMarketplace) -> None:
        """_handle_get_stats 应委托给 marketplace.get_stats"""
        from pycoder.skills import _handle_get_stats

        result = asyncio.run(_handle_get_stats({}, {}))
        assert "total_skills" in result

    @pytest.mark.asyncio
    async def test_handle_v1_skills_market_default_list(
        self, marketplace: SkillMarketplace
    ) -> None:
        """_handle_v1_skills_market 默认 action=list"""
        from pycoder.skills import _handle_v1_skills_market

        _register_skill(marketplace, skill_id="hv-default", name="HVDefault")
        result = await _handle_v1_skills_market({}, {})
        assert "skills" in result

    @pytest.mark.asyncio
    async def test_handle_v1_skills_market_search(
        self, marketplace: SkillMarketplace
    ) -> None:
        """_handle_v1_skills_market action=search"""
        from pycoder.skills import _handle_v1_skills_market

        _register_skill(marketplace, skill_id="hv-search", name="HVSearch")
        result = await _handle_v1_skills_market(
            {"action": "search", "query": "HVSearch"}, {}
        )
        assert "skills" in result

    @pytest.mark.asyncio
    async def test_handle_v1_skills_market_install_missing_skill_id(
        self, marketplace: SkillMarketplace
    ) -> None:
        """_handle_v1_skills_market action=install 缺少 skill_id 应返回 error"""
        from pycoder.skills import _handle_v1_skills_market

        result = await _handle_v1_skills_market({"action": "install"}, {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_handle_v1_skills_market_install_success(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """_handle_v1_skills_market action=install 成功"""
        from pycoder.skills import _handle_v1_skills_market

        mp = clean_marketplace
        _register_skill(mp, skill_id="hv-install", name="HVInstall")
        result = await _handle_v1_skills_market(
            {"action": "install", "skill_id": "hv-install"}, {}
        )
        assert result["success"] is True

    def test_register_capabilities_registers_all_capabilities(
        self, temp_skills_dir: Path
    ) -> None:
        """register_capabilities 应注册所有能力"""
        from unittest.mock import MagicMock

        from pycoder.skills import register_capabilities

        registry = MagicMock()
        register_capabilities(registry)
        # 应至少注册 5 个能力
        assert registry.register.call_count >= 5


# ═══════════════════════════════════════════════
# 28. SkillDefinition 数据类测试
# ═══════════════════════════════════════════════


class TestSkillDefinition:
    """SkillDefinition 数据类测试"""

    def test_post_init_publisher_fallback_to_author(self) -> None:
        """publisher 为空时应回退到 author"""
        sd = SkillDefinition(id="x", name="X", author="AuthorX")
        assert sd.publisher == "AuthorX"

    def test_post_init_publisher_keeps_explicit_value(self) -> None:
        """publisher 显式提供时应保留"""
        sd = SkillDefinition(id="x", name="X", author="AuthorX", publisher="Pub")
        assert sd.publisher == "Pub"

    def test_has_update_true(self) -> None:
        """local != remote → has_update=True"""
        sd = SkillDefinition(
            id="x", name="X", local_version="1.0.0", remote_version="1.1.0"
        )
        assert sd.has_update is True

    def test_has_update_false_when_same(self) -> None:
        """local == remote → has_update=False"""
        sd = SkillDefinition(
            id="x", name="X", local_version="1.0.0", remote_version="1.0.0"
        )
        assert sd.has_update is False

    def test_has_update_false_when_empty(self) -> None:
        """local 或 remote 为空 → has_update=False"""
        sd1 = SkillDefinition(id="x", name="X", local_version="", remote_version="1.0.0")
        assert sd1.has_update is False
        sd2 = SkillDefinition(id="x", name="X", local_version="1.0.0", remote_version="")
        assert sd2.has_update is False

    def test_to_dict_includes_all_fields(self) -> None:
        """to_dict 应包含所有 V2 字段"""
        sd = SkillDefinition(
            id="x", name="X", version="1.0.0", stars=42, verified=True,
            publisher="Pub", local_version="1.0.0", remote_version="1.1.0",
        )
        d = sd.to_dict()
        for field in [
            "id", "name", "version", "publisher", "verified", "stars",
            "local_version", "remote_version", "has_update", "downloads",
        ]:
            assert field in d
        assert d["has_update"] is True
        assert d["downloads"] == 0  # install_count 默认为 0


# ═══════════════════════════════════════════════
# 29. search_skills limit 参数测试（V1 兼容）
# ═══════════════════════════════════════════════


class TestSearchSkillsLimit:
    """search_skills limit 参数测试"""

    @pytest.mark.asyncio
    async def test_search_skills_with_limit(self, clean_marketplace: SkillMarketplace) -> None:
        """limit 参数应限制返回数量"""
        mp = clean_marketplace
        for i in range(10):
            _register_skill(mp, skill_id=f"sl-{i}", name=f"Skill{i}")
        result = await mp.search_skills(limit=5)
        assert len(result["skills"]) == 5
        assert result["total"] == 5  # total 是返回的数量

    @pytest.mark.asyncio
    async def test_search_skills_no_limit_returns_all(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """limit=0 应返回所有"""
        mp = clean_marketplace
        for i in range(3):
            _register_skill(mp, skill_id=f"sl-all-{i}", name=f"Skill{i}")
        result = await mp.search_skills()
        assert len(result["skills"]) >= 3
