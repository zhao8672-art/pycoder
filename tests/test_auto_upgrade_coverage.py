"""
auto_upgrade.py 模块单元测试 — 覆盖率目标 ≥80%

覆盖内容:
  - 数据模型 HealthCheckResult / UpgradeResult / VersionInfo
  - 断点续传: save/load/clear_pending_upgrade
  - 版本检测: check_version (网络/降级本地 git), _compare_versions
  - 健康检查: health_check (Python/pip/git/disk/network 各项分支)
  - 升级执行: run_upgrade (dry_run/success/git_pull失败/pip失败/验证失败)
  - 快照: _create_snapshot, _rollback_snapshot, _cleanup_snapshot
  - 启动检测: check_pending_on_startup (各 stage 分支)
  - 差异对比: get_snapshot_diff, _get_current_commit
  - 状态查询: get_upgrade_status
  - _find_project_root

测试策略:
  - monkeypatch 将 PENDING_FILE/UPGRADE_DIR/SNAPSHOT_DIR 重定向到 tmp_path
  - mock subprocess.run / urllib.request.urlopen / shutil.disk_usage
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pycoder.server import auto_upgrade as au


# ── Fixtures ──

@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """将模块级路径常量重定向到 tmp_path"""
    pending = tmp_path / "pending_upgrade.json"
    upgrade_dir = tmp_path / "upgrades"
    snapshot_dir = upgrade_dir / "snapshots"
    monkeypatch.setattr(au, "PENDING_FILE", pending)
    monkeypatch.setattr(au, "UPGRADE_DIR", upgrade_dir)
    monkeypatch.setattr(au, "SNAPSHOT_DIR", snapshot_dir)
    return {"pending": pending, "upgrade_dir": upgrade_dir, "snapshot_dir": snapshot_dir}


@pytest.fixture
def mock_subprocess(monkeypatch):
    """统一 mock subprocess.run"""
    mock_run = MagicMock()
    monkeypatch.setattr(au._sp, "run", mock_run)
    return mock_run


# ── 数据模型 ──

def test_health_check_result_defaults():
    r = au.HealthCheckResult(passed=True)
    assert r.checks == {}
    assert r.warnings == []
    assert r.errors == []


def test_upgrade_result_defaults():
    r = au.UpgradeResult(success=False, from_version="1.0", to_version="2.0")
    assert r.steps == []
    assert r.error == ""
    assert r.duration_ms == 0


def test_version_info_defaults():
    v = au.VersionInfo(current="1.0", latest="2.0", has_update=True)
    assert v.release_notes == ""
    assert v.published_at == ""


# ── 断点续传 ──

def test_save_pending_upgrade_writes_file(isolated_paths):
    """save_pending_upgrade 写入 JSON 文件并创建目录"""
    result = au.save_pending_upgrade("1.0", "2.0", stage="init")
    assert result["from_version"] == "1.0"
    assert result["to_version"] == "2.0"
    assert result["stage"] == "init"
    assert "started_at" in result
    assert result["completed_steps"] == []
    assert isolated_paths["pending"].exists()
    data = json.loads(isolated_paths["pending"].read_text(encoding="utf-8"))
    assert data["from_version"] == "1.0"


def test_load_pending_upgrade_none_when_missing(isolated_paths):
    """PENDING_FILE 不存在时返回 None"""
    assert au.load_pending_upgrade() is None


def test_load_pending_upgrade_reads_existing(isolated_paths):
    """读取已存在的 pending 文件"""
    au.save_pending_upgrade("1.0", "2.0", "snapshot")
    data = au.load_pending_upgrade()
    assert data is not None
    assert data["from_version"] == "1.0"
    assert data["stage"] == "snapshot"


def test_load_pending_upgrade_handles_corrupt_file(isolated_paths):
    """PENDING_FILE 损坏时返回 None"""
    isolated_paths["pending"].parent.mkdir(parents=True, exist_ok=True)
    isolated_paths["pending"].write_text("not json{", encoding="utf-8")
    assert au.load_pending_upgrade() is None


def test_clear_pending_upgrade(isolated_paths):
    """clear_pending_upgrade 删除文件"""
    au.save_pending_upgrade("1.0", "2.0")
    assert isolated_paths["pending"].exists()
    au.clear_pending_upgrade()
    assert not isolated_paths["pending"].exists()


def test_clear_pending_upgrade_missing_file_ok(isolated_paths):
    """clear_pending_upgrade 对不存在的文件不抛异常"""
    au.clear_pending_upgrade()  # 不应抛异常


# ── _compare_versions ──

def test_compare_versions_greater():
    assert au._compare_versions("2.0.0", "1.0.0") == 1


def test_compare_versions_lesser():
    assert au._compare_versions("1.0.0", "2.0.0") == -1


def test_compare_versions_equal():
    assert au._compare_versions("1.2.3", "1.2.3") == 0


def test_compare_versions_invalid_returns_zero():
    """非法版本号返回 0（相等）"""
    assert au._compare_versions("abc", "1.0.0") == 0
    assert au._compare_versions("1.0", None) == 0


# ── check_version (GitHub API 成功) ──

def test_check_version_api_success(monkeypatch):
    """check_version 通过 GitHub API 检测到新版本"""
    fake_resp = MagicMock()
    fake_resp.read.return_value = json.dumps({
        "tag_name": "v9.9.9",
        "body": "release notes",
        "published_at": "2025-01-01",
    }).encode("utf-8")
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=None)
    fake_resp.status = 200

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: fake_resp)
    result = au.check_version()
    assert result.current is not None
    assert result.latest == "9.9.9"
    assert result.has_update is True
    assert "release notes" in result.release_notes
    assert result.published_at == "2025-01-01"


def test_check_version_api_no_update(monkeypatch):
    """check_version 当前版本等于最新时 has_update=False"""
    from pycoder import __version__
    fake_resp = MagicMock()
    fake_resp.read.return_value = json.dumps({
        "tag_name": "v" + __version__,
        "body": "",
        "published_at": "",
    }).encode("utf-8")
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=None)

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: fake_resp)
    result = au.check_version()
    assert result.has_update is False


def test_check_version_api_failure_fallback_local(monkeypatch):
    """API 异常时降级到本地 git ls-remote"""
    def urlopen_err(req, timeout=None):
        raise RuntimeError("network down")
    monkeypatch.setattr("urllib.request.urlopen", urlopen_err)

    # mock subprocess 返回 tag 列表
    mock_run = MagicMock()
    mock_run.return_value = MagicMock(
        stdout="abc123\trefs/tags/v1.0.0\n"
               "def456\trefs/tags/v1.2.0\n"
               "ghi789\trefs/tags/v2.0.0\n",
        stderr="",
        returncode=0,
    )
    monkeypatch.setattr(au._sp, "run", mock_run)
    result = au.check_version()
    # 应取最大版本 v2.0.0 → "2.0.0"
    assert result.latest == "2.0.0"
    assert "本地 Git 检测" in result.release_notes


def test_check_version_local_no_tags(monkeypatch):
    """本地 git 无 tag 返回 '未知'"""
    def urlopen_err(req, timeout=None):
        raise RuntimeError("network down")
    monkeypatch.setattr("urllib.request.urlopen", urlopen_err)
    mock_run = MagicMock()
    mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
    monkeypatch.setattr(au._sp, "run", mock_run)
    result = au.check_version()
    assert result.latest == "未知"
    assert "无法检测" in result.release_notes


def test_check_version_local_git_exception(monkeypatch):
    """git 命令本身异常时返回 '未知' 与错误信息"""
    def urlopen_err(req, timeout=None):
        raise RuntimeError("api down")
    monkeypatch.setattr("urllib.request.urlopen", urlopen_err)
    mock_run = MagicMock()
    mock_run.side_effect = FileNotFoundError("git not found")
    monkeypatch.setattr(au._sp, "run", mock_run)
    result = au.check_version()
    assert result.latest == "未知"
    assert "版本检测失败" in result.release_notes


# ── health_check ──

def test_health_check_python_version_too_low(monkeypatch):
    """Python 版本低于 3.10 时 health_check 返回 passed=False"""
    # 用 namedtuple 替代真实 sys.version_info, 避免破坏 pytest 内部 >= 比较检查
    from collections import namedtuple
    VI = namedtuple("version_info", "major minor micro releaselevel serial")
    monkeypatch.setattr(au.sys, "version_info", VI(3, 9, 0, "final", 0))
    # mock 其他依赖避免真实调用
    monkeypatch.setattr(au._sp, "run", lambda *a, **k: MagicMock(returncode=0, stdout="pip 22.0", stderr=""))
    monkeypatch.setattr("shutil.disk_usage", lambda p: MagicMock(free=10 * 1024 * 1024 * 1024))
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _FakeResp(200))
    result = au.health_check()
    assert result.passed is False
    assert any("Python 版本过低" in e for e in result.errors)


def test_health_check_python_ok(monkeypatch):
    """正常 Python 版本时 passed=True"""
    monkeypatch.setattr(au._sp, "run", lambda *a, **k: MagicMock(returncode=0, stdout="pip 22.0", stderr=""))
    monkeypatch.setattr("shutil.disk_usage", lambda p: MagicMock(free=10 * 1024 * 1024 * 1024))
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _FakeResp(200))
    result = au.health_check()
    assert result.passed is True
    assert result.checks["python"]["ok"] is True
    assert result.checks["pip"]["ok"] is True
    assert result.checks["git"]["ok"] is True
    assert result.checks["disk"]["ok"] is True
    assert result.checks["network"]["ok"] is True


def test_health_check_pip_unavailable(monkeypatch):
    """pip 不可用时 passed=False"""
    def fake_run(*a, **k):
        # 第一次是 pip --version
        if a and "pip" in a[0]:
            raise FileNotFoundError("no pip")
        return MagicMock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(au._sp, "run", fake_run)
    monkeypatch.setattr("shutil.disk_usage", lambda p: MagicMock(free=10 * 1024 * 1024 * 1024))
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _FakeResp(200))
    result = au.health_check()
    assert result.passed is False
    assert any("pip 不可用" in e for e in result.errors)


def test_health_check_git_dirty(monkeypatch):
    """Git 工作区脏时仅 warning, 不影响 passed"""
    def fake_run(*a, **k):
        if a and "status" in a[0]:
            return MagicMock(returncode=0, stdout=" M file.py\n", stderr="")
        return MagicMock(returncode=0, stdout="pip 22.0", stderr="")
    monkeypatch.setattr(au._sp, "run", fake_run)
    monkeypatch.setattr("shutil.disk_usage", lambda p: MagicMock(free=10 * 1024 * 1024 * 1024))
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _FakeResp(200))
    result = au.health_check()
    assert result.passed is True
    assert any("未提交" in w for w in result.warnings)


def test_health_check_git_command_fails(monkeypatch):
    """Git 命令本身失败时 warning"""
    def fake_run(*a, **k):
        if a and "status" in a[0]:
            raise FileNotFoundError("no git")
        return MagicMock(returncode=0, stdout="pip 22.0", stderr="")
    monkeypatch.setattr(au._sp, "run", fake_run)
    monkeypatch.setattr("shutil.disk_usage", lambda p: MagicMock(free=10 * 1024 * 1024 * 1024))
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _FakeResp(200))
    result = au.health_check()
    assert any("Git 检测失败" in w for w in result.warnings)


def test_health_check_low_disk(monkeypatch):
    """磁盘空间 < 100MB 时 passed=False"""
    monkeypatch.setattr(au._sp, "run", lambda *a, **k: MagicMock(returncode=0, stdout="pip 22.0", stderr=""))
    monkeypatch.setattr("shutil.disk_usage", lambda p: MagicMock(free=50 * 1024 * 1024))  # 50MB
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _FakeResp(200))
    result = au.health_check()
    assert result.passed is False
    assert result.checks["disk"]["ok"] is False
    assert any("磁盘空间不足" in e for e in result.errors)


def test_health_check_disk_oserror(monkeypatch):
    """shutil.disk_usage 抛 OSError 时 disk 检查降级 ok=True"""
    monkeypatch.setattr(au._sp, "run", lambda *a, **k: MagicMock(returncode=0, stdout="pip 22.0", stderr=""))
    import shutil as _shutil
    monkeypatch.setattr("shutil.disk_usage", lambda p: (_ for _ in ()).throw(OSError("no disk")))
    # 但 OSError 捕获后, 走的是 except OSError 分支; shutil.disk_usage 抛 OSError 但 fixture 抛在 try 块内
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _FakeResp(200))
    # 由于 shutil.disk_usage 抛 OSError 不在源码 try 内 - 让我们检查源码
    # 源码: import shutil; free = shutil.disk_usage(...).free
    # 注意 OSError 处理是在 try 块外, disk_usage 在 try 块内
    # 实际源码: try: import shutil; free = shutil.disk_usage(...) ...
    # 所以 OSError 会被 except OSError 捕获
    result = au.health_check()
    assert result.checks["disk"]["ok"] is True
    assert "note" in result.checks["disk"]


def test_health_check_network_failure(monkeypatch):
    """网络不可用时 warning"""
    monkeypatch.setattr(au._sp, "run", lambda *a, **k: MagicMock(returncode=0, stdout="pip 22.0", stderr=""))
    monkeypatch.setattr("shutil.disk_usage", lambda p: MagicMock(free=10 * 1024 * 1024 * 1024))
    def urlopen_err(req, timeout=None):
        raise RuntimeError("net down")
    monkeypatch.setattr("urllib.request.urlopen", urlopen_err)
    result = au.health_check()
    assert result.checks["network"]["ok"] is False
    assert any("网络不可用" in w for w in result.warnings)


class _FakeResp:
    """模拟 urllib response 上下文管理器"""
    def __init__(self, status=200, data=b"{}"):
        self.status = status
        self._data = data
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return None
    def read(self):
        return self._data


# ── _find_project_root ──

def test_find_project_root_with_git(tmp_path, monkeypatch):
    """_find_project_root 优先用 pycoder 包目录的父目录"""
    # pycoder 包所在路径
    import pycoder
    pkg_path = Path(pycoder.__file__).parent
    # pycoder 在 c:\...\pycode\pycoder 下, 父目录是 pycode
    # 真实环境通常 pycode 下有 .git
    root = au._find_project_root()
    assert isinstance(root, Path)


def test_find_project_root_no_git_falls_back_to_cwd(tmp_path, monkeypatch):
    """_find_project_root 在没有 .git 时降级到 cwd"""
    # 创建一个虚拟的 pycoder 模块路径
    monkeypatch.chdir(tmp_path)
    # 创建假 .git 目录使 cwd 路径有效
    (tmp_path / ".git").mkdir()
    # 注: 由于 pycoder 包路径是真实的, _find_project_root 会优先返回 pycoder 父目录
    # 我们改用 monkeypatch 替换 pycoder.__file__ 指向临时路径
    fake_pycoder = MagicMock()
    fake_pycoder.__file__ = str(tmp_path / "fake_pkg" / "pycoder" / "__init__.py")
    monkeypatch.setitem(sys.modules, "pycoder", fake_pycoder)
    root = au._find_project_root()
    # tmp_path 下有 .git, 应返回 tmp_path
    assert root == tmp_path


# ── _create_snapshot ──

def test_create_snapshot_writes_meta(isolated_paths, tmp_path, mock_subprocess):
    """_create_snapshot 创建 SNAPSHOT_DIR 并写入 meta JSON"""
    mock_subprocess.return_value = MagicMock(stdout="abc123\n", stderr="", returncode=0)
    snapshot_id = au._create_snapshot(tmp_path)
    assert snapshot_id  # 非空
    assert isolated_paths["snapshot_dir"].exists()
    meta_file = isolated_paths["snapshot_dir"] / f"{snapshot_id}.json"
    assert meta_file.exists()
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    assert meta["snapshot_id"] == snapshot_id
    assert meta["git_commit"] == "abc123"


def test_create_snapshot_git_fails(isolated_paths, tmp_path, mock_subprocess):
    """git rev-parse 失败时 git_commit='unknown'"""
    mock_subprocess.side_effect = FileNotFoundError("no git")
    snapshot_id = au._create_snapshot(tmp_path)
    meta_file = isolated_paths["snapshot_dir"] / f"{snapshot_id}.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    assert meta["git_commit"] == "unknown"


# ── _rollback_snapshot ──

def test_rollback_snapshot_empty_id():
    """_rollback_snapshot 空 ID 返回 False"""
    assert au._rollback_snapshot("", Path(".")) is False


def test_rollback_snapshot_meta_missing(isolated_paths, tmp_path):
    """快照文件不存在时返回 False"""
    assert au._rollback_snapshot("no-such-id", tmp_path) is False


def test_rollback_snapshot_success(isolated_paths, tmp_path, mock_subprocess):
    """成功回滚: 调用 git reset --hard"""
    # 先创建快照
    mock_subprocess.return_value = MagicMock(stdout="abc123\n", stderr="", returncode=0)
    snapshot_id = au._create_snapshot(tmp_path)
    # 重置 mock 以验证 git reset 调用
    mock_subprocess.reset_mock()
    mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")
    result = au._rollback_snapshot(snapshot_id, tmp_path)
    assert result is True
    # 验证调用了 git reset
    calls = mock_subprocess.call_args_list
    assert any("reset" in str(c) for c in calls)


def test_rollback_snapshot_unknown_commit_skips_reset(isolated_paths, tmp_path, mock_subprocess):
    """git_commit='unknown' 时跳过 git reset 但仍返回 True"""
    mock_subprocess.return_value = MagicMock(stdout="abc123\n", stderr="", returncode=0)
    snapshot_id = au._create_snapshot(tmp_path)
    # 修改 meta 文件使 git_commit 为 unknown
    meta_file = isolated_paths["snapshot_dir"] / f"{snapshot_id}.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    meta["git_commit"] = "unknown"
    meta_file.write_text(json.dumps(meta), encoding="utf-8")
    mock_subprocess.reset_mock()
    result = au._rollback_snapshot(snapshot_id, tmp_path)
    assert result is True
    # 不应调用 git reset
    mock_subprocess.assert_not_called()


def test_rollback_snapshot_exception(isolated_paths, tmp_path, mock_subprocess):
    """rollback 抛异常时返回 False"""
    mock_subprocess.return_value = MagicMock(stdout="abc123\n", stderr="", returncode=0)
    snapshot_id = au._create_snapshot(tmp_path)
    # 让 git reset 抛异常
    mock_subprocess.side_effect = au._sp.SubprocessError("fail")
    result = au._rollback_snapshot(snapshot_id, tmp_path)
    assert result is False


# ── _cleanup_snapshot ──

def test_cleanup_snapshot(isolated_paths, tmp_path, mock_subprocess):
    """_cleanup_snapshot 删除 meta 文件"""
    mock_subprocess.return_value = MagicMock(stdout="abc123\n", stderr="", returncode=0)
    snapshot_id = au._create_snapshot(tmp_path)
    meta_file = isolated_paths["snapshot_dir"] / f"{snapshot_id}.json"
    assert meta_file.exists()
    au._cleanup_snapshot(snapshot_id)
    assert not meta_file.exists()


def test_cleanup_snapshot_missing_file_ok(isolated_paths):
    """清理不存在的文件不抛异常"""
    au._cleanup_snapshot("nonexistent")


def test_cleanup_snapshot_oserror(isolated_paths, tmp_path, mock_subprocess, monkeypatch):
    """_cleanup_snapshot 捕获 OSError (覆盖 line 417-418)"""
    mock_subprocess.return_value = MagicMock(stdout="abc123\n", stderr="", returncode=0)
    snapshot_id = au._create_snapshot(tmp_path)
    # 临时替换 Path.unlink 让它抛 OSError
    from pathlib import Path as _Path
    real_unlink = _Path.unlink
    def raise_oserror(self, *args, **kwargs):
        raise OSError("permission denied")
    monkeypatch.setattr(_Path, "unlink", raise_oserror)
    try:
        # 不应抛异常
        au._cleanup_snapshot(snapshot_id)
    finally:
        monkeypatch.setattr(_Path, "unlink", real_unlink)


# ── run_upgrade ──

def test_run_upgrade_dry_run(isolated_paths, mock_subprocess):
    """dry_run=True 直接返回成功"""
    result = au.run_upgrade(dry_run=True)
    assert result.success is True
    assert result.to_version == "latest"
    assert any(s["step"] == "dry_run" for s in result.steps)
    # 不应调用 git pull
    calls = [str(c) for c in mock_subprocess.call_args_list]
    assert not any("pull" in c for c in calls)


def test_run_upgrade_full_success(isolated_paths, mock_subprocess, tmp_path, monkeypatch):
    """完整升级成功路径"""
    # 让 _find_project_root 返回 tmp_path
    monkeypatch.setattr(au, "_find_project_root", lambda: tmp_path)
    # git rev-parse, git pull, pip install, verify 都成功
    mock_subprocess.side_effect = [
        MagicMock(stdout="abc123\n", stderr="", returncode=0),  # snapshot git rev-parse
        MagicMock(stdout="Already up to date", stderr="", returncode=0),  # git pull
        MagicMock(stdout="Successfully installed", stderr="", returncode=0),  # pip install
        MagicMock(stdout="OK 0.5.0", stderr="", returncode=0),  # verify import
    ]
    result = au.run_upgrade(to_version="9.9.9")
    assert result.success is True
    assert result.to_version == "9.9.9"
    # 应有 5 个步骤
    steps = [s["step"] for s in result.steps]
    assert "snapshot" in steps
    assert "git_pull" in steps
    assert "pip_install" in steps
    assert "verify_import" in steps
    assert "cleanup" in steps


def test_run_upgrade_git_pull_fails(isolated_paths, mock_subprocess, tmp_path, monkeypatch):
    """git pull 失败时触发回滚并返回失败"""
    monkeypatch.setattr(au, "_find_project_root", lambda: tmp_path)
    mock_subprocess.side_effect = [
        MagicMock(stdout="abc123\n", stderr="", returncode=0),  # snapshot rev-parse
        MagicMock(stdout="", stderr="merge conflict", returncode=1),  # git pull fails
    ]
    # mock rollback 避免真实 git 操作
    rollback_called = {"yes": False}
    def fake_rollback(sid, root):
        rollback_called["yes"] = True
        return True
    monkeypatch.setattr(au, "_rollback_snapshot", fake_rollback)
    result = au.run_upgrade()
    assert result.success is False
    assert "Git pull 失败" in result.error
    assert rollback_called["yes"] is True


def test_run_upgrade_git_pull_exception(isolated_paths, mock_subprocess, tmp_path, monkeypatch):
    """git pull 抛异常时触发回滚"""
    monkeypatch.setattr(au, "_find_project_root", lambda: tmp_path)
    mock_subprocess.side_effect = [
        MagicMock(stdout="abc123\n", stderr="", returncode=0),  # snapshot
        au._sp.TimeoutExpired(cmd="git pull", timeout=60),  # git pull 异常
    ]
    monkeypatch.setattr(au, "_rollback_snapshot", lambda sid, root: True)
    result = au.run_upgrade()
    assert result.success is False
    assert "Git pull 异常" in result.error


def test_run_upgrade_pip_install_fails(isolated_paths, mock_subprocess, tmp_path, monkeypatch):
    """pip install 失败时触发回滚"""
    monkeypatch.setattr(au, "_find_project_root", lambda: tmp_path)
    mock_subprocess.side_effect = [
        MagicMock(stdout="abc123\n", stderr="", returncode=0),  # snapshot
        MagicMock(stdout="", stderr="", returncode=0),  # git pull
        MagicMock(stdout="", stderr="dependency error", returncode=1),  # pip install fails
    ]
    monkeypatch.setattr(au, "_rollback_snapshot", lambda sid, root: True)
    result = au.run_upgrade()
    assert result.success is False
    assert "pip install 失败" in result.error


def test_run_upgrade_pip_install_exception(isolated_paths, mock_subprocess, tmp_path, monkeypatch):
    """pip install 抛异常时触发回滚"""
    monkeypatch.setattr(au, "_find_project_root", lambda: tmp_path)
    mock_subprocess.side_effect = [
        MagicMock(stdout="abc123\n", stderr="", returncode=0),  # snapshot
        MagicMock(stdout="", stderr="", returncode=0),  # git pull
        FileNotFoundError("pip not found"),  # pip install 异常
    ]
    monkeypatch.setattr(au, "_rollback_snapshot", lambda sid, root: True)
    result = au.run_upgrade()
    assert result.success is False
    assert "pip install 异常" in result.error


def test_run_upgrade_verify_fails(isolated_paths, mock_subprocess, tmp_path, monkeypatch):
    """验证导入失败时触发回滚"""
    monkeypatch.setattr(au, "_find_project_root", lambda: tmp_path)
    mock_subprocess.side_effect = [
        MagicMock(stdout="abc123\n", stderr="", returncode=0),  # snapshot
        MagicMock(stdout="", stderr="", returncode=0),  # git pull
        MagicMock(stdout="ok", stderr="", returncode=0),  # pip install
        MagicMock(stdout="ImportError", stderr="failed", returncode=1),  # verify fails
    ]
    monkeypatch.setattr(au, "_rollback_snapshot", lambda sid, root: True)
    result = au.run_upgrade()
    assert result.success is False
    assert "导入验证失败" in result.error


def test_run_upgrade_verify_exception(isolated_paths, mock_subprocess, tmp_path, monkeypatch):
    """验证步骤抛异常时触发回滚"""
    monkeypatch.setattr(au, "_find_project_root", lambda: tmp_path)
    mock_subprocess.side_effect = [
        MagicMock(stdout="abc123\n", stderr="", returncode=0),  # snapshot
        MagicMock(stdout="", stderr="", returncode=0),  # git pull
        MagicMock(stdout="ok", stderr="", returncode=0),  # pip install
        RuntimeError("verify crashed"),  # verify 异常
    ]
    monkeypatch.setattr(au, "_rollback_snapshot", lambda sid, root: True)
    result = au.run_upgrade()
    assert result.success is False
    assert "导入验证异常" in result.error


# ── check_pending_on_startup ──

def test_check_pending_no_pending(isolated_paths, monkeypatch):
    """无 pending 时返回 None"""
    monkeypatch.setattr(au, "load_pending_upgrade", lambda: None)
    assert au.check_pending_on_startup() is None


def test_check_pending_resume_init_stage(isolated_paths, monkeypatch):
    """stage=init 时自动重新执行升级"""
    monkeypatch.setattr(au, "load_pending_upgrade", lambda: {
        "stage": "init", "from_version": "1.0", "to_version": "2.0",
        "started_at": "2025-01-01",
    })
    fake_result = au.UpgradeResult(success=True, from_version="1.0", to_version="2.0")
    monkeypatch.setattr(au, "run_upgrade", lambda *a, **k: fake_result)
    clear_called = {"yes": False}
    monkeypatch.setattr(au, "clear_pending_upgrade", lambda: clear_called.__setitem__("yes", True))
    result = au.check_pending_on_startup()
    assert result["status"] == "resumed_and_completed"
    assert clear_called["yes"] is True


def test_check_pending_resume_pip_stage(isolated_paths, monkeypatch):
    """stage=pip_install 时自动重新执行"""
    monkeypatch.setattr(au, "load_pending_upgrade", lambda: {
        "stage": "pip_install", "from_version": "1.0", "to_version": "2.0",
        "started_at": "2025-01-01",
    })
    fake_result = au.UpgradeResult(success=True, from_version="1.0", to_version="2.0")
    monkeypatch.setattr(au, "run_upgrade", lambda *a, **k: fake_result)
    monkeypatch.setattr(au, "clear_pending_upgrade", lambda: None)
    result = au.check_pending_on_startup()
    assert result["status"] == "resumed_and_completed"


def test_check_pending_resume_failed(isolated_paths, monkeypatch):
    """自动升级失败时返回 failed"""
    monkeypatch.setattr(au, "load_pending_upgrade", lambda: {
        "stage": "init", "from_version": "1.0", "to_version": "2.0",
        "started_at": "2025-01-01",
    })
    fake_result = au.UpgradeResult(success=False, from_version="1.0", to_version="2.0", error="boom")
    monkeypatch.setattr(au, "run_upgrade", lambda *a, **k: fake_result)
    result = au.check_pending_on_startup()
    assert result["status"] == "failed"
    assert result["result"].error == "boom"


def test_check_pending_pip_install_stage_failed(isolated_paths, monkeypatch):
    """stage=pip_install 重新执行后失败时返回 failed (覆盖 line 462-463)"""
    monkeypatch.setattr(au, "load_pending_upgrade", lambda: {
        "stage": "pip_install", "from_version": "1.0", "to_version": "2.0",
        "started_at": "2025-01-01",
    })
    fake_result = au.UpgradeResult(success=False, from_version="1.0", to_version="2.0", error="pip failed")
    monkeypatch.setattr(au, "run_upgrade", lambda *a, **k: fake_result)
    result = au.check_pending_on_startup()
    assert result["status"] == "failed"
    assert result["result"].error == "pip failed"


def test_check_pending_verify_import_stage_failed(isolated_paths, monkeypatch):
    """stage=verify_import 重新执行后失败时返回 failed"""
    monkeypatch.setattr(au, "load_pending_upgrade", lambda: {
        "stage": "verify_import", "from_version": "1.0", "to_version": "2.0",
        "started_at": "2025-01-01",
    })
    fake_result = au.UpgradeResult(success=False, from_version="1.0", to_version="2.0", error="verify failed")
    monkeypatch.setattr(au, "run_upgrade", lambda *a, **k: fake_result)
    result = au.check_pending_on_startup()
    assert result["status"] == "failed"


def test_check_pending_done_stage_cleaned(isolated_paths, monkeypatch):
    """stage=done 时清理残留返回 cleaned"""
    monkeypatch.setattr(au, "load_pending_upgrade", lambda: {
        "stage": "done", "from_version": "1.0", "to_version": "2.0",
        "started_at": "2025-01-01",
    })
    clear_called = {"yes": False}
    monkeypatch.setattr(au, "clear_pending_upgrade", lambda: clear_called.__setitem__("yes", True))
    result = au.check_pending_on_startup()
    assert result["status"] == "cleaned"
    assert clear_called["yes"] is True


# ── get_snapshot_diff ──

def test_get_snapshot_diff_missing(isolated_paths, tmp_path):
    """快照不存在时返回 error"""
    result = au.get_snapshot_diff("no-such-id")
    assert "error" in result
    assert "快照不存在" in result["error"]


def test_get_snapshot_diff_unknown_commit(isolated_paths, tmp_path, mock_subprocess):
    """git_commit='unknown' 时返回无法计算差异"""
    mock_subprocess.return_value = MagicMock(stdout="abc123\n", stderr="", returncode=0)
    snapshot_id = au._create_snapshot(tmp_path)
    meta_file = isolated_paths["snapshot_dir"] / f"{snapshot_id}.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    meta["git_commit"] = "unknown"
    meta_file.write_text(json.dumps(meta), encoding="utf-8")
    result = au.get_snapshot_diff(snapshot_id)
    assert "无法计算差异" in result["diff"]


def test_get_snapshot_diff_success(isolated_paths, tmp_path, mock_subprocess, monkeypatch):
    """成功获取差异"""
    monkeypatch.setattr(au, "_find_project_root", lambda: tmp_path)
    mock_subprocess.return_value = MagicMock(stdout="abc123\n", stderr="", returncode=0)
    snapshot_id = au._create_snapshot(tmp_path)
    # mock 后续的 git diff 调用
    mock_subprocess.side_effect = [
        # get_snapshot_diff 内部 2 次 git diff + 1 次 _get_current_commit 内 git rev-parse
        MagicMock(stdout="1 file changed", stderr="", returncode=0),
        MagicMock(stdout="file1.py\nfile2.py\n", stderr="", returncode=0),
        MagicMock(stdout="def456\n", stderr="", returncode=0),
    ]
    result = au.get_snapshot_diff(snapshot_id)
    assert result["snapshot_id"] == snapshot_id
    assert "file1.py" in result["changed_files"]
    assert result["total_changes"] == 2
    assert "stat" in result


def test_get_snapshot_diff_exception(isolated_paths, tmp_path, mock_subprocess, monkeypatch):
    """git diff 异常时返回 error"""
    monkeypatch.setattr(au, "_find_project_root", lambda: tmp_path)
    mock_subprocess.return_value = MagicMock(stdout="abc123\n", stderr="", returncode=0)
    snapshot_id = au._create_snapshot(tmp_path)
    mock_subprocess.side_effect = RuntimeError("git diff boom")
    result = au.get_snapshot_diff(snapshot_id)
    assert "error" in result
    assert "git diff boom" in result["error"]


# ── _get_current_commit ──

def test_get_current_commit_success(tmp_path, mock_subprocess):
    mock_subprocess.return_value = MagicMock(stdout="abcdef1234\n", stderr="", returncode=0)
    assert au._get_current_commit(tmp_path) == "abcdef12"


def test_get_current_commit_exception(tmp_path, mock_subprocess):
    mock_subprocess.side_effect = FileNotFoundError("no git")
    assert au._get_current_commit(tmp_path) == "unknown"


# ── get_upgrade_status ──

def test_get_upgrade_status(isolated_paths, monkeypatch):
    """get_upgrade_status 返回完整状态字典"""
    monkeypatch.setattr(au, "load_pending_upgrade", lambda: {"stage": "init"})
    # SNAPSHOT_DIR 不存在 → snapshots=[]
    # check_version 返回 mock
    fake_vi = au.VersionInfo(current="1.0", latest="2.0", has_update=True)
    monkeypatch.setattr(au, "check_version", lambda: fake_vi)
    status = au.get_upgrade_status()
    assert status["current_version"] is not None
    assert status["latest_version"] == "2.0"
    assert status["has_update"] is True
    assert status["pending_upgrade"] == {"stage": "init"}
    assert status["snapshots_count"] == 0
    assert status["snapshots"] == []


def test_get_upgrade_status_with_snapshots(isolated_paths, tmp_path, mock_subprocess, monkeypatch):
    """get_upgrade_status 列出快照"""
    monkeypatch.setattr(au, "_find_project_root", lambda: tmp_path)
    mock_subprocess.return_value = MagicMock(stdout="abc123\n", stderr="", returncode=0)
    # 创建 2 个快照
    sid1 = au._create_snapshot(tmp_path)
    sid2 = au._create_snapshot(tmp_path)
    monkeypatch.setattr(au, "load_pending_upgrade", lambda: None)
    fake_vi = au.VersionInfo(current="1.0", latest="2.0", has_update=True)
    monkeypatch.setattr(au, "check_version", lambda: fake_vi)
    status = au.get_upgrade_status()
    assert status["snapshots_count"] == 2
    assert len(status["snapshots"]) == 2


def test_get_upgrade_status_check_version_fails(monkeypatch, isolated_paths):
    """check_version 抛连接异常时降级"""
    monkeypatch.setattr(au, "load_pending_upgrade", lambda: None)
    def boom():
        raise ConnectionError("api down")
    monkeypatch.setattr(au, "check_version", boom)
    status = au.get_upgrade_status()
    assert status["latest_version"] == "未知"
    assert status["has_update"] is False


def test_get_upgrade_status_with_corrupt_snapshot(isolated_paths, monkeypatch, tmp_path):
    """SNAPSHOT_DIR 包含损坏的快照文件时跳过 (覆盖 line 528-529)"""
    # 创建一个损坏的 JSON 快照文件
    isolated_paths["snapshot_dir"].mkdir(parents=True, exist_ok=True)
    bad_file = isolated_paths["snapshot_dir"] / "bad_20250101.json"
    bad_file.write_text("not json{", encoding="utf-8")
    monkeypatch.setattr(au, "load_pending_upgrade", lambda: None)
    fake_vi = au.VersionInfo(current="1.0", latest="2.0", has_update=True)
    monkeypatch.setattr(au, "check_version", lambda: fake_vi)
    status = au.get_upgrade_status()
    # 损坏文件被跳过, snapshots 为空
    assert status["snapshots_count"] == 0
    assert status["snapshots"] == []


def test_find_project_root_no_git_anywhere(tmp_path, monkeypatch):
    """_find_project_root 没有 .git 时返回 pycoder 父目录 (覆盖 line 367)"""
    # 用一个临时路径模拟 pycoder 包位置
    fake_pkg_dir = tmp_path / "fake_pycoder_pkg" / "pycoder"
    fake_pkg_dir.mkdir(parents=True)
    (fake_pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    fake_pycoder = MagicMock()
    fake_pycoder.__file__ = str(fake_pkg_dir / "__init__.py")
    monkeypatch.setitem(sys.modules, "pycoder", fake_pycoder)
    monkeypatch.chdir(tmp_path)  # cwd 也没有 .git
    root = au._find_project_root()
    # 返回 pycoder 父目录 (没有 .git 时的最后 fallback)
    assert root == fake_pkg_dir.parent
