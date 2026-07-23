from __future__ import annotations

import json
import os
import sys
import time
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════
# 2. skills_updater.py 测试
# ═══════════════════════════════════════════════════════════════


class TestFetchedSkill:
    """FetchedSkill 数据类测试"""

    def test_fetched_skill_defaults(self):
        """FetchedSkill 应有合理的默认值"""
        from pycoder.server.skills_updater import FetchedSkill

        skill = FetchedSkill(id="test", name="Test")
        assert skill.id == "test"
        assert skill.name == "Test"
        assert skill.description == ""
        assert skill.stars == 0
        assert skill.downloads == 0
        assert skill.category == "other"
        assert skill.tags == []

    def test_fetched_skill_full_init(self):
        """FetchedSkill 完整初始化"""
        from pycoder.server.skills_updater import FetchedSkill

        skill = FetchedSkill(
            id="test-skill",
            name="Test Skill",
            description="A test skill",
            author="test-author",
            stars=100,
            downloads=50,
            category="code-quality",
            tags=["testing", "quality"],
            version="2.0.0",
            url="https://example.com",
            source="github",
        )
        assert skill.id == "test-skill"
        assert skill.stars == 100
        assert skill.tags == ["testing", "quality"]


class TestExtractFromGitHubSearch:
    """GitHub Search API 提取器测试"""

    def test_extract_empty_items(self):
        """空 items 应返回空列表"""
        from pycoder.server.skills_updater import extract_from_github_search

        result = extract_from_github_search({"items": []})
        assert result == []

    def test_extract_no_items_key(self):
        """无 items 键应返回空列表"""
        from pycoder.server.skills_updater import extract_from_github_search

        result = extract_from_github_search({})
        assert result == []

    def test_extract_single_repo(self):
        """单个仓库应正确提取为 FetchedSkill"""
        from pycoder.server.skills_updater import extract_from_github_search

        data = {
            "items": [
                {
                    "name": "test-skill",
                    "full_name": "author/test-skill",
                    "description": "A test skill for security",
                    "stargazers_count": 42,
                    "forks_count": 10,
                    "topics": ["skills", "security", "testing"],
                    "created_at": "2024-01-01",
                    "updated_at": "2025-01-01",
                }
            ]
        }
        result = extract_from_github_search(data)
        assert len(result) == 1
        skill = result[0]
        assert skill.id == "test-skill"
        assert skill.author == "author"
        assert skill.stars == 42
        assert skill.downloads == 10
        assert skill.source == "github"
        assert skill.url == "https://github.com/author/test-skill"

    def test_extract_infers_security_category(self):
        """包含 security 关键词应推断为 security 分类"""
        from pycoder.server.skills_updater import extract_from_github_search

        data = {
            "items": [
                {
                    "name": "pentest-tool",
                    "full_name": "hacker/pentest-tool",
                    "description": "A penetration testing tool",
                    "stargazers_count": 100,
                    "forks_count": 50,
                    "topics": [],
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        }
        result = extract_from_github_search(data)
        assert result[0].category == "security"

    def test_extract_infers_web_category(self):
        """包含 web 关键词应推断为 web 分类"""
        from pycoder.server.skills_updater import extract_from_github_search

        data = {
            "items": [
                {
                    "name": "react-frontend",
                    "full_name": "dev/react-frontend",
                    "description": "A frontend skill",
                    "stargazers_count": 10,
                    "forks_count": 2,
                    "topics": [],
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        }
        result = extract_from_github_search(data)
        assert result[0].category == "web"

    def test_extract_filters_skill_topics_from_tags(self):
        """tags 应过滤掉 skills 和 claude-skills 主题"""
        from pycoder.server.skills_updater import extract_from_github_search

        data = {
            "items": [
                {
                    "name": "my-skill",
                    "full_name": "author/my-skill",
                    "description": "A skill",
                    "stargazers_count": 5,
                    "forks_count": 1,
                    "topics": ["skills", "claude-skills", "agent-skills", "python", "testing"],
                    "created_at": "",
                    "updated_at": "",
                }
            ]
        }
        result = extract_from_github_search(data)
        assert "skills" not in result[0].tags
        assert "claude-skills" not in result[0].tags
        assert "agent-skills" not in result[0].tags
        assert "python" in result[0].tags


class TestExtractFromSkillsRegistryJson:
    """Skills Registry JSON 提取器测试"""

    def test_extract_empty_skills(self):
        """空 skills 应返回空列表"""
        from pycoder.server.skills_updater import extract_from_skills_registry_json

        result = extract_from_skills_registry_json({"skills": []})
        assert result == []

    def test_extract_skills_with_all_fields(self):
        """应正确提取所有字段"""
        from pycoder.server.skills_updater import extract_from_skills_registry_json

        data = {
            "skills": [
                {
                    "id": "code-review",
                    "name": "Code Review",
                    "description": "AI code review",
                    "author": "test-author",
                    "stars": 100,
                    "downloads": 500,
                    "category": "code-quality",
                    "tags": ["review", "quality"],
                    "version": "1.0.0",
                    "url": "https://example.com",
                    "file": "skill.md",
                    "created_at": "2024-01-01",
                    "updated_at": "2025-01-01",
                }
            ]
        }
        result = extract_from_skills_registry_json(data)
        assert len(result) == 1
        skill = result[0]
        assert skill.id == "code-review"
        assert skill.stars == 100
        assert skill.downloads == 500
        assert skill.source == "awesome-list"

    def test_extract_falls_back_to_name_as_id(self):
        """无 id 时应使用 name 作为 id"""
        from pycoder.server.skills_updater import extract_from_skills_registry_json

        data = {"skills": [{"name": "Test Skill", "description": "A test"}]}
        result = extract_from_skills_registry_json(data)
        assert len(result) == 1
        assert result[0].id == "test-skill"


class TestValidateUrl:
    """URL 验证测试"""

    def test_valid_http_url(self):
        """http URL 应通过验证"""
        from pycoder.server.skills_updater import _validate_url

        result = _validate_url("http://example.com")
        assert result == "http://example.com"

    def test_valid_https_url(self):
        """https URL 应通过验证"""
        from pycoder.server.skills_updater import _validate_url

        result = _validate_url("https://example.com")
        assert result == "https://example.com"

    def test_invalid_file_url_raises(self):
        """file:// 协议应抛出 ValueError"""
        from pycoder.server.skills_updater import _validate_url

        with pytest.raises(ValueError, match="不允许的 URL 协议"):
            _validate_url("file:///etc/passwd")

    def test_invalid_ftp_url_raises(self):
        """ftp:// 协议应抛出 ValueError"""
        from pycoder.server.skills_updater import _validate_url

        with pytest.raises(ValueError, match="不允许的 URL 协议"):
            _validate_url("ftp://example.com")


class TestSkillsFetcher:
    """SkillsFetcher 爬虫测试"""

    @pytest.fixture
    def fetcher(self, tmp_path: Path):
        """创建 SkillsFetcher 实例（使用临时目录）"""
        import os

        from pycoder.server.skills_updater import SkillsFetcher

        with patch.object(os, "getcwd", return_value=str(tmp_path)):
            fetcher = SkillsFetcher()
            return fetcher

    def test_fetcher_init(self, fetcher):
        """SkillsFetcher 初始化应设置默认属性"""
        assert fetcher._last_update == 0.0
        assert "extract_from_github_search" in fetcher._extractors

    def test_get_stats_no_registry(self, fetcher):
        """无注册表文件时 get_stats 应返回默认值"""
        stats = fetcher.get_stats()
        assert stats["skills_count"] == 0
        assert stats["last_update"] == 0
        assert stats["sources"] == []

    def test_get_stats_with_corrupt_registry(self, fetcher, tmp_path: Path):
        """损坏的注册表文件应返回默认值"""
        import os

        fetcher._registry_path = tmp_path / ".skills-registry.json"
        fetcher._registry_path.write_text("not valid json", encoding="utf-8")

        stats = fetcher.get_stats()
        assert stats["skills_count"] == 0

    def test_get_stats_with_valid_registry(self, fetcher, tmp_path: Path):
        """有效的注册表文件应返回统计信息"""
        fetcher._registry_path = tmp_path / ".skills-registry.json"
        fetcher._registry_path.write_text(
            json.dumps({"total": 42, "last_updated": "2025-01-01T00:00:00Z", "source": "github"}),
            encoding="utf-8",
        )

        stats = fetcher.get_stats()
        assert stats["skills_count"] == 42
        assert stats["last_update"] == "2025-01-01T00:00:00Z"

    def test_save_registry_merges_existing_file(self, fetcher, tmp_path: Path):
        """保存注册表应合并已有 file 字段"""
        from pycoder.server.skills_updater import FetchedSkill

        # 创建已有注册表
        fetcher._registry_path = tmp_path / ".skills-registry.json"
        existing = {
            "skills": [
                {"id": "test-skill", "file": "existing_file.md", "url": "https://old.com"}
            ]
        }
        fetcher._registry_path.write_text(json.dumps(existing), encoding="utf-8")

        # 新数据
        skills = {
            "test-skill": FetchedSkill(
                id="test-skill", name="Test Skill", stars=10, file=None, url=None
            )
        }
        fetcher._save_registry(skills)

        # 验证合并
        saved = json.loads(fetcher._registry_path.read_text(encoding="utf-8"))
        saved_skill = saved["skills"][0]
        assert saved_skill["file"] == "existing_file.md"
        assert saved_skill["url"] == "https://old.com"

    def test_save_registry_sorts_by_stars(self, fetcher, tmp_path: Path):
        """保存注册表应按 stars 降序排序"""
        from pycoder.server.skills_updater import FetchedSkill

        fetcher._registry_path = tmp_path / ".skills-registry.json"
        skills = {
            "a": FetchedSkill(id="a", name="A", stars=10),
            "b": FetchedSkill(id="b", name="B", stars=100),
            "c": FetchedSkill(id="c", name="C", stars=50),
        }
        fetcher._save_registry(skills)

        saved = json.loads(fetcher._registry_path.read_text(encoding="utf-8"))
        saved_ids = [s["id"] for s in saved["skills"]]
        assert saved_ids == ["b", "c", "a"]


class TestGetSkillsFetcher:
    """SkillsFetcher 单例测试"""

    def test_get_skills_fetcher_returns_singleton(self):
        """get_skills_fetcher 应返回单例"""
        from pycoder.server.skills_updater import get_skills_fetcher, SkillsFetcher
        import pycoder.server.skills_updater as su

        # 重置全局变量
        su._fetcher = None
        f1 = get_skills_fetcher()
        f2 = get_skills_fetcher()
        assert f1 is f2
        # 清理
        su._fetcher = None


# ═══════════════════════════════════════════════════════════════
# 3. skills_updater_v2.py 测试
# ═══════════════════════════════════════════════════════════════


class TestEnhancedSkill:
    """EnhancedSkill 数据类测试"""

    def test_enhanced_skill_defaults(self):
        """EnhancedSkill 应有合理的默认值"""
        from pycoder.server.skills_updater_v2 import EnhancedSkill

        skill = EnhancedSkill(id="test", name="Test")
        assert skill.id == "test"
        assert skill.name == "Test"
        assert skill.stars == 0
        assert skill.rating == 0.0
        assert skill.category == "other"
        assert skill.verified is False
        assert skill.official is False
        assert skill.archived is False

    def test_quality_score_zero_skill(self):
        """零指标技能的 quality_score 应为 0"""
        from pycoder.server.skills_updater_v2 import EnhancedSkill

        skill = EnhancedSkill(id="test", name="Test")
        assert skill.quality_score() == 0.0

    def test_quality_score_stars_weight(self):
        """Stars 应贡献 30% 权重"""
        from pycoder.server.skills_updater_v2 import EnhancedSkill

        skill = EnhancedSkill(id="test", name="Test", stars=100)
        # stars: min(100, 100/100) * 0.3 = min(100, 1) * 0.3 = 0.3
        assert skill.quality_score() == pytest.approx(0.3, rel=0.01)

    def test_quality_score_downloads_weight(self):
        """Downloads 应贡献 25% 权重"""
        from pycoder.server.skills_updater_v2 import EnhancedSkill

        skill = EnhancedSkill(id="test", name="Test", downloads=1000)
        # downloads: min(100, 1000/1000) * 0.25 = min(100, 1) * 0.25 = 0.25
        assert skill.quality_score() == pytest.approx(0.25, rel=0.01)

    def test_quality_score_rating_weight(self):
        """Rating 应贡献 25% 权重"""
        from pycoder.server.skills_updater_v2 import EnhancedSkill

        skill = EnhancedSkill(id="test", name="Test", rating=5.0)
        # rating: (5/5) * 25 = 25
        assert skill.quality_score() == pytest.approx(25.0, rel=0.01)

    def test_quality_score_verified_and_official(self):
        """Verified 和 Official 各贡献 10 分"""
        from pycoder.server.skills_updater_v2 import EnhancedSkill

        skill = EnhancedSkill(id="test", name="Test", verified=True, official=True)
        assert skill.quality_score() == 20.0

    def test_quality_score_capped_at_100(self):
        """质量分数不应超过 100"""
        from pycoder.server.skills_updater_v2 import EnhancedSkill

        skill = EnhancedSkill(
            id="test", name="Test", stars=10000, downloads=100000, rating=5.0, verified=True, official=True
        )
        assert skill.quality_score() <= 100.0

    def test_to_dict_includes_quality_score(self):
        """to_dict 应包含 quality_score"""
        from pycoder.server.skills_updater_v2 import EnhancedSkill

        skill = EnhancedSkill(id="test", name="Test", stars=50)
        d = skill.to_dict()
        assert "quality_score" in d
        assert d["id"] == "test"
        assert d["name"] == "Test"


class TestInferCategory:
    """分类推断测试"""

    def test_infer_security(self):
        """security 关键词应推断为 security"""
        from pycoder.server.skills_updater_v2 import EnhancedSkillsFetcher

        cat = EnhancedSkillsFetcher._infer_category("pentest tool", "security testing")
        assert cat == "security"

    def test_infer_code_quality(self):
        """test 关键词应推断为 code-quality"""
        from pycoder.server.skills_updater_v2 import EnhancedSkillsFetcher

        cat = EnhancedSkillsFetcher._infer_category("test runner", "unit testing")
        assert cat == "code-quality"

    def test_infer_database(self):
        """database 关键词应推断为 database"""
        from pycoder.server.skills_updater_v2 import EnhancedSkillsFetcher

        cat = EnhancedSkillsFetcher._infer_category("postgres helper", "sql database")
        assert cat == "database"

    def test_infer_devops(self):
        """docker 关键词应推断为 devops"""
        from pycoder.server.skills_updater_v2 import EnhancedSkillsFetcher

        cat = EnhancedSkillsFetcher._infer_category("docker deploy", "kubernetes")
        assert cat == "devops"

    def test_infer_web(self):
        """web 关键词应推断为 web"""
        from pycoder.server.skills_updater_v2 import EnhancedSkillsFetcher

        cat = EnhancedSkillsFetcher._infer_category("react component", "frontend ui")
        assert cat == "web"

    def test_infer_other_as_default(self):
        """未知关键词应默认为 other"""
        from pycoder.server.skills_updater_v2 import EnhancedSkillsFetcher

        cat = EnhancedSkillsFetcher._infer_category("xyz", "unknown content")
        assert cat == "other"


class TestEnhancedSkillsFetcher:
    """EnhancedSkillsFetcher 测试"""

    @pytest.fixture
    def fetcher(self, tmp_path: Path):
        """创建 EnhancedSkillsFetcher 实例"""
        import os

        from pycoder.server.skills_updater_v2 import EnhancedSkillsFetcher

        with patch.object(os, "getcwd", return_value=str(tmp_path)):
            f = EnhancedSkillsFetcher()
            return f

    def test_init_sets_defaults(self, fetcher):
        """初始化应设置默认属性"""
        assert fetcher._last_sync_time == 0.0
        assert fetcher._sync_interval == 86400.0
        assert fetcher._cache == {}
        assert fetcher._auto_sync_task is None

    def test_sources_has_expected_keys(self, fetcher):
        """SOURCES 应包含预期的数据源"""
        expected = [
            "github_awesome_claude",
            "github_topic_claude_skills",
            "github_topic_agent_skills",
            "github_trending_python",
            "github_mcp_servers",
        ]
        for key in expected:
            assert key in fetcher.SOURCES

    def test_seed_skills_not_empty(self, fetcher):
        """SEED_SKILLS 不应为空"""
        assert len(fetcher.SEED_SKILLS) > 0
        for seed in fetcher.SEED_SKILLS:
            assert "id" in seed
            assert "name" in seed

    def test_get_stats_no_registry(self, fetcher):
        """无注册表文件时 get_stats 应返回默认值"""
        stats = fetcher.get_stats()
        assert stats["skills_count"] == 0
        assert stats["categories"] == {}

    def test_get_stats_with_valid_registry(self, fetcher, tmp_path: Path):
        """有效的注册表文件应返回统计"""
        fetcher._registry_path = tmp_path / ".skills-registry-enhanced.json"
        data = {
            "total": 10,
            "last_updated": "2025-01-01T00:00:00Z",
            "skills": [
                {"id": "a", "name": "A", "category": "security", "stars": 10},
                {"id": "b", "name": "B", "category": "web", "stars": 20},
                {"id": "c", "name": "C", "category": "security", "stars": 30},
            ],
        }
        fetcher._registry_path.write_text(json.dumps(data), encoding="utf-8")

        stats = fetcher.get_stats()
        assert stats["skills_count"] == 10
        assert stats["categories"] == {"security": 2, "web": 1}

    def test_get_stats_corrupt_registry(self, fetcher, tmp_path: Path):
        """损坏的注册表应返回默认值"""
        fetcher._registry_path = tmp_path / ".skills-registry-enhanced.json"
        fetcher._registry_path.write_text("bad json", encoding="utf-8")
        stats = fetcher.get_stats()
        assert stats["skills_count"] == 0

    def test_load_cache_empty(self, fetcher):
        """无注册表文件时 load_cache 返回空字典"""
        cache = fetcher.load_cache()
        assert cache == {}

    def test_load_cache_with_valid_data(self, fetcher, tmp_path: Path):
        """有效的注册表应正确加载为 EnhancedSkill"""
        fetcher._registry_path = tmp_path / ".skills-registry-enhanced.json"
        data = {
            "skills": [
                {"id": "test-skill", "name": "Test Skill", "stars": 42, "category": "web"}
            ]
        }
        fetcher._registry_path.write_text(json.dumps(data), encoding="utf-8")

        cache = fetcher.load_cache()
        assert "test-skill" in cache
        assert isinstance(cache["test-skill"].stars, int)

    def test_sync_status_default(self, fetcher):
        """默认同步状态应反映初始值"""
        status = fetcher.sync_status()
        assert status["last_sync_time"] is None
        assert status["sync_interval_hours"] == 24.0
        assert status["auto_sync_active"] is False
        assert status["cached_count"] == 0

    def test_stop_auto_sync_when_not_running(self, fetcher):
        """停止未运行的自动同步应不报错"""
        fetcher.stop_auto_sync()

    def test_save_registry(self, fetcher, tmp_path: Path):
        """保存注册表应写入文件"""
        from pycoder.server.skills_updater_v2 import EnhancedSkill

        fetcher._registry_path = tmp_path / ".skills-registry-enhanced.json"
        skills = {
            "test": EnhancedSkill(
                id="test", name="Test", stars=50, category="web", verified=True
            )
        }
        fetcher._save_registry(skills)

        assert fetcher._registry_path.exists()
        saved = json.loads(fetcher._registry_path.read_text(encoding="utf-8"))
        assert saved["total"] == 1
        assert saved["skills"][0]["id"] == "test"

    def test_parse_markdown_content(self, fetcher):
        """解析 Markdown 内容应提取链接"""
        content = (
            "- [Test Skill](https://github.com/test/skill) - A test skill description\n"
            "- [Another Skill](https://github.com/another/skill) - Another description\n"
        )
        result = fetcher._parse_markdown_content(content, "https://source", "test_source")
        assert len(result) == 2
        assert result[0].name == "Test Skill"
        assert result[0].repository_url == "https://github.com/test/skill"
        assert result[0].source == "test_source"

    def test_parse_markdown_content_dedup(self, fetcher):
        """重复的链接应被去重"""
        content = (
            "- [Test Skill](https://github.com/test/skill) - Desc\n"
            "- [Test Skill](https://github.com/test/skill) - Desc again\n"
        )
        result = fetcher._parse_markdown_content(content, "https://source", "test_source")
        assert len(result) == 1


class TestGetEnhancedFetcher:
    """EnhancedSkillsFetcher 单例测试"""

    def test_get_enhanced_fetcher_returns_singleton(self):
        """应返回单例"""
        from pycoder.server.skills_updater_v2 import get_enhanced_fetcher
        import pycoder.server.skills_updater_v2 as sv2

        sv2._enhanced_fetcher = None
        f1 = get_enhanced_fetcher()
        f2 = get_enhanced_fetcher()
        assert f1 is f2
        sv2._enhanced_fetcher = None


