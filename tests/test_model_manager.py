"""测试 ModelManager — 模型与 API Key 统一管理器

覆盖 pycoder.providers.auth.ModelManager 的核心功能：
- 单例获取
- 自动检测（环境变量 + 配置文件）
- 智能推荐
- 模型列表与元数据
- Key 检查与状态格式化
- 配置持久化
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

import pytest

from pycoder.providers.auth import (
    DEFAULT_FREE_MODEL,
    ModelManager,
    PROVIDER_DEFS,
    get_model_manager,
)
from pycoder.providers.registry import ALL_MODELS, ModelInfo


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """清除所有 provider 环境变量，避免污染测试"""
    for prov_defs in PROVIDER_DEFS.values():
        for env_var in prov_defs["env_vars"]:
            monkeypatch.delenv(env_var, raising=False)
    yield


@pytest.fixture
def isolated_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path, None, None]:
    """将配置文件指向临时目录，避免污染用户 ~/.pycoder/config.json"""
    config_file = tmp_path / "config.json"
    import pycoder.providers.auth as auth_module

    monkeypatch.setattr(auth_module, "_config_path", lambda: config_file)
    yield config_file


@pytest.fixture
def manager(clean_env: None, isolated_config: Path) -> ModelManager:
    """返回干净的 ModelManager 实例（隔离环境变量 + 配置文件）"""
    return ModelManager()


# ── 单例测试 ──────────────────────────────────────────────


class TestSingleton:
    def test_get_model_manager_returns_instance(self, clean_env: None):
        m = get_model_manager()
        assert isinstance(m, ModelManager)

    def test_get_model_manager_singleton(self, clean_env: None):
        m1 = get_model_manager()
        m2 = get_model_manager()
        assert m1 is m2


# ── 自动检测测试 ────────────────────────────────────────────


class TestAutoDetect:
    def test_no_keys_returns_empty(self, manager: ModelManager):
        detected = manager.auto_detect()
        assert detected == {}
        assert isinstance(detected, dict)

    def test_detects_env_var(self, manager: ModelManager, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-12345")
        detected = manager.auto_detect()
        assert "deepseek" in detected
        assert detected["deepseek"] == "sk-test-12345"

    def test_detects_multiple_providers(
        self, manager: ModelManager, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.setenv("GLM_API_KEY", "sk-glm")
        detected = manager.auto_detect()
        assert "deepseek" in detected
        assert "glm" in detected
        assert len(detected) == 2

    def test_first_env_var_wins(
        self, manager: ModelManager, monkeypatch: pytest.MonkeyPatch
    ):
        """同一 provider 的多个 env_var，第一个非空生效"""
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope")
        monkeypatch.setenv("QWEN_API_KEY", "sk-qwen")
        detected = manager.auto_detect()
        assert detected["qwen"] == "sk-dashscope"

    def test_detects_from_config_file(
        self, manager: ModelManager, isolated_config: Path
    ):
        import json

        isolated_config.write_text(
            json.dumps({"provider": {"api_keys": {"openai": "sk-openai-test"}}}),
            encoding="utf-8",
        )
        detected = manager.auto_detect()
        assert "openai" in detected
        assert detected["openai"] == "sk-openai-test"

    def test_env_var_takes_precedence_over_config(
        self, manager: ModelManager, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
    ):
        import json

        isolated_config.write_text(
            json.dumps({"provider": {"api_keys": {"deepseek": "from-config"}}}),
            encoding="utf-8",
        )
        monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")
        detected = manager.auto_detect()
        assert detected["deepseek"] == "from-env"


# ── 推荐测试 ──────────────────────────────────────────────


class TestRecommend:
    def test_no_keys_returns_default(self, manager: ModelManager):
        model, provider = manager.recommend()
        assert model == DEFAULT_FREE_MODEL
        assert provider == "deepseek"

    def test_returns_tuple_of_two_strings(self, manager: ModelManager):
        result = manager.recommend()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert all(isinstance(x, str) for x in result)

    def test_deepseek_highest_priority(
        self, manager: ModelManager, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        model, provider = manager.recommend()
        assert provider == "deepseek"
        assert model == "deepseek-chat"

    def test_cheap_task_prefers_glm(
        self, manager: ModelManager, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.setenv("GLM_API_KEY", "sk-glm")
        model, provider = manager.recommend(task_type="cheap")
        assert provider == "glm"

    def test_reasoning_task_prefers_deepseek_reasoner(
        self, manager: ModelManager, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        model, provider = manager.recommend(task_type="reasoning")
        assert model == "deepseek-reasoner"
        assert provider == "deepseek"


# ── 模型列表与元数据测试 ──────────────────────────────────


class TestModelListing:
    def test_get_available_models_returns_list(self, manager: ModelManager):
        models = manager.get_available_models()
        assert isinstance(models, list)
        assert len(models) > 0

    def test_each_model_has_required_fields(self, manager: ModelManager):
        models = manager.get_available_models()
        required_keys = {"id", "name", "provider", "available", "pricing", "context"}
        for m in models:
            assert required_keys.issubset(m.keys()), f"Missing keys in {m}"

    def test_get_model_info_known(self, manager: ModelManager):
        info = manager.get_model_info("deepseek-chat")
        assert info is not None
        assert isinstance(info, ModelInfo)
        assert info.provider == "deepseek"

    def test_get_model_info_unknown_returns_none(self, manager: ModelManager):
        assert manager.get_model_info("nonexistent-model-xyz") is None


# ── Key 检查测试 ───────────────────────────────────────────


class TestKeyChecking:
    def test_check_all_returns_all_providers(self, manager: ModelManager):
        result = manager.check_all()
        assert isinstance(result, dict)
        assert set(result.keys()) == set(PROVIDER_DEFS.keys())

    def test_check_all_no_keys_all_false(self, manager: ModelManager):
        result = manager.check_all()
        assert all(v is False for v in result.values())

    def test_check_all_with_key(self, manager: ModelManager, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GLM_API_KEY", "sk-glm")
        result = manager.check_all()
        assert result["glm"] is True
        assert result["deepseek"] is False

    def test_get_key_returns_empty_for_unknown(self, manager: ModelManager):
        assert manager.get_key("nonexistent") == ""

    def test_get_key_returns_detected(self, manager: ModelManager, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-xxx")
        manager.auto_detect()
        assert manager.get_key("deepseek") == "sk-ds-xxx"

    def test_get_all_keys_returns_dict(self, manager: ModelManager):
        keys = manager.get_all_keys()
        assert isinstance(keys, dict)


# ── 状态格式化测试 ──────────────────────────────────────────


class TestStatusFormatting:
    def test_format_status_returns_string(self, manager: ModelManager):
        status = manager.format_status()
        assert isinstance(status, str)
        assert len(status) > 0

    def test_format_status_contains_all_providers(self, manager: ModelManager):
        status = manager.format_status()
        for prov_defs in PROVIDER_DEFS.values():
            assert prov_defs["name"] in status

    def test_format_status_no_keys_shows_warning(self, manager: ModelManager):
        status = manager.format_status()
        assert "未检测到" in status or "未配置" in status

    def test_format_status_with_key_shows_recommendation(
        self, manager: ModelManager, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-12345abcdef")
        status = manager.format_status()
        assert "推荐模型" in status


# ── 配置持久化测试 ──────────────────────────────────────────


class TestConfigPersistence:
    def test_save_key_writes_config(
        self, manager: ModelManager, isolated_config: Path
    ):
        import json

        result = manager.save_key("glm", "sk-glm-saved")
        assert result["success"] is True
        assert isolated_config.exists()
        config = json.loads(isolated_config.read_text(encoding="utf-8"))
        assert config["provider"]["api_keys"]["glm"] == "sk-glm-saved"

    def test_save_key_sets_env_var(
        self, manager: ModelManager, isolated_config: Path
    ):
        manager.save_key("deepseek", "sk-from-save")
        assert os.environ.get("DEEPSEEK_API_KEY") == "sk-from-save"

    def test_save_key_unknown_provider_fails(
        self, manager: ModelManager, isolated_config: Path
    ):
        result = manager.save_key("unknown-provider", "sk-xxx")
        assert result["success"] is False
        assert "不支持" in result["error"]

    def test_get_saved_key_returns_persisted(
        self, manager: ModelManager, isolated_config: Path
    ):
        import json

        isolated_config.write_text(
            json.dumps({"provider": {"api_keys": {"qwen": "sk-qwen-persisted"}}}),
            encoding="utf-8",
        )
        assert manager.get_saved_key("qwen") == "sk-qwen-persisted"

    def test_get_saved_key_returns_empty_if_not_found(
        self, manager: ModelManager, isolated_config: Path
    ):
        assert manager.get_saved_key("nonexistent") == ""


# ── ALL_MODELS 一致性测试 ──────────────────────────────────


class TestRegistryConsistency:
    def test_all_models_non_empty(self):
        assert len(ALL_MODELS) > 0

    def test_registered_models_have_provider_in_defs(self):
        """反向一致性：ALL_MODELS 中每个模型的 provider 必须在 PROVIDER_DEFS 中定义"""
        for model_id, info in ALL_MODELS.items():
            assert info.provider in PROVIDER_DEFS, (
                f"Model {model_id} has provider={info.provider} "
                f"not defined in PROVIDER_DEFS"
            )

    def test_recommended_models_exist_in_registry(self):
        """正向一致性：每个 provider 的 recommended_model 必须在 ALL_MODELS 中注册"""
        for prov, defs in PROVIDER_DEFS.items():
            recommended = defs["recommended_model"]
            assert recommended in ALL_MODELS, (
                f"Provider {prov} recommends {recommended} but it's not in ALL_MODELS"
            )
            assert ALL_MODELS[recommended].provider == prov

    def test_default_free_model_exists(self):
        assert DEFAULT_FREE_MODEL in ALL_MODELS
