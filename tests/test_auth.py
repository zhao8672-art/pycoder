"""Tests for provider auth."""

from __future__ import annotations

import os

import pytest
from pycoder.providers.auth import get_model_manager, ModelManager


def test_get_model_manager():
    mgr = get_model_manager()
    assert mgr is not None
    assert isinstance(mgr, ModelManager)


def test_manager_is_singleton():
    mgr1 = get_model_manager()
    mgr2 = get_model_manager()
    assert mgr1 is mgr2


def test_get_available_models():
    mgr = get_model_manager()
    models = mgr.get_available_models()
    assert isinstance(models, list)
    assert len(models) > 0
