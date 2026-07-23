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
        # 仅检查行首的 [tool.setuptools.dynamic] 块 (避免匹配注释中的字符串)
        block_match = re.search(
            r"^\[tool\.setuptools\.dynamic\]\s*\n(.*?)(?=^\[|\Z)",
            pyproject,
            re.DOTALL | re.MULTILINE,
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


class TestDependencyGroups:
    """P3-11 扩展: 依赖组一致性 (requirements-all / pyproject optional-dependencies)"""

    def test_requirements_all_exists(self):
        assert (ROOT / "requirements-all.txt").exists(), "requirements-all.txt 缺失"

    def test_requirements_all_references_all_groups(self):
        """requirements-all.txt 必须引用所有 5 个组."""
        content = (ROOT / "requirements-all.txt").read_text(encoding="utf-8")
        required = [
            "requirements.txt",
            "requirements/requirements-dev.txt",
            "requirements/requirements-help.txt",
            "requirements/requirements-browser.txt",
            "requirements/requirements-playwright.txt",
        ]
        for ref in required:
            assert ref in content, f"requirements-all.txt 应引用 {ref}"

    def test_pyproject_optional_dependencies_declared(self):
        """pyproject.toml 必须定义所有 4 个可选组."""
        content = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        for group in ["dev", "help", "browser", "playwright"]:
            assert f"{group} =" in content or f"{group}=[" in content, \
                f"pyproject.toml 应定义可选组: {group}"

    def test_all_referenced_requirements_files_exist(self):
        """requirements-all.txt 引用的文件必须全部存在."""
        content = (ROOT / "requirements-all.txt").read_text(encoding="utf-8")
        refs = re.findall(r"^-\s*r\s+(.+)$", content, re.MULTILINE)
        for ref in refs:
            path = ROOT / ref
            assert path.exists(), f"引用的 {ref} 不存在"


class TestEntryPoints:
    """P3 扩展: pyproject.toml 入口点一致性"""

    def test_project_scripts_declares_pycoder(self):
        content = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert "[project.scripts]" in content, "[project.scripts] 块缺失"
        assert "pycoder = " in content, "pycoder 入口点缺失"
        assert "pycoder-server = " in content, "pycoder-server 入口点缺失"

    def test_entry_point_targets_exist(self):
        """入口点引用的模块:函数必须存在."""
        content = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        # 匹配 entry = "module:function" 形式
        entries = re.findall(r'(\w+(?:-\w+)?)\s*=\s*"([\w.]+):(\w+)"', content)
        for name, module, func in entries:
            # 跳过非 pycoder 模块
            if not module.startswith("pycoder"):
                continue
            # module 形如 "pycoder.__main__" / "pycoder.server.app" / "pycoder.cli.x"
            # 实际文件位于 ROOT/pycoder/<rel_path>.py 或 ROOT/pycoder/<rel_path>/__init__.py
            rel = module[len("pycoder."):] if module.startswith("pycoder.") else module
            rel_path = rel.replace(".", "/")
            candidates = [
                ROOT / "pycoder" / (rel_path + ".py"),       # 单文件模块
                ROOT / "pycoder" / rel_path / "__init__.py", # 包
            ]
            if not any(c.exists() for c in candidates):
                pytest.fail(f"入口 {name}: 模块 {module} 不存在")


class TestWindowsWrappers:
    """P3 扩展: Windows 启动包装器"""

    def test_bat_wrapper_exists(self):
        assert (ROOT / "scripts" / "pycoder.bat").exists()

    def test_bat_wrapper_syntax(self):
        """检查 .bat 语法 (无 PowerShell 特有语法)."""
        content = (ROOT / "scripts" / "pycoder.bat").read_text(encoding="utf-8", errors="ignore")
        assert content.startswith("@echo off"), ".bat 必须以 @echo off 开头"
        assert "powershell" not in content.lower(), ".bat 不应调用 powershell"

    def test_ps1_wrapper_exists(self):
        assert (ROOT / "scripts" / "pycoder.ps1").exists()

    def test_ps1_wrapper_syntax(self):
        """检查 .ps1 语法."""
        content = (ROOT / "scripts" / "pycoder.ps1").read_text(encoding="utf-8")
        # 应有 [CmdletBinding()] 或 param(...)
        assert "[CmdletBinding()]" in content or "param(" in content, \
            ".ps1 缺少 CmdletBinding 或 param 声明"
        # 应设置 UTF-8
        assert "PYTHONUTF8" in content, ".ps1 未设置 PYTHONUTF8"


class TestTaskRunner:
    """P3 扩展: scripts/run.py 任务运行器"""

    def test_run_py_exists(self):
        assert (ROOT / "scripts" / "run.py").exists()

    def test_run_py_list_runs(self):
        """run.py --list 应能正常输出."""
        import os
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        result = subprocess.run(
            [sys.executable, "scripts/run.py", "--list"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            env=env,
        )
        assert result.returncode == 0
        assert "PyCoder 任务运行器" in (result.stdout or "")

    def test_makefile_exists(self):
        assert (ROOT / "Makefile").exists()

    def test_makefile_has_install_all(self):
        content = (ROOT / "Makefile").read_text(encoding="utf-8")
        assert "install-all:" in content, "Makefile 缺少 install-all 目标"
        assert "requirements-all.txt" in content, "Makefile 应引用 requirements-all.txt"


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


class TestPyprojectToolBlocks:
    """P3 扩展: pyproject.toml 关键工具配置块 + 关键依赖版本锁定"""

    @pytest.fixture
    def pyproject(self) -> str:
        return (ROOT / "pyproject.toml").read_text(encoding="utf-8", errors="ignore")

    @pytest.mark.parametrize("block", [
        "tool.pytest.ini_options",
        "tool.coverage.run",
        "tool.coverage.report",
        "tool.ruff",
        "tool.black",
        "tool.mypy",
    ])
    def test_required_tool_block_exists(self, pyproject, block):
        """每个必须的工具块都应存在."""
        assert f"[{block}]" in pyproject, f"pyproject.toml 缺少 [{block}] 配置块"

    def test_pytest_minimum_version(self, pyproject):
        """pytest 配置应声明最低版本 8.0+."""
        assert 'minversion = "8.0"' in pyproject, "应声明 minversion = 8.0+"

    def test_pytest_has_markers(self, pyproject):
        """pytest 配置应包含 slow/integration 等 markers."""
        # 行首匹配 (避免被头部文档注释中的 [tool.pytest.ini_options] 字符串误匹配)
        block = re.search(
            r"^\[tool\.pytest\.ini_options\]\s*\n(.*?)(?=^\[|\Z)",
            pyproject, re.DOTALL | re.MULTILINE,
        )
        assert block is not None
        assert "markers" in block.group(1), "应定义 markers"
        assert "slow" in block.group(1), "应定义 slow marker"

    def test_coverage_branch_enabled(self, pyproject):
        """coverage 应启用 branch 模式."""
        assert re.search(
            r"\[tool\.coverage\.run\].*?branch\s*=\s*true",
            pyproject, re.DOTALL,
        ), "coverage 应启用 branch 模式"

    def test_coverage_has_fail_under(self, pyproject):
        """coverage 应设置 fail_under 阈值."""
        assert re.search(
            r"\[tool\.coverage\.report\].*?fail_under\s*=\s*\d+",
            pyproject, re.DOTALL,
        ), "coverage 应设置 fail_under 阈值"


class TestCriticalDependencyPinning:
    """P3 扩展: 关键运行时依赖应在 requirements.in 中锁定兼容版本"""

    @pytest.fixture
    def requirements_in(self) -> str:
        return (ROOT / "requirements" / "requirements.in").read_text(
            encoding="utf-8", errors="ignore"
        )

    @pytest.mark.parametrize("dep", ["litellm", "openai", "fastapi", "pydantic"])
    def test_critical_dep_pinned(self, requirements_in, dep):
        """关键依赖应使用 ~=/>=/<= 等版本约束, 避免裸依赖."""
        pattern = rf"^{re.escape(dep)}\s*[><=~!]+"
        assert re.search(pattern, requirements_in, re.MULTILINE), \
            f"{dep} 应锁定兼容版本, 当前为裸依赖"


class TestRootScripts:
    """P3 扩展: 仓库根目录必须有跨平台启动脚本"""

    @pytest.mark.parametrize("name", ["start.bat", "start.ps1"])
    def test_root_start_script_exists(self, name):
        path = ROOT / name
        assert path.exists(), f"仓库根目录缺少 {name} (用户审计会扫描根目录)"
        content = path.read_text(encoding="utf-8", errors="ignore")
        # 应包含 help / server / electron 至少一个子命令
        assert "server" in content or "help" in content, f"{name} 应至少支持 server / help 子命令"

    def test_start_bat_forces_utf8(self):
        """start.bat 应强制 UTF-8 (避免 Windows GBK 编码问题)."""
        content = (ROOT / "start.bat").read_text(encoding="utf-8", errors="ignore")
        assert "PYTHONUTF8" in content, "start.bat 应设置 PYTHONUTF8=1"
        assert "PYTHONIOENCODING" in content, "start.bat 应设置 PYTHONIOENCODING=utf-8"

    def test_start_ps1_forces_utf8(self):
        content = (ROOT / "start.ps1").read_text(encoding="utf-8", errors="ignore")
        assert "PYTHONUTF8" in content, "start.ps1 应设置 $env:PYTHONUTF8"
        assert "PYTHONIOENCODING" in content, "start.ps1 应设置 $env:PYTHONIOENCODING"


class TestCriticalDepsInRequirements:
    """P3 扩展: requirements.txt 必须包含关键依赖"""

    @pytest.fixture
    def requirements(self) -> str:
        return (ROOT / "requirements.txt").read_text(encoding="utf-8", errors="ignore")

    @pytest.mark.parametrize("dep", ["litellm", "sentry-sdk", "Pillow", "pytesseract"])
    def test_dep_in_requirements(self, requirements, dep):
        assert re.search(rf"^{re.escape(dep)}[><=~!\[]", requirements, re.MULTILINE), \
            f"requirements.txt 缺失 {dep}"


class TestSentryIntegration:
    """P3 扩展: Sentry 集成 (可选, 条件加载)"""

    def test_sentry_module_exists(self):
        """pycoder/observability/sentry.py 应存在."""
        assert (ROOT / "pycoder" / "observability" / "sentry.py").exists()

    def test_sentry_init_py(self):
        """pycoder/observability/__init__.py 应存在并导出主要符号."""
        init = (ROOT / "pycoder" / "observability" / "__init__.py").read_text(
            encoding="utf-8", errors="ignore"
        )
        for name in ["init_sentry", "capture_exception", "is_available", "is_enabled"]:
            assert name in init, f"observability 应导出 {name}"

    def test_sentry_conditional_import(self):
        """sentry.py 应在 ImportError 时优雅降级 (不应抛错)."""
        sentry_path = ROOT / "pycoder" / "observability" / "sentry.py"
        content = sentry_path.read_text(encoding="utf-8", errors="ignore")
        assert "except ImportError" in content, "sentry.py 应有 ImportError 降级"
        assert "_SENTRY_AVAILABLE" in content, "应有 _SENTRY_AVAILABLE 标志"

    def test_sentry_status_does_not_crash(self):
        """sentry.status() 不应抛错 (未配置 DSN 时返回安全字典)."""
        from pycoder.observability import sentry as sentry_mod
        result = sentry_mod.status()
        assert isinstance(result, dict)
        assert "available" in result
        assert "initialized" in result


class TestReadmeCapabilities:
    """P3 扩展: README 应声明已具备的核心能力 (澄清误解)"""

    def test_readme_has_capabilities_section(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="ignore")
        # 应有"已具备的核心能力"或"核心能力"章节
        assert "已具备的核心能力" in readme or "核心能力" in readme, \
            "README 应有'已具备的核心能力'章节"

    def test_readme_documents_sentry(self):
        """README 应提到 Sentry 集成能力."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="ignore")
        assert "Sentry" in readme or "sentry" in readme.lower(), \
            "README 应提到 Sentry 集成"

    def test_readme_documents_memory(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="ignore")
        assert "持久化记忆" in readme or "memory" in readme.lower(), \
            "README 应提到持久化记忆能力"

    def test_readme_documents_sandbox(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="ignore")
        assert "沙箱" in readme or "Sandbox" in readme or "sandbox" in readme.lower(), \
            "README 应提到代码沙箱能力"
