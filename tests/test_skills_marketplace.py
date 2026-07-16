"""
测试 pycoder.skills 技能市场模块

覆盖范围:
- SkillMarketplace 初始化
- 技能注册/注销
- 技能列表与搜索
- 技能安装/卸载
- 内置技能枚举
- 技能元数据验证
- 技能依赖检查
- 错误处理
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pycoder.skills import SkillDefinition, SkillMarketplace, get_marketplace
from pycoder.skills.builtin import (
    BUILTIN_SKILLS,
    SKILLS_BY_CATEGORY,
    get_builtin_skill,
    get_builtin_skills_by_category,
)

# ═══════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════


def _make_skill_def(
    skill_id: str = "test-skill",
    name: str = "测试技能",
    version: str = "1.0.0",
    description: str = "测试技能描述",
    author: str = "PyCoder",
    category: str = "general",
    tags: list[str] | None = None,
    dependencies: list[str] | None = None,
    is_builtin: bool = False,
    markdown_content: str = "",
) -> SkillDefinition:
    """创建测试用 SkillDefinition"""
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
        markdown_content=markdown_content or f"# {name}\n\n测试技能内容。",
    )


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

    yield skills_dir

    # 清理
    SkillMarketplace._instance = None
    if skills_dir.exists():
        shutil.rmtree(skills_dir, ignore_errors=True)


@pytest.fixture
def marketplace(temp_skills_dir: Path) -> SkillMarketplace:
    """创建隔离的技能市场实例"""
    mp = SkillMarketplace()
    return mp


@pytest.fixture
def registered_skill(marketplace: SkillMarketplace) -> SkillDefinition:
    """注册一个测试技能并返回其定义"""
    skill_def = _make_skill_def(
        skill_id="test-registered",
        name="已注册技能",
        description="预注册的测试技能",
        category="testing",
        tags=["test", "pytest"],
    )
    marketplace._save_skill_to_db(skill_def, mark_as_installed=False)
    marketplace._save_skill_content(skill_def)
    return skill_def


@pytest.fixture
def installed_skill(marketplace: SkillMarketplace) -> SkillDefinition:
    """安装一个测试技能并返回其定义"""
    skill_def = _make_skill_def(
        skill_id="test-installed",
        name="已安装技能",
        description="已安装的测试技能",
        category="tools",
        tags=["test", "installed"],
    )
    marketplace._save_skill_to_db(skill_def, mark_as_installed=True)
    marketplace._save_skill_content(skill_def)
    return skill_def


# ═══════════════════════════════════════════════
# SkillDefinition 测试
# ═══════════════════════════════════════════════


class TestSkillDefinition:
    """SkillDefinition 数据类测试"""

    def test_create_definition(self) -> None:
        """测试创建技能定义"""
        sd = SkillDefinition(
            id="my-skill",
            name="我的技能",
            version="2.0.0",
            description="技能描述",
            author="tester",
            category="tools",
            tags=["python", "test"],
            dependencies=["dep-1"],
        )
        assert sd.id == "my-skill"
        assert sd.name == "我的技能"
        assert sd.version == "2.0.0"
        assert sd.tags == ["python", "test"]
        assert sd.dependencies == ["dep-1"]
        assert sd.install_count == 0
        assert sd.rating == 0.0
        assert sd.is_builtin is False

    def test_default_values(self) -> None:
        """测试默认值"""
        sd = SkillDefinition(id="s1", name="n1")
        assert sd.version == "1.0.0"
        assert sd.description == ""
        assert sd.author == "PyCoder"
        assert sd.category == "general"
        assert sd.tags == []
        assert sd.dependencies == []
        assert sd.markdown_content == ""

    def test_to_dict(self) -> None:
        """测试转换为字典"""
        sd = SkillDefinition(
            id="s1",
            name="n1",
            version="1.0.0",
            description="desc",
            tags=["a", "b"],
            dependencies=["d1"],
            is_builtin=True,
        )
        d = sd.to_dict()
        assert d["id"] == "s1"
        assert d["name"] == "n1"
        assert d["tags"] == ["a", "b"]
        assert d["dependencies"] == ["d1"]
        assert d["is_builtin"] is True
        # to_dict 不包含 markdown_content
        assert "markdown_content" not in d


# ═══════════════════════════════════════════════
# SkillMarketplace 初始化测试
# ═══════════════════════════════════════════════


class TestSkillMarketplaceInit:
    """SkillMarketplace 初始化测试"""

    def test_singleton(self, temp_skills_dir: Path) -> None:
        """测试单例模式"""
        mp1 = SkillMarketplace()
        mp2 = SkillMarketplace()
        assert mp1 is mp2

    def test_initialization_creates_db(self, temp_skills_dir: Path) -> None:
        """测试初始化创建数据库文件"""
        SkillMarketplace()
        db_path = temp_skills_dir / "skills.db"
        assert db_path.exists()

    def test_initialization_creates_dir(self, temp_skills_dir: Path) -> None:
        """测试初始化创建技能目录"""
        SkillMarketplace()
        assert temp_skills_dir.exists()

    def test_builtin_skills_preinstalled(self, marketplace: SkillMarketplace) -> None:
        """测试内置技能已预安装"""
        stats = marketplace.get_stats()
        assert stats["total_skills"] >= len(BUILTIN_SKILLS)
        assert stats["builtin_skills"] >= len(BUILTIN_SKILLS)

    def test_get_stats(self, marketplace: SkillMarketplace) -> None:
        """测试获取统计信息"""
        stats = marketplace.get_stats()
        assert "total_skills" in stats
        assert "installed_skills" in stats
        assert "builtin_skills" in stats
        assert "average_rating" in stats
        assert "total_installs" in stats
        assert "total_ratings" in stats
        assert "categories" in stats
        assert "data_dir" in stats


# ═══════════════════════════════════════════════
# 技能注册测试
# ═══════════════════════════════════════════════


class TestSkillRegistration:
    """技能注册测试"""

    @pytest.mark.asyncio
    async def test_register_skill(self, marketplace: SkillMarketplace) -> None:
        """测试注册技能"""
        skill_def = _make_skill_def(
            skill_id="new-skill",
            name="新技能",
            markdown_content="# 新技能\n\n这是一个新技能。",
        )
        result = await marketplace.register_skill(skill_def, skill_def.markdown_content)
        assert result["success"] is True
        assert result["skill_id"] == "new-skill"
        assert result["name"] == "新技能"

    @pytest.mark.asyncio
    async def test_register_duplicate_skill(self, marketplace: SkillMarketplace) -> None:
        """测试注册重复技能 ID（INSERT OR REPLACE 会覆盖）"""
        skill_def = _make_skill_def(
            skill_id="dup-skill", name="重复技能", markdown_content="# dup"
        )
        await marketplace.register_skill(skill_def, skill_def.markdown_content)
        # 再次注册相同 ID —— INSERT OR REPLACE 会覆盖，返回成功
        result = await marketplace.register_skill(skill_def, skill_def.markdown_content)
        assert result["success"] is True
        assert result["skill_id"] == "dup-skill"

    @pytest.mark.asyncio
    async def test_register_missing_id(self, marketplace: SkillMarketplace) -> None:
        """测试注册时缺少 ID"""
        skill_def = _make_skill_def(skill_id="", name="", markdown_content="# test")
        result = await marketplace.register_skill(skill_def, "# test")
        assert result["success"] is False
        assert "ID" in result["error"]

    @pytest.mark.asyncio
    async def test_register_empty_content(self, marketplace: SkillMarketplace) -> None:
        """测试注册时 Markdown 内容为空"""
        skill_def = _make_skill_def(skill_id="s1", name="n1", markdown_content="")
        result = await marketplace.register_skill(skill_def, "")
        assert result["success"] is False
        assert "内容不能为空" in result["error"]

    @pytest.mark.asyncio
    async def test_register_with_tags(self, marketplace: SkillMarketplace) -> None:
        """测试注册带标签的技能"""
        skill_def = _make_skill_def(
            skill_id="tagged-skill",
            name="带标签技能",
            tags=["python", "ai", "ml"],
            markdown_content="# tagged",
        )
        result = await marketplace.register_skill(skill_def, skill_def.markdown_content)
        assert result["success"] is True
        # 验证标签可通过搜索找到
        search = await marketplace.search_skills(tags=["python"])
        assert search["total"] >= 1

    @pytest.mark.asyncio
    async def test_register_with_dependencies(self, marketplace: SkillMarketplace) -> None:
        """测试注册带依赖的技能"""
        skill_def = _make_skill_def(
            skill_id="dependent-skill",
            name="依赖技能",
            dependencies=["code-review", "test-generator"],
            markdown_content="# dependent",
        )
        result = await marketplace.register_skill(skill_def, skill_def.markdown_content)
        assert result["success"] is True


# ═══════════════════════════════════════════════
# 技能安装/卸载测试
# ═══════════════════════════════════════════════


class TestSkillInstallUninstall:
    """技能安装与卸载测试"""

    @pytest.mark.asyncio
    async def test_install_skill(
        self, marketplace: SkillMarketplace, registered_skill: SkillDefinition
    ) -> None:
        """测试安装技能"""
        result = await marketplace.install_skill(registered_skill.id)
        assert result["success"] is True
        assert result["skill_id"] == registered_skill.id
        assert result["action"] == "installed"

    @pytest.mark.asyncio
    async def test_install_already_installed(
        self, marketplace: SkillMarketplace, installed_skill: SkillDefinition
    ) -> None:
        """测试安装已安装的技能"""
        result = await marketplace.install_skill(installed_skill.id)
        assert result["success"] is True
        assert result["action"] == "skip"

    @pytest.mark.asyncio
    async def test_install_nonexistent(self, marketplace: SkillMarketplace) -> None:
        """测试安装不存在的技能"""
        result = await marketplace.install_skill("nonexistent-skill")
        assert result["success"] is False
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_uninstall_skill(
        self, marketplace: SkillMarketplace, installed_skill: SkillDefinition
    ) -> None:
        """测试卸载技能"""
        result = await marketplace.uninstall_skill(installed_skill.id)
        assert result["success"] is True
        assert result["action"] == "uninstalled"

    @pytest.mark.asyncio
    async def test_uninstall_builtin(self, marketplace: SkillMarketplace) -> None:
        """测试卸载内置技能（应拒绝）"""
        result = await marketplace.uninstall_skill("code-review")
        assert result["success"] is False
        assert "内置技能" in result["error"]

    @pytest.mark.asyncio
    async def test_uninstall_nonexistent(self, marketplace: SkillMarketplace) -> None:
        """测试卸载不存在的技能"""
        result = await marketplace.uninstall_skill("nonexistent-skill")
        assert result["success"] is False
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_uninstall_not_installed(
        self, marketplace: SkillMarketplace, registered_skill: SkillDefinition
    ) -> None:
        """测试卸载未安装的技能"""
        result = await marketplace.uninstall_skill(registered_skill.id)
        assert result["success"] is True
        assert result["action"] == "skip"


# ═══════════════════════════════════════════════
# 技能列表与搜索测试
# ═══════════════════════════════════════════════


class TestSkillListSearch:
    """技能列表与搜索测试"""

    @pytest.mark.asyncio
    async def test_list_skills(self, marketplace: SkillMarketplace) -> None:
        """测试列出技能"""
        result = await marketplace.list_skills()
        assert "skills" in result
        assert "total" in result
        assert result["total"] >= len(BUILTIN_SKILLS)

    @pytest.mark.asyncio
    async def test_list_skills_by_category(self, marketplace: SkillMarketplace) -> None:
        """测试按分类列出技能"""
        result = await marketplace.list_skills(category="quality")
        for skill in result["skills"]:
            assert skill["category"] == "quality"

    @pytest.mark.asyncio
    async def test_list_skills_sort_by_name(self, marketplace: SkillMarketplace) -> None:
        """测试按名称排序"""
        result = await marketplace.list_skills(sort_by="name")
        names = [s["name"] for s in result["skills"]]
        assert names == sorted(names)

    @pytest.mark.asyncio
    async def test_list_skills_sort_by_install_count(self, marketplace: SkillMarketplace) -> None:
        """测试按安装次数排序"""
        result = await marketplace.list_skills(sort_by="install_count")
        assert "skills" in result

    @pytest.mark.asyncio
    async def test_list_skills_limit(self, marketplace: SkillMarketplace) -> None:
        """测试限制返回数量"""
        result = await marketplace.list_skills(limit=5)
        assert len(result["skills"]) <= 5

    @pytest.mark.asyncio
    async def test_search_skills_by_name(self, marketplace: SkillMarketplace) -> None:
        """测试按名称搜索"""
        result = await marketplace.search_skills(query="代码审查")
        assert result["total"] >= 1
        skill_names = [s["name"] for s in result["skills"]]
        assert any("代码审查" in name for name in skill_names)

    @pytest.mark.asyncio
    async def test_search_skills_by_description(self, marketplace: SkillMarketplace) -> None:
        """测试按描述搜索"""
        result = await marketplace.search_skills(query="安全")
        assert result["total"] >= 1

    @pytest.mark.asyncio
    async def test_search_skills_by_category(self, marketplace: SkillMarketplace) -> None:
        """测试按分类过滤搜索"""
        result = await marketplace.search_skills(category="testing")
        for skill in result["skills"]:
            assert skill["category"] == "testing"

    @pytest.mark.asyncio
    async def test_search_skills_by_tags(self, marketplace: SkillMarketplace) -> None:
        """测试按标签搜索"""
        result = await marketplace.search_skills(tags=["git"])
        assert result["total"] >= 1

    @pytest.mark.asyncio
    async def test_search_skills_no_results(self, marketplace: SkillMarketplace) -> None:
        """测试搜索无结果"""
        result = await marketplace.search_skills(query="zzz_nonexistent_zzz")
        assert result["total"] == 0
        assert result["skills"] == []

    @pytest.mark.asyncio
    async def test_search_skills_combined(self, marketplace: SkillMarketplace) -> None:
        """测试组合搜索条件"""
        result = await marketplace.search_skills(
            query="代码", category="quality", tags=["代码审查"]
        )
        assert result["total"] >= 0  # 不报错即可


# ═══════════════════════════════════════════════
# 技能详情与更新测试
# ═══════════════════════════════════════════════


class TestSkillDetailUpdate:
    """技能详情与更新测试"""

    @pytest.mark.asyncio
    async def test_get_skill(self, marketplace: SkillMarketplace) -> None:
        """测试获取技能详情"""
        result = await marketplace.get_skill("code-review")
        assert "skill" in result
        assert result["skill"]["name"] == "代码审查"
        assert "markdown_content" in result["skill"]

    @pytest.mark.asyncio
    async def test_get_skill_nonexistent(self, marketplace: SkillMarketplace) -> None:
        """测试获取不存在的技能"""
        result = await marketplace.get_skill("nonexistent")
        assert "error" in result
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_update_skill(self, marketplace: SkillMarketplace) -> None:
        """测试更新技能"""
        # 先注册一个技能
        skill_def = _make_skill_def(
            skill_id="update-test",
            name="更新测试",
            markdown_content="# 原始内容",
        )
        await marketplace.register_skill(skill_def, skill_def.markdown_content)

        result = await marketplace.update_skill(
            "update-test",
            {"name": "已更新", "description": "新描述"},
        )
        assert result["success"] is True
        assert "name" in result["updated_fields"]

        # 验证更新
        detail = await marketplace.get_skill("update-test")
        assert detail["skill"]["name"] == "已更新"
        assert detail["skill"]["description"] == "新描述"

    @pytest.mark.asyncio
    async def test_update_skill_nonexistent(self, marketplace: SkillMarketplace) -> None:
        """测试更新不存在的技能"""
        result = await marketplace.update_skill("nope", {"name": "x"})
        assert result["success"] is False
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_update_skill_no_fields(self, marketplace: SkillMarketplace) -> None:
        """测试更新无有效字段"""
        result = await marketplace.update_skill("code-review", {"unknown_field": "x"})
        assert result["success"] is False
        assert "没有可更新的字段" in result["error"]


# ═══════════════════════════════════════════════
# 技能评分测试
# ═══════════════════════════════════════════════


class TestSkillRating:
    """技能评分测试"""

    @pytest.mark.asyncio
    async def test_rate_skill(self, marketplace: SkillMarketplace) -> None:
        """测试评分技能"""
        result = await marketplace.rate_skill("code-review", 5)
        assert result["success"] is True
        assert result["skill_id"] == "code-review"
        assert result["new_rating"] > 0
        assert result["rating_count"] >= 1

    @pytest.mark.asyncio
    async def test_rate_skill_invalid_rating(self, marketplace: SkillMarketplace) -> None:
        """测试无效评分（超出范围）"""
        result = await marketplace.rate_skill("code-review", 0)
        assert result["success"] is False
        assert "1-5" in result["error"]

        result = await marketplace.rate_skill("code-review", 6)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_rate_nonexistent_skill(self, marketplace: SkillMarketplace) -> None:
        """测试评分不存在的技能"""
        result = await marketplace.rate_skill("nonexistent", 3)
        assert result["success"] is False
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_multiple_ratings(self, marketplace: SkillMarketplace) -> None:
        """测试多次评分"""
        await marketplace.rate_skill("code-review", 5)
        await marketplace.rate_skill("code-review", 3)
        result = await marketplace.rate_skill("code-review", 4)
        assert result["success"] is True
        assert result["rating_count"] >= 3


# ═══════════════════════════════════════════════
# 内置技能测试
# ═══════════════════════════════════════════════


class TestBuiltinSkills:
    """内置技能测试"""

    def test_builtin_skills_count(self) -> None:
        """测试内置技能数量"""
        assert len(BUILTIN_SKILLS) >= 10

    def test_builtin_skills_all_have_ids(self) -> None:
        """测试所有内置技能都有 ID"""
        for skill in BUILTIN_SKILLS:
            assert skill.id != ""
            assert skill.name != ""
            assert skill.is_builtin is True

    def test_builtin_skills_markdown_content(self) -> None:
        """测试内置技能都有 Markdown 内容"""
        for skill in BUILTIN_SKILLS:
            assert skill.markdown_content != ""
            assert len(skill.markdown_content) > 50  # 内容要有一定长度

    def test_get_builtin_skill(self) -> None:
        """测试按 ID 获取内置技能"""
        skill = get_builtin_skill("code-review")
        assert skill is not None
        assert skill.name == "代码审查"

        skill = get_builtin_skill("nonexistent")
        assert skill is None

    def test_get_builtin_skills_by_category(self) -> None:
        """测试按分类获取内置技能"""
        quality_skills = get_builtin_skills_by_category("quality")
        quality_ids = {s.id for s in quality_skills}
        assert "code-review" in quality_ids
        assert "lint-fixer" in quality_ids

        tools_skills = get_builtin_skills_by_category("tools")
        tools_ids = {s.id for s in tools_skills}
        assert "git-helper" in tools_ids
        assert "dependency-checker" in tools_ids
        assert "project-scaffolder" in tools_ids

    def test_get_builtin_skills_unknown_category(self) -> None:
        """测试获取未知分类的内置技能"""
        skills = get_builtin_skills_by_category("nonexistent_category")
        assert skills == []

    def test_skills_by_category_coverage(self) -> None:
        """测试 SKILLS_BY_CATEGORY 覆盖所有内置技能"""
        all_ids_in_index: set[str] = set()
        for ids in SKILLS_BY_CATEGORY.values():
            all_ids_in_index.update(ids)
        all_builtin_ids = {s.id for s in BUILTIN_SKILLS}
        assert all_builtin_ids == all_ids_in_index

    def test_builtin_skills_unique_ids(self) -> None:
        """测试内置技能 ID 唯一"""
        ids = [s.id for s in BUILTIN_SKILLS]
        assert len(ids) == len(set(ids))

    def test_builtin_skills_metadata(self) -> None:
        """测试内置技能元数据完整性"""
        for skill in BUILTIN_SKILLS:
            assert skill.version == "1.0.0"
            assert skill.author == "PyCoder"
            assert skill.category in SKILLS_BY_CATEGORY
            assert len(skill.tags) > 0


# ═══════════════════════════════════════════════
# 技能元数据验证测试
# ═══════════════════════════════════════════════


class TestSkillMetadataValidation:
    """技能元数据验证测试"""

    @pytest.mark.asyncio
    async def test_skill_content_persisted(self, marketplace: SkillMarketplace) -> None:
        """测试技能内容持久化到文件系统"""
        skill_def = _make_skill_def(
            skill_id="persist-test",
            name="持久化测试",
            markdown_content="# 持久化\n\n测试内容持久化。",
        )
        await marketplace.register_skill(skill_def, skill_def.markdown_content)

        # 通过 get_skill 验证内容
        detail = await marketplace.get_skill("persist-test")
        assert "持久化" in detail["skill"]["markdown_content"]

    @pytest.mark.asyncio
    async def test_skill_version_tracking(self, marketplace: SkillMarketplace) -> None:
        """测试技能版本追踪"""
        skill_def = _make_skill_def(
            skill_id="version-test",
            name="版本测试",
            version="2.5.0",
            markdown_content="# version test",
        )
        await marketplace.register_skill(skill_def, skill_def.markdown_content)
        detail = await marketplace.get_skill("version-test")
        assert detail["skill"]["version"] == "2.5.0"

    @pytest.mark.asyncio
    async def test_skill_created_at(self, marketplace: SkillMarketplace) -> None:
        """测试技能创建时间"""
        skill_def = _make_skill_def(
            skill_id="time-test",
            name="时间测试",
            markdown_content="# time test",
        )
        result = await marketplace.register_skill(skill_def, skill_def.markdown_content)
        assert result["success"] is True

        detail = await marketplace.get_skill("time-test")
        assert detail["skill"]["created_at"] != ""
        assert detail["skill"]["updated_at"] != ""

    def test_skill_definition_to_dict_excludes_content(self) -> None:
        """测试 SkillDefinition.to_dict 不包含 markdown_content"""
        sd = _make_skill_def(
            skill_id="s1", name="n1", markdown_content="secret content"
        )
        d = sd.to_dict()
        assert "markdown_content" not in d


# ═══════════════════════════════════════════════
# 依赖检查测试
# ═══════════════════════════════════════════════


class TestDependencyChecking:
    """技能依赖检查测试"""

    @pytest.mark.asyncio
    async def test_skill_with_dependencies(self, marketplace: SkillMarketplace) -> None:
        """测试带依赖的技能注册"""
        skill_def = _make_skill_def(
            skill_id="dep-skill",
            name="依赖技能",
            dependencies=["code-review"],
            markdown_content="# dep skill",
        )
        result = await marketplace.register_skill(skill_def, skill_def.markdown_content)
        assert result["success"] is True

        # 验证依赖信息被保存
        detail = await marketplace.get_skill("dep-skill")
        assert "code-review" in detail["skill"]["dependencies"]

    @pytest.mark.asyncio
    async def test_skill_with_multiple_dependencies(self, marketplace: SkillMarketplace) -> None:
        """测试多依赖技能"""
        skill_def = _make_skill_def(
            skill_id="multi-dep",
            name="多依赖技能",
            dependencies=["code-review", "test-generator", "security-scanner"],
            markdown_content="# multi dep",
        )
        result = await marketplace.register_skill(skill_def, skill_def.markdown_content)
        assert result["success"] is True

        detail = await marketplace.get_skill("multi-dep")
        deps = detail["skill"]["dependencies"]
        assert "code-review" in deps
        assert "test-generator" in deps
        assert "security-scanner" in deps

    @pytest.mark.asyncio
    async def test_skill_with_no_dependencies(self, marketplace: SkillMarketplace) -> None:
        """测试无依赖技能"""
        skill_def = _make_skill_def(
            skill_id="no-dep",
            name="无依赖",
            dependencies=[],
            markdown_content="# no dep",
        )
        result = await marketplace.register_skill(skill_def, skill_def.markdown_content)
        assert result["success"] is True

        detail = await marketplace.get_skill("no-dep")
        assert detail["skill"]["dependencies"] == []


# ═══════════════════════════════════════════════
# 错误处理测试
# ═══════════════════════════════════════════════


class TestErrorHandling:
    """错误处理测试"""

    def test_get_marketplace_singleton(self, temp_skills_dir: Path) -> None:
        """测试 get_marketplace 单例"""
        mp1 = get_marketplace()
        mp2 = get_marketplace()
        assert mp1 is mp2

    @pytest.mark.asyncio
    async def test_install_skill_missing_from_db(
        self, marketplace: SkillMarketplace
    ) -> None:
        """测试安装数据库中不存在的技能"""
        result = await marketplace.install_skill("i-do-not-exist-anywhere")
        assert result["success"] is False
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_rate_skill_out_of_range_low(self, marketplace: SkillMarketplace) -> None:
        """测试评分为 0"""
        result = await marketplace.rate_skill("code-review", 0)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_rate_skill_out_of_range_high(self, marketplace: SkillMarketplace) -> None:
        """测试评分为 6"""
        result = await marketplace.rate_skill("code-review", 6)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_register_skill_whitespace_content(
        self, marketplace: SkillMarketplace
    ) -> None:
        """测试注册时 Markdown 内容仅为空白"""
        skill_def = _make_skill_def(skill_id="ws", name="空白", markdown_content="")
        result = await marketplace.register_skill(skill_def, "   \n  ")
        assert result["success"] is False
        assert "内容不能为空" in result["error"]

    @pytest.mark.asyncio
    async def test_update_skill_invalid_fields(self, marketplace: SkillMarketplace) -> None:
        """测试更新无效字段"""
        result = await marketplace.update_skill(
            "code-review",
            {"invalid_field": "value", "another_invalid": 123},
        )
        assert result["success"] is False
        assert "没有可更新的字段" in result["error"]
