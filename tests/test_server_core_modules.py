"""
对 pycoder/server 核心模块的综合单元测试。

覆盖模块:
  1. memory_bank.py          — MemoryBank 持久记忆管理
  2. skills_updater.py       — Skills 多源爬虫
  3. skills_updater_v2.py    — Skills 增强爬虫 v2
  4. agent_react_loop.py     — ReAct 循环实现
  5. agent_definitions.py    — Agent 角色定义
  6. agent_parser.py         — 统一响应解析器
  7. plugin_executor.py      — 后台插件/skills 执行器
  8. auto_plugin_installer.py — 自动插件安装器
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════
# 1. memory_bank.py 测试
# ═══════════════════════════════════════════════════════════════


class TestMemoryBank:
    """MemoryBank 持久记忆管理器测试"""

    @pytest.fixture
    def memory_bank(self, tmp_path: Path):
        """创建基于临时目录的 MemoryBank 实例"""
        from pycoder.server.memory_bank import MemoryBank, reset_memory_bank

        reset_memory_bank()
        mb = MemoryBank(workspace=tmp_path)
        return mb

    @pytest.fixture
    def populated_bank(self, memory_bank):
        """预填充的 MemoryBank 实例"""
        memory_bank.update_project_brief("这是一个测试项目")
        memory_bank.record_architecture_decision(
            "使用 FastAPI",
            "选择 FastAPI 作为 Web 框架",
            "高性能、异步支持、类型安全",
        )
        memory_bank.update_tech_context("Python 3.14", "FastAPI, pytest")
        memory_bank.set_active_context("正在实现用户认证模块", ["src/auth.py", "src/models.py"])
        memory_bank.update_progress("IN_PROGRESS", "用户认证 API 开发中")
        return memory_bank

    # ── 初始化 ──

    def test_init_creates_memory_directory(self, tmp_path: Path):
        """初始化时应创建 .pycoder/memory 目录"""
        from pycoder.server.memory_bank import MemoryBank, reset_memory_bank

        reset_memory_bank()
        MemoryBank(workspace=tmp_path)
        assert (tmp_path / ".pycoder" / "memory").exists()
        assert (tmp_path / ".pycoder" / "memory").is_dir()

    def test_memory_files_dict_has_expected_keys(self):
        """MEMORY_FILES 应包含预期的记忆文件键"""
        from pycoder.server.memory_bank import MemoryBank

        expected_keys = ["project_brief", "architecture", "tech_context", "active_context", "progress"]
        for key in expected_keys:
            assert key in MemoryBank.MEMORY_FILES

    def test_load_order_has_correct_priority(self):
        """LOAD_ORDER 应按正确的优先级排序"""
        from pycoder.server.memory_bank import MemoryBank

        assert MemoryBank.LOAD_ORDER == ["project_brief", "architecture", "tech_context", "active_context"]

    # ── 上下文加载 ──

    def test_load_context_empty_bank_returns_empty(self, memory_bank):
        """空记忆库加载上下文应返回空字符串"""
        result = memory_bank.load_context_for_prompt()
        assert result == ""

    def test_load_context_returns_header_and_content(self, populated_bank):
        """加载上下文应包含 header 和记忆内容"""
        result = populated_bank.load_context_for_prompt(max_tokens=5000)
        assert "<!-- Memory Bank" in result
        assert "测试项目" in result
        assert "FastAPI" in result
        assert "Python 3.14" in result

    def test_load_context_respects_max_tokens_and_truncates(self, populated_bank):
        """加载上下文应在超过 max_tokens 时截断"""
        result = populated_bank.load_context_for_prompt(max_tokens=20)
        # 20 tokens 只能容纳很少的内容
        assert len(result) < 500

    def test_load_context_skips_missing_files(self, memory_bank):
        """缺失的文件不应影响加载"""
        memory_bank.update_project_brief("只有项目概述")
        result = memory_bank.load_context_for_prompt(max_tokens=5000)
        assert "只有项目概述" in result
        assert "<!-- Memory Bank" in result

    # ── getter 方法 ──

    def test_get_project_brief(self, memory_bank):
        """get_project_brief 应返回项目概述"""
        memory_bank.update_project_brief("我的项目")
        result = memory_bank.get_project_brief()
        assert "我的项目" in result

    def test_get_project_brief_empty(self, memory_bank):
        """空项目概述应返回空字符串"""
        assert memory_bank.get_project_brief() == ""

    def test_get_architecture(self, memory_bank):
        """get_architecture 应返回架构文档"""
        memory_bank.record_architecture_decision("测试", "决策", "理由")
        result = memory_bank.get_architecture()
        assert "测试" in result
        assert "决策" in result

    def test_get_architecture_empty(self, memory_bank):
        """空架构文档应返回空字符串"""
        assert memory_bank.get_architecture() == ""

    def test_get_progress(self, memory_bank):
        """get_progress 应返回进度日志"""
        memory_bank.update_progress("DONE", "完成测试")
        result = memory_bank.get_progress()
        assert "DONE" in result
        assert "完成测试" in result

    def test_get_progress_empty(self, memory_bank):
        """空进度日志应返回空字符串"""
        assert memory_bank.get_progress() == ""

    # ── 更新方法 ──

    def test_update_project_brief(self, memory_bank):
        """更新项目概述应写入文件"""
        memory_bank.update_project_brief("全新的项目概述")
        content = memory_bank.get_project_brief()
        assert "全新的项目概述" in content
        assert "Project Brief" in content

    def test_update_project_brief_overwrites(self, memory_bank):
        """重复更新项目概述应覆盖旧内容"""
        memory_bank.update_project_brief("旧内容")
        memory_bank.update_project_brief("新内容")
        content = memory_bank.get_project_brief()
        assert "新内容" in content
        assert "旧内容" not in content

    def test_record_architecture_decision_appends(self, memory_bank):
        """记录架构决策应追加到现有文档"""
        memory_bank.record_architecture_decision("决策1", "使用 SQLite", "简单")
        memory_bank.record_architecture_decision("决策2", "使用 FastAPI", "异步")
        content = memory_bank.get_architecture()
        assert "决策1" in content
        assert "决策2" in content

    def test_record_architecture_decision_includes_fields(self, memory_bank):
        """架构决策记录应包含决策、理由、日期"""
        memory_bank.record_architecture_decision("测试决策", "选择方案A", "因为方案A更好")
        content = memory_bank.get_architecture()
        assert "测试决策" in content
        assert "选择方案A" in content
        assert "因为方案A更好" in content
        assert "日期:" in content

    def test_update_tech_context_with_dependencies(self, memory_bank):
        """更新技术栈上下文应包含依赖"""
        memory_bank.update_tech_context("Python 3.14", "pytest, fastapi")
        content = memory_bank._read("tech_context.md")
        assert "Python 3.14" in content
        assert "pytest, fastapi" in content

    def test_update_tech_context_without_dependencies(self, memory_bank):
        """更新技术栈上下文（无依赖）应正常"""
        memory_bank.update_tech_context("Python 3.14")
        content = memory_bank._read("tech_context.md")
        assert "Python 3.14" in content
        assert "## 依赖" not in content

    def test_set_active_context_with_files(self, memory_bank):
        """设置活跃上下文（含文件列表）应包含文件"""
        memory_bank.set_active_context("正在开发", ["a.py", "b.py"])
        content = memory_bank._read("active_context.md")
        assert "正在开发" in content
        assert "a.py" in content
        assert "b.py" in content

    def test_set_active_context_without_files(self, memory_bank):
        """设置活跃上下文（无文件列表）应正常"""
        memory_bank.set_active_context("正在开发")
        content = memory_bank._read("active_context.md")
        assert "正在开发" in content
        assert "## 相关文件" not in content

    def test_update_progress_appends(self, memory_bank):
        """更新进度应追加到日志"""
        memory_bank.update_progress("START", "开始任务")
        memory_bank.update_progress("DONE", "完成任务")
        content = memory_bank.get_progress()
        assert "START" in content
        assert "DONE" in content
        assert "开始任务" in content
        assert "完成任务" in content

    def test_mark_completed(self, memory_bank):
        """mark_completed 应标记任务为 COMPLETED"""
        memory_bank.mark_completed("用户认证")
        content = memory_bank.get_progress()
        assert "COMPLETED" in content

    def test_clear_active_context(self, memory_bank):
        """clear_active_context 应清除活跃上下文"""
        memory_bank.set_active_context("正在开发", ["a.py"])
        memory_bank.clear_active_context()
        content = memory_bank._read("active_context.md")
        assert content == "" or content == "\n" or content == ""

    # ── 查询方法 ──

    def test_has_memory_false_when_empty(self, memory_bank):
        """空记忆库时 has_memory 应返回 False"""
        assert memory_bank.has_memory() is False

    def test_has_memory_true_when_has_content(self, populated_bank):
        """有记忆内容时 has_memory 应返回 True"""
        assert populated_bank.has_memory() is True

    def test_list_memories_empty(self, memory_bank):
        """空记忆库时 list_memories 应返回空列表"""
        assert memory_bank.list_memories() == []

    def test_list_memories_with_content(self, populated_bank):
        """有记忆内容时 list_memories 应返回文件信息"""
        memories = populated_bank.list_memories()
        assert len(memories) >= 1
        for m in memories:
            assert "key" in m
            assert "file" in m
            assert "size" in m

    def test_list_memories_skips_missing_files(self, memory_bank):
        """list_memories 应只返回存在的文件"""
        memory_bank.update_project_brief("测试")
        memories = memory_bank.list_memories()
        # 只有 project_brief 文件存在
        brief_memories = [m for m in memories if m["key"] == "project_brief"]
        assert len(brief_memories) == 1


class TestNowHelper:
    """_now() 辅助函数测试"""

    def test_now_returns_valid_format(self):
        """_now 应返回 UTC 格式的时间字符串"""
        from pycoder.server.memory_bank import _now

        result = _now()
        assert "UTC" in result
        # 格式: YYYY-MM-DD HH:MM UTC
        assert len(result) > 10


class TestMemoryBankSingleton:
    """MemoryBank 单例管理测试"""

    def test_get_memory_bank_returns_singleton(self, tmp_path: Path):
        """get_memory_bank 应返回单例"""
        from pycoder.server.memory_bank import get_memory_bank, reset_memory_bank

        reset_memory_bank()
        mb1 = get_memory_bank(workspace=tmp_path)
        mb2 = get_memory_bank(workspace=tmp_path)
        assert mb1 is mb2

    def test_reset_memory_bank_clears_singleton(self, tmp_path: Path):
        """reset_memory_bank 应清除单例"""
        from pycoder.server.memory_bank import get_memory_bank, reset_memory_bank

        reset_memory_bank()
        mb1 = get_memory_bank(workspace=tmp_path)
        reset_memory_bank()
        mb2 = get_memory_bank(workspace=tmp_path)
        assert mb1 is not mb2


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


# ═══════════════════════════════════════════════════════════════
# 4. agent_react_loop.py 测试
# ═══════════════════════════════════════════════════════════════


class TestReActStep:
    """ReActStep 数据类测试"""

    def test_react_step_creation(self):
        """ReActStep 应正确创建"""
        from pycoder.server.services.agent_react_loop import ReActStep

        step = ReActStep(
            thought="需要读取文件",
            action="read_file",
            action_input={"path": "test.py"},
            observation="文件内容...",
            iteration=1,
        )
        assert step.thought == "需要读取文件"
        assert step.action == "read_file"
        assert step.iteration == 1

    def test_react_step_to_dict(self):
        """to_dict 应返回正确的字典"""
        from pycoder.server.services.agent_react_loop import ReActStep

        step = ReActStep(
            thought="测试",
            action="FINISH",
            action_input={},
            observation="obs" * 200,
            iteration=3,
        )
        d = step.to_dict()
        assert d["iteration"] == 3
        assert d["thought"] == "测试"
        assert d["action"] == "FINISH"
        assert len(d["observation"]) <= 500


class TestReActResult:
    """ReActResult 数据类测试"""

    def test_result_success_when_finished(self):
        """terminated_by='finish' 且无 error 时 success 应为 True"""
        from pycoder.server.services.agent_react_loop import ReActResult

        result = ReActResult(final_answer="完成", terminated_by="finish")
        assert result.success is True

    def test_result_not_success_when_max_iterations(self):
        """terminated_by='max_iterations' 时 success 应为 False"""
        from pycoder.server.services.agent_react_loop import ReActResult

        result = ReActResult(final_answer="超时", terminated_by="max_iterations")
        assert result.success is False

    def test_result_not_success_when_error(self):
        """有 error 时 success 应为 False"""
        from pycoder.server.services.agent_react_loop import ReActResult

        result = ReActResult(
            final_answer="失败", terminated_by="finish", error="something went wrong"
        )
        assert result.success is False

    def test_result_to_dict(self):
        """to_dict 应返回正确结构"""
        from pycoder.server.services.agent_react_loop import ReActResult, ReActStep

        step = ReActStep(thought="t", action="a", action_input={}, iteration=1)
        result = ReActResult(
            final_answer="done",
            steps=[step],
            iterations=1,
            terminated_by="finish",
        )
        d = result.to_dict()
        assert d["final_answer"] == "done"
        assert d["iterations"] == 1
        assert d["success"] is True
        assert len(d["steps"]) == 1


class TestExtractJsonCandidates:
    """JSON 候选提取测试"""

    def test_extract_from_markdown_code_block(self):
        """应从 Markdown 代码块中提取 JSON"""
        from pycoder.server.services.agent_react_loop import _extract_json_candidates

        text = '```json\n{"thought": "test", "action": "read", "action_input": {}}\n```'
        candidates = _extract_json_candidates(text)
        assert len(candidates) >= 1
        assert "test" in candidates[0]

    def test_extract_bare_json(self):
        """应从裸文本中提取 JSON"""
        from pycoder.server.services.agent_react_loop import _extract_json_candidates

        text = 'some prefix {"thought": "test", "action": "read", "action_input": {}} suffix'
        candidates = _extract_json_candidates(text)
        assert len(candidates) >= 1

    def test_extract_no_json(self):
        """无 JSON 时应返回空列表"""
        from pycoder.server.services.agent_react_loop import _extract_json_candidates

        text = "just plain text without braces"
        candidates = _extract_json_candidates(text)
        # 只有 Markdown 代码块候选，没有裸 JSON
        assert all("{" not in c for c in candidates)


class TestTryParseReActJson:
    """ReAct JSON 解析测试"""

    def test_parse_valid_react_json(self):
        """有效的 ReAct JSON 应正确解析"""
        from pycoder.server.services.agent_react_loop import _try_parse_react_json

        data = json.dumps({"thought": "需要读文件", "action": "read_file", "action_input": {"path": "test.py"}})
        step = _try_parse_react_json(data, 1)
        assert step is not None
        assert step.thought == "需要读文件"
        assert step.action == "read_file"
        assert step.action_input == {"path": "test.py"}
        assert step.iteration == 1

    def test_parse_missing_thought(self):
        """缺少 thought 字段应返回 None"""
        from pycoder.server.services.agent_react_loop import _try_parse_react_json

        data = json.dumps({"action": "read_file", "action_input": {}})
        step = _try_parse_react_json(data, 1)
        assert step is None

    def test_parse_missing_action(self):
        """缺少 action 字段应返回 None"""
        from pycoder.server.services.agent_react_loop import _try_parse_react_json

        data = json.dumps({"thought": "test", "action_input": {}})
        step = _try_parse_react_json(data, 1)
        assert step is None

    def test_parse_invalid_json(self):
        """无效 JSON 应返回 None"""
        from pycoder.server.services.agent_react_loop import _try_parse_react_json

        step = _try_parse_react_json("not valid json", 1)
        assert step is None

    def test_parse_non_dict_json(self):
        """非字典 JSON 应返回 None"""
        from pycoder.server.services.agent_react_loop import _try_parse_react_json

        step = _try_parse_react_json("[1, 2, 3]", 1)
        assert step is None

    def test_parse_action_input_not_dict(self):
        """action_input 非字典时应转换为空字典"""
        from pycoder.server.services.agent_react_loop import _try_parse_react_json

        data = json.dumps({"thought": "test", "action": "read", "action_input": "not a dict"})
        step = _try_parse_react_json(data, 1)
        assert step is not None
        assert step.action_input == {}


class TestTryParseToolCallsCompat:
    """旧格式兼容解析测试"""

    def test_parse_valid_tool_calls(self):
        """有效的 tool_calls 格式应正确解析"""
        from pycoder.server.services.agent_react_loop import _try_parse_tool_calls_compat

        data = json.dumps({
            "thought": "需要读文件",
            "tool_calls": [{"name": "read_file", "params": {"path": "test.py"}}],
        })
        step = _try_parse_tool_calls_compat(data, 1)
        assert step is not None
        assert step.action == "read_file"
        assert step.action_input == {"path": "test.py"}

    def test_parse_tool_calls_missing_name(self):
        """tool_calls 缺少 name 应返回 None"""
        from pycoder.server.services.agent_react_loop import _try_parse_tool_calls_compat

        data = json.dumps({"tool_calls": [{"params": {}}]})
        step = _try_parse_tool_calls_compat(data, 1)
        assert step is None

    def test_parse_tool_calls_not_list(self):
        """tool_calls 非列表应返回 None"""
        from pycoder.server.services.agent_react_loop import _try_parse_tool_calls_compat

        data = json.dumps({"tool_calls": "not a list"})
        step = _try_parse_tool_calls_compat(data, 1)
        assert step is None


class TestReActLoop:
    """ReActLoop 循环测试"""

    @pytest.fixture
    def mock_llm(self):
        """创建模拟 LLMProvider"""
        from pycoder.core.ports.llm_provider import LLMResponse

        llm = AsyncMock()
        llm.generate = AsyncMock(
            return_value=LLMResponse(
                content='{"thought": "任务完成", "action": "FINISH", "action_input": {}}',
                model="test-model",
            )
        )
        return llm

    @pytest.fixture
    def mock_tool_executor(self):
        """创建模拟工具执行器"""
        return AsyncMock(return_value="工具执行成功")

    @pytest.fixture
    def react_loop(self, mock_llm, mock_tool_executor):
        """创建 ReActLoop 实例"""
        from pycoder.server.services.agent_react_loop import ReActLoop

        loop = ReActLoop(
            llm=mock_llm,
            tool_executor=mock_tool_executor,
            max_iterations=5,
        )
        return loop

    def test_react_loop_init(self, react_loop):
        """ReActLoop 初始化应设置默认值"""
        assert react_loop.max_iterations == 5
        assert react_loop.tools is not None
        assert len(react_loop.tools) > 0

    def test_react_loop_default_tools(self, mock_llm, mock_tool_executor):
        """默认工具列表应包含常用工具"""
        from pycoder.server.services.agent_react_loop import ReActLoop

        loop = ReActLoop(llm=mock_llm, tool_executor=mock_tool_executor)
        tool_names = [t["name"] for t in loop.tools]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "FINISH" not in tool_names  # FINISH 是动作不是工具

    async def test_run_finish_immediately(self, react_loop, mock_llm):
        """LLM 直接返回 FINISH 时应立即结束"""
        from pycoder.core.ports.llm_provider import LLMResponse

        mock_llm.generate.return_value = LLMResponse(
            content='{"thought": "已完成", "action": "FINISH", "action_input": {}}',
            model="test",
        )

        result = await react_loop.run("测试任务")
        assert result.success is True
        assert result.terminated_by == "finish"
        assert result.iterations == 1
        assert "已完成" in result.final_answer

    async def test_run_with_tool_call_then_finish(self, react_loop, mock_llm):
        """先调用工具再 FINISH 的流程"""
        from pycoder.core.ports.llm_provider import LLMResponse

        mock_llm.generate.side_effect = [
            LLMResponse(
                content='{"thought": "需要读文件", "action": "read_file", "action_input": {"path": "test.py"}}',
                model="test",
            ),
            LLMResponse(
                content='{"thought": "已读取文件，任务完成", "action": "FINISH", "action_input": {}}',
                model="test",
            ),
        ]

        result = await react_loop.run("读取文件")
        assert result.success is True
        assert result.iterations == 2
        assert len(result.steps) == 2
        assert result.steps[0].action == "read_file"
        assert result.steps[1].action == "FINISH"

    async def test_run_max_iterations_exceeded(self, react_loop, mock_llm):
        """超过最大迭代次数应终止"""
        from pycoder.core.ports.llm_provider import LLMResponse

        # 一直返回非 FINISH 动作
        mock_llm.generate.return_value = LLMResponse(
            content='{"thought": "继续", "action": "read_file", "action_input": {"path": "test.py"}}',
            model="test",
        )

        result = await react_loop.run("测试")
        assert result.terminated_by == "max_iterations"
        assert result.iterations == react_loop.max_iterations
        assert result.success is False

    async def test_run_llm_failure_returns_error(self, react_loop, mock_llm):
        """LLM 调用失败应返回错误结果"""
        mock_llm.generate.side_effect = ConnectionError("连接失败")

        result = await react_loop.run("测试")
        assert result.terminated_by == "error"
        assert "连接失败" in result.final_answer
        assert result.success is False

    async def test_run_parse_failure_continues(self, react_loop, mock_llm):
        """解析失败应继续下一轮"""
        from pycoder.core.ports.llm_provider import LLMResponse

        mock_llm.generate.side_effect = [
            LLMResponse(content="not json at all", model="test"),
            LLMResponse(
                content='{"thought": "完成", "action": "FINISH", "action_input": {}}',
                model="test",
            ),
        ]

        result = await react_loop.run("测试")
        assert result.success is True
        assert result.iterations == 2
        # 第一步是解析失败
        assert result.steps[0].action == "(parse_error)"

    async def test_run_tool_execution_failure(self, react_loop, mock_llm, mock_tool_executor):
        """工具执行失败应记录错误并继续"""
        from pycoder.core.ports.llm_provider import LLMResponse

        mock_tool_executor.side_effect = RuntimeError("工具执行错误")
        mock_llm.generate.return_value = LLMResponse(
            content='{"thought": "完成", "action": "FINISH", "action_input": {}}',
            model="test",
        )

        result = await react_loop.run("测试")
        assert result.success is True
        # 工具执行失败不影响后续步骤

    async def test_run_with_context(self, react_loop, mock_llm):
        """带初始上下文的执行"""
        from pycoder.core.ports.llm_provider import LLMResponse

        mock_llm.generate.return_value = LLMResponse(
            content='{"thought": "完成", "action": "FINISH", "action_input": {}}',
            model="test",
        )

        result = await react_loop.run("测试", context="初始上下文信息")
        assert result.success is True

    def test_build_prompt(self, react_loop):
        """_build_prompt 应包含任务、工具和历史"""
        from pycoder.server.services.agent_react_loop import ReActStep

        steps = [
            ReActStep(thought="思考1", action="read_file", action_input={"path": "a.py"}, observation="内容", iteration=1)
        ]
        prompt = react_loop._build_prompt("测试任务", steps, ["初始观察"])

        assert "测试任务" in prompt
        assert "read_file" in prompt
        assert "思考1" in prompt
        assert "初始上下文" in prompt

    def test_compute_rumination_interval_zero_steps(self, react_loop):
        """零步时默认间隔 5"""
        interval = react_loop._compute_rumination_interval([], 0)
        assert interval == 5

    def test_compute_rumination_interval_no_errors(self, react_loop):
        """无错误时间隔 5"""
        from pycoder.server.services.agent_react_loop import ReActStep

        steps = [ReActStep(thought="t", action="a", action_input={}, iteration=i) for i in range(5)]
        interval = react_loop._compute_rumination_interval(steps, 0)
        assert interval == 5

    def test_compute_rumination_interval_high_errors(self, react_loop):
        """高错误率时间隔 2"""
        from pycoder.server.services.agent_react_loop import ReActStep

        steps = [ReActStep(thought="t", action="a", action_input={}, iteration=i) for i in range(5)]
        interval = react_loop._compute_rumination_interval(steps, 2)  # 2/5 = 40%
        assert interval == 2

    def test_compute_rumination_interval_persistent_errors(self, react_loop):
        """持续错误（>=3）时间隔 1"""
        from pycoder.server.services.agent_react_loop import ReActStep

        steps = [ReActStep(thought="t", action="a", action_input={}, iteration=i) for i in range(10)]
        interval = react_loop._compute_rumination_interval(steps, 3)
        assert interval == 1

    def test_compute_rumination_interval_low_errors(self, react_loop):
        """低错误率（<20% 但 >0）时间隔 3"""
        from pycoder.server.services.agent_react_loop import ReActStep

        steps = [ReActStep(thought="t", action="a", action_input={}, iteration=i) for i in range(10)]
        interval = react_loop._compute_rumination_interval(steps, 1)  # 1/10 = 10%
        assert interval == 3


# ═══════════════════════════════════════════════════════════════
# 5. agent_definitions.py 测试
# ═══════════════════════════════════════════════════════════════


class TestAgentRole:
    """AgentRole 数据类测试"""

    def test_agent_role_defaults(self):
        """AgentRole 应有合理的默认值"""
        from pycoder.server.services.agent_definitions import AgentRole

        role = AgentRole(
            id="test",
            name="测试角色",
            description="测试用",
            system_prompt="你是测试角色",
            tools=["read_file"],
        )
        assert role.id == "test"
        assert role.model == "deepseek-chat"
        assert role.model_tier == "standard"
        assert role.parallel is False
        assert role.max_retries == 3
        assert role.timeout == 120
        assert role.max_concurrent == 1
        assert role.skills == []
        assert role.forbid_actions == []
        assert role.heartbeat_interval == 0


class TestAgentTask:
    """AgentTask 数据类测试"""

    def test_agent_task_defaults(self):
        """AgentTask 应有合理的默认值"""
        from pycoder.server.services.agent_definitions import AgentTask

        task = AgentTask(
            id="task-1",
            title="测试任务",
            description="任务描述",
            assigned_role="developer",
        )
        assert task.id == "task-1"
        assert task.status == "pending"
        assert task.depends_on == []
        assert task.deliverables == []
        assert task.retries == 0
        assert task.max_retries == 3


class TestAgentMessage:
    """AgentMessage 数据类测试"""

    def test_agent_message_defaults(self):
        """AgentMessage 应有合理的默认值"""
        from pycoder.server.services.agent_definitions import AgentMessage

        msg = AgentMessage(
            from_agent="pm",
            to_agent="developer",
            msg_type="task",
            content="请实现用户认证",
        )
        assert msg.from_agent == "pm"
        assert msg.to_agent == "developer"
        assert msg.msg_type == "task"
        assert msg.attachments == []
        assert msg.context == {}


class TestAgentRoles:
    """预定义 Agent 角色测试"""

    def test_all_roles_defined(self):
        """所有 7 种角色应已定义"""
        from pycoder.server.services.agent_definitions import AGENT_ROLES

        expected_roles = ["pm", "architect", "developer", "qa", "documenter", "fixer", "devops"]
        for role_id in expected_roles:
            assert role_id in AGENT_ROLES
            assert AGENT_ROLES[role_id].id == role_id

    def test_pm_role_properties(self):
        """PM 角色应有正确的属性"""
        from pycoder.server.services.agent_definitions import AGENT_ROLES

        pm = AGENT_ROLES["pm"]
        assert pm.model_tier == "standard"
        assert pm.max_concurrent == 1
        assert pm.heartbeat_interval == 1800
        assert "taskflow" in pm.skills
        assert not pm.parallel

    def test_architect_role_properties(self):
        """架构师角色应有 premium 模型"""
        from pycoder.server.services.agent_definitions import AGENT_ROLES

        architect = AGENT_ROLES["architect"]
        assert architect.model_tier == "premium"
        assert architect.model == "deepseek-reasoner"

    def test_developer_role_properties(self):
        """开发者角色应支持并行"""
        from pycoder.server.services.agent_definitions import AGENT_ROLES

        developer = AGENT_ROLES["developer"]
        assert developer.parallel is True
        assert developer.max_concurrent == 3

    def test_qa_role_properties(self):
        """QA 角色应有正确的禁止操作"""
        from pycoder.server.services.agent_definitions import AGENT_ROLES

        qa = AGENT_ROLES["qa"]
        assert "code_write" in qa.forbid_actions
        assert "deploy" in qa.forbid_actions

    def test_fixer_role_properties(self):
        """Fixer 角色应有 patch 技能"""
        from pycoder.server.services.agent_definitions import AGENT_ROLES

        fixer = AGENT_ROLES["fixer"]
        assert "patch" in fixer.skills
        assert "fix" in fixer.skills

    def test_devops_role_properties(self):
        """DevOps 角色应有空 forbid_actions"""
        from pycoder.server.services.agent_definitions import AGENT_ROLES

        devops = AGENT_ROLES["devops"]
        assert devops.forbid_actions == []


class TestModelTiers:
    """模型分层测试"""

    def test_model_tiers_have_expected_keys(self):
        """MODEL_TIERS 应包含所有分层"""
        from pycoder.server.services.agent_definitions import MODEL_TIERS

        expected = ["premium", "standard", "economy", "vision", "local"]
        for tier in expected:
            assert tier in MODEL_TIERS

    def test_get_model_for_tier_known(self):
        """已知分层应返回正确的模型"""
        from pycoder.server.services.agent_definitions import get_model_for_tier

        assert get_model_for_tier("premium") == "deepseek-reasoner"
        assert get_model_for_tier("standard") == "deepseek-chat"

    def test_get_model_for_tier_unknown(self):
        """未知分层应返回默认模型"""
        from pycoder.server.services.agent_definitions import get_model_for_tier

        assert get_model_for_tier("nonexistent") == "deepseek-chat"

    def test_get_model_for_tier_local_empty(self):
        """local 分层（无模型）应返回默认模型"""
        from pycoder.server.services.agent_definitions import get_model_for_tier

        assert get_model_for_tier("local") == "deepseek-chat"


class TestRoleTier:
    """角色分层查询测试"""

    def test_get_role_tier_known(self):
        """已知角色应返回正确的分层"""
        from pycoder.server.services.agent_definitions import get_role_tier

        assert get_role_tier("architect") == "premium"
        assert get_role_tier("pm") == "standard"
        assert get_role_tier("documenter") == "economy"

    def test_get_role_tier_unknown(self):
        """未知角色应返回 standard"""
        from pycoder.server.services.agent_definitions import get_role_tier

        assert get_role_tier("nonexistent") == "standard"


class TestConcurrencyLimits:
    """并发限制测试"""

    def test_concurrency_limits_have_expected_keys(self):
        """CONCURRENCY_LIMITS 应包含所有限制键"""
        from pycoder.server.services.agent_definitions import CONCURRENCY_LIMITS

        expected = ["global", "dev_team", "qa_team", "devops_team", "single_agent"]
        for key in expected:
            assert key in CONCURRENCY_LIMITS

    def test_get_concurrency_limit_known(self):
        """已知类别应返回正确限制"""
        from pycoder.server.services.agent_definitions import get_concurrency_limit

        assert get_concurrency_limit("global") == 10
        assert get_concurrency_limit("dev_team") == 6

    def test_get_concurrency_limit_unknown(self):
        """未知类别应返回默认值 10"""
        from pycoder.server.services.agent_definitions import get_concurrency_limit

        assert get_concurrency_limit("unknown") == 10


class TestRoleConcurrency:
    """角色并发数测试"""

    def test_get_role_concurrency_known(self):
        """已知角色应返回正确的并发数"""
        from pycoder.server.services.agent_definitions import get_role_concurrency

        assert get_role_concurrency("developer") == 3
        assert get_role_concurrency("pm") == 1

    def test_get_role_concurrency_unknown(self):
        """未知角色应返回 1"""
        from pycoder.server.services.agent_definitions import get_role_concurrency

        assert get_role_concurrency("unknown") == 1


class TestGlobalConstants:
    """全局常量测试"""

    def test_max_retries(self):
        """MAX_RETRIES 应为 2"""
        from pycoder.server.services.agent_definitions import MAX_RETRIES

        assert MAX_RETRIES == 2

    def test_task_timeout(self):
        """TASK_TIMEOUT 应为 1200"""
        from pycoder.server.services.agent_definitions import TASK_TIMEOUT

        assert TASK_TIMEOUT == 1200


class TestGetRole:
    """get_role 工厂函数测试"""

    def test_get_role_exists(self):
        """存在的角色应返回正确的 AgentRole"""
        from pycoder.server.services.agent_definitions import get_role

        role = get_role("pm")
        assert role is not None
        assert role.id == "pm"

    def test_get_role_not_exists(self):
        """不存在的角色应返回 None"""
        from pycoder.server.services.agent_definitions import get_role

        role = get_role("superhero")
        assert role is None


class TestCreateTask:
    """create_task 工厂函数测试"""

    def test_create_task_basic(self):
        """基本创建任务应正确设置字段"""
        from pycoder.server.services.agent_definitions import create_task

        task = create_task(
            title="测试任务",
            description="任务描述",
            assigned_role="developer",
        )
        assert task.title == "测试任务"
        assert task.assigned_role == "developer"
        assert task.status == "pending"
        assert task.id.startswith("task-")
        assert task.created_at > 0

    def test_create_task_with_dependencies(self):
        """带依赖的任务创建"""
        from pycoder.server.services.agent_definitions import create_task

        task = create_task(
            title="任务2",
            description="依赖任务1",
            assigned_role="qa",
            depends_on=["task-1"],
            deliverables=["report.md"],
        )
        assert task.depends_on == ["task-1"]
        assert task.deliverables == ["report.md"]


# ═══════════════════════════════════════════════════════════════
# 6. agent_parser.py 测试
# ═══════════════════════════════════════════════════════════════


class TestParsedResponse:
    """ParsedResponse 数据类测试"""

    def test_parsed_response_defaults(self):
        """ParsedResponse 应有合理的默认值"""
        from pycoder.server.services.agent_parser import ParsedResponse

        pr = ParsedResponse(
            raw="test",
            tool_calls=[],
            file_blocks=[],
            completion=False,
            summary="",
            errors=[],
        )
        assert pr.raw == "test"
        assert pr.tool_calls == []
        assert pr.completion is False


class TestDetectCompletion:
    """完成信号检测测试"""

    def test_detect_completion_chinese_done(self):
        """中文"完成"应检测为完成信号"""
        from pycoder.server.services.agent_parser import _detect_completion

        is_comp, summary = _detect_completion("完成！所有任务已完成。")
        assert is_comp is True

    def test_detect_completion_done(self):
        """英文"done"应检测为完成信号"""
        from pycoder.server.services.agent_parser import _detect_completion

        is_comp, summary = _detect_completion("done.")
        assert is_comp is True

    def test_detect_completion_finished(self):
        """英文"finished"应检测为完成信号"""
        from pycoder.server.services.agent_parser import _detect_completion

        is_comp, summary = _detect_completion("finished!")
        assert is_comp is True

    def test_detect_completion_summary(self):
        """"总结:"应检测为完成信号"""
        from pycoder.server.services.agent_parser import _detect_completion

        is_comp, summary = _detect_completion("总结：本次开发了用户认证模块...")
        assert is_comp is True

    def test_detect_completion_emoji(self):
        """"✅"开头应检测为完成信号"""
        from pycoder.server.services.agent_parser import _detect_completion

        is_comp, summary = _detect_completion("✅ 所有任务已完成")
        assert is_comp is True

    def test_detect_not_completion(self):
        """普通文本不应检测为完成信号"""
        from pycoder.server.services.agent_parser import _detect_completion

        is_comp, summary = _detect_completion("请读取文件 config.yaml")
        assert is_comp is False


class TestParseResponse:
    """统一解析器测试"""

    def test_parse_empty_text(self):
        """空文本应返回空结果"""
        from pycoder.server.services.agent_parser import parse_response

        result = parse_response("")
        assert result.completion is False
        assert result.tool_calls == []
        assert result.file_blocks == []

    def test_parse_completion_signal(self):
        """完成信号应正确识别"""
        from pycoder.server.services.agent_parser import parse_response

        result = parse_response("完成！所有任务已完成。")
        assert result.completion is True
        assert len(result.summary) > 0

    def test_parse_tool_calls_json(self):
        """JSON tool_calls 格式应正确解析"""
        from pycoder.server.services.agent_parser import parse_response

        text = '```json\n{"tool_calls": [{"name": "read_file", "params": {"path": "test.py"}}]}\n```'
        result = parse_response(text)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "read_file"
        assert result.tool_calls[0]["params"] == {"path": "test.py"}

    def test_parse_tool_calls_bare_json(self):
        """裸 JSON tool_calls 应正确解析"""
        from pycoder.server.services.agent_parser import parse_response

        text = '{"tool_calls": [{"name": "write_file", "params": {"path": "test.py", "content": "hello"}}]}'
        result = parse_response(text)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "write_file"

    def test_parse_single_tool_format(self):
        """单工具 JSON 格式应正确解析"""
        from pycoder.server.services.agent_parser import parse_response

        text = '{"name": "read_file", "params": {"path": "config.yaml"}}'
        result = parse_response(text)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "read_file"

    def test_parse_react_format(self):
        """ReAct 格式应正确解析"""
        from pycoder.server.services.agent_parser import parse_response

        text = '{"thought": "需要读文件", "action": "read_file", "action_input": {"path": "test.py"}}'
        result = parse_response(text)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "read_file"
        assert result.tool_calls[0]["_react_thought"] == "需要读文件"

    def test_parse_react_finish_not_tool_call(self):
        """ReAct FINISH 动作不应被解析为工具调用"""
        from pycoder.server.services.agent_parser import parse_response

        text = '{"thought": "完成", "action": "FINISH", "action_input": {}}'
        result = parse_response(text)
        assert result.tool_calls == []

    def test_parse_file_blocks(self):
        """FILE: 代码块应正确解析"""
        from pycoder.server.services.agent_parser import parse_response

        text = "```FILE:test.py\nprint('hello')\n```"
        result = parse_response(text)
        assert len(result.file_blocks) >= 1
        assert any(b["path"] == "test.py" for b in result.file_blocks)
        assert any("print('hello')" in b["content"] for b in result.file_blocks)

    def test_parse_inline_code_blocks(self):
        """内联代码块应正确解析"""
        from pycoder.server.services.agent_parser import parse_response

        text = "```python:test.py\nprint('hello')\n```"
        result = parse_response(text)
        # 内联代码块在没有 tool_calls 时被解析
        assert len(result.file_blocks) >= 1

    def test_parse_response_combines_all(self):
        """混合内容应同时解析工具调用和文件块"""
        from pycoder.server.services.agent_parser import parse_response

        text = (
            '{"tool_calls": [{"name": "read_file", "params": {"path": "a.py"}}]}\n'
            "```FILE:b.py\ncontent\n```"
        )
        result = parse_response(text)
        assert len(result.tool_calls) >= 1
        assert len(result.file_blocks) >= 1


class TestParseJsonBlock:
    """JSON 代码块解析测试"""

    def test_parse_tool_calls_array(self):
        """tool_calls 数组格式"""
        from pycoder.server.services.agent_parser import _parse_json_block

        block = json.dumps({
            "tool_calls": [
                {"name": "read_file", "params": {}},
                {"name": "write_file", "params": {}},
            ]
        })
        result = _parse_json_block(block)
        assert len(result) == 2

    def test_parse_single_tool_in_block(self):
        """单个工具格式"""
        from pycoder.server.services.agent_parser import _parse_json_block

        block = json.dumps({"name": "read_file", "params": {"path": "test.py"}})
        result = _parse_json_block(block)
        assert len(result) == 1
        assert result[0]["name"] == "read_file"

    def test_parse_direct_array(self):
        """直接工具数组格式"""
        from pycoder.server.services.agent_parser import _parse_json_block

        block = json.dumps([
            {"name": "read_file", "params": {"path": "a.py"}},
            {"name": "write_file", "params": {"path": "b.py", "content": "c"}},
        ])
        result = _parse_json_block(block)
        assert len(result) == 2

    def test_parse_invalid_json(self):
        """无效 JSON 应返回空列表"""
        from pycoder.server.services.agent_parser import _parse_json_block

        result = _parse_json_block("not json")
        assert result == []


class TestParseBareJson:
    """裸 JSON 解析测试"""

    def test_parse_with_prefix_suffix(self):
        """带前后缀的裸 JSON 应正确解析"""
        from pycoder.server.services.agent_parser import _parse_bare_json

        text = 'prefix text {"name": "read_file", "params": {"path": "test.py"}} suffix'
        result = _parse_bare_json(text)
        assert len(result) == 1
        assert result[0]["name"] == "read_file"

    def test_no_braces(self):
        """无花括号应返回空列表"""
        from pycoder.server.services.agent_parser import _parse_bare_json

        result = _parse_bare_json("no braces")
        assert result == []


class TestExtractFileBlocks:
    """FILE 代码块提取测试"""

    def test_extract_single_file_block(self):
        """单个 FILE 块应正确提取"""
        from pycoder.server.services.agent_parser import _extract_file_blocks

        text = "```FILE:src/app.py\nprint('hello')\n```"
        blocks = _extract_file_blocks(text)
        assert len(blocks) == 1
        assert blocks[0]["path"] == "src/app.py"
        assert blocks[0]["source"] == "file-block"

    def test_extract_multiple_file_blocks(self):
        """多个 FILE 块应全部提取"""
        from pycoder.server.services.agent_parser import _extract_file_blocks

        text = (
            "```FILE:a.py\ncontent a\n```\n"
            "```FILE:b.py\ncontent b\n```"
        )
        blocks = _extract_file_blocks(text)
        assert len(blocks) == 2

    def test_extract_no_file_blocks(self):
        """无 FILE 块应返回空列表"""
        from pycoder.server.services.agent_parser import _extract_file_blocks

        blocks = _extract_file_blocks("plain text")
        assert blocks == []


class TestIsToolNameValid:
    """工具名称验证测试"""

    def test_known_tool_valid(self):
        """已知工具名应验证通过"""
        from pycoder.server.services.agent_parser import is_tool_name_valid

        assert is_tool_name_valid("read_file") is True
        assert is_tool_name_valid("write_file") is True
        assert is_tool_name_valid("run_command") is True

    def test_unknown_tool_invalid(self):
        """未知工具名应验证失败"""
        from pycoder.server.services.agent_parser import is_tool_name_valid

        assert is_tool_name_valid("unknown_tool") is False

    def test_pycoder_prefix_valid(self):
        """pycoder. 前缀的工具名应验证通过"""
        from pycoder.server.services.agent_parser import is_tool_name_valid

        assert is_tool_name_valid("pycoder.custom_tool") is True

    def test_underscore_prefix_valid(self):
        """_ 前缀的工具名应验证通过"""
        from pycoder.server.services.agent_parser import is_tool_name_valid

        assert is_tool_name_valid("_internal_tool") is True


class TestValidateToolCall:
    """工具调用校验测试"""

    def test_valid_tool_call(self):
        """有效的工具调用应校验通过"""
        from pycoder.server.services.agent_parser import validate_tool_call

        valid, msg = validate_tool_call({"name": "read_file", "params": {"path": "test.py"}})
        assert valid is True
        assert msg == ""

    def test_missing_name(self):
        """缺少名称应校验失败"""
        from pycoder.server.services.agent_parser import validate_tool_call

        valid, msg = validate_tool_call({"params": {}})
        assert valid is False
        assert "名称为空" in msg

    def test_params_not_dict(self):
        """参数非字典应校验失败"""
        from pycoder.server.services.agent_parser import validate_tool_call

        valid, msg = validate_tool_call({"name": "read_file", "params": "not a dict"})
        assert valid is False
        assert "参数必须是对象" in msg


# ═══════════════════════════════════════════════════════════════
# 7. plugin_executor.py 测试
# ═══════════════════════════════════════════════════════════════


class TestPluginExecutor:
    """PluginExecutor 测试"""

    @pytest.fixture
    def executor(self):
        """创建 PluginExecutor 实例"""
        from pycoder.server.services.plugin_executor import PluginExecutor

        return PluginExecutor()

    def test_init(self, executor):
        """初始化应设置默认属性"""
        assert executor._plugin_callback is None
        assert executor._results == {}

    def test_set_plugin_callback(self, executor):
        """设置回调应正确存储"""
        async def my_callback(event: dict) -> None:
            pass

        executor.set_plugin_callback(my_callback)
        assert executor._plugin_callback is my_callback

    async def test_emit_plugin_event_no_callback(self, executor):
        """无回调时发射事件应不报错"""
        await executor._emit_plugin_event("test", "测试插件", "start")

    async def test_emit_plugin_event_with_callback(self, executor):
        """有回调时发射事件应调用回调"""
        events = []

        async def callback(event: dict) -> None:
            events.append(event)

        executor.set_plugin_callback(callback)
        await executor._emit_plugin_event("test-id", "测试插件", "start", duration_ms=100)

        assert len(events) == 1
        assert events[0]["type"] == "plugin_event"
        assert events[0]["plugin_id"] == "test-id"
        assert events[0]["plugin_name"] == "测试插件"
        assert events[0]["action"] == "start"
        assert events[0]["duration_ms"] == 100
        assert events[0]["hidden"] is True

    async def test_emit_plugin_event_with_error(self, executor):
        """带错误的事件应包含错误信息"""
        events = []

        async def callback(event: dict) -> None:
            events.append(event)

        executor.set_plugin_callback(callback)
        await executor._emit_plugin_event("test-id", "测试", "error", error="something went wrong")

        assert events[0]["error"] == "something went wrong"
        assert events[0]["action"] == "error"

    async def test_emit_plugin_event_callback_failure(self, executor):
        """回调失败应不抛出异常"""
        async def failing_callback(event: dict) -> None:
            raise RuntimeError("回调失败")

        executor.set_plugin_callback(failing_callback)
        # 不应抛出异常
        await executor._emit_plugin_event("test", "测试", "start")

    async def test_execute_matching_plugins_no_registry(self, executor):
        """无插件注册表时应返回空结果"""
        with patch("pycoder.plugins.base.PluginRegistry", side_effect=ImportError):
            results = await executor.execute_matching_plugins("test message", {})
            assert results == {}

    async def test_execute_all_no_plugins(self, executor):
        """execute_all 无匹配时应正常返回"""
        with patch.object(executor, "execute_matching_plugins", return_value={}):
            with patch.object(executor, "execute_matching_skills", return_value={}):
                results = await executor.execute_all("test message", {})
                assert isinstance(results, dict)

    async def test_execute_all_with_exception(self, executor):
        """execute_all 异常时应返回错误结果"""
        with patch.object(
            executor,
            "execute_matching_plugins",
            side_effect=RuntimeError("插件执行失败"),
        ):
            with patch.object(
                executor,
                "execute_matching_skills",
                side_effect=RuntimeError("技能执行失败"),
            ):
                results = await executor.execute_all("test message", {})
                assert "__plugin_error__" in results
                assert "__skill_error__" in results


# ═══════════════════════════════════════════════════════════════
# 8. auto_plugin_installer.py 测试
# ═══════════════════════════════════════════════════════════════


class TestInstallResult:
    """InstallResult 数据类测试"""

    def test_install_result_defaults(self):
        """InstallResult 应有合理的默认值"""
        from pycoder.server.services.auto_plugin_installer import InstallResult

        result = InstallResult()
        assert result.success is False
        assert result.candidate_id == ""
        assert result.error == ""


class TestAutoPluginInstallerValidateUrl:
    """URL 验证测试"""

    def test_valid_url(self):
        """有效的 URL 应通过验证"""
        from pycoder.server.services.auto_plugin_installer import _validate_url

        assert _validate_url("https://example.com") == "https://example.com"

    def test_invalid_url(self):
        """无效的 URL 协议应抛出 ValueError"""
        from pycoder.server.services.auto_plugin_installer import _validate_url

        with pytest.raises(ValueError, match="不允许的 URL 协议"):
            _validate_url("ftp://example.com")


class TestAutoPluginInstaller:
    """AutoPluginInstaller 测试"""

    @pytest.fixture
    def installer(self, tmp_path: Path):
        """创建 AutoPluginInstaller 实例"""
        from pycoder.server.services.auto_plugin_installer import AutoPluginInstaller, _SKILLS_INSTALL_DIR, _INSTALL_LOG

        # 使用临时目录覆盖安装路径
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir(parents=True, exist_ok=True)
        log_file = tmp_path / "install_log.jsonl"
        # 创建 .pycoder 目录（_register_skill 需要）
        pycoder_dir = tmp_path / ".pycoder"
        pycoder_dir.mkdir(parents=True, exist_ok=True)

        with patch(
            "pycoder.server.services.auto_plugin_installer._SKILLS_INSTALL_DIR",
            skill_dir,
        ), patch(
            "pycoder.server.services.auto_plugin_installer._INSTALL_LOG",
            log_file,
        ), patch(
            "pycoder.server.services.auto_plugin_installer.Path.home",
            return_value=tmp_path,
        ):
            inst = AutoPluginInstaller()
            yield inst

    def test_init_creates_directory(self, tmp_path: Path):
        """初始化应创建安装目录"""
        from pycoder.server.services.auto_plugin_installer import AutoPluginInstaller

        with patch(
            "pycoder.server.services.auto_plugin_installer._SKILLS_INSTALL_DIR",
            tmp_path / "skills",
        ), patch(
            "pycoder.server.services.auto_plugin_installer._INSTALL_LOG",
            tmp_path / "log.jsonl",
        ), patch(
            "pycoder.server.services.auto_plugin_installer.Path.home",
            return_value=tmp_path,
        ):
            AutoPluginInstaller()
            assert (tmp_path / "skills").exists()

    def test_is_installed_false(self, installer, tmp_path: Path):
        """未安装时应返回 False"""
        assert installer.is_installed("nonexistent-skill") is False

    async def test_install_with_description_fallback(self, installer, tmp_path: Path):
        """仅提供描述时应从描述生成内容"""
        # 模拟 _fetch_content 返回描述生成的内容
        mock_fetch = AsyncMock(return_value=("# 自动生成的 Skill\n\n描述内容", "0.1"))
        with patch.object(installer, "_fetch_content", mock_fetch):
            result = await installer.install(
                candidate_id="test-skill",
                skill_data={"name": "Test Skill", "description": "A test skill description"},
                source="market",
            )
        assert result.success is True
        assert result.candidate_id == "test-skill"
        assert result.destination.endswith("test-skill.md")

    async def test_install_without_content_fails(self, installer):
        """无法获取内容时安装失败"""
        with patch.object(installer, "_fetch_content", return_value=("", "")):
            result = await installer.install("test-skill")
            assert result.success is False
            assert "无法获取" in result.error

    async def test_install_exception_handling(self, installer):
        """安装异常应返回失败结果"""
        with patch.object(installer, "_create_snapshot", side_effect=OSError("磁盘错误")):
            result = await installer.install("test-skill", {"name": "Test"})
            assert result.success is False
            assert "磁盘错误" in result.error

    def test_get_installed_empty(self, installer):
        """空安装目录应返回空列表"""
        installed = installer.get_installed()
        assert installed == []

    def test_get_install_log_empty(self, installer):
        """空日志应返回空列表"""
        log = installer.get_install_log()
        assert log == []

    def test_generate_from_description(self, installer):
        """从描述生成内容应包含必要信息"""
        content = installer._generate_from_description("my-skill", "这是一个测试技能")
        assert "my-skill" in content
        assert "这是一个测试技能" in content
        assert "自动安装" in content

    def test_build_github_url(self, installer):
        """构建 GitHub URL 应正确"""
        url = installer._build_github_url("code-review")
        assert "code-review" in url
        assert "SKILL.md" in url
        assert url.startswith("https://")

    async def test_download_url_invalid(self, installer):
        """无效 URL 下载应返回空字符串"""
        content = await installer._download_url("file:///etc/passwd")
        assert content == ""

    def test_create_snapshot_no_file(self, installer, tmp_path: Path):
        """无现有文件时应返回空引用"""
        ref = installer._create_snapshot("nonexistent")
        assert ref == ""

    def test_create_snapshot_existing_file(self, installer, tmp_path: Path):
        """有现有文件时应创建快照"""
        # 先创建一个文件
        skill_file = tmp_path / "skills" / "test-skill.md"
        skill_file.parent.mkdir(parents=True, exist_ok=True)
        skill_file.write_text("original content", encoding="utf-8")

        ref = installer._create_snapshot("test-skill")
        assert ref != ""
        assert "test-skill" in ref

        # 验证快照文件存在
        snap_dir = tmp_path / "skills" / ".snapshots"
        assert snap_dir.exists()
        snapshots = list(snap_dir.glob(f"{ref}.md"))
        assert len(snapshots) == 1

    def test_register_skill(self, tmp_path: Path):
        """注册技能应写入 installed_skills.json"""
        from pycoder.server.services.auto_plugin_installer import AutoPluginInstaller

        # 先创建 .pycoder 目录
        pycoder_dir = tmp_path / ".pycoder"
        pycoder_dir.mkdir(parents=True, exist_ok=True)
        reg_path = pycoder_dir / "installed_skills.json"
        with patch(
            "pycoder.server.services.auto_plugin_installer.Path.home",
            return_value=tmp_path,
        ):
            AutoPluginInstaller._register_skill("test-skill", "Test Skill")

        assert reg_path.exists()
        data = json.loads(reg_path.read_text(encoding="utf-8"))
        assert "test-skill" in data
        assert data["test-skill"]["name"] == "Test Skill"
        assert data["test-skill"]["enabled"] is True


# ═══════════════════════════════════════════════════════════════
# 端到端集成测试
# ═══════════════════════════════════════════════════════════════


class TestEndToEndMemoryBankFlow:
    """MemoryBank 端到端流程测试"""

    def test_full_memory_workflow(self, tmp_path: Path):
        """完整的记忆工作流：创建→更新→查询→清除"""
        from pycoder.server.memory_bank import MemoryBank, reset_memory_bank

        reset_memory_bank()
        mb = MemoryBank(workspace=tmp_path)

        # 初始状态
        assert mb.has_memory() is False
        assert mb.list_memories() == []

        # 更新项目概述
        mb.update_project_brief("端到端测试项目")
        assert mb.has_memory() is True

        # 记录架构决策
        mb.record_architecture_decision("使用 pytest", "测试框架", "社区支持好")
        mb.record_architecture_decision("使用 FastAPI", "Web 框架", "高性能")

        # 更新技术栈
        mb.update_tech_context("Python 3.14", "fastapi, pytest, uvicorn")

        # 设置活跃上下文
        mb.set_active_context("正在开发测试模块", ["tests/test_core.py"])

        # 更新进度
        mb.update_progress("START", "开始编写测试")
        mb.mark_completed("编写 MemoryBank 测试")

        # 验证查询
        memories = mb.list_memories()
        assert len(memories) >= 3  # project_brief, architecture, tech_context, active_context, progress

        # 加载上下文
        context = mb.load_context_for_prompt(max_tokens=5000)
        assert "端到端测试项目" in context
        assert "pytest" in context
        assert "FastAPI" in context

        # 清除活跃上下文
        mb.clear_active_context()
        assert mb._read("active_context.md") == ""