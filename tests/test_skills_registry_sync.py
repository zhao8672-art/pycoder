"""测试 pycoder.skills.registry_client + SkillMarketplace.sync_from_registry

覆盖范围:
- RegistryClient.fetch_index — 拉取索引
- RegistryClient.fetch_skill — 拉取详情
- RegistryClient.fetch_all — 拉取全部（含进度回调）
- RegistryClient._get_json — ETag 缓存 + 重试
- RegistryClient._parse_skill — 字段解析
- RegistryClient 失败重试 + 错误传播
- SkillMarketplace.sync_from_registry — 新增/更新/未变化/失败
- SkillMarketplace._upsert_from_registry — 保留本地数据
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from pycoder.skills import SkillDefinition, SkillMarketplace
from pycoder.skills.registry_client import (
    DEFAULT_REGISTRY_URL,
    RegistryClient,
    RegistrySkill,
    SyncResult,
)

# ═══════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════


def _make_registry_skill(
    skill_id: str = "remote-1",
    name: str = "Remote Skill",
    version: str = "1.0.0",
    description: str = "Remote description",
    markdown_content: str = "# Remote\n\nContent",
    **kwargs: Any,
) -> RegistrySkill:
    """创建测试用 RegistrySkill"""
    return RegistrySkill(
        id=skill_id,
        name=name,
        version=version,
        description=description,
        markdown_content=markdown_content,
        **kwargs,
    )


class MockTransport:
    """httpx.AsyncClient 自定义 transport，模拟 Registry 响应"""

    def __init__(
        self,
        *,
        index_data: list[dict] | None = None,
        skill_details: dict[str, dict] | None = None,
        etag: str = "v1",
        status_code: int = 200,
        fail_first_n: int = 0,
    ) -> None:
        self._index = index_data or []
        self._details = skill_details or {}
        self._etag = etag
        self._status = status_code
        self._fail_first_n = fail_first_n
        self._call_count = 0
        self.requests: list[httpx.Request] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self._call_count += 1
        if self._call_count <= self._fail_first_n:
            raise httpx.ConnectError("simulated failure", request=request)
        if self._status == 304:
            return httpx.Response(304, request=request, headers={"ETag": self._etag})
        if self._status != 200:
            return httpx.Response(self._status, text="error", request=request)

        # ETag 命中检查
        if_none_match = request.headers.get("If-None-Match")
        if if_none_match and if_none_match == self._etag and self._etag:
            return httpx.Response(304, request=request, headers={"ETag": self._etag})

        path = request.url.path
        if path.endswith("/index.json"):
            return httpx.Response(
                200,
                json={"skills": self._index},
                request=request,
                headers={"ETag": self._etag},
            )
        if "/skills/" in path and path.endswith(".json"):
            skill_id = path.split("/skills/")[-1].removesuffix(".json")
            detail = self._details.get(skill_id, {})
            return httpx.Response(
                200,
                json=detail,
                request=request,
                headers={"ETag": self._etag},
            )
        return httpx.Response(404, text="not found", request=request)


def _make_client_with_transport(transport: MockTransport) -> RegistryClient:
    """创建带 mock transport 的 RegistryClient（monkeypatch httpx.AsyncClient）"""
    client = RegistryClient("https://registry.test")
    original_get_json = client._get_json

    async def patched_get_json(url: str) -> Any:
        """绕过 httpx.AsyncClient，直接调用 transport"""
        from urllib.parse import urlparse

        parsed = urlparse(url)
        request = httpx.Request("GET", url)
        # ETag 头注入
        etag = client._etags.get(url)
        if etag:
            request.headers["If-None-Match"] = etag

        try:
            response = await transport(request)
        except httpx.HTTPError as e:
            # 模拟重试
            for _attempt in range(client._max_retries):
                try:
                    response = await transport(request)
                    break
                except httpx.HTTPError:
                    continue
            else:
                raise RuntimeError(f"Registry 请求失败: {url} - {e}") from e

        if response.status_code == 304:
            return {}
        response.raise_for_status()
        new_etag = response.headers.get("ETag")
        if new_etag:
            client._etags[url] = new_etag
        return response.json()

    client._get_json = patched_get_json  # type: ignore[assignment]
    return client


# ═══════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════


@pytest.fixture
def temp_skills_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """创建临时技能目录，隔离测试数据"""
    skills_dir = tmp_path / "data" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    SkillMarketplace._instance = None
    import pycoder.skills as skills_module

    monkeypatch.setattr(skills_module, "DATA_DIR", skills_dir)
    monkeypatch.setattr(skills_module, "DB_PATH", skills_dir / "skills.db")
    monkeypatch.setattr(skills_module, "_marketplace", None)

    yield skills_dir

    SkillMarketplace._instance = None
    skills_module._marketplace = None


@pytest.fixture
def marketplace(temp_skills_dir: Path) -> SkillMarketplace:
    """创建隔离的技能市场实例"""
    return SkillMarketplace()


@pytest.fixture
def clean_marketplace(marketplace: SkillMarketplace) -> SkillMarketplace:
    """清空所有技能数据的 marketplace"""
    with sqlite3.connect(str(marketplace._db_path)) as conn:
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
        conn.execute("DROP TABLE IF EXISTS skills_fts")
        conn.commit()
    return marketplace


# ═══════════════════════════════════════════════
# 1. RegistryClient 基础测试
# ═══════════════════════════════════════════════


class TestRegistryClientInit:
    """RegistryClient 初始化测试"""

    def test_default_values(self) -> None:
        """默认参数应正确设置"""
        client = RegistryClient()
        assert client.registry_url == DEFAULT_REGISTRY_URL
        assert client._timeout == 30.0
        assert client._max_retries == 2

    def test_custom_url_strips_trailing_slash(self) -> None:
        """自定义 URL 应去除尾部斜杠"""
        client = RegistryClient("https://example.com/")
        assert client.registry_url == "https://example.com"

    def test_custom_params(self) -> None:
        """自定义参数应正确设置"""
        client = RegistryClient("https://custom.registry", timeout=10.0, max_retries=5)
        assert client.registry_url == "https://custom.registry"
        assert client._timeout == 10.0
        assert client._max_retries == 5


# ═══════════════════════════════════════════════
# 2. fetch_index 测试
# ═══════════════════════════════════════════════


class TestFetchIndex:
    """fetch_index 测试"""

    @pytest.mark.asyncio
    async def test_fetch_index_returns_list(self) -> None:
        """fetch_index 应返回技能列表"""
        index_data = [
            {"id": "skill-a", "name": "Skill A", "version": "1.0.0"},
            {"id": "skill-b", "name": "Skill B", "version": "2.0.0"},
        ]
        transport = MockTransport(index_data=index_data)
        client = _make_client_with_transport(transport)
        result = await client.fetch_index()
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["id"] == "skill-a"

    @pytest.mark.asyncio
    async def test_fetch_index_empty(self) -> None:
        """空索引应返回空列表"""
        transport = MockTransport(index_data=[])
        client = _make_client_with_transport(transport)
        result = await client.fetch_index()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_index_dict_with_skills_key(self) -> None:
        """若返回 {skills: [...]} 字典，应提取 skills 字段"""
        original = MockTransport(index_data=[{"id": "x", "name": "X"}])

        class DictTransport(MockTransport):
            async def __call__(self, request: httpx.Request) -> httpx.Response:
                if request.url.path.endswith("/index.json"):
                    return httpx.Response(
                        200,
                        json={"skills": [{"id": "dict-skill"}]},
                        request=request,
                    )
                return await original.__call__(request)

        transport2 = DictTransport()
        client = _make_client_with_transport(transport2)
        result = await client.fetch_index()
        assert result == [{"id": "dict-skill"}]


# ═══════════════════════════════════════════════
# 3. fetch_skill 测试
# ═══════════════════════════════════════════════


class TestFetchSkill:
    """fetch_skill 测试"""

    @pytest.mark.asyncio
    async def test_fetch_skill_returns_detail(self) -> None:
        """fetch_skill 应返回技能详情"""
        details = {
            "remote-1": {
                "id": "remote-1",
                "name": "Remote Skill",
                "version": "1.5.0",
                "markdown_content": "# Remote\n\nContent",
            }
        }
        transport = MockTransport(skill_details=details)
        client = _make_client_with_transport(transport)
        result = await client.fetch_skill("remote-1")
        assert result["id"] == "remote-1"
        assert result["version"] == "1.5.0"
        assert "markdown_content" in result

    @pytest.mark.asyncio
    async def test_fetch_skill_nonexistent(self) -> None:
        """不存在的技能应返回空字典"""
        transport = MockTransport(skill_details={})
        client = _make_client_with_transport(transport)
        result = await client.fetch_skill("nonexistent")
        assert result == {}


# ═══════════════════════════════════════════════
# 4. fetch_all 测试
# ═══════════════════════════════════════════════


class TestFetchAll:
    """fetch_all 测试"""

    @pytest.mark.asyncio
    async def test_fetch_all_returns_full_skills(self) -> None:
        """fetch_all 应返回完整技能列表（含 markdown_content）"""
        index_data = [
            {"id": "skill-a", "name": "Skill A", "version": "1.0.0"},
            {"id": "skill-b", "name": "Skill B", "version": "2.0.0"},
        ]
        details = {
            "skill-a": {
                "id": "skill-a",
                "name": "Skill A",
                "version": "1.0.0",
                "description": "Skill A description",
                "markdown_content": "# A",
                "category": "tools",
                "tags": ["test"],
            },
            "skill-b": {
                "id": "skill-b",
                "name": "Skill B",
                "version": "2.0.0",
                "description": "Skill B description",
                "markdown_content": "# B",
                "category": "general",
                "verified": True,
                "stars": 42,
            },
        }
        transport = MockTransport(index_data=index_data, skill_details=details)
        client = _make_client_with_transport(transport)
        skills = await client.fetch_all()
        assert len(skills) == 2
        assert all(isinstance(s, RegistrySkill) for s in skills)
        # 验证字段对齐
        skill_a = next(s for s in skills if s.id == "skill-a")
        assert skill_a.name == "Skill A"
        assert skill_a.markdown_content == "# A"
        assert skill_a.category == "tools"
        skill_b = next(s for s in skills if s.id == "skill-b")
        assert skill_b.verified is True
        assert skill_b.stars == 42

    @pytest.mark.asyncio
    async def test_fetch_all_with_progress_callback(self) -> None:
        """进度回调应被调用"""
        index_data = [{"id": f"s-{i}", "name": f"S{i}"} for i in range(5)]
        details = {f"s-{i}": {"id": f"s-{i}", "markdown_content": "# x"} for i in range(5)}
        transport = MockTransport(index_data=index_data, skill_details=details)
        client = _make_client_with_transport(transport)

        progress_calls: list[tuple[int, int, str]] = []

        async def progress(completed: int, total: int, step: str) -> None:
            progress_calls.append((completed, total, step))

        await client.fetch_all(progress=progress)
        # 至少调用：1次开始 + 5次拉取 + 1次完成 = 7次
        assert len(progress_calls) >= 7
        # 最后一次应为完成状态
        assert progress_calls[-1][0] == 5
        assert progress_calls[-1][1] == 5
        assert "完成" in progress_calls[-1][2]

    @pytest.mark.asyncio
    async def test_fetch_all_skips_empty_id(self) -> None:
        """索引中空 id 应被跳过"""
        index_data = [
            {"id": "", "name": "Empty"},
            {"id": "valid", "name": "Valid"},
        ]
        details = {"valid": {"id": "valid", "markdown_content": "# x"}}
        transport = MockTransport(index_data=index_data, skill_details=details)
        client = _make_client_with_transport(transport)
        skills = await client.fetch_all()
        assert len(skills) == 1
        assert skills[0].id == "valid"

    @pytest.mark.asyncio
    async def test_fetch_all_continues_on_skill_fetch_error(self) -> None:
        """单个技能拉取失败不应中断整体流程"""
        index_data = [
            {"id": "ok", "name": "OK"},
            {"id": "bad", "name": "Bad"},
        ]
        details = {"ok": {"id": "ok", "markdown_content": "# ok"}}
        transport = MockTransport(index_data=index_data, skill_details=details)
        client = _make_client_with_transport(transport)

        # 让 bad 抛异常
        original_fetch_skill = client.fetch_skill

        async def fetch_skill_with_failure(skill_id: str) -> dict:
            if skill_id == "bad":
                raise RuntimeError("simulated failure")
            return await original_fetch_skill(skill_id)

        client.fetch_skill = fetch_skill_with_failure  # type: ignore[assignment]
        skills = await client.fetch_all()
        # 只有 ok 被成功拉取
        assert len(skills) == 1
        assert skills[0].id == "ok"


# ═══════════════════════════════════════════════
# 5. _parse_skill 测试
# ═══════════════════════════════════════════════


class TestParseSkill:
    """_parse_skill 字段解析测试"""

    def test_parse_full_skill(self) -> None:
        """完整字段应正确解析"""
        data = {
            "id": "full",
            "name": "Full Skill",
            "version": "3.2.1",
            "description": "Full description",
            "author": "Author",
            "category": "tools",
            "tags": ["a", "b"],
            "dependencies": ["dep-1"],
            "publisher": "Publisher",
            "verified": True,
            "source_url": "https://example.com/src",
            "homepage_url": "https://example.com",
            "license": "MIT",
            "icon_url": "https://example.com/icon.png",
            "stars": 100,
            "markdown_content": "# Full",
        }
        skill = RegistryClient._parse_skill(data)
        assert skill.id == "full"
        assert skill.name == "Full Skill"
        assert skill.version == "3.2.1"
        assert skill.tags == ["a", "b"]
        assert skill.dependencies == ["dep-1"]
        assert skill.publisher == "Publisher"
        assert skill.verified is True
        assert skill.stars == 100

    def test_parse_minimal_skill(self) -> None:
        """最小字段（仅 id/name）应使用默认值"""
        skill = RegistryClient._parse_skill({"id": "min", "name": "Min"})
        assert skill.id == "min"
        assert skill.name == "Min"
        assert skill.version == "1.0.0"
        assert skill.author == "PyCoder"
        assert skill.category == "general"
        assert skill.tags == []
        assert skill.markdown_content == ""

    def test_parse_handles_none_values(self) -> None:
        """None 值应被正确处理"""
        data = {"id": "x", "name": "X", "tags": None, "dependencies": None, "stars": None}
        skill = RegistryClient._parse_skill(data)
        assert skill.tags == []
        assert skill.dependencies == []
        assert skill.stars == 0


# ═══════════════════════════════════════════════
# 6. SyncResult 测试
# ═══════════════════════════════════════════════


class TestSyncResult:
    """SyncResult 数据类测试"""

    def test_default_values(self) -> None:
        result = SyncResult()
        assert result.total == 0
        assert result.new == 0
        assert result.updated == 0
        assert result.unchanged == 0
        assert result.failed == 0
        assert result.errors == []

    def test_to_dict(self) -> None:
        result = SyncResult(total=10, new=3, updated=2, failed=1, errors=["x: err"])
        d = result.to_dict()
        assert d["total"] == 10
        assert d["new"] == 3
        assert d["updated"] == 2
        assert d["failed"] == 1
        assert d["errors"] == ["x: err"]


# ═══════════════════════════════════════════════
# 7. SkillMarketplace.sync_from_registry 测试
# ═══════════════════════════════════════════════


class TestSyncFromRegistry:
    """sync_from_registry 集成测试"""

    @pytest.mark.asyncio
    async def test_sync_new_skills(self, clean_marketplace: SkillMarketplace) -> None:
        """新技能应被 INSERT 到本地数据库"""
        mp = clean_marketplace
        skills = [
            _make_registry_skill(skill_id="new-1", name="New 1", version="1.0.0"),
            _make_registry_skill(skill_id="new-2", name="New 2", version="2.0.0"),
        ]

        class FakeClient:
            async def fetch_all(self, progress=None):
                return skills

        result = await mp.sync_from_registry(FakeClient())
        assert result["total"] == 2
        assert result["new"] == 2
        assert result["updated"] == 0
        assert result["unchanged"] == 0
        assert result["failed"] == 0

        # 验证数据库
        with sqlite3.connect(str(mp._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, name, version, remote_version FROM skills ORDER BY id"
            ).fetchall()
        assert len(rows) == 2
        assert rows[0]["id"] == "new-1"
        assert rows[0]["remote_version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_sync_updates_existing_skill(self, clean_marketplace: SkillMarketplace) -> None:
        """已存在的技能版本应被 UPDATE"""
        mp = clean_marketplace
        # 本地先注册一个旧版本
        sd = SkillDefinition(
            id="exist-1",
            name="Old Name",
            version="1.0.0",
            description="old desc",
            markdown_content="# old",
        )
        mp._save_skill_to_db(sd, mark_as_installed=False)

        # 远程推送新版本
        skills = [
            _make_registry_skill(
                skill_id="exist-1",
                name="New Name",
                version="2.0.0",
                description="new desc",
                markdown_content="# new",
            )
        ]

        class FakeClient:
            async def fetch_all(self, progress=None):
                return skills

        result = await mp.sync_from_registry(FakeClient())
        assert result["total"] == 1
        assert result["updated"] == 1

        # 验证字段已更新
        with sqlite3.connect(str(mp._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT name, version, description, remote_version FROM skills WHERE id = ?",
                ("exist-1",),
            ).fetchone()
        assert row["name"] == "New Name"
        assert row["version"] == "2.0.0"
        assert row["remote_version"] == "2.0.0"
        assert row["description"] == "new desc"

    @pytest.mark.asyncio
    async def test_sync_unchanged_skill(self, clean_marketplace: SkillMarketplace) -> None:
        """相同版本应被标记为 unchanged"""
        mp = clean_marketplace
        # 本地注册一个技能
        sd = SkillDefinition(
            id="same-1",
            name="Same",
            version="1.0.0",
            markdown_content="# same",
        )
        mp._save_skill_to_db(sd, mark_as_installed=False)

        # 远程推送相同版本
        skills = [_make_registry_skill(skill_id="same-1", name="Same", version="1.0.0")]

        class FakeClient:
            async def fetch_all(self, progress=None):
                return skills

        result = await mp.sync_from_registry(FakeClient())
        assert result["unchanged"] == 1

    @pytest.mark.asyncio
    async def test_sync_preserves_local_install_data(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """同步应保留本地 install_count/rating/installed_at/local_version"""
        mp = clean_marketplace
        # 本地安装一个技能
        sd = SkillDefinition(
            id="preserve-1",
            name="Preserve",
            version="1.0.0",
            markdown_content="# v1",
        )
        mp._save_skill_to_db(sd, mark_as_installed=False)
        # 设置安装状态和评分
        with sqlite3.connect(str(mp._db_path)) as conn:
            conn.execute(
                "UPDATE skills SET install_count = 42, rating = 4.5, "
                "rating_count = 10, rating_sum = 45, installed_at = '2026-01-01', "
                "local_version = '1.0.0' WHERE id = ?",
                ("preserve-1",),
            )
            conn.commit()

        # 远程推送新版本
        skills = [
            _make_registry_skill(
                skill_id="preserve-1",
                name="Preserve New",
                version="2.0.0",
                markdown_content="# v2",
            )
        ]

        class FakeClient:
            async def fetch_all(self, progress=None):
                return skills

        await mp.sync_from_registry(FakeClient())

        # 验证本地字段被保留
        with sqlite3.connect(str(mp._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT install_count, rating, rating_count, rating_sum, "
                "installed_at, local_version, version, remote_version "
                "FROM skills WHERE id = ?",
                ("preserve-1",),
            ).fetchone()
        assert row["install_count"] == 42
        assert row["rating"] == 4.5
        assert row["rating_count"] == 10
        assert row["rating_sum"] == 45
        assert row["installed_at"] == "2026-01-01"
        assert row["local_version"] == "1.0.0"
        # 远程字段应更新
        assert row["version"] == "2.0.0"
        assert row["remote_version"] == "2.0.0"

    @pytest.mark.asyncio
    async def test_sync_failed_skill_recorded_in_errors(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """失败的技能应被记录在 errors 列表"""
        mp = clean_marketplace

        # 让 _upsert_from_registry 对 'bad' 抛异常
        original_upsert = mp._upsert_from_registry

        async def failing_upsert(remote):
            if remote.id == "bad":
                raise ValueError("bad skill")
            await original_upsert(remote)

        mp._upsert_from_registry = failing_upsert  # type: ignore[assignment]

        skills = [
            _make_registry_skill(skill_id="good", name="Good"),
            _make_registry_skill(skill_id="bad", name="Bad"),
        ]

        class FakeClient:
            async def fetch_all(self, progress=None):
                return skills

        result = await mp.sync_from_registry(FakeClient())
        assert result["total"] == 2
        assert result["new"] == 1  # good 被插入
        assert result["failed"] == 1
        assert any("bad" in err for err in result["errors"])

    @pytest.mark.asyncio
    async def test_sync_progress_callback_called(self, clean_marketplace: SkillMarketplace) -> None:
        """进度回调应被传递到 fetch_all"""
        mp = clean_marketplace
        progress_received: list[Any] = []

        async def fake_fetch_all(progress=None):
            if progress:
                await progress(0, 5, "start")
                await progress(5, 5, "done")
            progress_received.append(progress)
            return []

        class FakeClient:
            async def fetch_all(self, progress=None):
                return await fake_fetch_all(progress)

        async def my_progress(c, t, s):
            pass

        await mp.sync_from_registry(FakeClient(), progress=my_progress)
        assert progress_received[0] is my_progress


# ═══════════════════════════════════════════════
# 8. _upsert_from_registry 单元测试
# ═══════════════════════════════════════════════


class TestUpsertFromRegistry:
    """_upsert_from_registry 单元测试"""

    @pytest.mark.asyncio
    async def test_upsert_new_skill_creates_record(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """新技能应创建记录，installed_at 为空"""
        mp = clean_marketplace
        remote = _make_registry_skill(skill_id="new-upsert", name="New")
        await mp._upsert_from_registry(remote)

        with sqlite3.connect(str(mp._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, installed_at, local_version, remote_version FROM skills WHERE id = ?",
                ("new-upsert",),
            ).fetchone()
        assert row is not None
        assert row["installed_at"] == ""
        assert row["local_version"] == ""
        assert row["remote_version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_upsert_existing_preserves_local_fields(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """已存在技能应保留本地字段"""
        mp = clean_marketplace
        # 本地先注册
        sd = SkillDefinition(
            id="preserve-2",
            name="Old",
            version="1.0.0",
            markdown_content="# old",
        )
        mp._save_skill_to_db(sd, mark_as_installed=False)
        with sqlite3.connect(str(mp._db_path)) as conn:
            conn.execute(
                "UPDATE skills SET install_count = 99, local_version = '1.0.0', "
                "installed_at = '2026-01-01' WHERE id = ?",
                ("preserve-2",),
            )
            conn.commit()

        # 远程推送新版本
        remote = _make_registry_skill(
            skill_id="preserve-2",
            name="New",
            version="2.0.0",
            markdown_content="# new",
        )
        await mp._upsert_from_registry(remote)

        with sqlite3.connect(str(mp._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT install_count, local_version, installed_at, version, name "
                "FROM skills WHERE id = ?",
                ("preserve-2",),
            ).fetchone()
        assert row["install_count"] == 99
        assert row["local_version"] == "1.0.0"
        assert row["installed_at"] == "2026-01-01"
        assert row["version"] == "2.0.0"
        assert row["name"] == "New"

    @pytest.mark.asyncio
    async def test_upsert_empty_remote_md_preserves_local_md(
        self, clean_marketplace: SkillMarketplace
    ) -> None:
        """远程 markdown_content 为空时应保留本地内容"""
        mp = clean_marketplace
        sd = SkillDefinition(
            id="md-keep",
            name="MD",
            version="1.0.0",
            markdown_content="# local content",
        )
        mp._save_skill_to_db(sd, mark_as_installed=False)

        remote = _make_registry_skill(
            skill_id="md-keep",
            name="MD Updated",
            version="1.5.0",
            markdown_content="",  # 远程无内容
        )
        await mp._upsert_from_registry(remote)

        with sqlite3.connect(str(mp._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT markdown_content FROM skills WHERE id = ?",
                ("md-keep",),
            ).fetchone()
        assert row["markdown_content"] == "# local content"

    @pytest.mark.asyncio
    async def test_upsert_writes_skill_file(self, clean_marketplace: SkillMarketplace) -> None:
        """新技能应写入文件系统 SKILL.md"""
        mp = clean_marketplace
        remote = _make_registry_skill(
            skill_id="file-test",
            name="File",
            markdown_content="# File Skill\n\nTest content.",
        )
        await mp._upsert_from_registry(remote)
        skill_file = mp._skills_dir / "file-test" / "SKILL.md"
        assert skill_file.exists()
        assert "File Skill" in skill_file.read_text(encoding="utf-8")
