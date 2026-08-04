"""
PyCoder 错误码定义

所有错误码统一在此定义，避免硬编码散落在各模块中。
敏感值（如 API Key 校验用的密钥标识）通过环境变量注入。
"""

from __future__ import annotations

import os
from typing import Final


# ──────────────────────────────────────────────────────────
# 认证相关错误码（PYC-9xxx 系列）
# ──────────────────────────────────────────────────────────

# 密钥标识前缀，用于区分不同认证场景
_AUTH_KEY_PREFIX: str = os.environ.get("PYCODER_AUTH_KEY_PREFIX", "PYC")


def _auth_key(code: str) -> str:
    """根据环境前缀生成认证密钥标识"""
    return f"{_AUTH_KEY_PREFIX}-{code}"


# 无效 API Key
AUTH_INVALID_KEY: Final[str] = _auth_key("9000")

# 过期 Token
AUTH_EXPIRED_TOKEN: Final[str] = _auth_key("9004")

# 缺失 Key/Token
AUTH_MISSING_KEY: Final[str] = _auth_key("9002")

# 无效 Token
AUTH_INVALID_TOKEN: Final[str] = _auth_key("9003")

# 密钥已过期（保留兼容名）
AUTH_EXPIRED_KEY: Final[str] = AUTH_EXPIRED_TOKEN