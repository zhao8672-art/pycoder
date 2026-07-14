"""
Unified configuration settings for PyCoder.
Single source of truth for all configurable values.
"""

from __future__ import annotations

import json
import os

# Server
DEFAULT_HOST: str = "127.0.0.1"
DEFAULT_PORT: int = int(os.environ.get("PYCODER_PORT", "8423"))

# Vite dev server (Electron dev mode)
VITE_DEV_PORT: int = 5173

# CORS allowed origins
ALLOWED_ORIGINS: list[str] = [
    f"http://localhost:{DEFAULT_PORT}",
    f"http://127.0.0.1:{DEFAULT_PORT}",
    f"http://localhost:{VITE_DEV_PORT}",
    f"http://127.0.0.1:{VITE_DEV_PORT}",
    "file://",
]

# Default model
DEFAULT_MODEL: str = "deepseek-chat"

# Data paths
PYCODER_HOME: str = os.environ.get(
    "PYCODER_HOME",
    os.path.expanduser("~/.pycoder"),
)
DATA_DIR: str = os.path.join(PYCODER_HOME, "data")
DB_PATH: str = os.path.join(PYCODER_HOME, "sessions.db")

# Timeouts
EXEC_TIMEOUT_SECONDS: int = 30
WS_RECONNECT_MAX_DELAY_SECONDS: int = 30

# ── 配置持久化（供 pycoder.config 包导出 get_config/load_config/save_config） ──
from pathlib import Path  # noqa: E402

CONFIG_PATH: Path = Path(PYCODER_HOME) / "config.json"

DEFAULT_CONFIG: dict = {
    "version": "0.5.0",
    "default_model": DEFAULT_MODEL,
    "provider": {"default": "auto"},
    "theme": "tokyo_night",
    "api_keys": {},
    "budget": {
        "max_tokens_per_session": 100000,
        "daily_budget_usd": 5.0,
    },
}


def get_config_path() -> Path:
    """返回配置文件路径（~/.pycoder/config.json）。"""
    return CONFIG_PATH


def load_config() -> dict:
    """读取 JSON 配置并与 DEFAULT_CONFIG 浅合并；文件不存在/损坏时返回默认配置。"""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as _f:
                data = json.load(_f)
            if isinstance(data, dict):
                return {**DEFAULT_CONFIG, **data}
        except (json.JSONDecodeError, OSError) as _cfg_err:
            import logging as _lg
            _lg.getLogger(__name__).warning(
                "config_load_failed path=%s error=%s",
                CONFIG_PATH, _cfg_err,
            )
    return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    """将配置写入 ~/.pycoder/config.json。"""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as _f:
        json.dump(config, _f, ensure_ascii=False, indent=2)


def get_config(key: str | None = None, default: object | None = None) -> object:
    """
    获取配置。

    - 不带参数：返回完整配置字典。
    - 带 key：返回 config[key]，缺失时返回 default。
    """
    cfg = load_config()
    if key is None:
        return cfg
    return cfg.get(key, default)
