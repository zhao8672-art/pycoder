"""H7 测试：git.py 异步化 + Pydantic 入参

验证：
1. 所有 POST 端点使用 Pydantic BaseModel 而非 ``req: dict``
2. 网络/IO 相关 git 操作通过 ``_run_git`` 包装为 asyncio.to_thread
3. 无可变默认值（``list[str] = []`` 等反模式）
4. Pydantic 请求模型字段定义正确
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

GIT_ROUTER_PATH = (
    Path(__file__).resolve().parents[2]
    / "pycoder" / "server" / "routers" / "git.py"
)


def _load_source() -> str:
    return GIT_ROUTER_PATH.read_text(encoding="utf-8")


def _load_ast() -> ast.Module:
    return ast.parse(_load_source())


# ══════════════════════════════════════════════════════════
# 1. Pydantic 模型验证
# ══════════════════════════════════════════════════════════


class TestPydanticModels:
    """验证 H7 定义的 Pydantic 请求模型"""

    def test_all_required_models_exist(self):
        """H7 要求的所有 Pydantic 模型应存在"""
        from pycoder.server.routers import git as git_mod

        required = [
            "RemoteBranchRequest",
            "StashRequest",
            "FilesRequest",
            "StashIndexRequest",
            "BranchNameRequest",
            "MergeRequest",
            "CommitHashRequest",
            "RebaseRequest",
            "RemoteAddRequest",
            "RemoteNameRequest",
            "ConflictResolveRequest",
            "GitignoreRequest",
            "GitInitRequest",
            "FetchRequest",
        ]
        for name in required:
            assert hasattr(git_mod, name), f"缺少 H7 Pydantic 模型: {name}"

    def test_stash_request_has_optional_fields(self):
        """StashRequest 应包含 action/message/index 三个字段"""
        from pycoder.server.routers.git import StashRequest

        req = StashRequest()
        assert req.action == "push"
        assert req.message == "WIP"
        assert req.index == 0

    def test_files_request_uses_field_default_factory(self):
        """FilesRequest.files 应使用 Field(default_factory=list) 避免可变默认值"""
        from pycoder.server.routers.git import FilesRequest

        req = FilesRequest()
        assert req.files == []
        # 验证两个实例不共享 list（可变默认值 bug 检测）
        req2 = FilesRequest()
        req2.files.append("a.py")
        assert req.files == []  # 不应被污染

    def test_commit_request_no_mutable_default(self):
        """CommitRequest.files 应使用 Field(default_factory=list)"""
        from pycoder.server.routers.git import CommitRequest

        req1 = CommitRequest()
        req2 = CommitRequest()
        req1.files.append("x")
        assert req2.files == []  # 隔离验证


# ══════════════════════════════════════════════════════════
# 2. 端点签名验证（无 req: dict）
# ══════════════════════════════════════════════════════════


class TestEndpointSignatures:
    """验证所有 POST 端点不再使用 ``req: dict``"""

    def test_no_req_dict_in_post_endpoints(self):
        """源码中不应出现 ``req: dict`` 参数（注释除外）"""
        source = _load_source()
        lines = source.splitlines()
        violations = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # 跳过注释行
            if stripped.startswith("#"):
                continue
            # 检测函数签名中的 req: dict
            if "req: dict" in line and "def " in line:
                violations.append(f"L{i}: {line.strip()}")
        assert not violations, (
            "H7: 以下端点仍使用 req: dict:\n" + "\n".join(violations)
        )

    def test_no_req_dict_get_pattern(self):
        """源码中不应出现 ``(req or {}).get(`` 或 ``req.get(`` 模式"""
        source = _load_source()
        assert "(req or {}).get(" not in source, "H7: 仍有 (req or {}).get() 用法"
        # req.get( 仅在 req 是 dict 时有效，Pydantic 模型应用 req.field
        # 但 StashRequest 等可能有 .get 方法吗？不会，BaseModel 无 get
        # 排除注释中的说明
        code_lines = [
            line for line in source.splitlines()
            if not line.strip().startswith("#")
        ]
        code = "\n".join(code_lines)
        assert "req.get(" not in code, "H7: 仍有 req.get() 用法（应改为 req.field）"


# ══════════════════════════════════════════════════════════
# 3. _run_git 异步包装验证
# ══════════════════════════════════════════════════════════


class TestRunGitWrapper:
    """验证 _run_git 辅助函数使用 asyncio.to_thread"""

    def test_run_git_function_exists(self):
        from pycoder.server.routers import git as git_mod

        assert hasattr(git_mod, "_run_git"), "_run_git 辅助函数应存在"

    def test_run_git_is_async(self):
        from pycoder.server.routers.git import _run_git

        assert inspect.iscoroutinefunction(_run_git), "_run_git 应为 async 函数"

    def test_run_git_uses_to_thread(self):
        """_run_git 源码应包含 asyncio.to_thread 调用"""
        source = inspect.getsource(
            __import__("pycoder.server.routers.git", fromlist=["_run_git"])._run_git
        )
        assert "asyncio.to_thread" in source, (
            "_run_git 应使用 asyncio.to_thread 包装同步 git 操作"
        )

    @pytest.mark.asyncio
    async def test_run_git_delegates_to_thread(self):
        """_run_git 应将同步函数调用委托到线程"""
        from pycoder.server.routers.git import _run_git

        calls = []

        def sync_fn(a, b, c=0):
            calls.append((a, b, c))
            return "ok"

        result = await _run_git(sync_fn, 1, 2, c=3)
        assert result == "ok"
        assert calls == [(1, 2, 3)]


# ══════════════════════════════════════════════════════════
# 4. 网络/IO 操作使用 _run_git 验证
# ══════════════════════════════════════════════════════════


class TestNetworkOpsAsync:
    """验证网络/IO 密集操作使用 _run_git 包装"""

    def test_push_uses_run_git(self):
        source = _load_source()
        # git_push 端点内应调用 _run_git(repo.git.push, ...)
        assert "await _run_git(repo.git.push" in source, (
            "git_push 应使用 _run_git 包装 repo.git.push"
        )

    def test_pull_uses_run_git(self):
        source = _load_source()
        assert "await _run_git(repo.git.pull" in source, (
            "git_pull 应使用 _run_git 包装 repo.git.pull"
        )

    def test_fetch_uses_run_git(self):
        source = _load_source()
        assert "await _run_git(repo.remotes[" in source, (
            "fetch_remote 应使用 _run_git 包装 remotes[].fetch"
        )

    def test_merge_uses_run_git(self):
        source = _load_source()
        assert "await _run_git(repo.git.merge" in source, (
            "merge_branch 应使用 _run_git 包装 repo.git.merge"
        )

    def test_stash_uses_run_git(self):
        source = _load_source()
        assert "await _run_git(repo.git.stash" in source, (
            "git_stash 应使用 _run_git 包装 repo.git.stash"
        )


# ══════════════════════════════════════════════════════════
# 5. 端点契约验证（Pydantic 模型接入）
# ══════════════════════════════════════════════════════════


class TestEndpointContracts:
    """验证关键端点接受 Pydantic 模型入参"""

    def test_merge_endpoint_uses_merge_request(self):
        source = _load_source()
        assert "async def merge_branch(req: MergeRequest" in source

    def test_push_endpoint_uses_remote_branch_request(self):
        source = _load_source()
        assert "async def git_push(req: RemoteBranchRequest" in source

    def test_stash_endpoint_uses_stash_request(self):
        source = _load_source()
        assert "async def git_stash(req: StashRequest" in source

    def test_stage_endpoint_uses_files_request(self):
        source = _load_source()
        assert "async def stage_files(req: FilesRequest" in source

    def test_revert_endpoint_uses_commit_hash_request(self):
        source = _load_source()
        assert "async def git_revert(req: CommitHashRequest" in source

    def test_rebase_endpoint_uses_rebase_request(self):
        source = _load_source()
        assert "async def git_rebase(req: RebaseRequest" in source

    def test_resolve_conflict_uses_conflict_resolve_request(self):
        source = _load_source()
        assert "async def resolve_conflict(req: ConflictResolveRequest" in source

    def test_git_init_uses_git_init_request(self):
        source = _load_source()
        assert "async def git_init(req: GitInitRequest" in source
