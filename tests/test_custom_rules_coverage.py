"""覆盖率测试: pycoder/server/custom_rules.py

目标: 行覆盖率 >= 95%

覆盖内容:
  - CustomRulesEngine: load / save / add_rule / remove_rule / list_rules
    check_file (regex/ast/filename 分支, 文件不存在, 读取失败, 规则禁用)
    check_project / get_templates
  - get_rules_engine 单例

测试策略:
  - 用 monkeypatch 替换 _storage 为 tmp_path 下文件避免污染用户家目录
  - 创建真实临时 .py 文件作为 check_file/check_project 的目标
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pycoder.server import custom_rules as cr_mod
from pycoder.server.custom_rules import (
    CustomRulesEngine,
    get_rules_engine,
)


# ── 工厂: 创建带 tmp_path 存储的 CustomRulesEngine ────────

def _make_engine(tmp_path: Path) -> CustomRulesEngine:
    """创建 CustomRulesEngine，存储路径指向 tmp_path"""
    storage = tmp_path / "rules.json"
    # 直接构造实例并替换 _storage，避免触发 __init__ 中的 load()
    e = CustomRulesEngine.__new__(CustomRulesEngine)
    e._rules = []
    e._storage = storage
    return e


# ══════════════════════════════════════════════════════════
# load / save
# ══════════════════════════════════════════════════════════

class TestLoadSave:
    def test_load_nonexistent(self, tmp_path):
        e = _make_engine(tmp_path)
        # 不抛异常 — 文件不存在
        e.load()
        assert e._rules == []

    def test_load_valid(self, tmp_path):
        e = _make_engine(tmp_path)
        # 先保存规则
        e._rules = [
            {"id": "CR001", "name": "rule1", "pattern": "print", "type": "regex",
             "severity": "warning", "message": "msg", "enabled": True},
        ]
        e.save()

        # 新实例加载
        e2 = _make_engine(tmp_path)
        e2.load()
        assert len(e2._rules) == 1
        assert e2._rules[0]["name"] == "rule1"

    def test_load_corrupt_json(self, tmp_path):
        """损坏的 JSON → 静默捕获异常，_rules 置空"""
        e = _make_engine(tmp_path)
        e._storage.parent.mkdir(parents=True, exist_ok=True)
        e._storage.write_text("not-json{", encoding="utf-8")
        e.load()
        assert e._rules == []

    def test_load_os_error(self, tmp_path, monkeypatch):
        """OSError → 静默捕获"""
        e = _make_engine(tmp_path)
        e._storage.parent.mkdir(parents=True, exist_ok=True)
        e._storage.write_text("[]", encoding="utf-8")
        # mock read_text 抛 OSError
        def boom(*a, **k):
            raise OSError("disk err")
        monkeypatch.setattr(Path, "read_text", boom)
        e.load()
        assert e._rules == []

    def test_load_value_error(self, tmp_path):
        """read_text 抛 ValueError（实际 json.loads 抛 ValueError 也归为 JSONDecodeError）"""
        e = _make_engine(tmp_path)
        e._storage.parent.mkdir(parents=True, exist_ok=True)
        # JSONDecodeError 是 ValueError 子类
        e._storage.write_text("123abc", encoding="utf-8")
        e.load()
        assert e._rules == []

    def test_save_creates_parent_dir(self, tmp_path):
        """save 应自动创建父目录"""
        e = _make_engine(tmp_path)
        e._storage = tmp_path / "deep" / "nested" / "rules.json"
        e._rules = [{"id": "CR001", "name": "r"}]
        e.save()
        assert e._storage.exists()

    def test_save_writes_json(self, tmp_path):
        e = _make_engine(tmp_path)
        e._rules = [{"id": "CR001", "name": "rule1"}]
        e.save()
        data = json.loads(e._storage.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["id"] == "CR001"


# ══════════════════════════════════════════════════════════
# add_rule / remove_rule / list_rules
# ══════════════════════════════════════════════════════════

class TestRuleCRUD:
    def test_add_rule_with_message(self, tmp_path):
        e = _make_engine(tmp_path)
        r = e.add_rule("禁止 print", r"print\s*\(", message="no print")
        assert r["success"] is True
        assert r["rule"]["id"] == "CR001"
        assert r["rule"]["name"] == "禁止 print"
        assert r["rule"]["message"] == "no print"
        assert r["rule"]["enabled"] is True
        # 应已保存
        assert e._storage.exists()

    def test_add_rule_default_message(self, tmp_path):
        e = _make_engine(tmp_path)
        r = e.add_rule("规则A", r"pattern")
        # 无 message → 默认 "自定义规则: <name>"
        assert r["rule"]["message"] == "自定义规则: 规则A"

    def test_add_rule_increments_id(self, tmp_path):
        e = _make_engine(tmp_path)
        e.add_rule("r1", r"p1")
        r2 = e.add_rule("r2", r"p2")
        assert r2["rule"]["id"] == "CR002"

    def test_add_rule_severity(self, tmp_path):
        e = _make_engine(tmp_path)
        r = e.add_rule("crit", r"p", severity="critical")
        assert r["rule"]["severity"] == "critical"

    def test_remove_rule_existing(self, tmp_path):
        e = _make_engine(tmp_path)
        e.add_rule("r1", r"p1")
        e.add_rule("r2", r"p2")
        r = e.remove_rule("CR001")
        assert r["success"] is True
        assert len(e._rules) == 1
        assert e._rules[0]["id"] == "CR002"

    def test_remove_rule_nonexistent(self, tmp_path):
        """删除不存在的规则 → 仍返回 success=True（幂等）"""
        e = _make_engine(tmp_path)
        r = e.remove_rule("CR999")
        assert r["success"] is True

    def test_list_rules_empty(self, tmp_path):
        e = _make_engine(tmp_path)
        assert e.list_rules() == []

    def test_list_rules_with_data(self, tmp_path):
        e = _make_engine(tmp_path)
        e.add_rule("r1", r"p1")
        e.add_rule("r2", r"p2")
        rules = e.list_rules()
        assert len(rules) == 2


# ══════════════════════════════════════════════════════════
# check_file
# ══════════════════════════════════════════════════════════

class TestCheckFile:
    def test_file_not_exists(self, tmp_path):
        e = _make_engine(tmp_path)
        e.add_rule("r1", r"print")
        result = e.check_file(str(tmp_path / "nope.py"))
        assert result == []

    def test_regex_match(self, tmp_path):
        e = _make_engine(tmp_path)
        e.add_rule("禁止 print", r"print\s*\(", message="no print")
        # 创建含 print 的文件
        f = tmp_path / "code.py"
        f.write_text("print('hi')\nx = 1\nprint('bye')\n", encoding="utf-8")

        violations = e.check_file(str(f))
        assert len(violations) == 2
        assert all(v["rule_name"] == "禁止 print" for v in violations)
        assert violations[0]["line"] == 1
        assert violations[1]["line"] == 3
        assert "print" in violations[0]["text"]

    def test_regex_no_match(self, tmp_path):
        e = _make_engine(tmp_path)
        e.add_rule("禁止 print", r"print\s*\(")
        f = tmp_path / "code.py"
        f.write_text("x = 1\ny = 2\n", encoding="utf-8")
        assert e.check_file(str(f)) == []

    def test_regex_disabled_rule_skipped(self, tmp_path):
        """禁用的规则应被跳过"""
        e = _make_engine(tmp_path)
        e.add_rule("禁止 print", r"print\s*\(")
        # 手动禁用
        e._rules[0]["enabled"] = False
        f = tmp_path / "code.py"
        f.write_text("print('hi')\n", encoding="utf-8")
        assert e.check_file(str(f)) == []

    def test_ast_match_function_name(self, tmp_path):
        e = _make_engine(tmp_path)
        e.add_rule("禁止 fn", r"^bad_", rule_type="ast")
        f = tmp_path / "code.py"
        f.write_text(
            "def bad_func():\n    pass\n\ndef good_func():\n    pass\n",
            encoding="utf-8",
        )
        violations = e.check_file(str(f))
        assert len(violations) == 1
        assert violations[0]["line"] == 1
        assert "bad_func" in violations[0]["text"]

    def test_ast_syntax_error_skipped(self, tmp_path):
        """语法错误 → 跳过 AST 检查"""
        e = _make_engine(tmp_path)
        e.add_rule("ast", r".*", rule_type="ast")
        f = tmp_path / "bad.py"
        f.write_text("def (:\n", encoding="utf-8")
        # 不抛异常
        assert e.check_file(str(f)) == []

    def test_filename_match(self, tmp_path):
        e = _make_engine(tmp_path)
        e.add_rule("禁止 test_ 前缀", r"^test_", rule_type="filename")
        f = tmp_path / "test_foo.py"
        f.write_text("x = 1\n", encoding="utf-8")
        violations = e.check_file(str(f))
        assert len(violations) == 1
        assert violations[0]["rule_id"] == "CR001"
        # filename 分支没有 rule_name 字段
        assert "rule_name" not in violations[0]

    def test_filename_no_match(self, tmp_path):
        e = _make_engine(tmp_path)
        e.add_rule("禁止 test_", r"^test_", rule_type="filename")
        f = tmp_path / "foo.py"
        f.write_text("x = 1\n", encoding="utf-8")
        assert e.check_file(str(f)) == []

    def test_read_file_oserror(self, tmp_path, monkeypatch):
        """读取文件失败 → 静默捕获"""
        e = _make_engine(tmp_path)
        e.add_rule("r", r"p")
        f = tmp_path / "code.py"
        f.write_text("x = 1\n", encoding="utf-8")

        def boom(*a, **k):
            raise OSError("perm denied")
        monkeypatch.setattr(Path, "read_text", boom)
        assert e.check_file(str(f)) == []

    def test_read_file_unicode_error(self, tmp_path, monkeypatch):
        e = _make_engine(tmp_path)
        e.add_rule("r", r"p")
        f = tmp_path / "code.py"
        f.write_text("x = 1\n", encoding="utf-8")

        def boom(*a, **k):
            raise UnicodeDecodeError("utf-8", b"", 0, 1, "bad")
        monkeypatch.setattr(Path, "read_text", boom)
        assert e.check_file(str(f)) == []

    def test_read_file_permission_error(self, tmp_path, monkeypatch):
        e = _make_engine(tmp_path)
        e.add_rule("r", r"p")
        f = tmp_path / "code.py"
        f.write_text("x = 1\n", encoding="utf-8")

        def boom(*a, **k):
            raise PermissionError("denied")
        monkeypatch.setattr(Path, "read_text", boom)
        assert e.check_file(str(f)) == []

    def test_unknown_rule_type_skipped(self, tmp_path):
        """未知 type → 跳过该规则"""
        e = _make_engine(tmp_path)
        e.add_rule("unknown", r"p", rule_type="weird_type")
        f = tmp_path / "code.py"
        f.write_text("x = 1\n", encoding="utf-8")
        assert e.check_file(str(f)) == []

    def test_text_truncated_to_100_chars(self, tmp_path):
        """违规行长度超 100 字符时截断"""
        e = _make_engine(tmp_path)
        e.add_rule("long line", r"long_marker")
        f = tmp_path / "code.py"
        long_line = "long_marker" + "x" * 200
        f.write_text(long_line + "\n", encoding="utf-8")
        violations = e.check_file(str(f))
        assert len(violations) == 1
        # text 应被截断到 100 字符
        assert len(violations[0]["text"]) <= 100


# ══════════════════════════════════════════════════════════
# check_project
# ══════════════════════════════════════════════════════════

class TestCheckProject:
    def test_empty_project(self, tmp_path):
        e = _make_engine(tmp_path)
        e.add_rule("r", r"p")
        result = e.check_project(str(tmp_path))
        assert result["success"] is True
        assert result["total"] == 0
        assert result["violations"] == []

    def test_project_with_violations(self, tmp_path):
        e = _make_engine(tmp_path)
        e.add_rule("禁止 print", r"print\s*\(")
        # 创建若干 .py 文件
        (tmp_path / "a.py").write_text("print('a')\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("print('b')\n", encoding="utf-8")
        result = e.check_project(str(tmp_path))
        assert result["success"] is True
        assert result["total"] == 2

    def test_project_skips_pycache(self, tmp_path):
        """应跳过 __pycache__ 下的文件"""
        e = _make_engine(tmp_path)
        e.add_rule("禁止 print", r"print\s*\(")
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "mod.py").write_text("print('cached')\n", encoding="utf-8")
        (tmp_path / "main.py").write_text("print('main')\n", encoding="utf-8")
        result = e.check_project(str(tmp_path))
        assert result["total"] == 1  # 只有 main.py

    def test_project_skips_node_modules(self, tmp_path):
        """应跳过 node_modules 下的文件"""
        e = _make_engine(tmp_path)
        e.add_rule("禁止 print", r"print\s*\(")
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "lib.py").write_text("print('lib')\n", encoding="utf-8")
        result = e.check_project(str(tmp_path))
        assert result["total"] == 0

    def test_project_violations_truncated_to_100(self, tmp_path):
        """violations 应截断到 100 条"""
        e = _make_engine(tmp_path)
        e.add_rule("禁止 print", r"print\s*\(")
        # 创建 200 个含 print 的文件
        for i in range(200):
            (tmp_path / f"f{i}.py").write_text("print('x')\n", encoding="utf-8")
        result = e.check_project(str(tmp_path))
        assert result["total"] == 200
        assert len(result["violations"]) == 100  # 截断


# ══════════════════════════════════════════════════════════
# get_templates
# ══════════════════════════════════════════════════════════

class TestGetTemplates:
    def test_returns_list_of_templates(self, tmp_path):
        e = _make_engine(tmp_path)
        templates = e.get_templates()
        assert isinstance(templates, list)
        assert len(templates) >= 4
        names = {t["name"] for t in templates}
        assert "禁止 print 调试" in names
        assert "硬编码密钥" in names

    def test_template_fields(self, tmp_path):
        e = _make_engine(tmp_path)
        templates = e.get_templates()
        for t in templates:
            assert "name" in t
            assert "type" in t
            assert "pattern" in t
            assert "severity" in t
            assert "message" in t


# ══════════════════════════════════════════════════════════
# get_rules_engine 单例 + 默认构造函数（触发 load）
# ══════════════════════════════════════════════════════════

class TestGetRulesEngine:
    def test_singleton(self, monkeypatch, tmp_path):
        """重置全局单例后两次获取应是同一对象"""
        monkeypatch.setattr(cr_mod, "_engine", None)
        # 同时 mock _storage 避免读取真实文件
        # 直接 patch 类的初始化 — 使用 monkeypatch 替换 _storage 属性
        # CustomRulesEngine.__init__ 会调用 self.load()，但若 _storage 不存在则跳过
        # 用 monkeypatch.setattr 阻止真实 Path.home() 调用
        fake_home = tmp_path
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        e1 = get_rules_engine()
        e2 = get_rules_engine()
        assert e1 is e2

    def test_returns_engine(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cr_mod, "_engine", None)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        assert isinstance(get_rules_engine(), CustomRulesEngine)

    def test_init_loads_existing_storage(self, tmp_path, monkeypatch):
        """构造函数应触发 load() — 文件存在则加载"""
        # 准备存储文件
        rules_dir = tmp_path / ".pycoder"
        rules_dir.mkdir()
        storage = rules_dir / "custom_rules.json"
        storage.write_text(json.dumps([
            {"id": "CR001", "name": "existing", "pattern": "x", "type": "regex",
             "severity": "warning", "message": "m", "enabled": True},
        ]), encoding="utf-8")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        e = CustomRulesEngine()
        assert len(e._rules) == 1
        assert e._rules[0]["name"] == "existing"
