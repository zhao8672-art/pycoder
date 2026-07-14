"""浏览器访问权限管理 — 域名白名单、速率限制、内容过滤

安全控制浏览器访问范围，防止恶意利用和内部网络探测。
"""
from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class BrowserAccessPolicy:
    """浏览器访问策略"""
    allowed_domains: list[str] = field(default_factory=lambda: [
        "github.com", "*.github.com", "python.org", "*.python.org", "pypi.org", "*.pypi.org",
        "docs.python.org", "npmjs.com", "*.npmjs.com", "rust-lang.org", "*.rust-lang.org",
        "stackoverflow.com", "*.stackoverflow.com", "wikipedia.org", "*.wikipedia.org",
    ])
    blocked_domains: list[str] = field(default_factory=list)
    max_requests_per_minute: int = 60
    max_content_size_mb: int = 10
    block_private_ips: bool = True


class BrowserAccessControl:
    """浏览器访问控制器

    用法:
        acl = BrowserAccessControl()
        ok, reason = acl.check_url("https://docs.python.org/3/")
        if not ok:
            raise PermissionError(reason)
    """

    def __init__(self, policy: BrowserAccessPolicy | None = None):
        self._policy = policy or BrowserAccessPolicy()
        self._rate_limiter: dict[str, list[float]] = {}

    def check_url(self, url: str) -> tuple[bool, str]:
        """检查 URL 是否允许访问

        Returns:
            (是否允许, 拒绝原因)
        """
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.hostname or ""

        if self._matches_any(domain, self._policy.blocked_domains):
            return False, f"域名 {domain} 在黑名单中"

        if self._policy.block_private_ips and self._is_private_ip(parsed.hostname):
            return False, "禁止访问内网地址"

        if not self._matches_any(domain, self._policy.allowed_domains):
            return False, f"域名 {domain} 不在白名单中"

        return True, ""

    def check_rate_limit(self, domain: str) -> bool:
        """检查速率限制"""
        now = time.time()
        window = now - 60
        if domain not in self._rate_limiter:
            self._rate_limiter[domain] = []
        self._rate_limiter[domain] = [
            t for t in self._rate_limiter[domain] if t > window
        ]
        if len(self._rate_limiter[domain]) >= self._policy.max_requests_per_minute:
            return False
        self._rate_limiter[domain].append(now)
        return True

    @staticmethod
    def _matches_any(domain: str, patterns: list[str]) -> bool:
        return any(fnmatch.fnmatch(domain, p) for p in patterns)

    @staticmethod
    def _is_private_ip(hostname: str | None) -> bool:
        if not hostname:
            return False
        import ipaddress
        try:
            ip = ipaddress.ip_address(hostname)
            return ip.is_private or ip.is_loopback or ip.is_link_local
        except ValueError:
            return False