"""
OAuth2 第三方登录 — 在现有 JWT 认证基础上增加 OAuth2 支持

支持的提供商:
  - GitHub OAuth
  - Google OAuth
  - 可扩展的 Provider 注册机制

用法:
  from pycoder.server.auth.oauth2 import OAuth2Manager

  manager = OAuth2Manager()
  # GET /api/auth/oauth2/login/github → 重定向到 GitHub 授权页
  # GET /api/auth/oauth2/callback/github → 回调处理 → 返回 JWT
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from pycoder.server.auth.cloud_auth import (
    create_access_token,
    create_refresh_token,
)

logger = logging.getLogger(__name__)

# ── 状态存储（生产环境建议使用 Redis）──

_oauth_states: dict[str, dict[str, Any]] = {}  # state → {provider, created_at}
_oauth_state_ttl = 600  # 10 分钟


@dataclass
class OAuthProvider:
    """OAuth2 提供商配置"""
    name: str
    client_id: str
    client_secret: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scope: str = ""

    def get_redirect_uri(self) -> str:
        """获取回调 URL"""
        base = os.environ.get(
            "PYCODER_BASE_URL",
            "http://localhost:8423",
        )
        return f"{base}/api/auth/oauth2/callback/{self.name}"


# ── 内置提供商 ──


def _get_github_provider() -> OAuthProvider:
    return OAuthProvider(
        name="github",
        client_id=os.environ.get("GITHUB_OAUTH_CLIENT_ID", ""),
        client_secret=os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", ""),
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        userinfo_url="https://api.github.com/user",
        scope="user:email",
    )


def _get_google_provider() -> OAuthProvider:
    return OAuthProvider(
        name="google",
        client_id=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""),
        client_secret=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""),
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://www.googleapis.com/oauth2/v2/userinfo",
        scope="openid email profile",
    )


# ── OAuth2 管理器 ──


class OAuth2Manager:
    """OAuth2 认证管理器

    处理 OAuth2 授权码流程:
      1. 生成授权 URL → 重定向用户到提供商
      2. 接收回调 code → 交换 access_token
      3. 获取用户信息 → 生成 JWT
    """

    def __init__(self) -> None:
        self._providers: dict[str, OAuthProvider] = {}
        self._register_builtin_providers()
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))

    def _register_builtin_providers(self) -> None:
        """注册内置提供商"""
        github = _get_github_provider()
        if github.client_id:
            self._providers["github"] = github
            logger.info("OAuth2 提供商已注册: github")

        google = _get_google_provider()
        if google.client_id:
            self._providers["google"] = google
            logger.info("OAuth2 提供商已注册: google")

    def register_provider(self, provider: OAuthProvider) -> None:
        """注册自定义 OAuth2 提供商"""
        self._providers[provider.name] = provider
        logger.info("OAuth2 提供商已注册: %s", provider.name)

    def get_provider(self, name: str) -> OAuthProvider | None:
        """获取提供商配置"""
        return self._providers.get(name)

    def list_providers(self) -> list[str]:
        """列出可用提供商"""
        return list(self._providers.keys())

    def generate_authorize_url(self, provider_name: str) -> str | None:
        """生成授权 URL

        Args:
            provider_name: 提供商名称

        Returns:
            授权 URL，用户浏览器将重定向到此 URL
        """
        provider = self._providers.get(provider_name)
        if not provider:
            return None

        state = secrets.token_urlsafe(32)
        _oauth_states[state] = {
            "provider": provider_name,
            "created_at": time.time(),
        }

        params = {
            "client_id": provider.client_id,
            "redirect_uri": provider.get_redirect_uri(),
            "scope": provider.scope,
            "state": state,
            "response_type": "code",
        }

        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{provider.authorize_url}?{query}"

    async def handle_callback(
        self, provider_name: str, code: str, state: str
    ) -> dict[str, Any]:
        """处理 OAuth2 回调

        Args:
            provider_name: 提供商名称
            code: 授权码
            state: 状态参数

        Returns:
            {"jwt": "...", "user": {...}} 或 {"error": "..."}
        """
        # 验证 state
        state_data = _oauth_states.pop(state, None)
        if not state_data:
            return {"error": "invalid_state", "message": "无效的 state 参数"}
        if time.time() - state_data.get("created_at", 0) > _oauth_state_ttl:
            return {"error": "state_expired", "message": "state 已过期，请重新登录"}
        if state_data.get("provider") != provider_name:
            return {"error": "state_mismatch", "message": "state 提供商不匹配"}

        provider = self._providers.get(provider_name)
        if not provider:
            return {"error": "unknown_provider", "message": f"未知提供商: {provider_name}"}

        try:
            # 1. 交换 access_token
            token_resp = await self._client.post(
                provider.token_url,
                data={
                    "client_id": provider.client_id,
                    "client_secret": provider.client_secret,
                    "code": code,
                    "redirect_uri": provider.get_redirect_uri(),
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()
            access_token = token_data.get("access_token", "")

            if not access_token:
                return {"error": "no_access_token", "message": "未获取到 access_token"}

            # 2. 获取用户信息
            user_resp = await self._client.get(
                provider.userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            user_resp.raise_for_status()
            user_info = user_resp.json()

            # 3. 提取用户标识
            user_id = self._extract_user_id(provider_name, user_info)
            email = user_info.get("email", "")
            name = user_info.get("name", user_info.get("login", ""))

            # 4. 生成 JWT
            jwt_token = create_access_token(
                data={"sub": user_id, "email": email, "name": name, "provider": provider_name}
            )
            refresh_token = create_refresh_token(
                data={"sub": user_id, "provider": provider_name}
            )

            logger.info("OAuth2 登录成功: provider=%s user=%s", provider_name, user_id)

            return {
                "access_token": jwt_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "user": {
                    "id": user_id,
                    "email": email,
                    "name": name,
                    "provider": provider_name,
                },
            }

        except httpx.HTTPError as e:
            logger.error("OAuth2 回调失败: %s", e)
            return {"error": "http_error", "message": str(e)}

    def _extract_user_id(self, provider: str, user_info: dict) -> str:
        """从用户信息中提取唯一标识"""
        if provider == "github":
            return f"github:{user_info.get('id', '')}"
        elif provider == "google":
            return f"google:{user_info.get('id', '')}"
        return f"{provider}:{user_info.get('id', user_info.get('sub', ''))}"

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        await self._client.aclose()


# ── 全局单例 ──

_oauth2_manager: OAuth2Manager | None = None


def get_oauth2_manager() -> OAuth2Manager:
    """获取 OAuth2Manager 全局单例"""
    global _oauth2_manager
    if _oauth2_manager is None:
        _oauth2_manager = OAuth2Manager()
    return _oauth2_manager