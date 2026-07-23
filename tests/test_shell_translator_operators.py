"""P2-修复: 跨平台 shell 操作符翻译单元测试"""
from __future__ import annotations

import sys

import pytest

from pycoder.core.shell_translator import OPERATOR_MAP, ShellTranslator


class TestOperatorMap:
    """操作符映射表完整性."""

    def test_contains_core_operators(self) -> None:
        for op in ("&&", "||", "|", ">", "<", ";", ">>"):
            assert op in OPERATOR_MAP, f"OPERATOR_MAP 缺少 {op}"

    def test_all_platforms_covered(self) -> None:
        for op, m in OPERATOR_MAP.items():
            for plat in ("windows", "linux", "mac"):
                assert plat in m, f"OPERATOR_MAP[{op}] 缺少 {plat}"


class TestShellTranslatorOperators:
    """操作符翻译功能."""

    def setup_method(self) -> None:
        self.t = ShellTranslator()

    @pytest.mark.parametrize(
        "cmd",
        [
            "ls -la && echo done",
            "mkdir build && cd build && cmake",
            "test -f x.txt && cat x.txt",
        ],
    )
    def test_and_and_translated_to_windows_if(self, cmd: str) -> None:
        r = self.t.translate(cmd, source="linux", target="windows")
        assert "&&" not in r.translated, f"翻译后应不含 &&: {r.translated}"
        assert "$LASTEXITCODE -eq 0" in r.translated
        assert "&&" in r.mappings_applied

    def test_and_and_multiple_chains(self) -> None:
        r = self.t.translate("ls && pwd && date", source="linux", target="windows")
        # 3 段应有 2 个 if 块
        assert r.translated.count("if ($LASTEXITCODE -eq 0)") == 2
        assert r.translated.count("}") == 2

    def test_or_translated_to_windows_if(self) -> None:
        r = self.t.translate(
            "cd /tmp || echo failed", source="linux", target="windows"
        )
        assert "||" not in r.translated
        assert "$LASTEXITCODE -ne 0" in r.translated
        assert "||" in r.mappings_applied

    def test_pipe_preserved(self) -> None:
        r = self.t.translate(
            "grep foo file | head -10", source="linux", target="windows"
        )
        assert "|" in r.translated

    def test_redirect_preserved(self) -> None:
        r = self.t.translate("echo hi > out.txt", source="linux", target="windows")
        assert ">" in r.translated

    def test_windows_to_linux_collapse(self) -> None:
        win_cmd = 'ls ; if ($LASTEXITCODE -eq 0) { echo ok }'
        r = self.t.translate(win_cmd, source="windows", target="linux")
        assert "&&" in r.translated
        assert "echo ok" in r.translated

    def test_windows_to_linux_or_collapse(self) -> None:
        win_cmd = 'cd x ; if ($LASTEXITCODE -ne 0) { echo fail }'
        r = self.t.translate(win_cmd, source="windows", target="linux")
        assert "||" in r.translated
        assert "echo fail" in r.translated

    def test_windows_to_linux_chained(self) -> None:
        win_cmd = (
            "ls ; if ($LASTEXITCODE -eq 0) { echo a } ; if ($LASTEXITCODE -eq 0) { pwd }"
        )
        r = self.t.translate(win_cmd, source="windows", target="linux")
        assert "&&" in r.translated
        assert r.translated.count("&&") == 2

    def test_same_platform_no_change(self) -> None:
        r = self.t.translate("ls && pwd", source="linux", target="linux")
        assert r.changed is False
        assert r.translated == "ls && pwd"

    def test_complex_linux_to_windows(self) -> None:
        result = self.t.translate(
            "ls && pwd || echo fail",
            source="linux",
            target="windows",
        )
        assert "&&" not in result.translated
        assert "||" not in result.translated
        # 包含 ls 命令名映射
        assert "ls" in result.mappings_applied
        # && 和 || 都应被标记
        assert "&&" in result.mappings_applied
        assert "||" in result.mappings_applied
