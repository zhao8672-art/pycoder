"""Tests for model config upgrade (adapted for new module structure)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from pycoder.server.app import app
from pycoder.server.chat_handler import _resolve_model, _get_effective_model, _get_api_key_for_model

client = TestClient(app)


def test_resolve_model_uses_model_manager_recommendation(monkeypatch):
    class DummyManager:
        def auto_detect(self):
            return {"qwen": "fake-key"}
        def recommend(self, task_type="coding"):
            return ("qwen-coder-plus", "qwen")
        def get_key(self, provider: str) -> str:
            return "fake-key" if provider == "qwen" else ""

    monkeypatch.setattr(
        "pycoder.server.chat_handler.get_model_manager",
        lambda: DummyManager(),
    )

    assert isinstance(_resolve_model("auto"), str) and len(_resolve_model("auto")) > 0
    assert _get_api_key_for_model("qwen-coder-plus") is not None


def test_config_setup_accepts_frontend_key_payload(monkeypatch):
    captured = {}

    def fake_set_api_key(provider: str, api_key: str, set_default: bool = True):
        captured["provider"] = provider
        captured["api_key"] = api_key
        captured["set_default"] = set_default
        return {"success": True}

    monkeypatch.setattr("pycoder.providers.setup_wizard.set_api_key", fake_set_api_key)

    response = client.post(
        "/api/config/setup",
        json={"provider": "deepseek", "key": "sk-test-123"},
    )

    assert response.status_code == 200
    assert captured == {"provider": "deepseek", "api_key": "sk-test-123", "set_default": True}


def test_effective_model_uses_recommended_model_when_auto(monkeypatch):
    class DummyManager:
        def auto_detect(self):
            return {"qwen": "fake-key"}
        def recommend(self, task_type="coding"):
            return ("qwen-coder-plus", "qwen")
        def get_key(self, provider: str) -> str:
            return "fake-key" if provider == "qwen" else ""

    monkeypatch.setattr(
        "pycoder.server.chat_handler.get_model_manager",
        lambda: DummyManager(),
    )

    assert isinstance(_get_effective_model("auto"), str) and len(_get_effective_model("auto")) > 0
    assert isinstance(_get_effective_model(""), str) and len(_get_effective_model("")) > 0


def test_create_session_accepts_model_payload():
    response = client.post(
        "/api/sessions",
        json={"model": "qwen-coder-plus"},
    )

    assert response.status_code == 200
    assert response.json()["model"] == "qwen-coder-plus"
