"""覆盖率测试: pycoder/prompts/snippets_loader.py

目标: 行覆盖率 >= 95%

覆盖内容:
  - _init_dirs (幂等初始化)
  - load_snippets (各种格式: 简单/带 description/带代码栅栏/body 过短/无 prefix)
  - get_snippet / list_snippets

测试策略:
  - 用 monkeypatch 替换 SNIPPETS_DIRS 指向 tmp_path 避免污染
  - 创建临时 .json 文件作为片段库
  - 测试各分支: 文件不存在、内容格式、代码栅栏剥离等
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pycoder.prompts import snippets_loader as sl_mod
from pycoder.prompts.snippets_loader import (
    get_snippet,
    list_snippets,
    load_snippets,
)


# ── fixture: 每个 test 重置 SNIPPETS_DIRS ─────────────────

@pytest.fixture(autouse=True)
def _reset_snippets_dirs(monkeypatch, tmp_path):
    """每个测试前重置 SNIPPETS_DIRS 为 tmp_path 下的目录"""
    monkeypatch.setattr(
        sl_mod, "SNIPPETS_DIRS",
        [tmp_path / "snippets"],
    )


def _write_snippets(tmp_path: Path, language: str, content: str):
    """写入指定语言的 snippets 文件"""
    snip_dir = tmp_path / "snippets"
    snip_dir.mkdir(exist_ok=True)
    f = snip_dir / f"{language}.json"
    f.write_text(content, encoding="utf-8")
    return f


# ══════════════════════════════════════════════════════════
# _init_dirs
# ══════════════════════════════════════════════════════════

class TestInitDirs:
    def test_idempotent(self, monkeypatch):
        """多次调用 _init_dirs 不会重复扩展列表"""
        # 先清空以测试
        monkeypatch.setattr(sl_mod, "SNIPPETS_DIRS", [])
        sl_mod._init_dirs()
        first_len = len(sl_mod.SNIPPETS_DIRS)
        # 再次调用 — 已有内容，应直接返回
        sl_mod._init_dirs()
        assert len(sl_mod.SNIPPETS_DIRS) == first_len

    def test_initializes_with_cwd_and_home(self, monkeypatch, tmp_path):
        """首次调用应初始化 .snippets 和 ~/.pycoder/snippets 目录"""
        monkeypatch.setattr(sl_mod, "SNIPPETS_DIRS", [])
        # mock Path.cwd 和 Path.home
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        sl_mod._init_dirs()
        assert len(sl_mod.SNIPPETS_DIRS) == 2
        assert sl_mod.SNIPPETS_DIRS[0] == tmp_path / ".snippets"
        assert sl_mod.SNIPPETS_DIRS[1] == tmp_path / ".pycoder" / "snippets"


# ══════════════════════════════════════════════════════════
# load_snippets
# ══════════════════════════════════════════════════════════

class TestLoadSnippets:
    def test_no_dirs_exist(self, tmp_path):
        """目录下无 snippets 文件 → 返回空 dict"""
        # 不创建任何文件
        result = load_snippets("python")
        assert result == {}

    def test_basic_snippet(self, tmp_path):
        """基础格式: prefix + body，用 --- 分隔"""
        _write_snippets(tmp_path, "python", """prefix: fn
description: function snippet
---
def fn():
    return 1
""")
        result = load_snippets("python")
        assert "fn" in result
        assert result["fn"]["description"] == "function snippet"
        assert "def fn():" in result["fn"]["body"]
        assert "return 1" in result["fn"]["body"]

    def test_snippet_without_description(self, tmp_path):
        """无 description 字段 → 默认空字符串"""
        _write_snippets(tmp_path, "python", """prefix: cls
---
class C:
    pass
""")
        result = load_snippets("python")
        assert result["cls"]["description"] == ""
        assert "class C:" in result["cls"]["body"]

    def test_multiple_snippets(self, tmp_path):
        """多个 snippet 应都解析"""
        _write_snippets(tmp_path, "python", """prefix: fn
description: function
---
def fn():
    return 1
---
prefix: cls
description: class
---
class C:
    pass
""")
        result = load_snippets("python")
        assert "fn" in result
        assert "cls" in result

    def test_code_fence_stripped(self, tmp_path):
        """body 包裹在 ``` 围栏中应被剥离"""
        _write_snippets(tmp_path, "python", """prefix: fenced
description: with fence
---
```python
def hello():
    print("hi")
```
""")
        result = load_snippets("python")
        assert "fenced" in result
        # 应剥离 ```python 和 ```
        assert "```" not in result["fenced"]["body"]
        assert "def hello():" in result["fenced"]["body"]

    def test_body_too_short_skipped(self, tmp_path):
        """body 长度 < 10 → 跳过"""
        _write_snippets(tmp_path, "python", """prefix: short
description: too short
---
short
""")
        result = load_snippets("python")
        # body "short" 长度 5 < 10 → 被跳过
        assert "short" not in result

    def test_meta_block_without_prefix_skipped(self, tmp_path):
        """meta 块无 prefix: 字段 → 跳过"""
        _write_snippets(tmp_path, "python", """description: no prefix
---
def something():
    return 1
""")
        result = load_snippets("python")
        assert result == {}

    def test_language_other_than_python(self, tmp_path):
        """加载其他语言的 snippets"""
        _write_snippets(tmp_path, "javascript", """prefix: log
description: console log
---
console.log("x");
""")
        result = load_snippets("javascript")
        assert "log" in result
        assert "console.log" in result["log"]["body"]

    def test_load_exception_handled(self, tmp_path, monkeypatch):
        """读取抛异常 → 静默捕获"""
        _write_snippets(tmp_path, "python", """prefix: x
description: y
---
def x(): pass
""")
        # mock read_text 抛异常
        def boom(*a, **k):
            raise RuntimeError("disk err")
        monkeypatch.setattr(Path, "read_text", boom)
        # 不抛异常
        result = load_snippets("python")
        assert result == {}

    def test_multiple_dirs(self, tmp_path, monkeypatch):
        """多个目录都应被扫描"""
        dir1 = tmp_path / "snippets1"
        dir2 = tmp_path / "snippets2"
        dir1.mkdir()
        dir2.mkdir()
        (dir1 / "python.json").write_text(
            "prefix: a\ndescription: from dir1\n---\n"
            "def a():\n    return 1\n", encoding="utf-8",
        )
        (dir2 / "python.json").write_text(
            "prefix: b\ndescription: from dir2\n---\n"
            "def b():\n    return 2\n", encoding="utf-8",
        )
        monkeypatch.setattr(sl_mod, "SNIPPETS_DIRS", [dir1, dir2])

        result = load_snippets("python")
        assert "a" in result
        assert "b" in result
        assert result["a"]["description"] == "from dir1"
        assert result["b"]["description"] == "from dir2"

    def test_dir1_overridden_by_dir2(self, tmp_path, monkeypatch):
        """后扫描的目录会覆盖前者的同名 prefix"""
        dir1 = tmp_path / "snippets1"
        dir2 = tmp_path / "snippets2"
        dir1.mkdir()
        dir2.mkdir()
        (dir1 / "python.json").write_text(
            "prefix: dup\ndescription: from dir1\n---\n"
            "def dup():\n    return 1\n", encoding="utf-8",
        )
        (dir2 / "python.json").write_text(
            "prefix: dup\ndescription: from dir2\n---\n"
            "def dup():\n    return 2\n", encoding="utf-8",
        )
        monkeypatch.setattr(sl_mod, "SNIPPETS_DIRS", [dir1, dir2])

        result = load_snippets("python")
        # 后者覆盖
        assert result["dup"]["description"] == "from dir2"

    def test_init_dirs_called(self, monkeypatch, tmp_path):
        """load_snippets 应调用 _init_dirs"""
        # 重置 SNIPPETS_DIRS 为空
        monkeypatch.setattr(sl_mod, "SNIPPETS_DIRS", [])
        # mock Path.cwd / Path.home 返回 tmp_path
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        # 不抛异常
        result = load_snippets("python")
        assert result == {}
        # _init_dirs 应已扩展 SNIPPETS_DIRS
        assert len(sl_mod.SNIPPETS_DIRS) == 2


# ══════════════════════════════════════════════════════════
# get_snippet
# ══════════════════════════════════════════════════════════

class TestGetSnippet:
    def test_existing_prefix(self, tmp_path):
        _write_snippets(tmp_path, "python", """prefix: fn
description: func
---
def fn():
    return 1
""")
        snip = get_snippet("python", "fn")
        assert snip is not None
        assert snip["description"] == "func"

    def test_nonexistent_prefix(self, tmp_path):
        """不存在的 prefix → None"""
        # 不创建任何文件
        assert get_snippet("python", "nope") is None


# ══════════════════════════════════════════════════════════
# list_snippets
# ══════════════════════════════════════════════════════════

class TestListSnippets:
    def test_empty(self, tmp_path):
        """无 snippets → 空列表"""
        result = list_snippets("python")
        assert result == []

    def test_returns_list_with_metadata(self, tmp_path):
        _write_snippets(tmp_path, "python", """prefix: fn
description: function
---
def fn():
    return 1
""")
        result = list_snippets("python")
        assert len(result) == 1
        assert result[0]["prefix"] == "fn"
        assert result[0]["description"] == "function"
        # body 应截断到 100 字符
        assert "body" in result[0]

    def test_body_truncated_to_100(self, tmp_path):
        """body > 100 字符 → 截断并添加 ..."""
        long_body = "x = " + "1" * 200
        _write_snippets(tmp_path, "python", f"""prefix: long
description: long body
---
{long_body}
""")
        result = list_snippets("python")
        assert len(result) == 1
        body = result[0]["body"]
        # body 应被截断
        assert len(body) <= 104  # 100 + "..."
        assert body.endswith("...")

    def test_body_short_not_truncated(self, tmp_path):
        """body <= 100 字符 → 不截断"""
        _write_snippets(tmp_path, "python", """prefix: short
description: short body
---
def short():
    return 1
""")
        result = list_snippets("python")
        assert "..." not in result[0]["body"]
