"""Tests for health API endpoints."""

from __future__ import annotations


def test_health_endpoint(client):
    """GET /api/health should return 200."""
    """GET /api/health should return 200 with status info."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "server_uptime" in data


def test_models_endpoint(client):
    """GET /api/models should return model list."""
    resp = client.get("/api/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "models" in data
    assert data["total"] > 0


def test_sessions_list(client):
    """GET /api/sessions should return session list."""
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert "sessions" in data


def test_env_endpoint(client):
    """GET /api/env should return environment info."""
    resp = client.get("/api/env")
    assert resp.status_code == 200
    data = resp.json()
    assert "python_version" in data
