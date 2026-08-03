"""P0-1: 跨平台命令翻译器单元测试"""

from __future__ import annotations

from pycoder.core.shell_translator import (
    COMMAND_MAP,
    ShellTranslator,
    TranslationResult,
    detect_platform,
    translate_command,
    translate_to_current_platform,
)


class TestDetectPlatform:
    def test_returns_string(self):
        p = detect_platform()
        assert p in ("windows", "linux", "mac")


class TestShellTranslatorBasic:
    def test_empty_command(self):
        t = ShellTranslator()
        r = t.translate("")
        assert r.original == ""
        assert r.translated == ""
        assert not r.changed

    def test_same_platform_no_translation(self):
        t = ShellTranslator()
        r = t.translate("ls -la", source="linux", target="linux")
        assert not r.changed
        assert r.translated == "ls -la"

    def test_ls_to_windows(self):
        t = ShellTranslator()
        r = t.translate("ls -la", source="linux", target="windows")
        assert r.changed
        assert "dir" in r.translated
        assert "ls" in r.mappings_applied

    def test_cat_to_windows(self):
        t = ShellTranslator()
        r = t.translate("cat README.md", source="linux", target="windows")
        assert r.changed
        assert "type" in r.translated
        assert "cat" in r.mappings_applied

    def test_grep_to_windows(self):
        t = ShellTranslator()
        r = t.translate("grep -r 'TODO' src/", source="linux", target="windows")
        assert r.changed
        assert "findstr" in r.translated

    def test_ps_to_windows(self):
        t = ShellTranslator()
        r = t.translate("ps aux", source="linux", target="windows")
        assert r.changed
        assert "tasklist" in r.translated

    def test_rm_to_windows(self):
        t = ShellTranslator()
        r = t.translate("rm -rf build/", source="linux", target="windows")
        assert r.changed
        assert "del" in r.translated

    def test_pwd_to_windows(self):
        t = ShellTranslator()
        r = t.translate("pwd", source="linux", target="windows")
        assert r.changed
        assert "cd" in r.translated

    def test_clear_to_windows(self):
        t = ShellTranslator()
        r = t.translate("clear", source="linux", target="windows")
        assert r.changed
        assert "cls" in r.translated

    def test_ifconfig_to_windows(self):
        t = ShellTranslator()
        r = t.translate("ifconfig", source="linux", target="windows")
        assert r.changed
        assert "ipconfig" in r.translated

    def test_wget_to_windows(self):
        t = ShellTranslator()
        r = t.translate("wget https://example.com", source="linux", target="windows")
        assert r.changed
        assert "curl" in r.translated


class TestShellTranslatorArgs:
    def test_args_preserved(self):
        t = ShellTranslator()
        r = t.translate("ls -la /home/user", source="linux", target="windows")
        assert "-la" in r.translated
        assert "/home/user" in r.translated

    def test_unknown_command_unchanged(self):
        t = ShellTranslator()
        r = t.translate("my_custom_cmd --flag", source="linux", target="windows")
        assert r.translated == "my_custom_cmd --flag"

    def test_pipe_chains(self):
        t = ShellTranslator()
        r = t.translate("ps aux | grep python", source="linux", target="windows")
        assert r.changed
        assert "tasklist" in r.translated
        assert "findstr" in r.translated

    def test_quoted_args(self):
        t = ShellTranslator()
        r = t.translate('grep "hello world" file.txt', source="linux", target="windows")
        assert '"hello world"' in r.translated


class TestOperatorChains:
    """&& / || 命令链解析 — 混合链必须生成扁平 if 链, 不能嵌套."""

    def test_simple_and(self):
        t = ShellTranslator()
        r = t.translate("cmd1 && cmd2", source="linux", target="windows")
        assert r.translated == "cmd1 ; if ($?) { cmd2 }"

    def test_multiple_and(self):
        t = ShellTranslator()
        r = t.translate("cmd1 && cmd2 && cmd3", source="linux", target="windows")
        assert r.translated == "cmd1 ; if ($?) { cmd2 } ; if ($?) { cmd3 }"

    def test_simple_or(self):
        t = ShellTranslator()
        r = t.translate("cmd1 || cmd2", source="linux", target="windows")
        assert r.translated == "cmd1 ; if (-not $?) { cmd2 }"

    def test_multiple_or(self):
        t = ShellTranslator()
        r = t.translate("cmd1 || cmd2 || cmd3", source="linux", target="windows")
        assert r.translated == "cmd1 ; if (-not $?) { cmd2 } ; if (-not $?) { cmd3 }"

    def test_mixed_and_or(self):
        """cmd1 && cmd2 || cmd3 → 扁平 if 链, 不能嵌套."""
        t = ShellTranslator()
        r = t.translate("cmd1 && cmd2 || cmd3", source="linux", target="windows")
        # 正确: cmd3 在顶层, cmd1 失败时仍可执行
        assert r.translated == "cmd1 ; if ($?) { cmd2 } ; if (-not $?) { cmd3 }"
        # 不能嵌套: cmd3 不应在第一个 if 块内
        assert r.translated.count("{") == r.translated.count("}") == 2

    def test_mixed_or_and(self):
        """cmd1 || cmd2 && cmd3 → 扁平 if 链."""
        t = ShellTranslator()
        r = t.translate("cmd1 || cmd2 && cmd3", source="linux", target="windows")
        assert r.translated == "cmd1 ; if (-not $?) { cmd2 } ; if ($?) { cmd3 }"

    def test_triple_mixed(self):
        """cmd1 && cmd2 || cmd3 && cmd4 → 四段扁平 if 链."""
        t = ShellTranslator()
        r = t.translate("cmd1 && cmd2 || cmd3 && cmd4", source="linux", target="windows")
        expected = "cmd1 ; if ($?) { cmd2 } ; if (-not $?) { cmd3 } ; if ($?) { cmd4 }"
        assert r.translated == expected

    def test_and_inside_quotes(self):
        """引号内的 && 不应被分割."""
        t = ShellTranslator()
        r = t.translate('echo "a && b" && ls', source="linux", target="windows")
        assert '"a && b"' in r.translated
        assert "if ($?)" in r.translated

    def test_or_inside_quotes(self):
        """引号内的 || 不应被分割."""
        t = ShellTranslator()
        r = t.translate('echo "a || b" || ls', source="linux", target="windows")
        assert '"a || b"' in r.translated
        assert "if (-not $?)" in r.translated

    def test_mappings_applied_mixed(self):
        """混合链的 mappings_applied 应同时记录 && 和 ||."""
        t = ShellTranslator()
        r = t.translate("cmd1 && cmd2 || cmd3", source="linux", target="windows")
        assert "&&" in r.mappings_applied
        assert "||" in r.mappings_applied


class TestCrossPlatformChains:
    """跨平台命令链解析 — 覆盖 Linux/Mac/Windows 互相翻译."""

    def test_linux_to_mac_or_preserved(self):
        """Linux → Mac: || 不应被拆成 | | (str.replace 破坏双字符操作符)."""
        t = ShellTranslator()
        r = t.translate("cmd1 || cmd2", source="linux", target="mac")
        assert "||" in r.translated
        assert "| |" not in r.translated

    def test_linux_to_mac_mixed_chain(self):
        """Linux → Mac: 混合链保持原样."""
        t = ShellTranslator()
        r = t.translate("cmd1 && cmd2 || cmd3", source="linux", target="mac")
        assert "&&" in r.translated
        assert "||" in r.translated

    def test_mac_to_linux_or_preserved(self):
        """Mac → Linux: || 不应被拆成 | |."""
        t = ShellTranslator()
        r = t.translate("cmd1 || cmd2", source="mac", target="linux")
        assert "||" in r.translated
        assert "| |" not in r.translated

    def test_pipe_not_broken_by_or(self):
        """管道 | 和 || 共存时, 管道不应被破坏."""
        t = ShellTranslator()
        r = t.translate("cmd1 | grep foo || echo notfound", source="linux", target="mac")
        assert "|" in r.translated
        assert "||" in r.translated
        assert "| |" not in r.translated

    def test_redirect_append_preserved(self):
        """>> 不应被拆成 > >."""
        t = ShellTranslator()
        r = t.translate("cmd1 >> out.log", source="linux", target="mac")
        assert ">>" in r.translated
        assert "> >" not in r.translated

    def test_roundtrip_linux_windows_linux(self):
        """Linux → Windows → Linux 往返一致性."""
        t = ShellTranslator()
        original = "cmd1 && cmd2 || cmd3"
        r1 = t.translate(original, source="linux", target="windows")
        r2 = t.translate(r1.translated, source="windows", target="linux")
        assert " ".join(r2.translated.split()) == " ".join(original.split())

    def test_windows_to_linux_reverses_if_chain(self):
        """Windows if 链 → Linux 还原为 && / ||."""
        t = ShellTranslator()
        win_cmd = "cmd1 ; if ($?) { cmd2 } ; if (-not $?) { cmd3 }"
        r = t.translate(win_cmd, source="windows", target="linux")
        assert "&&" in r.translated
        assert "||" in r.translated
        assert "if" not in r.translated


class TestSpecialOperators:
    """特殊 shell 符号 (heredoc/fd 重定向) 不应被误拆分."""

    def test_heredoc_not_split(self):
        """<< heredoc 不应被 < 拆成 < <."""
        t = ShellTranslator()
        r = t.translate("cat << EOF", source="linux", target="mac")
        assert "<<" in r.translated
        assert "< <" not in r.translated

    def test_fd_redirect_out_not_split(self):
        """2>&1 fd 重定向中的 > 不应被拆分."""
        t = ShellTranslator()
        r = t.translate("cmd 2>&1 | grep foo", source="linux", target="mac")
        assert "2>&1" in r.translated
        assert "> &" not in r.translated

    def test_fd_redirect_err_not_split(self):
        """1>&2 fd 重定向中的 > 不应被拆分."""
        t = ShellTranslator()
        r = t.translate("echo error 1>&2", source="linux", target="mac")
        assert "1>&2" in r.translated

    def test_fd_input_not_split(self):
        """<&3 fd 输入中的 < 不应被拆分."""
        t = ShellTranslator()
        r = t.translate("cmd <&3", source="linux", target="mac")
        assert "<&3" in r.translated
        assert "< &" not in r.translated

    def test_fd_output_not_split(self):
        """fd 输出 >&2 中的 > 不应被拆分."""
        t = ShellTranslator()
        r = t.translate("cmd >&2", source="linux", target="mac")
        assert ">&2" in r.translated
        assert "> &" not in r.translated

    def test_heredoc_in_complex_chain(self):
        """复杂链中 heredoc 不被破坏."""
        t = ShellTranslator()
        r = t.translate("cat << EOF && grep foo", source="linux", target="windows")
        assert "<<" in r.translated
        assert "< <" not in r.translated

    def test_fd_redirect_in_pipe(self):
        """管道中的 fd 重定向不被破坏."""
        t = ShellTranslator()
        r = t.translate("cmd 2>&1 | grep err || echo fail", source="linux", target="windows")
        assert "2>&1" in r.translated
        assert "> &" not in r.translated


class TestCustomMapping:
    def test_add_custom_mapping(self):
        from pycoder.core.shell_translator import add_custom_mapping

        add_custom_mapping("myapp", {"windows": "myapp.exe", "linux": "myapp"})
        t = ShellTranslator()
        r = t.translate("myapp --run", source="linux", target="windows")
        assert "myapp.exe" in r.translated


class TestConvenienceFunctions:
    def test_translate_command(self):
        r = translate_command("ls", source="linux", target="windows")
        assert isinstance(r, TranslationResult)
        assert r.changed

    def test_translate_to_current_platform(self):
        r = translate_to_current_platform("ls")
        assert isinstance(r, TranslationResult)


class TestCommandMapIntegrity:
    def test_all_commands_have_all_platforms(self):
        for cmd, mapping in COMMAND_MAP.items():
            assert "windows" in mapping, f"{cmd} missing windows"
            assert "linux" in mapping, f"{cmd} missing linux"
            assert "mac" in mapping, f"{cmd} missing mac"
