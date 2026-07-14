"""覆盖率测试: pycoder/server/skills_market.py

目标: 行覆盖率 >= 80%
覆盖内容:
  - SkillEntry: from_dict / to_dict / 默认值
  - SkillsMarketManager: 加载/同步/列表/安装/卸载/更新/评分/详情/发布
  - _compare_versions / _has_update / _is_installed 辅助方法
  - get_skills_market 单例

测试策略:
  - 用 tmp_path 隔离 .skills 目录与 .skills-registry.json
  - 用 monkeypatch 替换 LOCAL_REGISTRY_PATH 与 Path.home()
  - mock urllib.request 测试远程同步/下载
  - 不依赖网络
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pycoder.server import skills_market as sm_mod
from pycoder.server.skills_market import (
    LOCAL_REGISTRY_PATH,
    REMOTE_REGISTRY_URL,
    SkillEntry,
    SkillsMarketManager,
    get_skills_market,
)


# ── Fixture: 隔离的 manager + 临时工作区 ─────────────────

@pytest.fixture
def mgr(tmp_path, monkeypatch):
    """构造使用临时目录的 SkillsMarketManager"""
    # 重定向 cwd → 安装目录 / 注册表文件路径都基于 cwd
    monkeypatch.chdir(tmp_path)
    # 重定向 LOCAL_REGISTRY_PATH 到临时目录
    fake_local = tmp_path / "home" / ".pycoder" / "skills_registry.json"
    monkeypatch.setattr(sm_mod, "LOCAL_REGISTRY_PATH", fake_local)
    # 新实例（不用全局单例，避免互相干扰）
    m = SkillsMarketManager()
    return m


def _make_registry_data(skills: list[dict]) -> dict:
    """构造注册表 JSON 数据"""
    return {
        "last_updated": "2026-01-01T00:00:00Z",
        "skills": skills,
    }


def _seed_registry(mgr: SkillsMarketManager, skills: list[dict], tmp_path: Path):
    """将注册表写入 cwd/.skills-registry.json 并加载"""
    registry_file = tmp_path / ".skills-registry.json"
    registry_file.write_text(
        json.dumps(_make_registry_data(skills), ensure_ascii=False),
        encoding="utf-8",
    )
    mgr._load_local(force=True)


# ══════════════════════════════════════════════════════════
# 常量测试
# ══════════════════════════════════════════════════════════

class TestConstants:
    def test_remote_url_is_github(self):
        assert "raw.githubusercontent.com" in REMOTE_REGISTRY_URL

    def test_local_registry_path_is_in_home(self):
        assert ".pycoder" in str(LOCAL_REGISTRY_PATH)


# ══════════════════════════════════════════════════════════
# SkillEntry 测试
# ══════════════════════════════════════════════════════════

class TestSkillEntry:
    def test_defaults(self):
        e = SkillEntry(id="x", name="X")
        assert e.id == "x"
        assert e.name == "X"
        assert e.description == ""
        assert e.author == ""
        assert e.stars == 0
        assert e.downloads == 0
        assert e.category == "other"
        assert e.tags == []
        assert e.version == "1.0.0"
        assert e.file is None
        assert e.url is None
        assert e.rating == 0.0
        assert e.ratings_count == 0
        assert e.reviews == []
        assert e.publisher == ""
        assert e.installs == 0
        assert e.verified is False

    def test_from_dict_with_all_fields(self):
        d = {
            "id": "skill-1",
            "name": "Test Skill",
            "description": "desc",
            "author": "auth",
            "stars": 10,
            "downloads": 100,
            "category": "test",
            "tags": ["t1", "t2"],
            "version": "2.0.0",
            "file": "local.py",
            "url": "https://example.com",
            "created_at": "2026-01-01",
            "updated_at": "2026-02-01",
            "rating": 4.5,
            "ratings_count": 10,
            "reviews": [{"user": "x"}],
            "publisher": "pub",
            "installs": 5,
            "verified": True,
        }
        e = SkillEntry.from_dict(d)
        assert e.id == "skill-1"
        assert e.name == "Test Skill"
        assert e.stars == 10
        assert e.rating == 4.5
        assert e.verified is True
        assert e.tags == ["t1", "t2"]

    def test_from_dict_with_missing_fields(self):
        """缺失字段使用默认值"""
        e = SkillEntry.from_dict({"id": "x", "name": "X"})
        assert e.stars == 0
        assert e.category == "other"
        assert e.version == "1.0.0"

    def test_to_dict_round_trip(self):
        original = SkillEntry(
            id="x", name="X", description="d", stars=5,
            version="1.2.3", tags=["a", "b"], rating=4.0,
            ratings_count=2, verified=True,
        )
        d = original.to_dict()
        restored = SkillEntry.from_dict(d)
        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.stars == original.stars
        assert restored.tags == original.tags
        assert restored.verified is True


# ══════════════════════════════════════════════════════════
# _load_local 测试
# ══════════════════════════════════════════════════════════

class TestLoadLocal:
    def test_load_from_cwd_registry(self, mgr, tmp_path):
        """从 cwd/.skills-registry.json 加载"""
        _seed_registry(mgr, [
            {"id": "s1", "name": "S1", "stars": 5},
            {"id": "s2", "name": "S2", "stars": 10},
        ], tmp_path)
        assert len(mgr._registry) == 2
        assert "s1" in mgr._registry
        assert mgr._loaded is True

    def test_load_falls_back_to_local_registry_path(self, mgr, tmp_path, monkeypatch):
        """当 cwd 没有注册表时，回退到 LOCAL_REGISTRY_PATH"""
        # cwd 中没有 .skills-registry.json
        # LOCAL_REGISTRY_PATH 已被 fixture 重定向
        fake_local = tmp_path / "home" / ".pycoder" / "skills_registry.json"
        fake_local.parent.mkdir(parents=True, exist_ok=True)
        fake_local.write_text(
            json.dumps({"skills": [{"id": "fb", "name": "Fallback"}]}),
            encoding="utf-8",
        )
        mgr._load_local(force=True)
        assert "fb" in mgr._registry

    def test_load_invalid_json_skipped(self, mgr, tmp_path):
        """无效 JSON 应被跳过，不抛异常"""
        registry_file = tmp_path / ".skills-registry.json"
        registry_file.write_text("not valid json {{{", encoding="utf-8")
        mgr._load_local(force=True)
        assert mgr._registry == {}  # 加载失败 → 空
        assert mgr._loaded is True

    def test_load_cached_returns_early(self, mgr, tmp_path):
        """已加载时不重复加载"""
        _seed_registry(mgr, [{"id": "x", "name": "X"}], tmp_path)
        # 第二次加载（force=False）应直接返回
        initial_count = len(mgr._registry)
        # 修改注册表文件，但不应被加载
        registry_file = tmp_path / ".skills-registry.json"
        registry_file.write_text(
            json.dumps({"skills": [{"id": "y", "name": "Y"}]}), encoding="utf-8"
        )
        mgr._load_local()  # 不强制
        assert len(mgr._registry) == initial_count  # 未重新加载

    def test_load_no_files_anywhere(self, mgr, tmp_path):
        """没有可加载的注册表文件"""
        # 清空 cwd 和 LOCAL_REGISTRY_PATH
        mgr._load_local(force=True)
        assert mgr._registry == {}
        assert mgr._loaded is True


# ══════════════════════════════════════════════════════════
# sync_from_remote 测试
# ══════════════════════════════════════════════════════════

class TestSyncFromRemote:
    async def test_sync_success_new_skills(self, mgr, tmp_path, monkeypatch):
        """远程同步成功，所有技能都是新的"""
        # mock urllib.request.urlopen
        remote_data = _make_registry_data([
            {"id": "r1", "name": "R1", "version": "1.0.0"},
            {"id": "r2", "name": "R2", "version": "1.0.0"},
        ])
        fake_resp = MagicMock()
        fake_resp.read.return_value = json.dumps(remote_data).encode()
        fake_resp.__enter__ = lambda self: self
        fake_resp.__exit__ = lambda self, *args: None

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=15: fake_resp)

        result = await mgr.sync_from_remote()
        assert result["success"] is True
        assert result["new"] == 2
        assert result["updated"] == 0
        assert result["total"] == 2

    async def test_sync_updates_existing(self, mgr, tmp_path, monkeypatch):
        """远程有版本更新 → 计为 updated"""
        # 先种本地数据
        _seed_registry(mgr, [
            {"id": "r1", "name": "R1", "version": "1.0.0"},
        ], tmp_path)

        remote_data = _make_registry_data([
            {"id": "r1", "name": "R1", "version": "2.0.0"},  # 版本升级
            {"id": "r2", "name": "R2", "version": "1.0.0"},  # 新技能
        ])
        fake_resp = MagicMock()
        fake_resp.read.return_value = json.dumps(remote_data).encode()
        fake_resp.__enter__ = lambda self: self
        fake_resp.__exit__ = lambda self, *args: None

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=15: fake_resp)

        result = await mgr.sync_from_remote()
        assert result["success"] is True
        assert result["new"] == 1
        assert result["updated"] == 1
        assert result["total"] == 2

    async def test_sync_failure_returns_fallback(self, mgr, tmp_path, monkeypatch):
        """同步失败 → 返回 success=False + fallback 提示"""
        import urllib.request
        def raise_error(req, timeout=15):
            raise OSError("network down")
        monkeypatch.setattr(urllib.request, "urlopen", raise_error)

        result = await mgr.sync_from_remote()
        assert result["success"] is False
        assert "fallback" in result
        assert "使用本地缓存" in result["fallback"]


# ══════════════════════════════════════════════════════════
# _save_local 测试
# ══════════════════════════════════════════════════════════

class TestSaveLocal:
    def test_save_default_data(self, mgr, tmp_path, monkeypatch):
        """不传 data 时使用当前注册表"""
        fake_local = tmp_path / "home" / ".pycoder" / "skills_registry.json"
        monkeypatch.setattr(sm_mod, "LOCAL_REGISTRY_PATH", fake_local)
        # 添加一个技能
        mgr._registry["x"] = SkillEntry(id="x", name="X")
        mgr._save_local()
        assert fake_local.exists()
        data = json.loads(fake_local.read_text(encoding="utf-8"))
        assert "skills" in data
        assert len(data["skills"]) == 1
        assert data["skills"][0]["id"] == "x"
        assert "last_updated" in data

    def test_save_custom_data(self, mgr, tmp_path, monkeypatch):
        """传入 data 时直接写入"""
        fake_local = tmp_path / "home" / ".pycoder" / "skills_registry.json"
        monkeypatch.setattr(sm_mod, "LOCAL_REGISTRY_PATH", fake_local)
        custom = {"custom": "data", "skills": []}
        mgr._save_local(custom)
        data = json.loads(fake_local.read_text(encoding="utf-8"))
        assert data == custom


# ══════════════════════════════════════════════════════════
# list_skills 测试
# ══════════════════════════════════════════════════════════

class TestListSkills:
    def test_empty_registry(self, mgr):
        result = mgr.list_skills()
        assert result["skills"] == []
        assert result["total"] == 0
        assert result["has_more"] is False

    def test_sort_by_stars(self, mgr, tmp_path):
        _seed_registry(mgr, [
            {"id": "s1", "name": "A", "stars": 5},
            {"id": "s2", "name": "B", "stars": 10},
            {"id": "s3", "name": "C", "stars": 1},
        ], tmp_path)
        result = mgr.list_skills(sort_by="stars")
        names = [s["name"] for s in result["skills"]]
        assert names == ["B", "A", "C"]  # 降序

    def test_sort_by_downloads(self, mgr, tmp_path):
        _seed_registry(mgr, [
            {"id": "s1", "name": "A", "downloads": 100},
            {"id": "s2", "name": "B", "downloads": 50},
        ], tmp_path)
        result = mgr.list_skills(sort_by="downloads")
        names = [s["name"] for s in result["skills"]]
        assert names == ["A", "B"]

    def test_sort_by_name(self, mgr, tmp_path):
        _seed_registry(mgr, [
            {"id": "s1", "name": "Zebra"},
            {"id": "s2", "name": "Apple"},
        ], tmp_path)
        result = mgr.list_skills(sort_by="name")
        names = [s["name"] for s in result["skills"]]
        assert names == ["Apple", "Zebra"]  # 升序

    def test_filter_by_category(self, mgr, tmp_path):
        _seed_registry(mgr, [
            {"id": "s1", "name": "A", "category": "test"},
            {"id": "s2", "name": "B", "category": "prod"},
            {"id": "s3", "name": "C", "category": "test"},
        ], tmp_path)
        result = mgr.list_skills(category="test")
        assert result["total"] == 2
        assert all(s["category"] == "test" for s in result["skills"])

    def test_search_in_name(self, mgr, tmp_path):
        _seed_registry(mgr, [
            {"id": "s1", "name": "Python Helper"},
            {"id": "s2", "name": "Java Helper"},
            {"id": "s3", "name": "Other"},
        ], tmp_path)
        result = mgr.list_skills(search="python")
        assert result["total"] == 1
        assert result["skills"][0]["name"] == "Python Helper"

    def test_search_in_description(self, mgr, tmp_path):
        _seed_registry(mgr, [
            {"id": "s1", "name": "X", "description": "A Python tool"},
            {"id": "s2", "name": "Y", "description": "A Java tool"},
        ], tmp_path)
        result = mgr.list_skills(search="python")
        assert result["total"] == 1

    def test_search_in_tags(self, mgr, tmp_path):
        _seed_registry(mgr, [
            {"id": "s1", "name": "X", "tags": ["python", "tool"]},
            {"id": "s2", "name": "Y", "tags": ["java"]},
        ], tmp_path)
        result = mgr.list_skills(search="python")
        assert result["total"] == 1

    def test_pagination(self, mgr, tmp_path):
        _seed_registry(mgr, [
            {"id": f"s{i}", "name": f"N{i}", "stars": i} for i in range(10)
        ], tmp_path)
        result = mgr.list_skills(limit=3, offset=0)
        assert len(result["skills"]) == 3
        assert result["total"] == 10
        assert result["has_more"] is True

        # 第二页
        result2 = mgr.list_skills(limit=3, offset=3)
        assert len(result2["skills"]) == 3
        assert result2["offset"] == 3

    def test_pagination_at_end(self, mgr, tmp_path):
        _seed_registry(mgr, [
            {"id": f"s{i}", "name": f"N{i}"} for i in range(5)
        ], tmp_path)
        result = mgr.list_skills(limit=10, offset=0)
        assert result["total"] == 5
        assert result["has_more"] is False

    def test_installed_and_has_update_fields(self, mgr, tmp_path):
        """list_skills 返回的字段含 installed / has_update"""
        _seed_registry(mgr, [
            {"id": "s1", "name": "X", "version": "1.0.0"},
        ], tmp_path)
        result = mgr.list_skills()
        assert "installed" in result["skills"][0]
        assert "has_update" in result["skills"][0]
        assert "rating" in result["skills"][0]
        assert "verified" in result["skills"][0]

    def test_unknown_sort_field_falls_back_to_name(self, mgr, tmp_path):
        """sort_by 不是已知值时回退到按 name 排序"""
        _seed_registry(mgr, [
            {"id": "s1", "name": "B"},
            {"id": "s2", "name": "A"},
        ], tmp_path)
        result = mgr.list_skills(sort_by="unknown")
        names = [s["name"] for s in result["skills"]]
        assert names == ["A", "B"]


# ══════════════════════════════════════════════════════════
# install_skill 测试
# ══════════════════════════════════════════════════════════

class TestInstallSkill:
    def test_install_nonexistent_skill(self, mgr):
        result = mgr.install_skill("nonexistent")
        assert result["success"] is False
        assert "不存在" in result["error"]

    def test_install_local_file_copy(self, mgr, tmp_path):
        """有本地 file 字段 → 复制"""
        src = tmp_path / "source.py"
        src.write_text("# source content", encoding="utf-8")
        _seed_registry(mgr, [
            {"id": "s1", "name": "X", "file": "source.py"},
        ], tmp_path)
        result = mgr.install_skill("s1")
        assert result["success"] is True
        assert result["method"] == "local_copy"
        dest = Path(result["file"])
        assert dest.exists()
        assert dest.read_text() == "# source content"

    def test_install_local_file_source_missing(self, mgr, tmp_path):
        """本地文件源不存在 → 失败"""
        _seed_registry(mgr, [
            {"id": "s1", "name": "X", "file": "missing.py"},
        ], tmp_path)
        result = mgr.install_skill("s1")
        assert result["success"] is False
        assert "源文件不存在" in result["error"]

    async def test_install_github_raw_success(self, mgr, tmp_path, monkeypatch):
        """github URL 安装成功"""
        _seed_registry(mgr, [
            {"id": "s1", "name": "X", "url": "https://github.com/owner/repo"},
        ], tmp_path)
        # mock urllib.request.urlopen 返回 raw 内容
        fake_resp = MagicMock()
        fake_resp.read.return_value = b"# Skill Content"
        fake_resp.__enter__ = lambda self: self
        fake_resp.__exit__ = lambda self, *args: None
        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=10: fake_resp)

        result = mgr.install_skill("s1")
        assert result["success"] is True
        assert result["method"] == "github_raw"
        dest = Path(result["file"])
        assert dest.exists()
        assert "Skill Content" in dest.read_text()

    async def test_install_remote_url_direct(self, mgr, tmp_path, monkeypatch):
        """非 github URL 直接下载成功"""
        _seed_registry(mgr, [
            {"id": "s1", "name": "X", "url": "https://example.com/skill.md"},
        ], tmp_path)
        # 第一个 urlopen 用于 github 匹配（会失败因为 URL 不匹配 github 模式）
        # 第二个用于直接 URL
        call_count = {"n": 0}

        def fake_urlopen(req, timeout=15):
            call_count["n"] += 1
            # 直接 URL 应被命中
            if "example.com" in req.full_url:
                fake_resp = MagicMock()
                fake_resp.read.return_value = b"# Direct Content"
                fake_resp.__enter__ = lambda self: self
                fake_resp.__exit__ = lambda self, *args: None
                return fake_resp
            raise OSError("not found")

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        result = mgr.install_skill("s1")
        assert result["success"] is True
        assert result["method"] == "remote_download"

    async def test_install_readme_fallback(self, mgr, tmp_path, monkeypatch):
        """github_raw 全部失败 → README fallback（master 分支）成功"""
        _seed_registry(mgr, [
            {"id": "s1", "name": "X", "url": "https://github.com/owner/repo"},
        ], tmp_path)
        # mock urlopen: 失败所有 github_raw URLs（SKILL.md/skill.md/main/README.md）
        # 仅 readme_fallback 的 master/README.md 成功
        def fake_urlopen(req, timeout=10):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            # readme_fallback 用 master 分支，github_raw 用 main 分支
            if "master/README.md" in url:
                fake_resp = MagicMock()
                fake_resp.read.return_value = b"# README Content"
                fake_resp.__enter__ = lambda self: self
                fake_resp.__exit__ = lambda self, *args: None
                return fake_resp
            raise OSError("not found")

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        result = mgr.install_skill("s1")
        assert result["success"] is True
        assert result["method"] == "readme_fallback"
        assert Path(result["file"]).read_text() == "# README Content"

    def test_install_auto_generated(self, mgr, tmp_path):
        """无 file 无 url，但有 name + description → 自动生成"""
        _seed_registry(mgr, [
            {"id": "s1", "name": "My Skill", "description": "An auto skill",
             "author": "auth", "category": "tool", "tags": ["a"]},
        ], tmp_path)
        result = mgr.install_skill("s1")
        assert result["success"] is True
        assert result["method"] == "auto_generated"
        content = Path(result["file"]).read_text()
        assert "My Skill" in content
        assert "An auto skill" in content
        assert "Auto-generated" in content

    def test_install_nothing_available(self, mgr, tmp_path):
        """无 file 无 url 无 name/description → 失败"""
        _seed_registry(mgr, [
            {"id": "s1", "name": "", "description": ""},
        ], tmp_path)
        result = mgr.install_skill("s1")
        assert result["success"] is False
        assert "无可下载" in result["error"]


# ══════════════════════════════════════════════════════════
# get_categories / uninstall / update_all / rate / detail / publish 测试
# ══════════════════════════════════════════════════════════

class TestGetCategories:
    def test_empty(self, mgr):
        assert mgr.get_categories() == []

    def test_counts(self, mgr, tmp_path):
        _seed_registry(mgr, [
            {"id": "s1", "name": "A", "category": "test"},
            {"id": "s2", "name": "B", "category": "test"},
            {"id": "s3", "name": "C", "category": "prod"},
        ], tmp_path)
        cats = mgr.get_categories()
        assert {"name": "prod", "count": 1} in cats
        assert {"name": "test", "count": 2} in cats


class TestUninstallSkill:
    def test_uninstall_installed(self, mgr, tmp_path):
        """已安装 → 删除文件"""
        # 先安装一个
        _seed_registry(mgr, [
            {"id": "s1", "name": "X", "description": "d"},
        ], tmp_path)
        mgr.install_skill("s1")
        result = mgr.uninstall_skill("s1")
        assert result["success"] is True
        assert result["action"] == "uninstalled"

    def test_uninstall_not_installed(self, mgr, tmp_path):
        result = mgr.uninstall_skill("nonexistent")
        assert result["success"] is False
        assert "未安装" in result["error"]


class TestUpdateAllSkills:
    def test_no_installed_skills(self, mgr, tmp_path):
        _seed_registry(mgr, [
            {"id": "s1", "name": "X", "version": "1.0.0"},
        ], tmp_path)
        result = mgr.update_all_skills()
        assert result["success"] is True
        assert result["updated"] == []
        assert result["total"] == 0

    def test_update_with_update_available(self, mgr, tmp_path):
        """已安装且有更新 → 调用 install_skill"""
        _seed_registry(mgr, [
            {"id": "s1", "name": "X", "version": "2.0.0",
             "description": "d"},
        ], tmp_path)
        # 模拟已安装（旧版本）
        skills_dir = tmp_path / ".skills"
        skills_dir.mkdir(exist_ok=True)
        local_file = skills_dir / "s1.md"
        local_file.write_text("version: 1.0.0", encoding="utf-8")

        result = mgr.update_all_skills()
        assert result["success"] is True
        assert "s1" in result["updated"]

    def test_update_failed(self, mgr, tmp_path, monkeypatch):
        """install_skill 失败时进入 failed 列表"""
        _seed_registry(mgr, [
            {"id": "s1", "name": "X", "version": "2.0.0",
             "description": "d"},
        ], tmp_path)
        skills_dir = tmp_path / ".skills"
        skills_dir.mkdir(exist_ok=True)
        local_file = skills_dir / "s1.md"
        local_file.write_text("version: 1.0.0", encoding="utf-8")

        # mock install_skill 返回失败
        monkeypatch.setattr(
            mgr, "install_skill",
            lambda sid: {"success": False, "error": "boom"},
        )
        result = mgr.update_all_skills()
        assert result["success"] is True
        assert result["failed"][0]["id"] == "s1"


class TestRateSkill:
    def test_rate_nonexistent_skill(self, mgr, tmp_path):
        result = mgr.rate_skill("nope", 5)
        assert result["success"] is False
        assert "不存在" in result["error"]

    def test_rate_invalid_low(self, mgr, tmp_path):
        _seed_registry(mgr, [{"id": "s1", "name": "X"}], tmp_path)
        result = mgr.rate_skill("s1", 0)
        assert result["success"] is False
        assert "1-5" in result["error"]

    def test_rate_invalid_high(self, mgr, tmp_path):
        _seed_registry(mgr, [{"id": "s1", "name": "X"}], tmp_path)
        result = mgr.rate_skill("s1", 6)
        assert result["success"] is False

    def test_rate_first_rating(self, mgr, tmp_path, monkeypatch):
        _seed_registry(mgr, [{"id": "s1", "name": "X"}], tmp_path)
        # 重定向 _save_local 避免污染
        fake_local = tmp_path / "home" / ".pycoder" / "skills_registry.json"
        monkeypatch.setattr(sm_mod, "LOCAL_REGISTRY_PATH", fake_local)
        result = mgr.rate_skill("s1", 4)
        assert result["success"] is True
        assert result["new_rating"] == 4.0
        assert result["ratings_count"] == 1

    def test_rate_with_review(self, mgr, tmp_path, monkeypatch):
        _seed_registry(mgr, [{"id": "s1", "name": "X"}], tmp_path)
        fake_local = tmp_path / "home" / ".pycoder" / "skills_registry.json"
        monkeypatch.setattr(sm_mod, "LOCAL_REGISTRY_PATH", fake_local)
        result = mgr.rate_skill("s1", 5, review="great")
        assert result["success"] is True
        assert len(mgr._registry["s1"].reviews) == 1
        assert mgr._registry["s1"].reviews[0]["review"] == "great"

    def test_rate_accumulates(self, mgr, tmp_path, monkeypatch):
        _seed_registry(mgr, [{"id": "s1", "name": "X"}], tmp_path)
        fake_local = tmp_path / "home" / ".pycoder" / "skills_registry.json"
        monkeypatch.setattr(sm_mod, "LOCAL_REGISTRY_PATH", fake_local)
        # 第一次评 4 分
        mgr.rate_skill("s1", 4)
        # 第二次评 5 分
        result = mgr.rate_skill("s1", 5)
        # avg = (4*1 + 5)/2 = 4.5
        assert result["new_rating"] == 4.5
        assert result["ratings_count"] == 2


class TestGetSkillDetail:
    def test_nonexistent(self, mgr, tmp_path):
        result = mgr.get_skill_detail("nope")
        assert "error" in result
        assert "不存在" in result["error"]

    def test_existing_skill(self, mgr, tmp_path):
        _seed_registry(mgr, [
            {"id": "s1", "name": "X", "publisher": "pub",
             "verified": True, "installs": 10, "rating": 4.5,
             "ratings_count": 3, "reviews": [{"user": "u", "review": "r"}]},
        ], tmp_path)
        result = mgr.get_skill_detail("s1")
        assert "skill" in result
        detail = result["skill"]
        assert detail["publisher"] == "pub"
        assert detail["verified"] is True
        assert detail["installs"] == 10
        assert detail["rating"] == 4.5
        # 注: list_skills(search="s1") 可能匹配也可能不匹配
        # 主要验证函数能正常完成


class TestPublishSkill:
    def test_publish_new_skill(self, mgr, tmp_path, monkeypatch):
        _seed_registry(mgr, [], tmp_path)
        fake_local = tmp_path / "home" / ".pycoder" / "skills_registry.json"
        monkeypatch.setattr(sm_mod, "LOCAL_REGISTRY_PATH", fake_local)
        result = mgr.publish_skill({
            "id": "new1", "name": "New", "description": "d",
        })
        assert result["success"] is True
        assert "new1" in mgr._registry
        # 新发布技能的统计字段应重置
        assert mgr._registry["new1"].installs == 0
        assert mgr._registry["new1"].rating == 0.0
        assert mgr._registry["new1"].ratings_count == 0

    def test_publish_duplicate_id(self, mgr, tmp_path):
        _seed_registry(mgr, [{"id": "dup", "name": "X"}], tmp_path)
        result = mgr.publish_skill({"id": "dup", "name": "Y"})
        assert result["success"] is False
        assert "已存在" in result["error"]


# ══════════════════════════════════════════════════════════
# _is_installed / _compare_versions / _has_update 测试
# ══════════════════════════════════════════════════════════

class TestIsInstalled:
    def test_not_installed_no_file(self, mgr, tmp_path):
        e = SkillEntry(id="x", name="X")
        assert mgr._is_installed(e) is False

    def test_installed_with_file(self, mgr, tmp_path):
        """file 字段指向已存在的文件"""
        f = tmp_path / "skill.py"
        f.write_text("content", encoding="utf-8")
        e = SkillEntry(id="x", name="X", file="skill.py")
        assert mgr._is_installed(e) is True

    def test_installed_with_md_file(self, mgr, tmp_path):
        """无 file 字段但 .skills/x.md 存在"""
        skills_dir = tmp_path / ".skills"
        skills_dir.mkdir(exist_ok=True)
        (skills_dir / "x.md").write_text("content", encoding="utf-8")
        e = SkillEntry(id="x", name="X")
        assert mgr._is_installed(e) is True


class TestCompareVersions:
    def test_equal_versions(self):
        assert SkillsMarketManager._compare_versions("1.0.0", "1.0.0") == 0

    def test_v1_less_than_v2(self):
        assert SkillsMarketManager._compare_versions("1.0.0", "1.0.1") == -1
        assert SkillsMarketManager._compare_versions("1.0.0", "1.1.0") == -1
        assert SkillsMarketManager._compare_versions("1.0.0", "2.0.0") == -1

    def test_v1_greater_than_v2(self):
        assert SkillsMarketManager._compare_versions("1.0.1", "1.0.0") == 1
        assert SkillsMarketManager._compare_versions("2.0.0", "1.0.0") == 1

    def test_different_length(self):
        assert SkillsMarketManager._compare_versions("1.0.0.0", "1.0.0") == 1
        assert SkillsMarketManager._compare_versions("1.0", "1.0.0") == -1

    def test_non_digit_parts_skipped(self):
        """非数字部分应被跳过"""
        result = SkillsMarketManager._compare_versions("1.0.x", "1.0")
        # parts1 = [1, 0], parts2 = [1, 0] → 相等
        assert result == 0


class TestHasUpdate:
    def test_not_installed_returns_false(self, mgr, tmp_path):
        e = SkillEntry(id="x", name="X", version="2.0.0")
        assert mgr._has_update(e) is False

    def test_installed_older_version(self, mgr, tmp_path):
        """已安装旧版本 → True"""
        skills_dir = tmp_path / ".skills"
        skills_dir.mkdir(exist_ok=True)
        local_file = skills_dir / "x.md"
        local_file.write_text("version: 1.0.0", encoding="utf-8")
        e = SkillEntry(id="x", name="X", version="2.0.0")
        assert mgr._has_update(e) is True

    def test_installed_same_version(self, mgr, tmp_path):
        """已安装相同版本 → False"""
        skills_dir = tmp_path / ".skills"
        skills_dir.mkdir(exist_ok=True)
        local_file = skills_dir / "x.md"
        local_file.write_text("version: 2.0.0", encoding="utf-8")
        e = SkillEntry(id="x", name="X", version="2.0.0")
        assert mgr._has_update(e) is False

    def test_installed_with_file_field(self, mgr, tmp_path):
        """file 字段指向已存在文件"""
        f = tmp_path / "skill.md"
        f.write_text("version: 1.0.0", encoding="utf-8")
        e = SkillEntry(id="x", name="X", version="2.0.0", file="skill.md")
        assert mgr._has_update(e) is True

    def test_no_version_in_file(self, mgr, tmp_path):
        """文件中无版本号 → False"""
        skills_dir = tmp_path / ".skills"
        skills_dir.mkdir(exist_ok=True)
        local_file = skills_dir / "x.md"
        local_file.write_text("no version here", encoding="utf-8")
        e = SkillEntry(id="x", name="X", version="2.0.0")
        assert mgr._has_update(e) is False


# ══════════════════════════════════════════════════════════
# get_skills_market 单例测试
# ══════════════════════════════════════════════════════════

class TestGetSkillsMarket:
    def test_returns_singleton(self, monkeypatch):
        # 重置全局单例
        monkeypatch.setattr(sm_mod, "_manager", None)
        m1 = get_skills_market()
        m2 = get_skills_market()
        assert m1 is m2

    def test_returns_existing_instance(self, monkeypatch):
        fake = MagicMock()
        monkeypatch.setattr(sm_mod, "_manager", fake)
        assert get_skills_market() is fake
