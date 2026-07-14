"""project_helpers 模块覆盖率测试 — 项目树/Git 状态/Diff 预览

覆盖 pycoder.server.project_helpers:
- _get_project_tree: 递归扫描目录树
- _get_git_status: 获取 Git 仓库状态
- _get_diff_preview: 生成 diff 预览

注意：源文件未导入 subprocess（疑似 bug），通过 monkeypatch 注入 subprocess
模块属性以使函数可调用。本测试不修改源文件。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import pycoder.server.project_helpers as ph_mod


@pytest.fixture
def inject_subprocess(monkeypatch):
    """注入 subprocess 到 project_helpers 模块（源文件未导入 subprocess）。

    使用 raising=False 因为模块本身没有 subprocess 属性。
    """
    monkeypatch.setattr(ph_mod, "subprocess", subprocess, raising=False)
    return subprocess


# ══════════════════════════════════════════════════════════
# _get_project_tree
# ══════════════════════════════════════════════════════════


class TestGetProjectTree:
    async def test_default_path(self, inject_subprocess, tmp_path, monkeypatch):
        (tmp_path / "file.py").write_text("x")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "child.py").write_text("y")
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: str(tmp_path))
        result = await ph_mod._get_project_tree()
        assert "children" in result
        assert result["root"] == str(tmp_path.resolve())
        names = [c["name"] for c in result["children"]]
        assert "file.py" in names
        assert "subdir" in names

    async def test_explicit_path(self, inject_subprocess, tmp_path):
        (tmp_path / "a.py").write_text("x")
        result = await ph_mod._get_project_tree(path=str(tmp_path))
        assert result["root"] == str(tmp_path.resolve())
        names = [c["name"] for c in result["children"]]
        assert "a.py" in names

    async def test_nonexistent_path(self, inject_subprocess, tmp_path):
        result = await ph_mod._get_project_tree(path=str(tmp_path / "nonexistent"))
        assert "error" in result
        assert "目录不存在" in result["error"]
        assert result["children"] == []

    async def test_max_depth_truncation(self, inject_subprocess, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "b").mkdir()
        result = await ph_mod._get_project_tree(path=str(tmp_path), max_depth=1)

        def find_truncated(node):
            if node.get("truncated"):
                return True
            for child in node.get("children", []):
                if find_truncated(child):
                    return True
            return False

        assert find_truncated(result)

    async def test_ignore_dirs(self, inject_subprocess, tmp_path):
        """IGNORE_DIRS 中的目录应被跳过"""
        (tmp_path / ".git").mkdir()
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "real.py").write_text("x")
        result = await ph_mod._get_project_tree(path=str(tmp_path))
        names = [c["name"] for c in result["children"]]
        assert ".git" not in names
        assert "__pycache__" not in names
        assert "node_modules" not in names
        assert "real.py" in names

    async def test_ignore_extensions(self, inject_subprocess, tmp_path):
        """IGNORE_EXTS 中的文件应被跳过"""
        (tmp_path / "x.pyc").write_text("x")
        (tmp_path / "y.pyo").write_text("y")
        (tmp_path / "z.py").write_text("z")
        result = await ph_mod._get_project_tree(path=str(tmp_path))
        names = [c["name"] for c in result["children"]]
        assert "x.pyc" not in names
        assert "y.pyo" not in names
        assert "z.py" in names

    async def test_file_metadata(self, inject_subprocess, tmp_path):
        (tmp_path / "f.txt").write_text("hello")
        result = await ph_mod._get_project_tree(path=str(tmp_path))
        file_entry = next(c for c in result["children"] if c["name"] == "f.txt")
        assert file_entry["type"] == "file"
        assert file_entry["size"] == 5
        assert "modified_at" in file_entry
        assert file_entry["path"] == "f.txt"

    async def test_root_path_empty_string(self, inject_subprocess, tmp_path):
        """根目录的 path 字段应为空字符串"""
        (tmp_path / "f.py").write_text("x")
        result = await ph_mod._get_project_tree(path=str(tmp_path))
        assert result["path"] == ""

    async def test_subdir_path_relative_to_root(self, inject_subprocess, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "f.py").write_text("x")
        result = await ph_mod._get_project_tree(path=str(tmp_path))
        sub_entry = next(c for c in result["children"] if c["name"] == "sub")
        assert sub_entry["path"] == "sub"

    async def test_permission_error_caught(self, inject_subprocess, tmp_path, monkeypatch):
        """iterdir 抛 PermissionError 时应返回错误节点"""

        def raise_perm(self):
            raise PermissionError("denied")

        monkeypatch.setattr(ph_mod.Path, "iterdir", raise_perm)
        result = await ph_mod._get_project_tree(path=str(tmp_path))
        # 根节点应有 error 字段
        assert result.get("error") == "权限拒绝"

    async def test_dirs_sorted_before_files(self, inject_subprocess, tmp_path):
        """目录应排在文件之前"""
        (tmp_path / "zfile.py").write_text("x")
        (tmp_path / "adir").mkdir()
        (tmp_path / "bdir").mkdir()
        result = await ph_mod._get_project_tree(path=str(tmp_path))
        names = [c["name"] for c in result["children"]]
        # 目录应在前
        assert names.index("adir") < names.index("zfile.py")
        assert names.index("bdir") < names.index("zfile.py")


# ══════════════════════════════════════════════════════════
# _get_git_status
# ══════════════════════════════════════════════════════════


class TestGetGitStatus:
    async def test_not_git_repo(self, inject_subprocess, monkeypatch):
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/some/path")
        mock_run = MagicMock(return_value=MagicMock(returncode=1, stdout="", stderr=""))
        monkeypatch.setattr(subprocess, "run", mock_run)
        result = await ph_mod._get_git_status()
        assert result["branch"] == ""
        assert result["error"] == "不是 Git 仓库"

    async def test_git_not_installed(self, inject_subprocess, monkeypatch):
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/some/path")

        def raise_fnf(*a, **k):
            raise FileNotFoundError()

        monkeypatch.setattr(subprocess, "run", raise_fnf)
        result = await ph_mod._get_git_status()
        assert result["error"] == "Git 未安装"

    async def test_git_timeout(self, inject_subprocess, monkeypatch):
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/some/path")

        def raise_timeout(*a, **k):
            raise subprocess.TimeoutExpired(cmd="git", timeout=5)

        monkeypatch.setattr(subprocess, "run", raise_timeout)
        result = await ph_mod._get_git_status()
        assert result["error"] == "Git 命令超时"

    async def test_general_exception(self, inject_subprocess, monkeypatch):
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/some/path")

        def raise_exc(*a, **k):
            raise ValueError("unexpected")

        monkeypatch.setattr(subprocess, "run", raise_exc)
        result = await ph_mod._get_git_status()
        assert "unexpected" in result["error"]

    async def test_success_with_branch_and_remote(self, inject_subprocess, monkeypatch):
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/repo")
        rev_parse_resp = MagicMock(returncode=0, stdout=".git\n", stderr="")
        branch_resp = MagicMock(returncode=0, stdout="main\n", stderr="")
        diff_resp = MagicMock(returncode=0, stdout="file1.py\nfile2.py\n", stderr="")
        staged_resp = MagicMock(returncode=0, stdout="staged.py\n", stderr="")
        untracked_resp = MagicMock(returncode=0, stdout="new.py\n", stderr="")
        remote_resp = MagicMock(returncode=0, stdout="origin\turl\n", stderr="")
        rev_list_resp = MagicMock(returncode=0, stdout="2 5\n", stderr="")
        mock_run = MagicMock(
            side_effect=[
                rev_parse_resp,
                branch_resp,
                diff_resp,
                staged_resp,
                untracked_resp,
                remote_resp,
                rev_list_resp,
            ]
        )
        monkeypatch.setattr(subprocess, "run", mock_run)
        result = await ph_mod._get_git_status()
        assert result["branch"] == "main"
        assert "file1.py" in result["modified"]
        assert "file2.py" in result["modified"]
        assert "staged.py" in result["staged"]
        assert "new.py" in result["untracked"]
        assert result["has_remote"] is True
        assert result["behind"] == 2
        assert result["ahead"] == 5

    async def test_success_no_remote(self, inject_subprocess, monkeypatch):
        """无 remote 时 has_remote 为 False"""
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/repo")
        rev_parse_resp = MagicMock(returncode=0, stdout=".git\n", stderr="")
        branch_resp = MagicMock(returncode=0, stdout="main\n", stderr="")
        diff_resp = MagicMock(returncode=0, stdout="", stderr="")
        staged_resp = MagicMock(returncode=0, stdout="", stderr="")
        untracked_resp = MagicMock(returncode=0, stdout="", stderr="")
        remote_resp = MagicMock(returncode=0, stdout="", stderr="")
        rev_list_resp = MagicMock(returncode=1, stdout="", stderr="")  # no upstream
        mock_run = MagicMock(
            side_effect=[
                rev_parse_resp,
                branch_resp,
                diff_resp,
                staged_resp,
                untracked_resp,
                remote_resp,
                rev_list_resp,
            ]
        )
        monkeypatch.setattr(subprocess, "run", mock_run)
        result = await ph_mod._get_git_status()
        assert result["has_remote"] is False
        assert result["ahead"] == 0
        assert result["behind"] == 0

    async def test_with_explicit_project_path(self, inject_subprocess, monkeypatch):
        rev_parse_resp = MagicMock(returncode=1, stdout="", stderr="")
        mock_run = MagicMock(return_value=rev_parse_resp)
        monkeypatch.setattr(subprocess, "run", mock_run)
        result = await ph_mod._get_git_status(project_path="/explicit/path")
        assert result["error"] == "不是 Git 仓库"
        # 验证使用了传入的 cwd
        _, kwargs = mock_run.call_args
        assert kwargs["cwd"] == "/explicit/path"

    async def test_branch_command_fails(self, inject_subprocess, monkeypatch):
        """branch 命令失败时 branch 保持空字符串"""
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/repo")
        rev_parse_resp = MagicMock(returncode=0, stdout=".git\n", stderr="")
        branch_resp = MagicMock(returncode=1, stdout="", stderr="error")
        diff_resp = MagicMock(returncode=0, stdout="", stderr="")
        staged_resp = MagicMock(returncode=0, stdout="", stderr="")
        untracked_resp = MagicMock(returncode=0, stdout="", stderr="")
        remote_resp = MagicMock(returncode=0, stdout="", stderr="")
        mock_run = MagicMock(
            side_effect=[
                rev_parse_resp,
                branch_resp,
                diff_resp,
                staged_resp,
                untracked_resp,
                remote_resp,
            ]
        )
        monkeypatch.setattr(subprocess, "run", mock_run)
        result = await ph_mod._get_git_status()
        assert result["branch"] == ""
        # branch 为空时不调用 rev-list

    async def test_rev_list_invalid_format(self, inject_subprocess, monkeypatch):
        """rev-list 返回非 2 字段格式时不应崩溃"""
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/repo")
        rev_parse_resp = MagicMock(returncode=0, stdout=".git\n", stderr="")
        branch_resp = MagicMock(returncode=0, stdout="main\n", stderr="")
        diff_resp = MagicMock(returncode=0, stdout="", stderr="")
        staged_resp = MagicMock(returncode=0, stdout="", stderr="")
        untracked_resp = MagicMock(returncode=0, stdout="", stderr="")
        remote_resp = MagicMock(returncode=0, stdout="origin\turl\n", stderr="")
        # 返回 1 个字段，不匹配 len(parts) == 2
        rev_list_resp = MagicMock(returncode=0, stdout="5\n", stderr="")
        mock_run = MagicMock(
            side_effect=[
                rev_parse_resp,
                branch_resp,
                diff_resp,
                staged_resp,
                untracked_resp,
                remote_resp,
                rev_list_resp,
            ]
        )
        monkeypatch.setattr(subprocess, "run", mock_run)
        result = await ph_mod._get_git_status()
        # ahead/behind 保持默认 0
        assert result["ahead"] == 0
        assert result["behind"] == 0


# ══════════════════════════════════════════════════════════
# _get_diff_preview
# ══════════════════════════════════════════════════════════


class TestGetDiffPreview:
    async def test_no_changes(self, inject_subprocess, monkeypatch):
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/repo")
        mock_run = MagicMock(
            return_value=MagicMock(returncode=0, stdout="", stderr="")
        )
        monkeypatch.setattr(subprocess, "run", mock_run)
        result = await ph_mod._get_diff_preview()
        assert result["summary"] == "没有变更"
        assert result["files"] == []
        assert result["total_additions"] == 0

    async def test_diff_command_failure(self, inject_subprocess, monkeypatch):
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/repo")
        mock_run = MagicMock(
            return_value=MagicMock(returncode=1, stdout="", stderr="git error")
        )
        monkeypatch.setattr(subprocess, "run", mock_run)
        result = await ph_mod._get_diff_preview()
        assert "error" in result
        assert "git error" in result["error"]

    async def test_git_not_installed(self, inject_subprocess, monkeypatch):
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/repo")

        def raise_fnf(*a, **k):
            raise FileNotFoundError()

        monkeypatch.setattr(subprocess, "run", raise_fnf)
        result = await ph_mod._get_diff_preview()
        assert result["error"] == "Git 未安装"

    async def test_diff_timeout(self, inject_subprocess, monkeypatch):
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/repo")

        def raise_timeout(*a, **k):
            raise subprocess.TimeoutExpired(cmd="git", timeout=10)

        monkeypatch.setattr(subprocess, "run", raise_timeout)
        result = await ph_mod._get_diff_preview()
        assert result["error"] == "Diff 命令超时"

    async def test_general_exception(self, inject_subprocess, monkeypatch):
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/repo")

        def raise_exc(*a, **k):
            raise ValueError("oops")

        monkeypatch.setattr(subprocess, "run", raise_exc)
        result = await ph_mod._get_diff_preview()
        assert "oops" in result["error"]

    async def test_diff_with_single_file(self, inject_subprocess, monkeypatch):
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/repo")
        diff_text = (
            "diff --git a/file1.py b/file1.py\n"
            "index abc..def 100644\n"
            "--- a/file1.py\n"
            "+++ b/file1.py\n"
            "@@ -1,3 +1,4 @@\n"
            " line1\n"
            "+added line\n"
            " line2\n"
            "-line3\n"
        )
        mock_run = MagicMock(
            return_value=MagicMock(returncode=0, stdout=diff_text, stderr="")
        )
        monkeypatch.setattr(subprocess, "run", mock_run)
        result = await ph_mod._get_diff_preview()
        assert len(result["files"]) == 1
        assert result["files"][0]["path"] == "file1.py"
        assert result["files"][0]["additions"] == 1
        assert result["files"][0]["deletions"] == 1
        assert result["total_additions"] == 1
        assert result["total_deletions"] == 1
        assert "1 个文件变更" in result["summary"]

    async def test_diff_with_multiple_files(self, inject_subprocess, monkeypatch):
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/repo")
        diff_text = (
            "diff --git a/file1.py b/file1.py\n"
            "--- a/file1.py\n"
            "+++ b/file1.py\n"
            "@@ -1 +1,2 @@\n"
            "+added1\n"
            "diff --git a/file2.py b/file2.py\n"
            "--- a/file2.py\n"
            "+++ b/file2.py\n"
            "@@ -1 +1,2 @@\n"
            "+added2\n"
        )
        mock_run = MagicMock(
            return_value=MagicMock(returncode=0, stdout=diff_text, stderr="")
        )
        monkeypatch.setattr(subprocess, "run", mock_run)
        result = await ph_mod._get_diff_preview()
        assert len(result["files"]) == 2
        assert result["total_additions"] == 2
        assert "2 个文件变更" in result["summary"]

    async def test_diff_staged_flag(self, inject_subprocess, monkeypatch):
        """staged=True 时应附加 --cached"""
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/repo")
        mock_run = MagicMock(
            return_value=MagicMock(returncode=0, stdout="", stderr="")
        )
        monkeypatch.setattr(subprocess, "run", mock_run)
        await ph_mod._get_diff_preview(staged=True)
        args = mock_run.call_args[0][0]
        assert "--cached" in args

    async def test_diff_with_file_path(self, inject_subprocess, monkeypatch):
        """指定 file_path 时应附加到命令"""
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/repo")
        mock_run = MagicMock(
            return_value=MagicMock(returncode=0, stdout="", stderr="")
        )
        monkeypatch.setattr(subprocess, "run", mock_run)
        await ph_mod._get_diff_preview(file_path="myfile.py")
        args = mock_run.call_args[0][0]
        assert "myfile.py" in args

    async def test_diff_staged_and_file_path(self, inject_subprocess, monkeypatch):
        """staged=True 与 file_path 同时指定"""
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/repo")
        mock_run = MagicMock(
            return_value=MagicMock(returncode=0, stdout="", stderr="")
        )
        monkeypatch.setattr(subprocess, "run", mock_run)
        await ph_mod._get_diff_preview(file_path="x.py", staged=True)
        args = mock_run.call_args[0][0]
        assert "--cached" in args
        assert "x.py" in args

    async def test_diff_ignores_header_lines(self, inject_subprocess, monkeypatch):
        """+++ 和 --- 行不计入 additions/deletions"""
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/repo")
        diff_text = (
            "diff --git a/f.py b/f.py\n"
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1 +1,2 @@\n"
            "+real addition\n"
        )
        mock_run = MagicMock(
            return_value=MagicMock(returncode=0, stdout=diff_text, stderr="")
        )
        monkeypatch.setattr(subprocess, "run", mock_run)
        result = await ph_mod._get_diff_preview()
        # 仅 +real addition 计为 addition
        assert result["total_additions"] == 1
        assert result["total_deletions"] == 0

    async def test_diff_with_deletions_only(self, inject_subprocess, monkeypatch):
        monkeypatch.setattr(ph_mod.os, "getcwd", lambda: "/repo")
        diff_text = (
            "diff --git a/f.py b/f.py\n"
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1 +0,0 @@\n"
            "-removed line\n"
        )
        mock_run = MagicMock(
            return_value=MagicMock(returncode=0, stdout=diff_text, stderr="")
        )
        monkeypatch.setattr(subprocess, "run", mock_run)
        result = await ph_mod._get_diff_preview()
        assert result["total_additions"] == 0
        assert result["total_deletions"] == 1
