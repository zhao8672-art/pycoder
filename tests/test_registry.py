"""Tests for model registry."""

from __future__ import annotations

import pytest
from pycoder.providers.registry import (
    ALL_MODELS,
    ModelInfo,
    get_all_models,
    get_model_info,
    get_models_by_provider,
    get_models_by_tag,
    get_recommended_models,
    get_provider_for_model,
    compare_models,
)


def test_all_models_not_empty():
    assert len(ALL_MODELS) > 0


def test_model_info_structure():
    model = ALL_MODELS.get("deepseek-chat")
    assert model is not None
    assert isinstance(model, ModelInfo)
    assert model.id == "deepseek-chat"
    assert model.provider == "deepseek"
    assert model.pricing_input > 0
    assert model.context_window > 0


def test_get_model_info():
    """Get model info returns ModelInfo object."""
    info = get_model_info("deepseek-chat")
    assert info is not None
    assert info.id == "deepseek-chat"


def test_models_by_provider():
    models = get_models_by_provider("deepseek")
    assert len(models) > 0
    assert all(m.provider == "deepseek" for m in models)


def test_models_by_tag():
    models = get_models_by_tag("coding")
    assert len(models) > 0
    assert all("coding" in m.tags for m in models)


def test_recommended_models():
    models = get_recommended_models()
    assert len(models) > 0


def test_get_provider_for_model():
    provider = get_provider_for_model("deepseek-chat")
    assert hasattr(provider, "name") and provider.name == "deepseek"


def test_compare_models():
    comparison = compare_models(model_ids=["deepseek-chat", "deepseek-coder"])
    assert len(comparison) == 2


def test_unknown_model_returns_none():
    info = get_model_info("non-existent-model")
    assert info is None
