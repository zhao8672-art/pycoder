"""覆盖率测试: pycoder/server/routers/cloud_api.py

目标: 行覆盖率 >= 95%

覆盖端点:
    POST   /api/cloud/auth/register    — 注册新用户
    POST   /api/cloud/auth/login       — 登录（成功 / 失败）
    POST   /api/cloud/auth/refresh     — 刷新令牌（成功 / 失败）
    POST   /api/cloud/auth/logout      — 登出
    POST   /api/cloud/sync/upload      — 上传评分（成功 / 失败）
    GET    /api/cloud/sync/download    — 下载评分（成功 / 失败 / since 格式错）
    GET    /api/cloud/sync/status      — 同步状态（成功 / 失败）
    POST   /api/cloud/sync/resolve     — 冲突解决（非法策略 / 成功 / 失败）
    GET    /api/cloud/devices          — 设备列表（成功 / 失败）
    POST   /api/cloud/devices/register — 设备注册（已存在 / 成功 / 异常）
    DELETE /api/cloud/devices/{id}     — 删除设备（不存在 / 成功 / 异常）

测试策略:
    - 用 FastAPI dependency_overrides 替换 get_db / get_current_user
    - mock CloudAuthService / CloudSyncEngine 的所有方法
    - 直接 patch DeviceInfo 查询路径以覆盖设备注册/删除的内部逻辑
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pycoder.server.routers import cloud_api as cloud_mod


# ══════════════════════════════════════════════════════════
# 通用 Fixtures
# ══════════════════════════════════════════════════════════


def _fake_user():
    """模拟已认证用户"""
    return {"user_id": "u-1", "username": "alice", "device_id": "dev-1"}


@pytest.fixture
def mock_db():
    """模拟数据库会话"""
    return MagicMock()


@pytest.fixture
def app_client(mock_db):
    """创建仅包含 cloud_api 路由的 FastAPI 应用，并替换 get_db / get_current_user"""
    app = FastAPI()
    app.include_router(cloud_mod.router)

    async def _override_db():
        yield mock_db

    app.dependency_overrides[cloud_mod.get_db] = _override_db
    app.dependency_overrides[cloud_mod.get_current_user] = _fake_user

    with TestClient(app) as c:
        yield c


# ══════════════════════════════════════════════════════════
# 0. get_db 依赖本身（不通过 dependency_overrides）
# ══════════════════════════════════════════════════════════


class TestGetDb:
    def test_get_db_yields_and_closes(self, monkeypatch):
        """get_db 生成器应 yield session 并在结束时 close"""
        from sqlalchemy.orm import sessionmaker

        fake_session = MagicMock()
        fake_sessionmaker = MagicMock(return_value=fake_session)
        fake_engine = MagicMock()

        # 模拟 sqlalchemy.create_engine 与 sessionmaker
        import sys
        fake_sa = MagicMock()
        fake_sa.create_engine = MagicMock(return_value=fake_engine)

        fake_sa_orm = MagicMock()
        fake_sa_orm.sessionmaker = MagicMock(return_value=fake_sessionmaker)

        # cloud_api 内部使用 `from sqlalchemy import create_engine` 和
        # `from sqlalchemy.orm import sessionmaker`，因此注入到 sys.modules
        monkeypatch.setitem(sys.modules, "sqlalchemy", fake_sa)
        monkeypatch.setitem(sys.modules, "sqlalchemy.orm", fake_sa_orm)

        gen = cloud_mod.get_db()
        session = next(gen)
        assert session is fake_session
        # 触发 finally
        with pytest.raises(StopIteration):
            next(gen)
        fake_session.close.assert_called_once()


# ══════════════════════════════════════════════════════════
# 1. get_current_user 依赖本身
# ══════════════════════════════════════════════════════════


class TestGetCurrentUser:
    def test_invalid_token_format(self, mock_db):
        """非 Bearer 前缀 → 401"""
        app = FastAPI()
        app.include_router(cloud_mod.router)
        # 不 override get_current_user，让真实逻辑跑
        async def _override_db():
            yield mock_db
        app.dependency_overrides[cloud_mod.get_db] = _override_db

        with TestClient(app) as c:
            resp = c.post(
                "/api/cloud/auth/logout",
                headers={"authorization": "Basic abc"},
            )
        assert resp.status_code == 401
        assert "无效的认证令牌" in resp.json()["detail"]

    def test_token_verify_returns_none(self, mock_db, monkeypatch):
        """verify_access_token 返回 None → 401"""
        app = FastAPI()
        app.include_router(cloud_mod.router)
        async def _override_db():
            yield mock_db
        app.dependency_overrides[cloud_mod.get_db] = _override_db
        # mock verify_access_token 返回 None
        monkeypatch.setattr(cloud_mod, "verify_access_token", lambda token: None)

        with TestClient(app) as c:
            resp = c.post(
                "/api/cloud/auth/logout",
                headers={"authorization": "Bearer sometoken"},
            )
        assert resp.status_code == 401
        assert "令牌已过期" in resp.json()["detail"]

    def test_valid_token(self, mock_db, monkeypatch):
        """有效 token → 返回用户字典"""
        app = FastAPI()
        app.include_router(cloud_mod.router)
        async def _override_db():
            yield mock_db
        app.dependency_overrides[cloud_mod.get_db] = _override_db

        fake_token_data = MagicMock(
            user_id="u1", username="bob", device_id="d1"
        )
        monkeypatch.setattr(cloud_mod, "verify_access_token", lambda token: fake_token_data)

        with TestClient(app) as c:
            resp = c.post(
                "/api/cloud/auth/logout",
                headers={"authorization": "Bearer valid"},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ══════════════════════════════════════════════════════════
# 2. POST /auth/register
# ══════════════════════════════════════════════════════════


class TestRegister:
    def test_success(self, app_client, mock_db):
        """注册成功"""
        with patch.object(cloud_mod, "CloudAuthService") as MockSvc:
            instance = MockSvc.return_value
            instance.register_user = AsyncMock(return_value={
                "success": True, "user_id": "u1", "message": "注册成功",
            })
            resp = app_client.post("/api/cloud/auth/register", json={
                "username": "alice", "email": "a@b.com", "password": "secret",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["user_id"] == "u1"


# ══════════════════════════════════════════════════════════
# 3. POST /auth/login
# ══════════════════════════════════════════════════════════


class TestLogin:
    def test_success(self, app_client, mock_db):
        """登录成功"""
        with patch.object(cloud_mod, "CloudAuthService") as MockSvc:
            instance = MockSvc.return_value
            instance.login_user = AsyncMock(return_value={
                "success": True, "user_id": "u1",
                "access_token": "a", "refresh_token": "r",
            })
            resp = app_client.post("/api/cloud/auth/login", json={
                "username": "alice", "password": "secret",
                "device_id": "d1", "device_name": "dev",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["access_token"] == "a"

    def test_failure(self, app_client, mock_db):
        """登录失败 → 401"""
        with patch.object(cloud_mod, "CloudAuthService") as MockSvc:
            instance = MockSvc.return_value
            instance.login_user = AsyncMock(return_value={
                "success": False, "error": "密码错误",
            })
            resp = app_client.post("/api/cloud/auth/login", json={
                "username": "alice", "password": "wrong",
                "device_id": "d1", "device_name": "dev",
            })
        assert resp.status_code == 401
        assert "密码错误" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════
# 4. POST /auth/refresh
# ══════════════════════════════════════════════════════════


class TestRefresh:
    def test_success(self, app_client, mock_db):
        with patch.object(cloud_mod, "CloudAuthService") as MockSvc:
            instance = MockSvc.return_value
            instance.refresh_access_token = AsyncMock(return_value={
                "success": True, "access_token": "new", "expires_in": 900,
            })
            resp = app_client.post("/api/cloud/auth/refresh", json={
                "refresh_token": "rtoken",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["access_token"] == "new"

    def test_failure(self, app_client, mock_db):
        with patch.object(cloud_mod, "CloudAuthService") as MockSvc:
            instance = MockSvc.return_value
            instance.refresh_access_token = AsyncMock(return_value={
                "success": False, "error": "无效刷新令牌",
            })
            resp = app_client.post("/api/cloud/auth/refresh", json={
                "refresh_token": "expired",
            })
        assert resp.status_code == 401
        assert "无效刷新令牌" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════
# 5. POST /auth/logout
# ══════════════════════════════════════════════════════════


class TestLogout:
    def test_logout(self, app_client):
        """登出 → 返回 success"""
        resp = app_client.post("/api/cloud/auth/logout")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["message"] == "登出成功"


# ══════════════════════════════════════════════════════════
# 6. POST /sync/upload
# ══════════════════════════════════════════════════════════


class TestSyncUpload:
    def test_success(self, app_client, mock_db):
        with patch.object(cloud_mod, "CloudSyncEngine") as MockEngine:
            inst = MockEngine.return_value
            inst.upload_ratings = AsyncMock(return_value={
                "success": True, "uploaded": 1, "conflicts": [],
                "timestamp": "2026-07-09T10:00:00",
            })
            resp = app_client.post("/api/cloud/sync/upload", json={
                "ratings": [
                    {"skill_id": "s1", "rating": 4, "review": "ok",
                     "timestamp": "2026-07-09T10:00:00"},
                ],
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["uploaded"] == 1

    def test_failure(self, app_client, mock_db):
        with patch.object(cloud_mod, "CloudSyncEngine") as MockEngine:
            inst = MockEngine.return_value
            inst.upload_ratings = AsyncMock(return_value={
                "success": False, "error": "网络错误",
                "timestamp": "2026-07-09T10:00:00",
            })
            resp = app_client.post("/api/cloud/sync/upload", json={
                "ratings": [],
            })
        assert resp.status_code == 400
        assert "网络错误" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════
# 7. GET /sync/download
# ══════════════════════════════════════════════════════════


class TestSyncDownload:
    def test_success(self, app_client, mock_db):
        with patch.object(cloud_mod, "CloudSyncEngine") as MockEngine:
            inst = MockEngine.return_value
            inst.download_ratings = AsyncMock(return_value={
                "success": True, "ratings": [{"skill_id": "s1"}],
                "count": 1, "timestamp": "2026-07-09T10:00:00",
            })
            resp = app_client.get("/api/cloud/sync/download")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["count"] == 1

    def test_with_since(self, app_client, mock_db):
        """since 参数为合法 ISO 格式"""
        with patch.object(cloud_mod, "CloudSyncEngine") as MockEngine:
            inst = MockEngine.return_value
            inst.download_ratings = AsyncMock(return_value={
                "success": True, "ratings": [], "count": 0,
                "timestamp": "2026-07-09T10:00:00",
            })
            resp = app_client.get(
                "/api/cloud/sync/download",
                params={"since": "2026-07-09T00:00:00"},
            )
        assert resp.status_code == 200

    def test_invalid_since(self, app_client):
        """since 格式错误 → 400"""
        resp = app_client.get(
            "/api/cloud/sync/download",
            params={"since": "not-a-date"},
        )
        assert resp.status_code == 400
        assert "无效的时间格式" in resp.json()["detail"]

    def test_failure(self, app_client, mock_db):
        with patch.object(cloud_mod, "CloudSyncEngine") as MockEngine:
            inst = MockEngine.return_value
            inst.download_ratings = AsyncMock(return_value={
                "success": False, "error": "数据库异常",
                "timestamp": "2026-07-09T10:00:00",
            })
            resp = app_client.get("/api/cloud/sync/download")
        assert resp.status_code == 400
        assert "数据库异常" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════
# 8. GET /sync/status
# ══════════════════════════════════════════════════════════


class TestSyncStatus:
    def test_success(self, app_client, mock_db):
        with patch.object(cloud_mod, "CloudSyncEngine") as MockEngine:
            inst = MockEngine.return_value
            inst.get_sync_status = AsyncMock(return_value={
                "success": True, "last_sync": "2026-07-09T10:00:00",
                "upload_count": 1, "download_count": 2,
                "conflict_count": 0, "is_syncing": False,
            })
            resp = app_client.get("/api/cloud/sync/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["upload_count"] == 1

    def test_failure(self, app_client, mock_db):
        with patch.object(cloud_mod, "CloudSyncEngine") as MockEngine:
            inst = MockEngine.return_value
            inst.get_sync_status = AsyncMock(return_value={
                "success": False, "error": "查询失败",
            })
            resp = app_client.get("/api/cloud/sync/status")
        assert resp.status_code == 400
        assert "查询失败" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════
# 9. POST /sync/resolve
# ══════════════════════════════════════════════════════════


class TestSyncResolve:
    def test_invalid_resolution(self, app_client):
        """非法解决策略 → 400"""
        resp = app_client.post("/api/cloud/sync/resolve", json={
            "skill_id": "s1", "resolution": "invalid_strategy",
        })
        assert resp.status_code == 400
        assert "无效的解决策略" in resp.json()["detail"]

    def test_success(self, app_client, mock_db):
        with patch.object(cloud_mod, "CloudSyncEngine") as MockEngine:
            inst = MockEngine.return_value
            inst.resolve_conflict = AsyncMock(return_value={
                "success": True, "message": "冲突已解决",
            })
            resp = app_client.post("/api/cloud/sync/resolve", json={
                "skill_id": "s1", "resolution": "local_wins",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_failure(self, app_client, mock_db):
        with patch.object(cloud_mod, "CloudSyncEngine") as MockEngine:
            inst = MockEngine.return_value
            inst.resolve_conflict = AsyncMock(return_value={
                "success": False, "error": "评分不存在",
            })
            resp = app_client.post("/api/cloud/sync/resolve", json={
                "skill_id": "s1", "resolution": "remote_wins",
            })
        assert resp.status_code == 400
        assert "评分不存在" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════
# 10. GET /devices
# ══════════════════════════════════════════════════════════


class TestListDevices:
    def test_success(self, app_client, mock_db):
        with patch.object(cloud_mod, "CloudAuthService") as MockSvc:
            inst = MockSvc.return_value
            inst.get_user_devices = AsyncMock(return_value={
                "success": True, "devices": [{"device_id": "d1"}], "count": 1,
            })
            resp = app_client.get("/api/cloud/devices")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["count"] == 1

    def test_failure(self, app_client, mock_db):
        with patch.object(cloud_mod, "CloudAuthService") as MockSvc:
            inst = MockSvc.return_value
            inst.get_user_devices = AsyncMock(return_value={
                "success": False, "error": "查询失败",
            })
            resp = app_client.get("/api/cloud/devices")
        assert resp.status_code == 400
        assert "查询失败" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════
# 11. POST /devices/register
# ══════════════════════════════════════════════════════════


class TestRegisterDevice:
    def _setup_db_query(self, mock_db, found_existing=False, raise_exc=None):
        """配置 db.query 链式 mock"""
        query_mock = MagicMock()
        filter_mock = MagicMock()
        first_mock = MagicMock(return_value=MagicMock() if found_existing else None)
        filter_mock.first = first_mock
        query_mock.filter = MagicMock(return_value=filter_mock)
        mock_db.query = MagicMock(return_value=query_mock)
        if raise_exc:
            mock_db.add.side_effect = raise_exc
            mock_db.commit.side_effect = raise_exc
        return filter_mock

    def test_already_exists(self, app_client, mock_db):
        """设备已存在 → 返回 success=False"""
        self._setup_db_query(mock_db, found_existing=True)
        resp = app_client.post("/api/cloud/devices/register", json={
            "device_id": "d1", "device_name": "Laptop", "device_type": "desktop",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "设备已存在"

    def test_success(self, app_client, mock_db):
        """新设备注册成功"""
        self._setup_db_query(mock_db, found_existing=False)
        resp = app_client.post("/api/cloud/devices/register", json={
            "device_id": "d-new", "device_name": "Tablet", "device_type": "mobile",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["device_id"] == "d-new"
        assert data["message"] == "设备注册成功"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_exception(self, app_client, mock_db):
        """注册过程抛异常 → 400"""
        self._setup_db_query(mock_db, found_existing=False, raise_exc=RuntimeError("db"))
        resp = app_client.post("/api/cloud/devices/register", json={
            "device_id": "d2", "device_name": "Phone",
        })
        assert resp.status_code == 400
        assert "设备注册失败" in resp.json()["detail"]
        mock_db.rollback.assert_called()


# ══════════════════════════════════════════════════════════
# 12. DELETE /devices/{device_id}
# ══════════════════════════════════════════════════════════


class TestDeleteDevice:
    def _setup_db_query(self, mock_db, found=True, raise_exc=None):
        query_mock = MagicMock()
        filter_mock = MagicMock()
        first_mock = MagicMock(return_value=MagicMock() if found else None)
        filter_mock.first = first_mock
        query_mock.filter = MagicMock(return_value=filter_mock)
        mock_db.query = MagicMock(return_value=query_mock)
        if raise_exc:
            mock_db.delete.side_effect = raise_exc
            mock_db.commit.side_effect = raise_exc

    def test_not_found(self, app_client, mock_db):
        """设备不存在 → 404"""
        self._setup_db_query(mock_db, found=False)
        resp = app_client.delete("/api/cloud/devices/missing")
        assert resp.status_code == 404
        assert "设备不存在" in resp.json()["detail"]

    def test_success(self, app_client, mock_db):
        """删除成功"""
        self._setup_db_query(mock_db, found=True)
        resp = app_client.delete("/api/cloud/devices/d1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["message"] == "设备删除成功"
        mock_db.delete.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_exception(self, app_client, mock_db):
        """删除抛异常 → 400"""
        self._setup_db_query(mock_db, found=True, raise_exc=RuntimeError("db"))
        resp = app_client.delete("/api/cloud/devices/d1")
        assert resp.status_code == 400
        assert "设备删除失败" in resp.json()["detail"]
        mock_db.rollback.assert_called()
