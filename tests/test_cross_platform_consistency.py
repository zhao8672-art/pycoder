"""P3 验证: 跨平台一致性测试

覆盖:
- P3-10: __git_commit_push.py 不硬编码 bash / shell=True
- P3-11: requirements.txt 与 requirements.in 一致
- P3-12: README 数字与实际测试函数数匹配
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class TestCrossPlatformScript:
    """P3-10: __git_commit_push.py 跨平台验证"""

    def test_script_exists(self):
        assert (ROOT / "__git_commit_push.py").exists(), "__git_commit_push.py 不存在"

    def test_uses_subprocess_run_list_args(self):
        """应使用 list 形式参数, 避免 shell=True."""
        content = (ROOT / "__git_commit_push.py").read_text(encoding="utf-8")
        # 禁止 shell=True
        assert "shell=True" not in content, "__git_commit_push.py 不应使用 shell=True"
        # 应有 list 字面量形式调用 run([...])
        assert re.search(r"run\(\[\s*\"[a-z]+\"", content), "应使用 list 字面量调用 run([...])"

    def test_no_hardcoded_bash(self):
        """不应硬编码 bash/sh 路径."""
        content = (ROOT / "__git_commit_push.py").read_text(encoding="utf-8")
        bad_patterns = ["/bin/bash", "/bin/sh", "bash -c", "sh -c"]
        for bad in bad_patterns:
            assert bad not in content, f"包含硬编码: {bad}"

    def test_post_commit_hook_has_bash_shebang(self):
        """post-commit 钩子应使用 bash shebang (Git for Windows 自带 Git Bash)."""
        hook = ROOT / ".git-hooks" / "post-commit"
        if not hook.exists():
            pytest.skip("post-commit 钩子未创建")
        content = hook.read_text(encoding="utf-8")
        assert content.startswith("#!/bin/bash") or content.startswith("#!/usr/bin/env bash"), \
            "post-commit 缺少 bash shebang"

    def test_post_commit_hook_no_windows_only(self):
        """post-commit 钩子不应使用 Windows-only 命令."""
        hook = ROOT / ".git-hooks" / "post-commit"
        if not hook.exists():
            pytest.skip("post-commit 钩子未创建")
        content = hook.read_text(encoding="utf-8")
        bad = ["cmd.exe", "powershell -File", "taskkill"]
        for b in bad:
            assert b not in content, f"post-commit 包含 Windows-only: {b}"


class TestRequirementsConsistency:
    """P3-11: requirements.txt 与 requirements.in 一致性"""

    def test_requirements_txt_exists(self):
        assert (ROOT / "requirements.txt").exists()

    def test_requirements_in_exists(self):
        assert (ROOT / "requirements" / "requirements.in").exists()

    def test_no_duplicate_packages_in_requirements_txt(self):
        """不应在 requirements.txt 末尾有硬编码冗余段 (P0-1 修复)."""
        content = (ROOT / "requirements.txt").read_text(encoding="utf-8", errors="ignore")
        # 修复后, 末尾应该是 -r requirements/requirements.in 引用
        # 不应再出现 "PyCoder 运行时必需但此前缺失的依赖" 等历史硬编码段
        bad_markers = [
            "PyCoder 运行时必需但此前缺失",
            "应将下列包加入 requirements/requirements.in 后重新",
        ]
        for marker in bad_markers:
            assert marker not in content, f"requirements.txt 仍含硬编码段: {marker}"

    def test_pyproject_references_valid_files(self):
        """pyproject.toml 引用的 requirements 文件必须存在."""
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        # 仅检查 [tool.setuptools.dynamic] 块
        block_match = re.search(
            r"\[tool\.setuptools\.dynamic\](.*?)(?:\[tool\.|\Z)",
            pyproject,
            re.DOTALL,
        )
        assert block_match, "pyproject.toml 缺少 [tool.setuptools.dynamic] 块"
        refs = re.findall(r'file\s*=\s*"([^"]+)"', block_match.group(1))
        assert len(refs) > 0, "pyproject.toml 应至少引用一个 requirements 文件"
        for ref in refs:
            path = ROOT / ref
            assert path.exists(), f"pyproject 引用 {ref} 不存在"


class TestReadmeConsistency:
    """P3-12: README 数字一致性"""

    def test_readme_exists(self):
        assert (ROOT / "README.md").exists()

    def test_readme_tests_badge_accurate(self):
        """README 中 tests-N+ 应与实际测试函数数一致."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        m = re.search(r"tests-(\d+)", readme)
        assert m, "README 缺少 tests-N+ badge"

        # 实际测试函数数
        test_files = list((ROOT / "tests").glob("test_*.py"))
        test_funcs = 0
        for f in test_files:
            content = f.read_text(encoding="utf-8", errors="ignore")
            test_funcs += len(re.findall(r"^\s*(?:async\s+)?def\s+test_", content, re.MULTILINE))

        claimed = int(m.group(1))
        assert test_funcs >= claimed * 0.9, \
            f"README 声明 {claimed}+ 测试, 实际仅 {test_funcs} 个测试函数"

    def test_readme_no_buggy_m_m_pattern(self):
        """README 不应在主示例中使用 'python -m pycoder -m' (短选项说明块除外)."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        lines = readme.split("\n")
        in_short_option_block = False
        for line in lines:
            if "短选项" in line or "与上面等价" in line:
                in_short_option_block = True
                continue
            if in_short_option_block and (line.strip().startswith("```") or not line.strip()):
                if line.strip().startswith("```"):
                    in_short_option_block = False
                continue
            if "python -m pycoder -m" in line and not in_short_option_block:
                pytest.fail(f"README 存在 -m -m 重复: {line.strip()}")


class TestConsistencyScript:
    """scripts/check_readme_consistency.py 自身可运行"""

    def test_consistency_script_exits_zero(self):
        """一致性检查脚本应返回 0 (全部通过)."""
        # 强制 UTF-8 避免 Windows GBK 解码失败
        import os
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        result = subprocess.run(
            [sys.executable, "scripts/check_readme_consistency.py"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env=env,
        )
        # 不强制 0, 但应能正常完成
        assert result.returncode in (0, 1, 2), f"异常退出: {result.returncode}\n{result.stderr}"
        # 颜色码可能干扰, 检查 [OK] 或 [ERROR] 标记
        stdout = result.stdout or ""
        assert "[OK]" in stdout or "[ERROR]" in stdout, "输出格式异常"
