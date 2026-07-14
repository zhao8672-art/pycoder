"""CloudService 单元测试 — 覆盖 pycoder.server.services.cloud_service

覆盖:
- base64_encode / base64_decode
- register / login / verify_token / get_user_info
- check_quota / track_usage / get_usage_history
- add_api_key / list_api_keys / get_proxy_key
- get_plan_upgrade_info / upgrade_plan
- get_cloud_service 单例
每个测试使用独立 tmp DB，互不干扰。
"""
from __future__ import annotations

import time

import pytest

from pycoder.server.services import cloud_service as cs_module
from pycoder.server.services.cloud_service import (
    CloudService,
    CloudUser,
    ApiKeyPool,
    base64_decode,
    base64_encode,
    get_cloud_service,
)


# ── 工具函数 ───────────────────────────────────────────


class TestBase64Helpers:
    def test_encode_decode_roundtrip(self):
        original = "hello 你好 world"
        encoded = base64_encode(original)
        assert encoded != original
        assert base64_decode(encoded) == original

    def test_encode_empty(self):
        assert base64_encode("") == ""

    def test_decode_url_safe(self):
        # urlsafe base64 不含 + /
        encoded = base64_encode("a/b+c")
        assert "+" not in encoded
        assert "/" not in encoded


# ── 数据模型 ───────────────────────────────────────────


class TestDataModels:
    def test_cloud_user_defaults(self):
        u = CloudUser(id="1", username="alice")
        assert u.email == ""
        assert u.plan == "free"
        assert u.tokens_used_today == 0
        assert u.is_active is True

    def test_api_key_pool_defaults(self):
        k = ApiKeyPool(id="k1", provider="deepseek", api_key_encrypted="enc")
        assert k.tokens_used == 0
        assert k.is_active is True
        assert k.rate_limit == 60


# ── Fixture：每个测试一个独立 DB ───────────────────────


@pytest.fixture
def service(tmp_path, monkeypatch):
    """提供独立 DB 的 CloudService 实例。"""
    db_path = tmp_path / "cloud.db"
    monkeypatch.setattr(cs_module, "DB_PATH", db_path)
    monkeypatch.setattr(cs_module, "_service", None)
    # 强制新建实例（_get_conn 会读取 DB_PATH）
    svc = CloudService()
    yield svc
    # 关闭连接
    conn = getattr(svc._local, "conn", None)
    if conn:
        conn.close()


def _make_token(svc: CloudService, username: str = "alice") -> str:
    """注册并返回 token。"""
    result = svc.register(username, "password123", "alice@example.com")
    assert result["success"], result
    return result["token"]


# ── register ──────────────────────────────────────────


class TestRegister:
    def test_success(self, service):
        r = service.register("alice", "password123", "alice@example.com")
        assert r["success"] is True
        assert r["username"] == "alice"
        assert "token" in r
        assert r["plan"] == "free"
        assert len(r["user_id"]) == 12

    def test_short_username(self, service):
        r = service.register("ab", "password123")
        assert r["success"] is False
        assert "3" in r["error"]

    def test_short_password(self, service):
        r = service.register("alice", "12345")
        assert r["success"] is False
        assert "6" in r["error"]

    def test_duplicate_username(self, service):
        service.register("alice", "password123")
        r = service.register("alice", "password456")
        assert r["success"] is False
        assert "已存在" in r["error"]

    def test_no_email(self, service):
        r = service.register("bob", "password123")
        assert r["success"] is True


# ── login ─────────────────────────────────────────────


class TestLogin:
    def test_success(self, service):
        service.register("alice", "password123")
        r = service.login("alice", "password123")
        assert r["success"] is True
        assert r["username"] == "alice"
        assert "token" in r
        assert r["plan"] == "free"

    def test_user_not_found(self, service):
        r = service.login("ghost", "password123")
        assert r["success"] is False
        assert "不存在" in r["error"]

    def test_wrong_password(self, service):
        service.register("alice", "password123")
        r = service.login("alice", "wrongpassword")
        assert r["success"] is False
        assert "密码错误" in r["error"]


# ── verify_token ───────────────────────────────────────


class TestVerifyToken:
    def test_valid_token(self, service):
        token = _make_token(service)
        r = service.verify_token(token)
        assert r["valid"] is True
        assert "user_id" in r
        assert r["username"] == "alice"

    def test_wrong_format(self, service):
        r = service.verify_token("not-a-token")
        assert r["valid"] is False
        assert "格式" in r["error"]

    def test_three_parts_format(self, service):
        r = service.verify_token("a.b.c")
        assert r["valid"] is False
        assert "格式" in r["error"]

    def test_invalid_signature(self, service):
        token = _make_token(service)
        # 篡改签名
        payload, _sig = token.split(".")
        r = service.verify_token(f"{payload}.fakesignature")
        assert r["valid"] is False
        assert "签名" in r["error"]

    def test_expired_token(self, service):
        # 手动构造过期 token
        import json
        import hmac
        import hashlib
        payload = {
            "uid": "u1", "un": "alice",
            "iat": time.time() - 100,
            "exp": time.time() - 10,  # 已过期
        }
        payload_b64 = base64_encode(json.dumps(payload))
        sig = hmac.new(
            cs_module.JWT_SECRET_KEY.encode(),
            payload_b64.encode(),
            hashlib.sha256,
        ).hexdigest()
        r = service.verify_token(f"{payload_b64}.{sig}")
        assert r["valid"] is False
        assert "过期" in r["error"]

    def test_token_with_invalid_payload(self, service):
        # 签名正确但 payload 不是合法 JSON
        import hmac
        import hashlib
        payload_b64 = base64_encode("not json at all")
        sig = hmac.new(
            cs_module.JWT_SECRET_KEY.encode(),
            payload_b64.encode(),
            hashlib.sha256,
        ).hexdigest()
        r = service.verify_token(f"{payload_b64}.{sig}")
        assert r["valid"] is False


# ── get_user_info ──────────────────────────────────────


class TestGetUserInfo:
    def test_success(self, service):
        token = _make_token(service, "alice")
        r = service.get_user_info(token)
        assert r["success"] is True
        assert r["user"]["username"] == "alice"
        assert r["user"]["email"] == "alice@example.com"

    def test_invalid_token(self, service):
        r = service.get_user_info("bad-token")
        assert r["success"] is False

    def test_user_not_found(self, service):
        # 构造一个有效签名但用户不存在的 token
        import json
        import hmac
        import hashlib
        payload = {
            "uid": "nonexistent", "un": "ghost",
            "iat": time.time(), "exp": time.time() + 3600,
        }
        payload_b64 = base64_encode(json.dumps(payload))
        sig = hmac.new(
            cs_module.JWT_SECRET_KEY.encode(),
            payload_b64.encode(),
            hashlib.sha256,
        ).hexdigest()
        r = service.get_user_info(f"{payload_b64}.{sig}")
        assert r["success"] is False
        assert "不存在" in r["error"]


# ── check_quota ───────────────────────────────────────


class TestCheckQuota:
    def test_free_plan(self, service):
        token = _make_token(service)
        r = service.check_quota(token)
        assert r["success"] is True
        assert r["plan"] == "free"
        assert r["daily_limit"] == cs_module.FREE_DAILY_TOKENS
        assert r["used_today"] == 0
        assert r["remaining"] == cs_module.FREE_DAILY_TOKENS
        assert r["usage_pct"] == 0
        assert r["near_limit"] is False

    def test_pro_plan_limit(self, service):
        token = _make_token(service)
        service.upgrade_plan(token, "pro")
        r = service.check_quota(token)
        assert r["daily_limit"] == 1_000_000

    def test_team_plan_limit(self, service):
        token = _make_token(service)
        service.upgrade_plan(token, "team")
        r = service.check_quota(token)
        assert r["daily_limit"] == 10_000_000

    def test_invalid_token(self, service):
        r = service.check_quota("bad")
        assert r["success"] is False

    def test_near_limit_flag(self, service):
        token = _make_token(service)
        # 注入使用量到接近上限 (90%)
        user_info = service.verify_token(token)
        conn = service._get_conn()
        conn.execute(
            "UPDATE users SET tokens_used_today = ? WHERE id = ?",
            (int(cs_module.FREE_DAILY_TOKENS * 0.9), user_info["user_id"]),
        )
        conn.commit()
        r = service.check_quota(token)
        assert r["near_limit"] is True


# ── track_usage ───────────────────────────────────────


class TestTrackUsage:
    def test_success(self, service):
        token = _make_token(service)
        r = service.track_usage(token, "deepseek-chat", 100, 200)
        assert r["success"] is True
        # 再次查询配额确认累加
        quota = service.check_quota(token)
        assert quota["used_today"] == 300

    def test_invalid_token(self, service):
        r = service.track_usage("bad", "model", 1, 1)
        assert r["success"] is False

    def test_accumulates(self, service):
        token = _make_token(service)
        service.track_usage(token, "deepseek-chat", 100, 200)
        service.track_usage(token, "deepseek-chat", 50, 50)
        quota = service.check_quota(token)
        assert quota["used_today"] == 400


# ── get_usage_history ─────────────────────────────────


class TestGetUsageHistory:
    def test_empty_history(self, service):
        token = _make_token(service)
        r = service.get_usage_history(token)
        assert r["success"] is True
        assert r["total_tokens"] == 0
        assert r["request_count"] == 0
        assert r["by_model"] == {}

    def test_with_records(self, service):
        token = _make_token(service)
        service.track_usage(token, "deepseek-chat", 100, 200)
        service.track_usage(token, "qwen", 50, 50)
        r = service.get_usage_history(token)
        assert r["total_tokens"] == 400
        assert r["request_count"] == 2
        assert r["by_model"]["deepseek-chat"] == 300
        assert r["by_model"]["qwen"] == 100
        assert len(r["records"]) == 2

    def test_invalid_token(self, service):
        r = service.get_usage_history("bad")
        assert r["success"] is False


# ── API Key 池 ────────────────────────────────────────


class TestApiKeyPool:
    def test_add_api_key(self, service):
        r = service.add_api_key("deepseek", "sk-abc123")
        assert r["success"] is True
        assert r["provider"] == "deepseek"
        assert len(r["key_id"]) == 8

    def test_list_api_keys_empty(self, service):
        keys = service.list_api_keys()
        assert keys == []

    def test_list_api_keys(self, service):
        service.add_api_key("deepseek", "sk-abc123")
        service.add_api_key("qwen", "sk-xyz789")
        keys = service.list_api_keys()
        assert len(keys) == 2
        assert all("api_key_encrypted" not in k for k in keys)

    def test_get_proxy_key_found(self, service):
        add_r = service.add_api_key("deepseek", "sk-abc123")
        key_id = service.get_proxy_key("deepseek")
        assert key_id == add_r["key_id"]

    def test_get_proxy_key_not_found(self, service):
        assert service.get_proxy_key("glm") is None

    def test_get_proxy_key_increments_usage(self, service):
        add_r = service.add_api_key("deepseek", "sk-abc123")
        service.get_proxy_key("deepseek")
        service.get_proxy_key("deepseek")
        keys = service.list_api_keys()
        assert keys[0]["tokens_used"] == 2


# ── 套餐 ──────────────────────────────────────────────


class TestPlans:
    def test_get_plan_upgrade_info(self, service):
        plans = service.get_plan_upgrade_info()
        assert len(plans) == 3
        names = [p["name"] for p in plans]
        assert "free" in names
        assert "pro" in names
        assert "team" in names
        assert plans[0]["daily_tokens"] == cs_module.FREE_DAILY_TOKENS

    def test_upgrade_plan_success(self, service):
        token = _make_token(service)
        r = service.upgrade_plan(token, "pro")
        assert r["success"] is True
        assert r["plan"] == "pro"
        # 验证生效
        quota = service.check_quota(token)
        assert quota["plan"] == "pro"

    def test_upgrade_plan_invalid_token(self, service):
        r = service.upgrade_plan("bad", "pro")
        assert r["success"] is False

    def test_upgrade_plan_invalid_plan(self, service):
        token = _make_token(service)
        r = service.upgrade_plan(token, "enterprise")
        assert r["success"] is False
        assert "无效套餐" in r["error"]

    def test_upgrade_to_same_plan(self, service):
        token = _make_token(service)
        r = service.upgrade_plan(token, "free")
        assert r["success"] is True


# ── 单例 ─────────────────────────────────────────────


class TestSingleton:
    def test_get_cloud_service_caches(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cs_module, "DB_PATH", tmp_path / "cloud.db")
        monkeypatch.setattr(cs_module, "_service", None)
        a = get_cloud_service()
        b = get_cloud_service()
        assert a is b
        assert isinstance(a, CloudService)
