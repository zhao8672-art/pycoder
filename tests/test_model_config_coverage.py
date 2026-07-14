"""覆盖率测试: pycoder/python/model_config.py

目标: 行覆盖率 >= 80%

覆盖范围:
- ModelInfo / ProviderInfo / ModelConfig 数据类
- CacheEntry / SimpleCache 缓存机制
- cached 装饰器与 invalidate_cache
- MODEL_REGISTRY 注册表一致性
- 配置目录与文件路径函数
- 加密 / 解密（_load_key / _encrypt_string / _decrypt_string）
- load_config / save_config
- API Key 管理（get_api_key / set_api_key / check_all_keys）
- 模型查询（get_all_models / get_models_for_provider / ...）
- 默认模型管理（get_default_model / set_default_model）
- 模型参数配置（get_model_config / save_model_config / update_model_config）
- 智能模型选择（suggest_model）

测试策略:
- 使用 monkeypatch 重定向 get_config_dir 到 tmp_path，避免污染 ~/.pycoder
- 使用 monkeypatch.delenv 清理环境变量
- 不依赖网络与外部进程
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Generator

import pytest

from pycoder.python import model_config as mc
from pycoder.python.model_config import (
    MODEL_REGISTRY,
    ModelConfig,
    ModelInfo,
    ProviderInfo,
    SimpleCache,
    CacheEntry,
    cached,
    invalidate_cache,
    get_config_dir,
    get_config_path,
    get_key_path,
    load_config,
    save_config,
    get_api_key,
    set_api_key,
    check_all_keys,
    get_all_models,
    get_models_for_provider,
    get_model_info,
    get_provider_for_model,
    get_recommended_models,
    get_models_by_capability,
    get_default_model,
    set_default_model,
    get_model_config,
    save_model_config,
    update_model_config,
    suggest_model,
)


# ── 公共 fixtures ──────────────────────────────────────────


@pytest.fixture
def isolated_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path, None, None]:
    """重定向 get_config_dir 到临时目录"""
    config_dir = tmp_path / ".pycoder"
    monkeypatch.setattr(mc, "get_config_dir", lambda: config_dir)
    # 缓存失效，避免跨测试污染
    invalidate_cache()
    yield config_dir
    invalidate_cache()


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """清除所有 provider 环境变量"""
    for provider_info in MODEL_REGISTRY.values():
        monkeypatch.delenv(provider_info.env_name, raising=False)
        if provider_info.key_name != provider_info.env_name:
            monkeypatch.delenv(provider_info.key_name, raising=False)
    yield


@pytest.fixture
def isolated_env(isolated_config_dir: Path, clean_env: None) -> Generator[Path, None, None]:
    """组合 fixture: 隔离配置目录 + 清理环境变量"""
    yield isolated_config_dir


# ── 数据类测试 ─────────────────────────────────────────────


class TestDataclasses:
    def test_model_info_defaults(self):
        m = ModelInfo(
            id="m1",
            name="M1",
            provider="prov",
            context_window=4096,
            max_tokens=1024,
        )
        assert m.input_price == 0.0
        assert m.output_price == 0.0
        assert m.capabilities == []
        assert m.recommended is False
        assert m.description == ""

    def test_provider_info_defaults(self):
        p = ProviderInfo(id="p", name="P", key_name="K", env_name="E")
        assert p.base_url == ""
        assert p.api_version == ""
        assert p.register_url == ""
        assert p.docs_url == ""
        assert p.pricing_page == ""
        assert p.models == []
        assert p.free_trial == ""
        assert p.price_summary == ""

    def test_model_config_defaults(self):
        c = ModelConfig()
        assert c.temperature == 0.7
        assert c.max_tokens == 4096
        assert c.top_p == 0.95
        assert c.frequency_penalty == 0.0
        assert c.presence_penalty == 0.0
        assert c.stop == []
        assert c.system_prompt == ""

    def test_model_config_custom(self):
        c = ModelConfig(temperature=0.1, max_tokens=100, system_prompt="hello")
        assert c.temperature == 0.1
        assert c.max_tokens == 100
        assert c.system_prompt == "hello"


# ── 缓存机制测试 ─────────────────────────────────────────


class TestCacheEntry:
    def test_not_expired_initially(self):
        entry = CacheEntry("data", ttl=100)
        assert entry.is_expired() is False

    def test_expired_after_ttl(self):
        entry = CacheEntry("data", ttl=0.01)
        # 修改 created_at 使其过期
        entry.created_at = time.time() - 1
        assert entry.is_expired() is True


class TestSimpleCache:
    def test_set_and_get(self):
        cache = SimpleCache()
        cache.set("k1", "v1")
        assert cache.get("k1") == "v1"

    def test_get_missing_returns_none(self):
        cache = SimpleCache()
        assert cache.get("missing") is None

    def test_get_expired_returns_none_and_clears(self):
        cache = SimpleCache()
        cache.set("k1", "v1", ttl=0.01)
        # 模拟时间流逝
        cache._cache["k1"].created_at = time.time() - 10
        assert cache.get("k1") is None
        assert "k1" not in cache._cache

    def test_clear_all(self):
        cache = SimpleCache()
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.clear()
        assert cache.keys() == []

    def test_clear_single_key(self):
        cache = SimpleCache()
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.clear("k1")
        assert "k1" not in cache.keys()
        assert "k2" in cache.keys()

    def test_keys(self):
        cache = SimpleCache()
        cache.set("a", 1)
        cache.set("b", 2)
        assert set(cache.keys()) == {"a", "b"}


class TestCachedDecorator:
    def test_cached_returns_value(self):
        @cached(ttl=100)
        def add(a, b):
            return a + b

        assert add(1, 2) == 3

    def test_cached_caches_result(self):
        call_count = {"n": 0}

        @cached(ttl=100)
        def expensive():
            call_count["n"] += 1
            return "result"

        r1 = expensive()
        r2 = expensive()
        assert r1 == r2 == "result"
        assert call_count["n"] == 1

    def test_cached_different_args_separate(self):
        @cached(ttl=100)
        def add(a, b):
            return a + b

        assert add(1, 2) == 3
        assert add(3, 4) == 7

    def test_invalidate_cache_clears(self):
        call_count = {"n": 0}

        @cached(ttl=100)
        def func():
            call_count["n"] += 1
            return "x"

        func()
        func()
        assert call_count["n"] == 1
        invalidate_cache()
        func()
        assert call_count["n"] == 2


# ── 注册表测试 ─────────────────────────────────────────────


class TestModelRegistry:
    def test_registry_has_expected_providers(self):
        expected = {"deepseek", "qwen", "glm", "openai", "anthropic", "google"}
        assert set(MODEL_REGISTRY.keys()) == expected

    def test_each_provider_has_models(self):
        for pid, info in MODEL_REGISTRY.items():
            assert len(info.models) > 0, f"Provider {pid} has no models"

    def test_each_provider_models_have_provider_field(self):
        for pid, info in MODEL_REGISTRY.items():
            for model in info.models:
                assert model.provider == pid

    def test_at_least_one_recommended_per_provider(self):
        for pid, info in MODEL_REGISTRY.items():
            assert any(m.recommended for m in info.models), (
                f"Provider {pid} has no recommended model"
            )


# ── 配置目录与文件路径测试 ─────────────────────────────────


class TestConfigPaths:
    def test_get_config_dir_default(self, monkeypatch):
        # 不打补丁时返回 ~/.pycoder
        result = get_config_dir()
        assert result.name == ".pycoder"

    def test_get_config_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mc, "get_config_dir", lambda: tmp_path)
        result = get_config_path()
        assert result == tmp_path / "config.json"

    def test_get_key_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mc, "get_config_dir", lambda: tmp_path)
        result = get_key_path()
        assert result == tmp_path / "secret.key"


# ── 加密 / 解密测试 ─────────────────────────────────────────


class TestEncryption:
    def test_encrypt_and_decrypt_roundtrip(self, isolated_config_dir: Path):
        original = "sk-test-secret-key-12345"
        encrypted = mc._encrypt_string(original)
        assert encrypted != original
        decrypted = mc._decrypt_string(encrypted)
        assert decrypted == original

    def test_decrypt_invalid_returns_none(self, isolated_config_dir: Path):
        # 使用无效的加密字符串
        result = mc._decrypt_string("not-a-valid-encrypted-string")
        assert result is None

    def test_decrypt_with_wrong_key_returns_none(
        self, isolated_config_dir: Path, monkeypatch
    ):
        # 加密后更换密钥再解密
        original = "sk-test-secret"
        encrypted = mc._encrypt_string(original)
        # 生成新密钥并写入
        new_key = mc._generate_key()
        key_path = get_key_path()
        key_path.write_bytes(new_key)
        result = mc._decrypt_string(encrypted)
        assert result is None

    def test_load_key_creates_new(self, isolated_config_dir: Path):
        key_path = get_key_path()
        assert not key_path.exists()
        key = mc._load_key()
        assert key
        assert key_path.exists()
        assert key_path.read_bytes() == key

    def test_load_key_existing(self, isolated_config_dir: Path):
        # 预先创建目录与密钥文件
        key_path = get_key_path()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(mc._generate_key())
        key1 = mc._load_key()
        key2 = mc._load_key()
        assert key1 == key2


# ── 配置文件读写测试 ─────────────────────────────────────────


class TestConfigLoadSave:
    def test_load_config_missing_returns_empty(self, isolated_config_dir: Path):
        assert load_config() == {}

    def test_save_and_load_config(self, isolated_config_dir: Path):
        cfg = {"a": 1, "b": "hello"}
        save_config(cfg)
        loaded = load_config()
        assert loaded == cfg

    def test_load_config_broken_json_returns_empty(self, isolated_config_dir: Path):
        config_path = get_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("not valid json {", encoding="utf-8")
        assert load_config() == {}

    def test_load_config_os_error_returns_empty(
        self, isolated_config_dir: Path, monkeypatch
    ):
        # 模拟 OSError（先创建可读文件，再让 open 抛错）
        config_path = get_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("{}", encoding="utf-8")

        real_open = open

        def raise_oserror(file, *args, **kwargs):
            if file == str(config_path):
                raise OSError("simulated")
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr("builtins.open", raise_oserror)
        assert load_config() == {}

    def test_save_config_creates_dir(self, tmp_path: Path, monkeypatch):
        # 配置目录不存在时创建
        nested = tmp_path / "a" / "b" / "c"
        monkeypatch.setattr(mc, "get_config_dir", lambda: nested)
        monkeypatch.setattr(mc, "get_config_path", lambda: nested / "config.json")
        save_config({"x": 1})
        assert nested.exists()
        assert (nested / "config.json").exists()


# ── API Key 管理测试 ───────────────────────────────────────


class TestApiKeyManagement:
    def test_get_api_key_unknown_provider(self, isolated_env: Path):
        assert get_api_key("nonexistent-provider") is None

    def test_get_api_key_from_env(self, isolated_env: Path, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env")
        assert get_api_key("deepseek") == "sk-from-env"

    def test_get_api_key_from_key_name_when_env_name_missing(
        self, isolated_env: Path, monkeypatch
    ):
        # qwen 的 key_name != env_name
        monkeypatch.setenv("QWEN_API_KEY", "sk-qwen-alt")
        assert get_api_key("qwen") == "sk-qwen-alt"

    def test_get_api_key_env_name_takes_precedence(
        self, isolated_env: Path, monkeypatch
    ):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-primary")
        monkeypatch.setenv("QWEN_API_KEY", "sk-secondary")
        assert get_api_key("qwen") == "sk-primary"

    def test_get_api_key_from_config(self, isolated_env: Path):
        # 加密存储后从配置读取
        encrypted = mc._encrypt_string("sk-from-config")
        save_config({"provider": {"api_keys": {"openai": encrypted}}})
        invalidate_cache()
        assert get_api_key("openai") == "sk-from-config"

    def test_get_api_key_returns_encrypted_if_decrypt_fails(
        self, isolated_env: Path, monkeypatch
    ):
        # 配置中有加密 key，但解密失败时返回原加密字符串
        save_config({"provider": {"api_keys": {"openai": "invalid-encrypted"}}})
        invalidate_cache()
        result = get_api_key("openai")
        assert result == "invalid-encrypted"

    def test_set_api_key_unknown_provider(self, isolated_env: Path):
        result = set_api_key("nonexistent", "sk-xxx")
        assert result["success"] is False
        assert "不支持" in result["message"]

    def test_set_api_key_valid_provider(self, isolated_env: Path, monkeypatch):
        # 防止 env var 持久化
        result = set_api_key("deepseek", "sk-test-12345")
        assert result["success"] is True
        assert result["provider"] == "deepseek"
        # 验证已写入配置文件（加密）
        config = load_config()
        assert "deepseek" in config["provider"]["api_keys"]
        assert config["provider"]["api_keys"]["deepseek"] != "sk-test-12345"
        # 验证 env var 已设置
        assert os.environ.get("DEEPSEEK_API_KEY") == "sk-test-12345"

    def test_set_api_key_without_setting_default(
        self, isolated_env: Path, monkeypatch
    ):
        # 预设 default 防止被覆盖
        save_config({"provider": {"default": "glm"}})
        result = set_api_key("deepseek", "sk-test", set_default=False)
        assert result["success"] is True
        config = load_config()
        # default 应保持不变
        assert config["provider"].get("default") == "glm"

    def test_set_api_key_sets_default(self, isolated_env: Path):
        result = set_api_key("glm", "sk-glm-test", set_default=True)
        assert result["success"] is True
        config = load_config()
        assert config["provider"]["default"] == "glm"


class TestCheckAllKeys:
    def test_no_keys_configured(self, isolated_env: Path):
        status = check_all_keys()
        assert set(status.keys()) == set(MODEL_REGISTRY.keys())
        for pid, info in status.items():
            assert info["configured"] is False
            assert info["key_preview"] == "N/A"

    def test_with_env_var(self, isolated_env: Path, monkeypatch):
        # 设置一个长 key 用于测试 preview
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-1234567890abcdef")
        status = check_all_keys()
        assert status["deepseek"]["configured"] is True
        # preview 应该是前 8 + ... + 后 4
        assert status["deepseek"]["key_preview"].startswith("sk-12345")
        assert "..." in status["deepseek"]["key_preview"]

    def test_short_key_preview(self, isolated_env: Path, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "short")
        status = check_all_keys()
        # 长度 <= 12，应返回 N/A
        assert status["deepseek"]["key_preview"] == "N/A"
        assert status["deepseek"]["configured"] is True


# ── 模型查询测试 ─────────────────────────────────────────


class TestModelQueries:
    def test_get_all_models(self, isolated_env: Path):
        models = get_all_models()
        assert len(models) > 0
        # 应包含所有 provider 的模型
        total = sum(len(p.models) for p in MODEL_REGISTRY.values())
        assert len(models) == total

    def test_get_all_models_cached(self, isolated_env: Path):
        m1 = get_all_models()
        m2 = get_all_models()
        # 应返回缓存的对象（同一引用）
        assert m1 is m2

    def test_get_models_for_provider_valid(self, isolated_env: Path):
        models = get_models_for_provider("deepseek")
        assert len(models) > 0
        for m in models:
            assert m.provider == "deepseek"

    def test_get_models_for_provider_invalid(self, isolated_env: Path):
        assert get_models_for_provider("nonexistent") == []

    def test_get_model_info_found(self, isolated_env: Path):
        info = get_model_info("deepseek-chat")
        assert info is not None
        assert info.id == "deepseek-chat"

    def test_get_model_info_not_found(self, isolated_env: Path):
        assert get_model_info("nonexistent-model") is None

    def test_get_provider_for_model_found(self, isolated_env: Path):
        provider = get_provider_for_model("gpt-4o")
        assert provider is not None
        assert provider.id == "openai"

    def test_get_provider_for_model_not_found(self, isolated_env: Path):
        assert get_provider_for_model("nonexistent") is None

    def test_get_recommended_models(self, isolated_env: Path):
        recs = get_recommended_models()
        assert len(recs) > 0
        assert all(m.recommended for m in recs)

    def test_get_models_by_capability(self, isolated_env: Path):
        vision_models = get_models_by_capability("vision")
        assert len(vision_models) > 0
        for m in vision_models:
            assert "vision" in m.capabilities

    def test_get_models_by_capability_empty(self, isolated_env: Path):
        # 不存在的能力
        result = get_models_by_capability("nonexistent-capability")
        assert result == []


# ── 默认模型管理测试 ─────────────────────────────────────


class TestDefaultModel:
    def test_get_default_model_no_config(self, isolated_env: Path):
        result = get_default_model()
        # deepseek 的推荐模型
        assert result == "deepseek-chat"

    def test_get_default_model_from_config(self, isolated_env: Path):
        save_config(
            {
                "provider": {
                    "default": "openai",
                    "default_model": "gpt-4o-mini",
                }
            }
        )
        invalidate_cache()
        assert get_default_model() == "gpt-4o-mini"

    def test_get_default_model_invalid_config_falls_back(self, isolated_env: Path):
        # 配置中 default_model 不存在时，回退到 provider 的推荐模型
        save_config(
            {
                "provider": {
                    "default": "openai",
                    "default_model": "nonexistent-model",
                }
            }
        )
        invalidate_cache()
        result = get_default_model()
        # openai 的推荐模型是 gpt-4o
        assert result == "gpt-4o"

    def test_get_default_model_invalid_provider_falls_back(self, isolated_env: Path):
        save_config({"provider": {"default": "nonexistent-provider"}})
        invalidate_cache()
        # 回退到 deepseek-chat
        assert get_default_model() == "deepseek-chat"

    def test_set_default_model_unknown(self, isolated_env: Path):
        result = set_default_model("nonexistent-model")
        assert result["success"] is False
        assert "不存在" in result["message"]

    def test_set_default_model_valid(self, isolated_env: Path):
        result = set_default_model("gpt-4o")
        assert result["success"] is True
        assert result["model"] == "gpt-4o"
        config = load_config()
        assert config["provider"]["default"] == "openai"
        assert config["provider"]["default_model"] == "gpt-4o"


# ── 模型参数配置测试 ─────────────────────────────────────


class TestModelConfigParams:
    def test_get_model_config_defaults(self, isolated_env: Path):
        cfg = get_model_config()
        assert isinstance(cfg, ModelConfig)
        assert cfg.temperature == 0.7
        assert cfg.max_tokens == 4096

    def test_get_model_config_from_config(self, isolated_env: Path):
        save_config(
            {
                "model_config": {
                    "temperature": 0.1,
                    "max_tokens": 100,
                    "top_p": 0.5,
                    "frequency_penalty": 0.5,
                    "presence_penalty": 0.5,
                    "stop": ["END"],
                    "system_prompt": "You are a helpful assistant",
                }
            }
        )
        cfg = get_model_config()
        assert cfg.temperature == 0.1
        assert cfg.max_tokens == 100
        assert cfg.top_p == 0.5
        assert cfg.frequency_penalty == 0.5
        assert cfg.presence_penalty == 0.5
        assert cfg.stop == ["END"]
        assert cfg.system_prompt == "You are a helpful assistant"

    def test_save_model_config(self, isolated_env: Path):
        cfg = ModelConfig(temperature=0.5, max_tokens=200, system_prompt="hi")
        save_model_config(cfg)
        loaded = load_config()
        assert loaded["model_config"]["temperature"] == 0.5
        assert loaded["model_config"]["max_tokens"] == 200
        assert loaded["model_config"]["system_prompt"] == "hi"

    def test_update_model_config(self, isolated_env: Path):
        result = update_model_config(temperature=0.2, max_tokens=500)
        assert result["success"] is True
        assert result["config"]["temperature"] == 0.2
        assert result["config"]["max_tokens"] == 500

    def test_update_model_config_with_system_prompt(self, isolated_env: Path):
        long_prompt = "x" * 100
        result = update_model_config(system_prompt=long_prompt)
        assert result["success"] is True
        # 长度 > 50 的 prompt 在返回时会被截断
        assert result["config"]["system_prompt"].endswith("...")
        assert len(result["config"]["system_prompt"]) <= 53  # 50 + "..."

    def test_update_model_config_short_system_prompt(self, isolated_env: Path):
        result = update_model_config(system_prompt="short")
        assert result["success"] is True
        # 短 prompt 仍会被附加 "..." 后缀
        assert result["config"]["system_prompt"] == "short..."

    def test_update_model_config_empty_system_prompt(self, isolated_env: Path):
        result = update_model_config(system_prompt="")
        assert result["success"] is True
        # 空 prompt 应返回空字符串
        assert result["config"]["system_prompt"] == ""

    def test_update_model_config_ignores_unknown_keys(self, isolated_env: Path):
        result = update_model_config(unknown_key="ignored", temperature=0.9)
        assert result["success"] is True
        assert result["config"]["temperature"] == 0.9


# ── 智能模型选择测试 ─────────────────────────────────────


class TestSuggestModel:
    def test_no_keys_returns_default(self, isolated_env: Path):
        # 无 key 时返回默认
        result = suggest_model("chat")
        assert result == "deepseek-chat"

    def test_chat_task(self, isolated_env: Path, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        result = suggest_model("chat")
        # 应该返回 deepseek 的推荐模型
        assert result == "deepseek-chat"

    def test_code_task(self, isolated_env: Path, monkeypatch):
        monkeypatch.setenv("GLM_API_KEY", "sk-glm")
        result = suggest_model("code")
        # 应该返回带 code 能力的最低价模型
        info = get_model_info(result)
        assert info is not None
        assert "code" in info.capabilities

    def test_vision_task(self, isolated_env: Path, monkeypatch):
        monkeypatch.setenv("GLM_API_KEY", "sk-glm")
        result = suggest_model("vision")
        info = get_model_info(result)
        assert info is not None
        assert "vision" in info.capabilities

    def test_long_task_no_match(self, isolated_env: Path, monkeypatch):
        # 仅配置 deepseek，但 deepseek 没有 1M 上下文模型
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        result = suggest_model("long")
        # 无候选时返回 default
        assert result == get_default_model()

    def test_long_task_with_match(self, isolated_env: Path, monkeypatch):
        # google 有 1M 上下文模型
        monkeypatch.setenv("GOOGLE_API_KEY", "sk-google")
        result = suggest_model("long")
        info = get_model_info(result)
        assert info is not None
        assert info.context_window >= 1000000

    def test_unknown_task_uses_chat_branch(self, isolated_env: Path, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        result = suggest_model("unknown-task")
        # 走 else 分支，应返回 deepseek-chat
        assert result == "deepseek-chat"

    def test_default_task_type(self, isolated_env: Path, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        # 不传 task_type，默认 "chat"
        result = suggest_model()
        assert result == "deepseek-chat"


# ── suggest_model 全分支覆盖测试 ─────────────────────────


class TestSuggestModelBranches:
    def test_code_task_picks_cheapest(self, isolated_env: Path, monkeypatch):
        # 配置 deepseek 和 glm，应选价格最低的 code 模型
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.setenv("GLM_API_KEY", "sk-glm")
        result = suggest_model("code")
        info = get_model_info(result)
        assert info is not None
        assert "code" in info.capabilities
        # glm-4.7-flash 是免费的，应优先返回
        assert result == "glm-4.7-flash"

    def test_vision_task_picks_cheapest(self, isolated_env: Path, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.setenv("GLM_API_KEY", "sk-glm")
        result = suggest_model("vision")
        info = get_model_info(result)
        assert info is not None
        assert "vision" in info.capabilities


# ── 集成测试 ─────────────────────────────────────────────


class TestIntegration:
    def test_full_workflow(self, isolated_env: Path, monkeypatch):
        """完整工作流：设置 key -> 选择默认模型 -> 更新配置"""
        # 1. 设置 API key
        result = set_api_key("glm", "sk-glm-1234567890")
        assert result["success"] is True

        # 2. 验证 key 可读
        key = get_api_key("glm")
        assert key == "sk-glm-1234567890"

        # 3. 设置默认模型
        result = set_default_model("glm-4.7-flash")
        assert result["success"] is True

        # 4. 获取默认模型
        assert get_default_model() == "glm-4.7-flash"

        # 5. 更新模型参数
        result = update_model_config(temperature=0.5, max_tokens=2048)
        assert result["success"] is True

        # 6. 验证配置持久化
        cfg = get_model_config()
        assert cfg.temperature == 0.5
        assert cfg.max_tokens == 2048

    def test_check_all_keys_after_setup(self, isolated_env: Path, monkeypatch):
        set_api_key("deepseek", "sk-deepseek-1234567890")
        status = check_all_keys()
        assert status["deepseek"]["configured"] is True
        assert status["openai"]["configured"] is False
