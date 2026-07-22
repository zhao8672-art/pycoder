"""P0-2: 持久化记忆引擎单元测试"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pycoder.memory.persistent_memory import (
    PersistentMemoryEngine,
    ProjectMemory,
    UserMemory,
    get_persistent_memory,
    is_sensitive_key,
    is_sensitive_value,
    sanitize_dict,
)


class TestSensitiveDetection:
    def test_sensitive_keys(self):
        assert is_sensitive_key("api_key")
        assert is_sensitive_key("api-key")
        assert is_sensitive_key("API_KEY")
        assert is_sensitive_key("password")
        assert is_sensitive_key("token")
        assert is_sensitive_key("secret")
        assert is_sensitive_key("private_key")
        assert is_sensitive_key("access_key")
        assert is_sensitive_key("credentials")

    def test_non_sensitive_keys(self):
        assert not is_sensitive_key("name")
        assert not is_sensitive_key("language")
        assert not is_sensitive_key("framework")
        assert not is_sensitive_key("style")

    def test_sensitive_values(self):
        assert is_sensitive_value("sk-15fb337194194e6981f0d0afa3b890db")
        assert is_sensitive_value("sk-ant-api03-1234567890abcdef")
        assert is_sensitive_value("ghp_1234567890abcdefghij")

    def test_non_sensitive_values(self):
        assert not is_sensitive_value("hello")
        assert not is_sensitive_value("python")
        assert not is_sensitive_value("")


class TestSanitize:
    def test_redact_sensitive_key(self):
        data = {"api_key": "sk-1234567890abcdef", "name": "test"}
        result = sanitize_dict(data)
        assert result["api_key"] == "[REDACTED]"
        assert result["name"] == "test"

    def test_redact_sensitive_value(self):
        data = {"token": "sk-1234567890abcdef"}
        result = sanitize_dict(data)
        assert result["token"] == "[REDACTED]"

    def test_nested_dict(self):
        data = {
            "user": {
                "name": "alice",
                "api_key": "sk-1234567890abcdef",
                "settings": {"password": "secret123long"},
            }
        }
        result = sanitize_dict(data)
        assert result["user"]["name"] == "alice"
        assert result["user"]["api_key"] == "[REDACTED]"
        assert result["user"]["settings"]["password"] == "[REDACTED]"

    def test_list_of_dicts(self):
        data = {"items": [{"api_key": "sk-1234567890abcdef"}, {"name": "x"}]}
        result = sanitize_dict(data)
        assert result["items"][0]["api_key"] == "[REDACTED]"
        assert result["items"][1]["name"] == "x"

    def test_depth_limit(self):
        data = {"a": {"b": {"c": {"d": {"e": {"f": "deep"}}}}}}
        result = sanitize_dict(data, _depth=0)
        # 不应该栈溢出
        assert "a" in result

    def test_no_false_positive(self):
        data = {
            "language": "python",
            "frameworks": ["fastapi", "pytest"],
            "test_count": 42,
        }
        result = sanitize_dict(data)
        assert result["language"] == "python"
        assert result["frameworks"] == ["fastapi", "pytest"]


class TestUserMemory:
    def test_default(self):
        u = UserMemory()
        assert u.user_id == "default"
        assert u.response_language == "zh"

    def test_to_dict(self):
        u = UserMemory(user_id="alice", preferred_language="python")
        d = u.to_dict()
        assert d["user_id"] == "alice"
        assert d["preferred_language"] == "python"

    def test_from_dict_filters_sensitive(self):
        data = {
            "user_id": "alice",
            "preferred_language": "python",
            "api_key": "sk-1234567890abcdef",
        }
        u = UserMemory.from_dict(data)
        assert u.preferred_language == "python"
        # api_key 被移到 custom 但已被脱敏
        assert u.custom.get("api_key") == "[REDACTED]"

    def test_from_dict_extra_fields_to_custom(self):
        data = {"user_id": "alice", "favorite_color": "blue"}
        u = UserMemory.from_dict(data)
        assert u.custom.get("favorite_color") == "blue"


class TestProjectMemory:
    def test_default(self):
        p = ProjectMemory()
        assert p.primary_language == ""
        assert p.frameworks == []

    def test_to_from_dict(self):
        p = ProjectMemory(
            project_name="pycoder",
            primary_language="python",
            frameworks=["fastapi", "pytest"],
        )
        data = p.to_dict()
        p2 = ProjectMemory.from_dict(data)
        assert p2.project_name == "pycoder"
        assert p2.primary_language == "python"
        assert p2.frameworks == ["fastapi", "pytest"]


class TestPersistentMemoryEngine:
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.user_dir = Path(self.tmp.name) / "user"
        self.project_dir = Path(self.tmp.name) / "project"

    def teardown_method(self):
        self.tmp.cleanup()

    def test_init_creates_defaults(self):
        engine = PersistentMemoryEngine(project_root=self.project_dir)
        engine._user_dir = self.user_dir
        engine._user_path = self.user_dir / "user_profile.json"
        engine._project_path = self.project_dir / ".pycoder" / "project_memory.json"
        engine.load()
        u = engine.get_user_memory()
        assert u.user_id == "default"

    def test_save_and_load_user(self):
        engine = PersistentMemoryEngine(project_root=self.project_dir)
        engine._user_dir = self.user_dir
        engine._user_path = self.user_dir / "user_profile.json"
        engine._project_path = self.project_dir / ".pycoder" / "project_memory.json"
        engine.load()
        engine.update_user(preferred_language="python", testing_framework="pytest")
        assert engine.save_user()

        # 重新加载
        engine2 = PersistentMemoryEngine(project_root=self.project_dir)
        engine2._user_dir = self.user_dir
        engine2._user_path = self.user_dir / "user_profile.json"
        engine2._project_path = self.project_dir / ".pycoder" / "project_memory.json"
        engine2.load()
        u = engine2.get_user_memory()
        assert u.preferred_language == "python"
        assert u.testing_framework == "pytest"

    def test_update_user_redacts_sensitive(self):
        engine = PersistentMemoryEngine(project_root=self.project_dir)
        engine._user_dir = self.user_dir
        engine._user_path = self.user_dir / "user_profile.json"
        engine._project_path = None
        engine.load()
        engine.update_user(api_key="sk-1234567890abcdef")
        assert engine.save_user()
        # 文件中应该被脱敏
        data = json.loads(engine._user_path.read_text(encoding="utf-8"))
        assert data.get("api_key") == "[REDACTED]" or data["custom"].get("api_key") == "[REDACTED]"

    def test_update_project(self):
        engine = PersistentMemoryEngine(project_root=self.project_dir)
        engine._user_dir = self.user_dir
        engine._user_path = self.user_dir / "user_profile.json"
        engine._project_path = self.project_dir / ".pycoder" / "project_memory.json"
        engine.load()
        engine.update_project(primary_language="python", frameworks=["fastapi"])
        assert engine.save_project()
        assert engine._project_path.is_file()

    def test_build_context_prompt(self):
        engine = PersistentMemoryEngine(project_root=self.project_dir)
        engine._user_dir = self.user_dir
        engine._user_path = self.user_dir / "user_profile.json"
        engine._project_path = self.project_dir / ".pycoder" / "project_memory.json"
        engine.load()
        engine.update_user(preferred_language="python", testing_framework="pytest")
        engine.update_project(primary_language="python", frameworks=["fastapi", "pytest"])
        prompt = engine.build_context_prompt()
        assert "持久化记忆" in prompt
        assert "python" in prompt
        assert "pytest" in prompt

    def test_no_project(self):
        engine = PersistentMemoryEngine(project_root=None)
        engine._user_dir = self.user_dir
        engine._user_path = self.user_dir / "user_profile.json"
        engine._project_path = None
        engine.load()
        assert engine.get_project_memory() is None
        assert engine.save_project() is False

    def test_get_persistent_memory_singleton(self):
        with patch("pycoder.memory.persistent_memory._engine", None):
            e1 = get_persistent_memory(Path(self.tmp.name))
            e2 = get_persistent_memory()
            assert e1 is e2
