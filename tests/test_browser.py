"""browser 模块测试"""
from __future__ import annotations

import pytest
from pycoder.browser.access_control import BrowserAccessControl, BrowserAccessPolicy


class TestBrowserAccessControl:
    @pytest.fixture
    def acl(self):
        return BrowserAccessControl()

    def test_allowed_domain(self, acl):
        ok, reason = acl.check_url("https://docs.python.org/3/library/asyncio.html")
        assert ok, reason

    def test_allowed_domain_github(self, acl):
        ok, reason = acl.check_url("https://github.com/python/cpython")
        assert ok, reason

    def test_blocked_domain(self, acl):
        ok, reason = acl.check_url("https://evil-site.com/malware")
        assert not ok
        assert "不在白名单" in reason

    def test_blocked_domain_custom(self):
        policy = BrowserAccessPolicy(blocked_domains=["*.evil.com"])
        acl = BrowserAccessControl(policy)
        ok, reason = acl.check_url("https://sub.evil.com/test")
        assert not ok
        assert "黑名单" in reason

    def test_private_ip_blocked(self, acl):
        ok, reason = acl.check_url("http://192.168.1.1/admin")
        assert not ok
        assert "内网" in reason

    def test_localhost_blocked(self, acl):
        ok, reason = acl.check_url("http://127.0.0.1:8080/api")
        assert not ok
        assert "内网" in reason

    def test_rate_limit(self, acl):
        acl._policy.max_requests_per_minute = 3
        domain = "docs.python.org"
        for _ in range(3):
            assert acl.check_rate_limit(domain) is True
        assert acl.check_rate_limit(domain) is False

    def test_rate_limit_reset_after_window(self, acl):
        acl._policy.max_requests_per_minute = 2
        domain = "github.com"
        acl._rate_limiter[domain] = [100.0]  # 过期时间戳
        assert acl.check_rate_limit(domain) is True  # 过期记录被清理

    def test_allow_public_ip(self, acl):
        policy = BrowserAccessPolicy(
            allowed_domains=["8.8.8.8"],
            block_private_ips=False,
        )
        acl2 = BrowserAccessControl(policy)
        ok, reason = acl2.check_url("http://8.8.8.8/")
        assert ok, reason

    def test_wildcard_domain_match(self, acl):
        ok, reason = acl.check_url("https://www.python.org/")
        assert ok, reason

    def test_pypi_allowed(self, acl):
        ok, reason = acl.check_url("https://pypi.org/project/requests/")
        assert ok, reason


class TestBrowserAccessPolicy:
    def test_default_policy(self):
        policy = BrowserAccessPolicy()
        assert "*.github.com" in policy.allowed_domains
        assert policy.max_requests_per_minute == 60
        assert policy.block_private_ips is True

    def test_custom_policy(self):
        policy = BrowserAccessPolicy(
            allowed_domains=["custom.com"],
            max_requests_per_minute=30,
            block_private_ips=False,
        )
        assert policy.allowed_domains == ["custom.com"]
        assert policy.max_requests_per_minute == 30
        assert policy.block_private_ips is False