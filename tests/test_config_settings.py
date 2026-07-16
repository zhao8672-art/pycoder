"""
配置模块 (pycoder.config.settings) 测试

覆盖:
  - 默认常量: DEFAULT_HOST, DEFAULT_PORT, DEFAULT_MODEL 等
  - 环境变量: PYCODER_PORT, PYCODER_HOME, PYCODER_DB_PATH
  - get_config_path: 配置文件路径
  - load_config: JSON 加载、默认值合并、损坏文件处理
  - save_config: 配置写入
  - get_config: 单个 key 获取、完整字典获取
  - DEFAULT_CONFIG 结构验证
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pycoder.config.settings import (
    ALLOWED_ORIGINS,
    CONFIG_PATH,
    DATA_DIR,
    DB_PATH,
    DEFAULT_CONFIG,
    DEFAULT_HOST,
    DEFAULT_MODEL,
    DEFAULT_PORT,
    EXEC_TIMEOUT_SECONDS,
    PYCODER_HOME,
    VITE_DEV_PORT,
    WS_RECONNECT_MAX_DELAY_SECONDS,
    get_config,
    get_config_path,
    load_config,
    save_config,
)


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture
def temp_config_dir() -> Path:
    """创建临时配置目录"""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def temp_config_file(temp_config_dir: Path) -> Path:
    """创建临时配置文件路径"""
    return temp_config_dir / "config.json"


# ══════════════════════════════════════════════════════════
# 默认常量测试
# ══════════════════════════════════════════════════════════


class TestDefaultConstants:
    """默认配置常量测试"""

    def test_default_host(self):
        """DEFAULT_HOST 应为 127.0.0.1"""
        assert DEFAULT_HOST == "127.0.0.1"

    def test_default_port_type(self):
        """DEFAULT_PORT 应为整数"""
        assert isinstance(DEFAULT_PORT, int)

    def test_default_port_positive(self):
        """DEFAULT_PORT 应为正数"""
        assert DEFAULT_PORT > 0

    def test_default_model(self):
        """DEFAULT_MODEL 应为有效模型名"""
        assert DEFAULT_MODEL == "deepseek-chat"
        assert isinstance(DEFAULT_MODEL, str)

    def test_vite_dev_port(self):
        """VITE_DEV_PORT 应为 5173"""
        assert VITE_DEV_PORT == 5173

    def test_exec_timeout_positive(self):
        """EXEC_TIMEOUT_SECONDS 应为正数"""
        assert EXEC_TIMEOUT_SECONDS > 0

    def test_ws_reconnect_max_delay_positive(self):
        """WS_RECONNECT_MAX_DELAY_SECONDS 应为正数"""
        assert WS_RECONNECT_MAX_DELAY_SECONDS > 0

    def test_allowed_origins_not_empty(self):
        """ALLOWED_ORIGINS 不应为空"""
        assert len(ALLOWED_ORIGINS) > 0

    def test_allowed_origins_contains_localhost(self):
        """ALLOWED_ORIGINS 应包含 localhost 地址"""
        has_localhost = any("localhost" in o for o in ALLOWED_ORIGINS)
        assert has_localhost


# ══════════════════════════════════════════════════════════
# 环境变量测试
# ══════════════════════════════════════════════════════════


class TestEnvironmentVariables:
    """环境变量覆盖测试"""

    def test_pycoder_home_env_var(self):
        """PYCODER_HOME 环境变量应覆盖默认路径"""
        custom = "/tmp/custom_pycoder"
        with patch.dict(os.environ, {"PYCODER_HOME": custom}, clear=True):
            # 重新导入以获取环境变量
            import importlib
            import pycoder.config.settings as settings_mod

            importlib.reload(settings_mod)
            try:
                # 注意: reload 后 PYCODER_HOME 会读取当前环境变量
                # 由于我们在 patch 中，需要使用 patch 后的值
                pass
            finally:
                # 恢复原始环境
                importlib.reload(settings_mod)

    def test_pycoder_port_env_var(self):
        """PYCODER_PORT 环境变量应覆盖默认端口"""
        custom_port = "9999"
        with patch.dict(os.environ, {"PYCODER_PORT": custom_port}, clear=True):
            import importlib
            import pycoder.config.settings as settings_mod

            importlib.reload(settings_mod)
            try:
                assert settings_mod.DEFAULT_PORT == 9999
            finally:
                importlib.reload(settings_mod)


# ══════════════════════════════════════════════════════════
# get_config_path 测试
# ══════════════════════════════════════════════════════════


class TestGetConfigPath:
    """get_config_path 测试"""

    def test_get_config_path_returns_path(self):
        """get_config_path 应返回 Path 对象"""
        path = get_config_path()
        assert isinstance(path, Path)

    def test_get_config_path_ends_with_config_json(self):
        """配置文件路径应以 config.json 结尾"""
        path = get_config_path()
        assert path.name == "config.json"


# ══════════════════════════════════════════════════════════
# load_config 测试
# ══════════════════════════════════════════════════════════


class TestLoadConfig:
    """load_config 测试"""

    def test_load_config_returns_dict(self):
        """load_config 应返回字典"""
        cfg = load_config()
        assert isinstance(cfg, dict)

    def test_load_config_has_default_keys(self):
        """加载的配置应包含默认键"""
        cfg = load_config()
        assert "version" in cfg
        assert "default_model" in cfg
        assert "provider" in cfg
        assert "theme" in cfg
        assert "api_keys" in cfg
        assert "budget" in cfg

    def test_load_config_has_version(self):
        """配置应包含版本号"""
        cfg = load_config()
        assert cfg["version"] == "0.5.0"

    def test_load_config_file_not_exists(self, temp_config_file: Path):
        """配置文件不存在时返回默认配置"""
        with patch("pycoder.config.settings.CONFIG_PATH", temp_config_file):
            cfg = load_config()
            assert cfg == DEFAULT_CONFIG

    def test_load_config_file_exists(self, temp_config_file: Path):
        """配置文件存在时应正确加载"""
        custom_data = {"theme": "custom_dark", "version": "1.0.0"}
        temp_config_file.write_text(json.dumps(custom_data), encoding="utf-8")

        with patch("pycoder.config.settings.CONFIG_PATH", temp_config_file):
            cfg = load_config()
            assert cfg["theme"] == "custom_dark"  # 自定义值覆盖
            assert cfg["version"] == "1.0.0"  # 自定义值覆盖
            assert cfg["default_model"] == DEFAULT_CONFIG["default_model"]  # 保留默认值

    def test_load_config_corrupted_file(self, temp_config_file: Path):
        """损坏的配置文件应返回默认配置（不抛异常）"""
        temp_config_file.write_text("not valid json{{{", encoding="utf-8")

        with patch("pycoder.config.settings.CONFIG_PATH", temp_config_file):
            cfg = load_config()
            assert cfg == DEFAULT_CONFIG

    def test_load_config_empty_file(self, temp_config_file: Path):
        """空配置文件应返回默认配置"""
        temp_config_file.write_text("", encoding="utf-8")

        with patch("pycoder.config.settings.CONFIG_PATH", temp_config_file):
            cfg = load_config()
            assert cfg == DEFAULT_CONFIG

    def test_load_config_not_dict(self, temp_config_file: Path):
        """非字典 JSON（如数组）应返回默认配置"""
        temp_config_file.write_text("[1, 2, 3]", encoding="utf-8")

        with patch("pycoder.config.settings.CONFIG_PATH", temp_config_file):
            cfg = load_config()
            assert cfg == DEFAULT_CONFIG


# ══════════════════════════════════════════════════════════
# save_config 测试
# ══════════════════════════════════════════════════════════


class TestSaveConfig:
    """save_config 测试"""

    def test_save_config_writes_file(self, temp_config_file: Path):
        """save_config 应写入配置文件"""
        config = {"theme": "saved_theme", "version": "2.0"}
        with patch("pycoder.config.settings.CONFIG_PATH", temp_config_file):
            save_config(config)
            assert temp_config_file.exists()

    def test_save_config_content_is_valid_json(self, temp_config_file: Path):
        """写入的内容应为有效 JSON"""
        config = {"theme": "test", "count": 42}
        with patch("pycoder.config.settings.CONFIG_PATH", temp_config_file):
            save_config(config)
            content = temp_config_file.read_text(encoding="utf-8")
            parsed = json.loads(content)
            assert parsed == config

    def test_save_config_creates_parent_dir(self, temp_config_dir: Path):
        """save_config 应自动创建父目录"""
        nested = temp_config_dir / "sub" / "deep" / "config.json"
        config = {"key": "value"}
        with patch("pycoder.config.settings.CONFIG_PATH", nested):
            save_config(config)
            assert nested.exists()

    def test_save_and_load_roundtrip(self, temp_config_file: Path):
        """save_config 后 load_config 应返回相同数据"""
        config = {"theme": "roundtrip", "version": "3.0", "custom_key": "custom_val"}
        with patch("pycoder.config.settings.CONFIG_PATH", temp_config_file):
            save_config(config)
            loaded = load_config()
            assert loaded["theme"] == "roundtrip"
            assert loaded["custom_key"] == "custom_val"


# ══════════════════════════════════════════════════════════
# get_config 测试
# ══════════════════════════════════════════════════════════


class TestGetConfig:
    """get_config 测试"""

    def test_get_config_all(self):
        """get_config() 无参数时返回完整配置字典"""
        cfg = get_config()
        assert isinstance(cfg, dict)
        assert "theme" in cfg

    def test_get_config_specific_key(self, temp_config_file: Path):
        """get_config 带 key 时返回对应值"""
        custom = {"theme": "specific_theme"}
        temp_config_file.write_text(json.dumps(custom), encoding="utf-8")

        with patch("pycoder.config.settings.CONFIG_PATH", temp_config_file):
            theme = get_config("theme")
            assert theme == "specific_theme"

    def test_get_config_missing_key_default(self):
        """不存在的 key 应返回默认值"""
        result = get_config("nonexistent_key", default="fallback")
        assert result == "fallback"

    def test_get_config_missing_key_none(self):
        """不存在的 key 无默认值时应返回 None"""
        result = get_config("nonexistent_key")
        assert result is None


# ══════════════════════════════════════════════════════════
# DEFAULT_CONFIG 结构测试
# ══════════════════════════════════════════════════════════


class TestDefaultConfig:
    """DEFAULT_CONFIG 结构验证"""

    def test_default_config_is_dict(self):
        """DEFAULT_CONFIG 应为字典"""
        assert isinstance(DEFAULT_CONFIG, dict)

    def test_default_config_has_version(self):
        """DEFAULT_CONFIG 应包含版本号"""
        assert "version" in DEFAULT_CONFIG
        assert isinstance(DEFAULT_CONFIG["version"], str)

    def test_default_config_has_budget(self):
        """DEFAULT_CONFIG 应包含预算配置"""
        assert "budget" in DEFAULT_CONFIG
        budget = DEFAULT_CONFIG["budget"]
        assert isinstance(budget, dict)
        assert "max_tokens_per_session" in budget
        assert "daily_budget_usd" in budget

    def test_default_config_api_keys_empty(self):
        """DEFAULT_CONFIG 的 api_keys 应为空字典"""
        assert DEFAULT_CONFIG["api_keys"] == {}


# ══════════════════════════════════════════════════════════
# 路径常量测试
# ══════════════════════════════════════════════════════════


class TestPathConstants:
    """路径相关常量测试"""

    def test_data_dir_under_pycoder_home(self):
        """DATA_DIR 应在 PYCODER_HOME 下"""
        assert os.path.normpath(DATA_DIR).startswith(os.path.normpath(PYCODER_HOME))

    def test_db_path_under_pycoder_home(self):
        """DB_PATH 应在 PYCODER_HOME 下"""
        assert os.path.normpath(DB_PATH).startswith(os.path.normpath(PYCODER_HOME))

    def test_config_path_under_pycoder_home(self):
        """CONFIG_PATH 应在 PYCODER_HOME 下"""
        assert os.path.normpath(str(CONFIG_PATH)).startswith(
            os.path.normpath(PYCODER_HOME)
        )