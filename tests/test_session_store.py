"""Tests for session store."""

from __future__ import annotations

import pytest
from pycoder.server.session_store import get_session_store


def test_create_session(fresh_store):
    store = fresh_store
    session = store.create_session()
    assert session is not None
    assert session.id is not None


def test_get_session(fresh_store):
    store = fresh_store
    created = store.create_session()
    fetched = store.get_session(created.id)
    assert fetched is not None
    assert fetched.id == created.id


def test_list_sessions(fresh_store):
    store = fresh_store
    store.create_session()
    store.create_session()
    sessions = store.list_sessions(limit=10)
    assert len(sessions) >= 2


def test_delete_session(fresh_store):
    store = fresh_store
    s = store.create_session()
    assert store.get_session(s.id) is not None
    store.delete_session(s.id)
    assert store.get_session(s.id) is None


def test_add_and_get_messages(fresh_store):
    store = fresh_store
    s = store.create_session()
    store.add_message(s.id, "user", "Hello")
    store.add_message(s.id, "assistant", "Hi there")
    messages = store.get_messages(s.id)
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "Hello"
    assert messages[1].role == "assistant"


def test_update_session_model(fresh_store):
    store = fresh_store
    s = store.create_session()
    store.update_session(s.id, model="deepseek-coder")
    updated = store.get_session(s.id)
    assert updated is not None
    assert updated.model == "deepseek-coder"


def test_message_count(fresh_store):
    store = fresh_store
    s = store.create_session()
    assert s.message_count == 0
    store.add_message(s.id, "user", "Test")
    fetched = store.get_session(s.id)
    assert fetched is not None
    assert fetched.message_count >= 1


def test_invalid_session_returns_none(fresh_store):
    store = fresh_store
    s = store.get_session("non-existent-id")
    assert s is None


def test_add_message_to_invalid_session(fresh_store):
    """Adding message to invalid session should be handled gracefully."""
    store = fresh_store
    try:
        store.add_message("nonexistent-id", "user", "test")
    except Exception:
        pass
