"""P2-1: AutoPatch 单元测试"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def sample_workspace():
    """创建测试用工作区"""
    tmp = Path(tempfile.mkdtemp(prefix="autopatch_test_"))
    (tmp / "src").mkdir()
    (tmp / "src" / "main.py").write_text("def hello():\n    return 'old'\n", encoding="utf-8")
    (tmp / "test.txt").write_text("original\n", encoding="utf-8")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


def test_generate_modify_patch(sample_workspace):
    """修改文件应生成正确的 unified diff"""
    from pycoder.python.auto_patch import FileChange, PatchGenerator

    gen = PatchGenerator(project_root=sample_workspace)
    change = FileChange(
        file_path="src/main.py",
        old_content="def hello():\n    return 'old'\n",
        new_content="def hello():\n    return 'new'\n",
        operation="modify",
    )
    patch = gen.generate(
        title="修改 hello 函数",
        description="将返回值改为 new",
        changes=[change],
    )
    assert patch.id.startswith("patch_")
    assert "src/main.py" in patch.diff
    assert "-    return 'old'" in patch.diff
    assert "+    return 'new'" in patch.diff


def test_generate_create_patch(sample_workspace):
    """新建文件应生成正确的 diff"""
    from pycoder.python.auto_patch import FileChange, PatchGenerator

    gen = PatchGenerator(project_root=sample_workspace)
    change = FileChange(
        file_path="src/new.py",
        new_content="def new_func():\n    pass\n",
        operation="create",
    )
    patch = gen.generate(title="新建文件", description="", changes=[change])
    assert "+++ src/new.py" in patch.diff
    assert "+def new_func():" in patch.diff


def test_generate_delete_patch(sample_workspace):
    """删除文件应生成正确的 diff"""
    from pycoder.python.auto_patch import FileChange, PatchGenerator

    gen = PatchGenerator(project_root=sample_workspace)
    change = FileChange(
        file_path="test.txt",
        old_content="original\n",
        operation="delete",
    )
    patch = gen.generate(title="删除文件", description="", changes=[change])
    assert "--- test.txt" in patch.diff
    assert "-original" in patch.diff


def test_save_and_load_patch(sample_workspace):
    """保存和加载补丁应保持元信息一致"""
    from pycoder.python.auto_patch import FileChange, PatchGenerator

    gen = PatchGenerator(project_root=sample_workspace)
    change = FileChange(
        file_path="src/main.py",
        old_content="old\n",
        new_content="new\n",
        operation="modify",
    )
    patch = gen.generate(
        title="测试补丁",
        description="描述信息",
        changes=[change],
        author="tester",
    )
    saved_path = gen.save_to_file(patch)
    assert saved_path.exists()

    loaded = gen.load_from_file(saved_path)
    assert loaded.id == patch.id
    assert loaded.title == "测试补丁"
    assert loaded.author == "tester"
    assert loaded.diff.strip()  # 非空


def test_apply_modify_patch(sample_workspace):
    """应用修改补丁应成功修改文件"""
    from pycoder.python.auto_patch import FileChange, PatchApplier, PatchGenerator

    gen = PatchGenerator(project_root=sample_workspace)
    applier = PatchApplier(project_root=sample_workspace)
    change = FileChange(
        file_path="src/main.py",
        old_content="def hello():\n    return 'old'\n",
        new_content="def hello():\n    return 'modified'\n",
        operation="modify",
    )
    patch = gen.generate(title="应用测试", description="", changes=[change])

    result = applier.apply(patch, dry_run=False)
    assert result["success"]
    assert "src/main.py" in result["applied"]

    # 验证文件已修改
    content = (sample_workspace / "src" / "main.py").read_text(encoding="utf-8")
    assert "modified" in content


def test_apply_create_patch(sample_workspace):
    """应用新建补丁应创建文件"""
    from pycoder.python.auto_patch import FileChange, PatchApplier, PatchGenerator

    gen = PatchGenerator(project_root=sample_workspace)
    applier = PatchApplier(project_root=sample_workspace)
    change = FileChange(
        file_path="src/new_module.py",
        new_content="# new module\n",
        operation="create",
    )
    patch = gen.generate(title="新建", description="", changes=[change])

    result = applier.apply(patch, dry_run=False)
    assert result["success"]
    assert (sample_workspace / "src" / "new_module.py").exists()


def test_apply_delete_patch(sample_workspace):
    """应用删除补丁应删除文件"""
    from pycoder.python.auto_patch import FileChange, PatchApplier, PatchGenerator

    gen = PatchGenerator(project_root=sample_workspace)
    applier = PatchApplier(project_root=sample_workspace)
    change = FileChange(
        file_path="test.txt",
        old_content="original\n",
        operation="delete",
    )
    patch = gen.generate(title="删除", description="", changes=[change])

    result = applier.apply(patch, dry_run=False)
    assert result["success"]
    assert not (sample_workspace / "test.txt").exists()


def test_apply_dry_run_does_not_modify(sample_workspace):
    """dry_run 不应实际修改文件"""
    from pycoder.python.auto_patch import FileChange, PatchApplier, PatchGenerator

    gen = PatchGenerator(project_root=sample_workspace)
    applier = PatchApplier(project_root=sample_workspace)
    change = FileChange(
        file_path="src/main.py",
        old_content="def hello():\n    return 'old'\n",
        new_content="def hello():\n    return 'new'\n",
        operation="modify",
    )
    patch = gen.generate(title="dry", description="", changes=[change])

    result = applier.apply(patch, dry_run=True)
    assert result["success"]
    assert result["dry_run"]
    # 文件未被修改
    content = (sample_workspace / "src" / "main.py").read_text(encoding="utf-8")
    assert "'old'" in content


def test_apply_creates_backup(sample_workspace):
    """应用补丁应创建备份"""
    from pycoder.python.auto_patch import FileChange, PatchApplier, PatchGenerator

    gen = PatchGenerator(project_root=sample_workspace)
    applier = PatchApplier(project_root=sample_workspace)
    change = FileChange(
        file_path="src/main.py",
        old_content="def hello():\n    return 'old'\n",
        new_content="def hello():\n    return 'new'\n",
        operation="modify",
    )
    patch = gen.generate(title="备份测试", description="", changes=[change])

    result = applier.apply(patch, dry_run=False)
    assert result["backup"] is not None
    backup_dir = Path(result["backup"])
    assert backup_dir.exists()
    # 备份内容应包含原始内容
    backup_file = backup_dir / "src" / "main.py"
    assert backup_file.exists()
    assert "old" in backup_file.read_text(encoding="utf-8")


def test_list_patches(sample_workspace):
    """列出补丁应返回所有 .patch 文件"""
    from pycoder.python.auto_patch import FileChange, PatchGenerator

    gen = PatchGenerator(project_root=sample_workspace)
    # 清理可能存在的历史 patches
    for old in gen._patches_dir.glob("*.patch"):
        old.unlink()

    for i in range(3):
        change = FileChange(
            file_path=f"file_{i}.py",
            new_content=f"# {i}\n",
            operation="create",
        )
        patch = gen.generate(title=f"patch {i}", description="", changes=[change])
        gen.save_to_file(patch)

    patches = gen.list_patches()
    assert len(patches) == 3


def test_generate_pr_draft_basic(sample_workspace):
    """PR 草稿应包含标题、描述、文件列表"""
    from pycoder.python.auto_patch import (
        FileChange,
        PatchGenerator,
        generate_pr_draft,
    )

    gen = PatchGenerator(project_root=sample_workspace)
    changes = [
        FileChange(
            file_path="src/main.py",
            old_content="old",
            new_content="new",
            operation="modify",
        ),
        FileChange(
            file_path="tests/test_main.py",
            new_content="def test_main():\n    pass\n",
            operation="create",
        ),
    ]
    patch = gen.generate(title="添加新功能", description="详细描述", changes=changes)
    patch.branch = "pycoder/test"

    pr = generate_pr_draft(patch)
    assert "添加新功能" in pr.title or "feat" in pr.title.lower()
    assert "src/main.py" in pr.body
    assert "tests/test_main.py" in pr.body
    assert "test" in pr.labels
    assert pr.head == "pycoder/test"


def test_pr_draft_classifies_labels(sample_workspace):
    """PR 草稿应基于文件路径和标题自动分类"""
    from pycoder.python.auto_patch import (
        FileChange,
        PatchGenerator,
        generate_pr_draft,
    )

    gen = PatchGenerator(project_root=sample_workspace)

    # Bug fix 标题 + 代码文件
    changes = [
        FileChange(
            file_path="pycoder/server/api.py",
            new_content="# fixed\n",
            operation="create",
        ),
    ]
    patch = gen.generate(title="Fix bug", description="", changes=changes)

    pr = generate_pr_draft(patch)
    assert "bug" in pr.labels
    assert pr.title.lower().startswith("fix")


def test_pr_draft_includes_diff_stats(sample_workspace):
    """PR 草稿应包含 diff 统计"""
    from pycoder.python.auto_patch import (
        FileChange,
        PatchGenerator,
        generate_pr_draft,
    )

    gen = PatchGenerator(project_root=sample_workspace)
    changes = [
        FileChange(
            file_path="src/main.py",
            old_content="line1\nline2\n",
            new_content="line1\nline2_new\nline3\n",
            operation="modify",
        ),
    ]
    patch = gen.generate(title="测试", description="", changes=changes)

    pr = generate_pr_draft(patch)
    # 应包含 +X / -Y 统计
    assert "+" in pr.body
    assert "-" in pr.body


def test_git_integration_is_repo(sample_workspace):
    """Git 集成应能识别 git 仓库"""
    import subprocess

    from pycoder.python.auto_patch import GitIntegration

    # 初始化 git 仓库
    subprocess.run(["git", "init"], cwd=sample_workspace, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=sample_workspace,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=sample_workspace,
        capture_output=True,
    )

    git = GitIntegration(repo_root=sample_workspace)
    assert git.is_repo()


def test_git_create_and_commit(sample_workspace):
    """应能创建分支并提交"""
    import subprocess

    from pycoder.python.auto_patch import GitIntegration

    # 初始化 git
    subprocess.run(["git", "init"], cwd=sample_workspace, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=sample_workspace,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=sample_workspace,
        capture_output=True,
    )
    # 初始 commit
    subprocess.run(["git", "add", "-A"], cwd=sample_workspace, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=sample_workspace,
        capture_output=True,
    )

    git = GitIntegration(repo_root=sample_workspace)
    branch = git.create_branch("pycoder/test123", base="master")
    assert branch == "pycoder/test123"

    # 创建新文件后提交
    (sample_workspace / "new.txt").write_text("new", encoding="utf-8")
    assert git.has_changes()
    sha = git.commit("add new file")
    assert len(sha) == 40  # SHA-1 长度
