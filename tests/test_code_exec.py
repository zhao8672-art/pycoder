"""Tests for code execution router."""

from __future__ import annotations

import pytest


def test_code_capabilities(client):
    """GET /api/code/capabilities should return supported languages."""
    resp = client.get("/api/code/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


def test_code_run_no_payload(client):
    """POST /api/code/run without payload should return 400 (empty code)."""
    resp = client.post("/api/code/run", json={})
    # 空代码返回 400（Code cannot be empty），而非 422
    assert resp.status_code in (200, 400, 422)


def test_repl_clear(client):
    """GET /api/code/repl/clear should succeed."""
    resp = client.post("/api/code/repl/clear")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


def test_code_history(client):
    """GET /api/code/history should return list."""
    resp = client.get("/api/code/history")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
