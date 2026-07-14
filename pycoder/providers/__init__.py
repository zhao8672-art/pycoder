"""Providers: model registry, auth, cost tracking, and local inference."""

from pycoder.providers.auth import ModelManager, get_model_manager
from pycoder.providers.cost import BudgetManager, CostTracker, get_budget_manager, get_cost_tracker
from pycoder.providers.ollama_client import OllamaClient
from pycoder.providers.registry import (
    ALL_MODELS,
    ModelInfo,
    compare_models,
    get_all_models,
    get_model_info,
    get_models_by_provider,
    get_models_by_tag,
    get_provider_for_model,
    get_recommended_models,
)
from pycoder.providers.setup_wizard import check_all_keys, get_api_key, set_api_key

__all__ = [
    # registry
    "ALL_MODELS",
    "ModelInfo",
    "get_all_models",
    "get_model_info",
    "get_models_by_provider",
    "get_models_by_tag",
    "get_recommended_models",
    "get_provider_for_model",
    "compare_models",
    # auth
    "get_model_manager",
    "ModelManager",
    # cost
    "get_cost_tracker",
    "CostTracker",
    "get_budget_manager",
    "BudgetManager",
    # setup
    "get_api_key",
    "set_api_key",
    "check_all_keys",
    # local
    "OllamaClient",
]
